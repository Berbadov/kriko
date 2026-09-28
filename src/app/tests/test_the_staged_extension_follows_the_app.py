"""B151: an app update left Chrome running the extension from two releases ago.

The reader's words: *"we are not reading enough data from the page to identify
the product."* The page's facts never left the browser: the app carried a
`background.js` that sends them, and the folder Chrome loads still held the
one that does not. Both reported the same version, so `/api/extension` said
"current".

Now the app restages a folder the reader already staged when its files are
not the ones it carries, tells the extension the staged digest on every
answer, and says `stale_files` while the browser still runs the old ones.
"""

import pytest
from fastapi.testclient import TestClient

from app import extension
from app.web.app import create_app
from app.web.settings import Settings

ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv("KRIKO_EXTENSION_DIR", raising=False)
    return tmp_path


def _app(home):
    return create_app(Settings.from_env(
        store_path=home / "knowledge.sqlite",
        app_state_path=home / "app.sqlite",
        analysis_log_path=home / "analyses.jsonl",
    ))


def _stage_an_old_copy(home):
    target = extension.staged_dir(home)
    extension.stage(extension.source_dir(), target)
    background = target / "background.js"
    background.write_text(background.read_text(encoding="utf-8") + "\n// older\n",
                          encoding="utf-8")
    return target


def _seen(client, digest):
    client.get("/api/health", headers={
        "origin": ORIGIN,
        extension.VERSION_HEADER: extension.version(extension.source_dir()),
        extension.DIGEST_HEADER: digest})


def test_an_app_update_restages_the_folder_the_browser_loads(home):
    target = _stage_an_old_copy(home)
    carried = extension.content_digest(extension.source_dir())
    assert extension.content_digest(target) != carried
    with TestClient(_app(home)) as client:
        assert extension.content_digest(target) == carried
        answer = client.get("/api/health", headers={"origin": ORIGIN})
        assert answer.headers[extension.STAGED_HEADER] == carried


def test_a_reader_who_never_staged_is_not_staged_for(home):
    with TestClient(_app(home)) as client:
        assert not extension.staged_dir(home).exists()
        answer = client.get("/api/health", headers={"origin": ORIGIN})
        assert extension.STAGED_HEADER not in answer.headers


def test_same_version_older_files_is_not_current(home):
    _stage_an_old_copy(home)
    with TestClient(_app(home)) as client:
        _seen(client, "a" * 64)
        state = client.get("/api/extension").json()["compatibility"]
        assert state["state"] == "stale_files", state
        assert "reloads itself" in state["detail"]


def test_the_same_files_are_current(home):
    _stage_an_old_copy(home)
    with TestClient(_app(home)) as client:
        _seen(client, extension.content_digest(extension.source_dir()))
        assert client.get("/api/extension").json()["compatibility"]["state"] == "current"
