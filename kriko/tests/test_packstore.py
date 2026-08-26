"""Install / enable / disable / uninstall isolation.

These tests pin the two properties the whole pivot rests on:

  1. **Uninstall is surgical.** Removing a pack leaves every other pack's rows
     bit-for-bit unchanged. That is why `pack_id` is in every primary key.
  2. **Disagreement survives.** Two packs may assert contradicting claims about
     the same subject and both persist, with their evidence. Nothing is
     overwritten, so there is no conflict resolution to get wrong.
"""

import sqlite3

import pytest

from kriko.store import ids, packstore
from kriko.store.db import connect


def _pack(tmp_path, pack_id, claims, facts=(), name=None):
    """Build a minimal one-subject pack file and return its path."""
    path = tmp_path / f"{pack_id}.kpack.sqlite"
    conn = connect(path)
    subject = ids.subject_id("product", {"make": "vw", "model": "golf"})
    packstore.write_pack_row(
        conn, pack_id=pack_id, name=name or pack_id, version="0.1.0",
        content_digest="x" * 64)
    conn.execute(
        "INSERT OR IGNORE INTO subjects VALUES (?,?,?,?)",
        (subject, pack_id, "product", "VW Golf"))
    for key, value in facts:
        conn.execute(
            "INSERT OR IGNORE INTO attributes"
            " (attribute_id, pack_id, subject_id, key, value_text, value_num,"
            "  unit, valid_from, valid_to, is_identity, confidence)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ids.attribute_id(subject, key, value), pack_id, subject, key,
             str(value), None, "", "", "", 1, None))
    for title, severity in claims:
        cid = ids.claim_id(subject, "known_issue", "engine", title)
        conn.execute(
            "INSERT OR IGNORE INTO claims"
            " (claim_id, pack_id, subject_id, kind, domain, severity,"
            "  consequence, detection, author_confidence, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cid, pack_id, subject, "known_issue", "engine", severity,
             "", "", 0.8, "2026-08-26"))
        conn.execute(
            "INSERT OR IGNORE INTO claim_text VALUES (?,?,?,?,?,?)",
            (cid, pack_id, "en", title, "", ""))
    conn.commit()
    conn.close()
    return path


def _rows(conn, table, pack_id=None):
    sql = f"SELECT * FROM {table}"
    args = ()
    if pack_id is not None:
        sql += " WHERE pack_id = ?"
        args = (pack_id,)
    return [tuple(r) for r in conn.execute(sql + " ORDER BY 1", args)]


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    yield conn
    conn.close()


def test_fresh_store_applies_the_schema(store):
    tables = {r[0] for r in store.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"packs", "subjects", "attributes", "relations", "claims",
            "claim_text", "claim_conditions", "sources", "evidence",
            "terms", "pack_trust"} <= tables


def test_store_uses_wal(store):
    """The web app reads while pipeline subprocesses write to the same file."""
    mode = store.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_install_tags_every_row_with_the_pack_id(store, tmp_path):
    packstore.install(store, _pack(tmp_path, "cars", [("Timing chain", "high")]))
    assert _rows(store, "claims", "cars")
    assert all(r[1] == "cars" for r in _rows(store, "claims"))


def test_install_is_idempotent(store, tmp_path):
    pack = _pack(tmp_path, "cars", [("Timing chain", "high")])
    packstore.install(store, pack)
    before = _rows(store, "claims")
    packstore.install(store, pack)
    assert _rows(store, "claims") == before


def test_two_packs_asserting_the_same_fact_keep_one_row_each(store, tmp_path):
    """Identical content hashes, but the rows do NOT collapse across packs.

    This is deliberate and is the crux of clean uninstall: if the two packs
    shared a single row, removing one would delete a fact the other still
    asserts. Deduplication is a read-time concern — the hash agreeing is what
    makes that read-time grouping possible.
    """
    packstore.install(store, _pack(tmp_path, "a", [], facts=[("fuel", "diesel")]))
    packstore.install(store, _pack(tmp_path, "b", [], facts=[("fuel", "diesel")]))

    rows = _rows(store, "attributes")
    assert len(rows) == 2
    assert len({r[0] for r in rows}) == 1          # one content hash
    assert {r[1] for r in rows} == {"a", "b"}      # two packs

    distinct = store.execute(
        "SELECT COUNT(DISTINCT attribute_id) FROM attributes").fetchone()[0]
    assert distinct == 1


def test_contradicting_claims_from_two_packs_both_persist(store, tmp_path):
    packstore.install(store, _pack(tmp_path, "a", [("Chain fails at 120k", "high")]))
    packstore.install(store, _pack(tmp_path, "b", [("Chain fails at 180k", "low")]))
    titles = {r[0] for r in store.execute("SELECT title FROM claim_text")}
    assert titles == {"Chain fails at 120k", "Chain fails at 180k"}


def test_uninstall_leaves_other_packs_bit_for_bit_unchanged(store, tmp_path):
    packstore.install(store, _pack(tmp_path, "cars", [("Timing chain", "high")],
                                   facts=[("fuel", "diesel")]))
    packstore.install(store, _pack(tmp_path, "drill", [("Chuck slips", "medium")],
                                   facts=[("voltage", "18")]))

    tables = ("subjects", "attributes", "claims", "claim_text", "packs")
    before = {t: _rows(store, t, "cars") for t in tables}

    packstore.uninstall(store, "drill")

    assert {t: _rows(store, t, "cars") for t in tables} == before
    for t in tables:
        assert _rows(store, t, "drill") == []


def test_uninstall_clears_every_table(store, tmp_path):
    packstore.install(store, _pack(tmp_path, "cars", [("Timing chain", "high")],
                                   facts=[("fuel", "diesel")]))
    packstore.uninstall(store, "cars")
    for table in packstore.PACK_TABLES:
        assert _rows(store, table, "cars") == [], f"{table} still holds cars rows"


def test_disable_keeps_rows_but_hides_the_pack(store, tmp_path):
    """Disable must not destroy data — re-enabling is free, reinstalling is not."""
    packstore.install(store, _pack(tmp_path, "cars", [("Timing chain", "high")]))
    packstore.set_enabled(store, "cars", False)

    assert _rows(store, "claims", "cars")
    assert packstore.enabled_pack_ids(store) == []

    packstore.set_enabled(store, "cars", True)
    assert packstore.enabled_pack_ids(store) == ["cars"]


def test_installed_packs_reports_state(store, tmp_path):
    packstore.install(store, _pack(tmp_path, "cars", [], name="Cars"))
    packstore.set_enabled(store, "cars", False)
    (row,) = packstore.installed_packs(store)
    assert row["pack_id"] == "cars"
    assert row["name"] == "Cars"
    assert row["enabled"] == 0
    assert row["installed_at"]


def test_uninstalling_an_absent_pack_is_an_error(store):
    with pytest.raises(KeyError):
        packstore.uninstall(store, "nope")


def test_install_rejects_a_pack_carrying_more_than_one_pack_row(store, tmp_path):
    """A pack file describes exactly one pack; two means a corrupt build."""
    path = _pack(tmp_path, "cars", [])
    conn = connect(path)
    packstore.write_pack_row(conn, pack_id="stowaway", name="s", version="0.1.0",
                             content_digest="y" * 64)
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="exactly one"):
        packstore.install(store, path)


def test_install_is_atomic(store, tmp_path, monkeypatch):
    """A failure mid-install must leave no half-installed pack behind."""
    packstore.install(store, _pack(tmp_path, "cars", [("Timing chain", "high")]))
    before = {t: _rows(store, t) for t in packstore.PACK_TABLES}

    real = packstore._copy_table

    def boom(conn, table, pack_id):
        if table == "claims":
            raise sqlite3.OperationalError("simulated failure")
        return real(conn, table, pack_id)

    monkeypatch.setattr(packstore, "_copy_table", boom)
    with pytest.raises(sqlite3.OperationalError):
        packstore.install(store, _pack(tmp_path, "drill", [("Chuck slips", "low")]))

    assert {t: _rows(store, t) for t in packstore.PACK_TABLES} == before
