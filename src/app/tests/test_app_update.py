"""The app finds a newer release, and installs only what matches its checksum."""

import hashlib
import io

import pytest

from app import appupdate


def _release(version="1.2.0", *, sums=True):
    base = "https://example.test/dl"
    assets = [{"name": f"kriko-{version}-x86_64.msi", "browser_download_url": f"{base}/kriko-{version}-x86_64.msi"},
              {"name": "cars.kpack", "browser_download_url": f"{base}/cars.kpack"}]
    if sums:
        assets.append({"name": "SHA256SUMS.txt", "browser_download_url": f"{base}/SHA256SUMS.txt"})
    return {"tag_name": f"v{version}", "html_url": "https://example.test/r", "body": "notes", "assets": assets}


def test_versions_compare_as_numbers_not_text():
    assert appupdate.is_newer("1.1.10", "1.1.9")
    assert appupdate.is_newer("v1.2.0", "1.1.5")
    assert not appupdate.is_newer("1.1.5", "1.1.5")
    assert not appupdate.is_newer("1.1.4", "1.1.5")
    assert not appupdate.is_newer("9.9.9", "unknown")


def test_a_release_without_an_installer_offers_nothing():
    assert appupdate.parse_release({"assets": [{"name": "cars.kpack", "browser_download_url": "https://x/y"}]}) == {}
    got = appupdate.parse_release(_release())
    assert got["version"] == "1.2.0" and got["name"] == "kriko-1.2.0-x86_64.msi"


def test_a_failed_check_is_a_plain_sentence_not_a_crash(monkeypatch):
    def boom(url, timeout):
        raise OSError("HTTP Error 404: Not Found")

    monkeypatch.setattr(appupdate, "_open", boom)
    got = appupdate.check("https://example.test/api", "1.1.5")
    assert got["newer"] is False and got["error"] == "no published release found"


def _serve(monkeypatch, installer: bytes, sums_line: str):
    def fake(url, timeout):
        return io.BytesIO(sums_line.encode() if url.endswith("SHA256SUMS.txt") else installer)

    monkeypatch.setattr(appupdate, "_open", fake)


def test_a_download_that_matches_the_checksum_is_kept(monkeypatch, tmp_path):
    body = b"installer bytes"
    info = appupdate.parse_release(_release())
    _serve(monkeypatch, body, f"{hashlib.sha256(body).hexdigest()}  {info['name']}\n")
    path = appupdate.download(info, tmp_path)
    assert path.read_bytes() == body and not list(tmp_path.glob("*.part"))


def test_a_download_that_does_not_match_is_discarded(monkeypatch, tmp_path):
    info = appupdate.parse_release(_release())
    _serve(monkeypatch, b"tampered", f"{'0' * 64}  {info['name']}\n")
    with pytest.raises(ValueError, match="checksum"):
        appupdate.download(info, tmp_path)
    assert not list(tmp_path.iterdir())


def test_a_release_without_checksums_is_not_offered(tmp_path):
    with pytest.raises(ValueError, match="checksums"):
        appupdate.download(appupdate.parse_release(_release(sums=False)), tmp_path)


def test_http_is_refused():
    with pytest.raises(ValueError, match="https"):
        appupdate._open("http://example.test/x", 1)
