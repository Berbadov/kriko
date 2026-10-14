"""Durable request, attempt, and provenance records for agent work.

The ledger lives in ``app.sqlite`` beside jobs. Request inputs and snapshots
are immutable; attempts record what may have reached a paid provider, and a
terminal run can only be closed once. The module intentionally has no provider
or pack dependencies so every interface can use the same record.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    client_request_id TEXT UNIQUE,
    job_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    input_json TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',
    outcome TEXT NOT NULL DEFAULT '',
    result_json TEXT,
    result_digest TEXT NOT NULL DEFAULT '',
    coverage_json TEXT NOT NULL DEFAULT '{}',
    query_ids_json TEXT NOT NULL DEFAULT '[]',
    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    usage_json TEXT NOT NULL DEFAULT '{}',
    terminal_at TEXT,
    recovery_action_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS agent_runs_created ON agent_runs(created_at DESC);
CREATE TRIGGER IF NOT EXISTS agent_runs_manifest_immutable
BEFORE UPDATE OF client_request_id, job_id, kind, input_hash, input_json, snapshot_json, created_at
ON agent_runs
BEGIN
    SELECT RAISE(ABORT, 'agent run manifest is immutable');
END;
CREATE TABLE IF NOT EXISTS agent_attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    ordinal INTEGER NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    request_json TEXT NOT NULL,
    delivery TEXT NOT NULL,
    context_id TEXT NOT NULL DEFAULT '',
    turn_id TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    outcome TEXT NOT NULL DEFAULT '',
    result_digest TEXT NOT NULL DEFAULT '',
    usage_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    finished_at TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(run_id, ordinal)
);
CREATE INDEX IF NOT EXISTS agent_attempts_run ON agent_attempts(run_id, ordinal);
CREATE TABLE IF NOT EXISTS agent_run_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id),
    created_at TEXT NOT NULL,
    event TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS agent_run_log_run ON agent_run_log(run_id, seq);
"""

DELIVERIES = frozenset({"not_sent", "rejected", "accepted", "unknown"})
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "interrupted", "partial"})


class RequestConflict(ValueError):
    """A client request ID was reused for different canonical input."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def request_hash(payload: Any) -> str:
    """SHA-256 over stable JSON, independent of mapping insertion order."""
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


_SECRET_KEYS = frozenset({"authorization", "api_key", "x_api_key", "apikey", "token",
                          "secret", "api_secret", "client_secret", "password", "credential",
                          "access_token", "refresh_token", "bearer"})
_SECRET_TEXT = re.compile(
    r"(?i)(authorization|x-api-key|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password|secret)(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_TEXT = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def _safe_text(value: Any, limit: int = 1000) -> str:
    text = str(value or "")
    text = _SECRET_TEXT.sub(r"\1\2[redacted]", text)
    text = _BEARER_TEXT.sub("Bearer [redacted]", text)
    return text[:limit]


def _safe_diagnostic(value: Any, *, max_chars: int = 4000) -> str:
    """Bound provider diagnostics and remove values under credential-like keys."""
    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {str(key): ("[redacted]" if str(key).lower().replace("-", "_") in _SECRET_KEYS
                               else clean(child)) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [clean(child) for child in item[:100]]
        if isinstance(item, str):
            return _safe_text(item)
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return str(item)[:1000]

    try:
        encoded = _json(clean(value))
        if len(encoded) > max_chars:
            return _json({"truncated": True, "preview": encoded[:max_chars - 64]})
        return encoded
    except (TypeError, ValueError):
        return "{}"


def _result_facts(result: dict | None) -> tuple[dict, list, list]:
    source: dict[str, Any] = result if isinstance(result, dict) else {}
    candidate = source.get("coverage")
    coverage = candidate if isinstance(candidate, dict) else {}
    queries = source.get("query_ids", source.get("queries", []))
    evidence = source.get("evidence_ids", source.get("evidence_pages", []))

    def identities(items: Any) -> list[Any]:
        if not isinstance(items, list):
            return []
        out: list[Any] = []
        for item in items:
            if isinstance(item, (str, int, float)):
                out.append(item)
            elif isinstance(item, dict):
                identity = item.get("id") or item.get("query_id") or item.get("url") or item.get("source_id")
                if identity is not None:
                    out.append(identity)
        return out

    return coverage, identities(queries), identities(evidence)


class Ledger:
    """SQLite-backed request ledger. ``db_path`` is app_state_path."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        conn = self.connect()
        try:
            with conn:
                conn.executescript(SCHEMA)
                # CREATE TABLE IF NOT EXISTS does not add columns to an existing
                # app.sqlite, so keep this small migration repeatable as well.
                present = {row[1] for row in conn.execute("PRAGMA table_info(agent_attempts)")}
                for name, declaration in (
                    ("outcome", "TEXT NOT NULL DEFAULT ''"),
                    ("result_digest", "TEXT NOT NULL DEFAULT ''"),
                    ("usage_json", "TEXT NOT NULL DEFAULT '{}'"),
                    ("error", "TEXT NOT NULL DEFAULT ''"),
                    ("finished_at", "TEXT"),
                ):
                    if name not in present:
                        conn.execute(f"ALTER TABLE agent_attempts ADD COLUMN {name} {declaration}")
                run_columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_runs)")}
                if "recovery_action_json" not in run_columns:
                    conn.execute("ALTER TABLE agent_runs ADD COLUMN recovery_action_json TEXT NOT NULL DEFAULT '{}'")
        finally:
            conn.close()

    @staticmethod
    def request_hash(payload: Any) -> str:
        return request_hash(payload)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15, isolation_level="DEFERRED")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def reserve(self, client_request_id: str | None, kind: str, payload: dict,
                snapshot: dict | None = None, *, job_id: str | None = None) -> dict:
        """Reserve a manifest, returning an existing identical request atomically.

        Job callers should use ``reserve_job`` to insert the job and manifest
        in one transaction. ``reserve`` is useful for callers without a jobs
        row and creates a stable internal job ID when omitted.
        """
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            with conn:
                return self._reserve(conn, client_request_id, kind,
                                     {"kind": kind, "params": payload}, snapshot, job_id)
        finally:
            conn.close()

    def reserve_job(self, conn: sqlite3.Connection, client_request_id: str | None,
                    kind: str, params: dict, snapshot: dict | None = None) -> dict:
        """Create a jobs row and its immutable run manifest in one transaction."""
        from app.web import state

        job_id = secrets.token_hex(8)
        input_value = {"kind": kind, "params": params}
        conn.execute("BEGIN IMMEDIATE")
        with conn:
            if client_request_id:
                old = conn.execute(
                    "SELECT * FROM agent_runs WHERE client_request_id = ?",
                    (client_request_id,),
                ).fetchone()
                if old:
                    if old["input_hash"] != request_hash(input_value):
                        raise RequestConflict("client_request_id already names different input")
                    return self._run_dict(old, created=False)
            conn.execute(
                "INSERT INTO jobs (job_id, kind, params_json, state, created_at) VALUES (?, ?, ?, ?, ?)",
                (job_id, kind, json.dumps(params, default=str), state.QUEUED, _now()),
            )
            return self._reserve(conn, client_request_id, kind, input_value, snapshot, job_id)

    def _reserve(self, conn: sqlite3.Connection, client_request_id: str | None,
                 kind: str, payload: dict, snapshot: dict | None,
                 job_id: str | None) -> dict:
        if client_request_id:
            old = conn.execute(
                "SELECT * FROM agent_runs WHERE client_request_id = ?", (client_request_id,)
            ).fetchone()
            if old:
                if old["input_hash"] != request_hash(payload):
                    raise RequestConflict("client_request_id already names different input")
                return self._run_dict(old, created=False)
        run_id = secrets.token_hex(16)
        job_id = job_id or secrets.token_hex(8)
        digest = request_hash(payload)
        conn.execute(
            "INSERT INTO agent_runs(run_id, client_request_id, job_id, kind, input_hash,"
            " input_json, snapshot_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, client_request_id or None, job_id, kind, digest,
             _json(payload), _json(snapshot or {}), _now()),
        )
        conn.execute("INSERT INTO agent_run_log(run_id,created_at,event,data_json) VALUES(?,?,?,?)",
                      (run_id, _now(), "reserved", _json({"kind": kind, "job_id": job_id})))
        return {"created": True, "run_id": run_id, "request_id": client_request_id or run_id,
                "job_id": job_id, "input_hash": digest}

    def start_attempt(self, run_id: str, provider: str = "", model: str = "",
                      request: Any = None) -> str:
        attempt_id = secrets.token_hex(12)
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            with conn:
                run = conn.execute("SELECT terminal_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                if not run:
                    raise KeyError(run_id)
                if run["terminal_at"]:
                    raise ValueError("run is terminal")
                ordinal = conn.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM agent_attempts WHERE run_id=?",
                                       (run_id,)).fetchone()[0]
                now = _now()
                conn.execute(
                    "INSERT INTO agent_attempts(attempt_id,run_id,ordinal,provider,model,request_json,delivery,started_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,'not_sent',?,?)",
                    (attempt_id, run_id, ordinal, provider, model,
                     _safe_diagnostic(request or {}, max_chars=20_000), now, now),
                )
                self._log(conn, run_id, "attempt_started", {"attempt_id": attempt_id, "ordinal": ordinal})
            return attempt_id
        finally:
            conn.close()

    def mark_sending(self, attempt_id: str) -> bool:
        """Mark the uncertain boundary just before request bytes are written."""
        return self.update_delivery(attempt_id, "unknown", detail={"phase": "sending"})

    def update_delivery(self, attempt_id: str, status: str, context_id: str = "",
                        turn_id: str = "", detail: Any = None) -> bool:
        if status not in DELIVERIES:
            raise ValueError(f"unknown delivery status {status!r}")
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            with conn:
                row = conn.execute("SELECT run_id,delivery,finished_at FROM agent_attempts WHERE attempt_id=?",
                                   (attempt_id,)).fetchone()
                if not row or row["finished_at"]:
                    return False
                allowed_from = {
                    "not_sent": DELIVERIES,
                    "unknown": frozenset({"unknown", "accepted", "rejected"}),
                    "accepted": frozenset({"accepted"}),
                    "rejected": frozenset({"rejected"}),
                }
                if status not in allowed_from.get(row["delivery"], frozenset()):
                    return False
                cur = conn.execute(
                    "UPDATE agent_attempts SET delivery=?, context_id=CASE WHEN ?='' THEN context_id ELSE ? END,"
                    " turn_id=CASE WHEN ?='' THEN turn_id ELSE ? END, detail_json=?, updated_at=?"
                    " WHERE attempt_id=? AND finished_at IS NULL AND delivery=?",
                    (status, context_id, context_id, turn_id, turn_id,
                     _safe_diagnostic(detail or {}), _now(), attempt_id, row["delivery"]),
                )
                if not cur.rowcount:
                    return False
                self._log(conn, row["run_id"], "delivery_updated", {
                    "attempt_id": attempt_id, "status": status,
                    "context_id": context_id, "turn_id": turn_id,
                })
            return True
        finally:
            conn.close()

    def finish_attempt(self, attempt_id: str, outcome: str, *, usage: dict | None = None,
                       result: Any = None, error: str = "") -> bool:
        """Record an attempt's completion without closing its parent run."""
        conn = self.connect()
        try:
            with conn:
                row = conn.execute("SELECT run_id FROM agent_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
                if not row:
                    return False
                cur = conn.execute(
                    "UPDATE agent_attempts SET outcome=?, result_digest=?, usage_json=?, error=?, finished_at=?, updated_at=?"
                    " WHERE attempt_id=? AND finished_at IS NULL",
                    (str(outcome), _digest(result) if result is not None else "", _safe_diagnostic(usage or {}),
                     _safe_text(error), _now(), _now(), attempt_id),
                )
                if cur.rowcount:
                    self._log(conn, row["run_id"], "attempt_finished",
                              {"attempt_id": attempt_id, "outcome": outcome})
            return bool(cur.rowcount)
        finally:
            conn.close()

    def checkpoint(self, run_id: str, result: dict, *, usage: dict | None = None) -> bool:
        """Persist a useful partial result while keeping the manifest immutable."""
        coverage, queries, evidence = _result_facts(result)
        conn = self.connect()
        try:
            with conn:
                row = conn.execute("SELECT terminal_at FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                if not row or row["terminal_at"]:
                    return False
                conn.execute(
                    "UPDATE agent_runs SET state='partial', result_json=?, result_digest=?, coverage_json=?,"
                    " query_ids_json=?, evidence_ids_json=?, usage_json=? WHERE run_id=? AND terminal_at IS NULL",
                    (_json(result), _digest(result), _json(coverage), _json(queries), _json(evidence),
                     _json(usage or {}), run_id),
                )
                self._log(conn, run_id, "checkpoint", {"result_digest": _digest(result)})
            return True
        finally:
            conn.close()

    def finish(self, run_id: str, outcome: str, result: dict | None = None,
               usage: dict | None = None) -> bool:
        """Close once; late success/failure cannot overwrite a terminal outcome."""
        normalized = outcome.lower()
        if normalized not in TERMINAL:
            raise ValueError(f"unknown terminal outcome {outcome!r}")
        conn = self.connect()
        try:
            with conn:
                if result is None:
                    existing = conn.execute("SELECT result_json FROM agent_runs WHERE run_id=?",
                                            (run_id,)).fetchone()
                    if existing and existing["result_json"]:
                        result = json.loads(existing["result_json"])
                coverage, queries, evidence = _result_facts(result)
                cur = conn.execute(
                    "UPDATE agent_runs SET state=?, outcome=?, result_json=COALESCE(?,result_json),"
                    " result_digest=CASE WHEN ? IS NULL THEN result_digest ELSE ? END, coverage_json=?,"
                    " query_ids_json=?, evidence_ids_json=?, usage_json=CASE WHEN ?='{}' THEN usage_json ELSE ? END,"
                    " terminal_at=? WHERE run_id=? AND terminal_at IS NULL",
                    (normalized, normalized, _json(result) if result is not None else None,
                     _json(result) if result is not None else None, _digest(result) if result is not None else "",
                     _json(coverage), _json(queries), _json(evidence), _json(usage or {}),
                     _json(usage or {}), _now(), run_id),
                )
                if cur.rowcount:
                    self._log(conn, run_id, "finished", {"outcome": normalized})
            return bool(cur.rowcount)
        finally:
            conn.close()

    def recover(self) -> dict:
        """Classify unfinished runs; potentially sent calls require reconciliation."""
        conn = self.connect()
        try:
            retry: list[str] = []
            reconcile: list[str] = []
            actions: list[dict[str, Any]] = []
            conn.execute("BEGIN IMMEDIATE")
            with conn:
                rows = conn.execute("SELECT * FROM agent_runs WHERE terminal_at IS NULL").fetchall()
                for row in rows:
                    deliveries = [item[0] for item in conn.execute(
                        "SELECT delivery FROM agent_attempts WHERE run_id=? ORDER BY ordinal",
                        (row["run_id"],))]
                    delivery = deliveries[-1] if deliveries else "not_sent"
                    job = None
                    try:
                        job = conn.execute("SELECT state,result_json FROM jobs WHERE job_id=?",
                                           (row["job_id"],)).fetchone()
                    except sqlite3.Error:
                        pass
                    if job and str(job["state"]).lower() in TERMINAL:
                        outcome = str(job["state"]).lower()
                        result_json = job["result_json"] or row["result_json"]
                        result = json.loads(result_json) if result_json else None
                        coverage, queries, evidence = _result_facts(result)
                        action = {"action": "job_terminal", "job_state": outcome,
                                  "delivery": delivery}
                        cur = conn.execute(
                            "UPDATE agent_runs SET state=?,outcome=?,result_json=COALESCE(?,result_json),"
                            "result_digest=CASE WHEN ? IS NULL THEN result_digest ELSE ? END,coverage_json=?,"
                            "query_ids_json=?,evidence_ids_json=?,terminal_at=?,recovery_action_json=? "
                            "WHERE run_id=? AND terminal_at IS NULL",
                            (outcome, outcome, _json(result) if result is not None else None,
                             _json(result) if result is not None else None,
                             _digest(result) if result is not None else "", _json(coverage),
                             _json(queries), _json(evidence), _now(), _json(action), row["run_id"]),
                        )
                    else:
                        action_name = ("reconcile" if any(item in ("accepted", "unknown")
                                                          for item in deliveries) else "retry")
                        (reconcile if action_name == "reconcile" else retry).append(row["run_id"])
                        action = {"action": action_name, "delivery": delivery,
                                  "automatic_replay": False}
                        cur = conn.execute(
                            "UPDATE agent_runs SET state='interrupted',outcome='interrupted',terminal_at=?,"
                            "recovery_action_json=? WHERE run_id=? AND terminal_at IS NULL",
                            (_now(), _json(action), row["run_id"]),
                        )
                    if cur.rowcount:
                        actions.append({"run_id": row["run_id"], **action})
                        self._log(conn, row["run_id"], "recovered", action)
            return {"retry": retry, "reconcile": reconcile, "actions": actions}
        finally:
            conn.close()

    def lookup(self, run_id: str | None = None, *, client_request_id: str | None = None) -> dict | None:
        if not run_id and not client_request_id:
            raise ValueError("run_id or client_request_id is required")
        conn = self.connect()
        try:
            key, value = ("run_id", run_id) if run_id else ("client_request_id", client_request_id)
            row = conn.execute(f"SELECT * FROM agent_runs WHERE {key}=?", (value,)).fetchone()
            if not row:
                return None
            out = self._run_dict(row)
            out["attempts"] = self.attempts(out["run_id"], limit=100)
            return out
        finally:
            conn.close()

    def lookup_job(self, job_id: str) -> dict | None:
        conn = self.connect()
        try:
            row = conn.execute("SELECT * FROM agent_runs WHERE job_id=?", (job_id,)).fetchone()
            return self._run_dict(row) if row else None
        finally:
            conn.close()

    def manifest(self, run_id: str) -> dict | None:
        found = self.lookup(run_id)
        return {key: found[key] for key in ("run_id", "request_id", "job_id", "kind", "input_hash",
                                             "input", "snapshot", "created_at", "state", "outcome",
                                             "result_digest", "coverage", "query_ids", "evidence_ids", "usage",
                                             "terminal_at", "recovery_action") } if found else None

    def attempts(self, run_id: str, *, limit: int = 50) -> list[dict]:
        conn = self.connect()
        try:
            return [self._attempt_dict(row) for row in conn.execute(
                "SELECT * FROM agent_attempts WHERE run_id=? ORDER BY ordinal LIMIT ?",
                (run_id, max(0, min(int(limit), 200)),),
            )]
        finally:
            conn.close()

    def logs(self, run_id: str, *, cursor: int = 0, limit: int = 100) -> dict:
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT seq,created_at,event,data_json FROM agent_run_log WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                (run_id, max(0, cursor), max(0, min(int(limit), 500))),
            ).fetchall()
            events = [{"seq": row["seq"], "created_at": row["created_at"], "event": row["event"],
                       "data": json.loads(row["data_json"])} for row in rows]
            return {"events": events, "next_cursor": events[-1]["seq"] if events else cursor}
        finally:
            conn.close()

    @staticmethod
    def _log(conn: sqlite3.Connection, run_id: str, event: str, data: dict) -> None:
        conn.execute("INSERT INTO agent_run_log(run_id,created_at,event,data_json) VALUES(?,?,?,?)",
                     (run_id, _now(), event, _json(data)))

    @staticmethod
    def _run_dict(row: sqlite3.Row, *, created: bool = False) -> dict:
        return {"created": created, "run_id": row["run_id"],
                "request_id": row["client_request_id"] or row["run_id"],
                "job_id": row["job_id"], "kind": row["kind"], "input_hash": row["input_hash"],
                "input": json.loads(row["input_json"]), "snapshot": json.loads(row["snapshot_json"]),
                "created_at": row["created_at"], "state": row["state"], "outcome": row["outcome"],
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "result_digest": row["result_digest"], "coverage": json.loads(row["coverage_json"]),
                "query_ids": json.loads(row["query_ids_json"]),
                "evidence_ids": json.loads(row["evidence_ids_json"]),
                "usage": json.loads(row["usage_json"]), "terminal_at": row["terminal_at"],
                "recovery_action": json.loads(row["recovery_action_json"])}

    @staticmethod
    def _attempt_dict(row: sqlite3.Row) -> dict:
        return {"attempt_id": row["attempt_id"], "run_id": row["run_id"],
                "ordinal": row["ordinal"], "provider": row["provider"], "model": row["model"],
                "request": json.loads(row["request_json"]), "delivery": row["delivery"],
                "context_id": row["context_id"], "turn_id": row["turn_id"],
                "detail": json.loads(row["detail_json"]), "started_at": row["started_at"],
                "updated_at": row["updated_at"], "outcome": row["outcome"],
                "result_digest": row["result_digest"], "usage": json.loads(row["usage_json"]),
                "error": row["error"], "finished_at": row["finished_at"]}
