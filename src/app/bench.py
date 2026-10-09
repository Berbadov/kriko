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
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from app.web import state
from app.web.jobs import Cancelled
from kriko.store.db import connect

#: How many cases a run uses when nobody says. Three is enough to see a
#: difference between planes and small enough that pressing the button on the
#: paid plane is not a decision to spend real money without noticing.
DEFAULT_CASES = 3

#: And what one benchmark case may spend on the paid plane. Per case, not per
#: run, so adding a case cannot silently multiply the bill by surprise.
DEFAULT_BUDGET_USD = 0.20
#: How long one fixed-set case may run. A quick-look style ask, not a deep
#: run, so the ceiling is chat-shaped rather than research-shaped (B185).
FIXED_CASE_TIMEOUT_SECONDS = 240.0


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


def _copy_settings(source_path, dest_path) -> None:
    """Carry the reader's preferences into the sandbox's own `app.sqlite`.

    A benchmark runs against a scratch `app.sqlite` so its history rows do not
    land in the reader's, and that part is right. What was wrong is that the
    scratch file started *empty* — and preferences live in `app.sqlite`, not
    in the engine's store. So every benchmark silently measured the defaults
    while the caller's comment below said an unset model meant "whichever this
    installation would pick". It did not. It meant "whichever a fresh install
    would pick", which is the one configuration the reader is provably not
    running.

    The visible shape of that: choose a harness, press Benchmark, and the
    numbers come back from a different harness than the one on screen.

    Copying rather than sharing keeps both halves: reads see the real
    settings, writes stay in the scratch file. A source with no settings yet,
    or none at all, is not an error — a fresh install has nothing to carry,
    and a benchmark is not the place to say so.
    """
    source_path = Path(source_path)
    if not source_path.exists():
        return
    read = state.connect(source_path)
    try:
        values = state.all_settings(read)
    finally:
        read.close()
    if not values:
        return
    write = state.connect(Path(dest_path))
    try:
        state.put_settings(write, values)
    finally:
        write.close()


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


def _asker(settings, params: dict, progress):
    """The plane that can `ask`, for the fixed set's cases (B185).

    Only the planes that gather can answer a fixed case, which mirrors the
    sweep's own rule (`pairs`): `agent` writes a brief nobody read.
    """
    from app.web import tasks
    backend = str(params.get("backend") or "").lower()
    if backend == "local":
        return tasks._local_asker(settings, params, progress)
    if backend == "api" and str(params.get("harness") or "").endswith("-api"):
        backend = "harness"
    return tasks._researcher({**params, "backend": backend})


def _run_fixed(settings, case: dict, *, plane: str, protocol: str,
               max_documents: int, budget_usd: float, batch_id: str,
               search: str = "", model: str = "",
               run_settings: dict | None = None,
               check_cancelled: Callable[[], None] | None = None) -> dict:
    """One fixed-set case: a product question against versioned ground truth.

    B185, D6. The case names a product, search queries and its own bar
    (`must_find`, `must_not_find`), so nothing is derived from the installed
    packs and two machines measure the same thing. A quick-look style ask,
    judged by `gold.judge` exactly as a gold case is.
    """
    from app import gold as gold_mod
    from app import quicklook
    row = {
        "batch_id": batch_id,
        "subject_id": case["id"],
        "subject": case.get("product") or case["id"],
        "pack_id": "",
        "plane": plane,
        "protocol": protocol,
        "search_provider": search,
        "kind": "fixed",
        "set_id": case.get("set_id") or "",
        "set_version": case.get("set_version") or "",
        "model": model,
    }
    columns, error = _spend_columns(protocol)
    if error:
        row["error"] = error
        return row
    row.update(columns)
    run_settings = run_settings or {}
    row["detail"] = {"case": case, "settings": run_settings, "answer": None}
    silent = _Silent(check_cancelled)
    silent.check()
    started = time.perf_counter()
    researcher = None
    try:
        researcher = _asker(settings, {
            "backend": plane, "protocol": protocol, "search": search,
            "model": model, "max_documents": max_documents,
            "budget_usd": budget_usd,
            "app_state_path": settings.app_state_path,
            "timeout_seconds": run_settings.get("timeout_seconds") or FIXED_CASE_TIMEOUT_SECONDS,
            "temperature": run_settings.get("temperature", 0),
            "max_tokens": run_settings.get("max_tokens", 1024),
            "harness": run_settings.get("harness", ""),
            "queries": case.get("queries") or [],
        }, silent)
        # ask() does not pass through gather(), which normally applies these
        # ceilings. A fixed case must honour the same run controls.
        for name, value in (("max_documents", max_documents),
                            ("max_pages", max_documents), ("budget_usd", budget_usd)):
            if hasattr(researcher, name):
                setattr(researcher, name, value)
        row["model"] = str(getattr(researcher, "requested_model", "")
                           or getattr(researcher, "model", "") or model or plane)
        if hasattr(researcher, "on_action"):
            researcher.on_action = silent.log
        if hasattr(researcher, "check_cancelled"):
            researcher.check_cancelled = silent.check
        if hasattr(researcher, "ask_quick"):
            reply = researcher.ask_quick(case.get("product") or case["id"])
        else:
            reply = researcher.ask(quicklook.brief(case.get("product") or case["id"], "", None, "", ""))
        silent.check()
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - a failed case is a measurement
        row["ms"] = int((time.perf_counter() - started) * 1000)
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["detail"].update(error=row["error"], error_code=getattr(exc, "code", ""),
                             runtime=getattr(researcher, "runtime", {}),
                             telemetry=getattr(researcher, "telemetry", {}),
                             sources=getattr(researcher, "sources", {}))
        return row
    row["ms"] = int((time.perf_counter() - started) * 1000)
    found = quicklook.parse(reply, getattr(researcher, "sources", None))
    row["documents"] = len(getattr(researcher, "sources", {}))
    row["detail"].update(answer=found, raw_reply=reply,
                         sources=getattr(researcher, "sources", {}),
                         runtime=getattr(researcher, "runtime", {}),
                         telemetry=getattr(researcher, "telemetry", {}))
    produced = [
        {"title": one.get("title", ""), "domain": one.get("domain", ""),
         "quote": one.get("quote", "")}
        for one in (found.get("risks") or [])
    ]
    judged = gold_mod.judge(case, produced)
    row["gold"] = judged
    row["model"] = str(getattr(researcher, "requested_model", "")
                       or getattr(researcher, "model", "") or model or plane)
    row["search_provider"] = (
        str(getattr(researcher, "search_provider", "") or "") or search
        or row["search_provider"])
    row["tokens"] = getattr(researcher, "tokens_used", None)
    row["usd"] = getattr(researcher, "spent", None) if (
        getattr(researcher, "cost_basis", "") == "per_token") else None
    row["accepted"] = len(produced)
    row["refused"] = int(found.get("dropped") or 0)
    row["findings"] = row["accepted"] + row["refused"]
    row["note"] = ""
    return row


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
    model: str = "",
    run_settings: dict | None = None,
    opener=None,
    check_cancelled: Callable[[], None] | None = None,
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
    if check_cancelled is not None:
        check_cancelled()
    kind = str(case.get("kind") or "specific")
    if kind == "fixed":
        return _run_fixed(
            settings, case, plane=plane, protocol=protocol,
            max_documents=max_documents, budget_usd=budget_usd,
            batch_id=batch_id, search=search, model=model,
            run_settings=run_settings,
            check_cancelled=check_cancelled,
        )
    if kind == "bulk":
        return _run_bulk(
            settings, case, plane=plane, protocol=protocol,
            max_documents=max_documents, budget_usd=budget_usd,
            batch_id=batch_id, search=search, model=model,
            check_cancelled=check_cancelled,
        )
    if kind == "validation":
        return _run_validation(
            settings, case, plane=plane, protocol=protocol, batch_id=batch_id,
            opener=opener, check_cancelled=check_cancelled,
        )
    return _run_specific(
        settings, case, plane=plane, protocol=protocol,
        max_documents=max_documents, budget_usd=budget_usd,
        batch_id=batch_id, search=search, model=model,
        check_cancelled=check_cancelled,
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
    budget_usd: float, batch_id: str, search: str = "", model: str = "",
    check_cancelled: Callable[[], None] | None = None,
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
        _copy_settings(settings.app_state_path, sandbox / "app.sqlite")
        measured = replace(
            settings,
            store_path=sandbox / "knowledge.sqlite",
            app_state_path=sandbox / "app.sqlite",
            analysis_log_path=sandbox / "analyses.jsonl",
        )
        progress = _Silent(check_cancelled)
        progress.check()
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
                    # Empty means "whichever this installation would pick",
                    # exactly as `protocol` and `search` already do — so a
                    # benchmark that names no model measures the reader's own
                    # setting rather than one this file chose for them.
                    "model": model,
                    "max_documents": max_documents,
                    "budget_usd": budget_usd,
                },
                progress,
            )
        except Cancelled:
            raise
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
    budget_usd: float, batch_id: str, search: str = "", model: str = "",
    check_cancelled: Callable[[], None] | None = None,
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
        if check_cancelled is not None:
            check_cancelled()
        sub_case = {**case, "subject_id": subject_id, "kind": "specific"}
        one = _run_specific(
            settings, sub_case, plane=plane, protocol=protocol,
            max_documents=max_documents, budget_usd=budget_usd,
            batch_id=batch_id, search=search, model=model,
            check_cancelled=check_cancelled,
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
    check_cancelled: Callable[[], None] | None = None,
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
        if check_cancelled is not None:
            check_cancelled()
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
    job_id = ""

    def __init__(self, check_cancelled: Callable[[], None] | None = None):
        self.lines: list[str] = []
        self.result: dict = {}
        self._check_cancelled = check_cancelled
        # tasks.py sets `researcher.replies = progress.replies` on any
        # researcher that has the attribute at all — a harness researcher
        # does, since it can be asked mid-run whether the reader answered a
        # conversation. Bench never opens one, so there is nothing to give
        # back, but the attribute has to exist or every harness-plane case
        # raises `AttributeError` before it can be scored.
        self.replies: Callable[[], list[str]] = lambda: []

    def log(self, line: str) -> None:
        self.lines.append(line)

    def set(self, progress: float, message: str = "") -> None:
        pass

    @property
    def cancelled(self) -> bool:
        try:
            self.check()
        except Cancelled:
            return True
        return False

    def check(self) -> None:
        if self._check_cancelled is not None:
            self._check_cancelled()

    def partial(self, result: dict) -> None:
        self.result = dict(result)


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
        key = (row.get("plane", ""), row.get("model", ""), row.get("protocol", ""),
               str(row.get("set_id") or ""), str(row.get("set_version") or ""))
        seen = groups.setdefault(key, {
            "plane": key[0], "model": key[1], "protocol": key[2],
            "runs": 0, "found": 0, "wanted": 0, "produced": 0, "hallucinated": 0,
            "set_id": key[3], "set_version": key[4],
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


KNOWN_PLANES = ("harness", "agent", "api", "local")


def split_axis(params: dict, *names: str) -> list[str]:
    for name in names:
        raw = params.get(name)
        if raw is None:
            continue
        if isinstance(raw, (list, tuple)):
            items = [str(one).strip() for one in raw]
        else:
            items = [one.strip() for one in str(raw).split(",")]
        found: list[str] = []
        for one in items:
            if one and one not in found:
                found.append(one)
        if found:
            return found
    return []


def validate(params: dict) -> dict:
    from app import keys
    from app import protocols

    from app import benchcases
    requested_cases = params.get("case_ids") or []
    known_cases = {one["id"] for one in benchcases.case_rows(50)}
    unknown_cases = set(requested_cases) - known_cases
    if unknown_cases:
        raise ValueError("unknown test case(s): " + ", ".join(sorted(unknown_cases)))
    planes = split_axis(params, "planes")
    unknown_planes = [one for one in planes if one not in KNOWN_PLANES]
    if unknown_planes:
        raise ValueError(f"unknown plane(s): {', '.join(unknown_planes)}")
    protocols_asked = split_axis(params, "protocols")
    unknown_protocols = [
        one for one in protocols_asked if one not in protocols.BY_NAME
    ]
    if unknown_protocols:
        raise ValueError(f"unknown protocol(s): {', '.join(unknown_protocols)}")
    searches_asked = split_axis(params, "searches", "search")
    unknown_searches = [
        one for one in searches_asked if one not in keys.SEARCH_PROVIDERS
    ]
    if unknown_searches:
        raise ValueError(
            f"unknown search provider(s): {', '.join(unknown_searches)}"
        )
    return {
        "planes": planes,
        "protocols": protocols_asked,
        "searches": searches_asked,
        "models": split_axis(params, "models", "model", "llms", "llm"),
    }


def llm_owners() -> dict[str, set[str]]:
    """Which plane each LLM name belongs to, as this machine names them.

    The harness plane's names come from its CLIs (`harness.models_for`), the
    paid plane's from the catalogue. Two namespaces, and a sweep that crossed
    them sent `opus` to the completion endpoint and `gpt-4o-mini` to
    `claude --model` — two runs per pair that could only fail, billed as
    measurements.
    """
    from app import modelcatalogue
    from app.providers import harness

    owners: dict[str, set[str]] = {}
    for names in harness.models_for_each(harness.available()).values():
        for name in names:
            owners.setdefault(name, set()).add("harness")
    for name in modelcatalogue.load():
        owners.setdefault(name, set()).add("api")
    return owners


def owners_for(params: dict) -> dict[str, set[str]]:
    owners = llm_owners()
    # A named agent's served model choices take precedence over overlapping
    # namespaces, such as an Ollama model also named in the API catalogue.
    agent = str(params.get("harness") or "")
    if agent:
        plane = "local" if agent == "local" else "api" if agent.endswith("-api") else "harness"
        for name in split_axis(params, "models", "model", "llms", "llm"):
            owners[name] = {plane}
    return owners


def pairs(planes: list[str], models: list[str],
          owners: dict[str, set[str]] | None = None) -> list[tuple[str, str]]:
    """`(plane, llm)` for every run a sweep makes, before cases and reps.

    A name one plane owns runs on that plane only; a name nobody owns (a
    gateway's, a model released this morning) runs on every plane, as it
    always did. A plane left with none of the named LLMs runs once on its
    default — empty on an axis means "whatever this installation would pick".
    """
    owners = owners or {}
    out: list[tuple[str, str]] = []
    for plane in planes:
        mine = [m for m in models if not owners.get(m) or plane in owners[m]]
        out += [(plane, m) for m in (mine or [""])]
    return out


def grid(params: dict, case_count: int,
         owners: dict[str, set[str]] | None = None) -> dict:
    """How many measurements a request asks for, and along which axes.

    Every axis here multiplies, which is the whole reason the reader asked to
    scope this: cases × (plane, LLM) pairs × protocols × searches × reps.
    Three cases, two planes and three protocols at two reps is thirty-six
    runs, and nothing on the screen said so before pressing.

    Empty on an axis means "one — whatever this installation would pick",
    never "all of them". A benchmark that swept every axis by default is one
    nobody presses twice.
    """
    planes = split_axis(params, "planes") or ["(this machine's)"]
    models = split_axis(params, "models", "model", "llms", "llm")
    runs_of = pairs(planes, models, owners)
    axes = {
        "cases": max(1, case_count),
        "planes": len(planes),
        "protocols": len(split_axis(params, "protocols") or [""]),
        "searches": len(split_axis(params, "searches", "search") or [""]),
        "models": len(models or [""]),
        "reps": max(1, min(int(params.get("reps") or 1), 10)),
    }
    per_pair = axes["cases"] * axes["protocols"] * axes["searches"] * axes["reps"]
    return {"axes": axes, "runs": per_pair * len(runs_of),
            "paid_runs": per_pair * sum(1 for plane, _ in runs_of if plane == "api")}


def estimate(conn, params: dict, case_count: int) -> dict:
    """What this grid is likely to cost, before anybody presses it.

    "Benchmarking everything costs a lot. I need to scope it." Scoping without
    a number is still guessing — so this multiplies the grid by what a measured
    run has actually cost *here*, and says `None` where nothing has been
    measured rather than inventing a figure. Same refusal as `app/costs.py`,
    for the same reason: the next decision is whether to spend.

    Only the paid plane is priced. A harness run's marginal cost really is
    zero, and counting it as free is a measurement rather than an optimism.
    """
    from app import costs

    validate(params)
    shape = grid(params, case_count, owners_for(params))
    per_run = costs.estimate(conn, plane="api")
    usd, tokens = per_run.get("usd"), per_run.get("tokens")
    priced = shape["runs"]
    planes = split_axis(params, "planes")
    if planes and "api" not in planes:
        # Nothing paid in this grid at all.
        return {**shape, "usd": 0.0, "tokens": 0, "basis": per_run.get("basis", 0),
                "note": "no paid plane in this grid — nothing to spend"}
    if planes:
        priced = shape["paid_runs"]
    return {
        **shape,
        "usd": round(usd * priced, 4) if isinstance(usd, (int, float)) else None,
        "tokens": int(tokens * priced) if isinstance(tokens, (int, float)) else None,
        "basis": per_run.get("basis", 0),
        "note": per_run.get("note", ""),
    }


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
    from app import localplane

    if localplane.is_ready():
        found.append("local")
    return found
