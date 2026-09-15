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
) -> dict:
    """One case on one plane, measured, against a throwaway store.

    Goes through `tasks.research` rather than around it: what is being measured
    is the plane *as the reader runs it*, including the gate that refuses most
    of what comes back. A benchmark that called the researcher directly would
    measure a code path nobody uses and would report an acceptance rate of one.
    """
    from app.web import tasks
    from app.web.jobs import Progress

    row = {
        "batch_id": batch_id,
        "subject_id": case["subject_id"],
        "subject": case.get("label") or case["subject_id"],
        "pack_id": case.get("pack_id") or "",
        "plane": plane,
        "context_chars": None,
        "batch_size": None,
        "protocol": protocol,
    }
    if protocol:
        from app import protocols

        spend = protocols.BY_NAME.get(protocol)
        if spend is None:
            row["error"] = f"no such protocol: {protocol}"
            return row
        row["context_chars"] = spend.context_chars
        row["batch_size"] = spend.batch_size
    with tempfile.TemporaryDirectory(prefix="kriko-bench-") as scratch:
        sandbox = Path(scratch)
        shutil.copy(settings.store_path, sandbox / "knowledge.sqlite")
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
