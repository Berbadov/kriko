"""Updating a pack over HTTP, end to end, against a real local server.

Mocking the fetch here would test almost nothing: the interesting parts are
that the download is verified before it is installed, that a republished
version is refused rather than installed, and that an unreachable index is an
answer instead of a 500. All three are about what actually crosses the wire.
"""

import hashlib
import json
from dataclasses import replace
import textwrap
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.tests.test_web import PACK
from app.web.app import create_app
from app.web.settings import Settings
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect


#: A claim the newer build knows and the installed one does not. Without it the
#: two builds would carry the same content_digest and `decide` would rightly
#: call the newer version a renumber of the same knowledge.
EXTRA_CLAIM = """
        - subject: {kind: product, identity: {brand: acme, model: orphan}}
          kind: known_issue
          domain: mech
          severity: low
          text: {en: {title: Chuck slips under load, body: b, advice: a}}
          evidence:
            - {url: "https://h.invalid/w", quote: Slipped on the third hole.}
"""


def write_pack(root, version="0.2.0", extra=False):
    for sub in ("vocabulary", "data", "research"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    toml = textwrap.dedent(PACK["toml"]).replace('version = "0.2.0"', f'version = "{version}"')
    (root / "pack.toml").write_text(toml, encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(
        textwrap.dedent(PACK["terms"]), encoding="utf-8"
    )
    (root / "data" / "subjects.yaml").write_text(
        textwrap.dedent(PACK["subjects"]), encoding="utf-8"
    )
    claims = textwrap.dedent(PACK["claims"] + (EXTRA_CLAIM if extra else ""))
    (root / "data" / "claims.yaml").write_text(claims, encoding="utf-8")
    (root / "research" / "principle.md").write_text("Only the expensive.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n', encoding="utf-8")
    return root


@pytest.fixture
def serve(tmp_path):
    """A directory served over real HTTP, so urllib does its actual job."""
    published = tmp_path / "published"
    published.mkdir()
    handler = partial(SimpleHTTPRequestHandler, directory=str(published))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield published, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def publish(published, base, artifact, version, digest_override=None):
    target = published / artifact.name
    target.write_bytes(artifact.read_bytes())
    conn = connect(target)
    content_digest = conn.execute("SELECT content_digest FROM packs").fetchone()[0]
    conn.close()
    index = {
        "packs": [
            {
                "pack_id": "tools",
                "name": "Tools",
                "version": version,
                "url": f"{base}/{target.name}",
                "content_digest": digest_override or content_digest,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "size": target.stat().st_size,
            }
        ]
    }
    (published / "packs.json").write_text(json.dumps(index), encoding="utf-8")
    return f"{base}/packs.json"


@pytest.fixture
def client(tmp_path):
    store_path = tmp_path / "store.sqlite"
    installed = build.build(write_pack(tmp_path / "v1", "0.2.0"), tmp_path / "v1.kpack")
    conn = connect(store_path)
    packstore.install(conn, installed)
    conn.commit()
    conn.close()
    tc = TestClient(
        create_app(
            Settings(store_path=store_path, app_state_path=tmp_path / "app.sqlite")
        )
    )
    tc.store_path = store_path
    return tc


def run(client, **body):
    """Start an update job and drain it — the worker is a single thread."""
    started = client.post("/api/packs/update", json=body)
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]
    for _ in range(600):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("succeeded", "failed", "cancelled"):
            return job
        threading.Event().wait(0.05)
    raise AssertionError("job never finished")


def test_a_newer_version_is_offered_then_installed(client, serve, tmp_path):
    published, base = serve
    newer = build.build(write_pack(tmp_path / "v2", "0.3.0", extra=True), tmp_path / "v2.kpack")
    index = publish(published, base, newer, "0.3.0")

    check = client.get("/api/packs/updates", params={"index_url": index}).json()
    assert check["error"] is None
    row = next(p for p in check["packs"] if p["pack_id"] == "tools")
    assert (row["state"], row["installed_version"], row["offered_version"]) == (
        "available",
        "0.2.0",
        "0.3.0",
    )

    with client:
        job = run(client, index_url=index)
    assert job["state"] == "succeeded", job
    assert job["result"]["updated"] == [
        {"pack_id": "tools", "version": "0.3.0", "from": "0.2.0"}
    ]

    conn = connect(client.store_path)
    assert conn.execute("SELECT version FROM packs").fetchone()[0] == "0.3.0"
    conn.close()


def test_the_same_version_is_reported_up_to_date_and_downloads_nothing(client, serve, tmp_path):
    published, base = serve
    same = build.build(write_pack(tmp_path / "v1b", "0.2.0"), tmp_path / "v1b.kpack")
    index = publish(published, base, same, "0.2.0")

    row = client.get("/api/packs/updates", params={"index_url": index}).json()["packs"][0]
    assert row["state"] == "up_to_date"
    with client:
        job = run(client, index_url=index)
    assert job["result"]["updated"] == []


def test_a_republished_version_is_refused_before_anything_is_downloaded(client, serve, tmp_path):
    published, base = serve
    same = build.build(write_pack(tmp_path / "v1c", "0.2.0"), tmp_path / "v1c.kpack")
    index = publish(published, base, same, "0.2.0", digest_override="pretend-different")

    row = client.get("/api/packs/updates", params={"index_url": index}).json()["packs"][0]
    assert row["state"] == "refused"
    assert "may not be republished" in row["reason"]
    with client:
        job = run(client, index_url=index)
    # Refused is not actionable, so the job finds nothing to do rather than
    # downloading a file the store would then reject.
    assert job["result"]["updated"] == []


def test_a_corrupted_download_never_reaches_the_store(client, serve, tmp_path):
    published, base = serve
    newer = build.build(write_pack(tmp_path / "v2b", "0.3.0", extra=True), tmp_path / "v2b.kpack")
    index = publish(published, base, newer, "0.3.0")
    # Truncate the published file after the index promised its hash.
    served = published / newer.name
    served.write_bytes(served.read_bytes()[: len(served.read_bytes()) // 2])

    with client:
        job = run(client, index_url=index)
    assert job["state"] == "failed"
    assert "sha256" in job["message"]
    conn = connect(client.store_path)
    assert conn.execute("SELECT version FROM packs").fetchone()[0] == "0.2.0"
    conn.close()
    assert not list((tmp_path).glob("downloads/*"))


def test_an_unreachable_index_is_an_answer_not_a_500(client):
    body = client.get(
        "/api/packs/updates", params={"index_url": "http://127.0.0.1:9/none.json"}
    ).json()
    assert body["error"]
    assert body["packs"][0]["state"] == "unknown"


def test_naming_a_pack_the_index_does_not_carry_fails_loudly(client, serve, tmp_path):
    published, base = serve
    newer = build.build(write_pack(tmp_path / "v2c", "0.3.0", extra=True), tmp_path / "v2c.kpack")
    index = publish(published, base, newer, "0.3.0")
    with client:
        job = run(client, index_url=index, pack_id="nosuch")
    assert job["state"] == "failed"
    assert "nosuch" in job["message"]


def test_a_pack_that_is_not_installed_yet_is_offered(tmp_path, serve):
    """A fresh install has an empty store; the first update is the first pack."""
    published, base = serve
    artifact = build.build(write_pack(tmp_path / "fresh", "0.3.0", extra=True), tmp_path / "f.kpack")
    index = publish(published, base, artifact, "0.3.0")
    store_path = tmp_path / "empty.sqlite"
    connect(store_path).close()
    client = TestClient(
        create_app(
            Settings(store_path=store_path, app_state_path=tmp_path / "app2.sqlite")
        )
    )
    client.store_path = store_path
    row = client.get("/api/packs/updates", params={"index_url": index}).json()["packs"][0]
    assert row["state"] == "not_installed"
    with client:
        job = run(client, index_url=index)
    assert job["result"]["updated"][0]["pack_id"] == "tools"


def test_a_non_http_pack_url_is_refused(client, serve, tmp_path):
    published, base = serve
    (published / "packs.json").write_text(
        json.dumps(
            {"packs": [{"pack_id": "tools", "version": "9.0.0",
                        "url": f"file://{tmp_path}/v1.kpack"}]}
        ),
        encoding="utf-8",
    )
    with client:
        job = run(client, index_url=f"{base}/packs.json")
    assert job["state"] == "failed"
    assert "non-http" in job["message"]


# ── B166: no Updates block, so the app installs updates itself ───────────

def _version(client):
    conn = connect(client.store_path)
    try:
        return conn.execute("SELECT version FROM packs WHERE pack_id='tools'").fetchone()[0]
    finally:
        conn.close()


def _wait(client, job_id):
    for _ in range(600):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in ("succeeded", "failed", "cancelled"):
            return job
        threading.Event().wait(0.05)
    raise AssertionError("job never finished")


def _pointed_at(client, index_url):
    settings = replace(client.app.state.settings, pack_index_url=index_url)
    client.app.state.jobs.settings = settings
    return settings, client.app.state.jobs


def test_an_available_update_installs_without_a_click(client, serve, tmp_path):
    from app import packautoupdate

    published, base = serve
    newer = build.build(write_pack(tmp_path / "v2", "0.3.0", extra=True), tmp_path / "v2.kpack")
    settings, runner = _pointed_at(client, publish(published, base, newer, "0.3.0"))

    job_id = packautoupdate.submit_if_due(settings, runner)
    assert job_id, "a never-checked install is due"
    assert _wait(client, job_id)["state"] == "succeeded"
    assert _version(client) == "0.3.0"
    # A success is remembered, so the next launch inside the week does nothing.
    assert packautoupdate.submit_if_due(settings, runner) is None


def test_the_automatic_pass_does_not_reinstall_an_uninstalled_pack(client, serve, tmp_path):
    from app import packautoupdate

    published, base = serve
    newer = build.build(write_pack(tmp_path / "v2", "0.3.0", extra=True), tmp_path / "v2.kpack")
    settings, runner = _pointed_at(client, publish(published, base, newer, "0.3.0"))
    assert client.delete("/api/packs/tools").status_code == 200

    assert _wait(client, packautoupdate.submit_if_due(settings, runner))["state"] == "succeeded"
    conn = connect(client.store_path)
    try:
        assert conn.execute("SELECT count(*) FROM packs").fetchone()[0] == 0
    finally:
        conn.close()


def test_an_unreachable_index_is_asked_again_at_the_next_launch(client):
    from app import packautoupdate

    settings, runner = _pointed_at(client, "http://127.0.0.1:9/packs.json")

    assert _wait(client, packautoupdate.submit_if_due(settings, runner))["state"] == "failed"
    assert packautoupdate.submit_if_due(settings, runner), "a failed pass must not count as a check"
