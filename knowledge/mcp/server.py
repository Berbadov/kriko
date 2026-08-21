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

from knowledge.agent import gates
from knowledge.catalog import generations as gencat, model_state
from knowledge.ledger import (
    cluster, db, export, remediate, resolve, verdict,
)
from knowledge.ledger.costs import log_stage
from knowledge.sources.tiers import resolve_tier

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEDGER_PATH = db.LEDGER_PATH
EXPORT_DIR = REPO_ROOT / "knowledge" / "ledger_export"
DATA_DIR = REPO_ROOT / "backend" / "data"
GENERATIONS_DIR = gencat.GENERATIONS_DIR
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
    from ops.reports.coverage import build_report
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
    if not url.strip() or not raw_text.strip():
        return {"error": "url and raw_text are required"}
    conn = _conn()
    try:
        h = db.text_hash(raw_text)
        exists = conn.execute(
            "SELECT id FROM documents WHERE text_hash=?", (h,)).fetchone()
        if exists:
            # Re-submitting a document already in the ledger is idempotent, not
            # a new source: it must not consume research budget, and re-gating
            # it would reject what is already stored.
            return {"doc_id": exists["id"], "created": False,
                    "tier": resolve_tier(url)[0]}

        used = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE target_hint=?",
            (target_hint,)).fetchone()[0] if target_hint else 0
        check = gates.check_document(url, raw_text, target_hint, used,
                                     MAX_AGENT_SOURCES_PER_PART)
        if not check.ok:
            return {"error": "; ".join(check.rejections), **check.as_dict()}

        doc_id = db.insert_document(
            conn, url=url, source_type=source_type, raw_text=raw_text,
            site_or_channel=site_or_channel, lang=lang, target_hint=target_hint)
        tier, trust = resolve_tier(url)
        return {"doc_id": doc_id, "created": True, "tier": tier,
                "source_trust": trust,
                "documents_for_target": used + 1,
                "budget_remaining": max(0, MAX_AGENT_SOURCES_PER_PART - used - 1),
                "warnings": check.warnings}
    finally:
        conn.close()


def _known_titles(conn, part_id: str) -> list[str]:
    """Claim titles already attached to this part — catalog plus this session's
    ledger rows, so a duplicate is caught before *and* after the export."""
    import yaml
    titles: list[str] = []
    path = next(((DATA_DIR / "parts").rglob(f"{part_id}.yaml")), None)
    if path:
        try:
            data = yaml.safe_load(path.read_text()) or {}
            titles += [c.get("title", "") for c in (data.get("claims") or [])]
        except yaml.YAMLError:
            pass
    titles += [r[0] for r in conn.execute(
        "SELECT title FROM evidence WHERE component_hint=?", (part_id,))]
    return [t for t in titles if t]


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
        doc = conn.execute("SELECT raw_text, url FROM documents WHERE id=?",
                           (doc_id,)).fetchone()
        if not doc:
            return {"error": "no such document"}

        grounded = _quote_grounded(quote, doc["raw_text"] or "")
        if quote.strip() and not grounded:
            return {"error": "quote not found in document text — copy it "
                             "verbatim from the raw_text you submitted, or "
                             "omit it", "doc_id": doc_id, "quote": quote}

        # The product principle, enforced rather than requested. A prompt asks;
        # this refuses. Rejections name what is wrong and what would fix it, so
        # the agent can rewrite the row instead of guessing at the rule.
        check = gates.check_evidence(title, rationale, inspection_advice,
                                     component_hint, doc["url"] or "")
        if not check.ok:
            return {"error": "; ".join(check.rejections), "written": False,
                    **check.as_dict()}

        # Rephrasing a chronic that is already recorded is not new coverage;
        # it is the volume problem (a buyer reads ~8 cards, dq200 carries 30
        # rows of the same two failures). Checked against the part's own
        # claims and against what this pass already wrote.
        if component_hint:
            dup = gates.duplicate_of(title, _known_titles(conn, component_hint))
            if dup:
                return {"error": f"this is already recorded as {dup!r} — add a "
                                 f"row only for a DIFFERENT failure mode, or "
                                 f"leave the existing one alone",
                        "written": False, "duplicate_of": dup}

        ev_id = db.insert_evidence(
            conn, doc_id=doc_id,
            claim={"title": title, "domain": domain, "severity": severity,
                   "rationale": rationale,
                   "inspection_advice": inspection_advice, "quote": quote,
                   "engine_or_variant_hint": component_hint,
                   "quote_grounded": grounded},
            span_start=None, span_end=None,
            extractor_version=verdict.AGENT_EXTRACTOR_VERSION)
        tier, trust = resolve_tier(doc["url"] or "")
        return {"evidence_id": ev_id, "created": True, "quote_grounded": grounded,
                "source_tier": tier, "source_trust": trust,
                "warnings": check.warnings}
    finally:
        conn.close()


# ── Model onboarding (B23) ────────────────────────────────────────────────────
#
# The agent's entry point. Before this, research could only start from a
# coverage finding that already named a part_id — so a car with no scaffold at
# all was unreachable, and scaffolding it meant a human hand-editing
# TR_MARKET_TRIMS. Now the agent researches the lineup and submits it.

def _model_key(make: str, model: str) -> str:
    return model_state.model_key(make, model)


@mcp.tool()
def list_generations(make: str, model: str) -> dict:
    """Which generations of this car have been researched, and the model key to
    onboard for each (`q2_1`, `q2_2`).

    Resolves scraped display names through aliases, so "VW CC 1.4 TSI" finds
    the lineup filed under its canonical slug. `researched: false` means nobody
    has run generation research for this car yet — do that first."""
    found = gencat.read_generations(make, model, GENERATIONS_DIR)
    if not found:
        return {"make": gencat.slugify(make),
                "model": gencat.slugify(model),
                "researched": False, "generations": []}
    return {**found, "researched": True}


@mcp.tool()
def submit_generations(make: str, model: str, generations: list[dict],
                       canonical_model: str = "") -> dict:
    """Record the researched generation lineup for one car — phase 1 of
    onboarding, before any trim or part work.

    Each generation needs: `generation` (positive int — it becomes the model
    key suffix), `year_from`, and at least one `source_urls` entry. Optional:
    `name` (display label like "IV (BJ)") and `year_to` (null = still built).

    Cite every generation. A lineup with an unsourced row is rejected whole and
    nothing is written — the same rule as trims and evidence.

    Pass `canonical_model` when the name you were given came off a scrape and
    is not a real model name: the demand queue says "VW CC 1.4 TSI" and
    "3 Series". Resolve those to `passat_cc`, `3_series` and pass it — the
    queried name is kept as an alias so later lookups still resolve."""
    return gencat.write_generations(make, model, generations,
                                    GENERATIONS_DIR,
                                    canonical_model=canonical_model)


@mcp.tool()
def onboard_model(make: str, model: str) -> dict:
    """The work list for one car. Reports whether the variants/fitment scaffold
    exists, which variant rows are still draft (a figure nobody could source),
    and every part code those rows reference tagged `missing` (no YAML at all),
    `zero_claim` (stub with no claims — research it) or `has_claims`.

    Call this first. If `has_variants` is false, research the TR-market trim
    lineup and call submit_trims before researching any part."""
    st = model_state.model_state(make, model, DATA_DIR)
    key = st["model_key"]
    part_ids = {p["part_id"] for p in st["parts"]}
    st["draft_ids"] = [d["id"] for d in st["drafts"]]
    st["coverage_findings"] = [
        f for f in coverage_report()
        if key in (f.get("subject") or "") or (f.get("part_id") or "") in part_ids
    ]
    return st


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
    # Codes arrive as the source printed them ("EA211_evo2", "6MT"); the catalog
    # stores canonical codes. Normalizing first means validation reports real
    # problems, not casing.
    trims = wv.normalize_trims(trims)
    errors = wv.validate_trims(trims, make, model)
    if errors:
        return {"errors": errors, "rows_written": 0}

    summary = wv.run(make, model, trims=trims,
                     variants_dir=DATA_DIR / "variants",
                     fitment_dir=DATA_DIR / "fitment")

    if summary.get("errors"):
        # run() refuses to write a catalog CI would reject (two rows a listing
        # could never tell apart, on different gearboxes). Research, not a rule,
        # is the fix — so it comes back as an error the agent must resolve.
        return {**summary, "sources_recorded": 0, "parts": []}

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

    # The work list is read back off what was actually WRITTEN, not off the
    # submitted trims: run() merges powertrain duplicates and may leave a row
    # draft, so building it from the input would report parts for rows that no
    # longer exist.
    state = model_state.model_state(make, model, DATA_DIR)
    return {**summary, "errors": [], "sources_recorded": recorded,
            "parts": state["parts"], "drafts": state["drafts"],
            "variants": state["variants"]}


# ── Research methodology (the agent's plan, not its improvisation) ───────────
#
# "Do web research" is the weakest instruction in the whole contract: it leaves
# a cheap subscription model to invent its own checklist per part, so coverage
# depends on which failure modes it happened to think of. research_brief turns
# that into a derived plan — what this subsystem can fail at (components.yaml),
# what is already known (so it does not re-add it), what budget is left, and
# which sources actually count (source_tiers.yaml). All catalog-derived: a new
# component or a newly tiered domain shows up in the brief with no prompt edit.

COMPONENTS_YAML = REPO_ROOT / "knowledge" / "catalog" / "components.yaml"
SOURCE_TIERS_YAML = REPO_ROOT / "knowledge" / "catalog" / "source_tiers.yaml"
AGENT_RUN_LOG = REPO_ROOT / "logs" / "agent_runs.jsonl"


def _components_for(part_type: str) -> list[dict]:
    """Registry components whose subsystem belongs to this part type."""
    import yaml
    try:
        comps = (yaml.safe_load(COMPONENTS_YAML.read_text()) or {}).get("components") or []
    except (OSError, yaml.YAMLError):
        return []
    out = []
    for c in comps:
        group = str(c.get("subsystem") or "").split("/", 1)[0]
        if part_type and group != part_type:
            continue
        out.append({"component_id": c.get("id"),
                    "subsystem": c.get("subsystem"),
                    "display": (c.get("display") or {}).get("en", ""),
                    "detection": c.get("detection")})
    return out


def _distinct_titles(titles: list[str], limit: int = 40) -> list[str]:
    """Collapse rephrasings so the brief shows failure modes, not a wall."""
    kept: list[str] = []
    for title in titles:
        if not gates.duplicate_of(title, kept):
            kept.append(title)
    return kept[:limit]


def _example_sources(limit: int = 12) -> dict:
    """Domains the tier registry already trusts — what "a good source" means."""
    import yaml
    try:
        reg = yaml.safe_load(SOURCE_TIERS_YAML.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}
    out: dict[str, list[str]] = {}
    for domain, meta in (reg.get("domains") or {}).items():
        tier = meta.get("tier")
        if tier in ("authoritative", "specialist"):
            out.setdefault(tier, []).append(domain)
    return {k: sorted(v)[:limit] for k, v in out.items()}


@mcp.tool()
def research_brief(part_id: str) -> dict:
    """The research plan for one part — call this BEFORE searching the web.

    Reports what this subsystem can actually fail at (the component registry),
    which chronics are already recorded (do not re-add them), how much of the
    per-part source budget is left, which source tiers count, and the rules
    your evidence must pass. Every field is derived from the catalog, so it is
    current by construction."""
    import yaml
    path = next(((DATA_DIR / "parts").rglob(f"{part_id}.yaml")), None)
    part_type = path.parent.name if path else ""
    known: list[str] = []
    if path:
        data = yaml.safe_load(path.read_text()) or {}
        known = [c.get("title", "") for c in (data.get("claims") or [])]

    conn = _conn()
    try:
        docs = [dict(r) for r in conn.execute(
            "SELECT id, url, source_type FROM documents WHERE target_hint=?"
            " ORDER BY id", (part_id,))]
    finally:
        conn.close()

    return {
        "part_id": part_id,
        "part_type": part_type,
        "scaffolded": bool(path),
        "known_claims": _distinct_titles(known),
        "look_for": _components_for(part_type),
        "documents_used": len(docs),
        "budget_remaining": max(0, MAX_AGENT_SOURCES_PER_PART - len(docs)),
        "documents": docs,
        "preferred_sources": _example_sources(),
        "write_rules": [
            "config-specific: name the engine/gearbox code or the mileage",
            "high-consequence: timing, dual-clutch/mechatronics, turbo, "
            "emissions hardware, structural",
            "maintenance-interval items count — 'due unless the ad proves "
            "otherwise' is a real claim",
            "never: warning lights, fluids, pads, compression, injector "
            "benches — the ekspertiz already catches those",
            "quote must be copied verbatim from the document you submitted",
        ],
    }


@mcp.tool()
def finish_model(make: str, model: str, notes: str = "") -> dict:
    """Close out a model: run the $0 pipeline pass, then report what landed.

    Call this once, at the end of an onboarding pass, instead of
    run_pipeline_pass — it does the same deterministic work and additionally
    writes the pass into logs/agent_runs.jsonl (what closed, what is still
    zero-claim, which rows stayed draft and which figure each is missing), so
    the outcome of an agent run is recorded state rather than a chat message
    that disappears with the session."""
    import json
    import time

    conn = _conn()
    try:
        stats = _pipeline_pass(conn)
    finally:
        conn.close()

    st = model_state.model_state(make, model, DATA_DIR)
    report = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model_key": st["model_key"],
        "variants": st["variants"],
        "variants_draft": st["variants_draft"],
        "drafts": st["drafts"],
        "rollup": st["rollup"],
        "open_parts": [p["part_id"] for p in st["parts"]
                       if p["state"] != "has_claims"],
        "pipeline": stats,
        "notes": notes,
    }
    try:
        AGENT_RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AGENT_RUN_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(report, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return report


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
