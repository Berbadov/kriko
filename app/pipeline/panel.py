"""panel.py — read-only pipeline + cost dashboard (stdlib only).

One screen answering the two questions that matter for a student budget:
"what is the pipeline doing" and "what would it cost to finish it". Reads the
ledger DB and the telemetry logs; touches nothing.

    python -m app.pipeline.panel
    python -m app.pipeline.panel --db path/to/ledger.db

Sections:
  1. Spend       — total $, by stage, by model, verdict import-vs-LLM split
  2. Pending     — docs/evidence/clusters/verdicts state + the EXACT $ to
                   finish (extract --dry-run + verdict --dry-run estimates)
  3. Catalog     — export part count/claims + coverage findings
  4. Activity    — recent runs + last remediation line
  5. Guardrails  — the commands that spend nothing or nearly nothing

The pending-USD figures ARE the dry-run estimates the real run uses, so the
panel's numbers are the same numbers the budget cap enforces.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from kriko.ledger import db
from kriko.ledger.costs import log_stage  # noqa: F401 — re-exported usage hint

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = db.LEDGER_PATH
REMEDIATION_LOG = REPO_ROOT / "logs" / "remediation.jsonl"
ANALYSES_LOG = REPO_ROOT / "logs" / "analyses.jsonl"

_SECTION = "─" * 64


def _money(x: float) -> str:
    return f"${x:,.4f}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def spend_section(conn) -> list[str]:
    lines = ["\n1. SPEND"]
    rows = conn.execute(
        "SELECT stage, model, SUM(calls), SUM(tokens_in), SUM(tokens_out),"
        " SUM(usd) FROM runs GROUP BY stage, model ORDER BY SUM(usd) DESC").fetchall()
    if not rows:
        lines.append("  no runs recorded yet — nothing has ever been spent")
        return lines
    total = 0.0
    for stage, model, calls, tin, tout, usd in rows:
        total += usd
        lines.append(f"  {stage:<12} {model:<20} calls={calls:>5} "
                     f"in={tin:>9} out={tout:>9} {_money(usd)}")
    imp = conn.execute("SELECT COUNT(*) FROM verdicts WHERE model='import'").fetchone()[0]
    llm = conn.execute("SELECT COUNT(*) FROM verdicts WHERE model!='import'").fetchone()[0]
    lines.append(f"  {'TOTAL':<12} {'':<20} {'':>5} {'':>9} {'':>9} {_money(total)}")
    lines.append(f"  verdicts: {imp} import ($0 each) + {llm} LLM")
    return lines


def pending_section(conn) -> list[str]:
    lines = ["\n2. PIPELINE STATE + COST TO FINISH"]
    n_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    n_ev = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    n_cl = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
    n_vr = conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0]
    lines.append(f"  documents={n_docs} evidence={n_ev} clusters={n_cl} verdicts={n_vr}")

    from packs.cars.pipeline.ledger.extraction import pending_extraction_estimate
    n_chunks, usd_extract = pending_extraction_estimate(conn)

    from packs.cars.pipeline.ledger.verdict import (DETERMINISTIC_VERSIONS,
                                          _evidence_versions, cluster_payload,
                                          input_hash, pending_verdict_estimate)
    n_pending, usd_verdict = pending_verdict_estimate(conn)
    import_ready = mixed = 0
    for row in conn.execute("SELECT id FROM clusters ORDER BY id"):
        payload = cluster_payload(conn, row["id"])
        if conn.execute("SELECT 1 FROM verdicts WHERE input_hash=?",
                        (input_hash(payload),)).fetchone():
            continue
        if _evidence_versions(conn, row["id"]) <= DETERMINISTIC_VERSIONS:
            import_ready += 1
        else:
            mixed += 1
    lines.append(f"  pending extraction: {n_chunks} chunk call(s) ≈ {_money(usd_extract)}")
    lines.append(f"  pending verdicts:   {n_pending} ({import_ready} import-ready at $0, "
                 f"{mixed} mixed/LLM) ≈ {_money(usd_verdict)}")
    lines.append(f"  COST TO FINISH:    ≈ {_money(usd_extract + usd_verdict)}"
                 f" (of which ~{_money(usd_verdict)} is LLM)")
    return lines


def catalog_section(data_dir: Path) -> list[str]:
    lines = ["\n3. CATALOG"]
    from packs.cars.coverage import build_report
    report = build_report(data_dir / "variants", data_dir / "fitment", data_dir / "parts")
    n_parts = n_claims = 0
    for p in sorted((data_dir / "parts").rglob("*.yaml")):
        try:
            import yaml
            data = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if isinstance(data, dict) and data.get("part_id"):
            n_parts += 1
            n_claims += len(data.get("claims") or [])
    lines.append(f"  serving parts={n_parts} claims={n_claims} "
                 f"coverage findings={len(report.findings)}")
    for kind, items in sorted(report.grouped().items()):
        lines.append(f"    {kind}: {len(items)}")
    return lines


def activity_section(conn, lines_out: int = 5) -> list[str]:
    lines = [f"\n4. RECENT ACTIVITY (last {lines_out} runs)"]
    for r in conn.execute(
        "SELECT started_at, stage, model, calls, usd FROM runs"
        " ORDER BY started_at DESC LIMIT ?", (lines_out,)):
        lines.append(f"  {r['started_at']} {r['stage']:<12} {r['model'] or '-':<20} "
                     f"{r['calls']} calls {_money(r['usd'])}")
    if REMEDIATION_LOG.exists():
        rows = [json.loads(l) for l in REMEDIATION_LOG.read_text().splitlines() if l.strip()]
        if rows:
            last = rows[-1]
            lines.append(f"  last remediation ({last.get('ts', '?')}): "
                         f"{len(last.get('parts') or [])} part(s) re-researched, "
                         f"+{last.get('ingested', 0)} docs, "
                         f"lost-source pages +{last.get('lost_ingested', 0)}, "
                         f"{_money(last.get('usd', 0.0))}")
    return lines


def guardrails_section() -> list[str]:
    lines = ["\n5. GUARDRAILS (nothing here spends more than cents)"]
    lines.append("  estimate before spending:  python -m app.pipeline.panel")
    lines.append("  remediate (import-only, $0):  python -m app.pipeline.ledger_run remediate")
    lines.append("  paid research (explicit):    python -m app.pipeline.ledger_run remediate --max-usd 0.10")
    lines.append("  dry-runs:                    python -m app.pipeline.ledger_run extract --dry-run")
    lines.append("                               python -m app.pipeline.ledger_run verdict --dry-run")
    lines.append("  coverage:                    python -m packs.cars.coverage")
    return lines


def render(conn, data_dir: Path = REPO_ROOT / "packs" / "cars" / "data") -> str:
    sections = [
        [_SECTION, f"KRIKO PIPELINE PANEL — {_now_iso()}",
         f"ledger: {conn.execute('SELECT 1').fetchone() and 'connected'}",
         _SECTION],
        *[s(conn) for s in (spend_section, pending_section)],
        catalog_section(data_dir),
        activity_section(conn),
        guardrails_section(),
        [_SECTION],
    ]
    return "\n".join(line for sec in sections for line in sec)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--data-dir", type=Path, default=REPO_ROOT / "packs" / "cars" / "data")
    args = p.parse_args(argv)
    conn = db.connect(args.db)
    conn.row_factory = __import__("sqlite3").Row
    print(render(conn, args.data_dir))
    conn.close()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
