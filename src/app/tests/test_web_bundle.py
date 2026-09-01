"""The committed bundle is what `python -m app.web` actually serves.

`ui/` is the source; `src/app/web/static/` is build output under version control,
so that `pip install kriko` needs no Node and a clean checkout serves a working
UI. These tests fail when the two drift apart in the ways that matter.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


def test_index_is_the_svelte_bundle(tmp_path):
    client = TestClient(create_app(Settings(store_path=tmp_path / "k.sqlite")))
    body = client.get("/").text
    assert '<div id="app">' in body, "index.html is not the Svelte mount point"
    assert "/static/assets/" in body, "index.html references no built asset"


def test_built_assets_are_committed():
    assets = STATIC / "assets"
    assert assets.is_dir(), f"{assets} missing — run: npm --prefix ui run build"
    assert any(assets.glob("*.js")), "no built JS in the committed bundle"
