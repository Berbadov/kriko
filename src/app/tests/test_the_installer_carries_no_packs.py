"""#169: the installer carries no packs, and a fresh store starts empty.

A pre-made pack in the installer put a catalog the reader never chose into
their store, and one a later release could quietly overwrite. So nothing is
carried: the spec freezes no `.kpack`, no build step makes one for the
installer, and startup installs none. A pack reaches a store only when the
reader installs it, or through the weekly update of a pack already installed.
"""

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings

REPO = Path(__file__).resolve().parents[3]


def test_a_fresh_store_starts_with_no_packs(tmp_path):
    settings = Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )

    # Entering the client runs the lifespan, which is what used to seed.
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/packs").json() == []


def test_the_seeder_is_gone():
    assert importlib.util.find_spec("app.bundledpacks") is None


def test_the_spec_freezes_no_pack_artifacts():
    spec = (REPO / "packaging" / "kriko-sidecar.spec").read_text(encoding="utf-8")

    assert "kpack" not in spec
    assert "packs_bundled" not in spec


def test_no_build_step_makes_packs_for_the_installer():
    assert not (REPO / "packaging" / "build_packs.py").exists()
    for step in (REPO / "kriko-ui" / "package.ps1",
                 REPO / ".github" / "workflows" / "desktop.yml"):
        assert "build_packs" not in step.read_text(encoding="utf-8"), step.name
