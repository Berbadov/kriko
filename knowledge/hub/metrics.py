"""kriko-hub metrics — pure data access for the desktop dashboard.

Every function is read-only and GUI-free, so tests can pin the numbers the
dashboard shows. The figures come from the same tables and the same estimate
functions the CLI panel uses (knowledge/ledger/panel.py) — a number in the
hub is the number the budget caps enforce.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from knowledge.ledger import db, verdict


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ledger_counts(conn) -> dict:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("documents", "evidence", "clusters", "verdicts")}


def spend(conn) -> dict:
    rows = [dict(r) for r in conn.execute(
        "SELECT stage, model, SUM(calls) calls, SUM(tokens_in) tokens_in,"
        " SUM(tokens_out) tokens_out, SUM(usd) usd FROM runs"
        " GROUP BY stage, model ORDER BY SUM(usd) DESC")]
    total = sum(r["usd"] for r in rows)
    imp = conn.execute("SELECT COUNT(*) FROM verdicts WHERE model='import'"
                       ).fetchone()[0]
    llm = conn.execute("SELECT COUNT(*) FROM verdicts WHERE model!='import'"
                       ).fetchone()[0]
    return {"rows": rows, "total_usd": total, "verdicts_import": imp,
            "verdicts_llm": llm}


def pending(conn) -> dict:
    from knowledge.ledger.extraction import pending_extraction_estimate
    chunks, usd_extract = pending_extraction_estimate(conn)
    n, usd_verdict = verdict.pending_verdict_estimate(conn)
    import_ready = llm = 0
    for cid, payload, h in verdict.pending_clusters(conn):
        if verdict._evidence_versions(conn, cid) <= verdict.DETERMINISTIC_VERSIONS:
            import_ready += 1
        else:
            llm += 1
    return {"extract_chunks": chunks, "extract_usd": usd_extract,
            "verdict_pending": n, "verdict_usd": usd_verdict,
            "import_ready": import_ready, "llm": llm}


def parts(data_dir: Path) -> list[dict]:
    import yaml
    out = []
    for path in sorted((data_dir / "parts").rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict) or not data.get("part_id"):
            continue
        out.append({"part_id": data["part_id"],
                    "part_type": path.parent.name,
                    "claims": len(data.get("claims") or [])})
    return out


def catalog_counts(data_dir: Path) -> dict:
    """Cheap catalog size snapshot for the overview KPIs (no report build)."""
    import yaml
    part_paths = list((data_dir / "parts").rglob("*.yaml"))
    claims = 0
    for p in part_paths:
        try:
            claims += len((yaml.safe_load(p.read_text()) or {}).get("claims")
                          or [])
        except yaml.YAMLError:
            pass
    return {"parts": len(part_paths),
            "variants": len(list((data_dir / "variants").rglob("*.yaml"))),
            "fitment": len(list((data_dir / "fitment").rglob("*.yaml"))),
            "claims": claims}


def part_detail(data_dir: Path, part_id: str) -> dict | None:
    import yaml
    path = next(((data_dir / "parts").rglob(f"{part_id}.yaml")), None)
    if not path:
        return None
    data = yaml.safe_load(path.read_text()) or {}
    claims = [{"title": c.get("title"), "severity": c.get("severity"),
               "domain": c.get("domain")}
              for c in data.get("claims") or []]
    variants = sorted((data_dir / "variants" / path.parent.name).glob(
        f"{part_id}*.yaml"))
    return {"part_id": part_id, "part_type": path.parent.name,
            "title": data.get("title", ""), "claims": claims,
            "variants": [p.stem for p in variants]}


def documents(conn, limit: int = 100) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, url, source_type, lang, target_hint, fetched_at"
        " FROM documents ORDER BY id DESC LIMIT ?", (int(limit),))]


def document(conn, doc_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return dict(r) if r else None


def recent_runs(conn, n: int = 6) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT started_at, stage, model, calls, usd FROM runs"
        " ORDER BY started_at DESC LIMIT ?", (int(n),))]


def last_remediation(log_path: Path) -> dict | None:
    if not log_path.exists():
        return None
    rows = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    return rows[-1] if rows else None


def findings(data_dir: Path) -> list[dict]:
    from backend.tools.coverage import build_report
    report = build_report(data_dir / "variants", data_dir / "fitment",
                          data_dir / "parts")
    return [{"kind": f.kind, "subject": f.subject, "message": f.message,
             "part_id": f.part_id, "axis": f.axis} for f in report.findings]
