"""The benchmark: the same case, every plane, measured.

*"Some very specific cases and cost measurements to understand how different
agents perform."* — B111, and it is the row everything else in
`docs/AGENT_OPERATIONS.md` waits on. Choosing how an operation should spend a
model (B123) is a question about ratios, and a ratio is a measurement or it is
a guess. Deciding whether a coding-agent CLI can be driven as a function at all
(B124) is the same measurement asked of two planes.

**The cases are derived, never enumerated.** A fixed list of subjects in Python
would be the hardcoded-car-data bug in benchmark clothing: it would name cars,
go stale the week a pack changed, and be meaningless for a pack that is not
`cars`. So the cases come off the installed store, ordered by `subject_id`,
which is stable across runs, identical on two machines with the same pack, and
correct for any category anyone ever installs.

**Nothing is written to the knowledge.** Each case runs against a *copy* of the
store in a temporary directory, which is thrown away with its claims, its
sources and its evidence. A benchmark that grew the pack it measured would make
the second run incomparable with the first — and would be a way to fill a
reader's store with runs they never asked to keep.

**A failed case is a measurement.** A plane that cannot start, times out or
refuses is *the* thing this is for; recording it as a row with an `error` and
dropping it from the averages is how "the harness plane is structurally worse"
becomes a fact rather than an impression.
"""

import shutil
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from kriko.store.db import connect

#: How many cases a run uses when nobody says. Three is enough to see a
#: difference between planes and small enough that pressing the button on the
#: paid plane is not a decision to spend real money without noticing.
DEFAULT_CASES = 3

#: And what one benchmark case may spend on the paid plane. Per case, not per
#: run, so adding a case cannot silently multiply the bill by surprise.
DEFAULT_BUDGET_USD = 0.20


def _copy_store(source_path, dest_path) -> None:
    """A throwaway copy that actually has the data in it.

    `kriko.store.db.connect` puts every store in WAL mode (see its own
    module), which means a normal write sits in `<name>-wal` until something
    checkpoints it — a plain `shutil.copy` of the main file alone silently
    drops everything not yet checkpointed. For a fresh subject or a claim
    accepted seconds before the button was pressed, that is *most* writes:
    the copy would open, `plan_task` would raise "no subject" for a subject
    that plainly exists, or worse, a `validation` case would silently see zero
    stored claims and report "nothing to validate" for a subject with plenty.
    Checkpointing the source before the copy is the fix; `TRUNCATE` also
    leaves the source's own WAL file empty, which is a courtesy to the next
    reader of `settings.store_path`, not a requirement of this function.
    """
    checkpoint = connect(source_path)
    try:
        checkpoint.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        checkpoint.close()
    shutil.copy(source_path, dest_path)


def gold_cases(conn, *, pack_id: str = "", limit: int = DEFAULT_CASES) -> list[dict]:
    """The pack-authored ground-truth cases, when there are any (B126).

    Preferred over derived cases wherever a pack ships them: a derived case
    measures discipline (what share of what came back survived the gate) and a
    gold case measures *correctness* — what a competent run should have found,
    and what it must not claim. The first is a floor the benchmark had from day
    one; the second is the reason the benchmark exists.
    """
    from app import gold

    found = gold.all_cases(conn)
    if pack_id:
        found = [case for case in found if case["pack_id"] == pack_id]
    labels = {
        row["subject_id"]: row["label"]
        for row in conn.execute("SELECT subject_id, label FROM subjects").fetchall()
    }
    return [
        {**case, "label": labels.get(case["subject_id"], case["subject_id"])}
        for case in found
        if case["subject_id"] in labels
    ][: max(1, min(limit, 50))]


def cases(conn, *, pack_id: str = "", limit: int = DEFAULT_CASES) -> list[dict]:
    """The fixed set, derived from the installed store.

    Ordered by `subject_id` rather than by anything interesting on purpose: a
    benchmark whose cases change with the data is not a benchmark. Subjects
    that already carry claims come first, because a subject nothing has ever
    researched measures the researcher against an empty baseline and is the
    weakest case available.
    """
    sql = (
        "SELECT s.subject_id, s.pack_id, s.label,"
        " (SELECT COUNT(*) FROM claims c WHERE c.subject_id = s.subject_id) AS claims"
        " FROM subjects s"
    )
    args: list = []
    if pack_id:
        sql += " WHERE s.pack_id = ?"
        args.append(pack_id)
    sql += " ORDER BY claims > 0 DESC, s.subject_id LIMIT ?"
    args.append(max(1, min(limit, 50)))
    return [
        {
            "subject_id": row["subject_id"],
            "pack_id": row["pack_id"],
            "label": row["label"],
            "claims": row["claims"],
        }
        for row in conn.execute(sql, args).fetchall()
    ]


def run_case(
    settings,
    case: dict,
    *,
    plane: str,
    protocol: str = "",
    max_documents: int = 3,
    budget_usd: float = DEFAULT_BUDGET_USD,
    batch_id: str = "",
    search: str = "",
    opener=None,
) -> dict:
    """One case, measured — dispatched on the case's `kind` (B126 §3/§9).

    `specific`, `bulk` and `validation` fail differently and are scored
    differently, so this is a dispatcher rather than one function with a
    branch buried in it: each kind gets its own body and its own docstring,
    and a caller that only ever ran `specific` cases never had to change.

    `search` names the search provider to use on the paid plane (B126 §8),
    the same way `protocol` names the batch/context/preamble setting — a
    sweep axis, not a call-site decision. **Not yet wired from the job that
    drives a sweep** (`app/web/tasks.py:bench`), which loops over `protocol`
    and `reps` but not this; see this module's own note in the design doc
    and the final report for the exact two-line change that job needs.

    `opener` is a testing seam for `validation` cases only — the fresh fetch
    a validation run does needs no network in a test, exactly as
    `app/factcheck.py` (which this borrows) already allows.
    """
    kind = str(case.get("kind") or "specific")
    if kind == "bulk":
        return _run_bulk(
            settings, case, plane=plane, protocol=protocol,
            max_documents=max_documents, budget_usd=budget_usd,
            batch_id=batch_id, search=search,
        )
    if kind == "validation":
        return _run_validation(
            settings, case, plane=plane, protocol=protocol, batch_id=batch_id,
            opener=opener,
        )
    return _run_specific(
        settings, case, plane=plane, protocol=protocol,
        max_documents=max_documents, budget_usd=budget_usd,
        batch_id=batch_id, search=search,
    )


def _spend_columns(protocol: str) -> tuple[dict, str]:
    """`(context_chars/batch_size, error)` for a named protocol, or `({}, "")`
    for none. Shared by every kind so an unknown protocol name fails the same
    way whichever kind asked for it."""
    if not protocol:
        return {}, ""
    from app import protocols

    spend = protocols.BY_NAME.get(protocol)
    if spend is None:
        return {}, f"no such protocol: {protocol}"
    return {"context_chars": spend.context_chars, "batch_size": spend.batch_size}, ""


def _run_specific(
    settings, case: dict, *, plane: str, protocol: str, max_documents: int,
    budget_usd: float, batch_id: str, search: str = "",
) -> dict:
    """One subject, the ordinary research operation — precision/recall per
    claim (B126 §3). The original shape of this benchmark, before `bulk` and
    `validation` existed.

    Goes through `tasks.research` rather than around it: what is being measured
    is the plane *as the reader runs it*, including the gate that refuses most
    of what comes back. A benchmark that called the researcher directly would
    measure a code path nobody uses and would report an acceptance rate of one.
    """
    from app.web import tasks

    row = {
        "batch_id": batch_id,
        "subject_id": case["subject_id"],
        "subject": case.get("label") or case["subject_id"],
        "pack_id": case.get("pack_id") or "",
        "plane": plane,
        "context_chars": None,
        "batch_size": None,
        "protocol": protocol,
        "search_provider": search,
        "kind": "specific",
    }
    columns, error = _spend_columns(protocol)
    if error:
        row["error"] = error
        return row
    row.update(columns)
    with tempfile.TemporaryDirectory(prefix="kriko-bench-") as scratch:
        sandbox = Path(scratch)
        _copy_store(settings.store_path, sandbox / "knowledge.sqlite")
        measured = replace(
            settings,
            store_path=sandbox / "knowledge.sqlite",
            app_state_path=sandbox / "app.sqlite",
            analysis_log_path=sandbox / "analyses.jsonl",
        )
        progress = _Silent()
        started = time.perf_counter()
        try:
            result = tasks.research(
                measured,
                {
                    "subject_id": case["subject_id"],
                    "pack_id": case.get("pack_id") or "",
                    "backend": plane,
                    "protocol": protocol,
                    "search": search,
                    "max_documents": max_documents,
                    "budget_usd": budget_usd,
                },
                progress,
            )
        except Exception as exc:  # noqa: BLE001 — a failed case is a measurement
            row["ms"] = int((time.perf_counter() - started) * 1000)
            row["error"] = f"{type(exc).__name__}: {exc}"
            return row
        row["ms"] = int((time.perf_counter() - started) * 1000)

    # Judged against ground truth where the case carries any (B126). The
    # claims are read back out of the verdicts rather than re-derived, so what
    # is scored is exactly what the gate let through — which is what a reader
    # would have seen.
    if case.get("must_find") or case.get("must_not_find") or case.get("known_absent"):
        from app import gold

        produced = [
            {"title": one.get("title", ""), "domain": one.get("domain", ""),
             "quote": one.get("quote", "")}
            for one in (result.get("accepted") or [])
        ]
        row["gold"] = gold.judge(case, produced)

    row["model"] = result.get("llm") or result.get("model") or plane
    row["search_provider"] = result.get("search_provider") or search or row["search_provider"]
    row["tokens"] = result.get("tokens_used")
    row["usd"] = result.get("spent_usd")
    row["documents"] = int(result.get("documents") or 0)
    accepted = result.get("accepted") or []
    refused = result.get("rejected") or []
    row["accepted"] = len(accepted)
    row["refused"] = len(refused)
    row["findings"] = len(accepted) + len(refused)
    row["reasons"] = [one.get("reason", "")[:200] for one in refused[:5]]
    row["note"] = result.get("note") or ""
    return row


def _run_bulk(
    settings, case: dict, *, plane: str, protocol: str, max_documents: int,
    budget_usd: float, batch_id: str, search: str = "",
) -> dict:
    """An agenda run over N subjects — throughput, and whether quality
    *degrades with volume* (B126 §3), the failure a single-case benchmark
    cannot see.

    The subjects are **pack-authored**, not derived or enumerated here: a
    `bulk` gold case names its own `subject_ids`, exactly as a `specific` case
    names one `subject_id`. That keeps the scalability rule intact — nothing
    in this module hand-lists a car, a model or a config — while still letting
    a pack author decide which group of subjects is worth sweeping together.
    Subjects no longer installed are skipped and counted, never silently
    dropped: a case whose subject was uninstalled mid-run is exactly the kind
    of thing a benchmark exists to notice.
    """
    from app import gold

    subject_ids = list(case.get("subject_ids") or [case.get("subject_id")])
    subject_ids = [one for one in subject_ids if one]
    row = {
        "batch_id": batch_id,
        "subject_id": case.get("subject_id") or (subject_ids[0] if subject_ids else ""),
        "subject": case.get("label") or "bulk",
        "pack_id": case.get("pack_id") or "",
        "plane": plane,
        "protocol": protocol,
        "search_provider": search,
        "kind": "bulk",
        "context_chars": None,
        "batch_size": None,
    }
    columns, error = _spend_columns(protocol)
    if error:
        row["error"] = error
        return row
    row.update(columns)
    if not subject_ids:
        row["error"] = "bulk case names no subject_ids"
        row["ms"] = 0
        return row

    produced_by_subject: dict[str, list[dict]] = {}
    missing_subjects: list[str] = []
    accepted_total = refused_total = documents_total = 0
    tokens_total = 0
    usd_total = 0.0
    priced = 0
    started = time.perf_counter()
    for subject_id in subject_ids:
        sub_case = {**case, "subject_id": subject_id, "kind": "specific"}
        one = _run_specific(
            settings, sub_case, plane=plane, protocol=protocol,
            max_documents=max_documents, budget_usd=budget_usd,
            batch_id=batch_id, search=search,
        )
        if one.get("error"):
            # "A claimed uninstalled" and "the plane failed" look the same
            # from here — both are `KeyError`/`ValueError` from a missing
            # subject or a research failure — and either way the subject is
            # skipped and counted rather than silently dropped from the mean.
            missing_subjects.append(subject_id)
            continue
        produced_by_subject[subject_id] = one.get("gold") or {}
        accepted_total += int(one.get("accepted") or 0)
        refused_total += int(one.get("refused") or 0)
        documents_total += int(one.get("documents") or 0)
        if one.get("tokens") is not None:
            tokens_total += int(one["tokens"])
        if one.get("usd") is not None:
            usd_total += float(one["usd"])
            priced += 1
        row["model"] = one.get("model") or row.get("model")

    row["ms"] = int((time.perf_counter() - started) * 1000)
    row["accepted"] = accepted_total
    row["refused"] = refused_total
    row["findings"] = accepted_total + refused_total
    row["documents"] = documents_total
    row["tokens"] = tokens_total or None
    row["usd"] = round(usd_total, 6) if priced else None
    row["claims_per_minute"] = (
        round(accepted_total / (row["ms"] / 60000), 3) if row["ms"] else None
    )
    row["missing_subjects"] = missing_subjects
    if len(missing_subjects) == len(subject_ids):
        row["error"] = (
            f"every subject in this bulk case failed or was uninstalled: "
            f"{', '.join(missing_subjects)}"
        )
    if case.get("must_find") or case.get("must_not_find") or case.get("known_absent"):
        row["gold"] = gold.judge_bulk(case, produced_by_subject)
    row["note"] = (
        f"{len(produced_by_subject)}/{len(subject_ids)} subject(s) measured"
        + (f"; skipped {len(missing_subjects)}" if missing_subjects else "")
    )
    return row


def _run_validation(
    settings, case: dict, *, plane: str, protocol: str, batch_id: str, opener=None,
) -> dict:
    """Re-check claims already in the store against their retained documents
    and a fresh fetch (B126 §3) — drift, and whether the plane can say "this
    no longer holds".

    No plane runs here and no LLM is asked to judge anything: this kind needs
    neither, which is the point (the automation principle: no human and no
    self-grading model in the data path). It borrows `app/factcheck.py`'s
    mechanical re-check — a substring test against a freshly fetched page —
    and scores it against the case's `must_find`/`must_not_find`/
    `known_absent` the same way every other kind does: matching the *stored*
    claim's title against the gold entries, not the fresh page's content.
    """
    from app import factcheck, gold
    from kriko.store.db import connect

    row = {
        "batch_id": batch_id,
        "subject_id": case["subject_id"],
        "subject": case.get("label") or case["subject_id"],
        "pack_id": case.get("pack_id") or "",
        "plane": plane,
        "protocol": protocol,
        "kind": "validation",
        "context_chars": None,
        "batch_size": None,
        "search_provider": "",
        "model": "factcheck",
    }
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="kriko-bench-") as scratch:
        sandbox = Path(scratch) / "knowledge.sqlite"
        _copy_store(settings.store_path, sandbox)
        conn = connect(sandbox)
        try:
            claims = conn.execute(
                # `title` is language-carrying (`claim_text`), not a column
                # on `claims` itself. `GROUP BY` picks one language per
                # (claim, quote) pair deterministically rather than
                # duplicating the row once per translation.
                "SELECT c.claim_id, ct.title, c.domain, e.quote, s.url"
                " FROM claims c"
                " JOIN claim_text ct ON ct.claim_id = c.claim_id AND ct.pack_id = c.pack_id"
                " JOIN evidence e ON e.claim_id = c.claim_id AND e.pack_id = c.pack_id"
                " JOIN sources s ON s.source_id = e.source_id AND s.pack_id = c.pack_id"
                " WHERE c.subject_id = ? AND c.pack_id = ?"
                " GROUP BY c.claim_id, e.evidence_id",
                (case["subject_id"], case.get("pack_id") or ""),
            ).fetchall()
        except Exception as exc:  # noqa: BLE001 — a bad copy is a measurement too
            row["ms"] = int((time.perf_counter() - started) * 1000)
            row["error"] = f"{type(exc).__name__}: {exc}"
            return row
        finally:
            conn.close()

    if not claims:
        row["ms"] = int((time.perf_counter() - started) * 1000)
        row["error"] = f"no stored claims for {case['subject_id']} to validate"
        row["documents"] = 0
        row["accepted"] = row["refused"] = row["findings"] = 0
        return row

    rechecked = []
    for claim in claims:
        verdict = factcheck.check_source(claim["quote"], claim["url"], opener=opener)
        rechecked.append({
            "claim_id": claim["claim_id"], "title": claim["title"],
            "domain": claim["domain"], "verdict": verdict["verdict"],
        })

    row["ms"] = int((time.perf_counter() - started) * 1000)
    row["documents"] = len({c["url"] for c in claims})
    still_supported = sum(1 for one in rechecked if one["verdict"] == factcheck.QUOTED)
    row["accepted"] = still_supported
    row["refused"] = len(rechecked) - still_supported
    row["findings"] = len(rechecked)
    row["note"] = (
        f"{still_supported}/{len(rechecked)} claim(s) still quoted on their "
        "retained source"
    )
    if case.get("must_find") or case.get("must_not_find") or case.get("known_absent"):
        row["gold"] = gold.judge_validation(case, rechecked)
    return row


class _Silent:
    """A `Progress` that keeps the lines and cancels nothing.

    The benchmark is its own job; a nested one would need a second row and a
    second worker, and `tasks.research` only ever asks for `log`, `set` and
    `check`.
    """

    def __init__(self):
        self.lines: list[str] = []

    def log(self, line: str) -> None:
        self.lines.append(line)

    def set(self, progress: float, message: str = "") -> None:
        pass

    @property
    def cancelled(self) -> bool:
        return False

    def check(self) -> None:
        pass


#: Why a measured run failed, as a class rather than as a sentence. B124.
#:
#: The hypothesis being tested is that a coding-agent CLI resists being driven
#: as a function — it wants a terminal, it carries the reader's whole
#: configuration, it decides when it is finished. If that is true, its failures
#: will not be random: they will cluster in `auth` (only a human can log in),
#: `start` (it is not where a launcher's PATH says), `shape` (it answered in
#: prose the caller could not read) and `timeout` (it kept working past a
#: ceiling a function needs). A plane that fails *randomly* is unlucky; a plane
#: that fails the same way every time is mis-used.
#:
#: Matched against the recorded error, lowercased, first hit wins. A closed
#: engineering vocabulary — the classes of thing a CLI does instead of
#: answering — and not a list that grows with pack coverage.
FAILURE_CLASSES = (
    ("auth", ("not logged in", "/login", "oauth", "unauthorized", "authentication",
              "invalid api key", "missingkey")),
    ("limit", ("usage limit", "rate limit", "limit reached", "quota", "credit balance",
               "billing", "budgetexceeded")),
    ("start", ("enoent", "not on path", "noharness", "not recognized",
               "cannot find the path")),
    ("timeout", ("timeout", "did not finish within")),
    ("shape", ("without a findings list", "answered in prose", "json", "envelope",
               "error_max_turns", "error_during_execution")),
)


def failure_class(error: str) -> str:
    """Which way this run failed, or `""` when it did not."""
    low = (error or "").lower()
    if not low:
        return ""
    for name, needles in FAILURE_CLASSES:
        if any(needle in low for needle in needles):
            return name
    return "other"


def scored(rows: list[dict]) -> dict:
    """Recall, precision and hallucination across graded rows, with intervals.

    Aggregated per (plane, model, protocol) rather than per case, because the
    question is which *way of running* is better and a per-case table answers a
    different one. Every rate carries a Wilson interval: 60% from five findings
    and 60% from two hundred are different facts, and printing them identically
    is how a benchmark starts being quoted as though it had settled something.
    """
    from app import gold

    groups: dict[tuple, dict] = {}
    for row in rows:
        judged = row.get("gold")
        if not judged:
            continue
        key = (row.get("plane", ""), row.get("model", ""), row.get("protocol", ""))
        seen = groups.setdefault(key, {
            "plane": key[0], "model": key[1], "protocol": key[2],
            "runs": 0, "found": 0, "wanted": 0, "produced": 0, "hallucinated": 0,
        })
        seen["runs"] += 1
        seen["found"] += len(judged.get("found") or [])
        seen["wanted"] += len(judged.get("found") or []) + len(judged.get("missed") or [])
        seen["produced"] += (
            len(judged.get("found") or [])
            + len(judged.get("unlisted") or [])
            + len(judged.get("hallucinated") or [])
        )
        seen["hallucinated"] += len(judged.get("hallucinated") or [])

    out = []
    for seen in groups.values():
        seen["recall"] = (
            round(seen["found"] / seen["wanted"], 3) if seen["wanted"] else None
        )
        seen["recall_interval"] = gold.wilson(seen["found"], seen["wanted"])
        seen["hallucination_rate"] = (
            round(seen["hallucinated"] / seen["produced"], 3)
            if seen["produced"] else None
        )
        seen["hallucination_interval"] = gold.wilson(
            seen["hallucinated"], seen["produced"]
        )
        out.append(seen)
    return {"groups": sorted(out, key=lambda one: (one["plane"], one["model"]))}


def verdict(rows: list[dict]) -> dict:
    """What the measurements say about each plane — including B124's question.

    Deliberately not a judgement with a threshold in it. It reports the shape:
    how many runs, how many failed, and *how* they failed. "Four of five
    harness runs failed, all of them `auth`" is an answer a person can act on —
    log in, or stop driving the CLI unattended — and "four of five failed,
    every one a different way" is a different answer entirely. A single number
    could not tell them apart, which is why this returns the distribution
    rather than a score.
    """
    planes: dict[str, dict] = {}
    for row in rows:
        plane = row.get("plane") or ""
        seen = planes.setdefault(
            plane,
            {"plane": plane, "runs": 0, "failed": 0, "classes": {}, "accepted": 0,
             "refused": 0},
        )
        seen["runs"] += 1
        seen["accepted"] += int(row.get("accepted") or 0)
        seen["refused"] += int(row.get("refused") or 0)
        kind = failure_class(str(row.get("error") or ""))
        if kind:
            seen["failed"] += 1
            seen["classes"][kind] = seen["classes"].get(kind, 0) + 1
    for seen in planes.values():
        judged = seen["accepted"] + seen["refused"]
        seen["acceptance"] = round(seen["accepted"] / judged, 3) if judged else None
        # One class accounting for most failures is the signal B124 is after:
        # a plane that fails the same way every time is being mis-used, not
        # having bad luck.
        if seen["classes"]:
            worst = max(seen["classes"].items(), key=lambda pair: pair[1])
            seen["dominant_failure"] = worst[0] if worst[1] * 2 >= seen["failed"] else ""
        else:
            seen["dominant_failure"] = ""
    return {"planes": sorted(planes.values(), key=lambda one: one["plane"])}


def planes_available(settings) -> list[str]:
    """Which planes this machine can actually run, in the order to run them.

    `agent` is excluded and that is not an oversight: its `gather` returns
    nothing by design — the plane *is* a brief handed to a person — so
    benchmarking it would measure the brief writer and report zero of
    everything.
    """
    from app.providers import harness

    found = []
    if harness.available():
        found.append("harness")
    from app import keys

    # Both keys, not either: `keys.ready()` is the same check the API card
    # uses, and half-configured is a run that fails on its first document
    # rather than a degraded plane worth measuring.
    if keys.ready():
        found.append("api")
    return found
