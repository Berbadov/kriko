"""Getting the browser extension installed, from the app's side.

The install itself is three clicks in a browser that no application is allowed
to perform. What the app owes the reader is everything around them: files in a
path that survives an update, and an honest answer to "did it work?" — and the
second one is the part with teeth, because the failure it replaces (a working
install that silently reaches nothing) looks identical to a bad install.
"""

import json
import re

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
    # The allowlist is a *list*, so what it keeps out is only ever what
    # somebody remembered. This asserts the shape instead: nothing lands that
    # `SHIPPED` does not name, which holds for the next file too.
    assert landed <= set(extension.SHIPPED), (
        f"staged files nobody listed: {sorted(landed - set(extension.SHIPPED))}"
    )


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


def test_a_stale_sighting_still_counts_as_ever_installed(tmp_path):
    """B85: `connected` is a live badge, not an install record.

    A reader who has not opened a listing in the last FRESH_SECENDS goes
    stale on the badge — correctly, that badge is about right now. But an
    onboarding hint keyed on the same field would tell someone whose history
    is full of extension-sourced answers to go add the extension again.
    `ever_connected` is the field that must not go false just because nobody
    has browsed a listing recently: it looks at whether a sighting exists at
    all, never at its age.
    """
    from datetime import datetime, timedelta, timezone

    from app.web import state
    from app.web.routers.extension import FRESH_SECONDS

    client = _client(tmp_path)
    client.get("/api/health", headers={"origin": "chrome-extension://abcdefg"})

    # Back-date the sighting past the freshness window without touching the
    # sightings row's existence — the thing `ever_connected` must survive.
    conn = state.connect(tmp_path / "app.sqlite")
    old = (
        datetime.now(timezone.utc) - timedelta(seconds=FRESH_SECONDS + 60)
    ).isoformat()
    conn.execute("UPDATE extension_seen SET last_at = ?", (old,))
    conn.commit()
    conn.close()

    body = client.get("/api/extension").json()
    assert body["connected"] is False
    assert body["ever_connected"] is True


def test_never_seen_is_not_ever_connected(tmp_path):
    """The other half: no sighting at all must still read as never installed,
    or the onboarding hint would never offer to add the extension."""
    assert _client(tmp_path).get("/api/extension").json()["ever_connected"] is False


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
    if manifest.get("options_ui", {}).get("page"):
        referenced.add(manifest["options_ui"]["page"])

    client = _client(tmp_path)
    client.post("/api/extension/stage")
    missing = [
        path for path in sorted(referenced) if not (tmp_path / "extension" / path).exists()
    ]
    assert missing == [], (
        f"manifest.json references {missing}, which app.extension.SHIPPED does "
        f"not carry — the browser would refuse to load the staged folder"
    )


def test_a_staged_page_can_load_everything_it_asks_for(tmp_path):
    """One step past the manifest, and for the same reason.

    An HTML page in the extension pulls its own script and stylesheet, and
    neither is named in `manifest.json` — so the allowlist can carry the page
    and leave its two halves behind, which renders as an options screen that
    silently does nothing. Derived from the staged files rather than listed
    here, so a page added later is covered the moment it exists.
    """
    client = _client(tmp_path)
    client.post("/api/extension/stage")
    staged = tmp_path / "extension"

    broken = []
    for page in sorted(staged.rglob("*.html")):
        text = page.read_text("utf-8")
        for ref in re.findall(r'(?:src|href)="([^"#?:]+)"', text):
            if ref.startswith("/"):
                continue
            if not (page.parent / ref).exists():
                broken.append(f"{page.relative_to(staged)} → {ref}")
    assert broken == [], (
        f"staged pages reference files that were not shipped: {broken}"
    )
