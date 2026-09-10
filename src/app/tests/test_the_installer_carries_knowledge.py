"""What the installer carries, and what startup does with it.

A fresh install opened onto an empty store, and the worse half of that was
invisible: a defect whose fix lives in a pack's *rows* could not be delivered
by any release at all. B101 gave a subject its `search_name` aliases so the
reader's searches would stop being `Volkswagen Golf 1.5_TSI 150 hp common
problems`, and the engine half shipped while their installed cars 0.1.1 kept
producing the old ones, because nothing in a release had ever handed a pack
over.

These tests pin the three rules `app/bundledpacks.py` states, and one property
of the build that makes it possible to forget them: which packs get carried is
*discovered*, so a third first-party pack ships by existing.
"""

import importlib.util
import shutil
import sqlite3
from pathlib import Path

import pytest

from app import bundledpacks
from kriko.store import ids, packstore
from kriko.store.db import connect

REPO = Path(__file__).resolve().parents[3]


def _build_packs():
    """`packaging/build_packs.py`, loaded by path.

    Not importable: `packaging/` is a directory of build scripts rather than a
    package, on purpose — nothing in `src/` may import from it. A test may read
    it, which is what this does.
    """
    spec = importlib.util.spec_from_file_location(
        "build_packs", REPO / "packaging" / "build_packs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _artifact(path, pack_id, version, *, digest=None, label="Makita DHP484"):
    """A real one-subject `.kpack` at `path`.

    Built by hand rather than by running the pack builder: what these tests are
    about is the *seeder*, and a fixture that took twelve seconds to build the
    cars pack would be testing YAML. Drill's vocabulary, so a test that does
    not care what the subject is is not accidentally a car fixture.
    """
    conn = connect(path)
    subject = ids.subject_id("product", {"brand": "makita", "model": "DHP484"})
    packstore.write_pack_row(
        conn,
        pack_id=pack_id,
        name=pack_id,
        version=version,
        content_digest=digest or (pack_id + version).ljust(64, "x")[:64],
    )
    conn.execute(
        "INSERT OR IGNORE INTO subjects VALUES (?,?,?,?)",
        (subject, pack_id, "product", label),
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def carried(tmp_path, monkeypatch):
    """A directory of bundled artifacts, pointed at the way a build points."""
    root = tmp_path / "packs_bundled"
    root.mkdir()
    monkeypatch.setenv("KRIKO_BUNDLED_PACKS", str(root))
    return root


def _installed(store_path) -> dict:
    conn = connect(store_path)
    try:
        return {r["pack_id"]: r["version"] for r in packstore.installed_packs(conn)}
    finally:
        conn.close()


def test_a_fresh_store_ends_up_with_the_carried_knowledge_in_it(carried, tmp_path):
    _artifact(carried / "drill.kpack", "org.kriko.drill", "0.1.0")
    store = tmp_path / "knowledge.sqlite"

    rows = bundledpacks.seed(store)

    assert [(r["pack_id"], r["action"]) for r in rows] == [
        ("org.kriko.drill", "installed")
    ]
    # The store, not the return value: a seeder that reported an install it did
    # not commit is the failure this whole feature exists to prevent.
    assert _installed(store) == {"org.kriko.drill": "0.1.0"}


def test_seeding_twice_installs_nothing_the_second_time(carried, tmp_path):
    _artifact(carried / "drill.kpack", "org.kriko.drill", "0.1.0")
    store = tmp_path / "knowledge.sqlite"

    bundledpacks.seed(store)
    again = bundledpacks.seed(store)

    # Startup runs on every launch. `current` rather than a second install,
    # and nothing in the log for a reader to read as churn.
    assert [r["action"] for r in again] == ["current"]


def test_a_newer_bundle_upgrades_a_store_that_is_behind(carried, tmp_path):
    old = _artifact(tmp_path / "old.kpack", "org.kriko.drill", "0.1.0")
    store = tmp_path / "knowledge.sqlite"
    conn = connect(store)
    packstore.install(conn, old)
    conn.commit()
    conn.close()

    _artifact(carried / "drill.kpack", "org.kriko.drill", "0.2.0")
    rows = bundledpacks.seed(store)

    assert [r["action"] for r in rows] == ["upgraded"]
    assert _installed(store) == {"org.kriko.drill": "0.2.0"}


def test_a_pack_the_reader_installed_by_hand_is_never_walked_backwards(
    carried, tmp_path
):
    newer = _artifact(tmp_path / "newer.kpack", "org.kriko.drill", "0.9.0")
    store = tmp_path / "knowledge.sqlite"
    conn = connect(store)
    packstore.install(conn, newer)
    conn.commit()
    conn.close()

    _artifact(carried / "drill.kpack", "org.kriko.drill", "0.2.0")
    rows = bundledpacks.seed(store)

    # An app upgrade that replaced a hand-installed 0.9.0 with the 0.2.0 it
    # happened to carry would be destroying the reader's own work to deliver
    # ours. The row says so rather than staying silent about it.
    assert rows == [
        {"pack_id": "org.kriko.drill", "version": "0.9.0",
         "action": "store_is_newer"}
    ]
    assert _installed(store) == {"org.kriko.drill": "0.9.0"}


def test_an_unreadable_artifact_is_skipped_and_the_others_still_install(
    carried, tmp_path
):
    (carried / "broken.kpack").write_bytes(b"not a database at all")
    _artifact(carried / "drill.kpack", "org.kriko.drill", "0.1.0")
    store = tmp_path / "knowledge.sqlite"

    rows = bundledpacks.seed(store)

    # Rule 3. Bundled knowledge is a convenience over a working store, never a
    # precondition for one — a truncated file in a bundle must not be the
    # reason an app will not start.
    assert [r["pack_id"] for r in rows] == ["org.kriko.drill"]
    assert _installed(store) == {"org.kriko.drill": "0.1.0"}


def test_an_artifact_is_identified_by_what_it_says_not_by_its_file_name(
    carried, tmp_path
):
    _artifact(carried / "drill.kpack", "org.kriko.drill", "0.1.0")
    shutil.move(carried / "drill.kpack", carried / "espresso-machines.kpack")

    assert [(pack_id, version) for _, pack_id, version in bundledpacks.bundled()] == [
        ("org.kriko.drill", "0.1.0")
    ]


def test_a_checkout_seeds_nothing_unless_it_is_asked_to(tmp_path, monkeypatch):
    monkeypatch.delenv("KRIKO_BUNDLED_PACKS", raising=False)

    # Deliberately narrower than `extension.source_dir`, which falls back to
    # the checkout. This one writes into a *store*: a developer's `dist/` holds
    # whatever they last built — the first run of this module found a
    # `drill.kpack` frozen before `gate_terms` existed in the schema — and the
    # 28 tests that start a lifespan would each have a 2 MB cars pack installed
    # into their temporary store by the act of starting the app.
    assert bundledpacks.source_dir() is None
    assert bundledpacks.seed(tmp_path / "knowledge.sqlite") == []
    assert not (tmp_path / "knowledge.sqlite").exists()


def test_a_store_holding_an_uncomparable_version_is_left_alone(carried, tmp_path):
    weird = _artifact(tmp_path / "weird.kpack", "org.kriko.drill", "nightly")
    store = tmp_path / "knowledge.sqlite"
    conn = connect(store)
    packstore.install(conn, weird)
    conn.commit()
    conn.close()

    _artifact(carried / "drill.kpack", "org.kriko.drill", "0.2.0")
    rows = bundledpacks.seed(store)

    # Two versions that cannot be ordered are not an upgrade in either
    # direction. Doing nothing is the safe answer and the reader can still
    # install the file by hand.
    assert [r["action"] for r in rows] == ["store_is_newer"]
    assert _installed(store) == {"org.kriko.drill": "nightly"}


def test_the_store_is_not_left_open_after_seeding(carried, tmp_path):
    _artifact(carried / "drill.kpack", "org.kriko.drill", "0.1.0")
    store = tmp_path / "knowledge.sqlite"
    bundledpacks.seed(store)

    # An unclosed store is a held WAL lock, and a lock held by the process the
    # installer is trying to replace is how "Error opening file for writing"
    # became a Windows install failure. Proven by taking the exclusive lock
    # that a live reader would refuse.
    conn = sqlite3.connect(store)
    try:
        conn.execute("PRAGMA locking_mode = EXCLUSIVE")
        conn.execute("BEGIN EXCLUSIVE")
    finally:
        conn.close()


def test_which_packs_the_build_carries_is_discovered_rather_than_listed():
    found = {path.name for path in _build_packs().pack_dirs()}

    # Every pack directory in the repository, with no list anywhere to keep in
    # step — the scalability principle applied to the build. A third
    # first-party pack ships by existing.
    on_disk = {
        path.parent.name for path in (REPO / "packs").glob("*/pack.toml")
    }
    assert found == on_disk
    assert "cars" in found and "drill" in found


def test_the_installer_spec_carries_the_artifacts_the_build_writes():
    spec = (REPO / "packaging" / "kriko-sidecar.spec").read_text(encoding="utf-8")

    # PyInstaller cannot see a file nothing imports, and the failure mode is a
    # green build that ships an empty engine. The spec refuses to freeze
    # without them; this is the check that it still asks.
    assert "packs_bundled" in spec
    assert 'glob("*.kpack")' in spec
