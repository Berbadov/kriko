"""The release's engine zip and the updater that unpacks it agree.

The packer is `packaging/make_engine_zip.py` (run by `desktop.yml` and
`kriko-ui/package.ps1`), the reader is `app/engineupdate.py`. They share a
layout and nothing else, so this test runs one into the other.
"""

import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

from app import appupdate, engineupdate

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def packer():
    spec = importlib.util.spec_from_file_location("make_engine_zip", ROOT / "packaging" / "make_engine_zip.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frozen(folder: Path) -> Path:
    (folder / "_internal" / "kriko-9.9.9.dist-info").mkdir(parents=True)
    (folder / "_internal" / "kriko-9.9.9.dist-info" / "METADATA").write_text("Version: 9.9.9", encoding="utf-8")
    (folder / "_internal" / "python313.dll").write_bytes(b"dll")
    (folder / "kriko-sidecar.exe").write_bytes(b"engine")
    return folder


def test_the_zip_holds_the_manifest_the_program_and_the_folder(packer, tmp_path):
    zip_path = packer.pack(_frozen(tmp_path / "frozen"), tmp_path / "out", "9.9.9")
    assert zip_path.name == "kriko-engine-9.9.9-win64.zip"
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("engine.json"))
    assert {"engine.json", "kriko-sidecar.exe", "_internal/python313.dll",
            "_internal/kriko-9.9.9.dist-info/METADATA"} <= names
    assert manifest["version"] == "9.9.9" and manifest["asset"] == zip_path.name
    assert json.loads((tmp_path / "out" / "engine.json").read_text(encoding="utf-8")) == manifest


def test_what_the_packer_writes_the_updater_stages(packer, tmp_path, monkeypatch):
    zip_path = packer.pack(_frozen(tmp_path / "frozen"), tmp_path / "out", "9.9.9")
    body = zip_path.read_bytes()
    name = zip_path.name
    release = {"assets": [
        {"name": "kriko-9.9.9-x86_64-setup.exe", "browser_download_url": "https://x/s.exe"},
        {"name": name, "browser_download_url": f"https://x/{name}"},
        {"name": "engine.json", "browser_download_url": "https://x/engine.json"},
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://x/SHA256SUMS.txt"},
    ]}
    manifest = (tmp_path / "out" / "engine.json").read_bytes()
    sums = f"{hashlib.sha256(body).hexdigest()}  {name}\n".encode()

    def fake(url, timeout):
        return io.BytesIO(sums if url.endswith("SUMS.txt") else manifest if url.endswith("engine.json") else body)

    monkeypatch.setattr(appupdate, "_open", fake)
    offered = engineupdate.offer(appupdate.parse_release(release), "0.2.5", "0.2.5")
    assert offered["version"] == "9.9.9"
    root = tmp_path / "engines"
    engineupdate.stage(offered, root=root, shell="0.2.5")
    assert (root / "9.9.9" / "kriko-sidecar.exe").read_bytes() == b"engine"
    assert (root / "9.9.9" / engineupdate.READY).is_file()


def test_a_folder_that_is_not_an_engine_is_refused(packer, tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit, match="not a frozen engine"):
        packer.pack(tmp_path / "empty", tmp_path / "out", "9.9.9")


def test_the_zip_is_named_for_the_tree_it_was_built_from(packer, tmp_path):
    frozen = _frozen(tmp_path / "frozen")
    with pytest.raises(SystemExit, match="this tree is"):
        packer.main(["--engine", str(frozen), "--out", str(tmp_path / "out"), "--version", "0.0.1"])
