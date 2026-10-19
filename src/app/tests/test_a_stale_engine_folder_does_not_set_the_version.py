"""An update lays the new engine over the old one, and the old metadata stays.

The engine's folder build keeps its packages beside it, and the installer only
copies: `kriko-0.2.3.dist-info` survived the update to 0.2.4. The version is
read from the distribution metadata, and `importlib.metadata.version` answers
with the first match on the path, so the engine of 0.2.4 said "0.2.3", the app
offered 0.2.4 to a copy that already was 0.2.4, and the 0.2.4 installer appeared
to install 0.2.3. The reader's words: "i cannot update it the 0.2.4 installer
shows 0.2.3".
"""

import sys

import pytest

from app import version


def _dist(folder, number: str) -> None:
    info = folder / f"kriko-{number}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: kriko\nVersion: {number}\n", encoding="utf-8"
    )


@pytest.fixture
def fresh():
    version.app_version.cache_clear()
    yield
    version.app_version.cache_clear()


def test_the_newest_copy_of_the_metadata_is_the_version(tmp_path, monkeypatch, fresh):
    # `-I`-like isolation: only this folder carries a kriko distribution.
    monkeypatch.setattr(sys, "path", [str(tmp_path)])
    _dist(tmp_path, "0.2.3")
    _dist(tmp_path, "0.2.4")
    assert version.app_version() == "0.2.4"


def test_the_order_of_the_folders_does_not_matter(tmp_path, monkeypatch, fresh):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    _dist(old, "0.2.3")
    _dist(new, "0.10.0")
    monkeypatch.setattr(sys, "path", [str(old), str(new)])
    # numbers, not strings: "0.10.0" is newer than "0.2.3"
    assert version.app_version() == "0.10.0"


def test_a_lone_distribution_is_still_the_version(tmp_path, monkeypatch, fresh):
    monkeypatch.setattr(sys, "path", [str(tmp_path)])
    _dist(tmp_path, "0.2.4")
    assert version.app_version() == "0.2.4"


def test_no_metadata_at_all_is_unknown_not_a_crash(tmp_path, monkeypatch, fresh):
    monkeypatch.setattr(sys, "path", [str(tmp_path)])
    assert version.app_version() == version.UNKNOWN
