"""Kriko MCP server — the ledger as tools for LLM-driven control (B21).

Stdio MCP server exposing the knowledge pipeline to agent hosts. OpenCode
registers it in `opencode.json` (`mcp.kriko`, type local); Claude Code via
`claude mcp add`.

This is the $0 plane of the pipeline by construction: every read tool exposes
state, every write tool is deterministic or import-only, and nothing here can
spend API tokens. Agent-written evidence (extractor_version=1) flows through
the same deterministic verdict path (verdict.import_verdicts) as imported
legacy research, so research performed by a flat-rate subscription LLM lands
as claims at zero marginal cost; the agent pass is still logged in `runs`
(model='agent', usd=0) so the cost panel stays honest.

Run directly to smoke-test:
    python -m knowledge.mcp.server

The handler functions are plain Python (FastMCP registers but does not wrap
them), so tests exercise the exact same code the agent calls.
"""

import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from knowledge.ledger import (
    cluster, db, export, remediate, resolve, verdict,
)
from knowledge.ledger.costs import log_stage

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEDGER_PATH = db.LEDGER_PATH
EXPORT_DIR = REPO_ROOT / "knowledge" / "ledger_export"
DATA_DIR = REPO_ROOT / "backend" / "data"
MAX_AGENT_SOURCES_PER_PART = 5  # per-part research budget for the agent loop

mcp = FastMCP("kriko", instructions=(
    "Kriko ledger control. Read tools report pipeline state and cost; write "
    "tools are all $0 (deterministic or import-only) — they never spend API "
    "tokens. add_evidence writes extractor_version=1 (agent) rows that the "
    "import verdict path treats like legacy research. Keep per-part research "
    f"to at most {MAX_AGENT_SOURCES_PER_PART} documents; target_hint should "
    "be the part_id being researched."))


def _conn() -> sqlite3.Connection:
    return db.connect(LEDGER_PATH)


def _parts(data_dir: Path = DATA_DIR) -> list[dict]:
    import yaml
    out = []
    for path in sorted((data_dir / "parts").rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict) or not data.get("part_id"):
            continue
        claims = data.get("claims") or []
        out.append({
            "part_id": data["part_id"],
            "part_type": path.parent.name,
            "claims": len(claims),
            "title": data.get("title", ""),
        })
    return out


# ── Read tools ────────────────────────────────────────────────────────────────


@mcp.tool()
def ledger_status() -> dict:
    """Table counts: documents, evidence, clusters, verdicts, plus spend rows."""
    conn = _conn()
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("documents", "evidence", "clusters", "verdicts")}
    finally:
        conn.close()


@mcp.tool()
def spend_summary() -> dict:
    """Lifetime spend grouped by stage+model, and the import-vs-LLM verdict split."""
    conn = _conn()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT stage, model, SUM(calls) calls, SUM(tokens_in) tokens_in,"
            " SUM(tokens_out) tokens_out, SUM(usd) usd FROM runs"
            " GROUP BY stage, model ORDER BY SUM(usd) DESC")]
        total = sum(r["usd"] for r in rows)
        imp = conn.execute(
            "SELECT COUNT(*) FROM verdicts WHERE model='import'").fetchone()[0]
        llm = conn.execute(
            "SELECT COUNT(*) FROM verdicts WHERE model!='import'").fetchone()[0]
        return {"rows": rows, "total_usd": round(total, 4),
                "verdicts_import": imp, "verdicts_llm": llm}
    finally:
        conn.close()


@mcp.tool()
def pending_extract() -> dict:
    """How many extraction chunk calls remain and their estimated USD."""
    conn = _conn()
    try:
        n, usd = __import__(
            "knowledge.ledger.extraction", fromlist=["pending_extraction_estimate"]
        ).pending_extraction_estimate(conn)
        return {"chunks": n, "est_usd": round(usd, 4)}
    finally:
        conn.close()


@mcp.tool()
def pending_verdicts() -> dict:
    """Pending verdict clusters split into deterministic ($0) and LLM-eligible."""
    conn = _conn()
    try:
        n, usd = verdict.pending_verdict_estimate(conn)
        import_ready = llm = 0
        for cid, payload, h in verdict.pending_clusters(conn):
            if verdict._evidence_versions(conn, cid) <= verdict.DETERMINISTIC_VERSIONS:
                import_ready += 1
            else:
                llm += 1
        return {"pending": n, "est_usd": round(usd, 4),
                "import_ready": import_ready, "llm": llm}
    finally:
        conn.close()


@mcp.tool()
def list_parts() -> list[dict]:
    """Serving catalog parts with claim counts, from backend/data/parts."""
    return _parts()


@mcp.tool()
def get_part(part_id: str) -> dict:
    """One part: claims summary, variants, and its coverage findings."""
    import yaml
    data_dir = DATA_DIR
    path = next(((data_dir / "parts").rglob(f"{part_id}.yaml")), None)
    if not path:
        return {"part_id": part_id, "error": "no part YAML found"}
    data = yaml.safe_load(path.read_text()) or {}
    claims = []
    for c in data.get("claims") or []:
        claims.append({
            "title": c.get("title"),
            "severity": c.get("severity"),
            "domain": c.get("domain"),
            "rationale": (c.get("rationale") or "")[:400],
        })
    variants = [p.stem for p in sorted(
        (data_dir / "variants" / path.parent.name).glob(f"{part_id}*.yaml"))]
    findings = [f for f in coverage_report() if f.get("part_id") == part_id]
    return {"part_id": part_id, "part_type": path.parent.name,
            "claims": claims, "variants": variants, "findings": findings}


@mcp.tool()
def list_documents(limit: int = 50, source_type: str | None = None) -> list[dict]:
    """Ledger documents (id, url, source_type, lang, target_hint), newest first."""
    conn = _conn()
    try:
        sql = ("SELECT id, url, source_type, site_or_channel, lang, target_hint,"
               " fetched_at FROM documents")
        args: list = []
        if source_type:
            sql += " WHERE source_type=?"
            args.append(source_type)
        sql += f" ORDER BY id DESC LIMIT {int(limit)}"
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


@mcp.tool()
def get_document(doc_id: int) -> dict:
    """Full document: url, provenance fields, and raw text."""
    conn = _conn()
    try:
        r = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return dict(r) if r else {"error": "no such document"}
    finally:
        conn.close()


@mcp.tool()
def coverage_report() -> list[dict]:
    """Coverage findings (missing/zero-claim parts, variant_no_emissions, ...)."""
    from backend.tools.coverage import build_report
    report = build_report(DATA_DIR / "variants", DATA_DIR / "fitment",
                          DATA_DIR / "parts")
    return [{"kind": f.kind, "subject": f.subject, "message": f.message,
             "part_id": f.part_id, "axis": f.axis} for f in report.findings]


# ── Write tools ($0 only) ─────────────────────────────────────────────────────


@mcp.tool()
def add_document(url: str, source_type: str, raw_text: str,
                 target_hint: str = "", site_or_channel: str = "",
                 lang: str = "") -> dict:
    """Insert a source document (hash-idempotent: same text returns the
    existing id). The agent's research output channel."""
    if not url or not raw_text.strip():
        return {"error": "url and raw_text are required"}
    conn = _conn()
    try:
        h = db.text_hash(raw_text)
        exists = conn.execute(
            "SELECT id FROM documents WHERE text_hash=?", (h,)).fetchone()
        doc_id = db.insert_document(
            conn, url=url, source_type=source_type, raw_text=raw_text,
            site_or_channel=site_or_channel, lang=lang, target_hint=target_hint)
        return {"doc_id": doc_id, "created": exists is None}
    finally:
        conn.close()


def _normalize(text: str) -> str:
    """Casefold + collapse whitespace, so a quote copied across a line wrap or
    with a different case still matches the source it came from."""
    return " ".join(text.split()).casefold()


def _quote_grounded(quote: str, raw_text: str) -> bool:
    """Is this quote actually present in the document it claims to come from?

    The whole trust model of agent-supplied research rests here: without it,
    `quote_grounded` was just `bool(quote)` and a fabricated citation was
    indistinguishable from a real one downstream.
    """
    if not quote.strip():
        return False
    return _normalize(quote) in _normalize(raw_text)


@mcp.tool()
def add_evidence(doc_id: int, title: str, severity: str = "medium",
                 domain: str = "general", rationale: str = "",
                 inspection_advice: str = "", quote: str = "",
                 component_hint: str | None = None) -> dict:
    """Write one agent-authored evidence row (extractor_version=1). Idempotent
    per (doc_id, title): a repeated write returns the existing evidence id.
    severity is one of low|medium|high.

    `quote` must be copied VERBATIM from the document's raw_text (whitespace
    and case may differ, nothing else). A quote that is not in the document is
    rejected and nothing is written — you cannot cite what you did not read.
    An omitted quote is allowed; the row is simply stored ungrounded."""
    if severity not in ("low", "medium", "high"):
        return {"error": "severity must be low|medium|high"}
    conn = _conn()
    try:
        existing = conn.execute(
            "SELECT id FROM evidence WHERE doc_id=? AND title=?",
            (doc_id, title)).fetchone()
        if existing:
            return {"evidence_id": existing["id"], "created": False}
        doc = conn.execute("SELECT raw_text FROM documents WHERE id=?",
                           (doc_id,)).fetchone()
        if not doc:
            return {"error": "no such document"}

        grounded = _quote_grounded(quote, doc["raw_text"] or "")
        if quote.strip() and not grounded:
            return {"error": "quote not found in document text — copy it "
                             "verbatim from the raw_text you submitted, or "
                             "omit it", "doc_id": doc_id, "quote": quote}

        ev_id = db.insert_evidence(
            conn, doc_id=doc_id,
            claim={"title": title, "domain": domain, "severity": severity,
                   "rationale": rationale,
                   "inspection_advice": inspection_advice, "quote": quote,
                   "engine_or_variant_hint": component_hint,
                   "quote_grounded": grounded},
            span_start=None, span_end=None,
            extractor_version=verdict.AGENT_EXTRACTOR_VERSION)
        return {"evidence_id": ev_id, "created": True, "quote_grounded": grounded}
    finally:
        conn.close()


# ── Model onboarding (B23) ────────────────────────────────────────────────────
#
# The agent's entry point. Before this, research could only start from a
# coverage finding that already named a part_id — so a car with no scaffold at
# all was unreachable, and scaffolding it meant a human hand-editing
# TR_MARKET_TRIMS. Now the agent researches the lineup and submits it.

# The variant columns that name a part to research. Same axes the fitment file
# projects, so the work list is derived from the catalog, never enumerated.
_PART_AXES = ("engine_family", "transmission_code", "electrical_code", "body_code")

# Placeholder codes that are engineering vocabulary, not a researchable part.
_PSEUDO_PART_CODES = {"manual", ""}


def _model_key(make: str, model: str) -> str:
    return f"{make.lower()}_{model.lower()}"


def _part_work_list(variant_rows: list[dict]) -> list[dict]:
    """Every part code the variants reference, tagged with what it still needs."""
    known = {p["part_id"]: p for p in _parts(DATA_DIR)}
    codes: dict[str, set[str]] = {}
    for row in variant_rows:
        for axis in _PART_AXES:
            code = (row.get(axis) or "").strip()
            if code and code not in _PSEUDO_PART_CODES:
                codes.setdefault(code, set()).add(axis)

    out = []
    for code in sorted(codes):
        part = known.get(code)
        if part is None:
            state, claims, part_type = "missing", 0, ""
        elif part["claims"] == 0:
            state, claims, part_type = "zero_claim", 0, part["part_type"]
        else:
            state, claims, part_type = "has_claims", part["claims"], part["part_type"]
        out.append({"part_id": code, "part_type": part_type, "state": state,
                    "claims": claims, "axes": sorted(codes[code])})
    return out


@mcp.tool()
def onboard_model(make: str, model: str) -> dict:
    """The work list for one car. Reports whether the variants/fitment scaffold
    exists, which variant rows are still draft (a figure nobody could source),
    and every part code those rows reference tagged `missing` (no YAML at all),
    `zero_claim` (stub with no claims — research it) or `has_claims`.

    Call this first. If `has_variants` is false, research the TR-market trim
    lineup and call submit_trims before researching any part."""
    import yaml
    key = _model_key(make, model)
    v_path = DATA_DIR / "variants" / f"{key}.yaml"
    f_path = DATA_DIR / "fitment" / f"{key}.yaml"

    rows: list[dict] = []
    if v_path.exists():
        rows = yaml.safe_load(v_path.read_text()) or []

    findings = [f for f in coverage_report()
                if key in (f.get("subject") or "")
                or (f.get("part_id") or "") in {r.get("engine_family") for r in rows}]

    return {
        "model_key": key,
        "has_variants": v_path.exists(),
        "has_fitment": f_path.exists(),
        "variants": len(rows),
        "variants_draft": sum(1 for r in rows if r.get("draft")),
        "draft_ids": [r["id"] for r in rows if r.get("draft")],
        "parts": _part_work_list(rows),
        "coverage_findings": findings,
    }


@mcp.tool()
def submit_trims(make: str, model: str, trims: list[dict],
                 source_urls: list[str] | None = None) -> dict:
    """Write the variants + fitment scaffold for a model from a researched
    TR-market trim lineup. Replaces the hand-edited TR_MARKET_TRIMS table.

    Each trim needs: id, engine_code, engine_family, fuel, transmission,
    transmission_code, year_from. Optional: generation, displacement_cc,
    power_min_hp, power_max_hp, year_to, notes, drivetrain, emissions.

    OMIT any figure you could not source — do not estimate. A row missing
    displacement or power is written `draft: true`, kept out of serving, and
    surfaced in the coverage report until someone can source it. Rows that
    fail structural validation are rejected and NOTHING is written.

    Pass the pages you took the lineup from as `source_urls` so the scaffold
    stays traceable."""
    from knowledge.catalog import write_variants as wv

    if not trims:
        return {"errors": ["no trims supplied"]}
    errors = wv.validate_trims(trims)
    if errors:
        return {"errors": errors, "rows_written": 0}

    summary = wv.run(make, model, trims=trims,
                     variants_dir=DATA_DIR / "variants",
                     fitment_dir=DATA_DIR / "fitment")

    key = _model_key(make, model)
    recorded = 0
    conn = _conn()
    try:
        for url in source_urls or []:
            if not url.strip():
                continue
            db.insert_document(conn, url=url, source_type="spec",
                               raw_text=f"Trim lineup source for {key}: {url}",
                               site_or_channel="", lang="", target_hint=key)
            recorded += 1
    finally:
        conn.close()

    return {**summary, "errors": [], "sources_recorded": recorded,
            "parts": _part_work_list(wv.build_rows(
                make, model, trims, wv._SHARED_CODES.get(key, {})))}


def _pipeline_pass(conn) -> dict:
    """Deterministic tail of the pipeline: resolve → cluster → import verdicts
    → export. Never constructs a Budget — $0 by construction."""
    resolved = resolve.resolve_all(conn)
    clusters = cluster.rebuild_clusters(conn)
    verdicts = verdict.import_verdicts(conn)
    exported = len(export.export_all(conn, EXPORT_DIR))
    log_stage(conn, "agent_pass", "agent", 1, 0, 0, 0.0)
    return {"resolved": resolved, "clusters": clusters,
            "verdicts": verdicts, "exported": exported}


@mcp.tool()
def run_pipeline_pass() -> dict:
    """After adding evidence: resolve components, rebuild clusters, store the
    deterministic $0 import verdicts, regenerate the export. One call."""
    conn = _conn()
    try:
        return _pipeline_pass(conn)
    finally:
        conn.close()


@mcp.tool()
def run_remediate_import_only() -> dict:
    """One $0 catch-up pass: re-ingest parity-lost cited sources, then the
    deterministic pipeline tail (resolve/cluster/import/export)."""
    conn = _conn()
    try:
        lost = remediate.ingest_lost_sources(conn, EXPORT_DIR, DATA_DIR)
        stats = _pipeline_pass(conn)
        stats["lost_ingested"] = lost
        return stats
    finally:
        conn.close()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
