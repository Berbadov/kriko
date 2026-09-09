"""What to research next, derived rather than decided.

`app/agentskill.py` tells a connected agent what this installation holds, what
its packs consider worth keeping, and how to file a finding. It does not say
which subject to open first, and the two places a reader would look answer it
badly: `coverage_gaps` orders alphabetically, so an agent taking the first ten
rows researches ten subjects beginning with A — and the record of what anyone
actually wanted to know is in a different file entirely.

This module is the miner `app/web/observability.py` names in its own docstring
("the demand signal — which subjects people look up that no installed pack
covers yet") and nothing had yet read. Four signals, kept separate:

    demand   how often the log was asked about it     analyses.jsonl
    gap      the subject exists and holds no claims   subjects ⟂ claims
    thin     what it holds is weakly supported        weakest_claims
    stale    a cited page no longer carries its quote fact_checks

Kept separate on the same grounds `subject_health` refuses to emit a score: an
agent told only *rank* cannot tell "nobody has ever researched this" from "the
source moved", and those are different searches. The rank is present as well,
because an ordering nobody can act on is a list.

**Why it lives in `app/`.** It reads three files — the engine's store, the
interface's `app.sqlite`, and the analyses log — and `app/` is the only layer
allowed to hold all three. `kriko/` may not: what a reader looked up is not the
engine's business, and it must never be able to move a pack's `content_digest`.

**Demand comes from the log, not from history.** `lookups` in `app.sqlite` is
the reader's own record and clearing it is their right; the JSONL log is the
demand corpus and survives that, which is exactly why `routers/analyze.py`
writes both. The log carries no timestamp on the rows this version writes, so
the window is a *count* — the most recent `WINDOW` analyses — which is exact
recency in an append-only file and needs nothing added to the format.

**One row kind is not an agent task.** A lookup that resolved to no subject at
all (`NOT_MATCHED`) is the strongest signal here — a reader brought us a
product the catalog cannot even name — and it is invisible to every gap
surface, because a gap list can only name subjects that exist. It has no
`subject_id`, so `submit_findings` could not accept anything against it; it is
reported as `unknown_subject`, which is a catalog input and says so.

Nothing here is category-aware. `identity` is whatever dict the pack's adapter
produced, passed through opaquely and stripped of everything else the log line
carries — the log holds listing URLs and advert text, and an agenda row must
carry neither.
"""

import json
from pathlib import Path

from kriko.lookup.tree import weakest_claims

#: How many of the most recent analyses count as demand. A window, because
#: "ever" would let a car looked up once in July outrank one looked up twice
#: this week forever, and small enough to be a few milliseconds of JSON.
WINDOW = 500

#: Row kinds, in the order they break a tie at equal demand. Actionable first:
#: an empty subject is a research task, `unknown_subject` is a message to the
#: catalog, and at equal demand the task is the more useful thing to read.
KINDS = ("empty_subject", "stale_claim", "thin_subject", "unknown_subject")

#: What each kind asks for, in one line, because a row that states a rank and
#: not a next action is a list.
_ACTION = {
    "empty_subject": "nothing is known about this subject — research_brief, then submit_findings",
    "stale_claim": "the cited page no longer carries this quote — re-read it and file what it says now",
    "thin_subject": "supported by too little — look for an independent source",
    "unknown_subject": "no subject exists for this identity: the catalog is missing it, not the claims",
}


def _identity_key(identity: dict) -> str:
    """A stable key for an identity the catalog does not know.

    Sorted keys and JSON, so two lookups of the same product collapse into one
    row whatever order the adapter emitted its fields in — and so the key
    survives a round trip through a response body unchanged.
    """
    clean = {str(k): str(v) for k, v in sorted(identity.items()) if v not in (None, "")}
    return json.dumps(clean, sort_keys=True, ensure_ascii=False)


def read_demand(log_path: Path | None, window: int = WINDOW) -> tuple[dict, dict, str]:
    """`(per subject, per unknown identity, note)` from the tail of the log.

    Never raises. A missing log is a fresh install, an unreadable one is a
    worse ordering, and neither is worth failing a request over — an agent
    with gaps in alphabetical order is strictly better off than an agent with
    an error.
    """
    if not log_path:
        return {}, {}, "no analyses log: ordering by gap and support only"
    try:
        from app.web.observability import load_records

        records, _ = load_records(Path(log_path))
    except Exception:
        return {}, {}, "the analyses log could not be read: ordering by gap and support only"
    if not records:
        return {}, {}, "no analyses yet: ordering by gap and support only"

    subjects: dict[str, int] = {}
    unknown: dict[str, dict] = {}
    for record in records[-max(0, window):]:
        for subject_id in record.get("subjects") or []:
            key = str(subject_id)
            if key:
                subjects[key] = subjects.get(key, 0) + 1
        identity = record.get("identity")
        # Only the resolution says the catalog missed it. A lookup that
        # resolved and found nothing is an `empty_subject`, which is a
        # different row with a different action.
        if record.get("coverage") == "NOT_MATCHED" and isinstance(identity, dict) and identity:
            key = _identity_key(identity)
            row = unknown.setdefault(key, {"identity": key, "asked": 0})
            row["asked"] += 1
    return subjects, unknown, ""


def _installed(store) -> bool:
    return bool(store.execute("SELECT 1 FROM packs WHERE enabled = 1 LIMIT 1").fetchone())


def _gaps(store, pack_id: str) -> list[dict]:
    args: list = []
    clause = "p.enabled = 1"
    if pack_id:
        clause += " AND s.pack_id = ?"
        args.append(pack_id)
    return [
        {
            "kind": "empty_subject",
            "subject_id": row["subject_id"],
            "pack_id": row["pack_id"],
            "label": row["label"],
            "subject_kind": row["kind"],
        }
        for row in store.execute(
            f"SELECT s.subject_id, s.pack_id, s.kind, s.label"
            f" FROM subjects s JOIN packs p USING (pack_id)"
            f" LEFT JOIN claims c USING (subject_id, pack_id)"
            f" WHERE {clause} AND c.claim_id IS NULL"
            f" ORDER BY s.subject_id",
            args,
        )
    ]


def _thin(store, pack_id: str, limit: int) -> list[dict]:
    packs = [pack_id] if pack_id else None
    rows = []
    for health in weakest_claims(store, packs, limit=limit):
        rows.append({
            "kind": "thin_subject",
            "subject_id": health.subject_id,
            "pack_id": health.pack_id,
            "label": health.subject_label,
            "claim_id": health.claim_id,
            "title": health.title,
            "independent_sources": health.independent_sources,
            "refuted_by": health.refuted_by,
            "best_tier": health.best_tier,
        })
    return rows


def _stale(app_state, pack_id: str) -> list[dict]:
    """Claims whose cited page has changed, from the interface's own file.

    `missing` ranks nothing in the reader's report — pages get rewritten and
    Kriko has no authority to retract anything. Ranking *research* is the other
    question, and this is where it gets asked.
    """
    if app_state is None:
        return []
    try:
        from app.web import state

        checks = state.fact_checks(app_state, verdict="missing", limit=200)
    except Exception:
        return []
    rows = []
    for check in checks:
        if pack_id and check.get("pack_id") != pack_id:
            continue
        rows.append({
            "kind": "stale_claim",
            "subject_id": check.get("subject_id") or "",
            "pack_id": check.get("pack_id") or "",
            "label": check.get("title") or "",
            "claim_id": check.get("claim_id") or "",
            "checked_at": check.get("checked_at") or "",
            "sources": [
                s.get("url", "") for s in check.get("sources") or []
                if isinstance(s, dict) and s.get("verdict") == "missing"
            ],
        })
    return rows


def compute(store, app_state=None, log_path=None, pack_id: str = "", limit: int = 20) -> dict:
    """The agenda: ranked rows, each carrying the signals that ranked it.

    Computed on read, from rows that already exist. No table, no clock and
    nothing to invalidate — an agenda that recommended a subject researched an
    hour ago would be worse than none, and that is the only failure a cache
    here could produce.
    """
    if not _installed(store):
        # Same answer as `agentskill.render` gives an empty installation:
        # there is nothing to research and nothing to say what would count.
        return {"rows": [], "note": "no packs installed", "window": WINDOW, "counts": {}}

    demand, unknown, note = read_demand(log_path)
    rows = _gaps(store, pack_id) + _thin(store, pack_id, limit) + _stale(app_state, pack_id)
    for row in rows:
        row["asked"] = demand.get(row.get("subject_id") or "", 0)
    # An identity with no subject cannot be filtered by pack: no pack claimed
    # it, which is the whole content of the row.
    if not pack_id:
        rows += [
            {"kind": "unknown_subject", "subject_id": "", "pack_id": "",
             "label": "", "identity": row["identity"], "asked": row["asked"]}
            for row in unknown.values()
        ]

    for row in rows:
        row["why"] = _ACTION[row["kind"]]

    # Total and stable: demand first because that is the fix this module
    # exists for, then the kind, then the ids. Ties that resolve at random
    # would make the ordering untestable and the agenda unreproducible.
    rows.sort(key=lambda r: (
        -r["asked"], KINDS.index(r["kind"]),
        r.get("subject_id") or "", r.get("claim_id") or "", r.get("identity") or "",
    ))
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    return {
        "rows": rows[:max(0, limit)],
        "note": note,
        "window": WINDOW,
        "counts": counts,
    }
