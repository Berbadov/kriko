import json
import re
import zipfile

from fastapi.testclient import TestClient

from app import extension
from app.web.app import create_app
from app.web.settings import Settings


def app(home):
    return create_app(Settings(store_path=home / "knowledge.sqlite",
        app_state_path=home / "app.sqlite", analysis_log_path=home / "analyses.jsonl"))


def test_firefox_bundle_is_separate_and_loadable(tmp_path, monkeypatch):
    monkeypatch.delenv("KRIKO_EXTENSION_DIR", raising=False)
    with TestClient(app(tmp_path)) as client:
        assert not client.get("/api/extension").json()["firefox"]["staged"]
        chromium = client.post("/api/extension/stage").json()
        chrome_manifest = (tmp_path / "extension/manifest.json").read_bytes()
        chrome_digest = chromium["content_digest"]
        response = client.post("/api/extension/firefox/stage")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["signed"] is False
        folder = tmp_path / "extension-firefox"
        manifest = json.loads((folder / "manifest.json").read_bytes())
        assert manifest["background"] == {"scripts": ["background.js"]}
        gecko = manifest["browser_specific_settings"]["gecko"]
        assert gecko["id"] == "kriko@kriko.local"
        assert gecko["strict_min_version"] == "140.0"
        assert gecko["data_collection_permissions"]["required"] == ["browsingActivity", "websiteContent"]
        assert "use_dynamic_url" not in manifest["web_accessible_resources"][0]
        with zipfile.ZipFile(body["package_path"]) as archive:
            assert json.loads(archive.read("manifest.json")) == manifest
            assert "background.js" in archive.namelist()
            assert not any("tests" in name for name in archive.namelist())
        assert (tmp_path / "extension/manifest.json").read_bytes() == chrome_manifest
        assert extension.content_digest(tmp_path / "extension") == chrome_digest
        digest = extension.content_digest(folder)
        assert digest == extension.content_digest(extension.source_dir(), "firefox")
        stamp = re.search(r'LOADED_CONTENT_DIGEST = "([a-f0-9]+)"', (folder / "background.js").read_text(encoding="utf-8")).group(1)
        assert stamp == digest != chrome_digest
        for origin, expected in [("moz-extension://test-addon", digest),
                ("chrome-extension://test-addon", chrome_digest)]:
            answer = client.get("/api/health", headers={"origin": origin,
                extension.VERSION_HEADER: body["version"], extension.DIGEST_HEADER: expected})
            assert answer.headers[extension.STAGED_HEADER] == expected
            assert client.get("/api/extension").json()["compatibility"]["state"] == "current"


def test_firefox_update_refreshes_only_a_prepared_addon(tmp_path, monkeypatch):
    monkeypatch.delenv("KRIKO_EXTENSION_DIR", raising=False)
    target = extension.target_for(tmp_path / "knowledge.sqlite", "firefox")
    with TestClient(app(tmp_path)):
        assert not target.exists()
    extension.stage(extension.source_dir(), target, "firefox")
    with (target / "background.js").open("a", encoding="utf-8") as stream:
        stream.write("\n// old file")
    with TestClient(app(tmp_path)) as client:
        status = client.get("/api/extension").json()
        assert status["firefox"]["staged"]
        assert extension.content_digest(target) == extension.content_digest(extension.source_dir(), "firefox")
        assert target.with_suffix(".xpi").is_file()
        assert not (tmp_path / "extension").exists()
