from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings

def test_root_identifies_the_native_app_and_api(tmp_path):
    client = TestClient(create_app(Settings(store_path=tmp_path / "k.sqlite")))
    assert client.get("/").json() == {
        "app": "Kriko", "desktop": "GPUI", "service": "local API",
        "health": "/api/health", "docs": "/api/docs",
    }
    assert client.get("/api/docs").status_code == 200
