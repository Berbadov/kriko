"""Install, enable, disable and uninstall packs.

A pack is a SQLite file carrying the same schema as the store (`schema.sql`), so
installing is a row copy rather than a translation. Every copied row keeps its
`pack_id`, which is what makes uninstall a `DELETE` and nothing more.

The one thing worth stating plainly, because it looks like a bug until you see
why: **two packs asserting the identical fact produce two rows, not one.** Their
content hashes agree, but `pack_id` is in the primary key, so they do not
collapse. If they did, uninstalling one pack would delete a fact the other still
asserts. Deduplication belongs at read time, where the agreeing hash makes it a
`GROUP BY`; it does not belong in storage, where it would destroy data.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from kriko.store.db import SCHEMA_VERSION

# Every table carrying a pack_id, in foreign-key-safe deletion order (children
# before parents). Uninstall walks this list; a table missing from it would
# silently orphan rows, so `test_uninstall_clears_every_table` iterates it.
PACK_TABLES = (
    "evidence",
    "sources",
    "claim_conditions",
    "claim_text",
    "claims",
    "relations",
    "attributes",
    "subject_aliases",
    "subjects",
    "term_aliases",
    "terms",
    "source_tiers",
    "tier_trust",
    "pack_assets",
    "packs",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_pack_row(conn, *, pack_id, name, version, content_digest,
                   publisher="", license="", origin_url="", manifest_json="{}") -> None:
    """Write a pack's own identity row. Used by the builder and by tests."""
    conn.execute(
        "INSERT OR REPLACE INTO packs (pack_id, name, version, schema_version,"
        " built_at, publisher, license, origin_url, content_digest, manifest_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (pack_id, name, version, SCHEMA_VERSION, _now(), publisher, license,
         origin_url, content_digest, manifest_json))


def _columns(conn, table) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _copy_table(conn, table, pack_id) -> int:
    """Copy one table's rows for `pack_id` from the attached pack into the store.

    `INSERT OR IGNORE` makes reinstalling the same pack a no-op rather than an
    error, which matters because upgrading a pack is install-over-install.
    """
    cols = ", ".join(_columns(conn, table))
    cur = conn.execute(
        f"INSERT OR IGNORE INTO main.{table} ({cols})"
        f" SELECT {cols} FROM pack.{table} WHERE pack_id = ?",
        (pack_id,))
    return cur.rowcount


def install(conn: sqlite3.Connection, pack_path) -> str:
    """Install a pack file into the store. Returns the installed `pack_id`.

    Atomic: a failure part-way through rolls back, so there is no such thing as
    a half-installed pack. Without that, a crash would leave subjects with no
    claims and the store would answer confidently with a truncated pack.
    """
    pack_path = Path(pack_path)
    if not pack_path.exists():
        raise FileNotFoundError(pack_path)

    conn.execute("ATTACH DATABASE ? AS pack", (str(pack_path),))
    try:
        pack_ids = [r[0] for r in conn.execute("SELECT pack_id FROM pack.packs")]
        if len(pack_ids) != 1:
            raise ValueError(
                f"{pack_path.name} declares {len(pack_ids)} packs; a pack file "
                "must declare exactly one"
            )
        pack_id = pack_ids[0]

        with conn:  # commits on success, rolls back on any exception
            for table in reversed(PACK_TABLES):  # parents before children
                _copy_table(conn, table, pack_id)
            conn.execute(
                "UPDATE packs SET installed_at = ?, enabled = 1 WHERE pack_id = ?",
                (_now(), pack_id))
            conn.execute(
                "INSERT OR IGNORE INTO pack_trust (pack_id, weight, pinned)"
                " VALUES (?, 1.0, 0)", (pack_id,))
        return pack_id
    finally:
        conn.execute("DETACH DATABASE pack")


def uninstall(conn: sqlite3.Connection, pack_id: str) -> None:
    """Remove a pack completely. Every other pack is untouched."""
    if not conn.execute(
            "SELECT 1 FROM packs WHERE pack_id = ?", (pack_id,)).fetchone():
        raise KeyError(f"pack not installed: {pack_id}")
    with conn:
        for table in PACK_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE pack_id = ?", (pack_id,))
        conn.execute("DELETE FROM pack_trust WHERE pack_id = ?", (pack_id,))


def set_enabled(conn: sqlite3.Connection, pack_id: str, enabled: bool) -> None:
    """Hide or restore a pack without destroying its rows.

    Disabling is the cheap, reversible half of uninstall — the reader tries a
    pack, decides against it, and turns it off. Re-enabling is free; reinstalling
    means fetching the file again.
    """
    if not conn.execute(
            "SELECT 1 FROM packs WHERE pack_id = ?", (pack_id,)).fetchone():
        raise KeyError(f"pack not installed: {pack_id}")
    with conn:
        conn.execute("UPDATE packs SET enabled = ? WHERE pack_id = ?",
                     (1 if enabled else 0, pack_id))


def enabled_pack_ids(conn: sqlite3.Connection) -> list[str]:
    """The packs reads should consult. Every query filters on this."""
    return [r[0] for r in conn.execute(
        "SELECT pack_id FROM packs WHERE enabled = 1 ORDER BY pack_id")]


def installed_packs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT p.*, COALESCE(t.weight, 1.0) AS trust_weight"
        " FROM packs p LEFT JOIN pack_trust t USING (pack_id)"
        " ORDER BY p.pack_id"))
