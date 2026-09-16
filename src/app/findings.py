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

from collections.abc import Sequence
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


#: The explanation attached to a finding, under either of the two names it has
#: been submitted under. **They are one concept and were never bridged**, which
#: is the whole of the reader's "rationale is 0 chars" report.
#:
#: `kriko.gates` calls it `rationale` and measures it. `claim_text` calls it
#: `body` and stores it. `kriko.research.base.Finding` carries `body`, the API
#: plane's extraction prompt asks for `body`, and `accept_findings` read
#: `rationale`. So the gate measured a field no extractor on the paid plane ever
#: filled, and refused every finding it produced — while an MCP agent that did
#: fill `rationale` passed the gate and had its explanation dropped on the way
#: into the store, landing a claim with a title and nothing under it.
#:
#: Both directions were broken, and both looked like a model behaving badly.
#: Accepting both spellings here, once, is what makes the two ends agree; the
#: prompts and the skill now name `rationale` so new callers have one answer.
RATIONALE_KEYS = ("rationale", "body")


def explanation(item: dict) -> str:
    for key in RATIONALE_KEYS:
        value = (item.get(key) or "").strip()
        if value:
            return value
    return ""


def accept_findings(
    conn,
    subject_id: str,
    pack_id: str,
    findings: list[dict],
    *,
    retain: list | None = None,
) -> dict:
    """Store the findings that survive; report every one that does not.

    Returns a per-finding verdict rather than a count, so a caller learns which
    of its quotes or claims did not make it instead of discovering later that
    half the work vanished.

    `retain` is where the *documents* go (B120): pass a list and it is filled
    with `{source_id, pack_id, url, text}` for every finding that was accepted,
    for `log_submission` to keep in `app.sqlite`. A collecting list rather than
    a second connection argument, and rather than another key in the returned
    verdicts: acceptance must not depend on the interface's database being
    present (see `log_submission`), and the verdicts are handed straight back
    to the agent that submitted them — echoing its own page text at it would
    be a protocol change nobody asked for.
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

        rationale = explanation(item)
        has_anchor = bool(item.get("component") or item.get("component_hint"))
        reason = gate_reason(
            f"{title} {rationale}", vocab, subject=title, has_anchor=has_anchor
        )
        if reason:
            rejected.append({"title": title, "reason": reason, "fix": ""})
            continue

        structural = structural_reasons(
            title, rationale, vocab,
            has_anchor=has_anchor,
        )
        if structural:
            rejected.append({
                "title": title,
                "reason": "; ".join(structural),
                # Which refusals are worth another attempt, and which are a
                # verdict. A finding whose evidence was fabricated must not be
                # re-asked for — that is asking it to try harder at the thing
                # it got wrong. A finding whose *rationale* was left empty is
                # one edit from being kept, and the whole finding is otherwise
                # good: the titles in the reader's report were genuinely the
                # best of the run and were binned for a field nobody had
                # required.
                "fix": _repairable(structural),
            })
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
                str(item.get("published_at") or ""),
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
                # The same string the gate just measured. It used to be
                # `item.get("body", "")` while the gate read `rationale`, and
                # the two were never bridged — see `explanation`.
                rationale,
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
        if retain is not None:
            retain.append(
                {
                    "source_id": source_id,
                    "pack_id": pack_id,
                    "url": url,
                    "text": document,
                }
            )

    return {
        "accepted": accepted,
        "rejected": rejected,
        # Two audiences, two sentences. `rejected[].reason` is written at the
        # model — "rationale is 0 chars" is an instruction it can act on. The
        # reader got that same string in their face, which is debug output
        # leaking through an interface, so they get this instead.
        "summary": summarise(accepted, rejected),
        "note": f"author_confidence is {AGENT_CONFIDENCE} — agent-written "
        "claims rank as reported, not confirmed, until corroborated",
    }


#: Refusals a second attempt can honestly fix, and what to ask for. Keyed by a
#: fragment of the gate's own message rather than by an error code, because
#: `kriko.gates` returns prose — and inventing codes here would mean two places
#: deciding what a refusal means, which is how they come to disagree.
REPAIRABLE = {
    "rationale is": "rationale",
    "title is": "title",
}


def _repairable(reasons: Sequence[str]) -> str:
    """Which single field would fix these refusals, or "" if none would.

    Deliberately "" when a finding failed on more than one count. Re-asking for
    one field when two are wrong produces a second refusal and a third attempt,
    and a loop that cannot converge is worse than an honest stop.
    """
    fields = {
        field
        for reason in reasons
        for fragment, field in REPAIRABLE.items()
        if reason.startswith(fragment)
    }
    return fields.pop() if len(fields) == 1 and len(reasons) == 1 else ""


def summarise(accepted: Sequence, rejected: Sequence) -> str:
    """What happened, for somebody who is not going to read a verdict list.

    The reader saw `rationale is 0 chars — write 2–3 plain sentences a
    non-expert can act on (min 60)` three times over. That is a good sentence
    aimed at a model and a terrible one aimed at a person: it describes a field
    they have never heard of, in a schema they did not write, about work they
    cannot redo by hand.
    """
    kept = len(accepted)
    if not rejected:
        return f"{kept} finding(s) kept." if kept else "Nothing was submitted."

    held = [one for one in rejected if one.get("fix")]
    refused = len(rejected) - len(held)
    parts = [f"{kept} finding(s) kept" if kept else "Nothing was kept"]
    if held:
        parts.append(
            f"{len(held)} could not be explained well enough to be useful and "
            f"{'was' if len(held) == 1 else 'were'} held back"
        )
    if refused:
        parts.append(
            f"{refused} did not survive the evidence check or this pack's bar"
        )
    return ", ".join(parts) + "."


def log_submission(
    app_state_path,
    *,
    door: str,
    subject_id: str,
    pack_id: str,
    verdicts: dict,
    queries: Sequence[str] | None = None,
    documents: Sequence[dict] | None = None,
) -> None:
    """Note what happened to a batch, in `app.sqlite`, and never raise.

    `queries` is what the researcher searched for (B95) — passed through
    untouched, because which shapes earn their keep is a question about the
    pack's seeds and nothing on the acceptance path has an opinion about it.

    `documents` is `accept_findings`' `retain` list (B120): the text each
    accepted quote was checked against, kept so the check can be made again.
    Written here because this function already runs on both doors and already
    owns the interface's database — the alternative was for acceptance to open
    it, which is the coupling the paragraph below exists to prevent.

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
            queries=queries,
        )
        state.retain_documents(conn, documents or ())
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()


def regrounded(conn, app_state_path, pack_id: str, claim_id: str) -> list[dict]:
    """Re-run the grounding check on a stored claim, offline. One row per quote.

    This is what keeping the document buys, and the reason B120 was a defect
    rather than a tidy-up: the check that makes a quote into evidence used to
    happen exactly once, against text that was then dropped, so nothing could
    ever ask it again. Now it can be asked at any time, with no network and no
    model, and it answers one of three things per piece of evidence:

    * ``grounded`` — the quote is in the page this install read.
    * ``ungrounded`` — it is not. The evidence and the document disagree, which
      after acceptance can only mean the row was written by something other
      than this path, or the text was replaced by a later, different read of
      the same URL.
    * ``not_kept`` — this install has no copy: the claim came from a pack, from
      a run that predates B120, or from a page too large to keep.

    Deliberately *not* a fetch. `app/factcheck.py` is the one that goes out to
    the web and asks whether the page still says it; this asks the narrower
    question that needs no permission, no timeout and no user-agent — and the
    two together are what separates "the page changed" from "it never said
    this", which neither could answer alone.

    Reports rather than retracts, like everything else on this side of the
    line: the engine has no authority to remove a claim on a mechanical check.
    """
    from app.web import state

    rows = conn.execute(
        "SELECT evidence_id, source_id, quote FROM evidence"
        " WHERE pack_id = ? AND claim_id = ?",
        (pack_id, claim_id),
    ).fetchall()
    if not rows:
        return []
    try:
        app_conn = state.connect(app_state_path)
    except Exception:  # noqa: BLE001 — a missing interface database is a
        # "nothing kept" answer, not a failure of the check.
        app_conn = None
    out = []
    try:
        for row in rows:
            kept = (
                state.document_for(app_conn, row["source_id"])
                if app_conn is not None
                else None
            )
            if kept is None or not kept.get("text"):
                verdict = "not_kept"
            elif is_grounded(kept["text"], row["quote"]):
                verdict = "grounded"
            else:
                verdict = "ungrounded"
            out.append(
                {
                    "evidence_id": row["evidence_id"],
                    "source_id": row["source_id"],
                    "quote": row["quote"],
                    "url": (kept or {}).get("url", ""),
                    "verdict": verdict,
                }
            )
    finally:
        if app_conn is not None:
            app_conn.close()
    return out


#: Deleted in this order so that a foreign key never dangles mid-transaction:
#: children first, the `claims` row last. `sources` is deliberately absent —
#: see `retract_claim`.
CLAIM_TABLES = ("evidence", "claim_conditions", "claim_text", "claims")


def retract_claim(conn, pack_id: str, claim_id: str) -> bool:
    """Take one claim back out of the store. False if it was already gone.

    The reverse of `accept_findings`, and the reason an unattended multi-row
    research run is a feature rather than a liability: whatever it wrote can
    be taken back out, by run, without touching what anyone else wrote.

    **`sources` rows are left alone on purpose.** A source is shared between
    claims — two findings from the same page are one `sources` row — so
    deleting it with the claim that happened to be undone would leave a
    dangling `source_id` on a claim nobody asked about. An unreferenced source
    row is harmless; a dangling reference is not.

    Returning a bool rather than raising, because "already absent" is the
    ordinary case for a second undo, a hand-deleted claim, or a pack
    reinstall — and an undo that fails on those is an undo nobody presses.
    """
    present = conn.execute(
        "SELECT 1 FROM claims WHERE claim_id = ? AND pack_id = ?",
        (claim_id, pack_id),
    ).fetchone()
    for table in CLAIM_TABLES:
        conn.execute(
            f"DELETE FROM {table} WHERE claim_id = ? AND pack_id = ?",
            (claim_id, pack_id),
        )
    return present is not None
