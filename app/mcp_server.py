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
mechanical and lives in `submit_findings`, because an agent asked for verbatim
text will occasionally produce something plausible instead, and the whole value
of the evidence chain is that this cannot pass quietly.
"""

from contextlib import contextmanager

from mcp.server.fastmcp import FastMCP

from kriko.extract.grounding import is_grounded
from kriko.gates import gate_reason, load_gates, structural_reasons
from kriko.research import get_researcher, plan_task
from kriko.store import ids, packstore
from kriko.store.db import connect

mcp = FastMCP("kriko")

#: Overridden by tests so they never touch the real ~/.kriko store.
STORE_PATH = None

#: Rank weight for a claim an agent wrote. A subscription harness is a source,
#: not an authority: its claims reach the reader, ranked as *reported* rather
#: than confirmed, until something independent corroborates them. Same value the
#: cars exporter gives an unreviewed legacy claim, so the two cannot be told
#: apart by rank alone — which is correct, because neither has been checked.
AGENT_CONFIDENCE = 0.6


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


# ── writes: all $0, all deterministic ────────────────────────────────────


@mcp.tool()
def submit_findings(subject_id: str, pack_id: str, findings: list[dict]) -> dict:
    """Store what the agent read. Ungrounded quotes are refused.

    Each finding needs: title, domain, severity, quote, source_url, and the
    `document_text` the quote was taken from. The document text is what makes
    the grounding check possible — without it there is nothing to check against,
    and "trust me" is not an evidence model.

    Returns a per-finding verdict so the agent learns which of its quotes did
    not survive, rather than discovering later that half its work vanished.
    """
    accepted, rejected = [], []

    with _store() as conn:
        subject = conn.execute(
            "SELECT 1 FROM subjects WHERE subject_id = ? AND pack_id = ?",
            (subject_id, pack_id),
        ).fetchone()
        if subject is None:
            return {"error": f"no subject {subject_id} in pack {pack_id}"}

        vocab = load_gates(conn, pack_id)

        for item in findings:
            quote = (item.get("quote") or "").strip()
            document = item.get("document_text") or ""
            title = (item.get("title") or "").strip()

            if not title:
                rejected.append({"title": title, "reason": "no title"})
                continue
            if not quote:
                rejected.append({"title": title, "reason": "no quote"})
                continue
            if document and not is_grounded(document, quote):
                rejected.append(
                    {
                        "title": title,
                        "reason": "quote does not appear in the document text — "
                        "copy it verbatim rather than reconstructing it",
                    }
                )
                continue
            if not document:
                rejected.append(
                    {
                        "title": title,
                        "reason": "document_text missing, so the quote cannot be "
                        "checked; send the text the quote came from",
                    }
                )
                continue

            rationale = (item.get("rationale") or "").strip()
            reason = gate_reason(f"{title} {rationale}", vocab, subject=title)
            if reason:
                rejected.append({"title": title, "reason": reason})
                continue

            structural = structural_reasons(
                title, rationale, vocab,
                has_anchor=bool(item.get("component") or item.get("component_hint")),
            )
            if structural:
                rejected.append({"title": title, "reason": "; ".join(structural)})
                continue

            url = item.get("source_url") or ""
            source_id = ids.source_id(url=url, text=quote)
            claim_id = ids.claim_id(
                subject_id,
                item.get("kind", "known_issue"),
                item.get("domain", "general"),
                title,
            )
            conn.execute(
                "INSERT OR IGNORE INTO sources (source_id, pack_id, url,"
                " domain, site_or_channel, title, lang, source_type,"
                " published_at, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    source_id,
                    pack_id,
                    url,
                    _domain_of(url),
                    "",
                    "",
                    "",
                    item.get("source_type", "page"),
                    "",
                    "",
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO claims (claim_id, pack_id, subject_id,"
                " kind, domain, severity, consequence, detection, component,"
                " subsystem, author_confidence, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                (
                    claim_id,
                    pack_id,
                    subject_id,
                    item.get("kind", "known_issue"),
                    item.get("domain", "general"),
                    item.get("severity", "medium"),
                    "",
                    item.get("detection", ""),
                    item.get("component", ""),
                    "",
                    AGENT_CONFIDENCE,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO claim_text VALUES (?,?,?,?,?,?)",
                (
                    claim_id,
                    pack_id,
                    "en",
                    title,
                    item.get("body", ""),
                    item.get("advice", ""),
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO evidence (evidence_id, pack_id,"
                " claim_id, source_id, quote, locator, stance, independent)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    ids.evidence_id(source_id, quote),
                    pack_id,
                    claim_id,
                    source_id,
                    quote,
                    "",
                    item.get("stance", "supports"),
                    1,
                ),
            )
            accepted.append({"title": title, "claim_id": claim_id})

    return {
        "accepted": accepted,
        "rejected": rejected,
        "note": f"author_confidence is {AGENT_CONFIDENCE} — agent-written "
        "claims rank as reported, not confirmed, until corroborated",
    }


def _domain_of(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(url).netloc.lower().removeprefix("www.")


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
