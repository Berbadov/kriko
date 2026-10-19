from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings

def test_root_identifies_the_native_app_and_api(tmp_path):
    # `app_state_path` too, not just `store_path`: `create_app` builds the job
    # runner, which opens the job ledger, and the default is the *reader's own*
    # `~/.kriko/app.sqlite`. This test used to believe it was isolated while
    # running `CREATE TABLE IF NOT EXISTS` against the real history file.
    client = TestClient(create_app(Settings(store_path=tmp_path / "k.sqlite",
                                            app_state_path=tmp_path / "app.sqlite")))
    assert client.get("/").json() == {
        "app": "Kriko", "desktop": "Tauri", "service": "local API",
        "health": "/api/health", "docs": "/api/docs",
    }
    assert client.get("/api/docs").status_code == 200
