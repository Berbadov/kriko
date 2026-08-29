"""Install, revise, activate, rollback and uninstall packs.

The ``packs`` row is the active-read projection used by the lookup engine. Local
revision tables retain immutable content snapshots, so changing the active
revision never mutates or loses an installed pack. Lifecycle events are append
only and are intentionally queryable without involving an interface layer.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from kriko.store.db import SCHEMA_VERSION

# Every table carrying a pack_id, in foreign-key-safe deletion order (children
# before parents). The revision tables are local metadata, not pack contents.
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
    "gate_terms",
    "terms",
    "source_tiers",
    "tier_trust",
    "pack_assets",
    "packs",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _revision_id(pack_id: str, digest: str) -> str:
    return f"{pack_id}@{digest}"


def write_pack_row(
    conn,
    *,
    pack_id,
    name,
    version,
    content_digest,
    publisher="",
    license="",
    origin_url="",
    manifest_json="{}",
) -> None:
    """Write a pack's own identity row. Used by the builder and by tests."""
    conn.execute(
        "INSERT OR REPLACE INTO packs (pack_id, name, version, schema_version,"
        " built_at, publisher, license, origin_url, content_digest, manifest_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            pack_id,
            name,
            version,
            SCHEMA_VERSION,
            _now(),
            publisher,
            license,
            origin_url,
            content_digest,
            manifest_json,
        ),
    )


def _columns(conn, table) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _copy_table(conn, table, pack_id) -> int:
    """Copy one table's rows for ``pack_id`` from the attached pack."""
    cols = ", ".join(_columns(conn, table))
    cur = conn.execute(
        f"INSERT OR IGNORE INTO main.{table} ({cols})"
        f" SELECT {cols} FROM pack.{table} WHERE pack_id = ?",
        (pack_id,),
    )
    return cur.rowcount


def _clear_active(conn, pack_id: str) -> None:
    # Trust is local reader policy, not pack content.  It must survive changing
    # the active revision; uninstall is the operation that removes it.
    for table in PACK_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE pack_id = ?", (pack_id,))


def _snapshot(conn, revision_id: str, pack_id: str) -> None:
    """Persist the active rows once; existing revision content is immutable."""
    for table in PACK_TABLES:
        columns = _columns(conn, table)
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE pack_id = ?",
            (pack_id,),
        ).fetchall()
        conn.execute(
            "INSERT OR IGNORE INTO pack_revision_tables"
            " (revision_id, table_name, row_count) VALUES (?,?,?)",
            (revision_id, table, len(rows)),
        )
        for row_key, row in enumerate(rows):
            payload = json.dumps(
                dict(zip(columns, row)), sort_keys=True, separators=(",", ":")
            )
            conn.execute(
                "INSERT OR IGNORE INTO pack_revision_rows"
                " (revision_id, table_name, row_key, row_json) VALUES (?,?,?,?)",
                (revision_id, table, row_key, payload),
            )


def _save_revision(
    conn, row, *, snapshot_active: bool = True, activated: bool = False
) -> str:
    revision_id = _revision_id(row["pack_id"], row["content_digest"])
    conn.execute(
        "INSERT OR IGNORE INTO pack_revisions"
        " (revision_id, pack_id, version, content_digest, name, publisher,"
        " license, origin_url, manifest_json, installed_at, activated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            revision_id,
            row["pack_id"],
            row["version"],
            row["content_digest"],
            row["name"],
            row["publisher"],
            row["license"],
            row["origin_url"],
            row["manifest_json"],
            row["installed_at"] or _now(),
            _now() if activated else "",
        ),
    )
    if snapshot_active:
        _snapshot(conn, revision_id, row["pack_id"])
    return revision_id


def _event(conn, pack_id, action, row=None, *, details=None) -> None:
    row = row or {}
    if isinstance(row, sqlite3.Row):
        digest = row["content_digest"]
        version = row["version"]
    else:
        digest = row.get("content_digest", "")
        version = row.get("version", "")
    conn.execute(
        "INSERT INTO pack_events"
        " (pack_id, action, revision_id, version, content_digest, created_at, details_json)"
        " VALUES (?,?,?,?,?,?,?)",
        (
            pack_id,
            action,
            _revision_id(pack_id, digest) if digest else "",
            version,
            digest,
            _now(),
            json.dumps(details or {}, sort_keys=True, separators=(",", ":")),
        ),
    )


def install(conn: sqlite3.Connection, pack_path) -> str:
    """Install a new immutable revision, or update the active revision.

    Reinstalling the same digest is a no-op. A different digest for the same
    pack version is rejected: versions are immutable identifiers, not labels
    that can silently be republished.
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
        incoming = conn.execute(
            "SELECT * FROM pack.packs WHERE pack_id = ?", (pack_id,)
        ).fetchone()
        current = conn.execute(
            "SELECT * FROM packs WHERE pack_id = ?", (pack_id,)
        ).fetchone()
        same_version = conn.execute(
            "SELECT 1 FROM pack_revisions WHERE pack_id = ? AND version = ?"
            " AND content_digest != ? LIMIT 1",
            (pack_id, incoming["version"], incoming["content_digest"]),
        ).fetchone()
        if same_version or (
            current
            and current["version"] == incoming["version"]
            and current["content_digest"] != incoming["content_digest"]
        ):
            raise ValueError(
                f"pack {pack_id!r} version {incoming['version']!r} is immutable; "
                "the content digest differs"
            )
        same_digest = conn.execute(
            "SELECT version FROM pack_revisions WHERE pack_id = ?"
            " AND content_digest = ? LIMIT 1",
            (pack_id, incoming["content_digest"]),
        ).fetchone()
        if same_digest and same_digest["version"] != incoming["version"]:
            raise ValueError(
                f"pack {pack_id!r} digest {incoming['content_digest']!r} "
                "is already associated with another version"
            )

        with conn:
            if current and current["content_digest"] == incoming["content_digest"]:
                revision_id = _save_revision(conn, current)
                conn.execute(
                    "UPDATE packs SET enabled = 1 WHERE pack_id = ?", (pack_id,)
                )
                _event(
                    conn, pack_id, "enable", current, details={"reason": "reinstall"}
                )
                return pack_id

            if current:
                _save_revision(conn, current, activated=False)
            _clear_active(conn, pack_id)
            for table in reversed(PACK_TABLES):
                _copy_table(conn, table, pack_id)
            active = conn.execute(
                "SELECT * FROM packs WHERE pack_id = ?", (pack_id,)
            ).fetchone()
            conn.execute(
                "UPDATE packs SET installed_at = ?, enabled = 1 WHERE pack_id = ?",
                (_now(), pack_id),
            )
            revision_id = _save_revision(conn, active, activated=True)
            action = "update" if current else "install"
            _event(
                conn,
                pack_id,
                action,
                active,
                details={
                    "previous_revision": _revision_id(
                        current["pack_id"], current["content_digest"]
                    )
                    if current
                    else ""
                },
            )
        return pack_id
    finally:
        conn.execute("DETACH DATABASE pack")


def update(conn: sqlite3.Connection, pack_path) -> str:
    """Explicit spelling for a revision-changing install."""
    return install(conn, pack_path)


def _find_revision(conn, pack_id: str, selector=None):
    if selector is None:
        # Rollback means the revision installed immediately before the active
        # revision, not the newest revision that happens not to be active.  The
        # latter would jump forward after rolling back from the newest revision.
        return conn.execute(
            "SELECT previous.* FROM pack_revisions AS previous"
            " JOIN pack_revisions AS current"
            "   ON current.pack_id = previous.pack_id"
            "  AND current.content_digest = (SELECT content_digest FROM packs"
            "                               WHERE pack_id = ?)"
            " WHERE previous.pack_id = ?"
            "   AND (previous.installed_at < current.installed_at"
            "        OR (previous.installed_at = current.installed_at"
            "            AND previous.revision_id < current.revision_id))"
            " ORDER BY previous.installed_at DESC, previous.revision_id DESC"
            " LIMIT 1",
            (pack_id, pack_id),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM pack_revisions WHERE pack_id = ? AND"
        " (revision_id = ? OR content_digest = ? OR version = ?)"
        " ORDER BY installed_at DESC LIMIT 1",
        (pack_id, str(selector), str(selector), str(selector)),
    ).fetchone()


def _validate_snapshot(conn, revision) -> None:
    """Reject a partial or malformed revision before touching active rows."""
    manifest = conn.execute(
        "SELECT table_name, row_count FROM pack_revision_tables"
        " WHERE revision_id = ? ORDER BY table_name",
        (revision["revision_id"],),
    ).fetchall()
    if {row["table_name"] for row in manifest} != set(PACK_TABLES):
        raise ValueError(f"incomplete snapshot for revision {revision['revision_id']}")

    for entry in manifest:
        if entry["row_count"] < 0:
            raise ValueError(
                f"incomplete snapshot for revision {revision['revision_id']}"
            )
        count = conn.execute(
            "SELECT COUNT(*) FROM pack_revision_rows WHERE revision_id = ?"
            " AND table_name = ?",
            (revision["revision_id"], entry["table_name"]),
        ).fetchone()[0]
        if count != entry["row_count"]:
            raise ValueError(
                f"incomplete snapshot for revision {revision['revision_id']}"
            )
        keys = [
            row[0]
            for row in conn.execute(
                "SELECT row_key FROM pack_revision_rows"
                " WHERE revision_id = ? AND table_name = ? ORDER BY row_key",
                (revision["revision_id"], entry["table_name"]),
            )
        ]
        if keys != list(range(entry["row_count"])):
            raise ValueError(
                f"incomplete snapshot for revision {revision['revision_id']}"
            )
        for row in conn.execute(
            "SELECT row_json FROM pack_revision_rows"
            " WHERE revision_id = ? AND table_name = ? ORDER BY row_key",
            (revision["revision_id"], entry["table_name"]),
        ):
            try:
                payload = json.loads(row["row_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"malformed snapshot for revision {revision['revision_id']}"
                ) from exc
            if not isinstance(payload, dict):
                raise ValueError(
                    f"malformed snapshot for revision {revision['revision_id']}"
                )

    pack_rows = conn.execute(
        "SELECT row_json FROM pack_revision_rows WHERE revision_id = ?"
        " AND table_name = 'packs'",
        (revision["revision_id"],),
    ).fetchall()
    if len(pack_rows) != 1:
        raise ValueError(f"incomplete snapshot for revision {revision['revision_id']}")
    try:
        pack_data = json.loads(pack_rows[0]["row_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"malformed snapshot for revision {revision['revision_id']}"
        ) from exc
    if not isinstance(pack_data, dict) or (
        pack_data.get("pack_id") != revision["pack_id"]
        or pack_data.get("version") != revision["version"]
        or pack_data.get("content_digest") != revision["content_digest"]
    ):
        raise ValueError(
            f"snapshot metadata mismatch for revision {revision['revision_id']}"
        )


def activate(
    conn: sqlite3.Connection,
    pack_id: str,
    revision=None,
    *,
    _event_action: str | None = "activate",
) -> str:
    """Activate a retained revision by id, digest, or version."""
    current = conn.execute(
        "SELECT * FROM packs WHERE pack_id = ?", (pack_id,)
    ).fetchone()
    if not current:
        raise KeyError(f"pack not installed: {pack_id}")
    target = _find_revision(conn, pack_id, revision)
    if not target:
        raise KeyError(f"pack revision not found: {pack_id}: {revision}")
    # Validate before changing the active projection.  This also makes a
    # corrupted current snapshot observable instead of silently treating a
    # same-revision activation as a no-op.
    _validate_snapshot(conn, target)
    if target["content_digest"] == current["content_digest"]:
        return pack_id
    with conn:
        _save_revision(conn, current, activated=False)
        rows = conn.execute(
            "SELECT table_name, row_json FROM pack_revision_rows"
            " WHERE revision_id = ? ORDER BY table_name, row_key",
            (target["revision_id"],),
        ).fetchall()
        _clear_active(conn, pack_id)
        for table, payload in rows:
            data = json.loads(payload)
            columns = list(data)
            conn.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES"
                f" ({', '.join('?' for _ in columns)})",
                [data[c] for c in columns],
            )
        conn.execute(
            "UPDATE packs SET enabled = 1, installed_at = ? WHERE pack_id = ?",
            (_now(), pack_id),
        )
        conn.execute(
            "UPDATE pack_revisions SET activated_at = ? WHERE revision_id = ?",
            (_now(), target["revision_id"]),
        )
        if _event_action:
            _event(conn, pack_id, _event_action, target)
    return pack_id


def rollback(conn: sqlite3.Connection, pack_id: str, revision=None) -> str:
    """Activate the previous revision, or a specifically selected revision."""
    target = _find_revision(conn, pack_id, revision)
    if not target:
        raise KeyError(f"no rollback revision for pack: {pack_id}")
    result = activate(conn, pack_id, target["revision_id"], _event_action=None)
    row = conn.execute("SELECT * FROM packs WHERE pack_id = ?", (pack_id,)).fetchone()
    with conn:
        _event(
            conn,
            pack_id,
            "rollback",
            row,
            details={"to_revision": target["revision_id"]},
        )
    return result


def uninstall(conn: sqlite3.Connection, pack_id: str) -> None:
    """Remove a pack and its retained revisions completely."""
    current = conn.execute(
        "SELECT * FROM packs WHERE pack_id = ?", (pack_id,)
    ).fetchone()
    if not current:
        raise KeyError(f"pack not installed: {pack_id}")
    with conn:
        _event(conn, pack_id, "uninstall", current)
        for table in PACK_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE pack_id = ?", (pack_id,))
        conn.execute("DELETE FROM pack_trust WHERE pack_id = ?", (pack_id,))
        conn.execute(
            "DELETE FROM pack_revision_rows WHERE revision_id LIKE ?", (pack_id + "@%",)
        )
        conn.execute("DELETE FROM pack_revisions WHERE pack_id = ?", (pack_id,))


def set_enabled(conn, pack_id: str, enabled: bool) -> None:
    if not conn.execute("SELECT 1 FROM packs WHERE pack_id = ?", (pack_id,)).fetchone():
        raise KeyError(f"pack not installed: {pack_id}")
    with conn:
        conn.execute(
            "UPDATE packs SET enabled = ? WHERE pack_id = ?",
            (1 if enabled else 0, pack_id),
        )
        row = conn.execute(
            "SELECT * FROM packs WHERE pack_id = ?", (pack_id,)
        ).fetchone()
        _event(conn, pack_id, "enable" if enabled else "disable", row)


def enabled_pack_ids(conn) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT pack_id FROM packs WHERE enabled = 1 ORDER BY pack_id"
        )
    ]


def installed_packs(conn) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT p.*, COALESCE(t.weight, 1.0) AS trust_weight"
            " FROM packs p LEFT JOIN pack_trust t USING (pack_id) ORDER BY p.pack_id"
        )
    )


def revisions(conn, pack_id: str | None = None) -> list[sqlite3.Row]:
    """Return immutable installed revisions, newest first per pack."""
    if pack_id is None:
        return list(
            conn.execute("SELECT * FROM pack_revisions ORDER BY installed_at DESC")
        )
    return list(
        conn.execute(
            "SELECT * FROM pack_revisions WHERE pack_id = ? ORDER BY installed_at DESC",
            (pack_id,),
        )
    )


def events(conn, pack_id: str | None = None) -> list[sqlite3.Row]:
    """Return durable lifecycle events in chronological order."""
    if pack_id is None:
        return list(conn.execute("SELECT * FROM pack_events ORDER BY event_id"))
    return list(
        conn.execute(
            "SELECT * FROM pack_events WHERE pack_id = ? ORDER BY event_id", (pack_id,)
        )
    )
