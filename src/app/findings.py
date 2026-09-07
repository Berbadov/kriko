"""Turning what a researcher read into rows — and refusing most of it.

Extracted from `app/mcp_server.py` when the web dashboard grew a research job
(`app/web/tasks.py`). Both planes now share one acceptance path, which is the
point: whether a finding arrived through MCP from a coding agent or through a
browser-started job, it faces the same grounding check and the same pack gate.
Two copies of this would eventually disagree, and the disagreement would show
up as a pack whose provenance depended on which door its claims came in.

**A quote that is not in the document does not become evidence.** The check is
mechanical, because an agent asked for verbatim text will occasionally produce
something plausible instead, and the whole value of the evidence chain is that
this cannot pass quietly.
"""

from datetime import datetime, timezone
from urllib.parse import urlsplit

from kriko.extract.grounding import is_grounded
from kriko.gates import gate_reason, load_gates, structural_reasons
from kriko.store import ids

#: Rank weight for a claim an agent wrote. A subscription harness is a source,
#: not an authority: its claims reach the reader, ranked as *reported* rather
#: than confirmed, until something independent corroborates them. Same value an
#: installed pack's exporter gives an unreviewed claim, so the two cannot be
#: told apart by rank alone — which is correct, because neither has been
#: checked.
AGENT_CONFIDENCE = 0.6


def domain_of(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def accept_findings(conn, subject_id: str, pack_id: str, findings: list[dict]) -> dict:
    """Store the findings that survive; report every one that does not.

    Returns a per-finding verdict rather than a count, so a caller learns which
    of its quotes or claims did not make it instead of discovering later that
    half the work vanished.
    """
    accepted, rejected = [], []

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
        has_anchor = bool(item.get("component") or item.get("component_hint"))
        reason = gate_reason(
            f"{title} {rationale}", vocab, subject=title, has_anchor=has_anchor
        )
        if reason:
            rejected.append({"title": title, "reason": reason})
            continue

        structural = structural_reasons(
            title, rationale, vocab,
            has_anchor=has_anchor,
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
                domain_of(url),
                "",
                "",
                "",
                item.get("source_type", "page"),
                "",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
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


def log_submission(
    app_state_path,
    *,
    door: str,
    subject_id: str,
    pack_id: str,
    verdicts: dict,
) -> None:
    """Note what happened to a batch, in `app.sqlite`, and never raise.

    Kept out of `accept_findings` on purpose: acceptance is a decision about
    the knowledge store and takes its connection, while this is interface
    bookkeeping in a different file. Passing both connections into one function
    would make the acceptance path depend on the UI's database being present,
    which is exactly the coupling the two-file split exists to prevent.

    Silent on failure for the same reason `record_extension` is: an author
    losing the refusal log is a nuisance, and a researcher losing an accepted
    finding because the log could not be written is a bug.
    """
    from app.web import state

    try:
        conn = state.connect(app_state_path)
    except Exception:  # noqa: BLE001 — see the docstring
        return
    try:
        state.record_submission(
            conn,
            door=door,
            subject_id=subject_id,
            pack_id=pack_id,
            verdicts=verdicts,
        )
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()
