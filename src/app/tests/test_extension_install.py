"""Getting the browser extension installed, from the app's side.

The install itself is three clicks in a browser that no application is allowed
to perform. What the app owes the reader is everything around them: files in a
path that survives an update, and an honest answer to "did it work?" — and the
second one is the part with teeth, because the failure it replaces (a working
install that silently reaches nothing) looks identical to a bad install.
"""

import json

from fastapi.testclient import TestClient

from app import extension
from app.web.app import create_app
from app.web.settings import EXTENSION_PORT, Settings


def _client(tmp_path, **over):
    return TestClient(
        create_app(
            Settings(
                store_path=tmp_path / "knowledge.sqlite",
                app_state_path=tmp_path / "app.sqlite",
                analysis_log_path=tmp_path / "analyses.jsonl",
                **over,
            )
        )
    )


def test_the_files_land_beside_the_store_not_inside_the_install(tmp_path):
    """A browser remembers an unpacked extension by path.

    Staging into the install directory would therefore uninstall the extension
    on every app update — the next installer replaces that directory wholesale
    and the browser finds nothing where it was told to look. `~/.kriko` is the
    same reasoning that put the two SQLite files there.
    """
    client = _client(tmp_path)
    body = client.post("/api/extension/stage").json()

    assert body["path"] == str(tmp_path / "extension")
    assert (tmp_path / "extension" / "manifest.json").is_file()
    assert (tmp_path / "extension" / "hover_lite" / "hover_lite.css").is_file()


def test_staging_ships_only_what_a_browser_loads(tmp_path):
    """`extension/tests/` is not the extension.

    An allowlist rather than a directory copy, because a folder full of files
    Chrome ignores invites the reader to wonder which one is the broken part.
    """
    client = _client(tmp_path)
    client.post("/api/extension/stage")
    landed = {p.name for p in (tmp_path / "extension").iterdir()}

    assert "manifest.json" in landed
    assert "tests" not in landed
    assert "colors_and_type.css" not in landed


def test_staging_again_removes_what_the_extension_stopped_shipping(tmp_path):
    """Replace, never merge: a stale file the browser still loads is worse
    than a missing one, because it works."""
    client = _client(tmp_path)
    client.post("/api/extension/stage")
    stale = tmp_path / "extension" / "leftover.js"
    stale.write_text("// from an older version")

    client.post("/api/extension/stage")

    assert not stale.exists()
    assert (tmp_path / "extension" / "manifest.json").is_file()


def test_an_extension_origin_is_recorded_as_evidence_it_is_running(tmp_path):
    """The only proof the app can have, and it cannot be faked by a setting.

    Nothing on the machine but a browser can put `chrome-extension://` in an
    Origin header, and the extension only sends one while doing its actual job.
    So a sighting means installed *and* running *and* able to reach this
    process — the three things a reader cannot check for themselves.
    """
    client = _client(tmp_path)
    assert client.get("/api/extension").json()["connected"] is False

    client.get("/api/health", headers={"origin": "chrome-extension://abcdefg"})

    body = client.get("/api/extension").json()
    assert body["connected"] is True
    assert body["seconds_since_seen"] < 60
    assert [row["origin"] for row in body["sightings"]] == ["chrome-extension://abcdefg"]


def test_two_browser_profiles_are_two_rows(tmp_path):
    """Each install gets its own id, and "which of my browsers is wired up"
    is the question that follows the first one."""
    client = _client(tmp_path)
    client.get("/api/health", headers={"origin": "chrome-extension://one"})
    client.get("/api/health", headers={"origin": "moz-extension://two"})
    client.get("/api/health", headers={"origin": "chrome-extension://one"})

    rows = {row["origin"]: row["hits"] for row in client.get("/api/extension").json()["sightings"]}
    assert rows == {"chrome-extension://one": 2, "moz-extension://two": 1}


def test_an_ordinary_request_is_not_a_sighting(tmp_path):
    """The window itself calls these endpoints constantly. Counting those
    would make the page say "connected" to someone with no extension at all."""
    client = _client(tmp_path)
    client.get("/api/health")
    client.get("/api/health", headers={"origin": "http://localhost:5173"})

    assert client.get("/api/extension").json()["sightings"] == []


def test_the_page_is_told_when_the_extension_port_is_not_ours(tmp_path):
    """The extension cannot be handed a port, so it hardcodes one.

    When something else on the machine holds it, the extension installs
    perfectly and fails on every listing — and the reader's obvious response,
    reinstalling the extension, never helps. The app knows; it has to say.
    """
    assert _client(tmp_path).get("/api/extension").json()["port"] == EXTENSION_PORT
    assert _client(tmp_path).get("/api/extension").json()["port_is_ours"] is False
    assert (
        _client(tmp_path, extension_port_bound=True).get("/api/extension").json()[
            "port_is_ours"
        ]
        is True
    )


def test_revealing_before_staging_is_refused_rather_than_opening_nothing(tmp_path):
    assert _client(tmp_path).post("/api/extension/reveal").status_code == 409


def test_the_shipped_list_matches_what_the_manifest_actually_references(tmp_path):
    """The allowlist is a hand-written list, which is exactly the kind that
    goes stale. This reads the manifest and checks nothing it names was left
    behind — so adding a content script to the extension cannot silently ship
    an extension the browser refuses to load."""
    source = extension.source_dir()
    assert source is not None
    manifest = json.loads((source / "manifest.json").read_text("utf-8"))

    referenced = set()
    for script in manifest.get("content_scripts", []):
        referenced.update(script.get("js", []))
    referenced.add(manifest["background"]["service_worker"])
    for resource in manifest.get("web_accessible_resources", []):
        referenced.update(resource.get("resources", []))
    referenced.update(manifest.get("icons", {}).values())

    client = _client(tmp_path)
    client.post("/api/extension/stage")
    missing = [
        path for path in sorted(referenced) if not (tmp_path / "extension" / path).exists()
    ]
    assert missing == [], (
        f"manifest.json references {missing}, which app.extension.SHIPPED does "
        f"not carry — the browser would refuse to load the staged folder"
    )
