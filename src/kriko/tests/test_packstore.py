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


def _pack(tmp_path, pack_id, claims, facts=(), name=None, version="0.1.0", digest=None,
          identity=None, label=None, domain="mechanical"):
    """Build a minimal one-subject pack file and return its path.

    Defaults to drill's own vocabulary (a Makita DHP484) so a test that does
    not care what the subject *is* — install/uninstall/versioning isolation —
    is not accidentally a car fixture. A test that genuinely needs to cross
    two categories passes `identity`/`label`/`domain` explicitly and says so.
    """
    identity = identity or {"brand": "makita", "model": "DHP484"}
    label = label or "Makita DHP484"
    path = tmp_path / f"{pack_id}-{version}-{digest or 'default'}.kpack.sqlite"
    conn = connect(path)
    subject = ids.subject_id("product", identity)
    packstore.write_pack_row(
        conn,
        pack_id=pack_id,
        name=name or pack_id,
        version=version,
        content_digest=digest or "x" * 64,
    )
    conn.execute(
        "INSERT OR IGNORE INTO subjects VALUES (?,?,?,?)",
        (subject, pack_id, "product", label),
    )
    for key, value in facts:
        conn.execute(
            "INSERT OR IGNORE INTO attributes"
            " (attribute_id, pack_id, subject_id, key, value_text, value_num,"
            "  unit, valid_from, valid_to, is_identity, confidence)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                ids.attribute_id(subject, key, value),
                pack_id,
                subject,
                key,
                str(value),
                None,
                "",
                "",
                "",
                1,
                None,
            ),
        )
    for title, severity in claims:
        cid = ids.claim_id(subject, "known_issue", domain, title)
        conn.execute(
            "INSERT OR IGNORE INTO claims"
            " (claim_id, pack_id, subject_id, kind, domain, severity,"
            "  consequence, detection, author_confidence, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                cid,
                pack_id,
                subject,
                "known_issue",
                domain,
                severity,
                "",
                "",
                0.8,
                "2026-08-26",
            ),
        )
        conn.execute(
            "INSERT OR IGNORE INTO claim_text VALUES (?,?,?,?,?,?)",
            (cid, pack_id, "en", title, "", ""),
        )
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
    tables = {
        r[0] for r in store.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "packs",
        "subjects",
        "attributes",
        "relations",
        "claims",
        "claim_text",
        "claim_conditions",
        "sources",
        "evidence",
        "terms",
        "pack_trust",
    } <= tables


def test_store_uses_wal(store):
    """The web app reads while pipeline subprocesses write to the same file."""
    mode = store.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_install_tags_every_row_with_the_pack_id(store, tmp_path):
    packstore.install(store, _pack(tmp_path, "p", [("Chuck bearing wear", "high")]))
    assert _rows(store, "claims", "p")
    assert all(r[1] == "p" for r in _rows(store, "claims"))


def test_install_is_idempotent(store, tmp_path):
    pack = _pack(tmp_path, "p", [("Chuck bearing wear", "high")])
    packstore.install(store, pack)
    before = _rows(store, "claims")
    packstore.install(store, pack)
    assert _rows(store, "claims") == before


def test_installing_an_older_version_is_refused_unless_allowed(store, tmp_path):
    """Installing dist/drill.kpack after a newer build must not silently roll
    the active pack back (knowledge-13) — the reader gets no warning that
    "Installed Cordless drills 0.1.1" replaced a 0.1.2 they already had."""
    packstore.install(store, _pack(tmp_path, "p", [], version="0.1.2", digest="a" * 64))
    older = _pack(tmp_path, "p", [], version="0.1.1", digest="b" * 64)

    with pytest.raises(packstore.DowngradeRefused):
        packstore.install(store, older)
    assert store.execute(
        "SELECT version FROM packs WHERE pack_id = 'p'"
    ).fetchone()[0] == "0.1.2"

    # Asking for it explicitly still works.
    packstore.install(store, older, allow_downgrade=True)
    assert store.execute(
        "SELECT version FROM packs WHERE pack_id = 'p'"
    ).fetchone()[0] == "0.1.1"


def test_two_packs_asserting_the_same_fact_keep_one_row_each(store, tmp_path):
    """Identical content hashes, but the rows do NOT collapse across packs.

    This is deliberate and is the crux of clean uninstall: if the two packs
    shared a single row, removing one would delete a fact the other still
    asserts. Deduplication is a read-time concern — the hash agreeing is what
    makes that read-time grouping possible.
    """
    packstore.install(store, _pack(tmp_path, "a", [], facts=[("voltage_v", "18")]))
    packstore.install(store, _pack(tmp_path, "b", [], facts=[("voltage_v", "18")]))

    rows = _rows(store, "attributes")
    assert len(rows) == 2
    assert len({r[0] for r in rows}) == 1  # one content hash
    assert {r[1] for r in rows} == {"a", "b"}  # two packs

    distinct = store.execute(
        "SELECT COUNT(DISTINCT attribute_id) FROM attributes"
    ).fetchone()[0]
    assert distinct == 1


def test_contradicting_claims_from_two_packs_both_persist(store, tmp_path):
    packstore.install(
        store, _pack(tmp_path, "a", [("Chuck bearing fails at 1,200 cycles", "high")]))
    packstore.install(
        store, _pack(tmp_path, "b", [("Chuck bearing fails at 1,800 cycles", "low")]))
    titles = {r[0] for r in store.execute("SELECT title FROM claim_text")}
    assert titles == {
        "Chuck bearing fails at 1,200 cycles", "Chuck bearing fails at 1,800 cycles"}


def test_uninstall_leaves_other_packs_bit_for_bit_unchanged(store, tmp_path):
    """Deliberately two real, distinct categories — cars and a cordless drill
    — because the property under test is isolation between installed packs,
    and that claim is stronger proven across genuinely different products
    than across two same-shaped ones."""
    packstore.install(
        store,
        _pack(tmp_path, "cars", [("Timing chain wear", "high")],
              facts=[("fuel", "diesel")],
              identity={"make": "vw", "model": "golf"}, label="VW Golf",
              domain="engine"),
    )
    packstore.install(
        store,
        _pack(tmp_path, "drill", [("Chuck bearing wear", "medium")],
              facts=[("voltage_v", "18")]),
    )

    tables = ("subjects", "attributes", "claims", "claim_text", "packs")
    before = {t: _rows(store, t, "cars") for t in tables}

    packstore.uninstall(store, "drill")

    assert {t: _rows(store, t, "cars") for t in tables} == before
    for t in tables:
        assert _rows(store, t, "drill") == []


def test_uninstall_clears_every_table(store, tmp_path):
    packstore.install(
        store,
        _pack(tmp_path, "p", [("Chuck bearing wear", "high")],
              facts=[("voltage_v", "18")]),
    )
    packstore.uninstall(store, "p")
    for table in packstore.PACK_TABLES:
        assert _rows(store, table, "p") == [], f"{table} still holds rows"


def test_disable_keeps_rows_but_hides_the_pack(store, tmp_path):
    """Disable must not destroy data — re-enabling is free, reinstalling is not."""
    packstore.install(store, _pack(tmp_path, "p", [("Chuck bearing wear", "high")]))
    packstore.set_enabled(store, "p", False)

    assert _rows(store, "claims", "p")
    assert packstore.enabled_pack_ids(store) == []

    packstore.set_enabled(store, "p", True)
    assert packstore.enabled_pack_ids(store) == ["p"]


def test_installed_packs_reports_state(store, tmp_path):
    packstore.install(store, _pack(tmp_path, "p", [], name="P"))
    packstore.set_enabled(store, "p", False)
    (row,) = packstore.installed_packs(store)
    assert row["pack_id"] == "p"
    assert row["name"] == "P"
    assert row["enabled"] == 0
    assert row["installed_at"]


def test_uninstalling_an_absent_pack_is_an_error(store):
    with pytest.raises(KeyError):
        packstore.uninstall(store, "nope")


def test_install_rejects_a_pack_carrying_more_than_one_pack_row(store, tmp_path):
    """A pack file describes exactly one pack; two means a corrupt build."""
    path = _pack(tmp_path, "p", [])
    conn = connect(path)
    packstore.write_pack_row(
        conn, pack_id="stowaway", name="s", version="0.1.0", content_digest="y" * 64
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="exactly one"):
        packstore.install(store, path)


def test_same_version_with_a_new_digest_is_rejected(store, tmp_path):
    packstore.install(store, _pack(tmp_path, "p", [], digest="a" * 64))
    with pytest.raises(ValueError, match="immutable"):
        packstore.install(store, _pack(tmp_path, "p", [], digest="b" * 64))
    assert store.execute("SELECT content_digest FROM packs").fetchone()[0] == "a" * 64


def test_update_preserves_pack_trust(store, tmp_path):
    packstore.install(store, _pack(tmp_path, "p", [], digest="a" * 64))
    store.execute(
        "INSERT INTO pack_trust (pack_id, weight, pinned) VALUES (?, ?, ?)",
        ("p", 0.25, 1),
    )
    packstore.update(
        store, _pack(tmp_path, "p", [], version="2.0.0", digest="b" * 64)
    )
    assert tuple(
        store.execute(
            "SELECT weight, pinned FROM pack_trust WHERE pack_id = 'p'"
        ).fetchone()
    ) == (0.25, 1)
    packstore.activate(store, "p", "a" * 64)
    assert tuple(
        store.execute(
            "SELECT weight, pinned FROM pack_trust WHERE pack_id = 'p'"
        ).fetchone()
    ) == (0.25, 1)


def test_update_retains_the_old_revision_and_changes_active_rows(store, tmp_path):
    packstore.install(
        store,
        _pack(tmp_path, "p", [("old", "high")], version="1.0.0", digest="a" * 64),
    )
    packstore.update(
        store,
        _pack(tmp_path, "p", [("new", "low")], version="2.0.0", digest="b" * 64),
    )

    assert store.execute("SELECT version FROM packs").fetchone()[0] == "2.0.0"
    assert {r[0] for r in store.execute("SELECT title FROM claim_text")} == {"new"}
    assert {r["version"] for r in packstore.revisions(store, "p")} == {
        "1.0.0",
        "2.0.0",
    }


def test_same_version_with_a_new_digest_is_rejected_from_retained_history(
    store, tmp_path
):
    packstore.install(
        store, _pack(tmp_path, "p", [], version="1.0.0", digest="a" * 64)
    )
    packstore.install(
        store, _pack(tmp_path, "p", [], version="2.0.0", digest="b" * 64)
    )
    with pytest.raises(ValueError, match="immutable"):
        packstore.install(
            store, _pack(tmp_path, "p", [], version="1.0.0", digest="c" * 64)
        )


def test_same_digest_cannot_be_relabelled_with_another_version(store, tmp_path):
    packstore.install(
        store, _pack(tmp_path, "p", [], version="1.0.0", digest="a" * 64)
    )
    with pytest.raises(ValueError, match="another version"):
        packstore.install(
            store, _pack(tmp_path, "p", [], version="2.0.0", digest="a" * 64)
        )


def test_rollback_walks_back_through_three_revisions(store, tmp_path):
    for version, digest, title in (
        ("1.0.0", "a", "one"),
        ("2.0.0", "b", "two"),
        ("3.0.0", "c", "three"),
    ):
        packstore.install(
            store,
            _pack(
                tmp_path, "p", [(title, "high")], version=version, digest=digest * 64
            ),
        )

    initial = {
        row["version"]: row["activated_at"]
        for row in packstore.revisions(store, "p")
    }
    packstore.rollback(store, "p")
    assert store.execute("SELECT version FROM packs").fetchone()[0] == "2.0.0"
    assert store.execute("SELECT title FROM claim_text").fetchone()[0] == "two"
    after_first = {
        row["version"]: row["activated_at"]
        for row in packstore.revisions(store, "p")
    }
    assert after_first["3.0.0"] == initial["3.0.0"]
    assert after_first["2.0.0"] > initial["2.0.0"]

    packstore.rollback(store, "p")
    assert store.execute("SELECT version FROM packs").fetchone()[0] == "1.0.0"
    assert store.execute("SELECT title FROM claim_text").fetchone()[0] == "one"
    after_second = {
        row["version"]: row["activated_at"]
        for row in packstore.revisions(store, "p")
    }
    assert after_second["2.0.0"] == after_first["2.0.0"]
    assert after_second["1.0.0"] > initial["1.0.0"]
    assert [r["action"] for r in packstore.events(store, "p")] == [
        "install",
        "update",
        "update",
        "rollback",
        "rollback",
    ]


def test_activation_rejects_an_incomplete_snapshot_without_changing_active_rows(
    store, tmp_path
):
    packstore.install(
        store,
        _pack(tmp_path, "p", [("one", "high")], version="1.0.0", digest="a" * 64),
    )
    packstore.install(
        store,
        _pack(tmp_path, "p", [("two", "high")], version="2.0.0", digest="b" * 64),
    )
    store.execute(
        "DELETE FROM pack_revision_rows WHERE revision_id = ? AND table_name = 'claims'",
        ("p@" + "a" * 64,),
    )
    store.commit()

    with pytest.raises(ValueError, match="incomplete snapshot"):
        packstore.activate(store, "p", "a" * 64)

    assert store.execute("SELECT version FROM packs").fetchone()[0] == "2.0.0"
    assert store.execute("SELECT title FROM claim_text").fetchone()[0] == "two"


def test_activation_can_select_a_revision_by_digest(store, tmp_path):
    packstore.install(
        store, _pack(tmp_path, "p", [], version="1.0.0", digest="a" * 64)
    )
    packstore.install(
        store, _pack(tmp_path, "p", [], version="2.0.0", digest="b" * 64)
    )
    packstore.activate(store, "p", "a" * 64)
    assert store.execute("SELECT version FROM packs").fetchone()[0] == "1.0.0"


def test_install_is_atomic(store, tmp_path, monkeypatch):
    """A failure mid-install must leave no half-installed pack behind."""
    packstore.install(store, _pack(tmp_path, "p", [("Chuck bearing wear", "high")]))
    before = {t: _rows(store, t) for t in packstore.PACK_TABLES}

    real = packstore._copy_table

    def boom(conn, table, pack_id):
        if table == "claims":
            raise sqlite3.OperationalError("simulated failure")
        return real(conn, table, pack_id)

    monkeypatch.setattr(packstore, "_copy_table", boom)
    with pytest.raises(sqlite3.OperationalError):
        packstore.install(store, _pack(tmp_path, "q", [("Chuck housing crack", "low")]))

    assert {t: _rows(store, t) for t in packstore.PACK_TABLES} == before
