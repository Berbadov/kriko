"""An engine update is a folder of its own, never files laid over files.

The reader's words: "uninstalling and reinstalling is idiotic". An update that
overlaid the engine left the old one's leftovers beside the new, and the cure was
an uninstall. The engine now arrives whole, in `<engines>/<version>/`, checked
against the release's checksums, and nothing existing is written to.
"""

import hashlib
import io
import json
import os
import time
import zipfile

import pytest

from app import appupdate, engineupdate

SIDECAR = engineupdate.sidecar_name()


def _zip(version="0.3.0", *, min_shell="0", extra=None, manifest_version=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("engine.json", json.dumps({"version": manifest_version or version, "min_shell": min_shell}))
        zf.writestr(SIDECAR, b"engine")
        zf.writestr("_internal/kriko-%s.dist-info/METADATA" % version, f"Version: {version}")
        for name, body in (extra or {}).items():
            zf.writestr(name, body)
    return buf.getvalue()


def _release(version="0.3.0", *, engine=True):
    base = "https://example.test/dl"
    names = [f"kriko-{version}-x86_64-setup.exe", "SHA256SUMS.txt"]
    if engine:
        names += [f"kriko-engine-{version}-win64.zip", "engine.json"]
    return {"tag_name": f"v{version}", "html_url": "https://example.test/r", "body": "",
            "assets": [{"name": n, "browser_download_url": f"{base}/{n}"} for n in names]}


def _serve(monkeypatch, body: bytes, version="0.3.0", *, manifest=None, digest=None):
    name = f"kriko-engine-{version}-win64.zip"
    sums = f"{digest or hashlib.sha256(body).hexdigest()}  {name}\n"

    def fake(url, timeout):
        if url.endswith("SHA256SUMS.txt"):
            return io.BytesIO(sums.encode())
        if url.endswith("engine.json"):
            return io.BytesIO(json.dumps(manifest or {"version": version, "min_shell": "0"}).encode())
        return io.BytesIO(body)

    monkeypatch.setattr(appupdate, "_open", fake)


def _info(version="0.3.0"):
    return appupdate.parse_release(_release(version))["engine"]


def test_a_release_with_an_engine_names_it():
    got = appupdate.parse_release(_release())
    assert got["engine"]["version"] == "0.3.0" and got["engine"]["name"].endswith("-win64.zip")
    assert appupdate.parse_release(_release(engine=False))["engine"] == {}


def test_the_engine_is_offered_only_to_a_copy_that_can_restart_into_it(monkeypatch):
    _serve(monkeypatch, b"", manifest={"version": "0.3.0", "min_shell": "0.2.6"})
    release = appupdate.parse_release(_release())
    assert engineupdate.offer(release, "0.2.5", "0.2.6")["version"] == "0.3.0"
    assert engineupdate.offer(release, "0.2.5", "") == {}, "no desktop app, no restart into it"
    assert engineupdate.offer(release, "0.2.5", "0.2.5") == {}, "the app is older than the engine needs"
    assert engineupdate.offer(release, "0.3.0", "0.3.0") == {}, "already running it"


def test_a_check_carries_the_engine_beside_the_installer(monkeypatch):
    _serve(monkeypatch, b"")
    monkeypatch.setattr(appupdate, "latest", lambda url: appupdate.parse_release(_release()))
    monkeypatch.setenv("KRIKO_SHELL_VERSION", "0.2.5")
    got = appupdate.check("https://example.test/api", "0.2.5")
    assert got["newer"] and got["name"].endswith("setup.exe") and got["engine"]["version"] == "0.3.0"
    monkeypatch.delenv("KRIKO_SHELL_VERSION")
    assert appupdate.check("https://example.test/api", "0.2.5")["engine"] == {}


def test_staging_builds_a_whole_folder_and_marks_it_ready_last(monkeypatch, tmp_path):
    _serve(monkeypatch, _zip())
    older = tmp_path / "0.2.9"
    older.mkdir()
    (older / "keep").write_text("untouched", encoding="utf-8")
    out = engineupdate.stage(_info(), root=tmp_path, shell="0.2.6")
    folder = tmp_path / "0.3.0"
    assert out["staged"] == "0.3.0" and (folder / SIDECAR).is_file()
    assert (folder / "_internal" / "kriko-0.3.0.dist-info" / "METADATA").is_file()
    assert (folder / engineupdate.READY).read_text(encoding="utf-8") == "0.3.0"
    assert (older / "keep").read_text(encoding="utf-8") == "untouched"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["0.2.9", "0.3.0"], "no scratch left behind"


def test_staging_twice_replaces_the_folder_instead_of_overlaying_it(monkeypatch, tmp_path):
    _serve(monkeypatch, _zip())
    engineupdate.stage(_info(), root=tmp_path, shell="0.2.6")
    (tmp_path / "0.3.0" / "leftover").write_text("old", encoding="utf-8")
    engineupdate.stage(_info(), root=tmp_path, shell="0.2.6")
    assert not (tmp_path / "0.3.0" / "leftover").exists()


@pytest.mark.parametrize("body,digest,why", [
    (_zip(), "0" * 64, "checksum"),
    (_zip(manifest_version="0.9.9"), None, "not the version"),
    (_zip(min_shell="9.0.0"), None, "installer"),
    (_zip(extra={"../escape.txt": "x"}), None, "unsafe"),
    (_zip(extra={"/abs.txt": "x"}), None, "unsafe"),
])
def test_a_download_that_is_wrong_leaves_the_engines_as_they_were(monkeypatch, tmp_path, body, digest, why):
    _serve(monkeypatch, body, digest=digest)
    with pytest.raises(ValueError, match=why):
        engineupdate.stage(_info(), root=tmp_path, shell="0.2.6")
    assert list(tmp_path.iterdir()) == []
    assert not (tmp_path.parent / "escape.txt").exists()


def test_a_zip_without_an_engine_in_it_is_refused(monkeypatch, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("engine.json", json.dumps({"version": "0.3.0"}))
    _serve(monkeypatch, buf.getvalue())
    with pytest.raises(ValueError, match="holds no"):
        engineupdate.stage(_info(), root=tmp_path, shell="0.2.6")


def _folder(root, name, *, ready=True, bad=False):
    one = root / name
    one.mkdir()
    if ready:
        (one / engineupdate.READY).write_text(name, encoding="utf-8")
    if bad:
        (one / engineupdate.BAD).write_text("did not start", encoding="utf-8")
    return one


def test_prune_keeps_what_runs_and_what_is_staged_and_removes_the_rest(tmp_path):
    _folder(tmp_path, "0.2.9")                    # older than the running one: never chosen again
    _folder(tmp_path, "0.3.0")                    # running
    _folder(tmp_path, "0.3.1")                    # staged update
    _folder(tmp_path, "0.3.2", bad=True)          # failed to start
    half = _folder(tmp_path, "0.3.3", ready=False)  # an update that stopped halfway
    old = time.time() - 2 * 3600
    os.utime(half, (old, old))
    gone = engineupdate.prune("0.3.0", tmp_path)
    assert sorted(gone) == ["0.2.9", "0.3.2", "0.3.3"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["0.3.0", "0.3.1"]


def test_prune_leaves_an_update_that_is_still_unpacking(tmp_path):
    _folder(tmp_path, "0.3.3", ready=False)
    (tmp_path / "kriko-engine-abc123").mkdir()
    assert engineupdate.prune("0.3.0", tmp_path) == []


def test_the_engines_folder_can_be_pointed_elsewhere(monkeypatch, tmp_path):
    monkeypatch.setenv("KRIKO_ENGINES_DIR", str(tmp_path / "e"))
    assert engineupdate.engines_root() == tmp_path / "e"
