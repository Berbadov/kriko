"""A release must not leave the install instructions on an older download."""

import importlib.util
import json
import shutil
from pathlib import Path


def test_a_release_updates_both_install_pages_and_their_translation_keys(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("bump_site_test", repo / "tools/bump.py")
    bump = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bump)
    files = [p for p, _ in bump.PLACES] + list(bump.SITE_PAGES) + [Path("README.md"), Path("site/locales/tr.json")]
    for relative in files:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / relative, target)
    monkeypatch.setattr(bump, "ROOT", tmp_path)
    monkeypatch.setattr(bump, "installed", lambda: "")
    assert bump.bump("999.0.0") == 0
    for relative in bump.SITE_PAGES:
        text = (tmp_path / relative).read_text(encoding="utf-8")
        assert "kriko-999.0.0-x86_64-setup.exe" in text
        if "install" in relative.parts:
            assert "kriko-999.0.0-win64-portable.zip" in text
            assert "Get-FileHash -Algorithm SHA256 .\\kriko-999.0.0-x86_64-setup.exe" in text
            assert "kriko-0.3.7" not in text
    translations = json.loads((tmp_path / "site/locales/tr.json").read_text(encoding="utf-8"))
    command = "Get-FileHash -Algorithm SHA256 .\\kriko-999.0.0-x86_64-setup.exe"
    assert translations[command] == command
    assert bump.show(strict=True) == 0
