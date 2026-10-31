"""The single-folder catalog bundle is the same set the index names.

`packaging/make_packs_bundle.py` makes `packs-<version>.zip`: one attachment a
person can download, or one folder to hand over offline. It must never drift
from the files the app actually installs and updates from, so the bundler
refuses an index and a set of `.kpack` files that disagree, and the same input
set has to produce the same bytes.
"""

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packaging"))

import make_packs_bundle  # noqa: E402


def _catalogs(tmp_path: Path, names: list[str]):
    packs = tmp_path / "built"
    packs.mkdir()
    files = []
    rows = []
    for name in names:
        pack = packs / f"{name}.kpack"
        pack.write_bytes(f"sqlite:{name}".encode())
        files.append(pack)
        rows.append(
            {
                "pack_id": f"org.example.{name}",
                "version": "1.0.0",
                "url": f"https://example.test/download/v1/{name}.kpack",
                "sha256": hashlib.sha256(pack.read_bytes()).hexdigest(),
            }
        )
    index = tmp_path / "packs.json"
    index.write_text(json.dumps({"packs": rows}), encoding="utf-8")
    return index, files


def _names(bundle: Path) -> list[str]:
    with zipfile.ZipFile(bundle) as archive:
        return sorted(archive.namelist())


def test_the_bundle_holds_the_index_and_every_catalog(tmp_path):
    index, files = _catalogs(tmp_path, ["cars", "drill"])
    result = make_packs_bundle.build(index, files, tmp_path / "packs-9.9.9.zip")
    assert _names(result["path"]) == [
        "packs.json",
        "packs/cars.kpack",
        "packs/drill.kpack",
    ]
    assert result["files"] == 3
    with zipfile.ZipFile(result["path"]) as archive:
        assert archive.read("packs.json") == index.read_bytes()
        for pack in files:
            assert archive.read(f"packs/{pack.name}") == pack.read_bytes()


def test_the_same_inputs_make_the_same_bytes(tmp_path):
    index, files = _catalogs(tmp_path, ["cars", "drill"])
    first = make_packs_bundle.build(index, files, tmp_path / "a.zip")
    second = make_packs_bundle.build(index, files, tmp_path / "b.zip")
    assert first["sha256"] == second["sha256"]


def test_a_bundle_that_would_lie_is_refused(tmp_path):
    index, files = _catalogs(tmp_path, ["cars", "drill"])
    with pytest.raises(SystemExit):
        make_packs_bundle.build(index, files[:1], tmp_path / "missing-one.zip")
    with pytest.raises(SystemExit):
        make_packs_bundle.build(
            index, files + [tmp_path / "not-in-the-index.kpack"], tmp_path / "extra.zip"
        )


def test_an_index_that_names_nothing_is_refused(tmp_path):
    index = tmp_path / "packs.json"
    index.write_text(json.dumps({"packs": []}), encoding="utf-8")
    with pytest.raises(SystemExit):
        make_packs_bundle.build(index, [], tmp_path / "empty.zip")
