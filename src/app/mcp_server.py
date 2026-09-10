"""Kriko as MCP tools — the $0 research plane.

    python -m app.mcp_server

Every tool here is free by construction: reads report state, writes are
deterministic or import-only, and nothing calls a paid API. The research itself
is done by the harness that already pays for a subscription — Kriko says what to
look for and stores what comes back.

Two rules this file exists to hold:

**No pack Python runs in this process.** Tools are registered by a decorator at
import time, so "packs supply their own tools" would mean importing pack code
into the MCP server. That is the same door the extension keeps shut, for the
same reason. The tools are instead *generalised* — `list_subjects`,
`submit_findings` — and driven by whatever vocabulary the installed packs
declare. The five car-shaped tools of the old server (`onboard_model`,
`submit_trims`, `list_generations`, …) collapse into these.

**A quote that is not in the document does not become evidence.** The check is
mechanical and lives in `app/findings.py`, because an agent asked for verbatim
text will occasionally produce something plausible instead, and the whole value
of the evidence chain is that this cannot pass quietly.
"""

from contextlib import contextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app import agenda as _agenda
from app.findings import accept_findings, log_submission
from kriko.lookup.tree import health_json, tree_json
from kriko.lookup.tree import subject_tree as _subject_tree
from kriko.lookup.tree import weakest_claims as _weakest_claims
from kriko.research import get_researcher, plan_task
from kriko.store import packstore
from kriko.store.db import connect

mcp = FastMCP("kriko")

#: Overridden by tests so they never touch the real ~/.kriko store.
STORE_PATH = None


def _app_state_path():
    """Where the interface's own database is, derived from the store's own
    directory rather than imported from `app.web.settings`.

    The two files are siblings in `~/.kriko` by construction, so the parent
    directory is all this needs — and it means a test that points STORE_PATH at
    a temporary directory gets a temporary submission log too, without knowing
    this function exists.
    """
    from kriko.store.db import DEFAULT_STORE

    return Path(STORE_PATH or DEFAULT_STORE).parent / "app.sqlite"

def _log_path():
    """Where the analyses log is, derived rather than imported.

    Same reasoning as `_app_state_path`: the log is a sibling of the store by
    construction, so a test that points STORE_PATH at a temporary directory
    gets a temporary demand log too. `KRIKO_ANALYSES_LOG` still wins, because
    that is the variable the app itself honours.
    """
    import os

    override = os.environ.get("KRIKO_ANALYSES_LOG")
    if override:
        return Path(override)
    if STORE_PATH:
        # A test (or an operator) pointing the store somewhere gets the log
        # from beside it, which is where a real install keeps it.
        return Path(STORE_PATH).parent / "logs" / "analyses.jsonl"
    # No override and the default store: ask the app where it *writes* the
    # log, because in a source checkout that is the repository's `logs/` and
    # not `~/.kriko` — reading a different file from the one being written is
    # a demand signal of zero.
    from app.web.settings import default_analysis_log

    return Path(default_analysis_log())


@contextmanager
def _store():
    """One connection per tool call, always closed.

    `sqlite3.Connection` is itself a context manager, but its `__exit__` only
    commits or rolls back — it does not close. Long-lived MCP servers make many
    tool calls, so relying on that would leak a handle per call until the
    process ran out.
    """
    conn = connect(STORE_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── reads: what is installed, and what does it know? ─────────────────────


@mcp.tool()
def list_packs() -> list[dict]:
    """Installed packs, their versions and whether they are enabled."""
    with _store() as conn:
        return [
            {
                "pack_id": r["pack_id"],
                "name": r["name"],
                "version": r["version"],
                "enabled": bool(r["enabled"]),
                "trust_weight": r["trust_weight"],
            }
            for r in packstore.installed_packs(conn)
        ]


@mcp.tool()
def store_status() -> dict:
    """Row counts across the installed store — the shape of what is known."""
    tables = (
        "packs",
        "subjects",
        "attributes",
        "relations",
        "claims",
        "evidence",
        "sources",
    )
    with _store() as conn:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables
        }


@mcp.tool()
def list_subjects(pack_id: str = "", kind: str = "", limit: int = 50) -> list[dict]:
    """Subjects, newest packs first. Replaces the old `list_parts`."""
    clauses, args = ["p.enabled = 1"], []
    if pack_id:
        clauses.append("s.pack_id = ?")
        args.append(pack_id)
    if kind:
        clauses.append("s.kind = ?")
        args.append(kind)
    with _store() as conn:
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT s.subject_id, s.pack_id, s.kind, s.label,"
                f"       COUNT(c.claim_id) AS claims"
                f" FROM subjects s JOIN packs p USING (pack_id)"
                f" LEFT JOIN claims c USING (subject_id, pack_id)"
                f" WHERE {' AND '.join(clauses)}"
                f" GROUP BY s.subject_id, s.pack_id ORDER BY claims DESC LIMIT ?",
                (*args, limit),
            )
        ]


@mcp.tool()
def get_subject(subject_id: str) -> dict:
    """One subject: its attributes, its relations, and its claims."""
    with _store() as conn:
        row = conn.execute(
            "SELECT * FROM subjects WHERE subject_id = ?", (subject_id,)
        ).fetchone()
        if row is None:
            return {"error": f"no subject {subject_id}"}
        return {
            "subject_id": subject_id,
            "pack_id": row["pack_id"],
            "kind": row["kind"],
            "label": row["label"],
            "attributes": {
                r["key"]: r["value_text"]
                for r in conn.execute(
                    "SELECT key, value_text FROM attributes WHERE subject_id = ?",
                    (subject_id,),
                )
            },
            "relations": [
                dict(r)
                for r in conn.execute(
                    "SELECT predicate, object_id, note FROM relations"
                    " WHERE subject_id = ?",
                    (subject_id,),
                )
            ],
            "claims": [
                dict(r)
                for r in conn.execute(
                    "SELECT c.claim_id, c.kind, c.domain, c.severity, t.title"
                    " FROM claims c LEFT JOIN claim_text t"
                    "   ON t.claim_id = c.claim_id AND t.pack_id = c.pack_id"
                    "  AND t.lang = 'en'"
                    " WHERE c.subject_id = ?",
                    (subject_id,),
                )
            ],
        }


@mcp.tool()
def lookup(
    kind: str,
    identity: dict,
    context: dict | None = None,
    lang: str = "en",
    limit: int = 8,
) -> dict:
    """Ask the installed packs about a product, exactly as the CLI does."""
    from kriko.lookup import lookup as run_lookup
    from kriko.lookup.query import Query

    with _store() as conn:
        result = run_lookup(
            conn,
            Query(
                kind=kind,
                identity=identity,
                context=context or {},
                lang=lang,
                limit=limit,
            ),
        )
        return {
            "method": result.resolution.method,
            "coverage": result.coverage,
            "flags": list(result.resolution.flags),
            "claims": [
                {
                    "title": c.title,
                    "severity": c.severity,
                    "domain": c.domain,
                    "subject": c.subject_label,
                    "relevance": round(c.relevance, 4),
                    "disputed": c.disputed,
                    "pack_id": c.pack_id,
                    "why": list(c.why),
                }
                for c in result.claims
            ],
        }


@mcp.tool()
def research_brief(subject_id: str, pack_id: str) -> dict:
    """What to research about this subject, in this pack's own terms.

    The brief carries the pack's value principle and query templates, so the
    same agent researching a car and a power tool is told two different things
    about what is worth keeping — without a line of code knowing either.
    """
    with _store() as conn:
        task = plan_task(conn, subject_id, pack_id)
        return {
            "subject": task.subject_label,
            "queries": list(task.rendered_queries()),
            "brief": get_researcher().brief(task),
        }


@mcp.tool()
def research_agenda(pack_id: str = "", limit: int = 20) -> dict:
    """**Call this first.** What to research next, in the order it is worth it.

    `coverage_gaps` answers "what is missing" alphabetically, which is not an
    ordering — an agent taking its first ten rows researches ten subjects
    beginning with A while the product someone actually looked up twice this
    week waits. This ranks by demand: how often this installation was asked
    about a subject, out of the analyses log.

    Four row kinds, and the `why` on each says what it is asking for:

      `empty_subject`   nothing known — the normal research task
      `stale_claim`     a cited page no longer carries its quote; re-read it
      `thin_subject`    supported by too little; find an independent source
      `unknown_subject` **not a task for you.** A product this installation
                        was asked about that no subject exists for. It has no
                        `subject_id`, so nothing can be filed against it — it
                        is demand for catalog coverage, and reporting it to
                        the reader is the whole of what it is for.

    The signals ride on every row (`asked`, `independent_sources`,
    `refuted_by`, `checked_at`) rather than being fused into a score, because
    "nobody has ever researched this" and "the source moved" call for
    different searches, and a single number cannot tell them apart.
    """
    with _store() as conn:
        app_state = None
        try:
            from app.web import state as _state

            app_state = _state.connect(_app_state_path())
        except Exception:
            app_state = None
        try:
            return _agenda.compute(
                conn, app_state=app_state, log_path=_log_path(),
                pack_id=pack_id, limit=limit,
            )
        finally:
            if app_state is not None:
                app_state.close()


@mcp.tool()
def coverage_gaps(pack_id: str = "", limit: int = 50) -> list[dict]:
    """Subjects with no claims — where research would actually help.

    Fail-open made visible: a subject nobody has researched is not an error and
    does not stop anything, but it must be findable without a person noticing.
    """
    args = []
    clause = "p.enabled = 1"
    if pack_id:
        clause += " AND s.pack_id = ?"
        args.append(pack_id)
    with _store() as conn:
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT s.subject_id, s.pack_id, s.kind, s.label"
                f" FROM subjects s JOIN packs p USING (pack_id)"
                f" LEFT JOIN claims c USING (subject_id, pack_id)"
                f" WHERE {clause} AND c.claim_id IS NULL"
                f" ORDER BY s.label LIMIT ?",
                (*args, limit),
            )
        ]


@mcp.tool()
def subject_health(subject_id: str, pack_id: str = "") -> dict:
    """How well supported is everything we know about this subject?

    The read-back that lets an agent catch its own mistake. Each claim comes
    with four separate signals — how many sources refute it, how many
    independent sources support it, the best source's trust tier, and when we
    last saw the page — plus the evidence itself. No score: an agent that gets
    one number cannot tell a weak claim from an old one.

    `independent` and `stance` are flags whoever wrote the evidence supplied.
    They are assertions about the sources, not verified facts.
    """
    packs = [pack_id] if pack_id else None
    with _store() as conn:
        return tree_json(_subject_tree(conn, subject_id, packs))


@mcp.tool()
def weakest_claims(pack_id: str = "", limit: int = 20) -> list[dict]:
    """The shipped claims that are least well supported, worst first.

    `coverage_gaps` answers what is missing; this answers what is thin. A
    claim with no sources at all appears in neither — it is not weak evidence,
    it is no evidence, and it belongs to the coverage report.
    """
    packs = [pack_id] if pack_id else None
    with _store() as conn:
        return [health_json(h) for h in _weakest_claims(conn, packs, limit=limit)]


# ── writes: all $0, all deterministic ────────────────────────────────────


@mcp.tool()
def submit_findings(
    subject_id: str,
    pack_id: str,
    findings: list[dict],
    queries: list[str] | None = None,
) -> dict:
    """Store what the agent read. Ungrounded and low-value findings are refused.

    Each finding needs: title, domain, severity, quote, source_url, and the
    `document_text` the quote was taken from. The document text is what makes
    the grounding check possible — without it there is nothing to check against,
    and "trust me" is not an evidence model.

    A grounded finding still is not automatically kept: the installed pack's
    own gate (`kriko.gates.gate_reason`, `kriko.gates.structural_reasons`) may
    refuse it as routine, generic, or tied to nothing specific. Optionally set
    `component` or `component_hint` to the concrete part/unit the finding is
    about — that satisfies the "tied to something specific" requirement on its
    own. Without either field, the finding's own title or rationale must carry
    that specificity itself (an identifier, a specification, or a usage
    figure), or it is refused for having nothing to anchor it to a
    configuration.

    Pass `queries` — the searches you actually ran to find this batch. The
    brief's search list is a set of seeds you are expected to adapt to this
    subject, its market and its language, so the pack can only learn which
    shapes are worth seeding if you report the ones you chose. It changes
    nothing about whether a finding is kept.

    Returns a per-finding verdict so the agent learns which of its quotes or
    claims did not survive, rather than discovering later that half its work
    vanished.
    """
    with _store() as conn:
        verdicts = accept_findings(conn, subject_id, pack_id, findings)
    # Logged after the store connection closes, and to a different file: the
    # refusals in this payload are what an author tunes the skill against, and
    # they were previously returned to the agent and then lost.
    log_submission(
        _app_state_path(),
        door="mcp",
        subject_id=subject_id,
        pack_id=pack_id,
        verdicts=verdicts,
        queries=queries,
    )
    return verdicts


@mcp.tool()
def install_pack(path: str) -> dict:
    """Install a pack file that is already on disk."""
    with _store() as conn:
        return {"pack_id": packstore.install(conn, path)}


@mcp.tool()
def set_pack_enabled(pack_id: str, enabled: bool = True) -> dict:
    with _store() as conn:
        packstore.set_enabled(conn, pack_id, enabled)
        return {"pack_id": pack_id, "enabled": enabled}


if __name__ == "__main__":
    mcp.run()
