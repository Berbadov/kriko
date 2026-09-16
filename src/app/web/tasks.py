"""The two operations that actually grow the knowledge base.

Before this module both were terminal-only, which is the specific thing G6's
delivery constraint forbids. Neither handler invents any logic: `research`
drives `kriko.research`'s `Researcher` protocol and hands what comes back to
`app.findings.accept_findings` — the same acceptance path MCP uses, so a claim's
provenance does not depend on which door it came in. `pack_build` runs the same
builder `app.cli`'s `kriko pack build` runs.

A handler is `(settings, params, progress) -> dict`. It reports through
`progress` only: printing to stdout would be invisible in the browser, which is
the whole point of the jobs layer.
"""

import importlib
import secrets
from datetime import UTC, datetime
from pathlib import Path

from app import packsource

from app.findings import accept_findings, log_submission, retract_claim
from app.web import pipeline, state
from app.web.jobs import Cancelled, Progress
from kriko.pack import updates
from kriko.research import BudgetExceeded, get_researcher, plan_task
from kriko.store import packstore
from kriko.store.db import connect


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _subject_pack(conn, subject_id: str) -> str:
    row = conn.execute(
        "SELECT pack_id FROM subjects WHERE subject_id = ?", (subject_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no subject {subject_id} is installed")
    return row["pack_id"]


#: What one paid call is assumed to cost, when nobody says otherwise.
#:
#: A deliberate over-estimate. `ApiResearcher._charge` adds this per search and
#: per completion and stops the run when the total passes the ceiling, so the
#: number's only job is to make the ceiling arrive *early* rather than late.
#: Guessing low means a budget that is exceeded before it triggers, which is
#: the failure this whole mechanism exists to prevent; guessing high means a
#: run that stops with money left, which the reader can simply raise.
DEFAULT_PRICE_PER_CALL = 0.01

#: The ceiling a paid single-subject run gets when the caller names none.
#:
#: Not zero. `ApiResearcher._charge` treats `budget_usd = 0` as *unlimited* —
#: correct for the agent plane, whose marginal cost really is zero, and exactly
#: wrong for this one. A paid run with no ceiling is the $40 bill.
DEFAULT_BUDGET_USD = 0.20


def default_backend() -> str:
    """The plane a run gets when the caller names none.

    It used to be `agent` unconditionally, and `agent` fetches nothing by
    design — it writes a brief for somebody else to read. On a machine with a
    coding-agent CLI installed that made pressing **Research** produce a brief
    and a `succeeded / 0 claim(s) kept`, which is the second time the reader
    reported the same experience: "run nothing again".

    So: the best plane that is free *and* can actually gather. `harness` when
    a CLI is on PATH, `agent` otherwise. `api` is still never chosen by
    omission — a tool that starts spending money because a key happened to be
    in the environment is a tool people stop trusting, and that reasoning was
    always about the paid plane rather than about defaulting to a no-op.
    """
    try:
        from app.providers import harness

        if harness.available():
            return "harness"
    except Exception:  # noqa: BLE001 - a missing CLI must never fail a run
        pass
    return "agent"


def _researcher(params: dict):
    """The plane this run asked for, wired to whatever it needs.

    The `agent` plane needs nothing, which is why it is the default and why it
    is the one that works on a machine with no keys. The `api` plane needs
    three callables, and `app/providers/` is where the sockets live — the
    engine owns none, so `kriko.research` could never have built this itself.
    """
    backend = str(params.get("backend") or default_backend()).lower()
    if backend == "harness":
        # Same reason as the paid plane below, one layer out: this one spawns a
        # process, and `kriko/` owns no subprocesses any more than it owns
        # sockets. So it is not a `get_researcher` backend and never will be.
        from app.providers import harness_researcher

        return harness_researcher(
            preferred=str(params.get("harness") or ""),
            timeout=float(params.get("timeout_seconds") or 0.0),
            # So "which agent" is the reader's standing choice rather than
            # whichever CLI happened to be found first (B117).
            app_state_path=params.get("app_state_path"),
        )
    if backend != "api":
        return get_researcher({"backend": backend})
    from app.providers import api_researcher

    price = float(params.get("price_per_call") or DEFAULT_PRICE_PER_CALL)
    # The protocol: named by the caller when something is deliberately
    # measuring one (the benchmark), and otherwise chosen from this
    # installation's own measurements. `settings` is not in scope here, so the
    # path comes through params — the same way every other per-run decision
    # reaches this function.
    from app import protocols

    named = str(params.get("protocol") or "")
    return api_researcher(
        price_per_call=price,
        app_state_path=params.get("app_state_path"),
        spend=protocols.BY_NAME.get(named) if named else None,
        model=str(params.get("model") or ""),
        search=str(params.get("search") or ""),
    )


def _budget(params: dict) -> float:
    """The ceiling, with the paid plane's floor applied.

    A caller may raise it or lower it; a caller may not leave the paid plane
    uncapped by omission.
    """
    named = float(params.get("budget_usd") or 0.0)
    if str(params.get("backend") or default_backend()).lower() != "api":
        return named
    return named if named > 0 else DEFAULT_BUDGET_USD


#: What each plane does *instead of* fetching, and what the reader does next.
#:
#: A run that gathers nothing is not a failure on two of the three planes — it
#: is the design — but "succeeded / 0 claim(s) kept" is indistinguishable from
#: a broken button, and that is precisely what a reader reported on 0.5.3. The
#: log is the one place they looked, so the log has to answer it. Keyed by
#: plane so a new plane cannot be added without deciding what its empty run
#: means.
EMPTY_RUN = {
    "agent": (
        "this plane fetches nothing itself — the brief above IS the output. "
        "Nothing can be kept until an agent reads it: press “Run my agent on "
        "this” to have Kriko run your installed agent headlessly, hand the "
        "brief to a connected agent yourself, or wire one up in Agents → "
        "Connect."
    ),
    "harness": (
        "your agent ran and came back with nothing usable. That is a coverage "
        "answer, not an error: either the sources it can reach say nothing "
        "specific about this subject, or everything they say was too generic "
        "to keep. The queries it was seeded with are above."
    ),
    "api": (
        "the searches returned nothing this plane could read. Check the "
        "queries above, and Settings → Research for the search key."
    ),
}


def _empty_run_note(researcher) -> str:
    """Why this run has no documents, in the plane's own terms.

    A plane may override the sentence by setting `note` — the harness plane
    does, because "the CLI answered without a findings list" and "the CLI found
    nothing" are different problems with different fixes, and only the plane
    knows which happened.
    """
    own = str(getattr(researcher, "note", "") or "").strip()
    general = EMPTY_RUN.get(researcher.name, "")
    if own and general:
        return f"{own} — {general}"
    return own or general or (
        f"the {researcher.name} plane gathered nothing and said nothing about why"
    )


def _queries_run(researcher, task) -> list[str]:
    """What was actually searched for, preferring the researcher's own account.

    A plane that drives an agent hands it seeds and expects them to be adapted
    (B95), so its `queries_run` is the truth and the pack's rendered templates
    are only what it was offered. A plane that runs the templates literally
    reports nothing, and then the templates *are* what ran.
    """
    reported = [
        str(query).strip()
        for query in (getattr(researcher, "queries_run", None) or ())
        if str(query).strip()
    ]
    return reported or list(task.rendered_queries())


def _outcome(researcher, documents: int, verdicts: dict) -> str:
    """The one line the jobs list shows for a finished run.

    `0 claim(s) kept` was true and useless. Three different runs produced it —
    a plane that never fetches, a plane that fetched and found nothing, and a
    plane whose findings were all refused — and a reader cannot act on any of
    them without knowing which.
    """
    kept = len(verdicts.get("accepted", []))
    refused = len(verdicts.get("rejected", []))
    if kept:
        return f"{kept} claim(s) kept" + (f", {refused} refused" if refused else "")
    if refused:
        return f"nothing kept — all {refused} finding(s) refused, see the log"
    if not documents:
        if researcher.name == "agent":
            return "brief ready — hand it to an agent, nothing is kept until one reads it"
        return f"nothing found — the {researcher.name} plane read no source"
    return f"read {documents} source(s), none of them said anything keepable"


def _describe_plane(researcher) -> dict:
    """What a provenance row can honestly say about this plane.

    Duck-typed, like `tokens_used` in `_research`: a plane that knows its model
    reports one, and the agent plane leaves both columns empty rather than
    inventing a name for whatever harness the reader happened to be using.
    """
    return {
        "plane": researcher.name,
        "model": str(getattr(researcher, "model", "") or ""),
        "search_provider": str(getattr(researcher, "search_provider", "") or ""),
    }


class _Provenance:
    """The `research_runs` row, kept open across a run's stages.

    A small object rather than three loose calls because the row has to be
    opened before the first request and closed on every path out — including
    the two that are not failures — and threading a connection through
    `_research`'s stages to do that by hand is how one of those paths gets
    forgotten.

    Its connection is `app.sqlite`. Provenance is interface state: see the
    comment on `research_runs` in `app/web/state.py` for why putting it in the
    engine store would make a pack's `content_digest` depend on who grew it.
    """

    def __init__(self, settings, run_id: str, job_id: str, params: dict):
        self._path = getattr(settings, "app_state_path", None)
        self.run_id = run_id
        self._job_id = job_id or ""
        self._budget = _budget(params)
        self._opened = False
        self._researcher = None

    def _connect(self):
        if self._path is None:
            return None
        return state.connect(self._path)

    def open(self, researcher) -> None:
        """Once the plane exists, so the row can name the model rather than
        the intention.

        The researcher is kept so that `close` can read the spend on *every*
        path out, including the ones that raise. A budget stop that recorded no
        spend would be the one run whose cost is unrecoverable.
        """
        self._researcher = researcher
        conn = self._connect()
        if conn is None:
            return
        try:
            state.open_research_run(
                conn,
                self.run_id,
                job_id=self._job_id,
                budget_usd=self._budget or None,
                **_describe_plane(researcher),
            )
            self._opened = True
        finally:
            conn.close()

    def claims(self, pack_id: str, subject_id: str, accepted: list) -> None:
        conn = self._connect()
        if conn is None:
            return
        try:
            state.record_run_claims(conn, self.run_id, pack_id, subject_id, accepted)
        finally:
            conn.close()

    def close(self, outcome: str) -> None:
        """The one exit. Called on every path, including the two that raise."""
        if not self._opened:
            return  # nothing was opened, so there is nothing to contradict
        conn = self._connect()
        if conn is None:
            return
        try:
            state.close_research_run(
                conn, self.run_id, outcome, self.spent(), self.tokens()
            )
        finally:
            conn.close()

    def spent(self) -> float | None:
        """What the plane says it spent, and nothing inferred.

        `ApiResearcher` counts; `AgentResearcher` has no such field and gets
        NULL rather than 0.0, because "cost nothing" and "nobody counted" are
        different answers and the column has to keep them apart.
        """
        value = getattr(self._researcher, "spent", None)
        return float(value) if isinstance(value, (int, float)) else None

    def tokens(self) -> int | None:
        """What the plane says it read and wrote, and nothing inferred.

        The sibling of `spent`, and separate from it because the two planes
        that can count count *different* things: the harness reports its
        tokens and spends none of Kriko's money, and a per-call price knows
        its dollars without ever seeing a token. A single "cost" column would
        have had to pick one and silently drop the other.

        Read on every path out for the same reason as `spent`: a run that
        stopped at its budget is exactly the run whose usage a reader wants,
        and it is the one that raises.
        """
        value = getattr(self._researcher, "tokens_used", None)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)


def research(settings, params: dict, progress: Progress) -> dict:
    """Research one subject, writing down what the pipeline did as it does it.

    Two channels, and they answer different questions. `progress` is the job's
    own log — a line-oriented record of a single run, for the reader watching
    that run. The `Emitter` is the pipeline's record: which stage, how many
    sources, how many findings survived the grounding check, and which source
    each one came from, in tables that outlive the request and can be read
    against yesterday's run.

    A `jobs` row could never have answered the second question. A run that
    gathered nothing and a run that gathered plenty and lost all of it at
    acceptance produce near-identical job logs, and they are entirely
    different problems — the first is discovery, the second is evidence.

    The emitter is constructed here rather than inside `_research` so the
    run is opened before anything can fail: a crash in `plan_task` must leave
    a readable `failed` row, not nothing at all. Nothing about this reaches
    `kriko/` — the stages are boundaries in this driver, which is the layer
    that sequences them.
    """
    emit = pipeline.Emitter(
        getattr(settings, "app_state_path", None),
        kind="research",
        job_id=progress.job_id,
    )
    emit.begin(subject_id=params.get("subject_id") or "")
    # Opened before anything can spend, and closed on every path out. A run
    # that hit its ceiling, was cancelled, or crashed is exactly the run whose
    # provenance a reader needs — and a row written only on success is a row
    # that never exists for any of them.
    provenance = _Provenance(settings, emit.run_id, progress.job_id, params)
    try:
        result = _research(settings, params, progress, emit, provenance)
    except Cancelled:
        # Cancelled is not failed. The reader stopped it, and a view that
        # colours a deliberate stop the same as a crash trains the reader to
        # ignore the colour.
        emit.finish("cancelled", "stopped by the reader")
        provenance.close("cancelled")
        raise
    except BudgetExceeded as stop:
        # Nor is this. The ceiling working as designed is the feature, so it
        # gets its own outcome rather than being coloured as a crash — and it
        # is re-raised, because nothing may catch this and go on spending.
        emit.finish("budget", str(stop))
        provenance.close("budget")
        raise
    except Exception as error:
        emit.finish("failed", f"{type(error).__name__}: {error}")
        provenance.close("failed")
        raise
    emit.finish("done")
    provenance.close("done")
    return result


def _research(settings, params: dict, progress: Progress, emit, provenance=None) -> dict:
    """The run itself, with the four stages named.

    The default plane is `agent`, whose `gather` returns nothing by design —
    the searching is done by a coding-agent harness whose subscription is
    already paid for. So on the default plane this job's real output is the
    brief, and that is not a degraded result: it is the $0 path, and refusing
    to run it because it cannot also fetch would push the cheapest way to grow
    a pack back into the terminal. Which is why the later stages are *skipped*
    rather than completed-with-zero: "Extraction: done, 0 findings" reads as a
    fault, and this is the path working exactly as intended.
    """
    subject_id = params.get("subject_id") or ""
    if not subject_id:
        raise ValueError("subject_id is required")

    conn = connect(settings.store_path)
    try:
        # ── Discovery ────────────────────────────────────────────────────
        emit.open_stage("discovery", "planning the search")
        pack_id = params.get("pack_id") or _subject_pack(conn, subject_id)
        task = plan_task(
            conn,
            subject_id,
            pack_id,
            budget_usd=_budget(params),
            max_documents=int(params.get("max_documents") or 5),
        )
        progress.set(0.1, f"planning {task.subject_label}")
        emit.describe(pack_id=pack_id, subject=task.subject_label)
        for query in task.rendered_queries():
            progress.log(f"query: {query}")
            emit.event(f"query: {query}", detail_kind="query")

        # The interface's own database, so the plane can read what this
        # installation has measured about the model it is about to use.
        researcher = _researcher({**params, "app_state_path": settings.app_state_path})
        # What the plane does while it does it (B121). Duck-typed, like
        # `tokens_used` below: a plane that can narrate gets somewhere to
        # narrate to, and one that cannot is unaffected. The job log is the
        # channel because it already streams to the app and to `kriko tui` —
        # the actions needed a sender, not a second transport.
        if hasattr(researcher, "on_action"):
            researcher.on_action = progress.log
        if hasattr(researcher, "check_cancelled"):
            researcher.check_cancelled = progress.check
        if provenance is not None:
            provenance.open(researcher)
        brief = researcher.brief(task)
        progress.set(0.2, f"{researcher.name} plane ({researcher.cost_basis})")
        emit.describe(plane=researcher.name)
        emit.event(f"{researcher.name} plane, cost {researcher.cost_basis}")
        progress.check()

        documents = researcher.gather(task)
        progress.log(f"gathered {len(documents)} document(s)")
        if not documents:
            # Said in the log, not only in the stage list: the log is what the
            # reader expands, and on 0.5.3 it ended at this line.
            progress.log(_empty_run_note(researcher))
        emit.count(sources=len(documents))
        for document in documents:
            emit.event(
                f"source: {document.site_or_channel or document.url}",
                source_url=document.url,
                title=document.title,
                chars=len(document.text or ""),
            )
        emit.close_stage(detail=f"{len(documents)} source(s)")

        # ── Extraction ───────────────────────────────────────────────────
        findings: list[dict] = []
        if not documents:
            emit.skip_stage("extraction", _empty_run_note(researcher))
        else:
            emit.open_stage("extraction", f"reading {len(documents)} source(s)")
        for index, document in enumerate(documents, start=1):
            progress.check()
            progress.set(
                0.2 + 0.6 * index / max(1, len(documents)),
                f"reading {document.site_or_channel or document.url}",
            )
            emit.count(chars=len(document.text or ""))
            # Per document, because a run stopped halfway through ten sources
            # has read the first five and that is worth keeping.
            progress.partial({
                "subject_id": subject_id, "pack_id": pack_id,
                "documents": index - 1, "findings": len(findings),
                "stopped_at": "extraction",
            })
            found = 0
            for finding in researcher.extract(task, document):
                found += 1
                findings.append(
                    {
                        "title": finding.title,
                        "body": finding.body,
                        "advice": finding.advice,
                        "domain": finding.domain,
                        "severity": finding.severity,
                        "quote": finding.quote,
                        "source_url": finding.source_url,
                        "stance": finding.stance,
                        "component": finding.component,
                        "published_at": document.published_at,
                        # The document text is what makes the grounding check
                        # possible. Without it every finding is refused, which
                        # is the correct failure — "trust me" is not an
                        # evidence model.
                        "document_text": document.text,
                    }
                )
                emit.event(
                    f"found “{finding.title}”",
                    source_url=finding.source_url or document.url,
                    severity=finding.severity,
                    domain=finding.domain,
                )
            emit.count(findings=found)
            if not found:
                emit.event(
                    f"nothing grounded in {document.site_or_channel or document.url}",
                    level="warn",
                    source_url=document.url,
                )
        if documents:
            emit.close_stage(detail=f"{len(findings)} finding(s)")
        # Checkpointed here rather than only at the end: this is the moment the
        # run has cost the most and delivered nothing durable, and it is where
        # a reader watching a long run decides to stop it.
        progress.partial({
            "subject_id": subject_id, "pack_id": pack_id,
            "documents": len(documents), "findings": len(findings),
            "stopped_at": "extraction",
        })

        # Whatever the plane knows about its own spend, and nothing invented.
        # `Researcher` has no token field, so this is a duck-typed hook: a
        # plane that counts reports a number, and every other plane leaves the
        # column NULL. An estimate rendered as a measurement would be the
        # `raised: true` mistake over again.
        used = getattr(researcher, "tokens_used", None)
        if isinstance(used, int):
            emit.describe(tokens=used)

        # ── Ingestion ────────────────────────────────────────────────────
        progress.check()
        verdicts: dict[str, list] = {"accepted": [], "rejected": []}
        #: The text each accepted quote was proved against, kept by
        #: `log_submission` so the proof can be repeated (B120).
        retained: list[dict] = []
        if findings:
            emit.open_stage("ingestion", f"checking {len(findings)} finding(s)")
            progress.set(0.85, f"checking {len(findings)} finding(s)")
            verdicts = accept_findings(
                conn, subject_id, pack_id, findings, retain=retained
            )
            # One more attempt, on the failures only, for the failures a second
            # attempt can honestly fix. See `_repair`.
            verdicts = _repair(
                conn, subject_id, pack_id, verdicts, findings,
                researcher=researcher, task=task, emit=emit,
                progress=progress, retain=retained,
            )
            conn.commit()
            # Written down as soon as the claims exist, not at the end of the
            # run: an undo has to be possible for a run that was cancelled
            # after acceptance, which is precisely when a reader wants it.
            if provenance is not None:
                provenance.claims(pack_id, subject_id, verdicts.get("accepted", []))
            emit.count(
                accepted=len(verdicts.get("accepted", [])),
                refused=len(verdicts.get("rejected", [])),
            )
            emit.close_stage(
                detail=f"{len(verdicts.get('accepted', []))} kept, "
                f"{len(verdicts.get('rejected', []))} refused"
            )
            # The claims are in the store by now, so a cancel after this point
            # must not report them as lost — they are not.
            progress.partial({
                "subject_id": subject_id, "pack_id": pack_id,
                "documents": len(documents),
                "findings": len(findings),
                "accepted": len(verdicts.get("accepted", [])),
                "refused": len(verdicts.get("rejected", [])),
                "stopped_at": "ingestion",
            })

            # ── Ledgering ────────────────────────────────────────────────
            emit.open_stage("ledgering", "writing the verdicts down")
            # The refusals are the point of the ledger, so it is written even
            # when nothing was kept — a batch that lost everything is the one
            # an author most needs to be able to read afterwards.
            log_submission(
                settings.app_state_path,
                door="job",
                subject_id=subject_id,
                pack_id=pack_id,
                verdicts=verdicts,
                queries=_queries_run(researcher, task),
                documents=retained,
            )
            if retained:
                # Said out loud because it is the reader's proof that the
                # evidence can be re-checked later without the page: a run
                # that kept nothing and one that kept everything used to look
                # identical here.
                progress.log(
                    f"kept {len(retained)} document(s) the quotes were checked against"
                )
        else:
            emit.skip_stage("ingestion", "no findings to check")
            emit.skip_stage("ledgering", "nothing to write down")

        for item in verdicts.get("rejected", []):
            progress.log(f"refused “{item['title']}”: {item['reason']}")
            emit.event(
                f"refused “{item['title']}”: {item['reason']}",
                level="refused",
                stage="ledgering",
            )
        for item in verdicts.get("accepted", []):
            progress.log(f"kept “{item['title']}” as {item['claim_id']}")
            emit.event(
                f"kept “{item['title']}”",
                level="kept",
                stage="ledgering",
                claim_id=item["claim_id"],
            )
        if findings:
            emit.close_stage()

        outcome = _outcome(researcher, len(documents), verdicts)
        # Last line on purpose. The reader who expanded this log did it to find
        # out what happened; the brief is the artifact and it is worth nothing
        # if they cannot find it again.
        progress.log(
            f"brief: {len(brief)} characters, kept with this run — reopen it from "
            f"this subject's Research panel, or Activity → Runs"
        )
        progress.set(1.0, outcome)
        # Not closed here: `research` closes the row on every path out,
        # which is the only way the failing paths get one too.
        spent = provenance.spent() if provenance is not None else None
        return {
            "run_id": emit.run_id,
            "spent_usd": spent,
            # Returned as well as stored, so the panel that just watched the
            # run can say what it used without re-reading the runs table.
            "tokens_used": provenance.tokens() if provenance is not None else None,
            "budget_usd": task.budget_usd or None,
            "subject": task.subject_label,
            "pack_id": pack_id,
            **_describe_plane(researcher),
            "cost_basis": researcher.cost_basis,
            "queries": list(task.rendered_queries()),
            "brief": brief,
            "documents": len(documents),
            "outcome": outcome,
            # Why nothing came back, when nothing did. Returned as well as
            # logged so the brief panel can say it without parsing the log.
            "note": _empty_run_note(researcher) if not documents else "",
            **verdicts,
        }
    finally:
        conn.close()


#: How many agenda rows one unattended run will work through by default, and
#: what it may spend doing it. Both deliberately modest: this is the button
#: that runs without anybody watching, and the first time a reader presses it
#: they should be able to read the whole result.
DEFAULT_AGENDA_ROWS = 10
DEFAULT_AGENDA_BUDGET_USD = 0.40


def agenda_run(settings, params: dict, progress: Progress) -> dict:
    """Work down the agenda, one subject at a time, under one shared ceiling.

    This is the answer to "how do I build knowledge with my agents" for someone
    who does not want to pick subjects by hand: `app/agenda.py` already knows
    what is worth researching next, and this walks that list.

    **It calls `_research` inline rather than submitting a job per row.**
    `app/web/jobs.py` has a single worker — a job that submits jobs and waits
    for them deadlocks, and it deadlocks silently, with a queue that never
    drains and a UI that shows two rows spinning forever. Every stage, every
    emitter and every acceptance check is the same code the single-subject door
    runs; only the loop is new.

    **The ceiling is shared, not per row.** Each row is given whatever is left,
    and what it spent is taken off the total. Ten rows with a $0.40 budget each
    would be a $4.00 run wearing a $0.40 label.

    **`unknown_subject` rows are skipped, loudly.** B82 ships them with no
    `subject_id` on purpose: they are identities readers asked about that no
    pack claims, which is a message to whoever grows the catalog, not a task an
    agent can act on. Researching "some car nobody has modelled" is not a
    thing. So they are counted and reported — *"3 rows need a subject before
    anyone can research them"* — rather than silently dropped, which would make
    a run of 10 rows quietly do 7 and look complete.
    """
    from app import agenda as agenda_module

    limit = max(1, int(params.get("rows") or DEFAULT_AGENDA_ROWS))
    backend = str(params.get("backend") or default_backend()).lower()
    ceiling = float(params.get("budget_usd") or 0.0)
    if backend == "api" and ceiling <= 0:
        ceiling = DEFAULT_AGENDA_BUDGET_USD

    store = connect(settings.store_path)
    app_state = state.connect(settings.app_state_path)
    try:
        plan = agenda_module.compute(
            store,
            app_state=app_state,
            log_path=getattr(settings, "analysis_log_path", None),
            pack_id=str(params.get("pack_id") or ""),
            limit=limit,
        )
    finally:
        store.close()
        app_state.close()

    rows = plan.get("rows") or []
    # De-duplicated by subject: the agenda ranks *claims* as well as subjects,
    # so two thin-claim rows on one car are two rows and one research run. Not
    # de-duplicating would spend the budget twice on the same queries.
    subjects: list[dict] = []
    seen: set[str] = set()
    needs_a_subject = 0
    for row in rows:
        if row.get("kind") == "unknown_subject" or not row.get("subject_id"):
            needs_a_subject += 1
            continue
        if row["subject_id"] in seen:
            continue
        seen.add(row["subject_id"])
        subjects.append(row)

    if needs_a_subject:
        progress.log(
            f"{needs_a_subject} row(s) need a subject before anyone can "
            f"research them — they are identities no installed pack claims"
        )

    done: list[dict] = []
    spent_total = 0.0
    tokens_counted: list[int] = []
    stopped = ""
    for index, row in enumerate(subjects, start=1):
        progress.check()
        remaining = ceiling - spent_total if ceiling else 0.0
        if ceiling and remaining <= 0:
            stopped = "budget"
            break
        progress.set(
            index / (len(subjects) + 1),
            f"{row.get('label') or row['subject_id']} ({index} of {len(subjects)})",
        )
        row_params = {
            **params,
            "subject_id": row["subject_id"],
            "pack_id": row.get("pack_id") or "",
            "budget_usd": remaining,
        }
        try:
            result = research(settings, row_params, progress)
        except BudgetExceeded as stop:
            # Not caught to carry on — caught to stop. The next line breaks,
            # and nothing after it spends. `research` has already closed this
            # row's provenance with the `budget` outcome.
            progress.log(f"stopped: {stop}")
            stopped = "budget"
            break
        except Cancelled:
            # Re-raised: the job runner is what marks the row cancelled, and
            # swallowing it here would report a stopped run as a finished one.
            raise
        except Exception as error:  # noqa: BLE001
            # One subject that cannot be researched must not end the run. A
            # missing subject, an adapter with no templates, a provider that
            # refuses one query — each is a row's problem, not the agenda's.
            progress.log(f"{row['subject_id']}: {type(error).__name__}: {error}")
            done.append({"subject_id": row["subject_id"], "error": str(error)})
            continue
        spent_total += float(result.get("spent_usd") or 0.0)
        used = result.get("tokens_used")
        if isinstance(used, int):
            # Accumulated in a list rather than a running int so that "no row
            # could count" stays distinguishable from "every row counted zero"
            # — the same distinction the column keeps, one level up.
            tokens_counted.append(used)
        done.append(
            {
                "subject_id": row["subject_id"],
                "subject": result.get("subject") or "",
                "run_id": result.get("run_id") or "",
                "kept": len(result.get("accepted") or []),
                "refused": len(result.get("rejected") or []),
                "spent_usd": result.get("spent_usd"),
                "tokens_used": used,
            }
        )

    kept = sum(item.get("kept") or 0 for item in done)
    # Same reason as `_outcome`: a bulk run that kept nothing is the shape a
    # reader is most likely to see first, and "0 claim(s) kept across 5
    # subject(s)" tells them nothing about which of the four possible causes
    # it was.
    if kept:
        summary = f"{kept} claim(s) kept across {len(done)} subject(s)"
    elif not done:
        summary = "nothing to research — the agenda came back empty"
    elif backend == "agent":
        summary = (
            f"{len(done)} brief(s) ready, nothing kept — the agent plane does not "
            f"read; run the harness plane or hand the briefs to an agent"
        )
    else:
        summary = (
            f"nothing kept across {len(done)} subject(s) — open a run below for "
            f"the log that says why"
        )
    progress.set(1.0, summary)
    return {
        "rows": done,
        "subjects": len(subjects),
        "needs_a_subject": needs_a_subject,
        "kept": kept,
        "plane": backend,
        "budget_usd": ceiling or None,
        "spent_usd": spent_total if backend == "api" else None,
        # The plane decides, not the loop: a total is reported when at least
        # one row could be counted, and stays None when none could.
        "tokens_used": sum(tokens_counted) if tokens_counted else None,
        "rows_counted": len(tokens_counted),
        "stopped": stopped,
        "outcome": summary,
        "note": plan.get("note") or "",
    }


def research_undo(settings, params: dict, progress: Progress) -> dict:
    """Take a research run's claims back out of the store.

    A job rather than a request because it writes to the engine store once per
    claim and a reader who undoes a forty-claim run should watch it happen
    rather than watch a spinner.

    **Already-absent is reported, not failed.** A claim may have been deleted
    by hand, superseded by a later run, or lost with a pack reinstall — all
    ordinary, and a run that 500s on any of them is an undo nobody trusts. The
    result says *"removed 4 of 6; 2 were already absent"*.
    """
    run_id = str(params.get("run_id") or "")
    if not run_id:
        raise ValueError("run_id is required")

    app_state = state.connect(settings.app_state_path)
    try:
        run = state.get_research_run(app_state, run_id)
        if run is None:
            raise KeyError(f"no research run {run_id}")
        claims = [
            item for item in state.run_claims(app_state, run_id) if not item["removed_at"]
        ]
        if not claims:
            progress.set(1.0, "nothing left to remove")
            return {"run_id": run_id, "removed": 0, "absent": 0, "total": 0,
                    "note": "this run's claims have already been taken out"}

        store = connect(settings.store_path)
        removed = absent = 0
        try:
            for index, claim in enumerate(claims, start=1):
                progress.check()
                progress.set(index / len(claims), f"removing {claim['title'] or claim['claim_id']}")
                if retract_claim(store, claim["pack_id"], claim["claim_id"]):
                    removed += 1
                else:
                    absent += 1
                    progress.log(f"{claim['claim_id']} was already absent")
                state.mark_claim_removed(
                    app_state, run_id, claim["pack_id"], claim["claim_id"]
                )
            store.commit()
            app_state.commit()
        finally:
            store.close()
    finally:
        app_state.close()

    progress.set(1.0, f"removed {removed} of {len(claims)}")
    return {
        "run_id": run_id,
        "removed": removed,
        "absent": absent,
        "total": len(claims),
        "note": (
            f"removed {removed} of {len(claims)}; {absent} were already absent"
            if absent
            else f"removed {removed} claim(s)"
        ),
    }


def pack_build(settings, params: dict, progress: Progress) -> dict:
    """Build a pack directory into a `.kpack`, and install it unless told not to.

    Same path and same rules as `kriko pack build`: a pack shipping its own
    `build.py` gets to use it (pointing the generic builder at such a pack
    "succeeds" and produces a pack with nothing in it), and an artifact with no
    subjects and no claims is refused rather than installed — a pack that can
    answer nothing is a failed build, not a quiet one.
    """
    root = Path(params.get("root") or "")
    if not root.name:
        raise ValueError("root is required")
    if not root.is_dir():
        candidate = settings.packs_dir / root.name
        if not candidate.is_dir():
            raise ValueError(f"not a pack directory: {root}")
        root = candidate

    from kriko.pack.build import build as generic_build
    from kriko.pack.build import digest_of

    out = Path(params.get("out") or settings.dist_dir / f"{root.name}.kpack")
    out.parent.mkdir(parents=True, exist_ok=True)

    progress.set(0.1, f"building {root.name}")
    stats = None
    if (root / "build.py").exists():
        progress.log(f"{root.name} ships its own builder")
        try:
            module = importlib.import_module(f"packs.{root.name}.build")
        except ModuleNotFoundError as exc:
            # The frozen desktop sidecar bundles the engine, not the repo's
            # packs. A pack whose builder is Python can only be built where
            # that Python is importable, and saying so beats a traceback about
            # a module nobody asked for.
            raise ValueError(
                f"{root.name} builds itself with Python (packs/{root.name}/"
                f"build.py), which this build of Kriko cannot import "
                f"({exc}). Build it from a source checkout with "
                f"`python -m app.cli build {root}`, then install the .kpack "
                f"here."
            ) from exc
        result = module.build(out)
        if isinstance(result, tuple):
            out, report = result
            if isinstance(report, dict):
                stats = report.get("stats", report)
        else:
            out = result
    else:
        generic_build(root, out)

    progress.check()
    out = Path(out)
    digest = digest_of(out)
    progress.set(0.6, f"built {out.name} ({digest[:12]})")

    counts = {}
    artifact = connect(out)
    try:
        for table in ("subjects", "claims", "evidence"):
            counts[table] = artifact.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
    finally:
        artifact.close()
    progress.log(", ".join(f"{value} {name}" for name, value in counts.items()))
    for key, value in sorted((stats or {}).items()):
        progress.log(f"{key}: {value}")

    if not counts["subjects"] and not counts["claims"]:
        raise ValueError(
            f"{out} has no subjects and no claims — it cannot answer anything, "
            "so it was not installed"
        )

    installed = None
    if params.get("install", True):
        progress.check()
        progress.set(0.8, "installing")
        store = connect(settings.store_path)
        try:
            installed = packstore.install(store, out)
            store.commit()
        finally:
            store.close()
        progress.log(f"installed revision {installed}")

    progress.set(1.0, f"{root.name} built" + (" and installed" if installed else ""))
    return {
        "root": str(root),
        "artifact": str(out),
        "digest": digest,
        "counts": counts,
        "stats": stats or {},
        "installed": installed,
    }


def _installed_rows(conn):
    return conn.execute(
        "SELECT pack_id, name, version, content_digest, origin_url FROM packs"
        " ORDER BY pack_id"
    ).fetchall()


def check_updates(settings, index_url: str = "") -> dict:
    """Compare what is installed against what the index offers.

    Synchronous and cheap — one small JSON fetch — so it is a request rather
    than a job. Network failure is reported as a value, not raised: "we could
    not reach the index" is a legitimate answer to "is anything newer", and a
    500 would make the Packs screen look broken when only the network is.
    """
    url = index_url or settings.pack_index_url
    conn = connect(settings.store_path)
    try:
        rows = _installed_rows(conn)
    finally:
        conn.close()

    try:
        candidates = packsource.fetch_index(url)
    except Exception as exc:  # noqa: BLE001 — unreachable is an answer, not a crash
        return {
            "index_url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "checked_at": _now(),
            "packs": [
                {
                    "pack_id": row["pack_id"],
                    "name": row["name"],
                    "installed_version": row["version"],
                    "state": updates.UNKNOWN,
                    "reason": "the pack index could not be reached",
                }
                for row in rows
            ],
        }

    decisions = updates.plan(rows, candidates)
    known = {row["pack_id"] for row in rows}
    names = {row["pack_id"]: row["name"] for row in rows}
    payload = [
        {
            "pack_id": d.pack_id,
            "name": names.get(d.pack_id, d.pack_id),
            "installed_version": d.installed_version,
            "offered_version": d.offered_version,
            "state": d.state,
            "reason": d.reason,
            "url": d.candidate.url if d.candidate else "",
            "size": d.candidate.size if d.candidate else 0,
            "published_at": d.candidate.published_at if d.candidate else "",
        }
        for d in decisions
    ]
    # Packs the index offers that are not installed yet. Shown because an empty
    # store is the normal state of a fresh install: the first "update" a reader
    # wants is the one that gives them any knowledge at all.
    payload += [
        {
            "pack_id": c.pack_id,
            "name": c.name or c.pack_id,
            "installed_version": "",
            "offered_version": c.version,
            "state": "not_installed",
            "reason": "available, not installed",
            "url": c.url,
            "size": c.size,
            "published_at": c.published_at,
        }
        for c in candidates
        if c.pack_id not in known
    ]
    return {"index_url": url, "error": None, "checked_at": _now(), "packs": payload}


def pack_update(settings, params: dict, progress: Progress) -> dict:
    """Download and install every pack the index has something newer for.

    Goes through `packstore.install` like every other door: an updated pack is
    not a special kind of pack, and a second install path is a second place for
    the immutability rule to be forgotten.
    """
    only = params.get("pack_id") or ""
    index_url = params.get("index_url") or settings.pack_index_url
    progress.set(0.05, f"reading {index_url}")
    candidates = packsource.fetch_index(index_url)
    progress.log(f"index offers {len(candidates)} pack(s)")

    conn = connect(settings.store_path)
    try:
        rows = _installed_rows(conn)
    finally:
        conn.close()

    known = {row["pack_id"] for row in rows}
    wanted = [d for d in updates.plan(rows, candidates) if d.actionable]
    wanted += [
        updates.Decision(c.pack_id, updates.AVAILABLE, "not installed",
                         "", c.version, c)
        for c in candidates
        if c.pack_id not in known
    ]
    if only:
        wanted = [d for d in wanted if d.pack_id == only]
        if not wanted:
            raise ValueError(
                f"the index offers nothing newer for {only!r}"
                if only in known
                else f"the index does not carry a pack called {only!r}"
            )
    if not wanted:
        progress.set(1.0, "everything is up to date")
        return {"index_url": index_url, "updated": [], "skipped": len(rows)}

    into = Path(settings.store_path).parent / "downloads"
    updated = []
    for position, decision in enumerate(wanted, start=1):
        progress.check()
        share = (position - 1) / len(wanted)
        candidate = decision.candidate
        assert candidate is not None
        progress.set(0.1 + 0.8 * share, f"downloading {candidate.pack_id} {candidate.version}")
        path = packsource.download(
            candidate,
            into,
            lambda read, total, share=share, candidate=candidate: progress.set(
                0.1 + 0.8 * (share + (read / total if total else 0) / len(wanted)),
                f"downloading {candidate.pack_id} {read // 1024} KiB",
            ),
        )
        progress.check()
        progress.log(f"installing {path.name}")
        store = connect(settings.store_path)
        try:
            pack_id = packstore.install(store, path)
            store.commit()
        finally:
            store.close()
        # The file is the transport, not the record: the store holds the
        # revision, so keeping downloads around would only grow ~/.kriko.
        path.unlink(missing_ok=True)
        updated.append(
            {
                "pack_id": pack_id,
                "version": candidate.version,
                "from": decision.installed_version,
            }
        )
        progress.log(f"{pack_id} is now {candidate.version}")

    progress.set(1.0, f"updated {len(updated)} pack(s)")
    return {"index_url": index_url, "updated": updated, "skipped": len(rows) - len(updated)}


def pack_author(settings, params: dict, progress: Progress) -> dict:
    """Author a whole pack from a category named in plain words. (D4)

    The reader has asked for this three times, most recently as "package
    bulding still expects user raw input to create which i said many times,
    its gotta be automated with agents man". They were describing
    `POST /api/packs/scaffold`, which asked for a directory, a pack id, a name
    and an identity table before it would write anything — and the identity
    table is a decision nobody can make about a category they have not read.

    So this is one field and one press. Everything that makes it safe is
    already built: the spawn is the research plane's (`app/providers/
    harness.py` — same allowlist, neutral working directory, no
    `--mcp-config`), and every file is written through `app/packdraft.py`,
    which confines the directory, fixes the set of names, refuses anything
    executable and caps the sizes. The agent proposes data; Kriko writes it;
    the reader installs it. Three steps, three different authorities.

    Nothing is installed here. `POST /api/packs/drafts/{slug}/install` is the
    reader's press, on a screen that lists what the agent wrote.
    """
    from app import packauthor
    from app.providers import harness, harness_researcher

    category = str(params.get("category") or "").strip()
    if not category:
        raise ValueError(
            "name the category in a few words — 'cordless drills', 'espresso "
            "machines'. It is the only thing an agent cannot infer")

    if not harness.available():
        # Said in full rather than as "no harness": a reader whose opencode is
        # installed deserves to know why it is not being driven, and a reader
        # with neither deserves the other door rather than a dead end.
        blocked = "; ".join(one.unusable for one in harness.found_but_unusable())
        raise ValueError(
            "no coding-agent CLI on PATH, so Kriko cannot author a pack by "
            "itself. Install Claude Code, or hand the brief to your own agent "
            "through the MCP server (Agents → Connect) and let it use "
            "`draft_pack`."
            + (f" Found but not usable: {blocked}." if blocked else ""))

    researcher = harness_researcher(
        preferred=str(params.get("harness") or ""),
        app_state_path=settings.app_state_path,
        # Not the research ceiling. Authoring a pack is a category read from
        # scratch plus two or three subjects researched before the first line
        # is printed, and the real CLI runs past ten minutes doing it -- so
        # `TIMEOUT_SECONDS` would have killed a healthy run and reported a
        # hang. (B105)
        timeout=float(
            params.get("timeout_seconds") or harness.AUTHOR_TIMEOUT_SECONDS),
    )
    # The forty-minute silence this job used to be (B121). A pack author is
    # the longest-running thing in the app and the one whose log most needed
    # to say something before it finished.
    researcher.on_action = progress.log
    researcher.check_cancelled = progress.check
    # ── the cheap pass, before the expensive one ─────────────────────────
    #
    # "It never asks me anything." A pack built on the wrong variant is worse
    # than no pack, because it is confidently wrong — and the point of asking
    # *here* is that the expensive research has not happened yet. Nothing waits
    # on the answer: see `app/disambiguate.py` for why non-blocking is not a
    # compromise but the automation principle holding.
    scope = _disambiguate(settings, researcher, category, params, progress)

    progress.set(0.15, f"{researcher.search_provider} is reading up on {category}")
    progress.log(f"category: {category}")

    reply = researcher.ask(packauthor.brief(category, scope=scope))
    progress.check()
    progress.set(0.7, "writing the draft")
    # The reply is kept in the log whatever happens next: an agent that read
    # the category well and printed a malformed object has produced work worth
    # seeing, and a refusal that throws the text away is a refusal nobody can
    # act on.
    progress.log(reply.strip()[:4000] or "(the agent printed nothing)")

    try:
        written = packauthor.author(settings.store_path, reply, category=category)
    except packauthor.PackRefused as exc:
        raise ValueError(f"the agent did not produce a usable pack: {exc}") from exc

    for name in written["files"]:
        progress.log(f"wrote {name}")
    if written["notes"]:
        progress.log(f"the author noted: {written['notes']}")
    progress.set(
        1.0,
        f"drafted {written['pack_id']} — {written['subjects']} subject(s), "
        f"{written['claims']} claim(s). Nothing is installed yet: read it on "
        f"Knowledge and press Install."
    )
    written["category"] = category
    written["scope"] = scope
    if written.get("uncovered"):
        # Said in the job's own last line, because a partial pack the reader
        # knows about is a next step and one they do not is a wrong answer
        # waiting. B127's button acts on exactly this list.
        progress.log(
            f"{len(written['uncovered'])} product(s) named and not covered: "
            + ", ".join(written["uncovered"][:12])
            + ("…" if len(written["uncovered"]) > 12 else "")
            + " — press “Cover the gaps” on the draft to ask for them"
        )
    return written


def pack_amend(settings, params: dict, progress: Progress) -> dict:
    """Extend a draft that is nearly right, rather than authoring it again (B127).

    *"This pack seems very solid but it includes 19 products and lacks the
    20th. I don't want to rebuild the whole thing."* Re-authoring re-spends the
    whole run and can come back worse — the reader's second attempt returned
    nothing at all. This hands the agent what the draft already holds plus what
    it is missing, and merges the additions.

    Nothing existing is rewritten, and a refused amendment leaves the draft
    exactly as it was: the property that makes this safe to press on a pack you
    like.
    """
    from app import packauthor
    from app.providers import harness, harness_researcher

    slug = str(params.get("slug") or "").strip()
    if not slug:
        raise ValueError("which draft? `slug` is required")
    note = str(params.get("note") or "").strip()

    state_of = packauthor.draft_state(settings.store_path, slug)
    if not harness.available():
        raise ValueError(
            "no coding-agent CLI on PATH, so Kriko cannot extend this draft by "
            "itself. Hand the brief to your own agent through the MCP server "
            "(Agents → Connect) — `amend_draft` gives you the same brief."
        )

    researcher = harness_researcher(
        preferred=str(params.get("harness") or ""),
        app_state_path=settings.app_state_path,
        timeout=float(
            params.get("timeout_seconds") or harness.AUTHOR_TIMEOUT_SECONDS),
    )
    researcher.on_action = progress.log
    researcher.check_cancelled = progress.check
    progress.set(0.1, f"extending {state_of.get('name') or slug}")
    progress.log(
        f"{len(state_of.get('subjects') or [])} subject(s) already; "
        f"{len(state_of.get('uncovered') or [])} named and uncovered"
    )
    if note:
        progress.log(f"asked for: {note}")

    reply = researcher.ask(packauthor.amend_brief(state_of, note))
    progress.check()
    progress.set(0.7, "merging the additions")
    progress.log(reply.strip()[:4000] or "(the agent printed nothing)")
    try:
        result = packauthor.amend(settings.store_path, slug, reply)
    except packauthor.PackRefused as exc:
        raise ValueError(f"the draft is unchanged: {exc}") from exc

    for name in result["files"]:
        progress.log(f"wrote {name}")
    progress.set(
        1.0,
        f"added {result['subjects_added']} subject(s) and "
        f"{result['claims_added']} claim(s) to {result['pack_id'] or slug}"
        + (f"; {len(result['uncovered'])} still uncovered"
           if result["uncovered"] else "; the line-up is now covered")
    )
    return result


#: How many times a refused finding may be re-asked for. One.
#:
#: Not zero, because the commonest refusal is a field left empty on work that
#: was otherwise good — the reader watched three genuinely useful titles get
#: binned for it — and asking again costs one short call against text already
#: fetched.
#:
#: Not more than one, because a second refusal on the same field is not a
#: transient failure, it is the extractor telling us it has nothing more to say
#: about that document. Looping past that spends money to arrive at the same
#: answer more slowly, and an unbounded repair loop on a paid plane is a bill
#: nobody authorised.
REPAIR_ATTEMPTS = 1


def _repair(conn, subject_id, pack_id, verdicts, findings, *, researcher, task,
            emit, progress, retain):
    """Re-ask for the one field that would have kept a refused finding.

    Only the failing items, only the fields `findings._repairable` judged
    fixable, and only once. A finding whose *quote* could not be grounded is
    never re-asked for — that is asking it to try harder at the thing it got
    wrong, and the evidence model exists precisely so that cannot be
    negotiated.
    """
    from app.findings import explanation

    fixable = [one for one in verdicts.get("rejected", []) if one.get("fix")]
    if not fixable or not hasattr(researcher, "repair"):
        return verdicts

    wanted = {one["title"]: one for one in fixable}
    again = [dict(one) for one in findings if one.get("title") in wanted]
    if not again:
        return verdicts

    emit.open_stage("repair", f"re-asking for {len(again)} finding(s)")
    progress.log(
        f"{len(again)} finding(s) were refused for a field that can be "
        f"rewritten — asking once more"
    )
    try:
        mended = researcher.repair(task, again, wanted)
    except Exception as exc:  # noqa: BLE001 — a failed repair is not a failed run
        emit.close_stage(detail=f"could not re-ask: {exc}")
        return verdicts

    kept = [one for one in mended if explanation(one)]
    if not kept:
        emit.close_stage(detail="nothing came back with the field filled in")
        return verdicts

    second = accept_findings(conn, subject_id, pack_id, kept, retain=retain)
    emit.close_stage(
        detail=f"{len(second.get('accepted', []))} of {len(again)} kept on the "
               f"second attempt")

    # Merge: what the repair kept joins the accepted list, and the refusals it
    # replaced leave the rejected one. A finding that failed twice stays
    # refused, carrying the second verdict rather than the first — the reader
    # should see why it finally lost, not why it first did.
    mended_titles = {one["title"] for one in second.get("accepted", [])}
    from app.findings import summarise

    accepted = verdicts.get("accepted", []) + second.get("accepted", [])
    rejected = [one for one in verdicts.get("rejected", [])
                if one["title"] not in mended_titles
                and not any(one["title"] == two["title"]
                            for two in second.get("rejected", []))]
    rejected += second.get("rejected", [])
    return {**verdicts, "accepted": accepted, "rejected": rejected,
            "summary": summarise(accepted, rejected)}


def _disambiguate(settings, researcher, subject, params, progress) -> dict:
    """One short call: is this name one product or several?

    Returns the scope record — what was settled, and which parts of it were
    *assumed* rather than confirmed. Never raises and never waits: a
    disambiguation that failed must cost the reader a question, not the run
    behind it, so every failure path here returns the same empty scope the run
    had before this existed.
    """
    from app import disambiguate

    conn = connect(settings.store_path)
    try:
        keys = identity_keys_text(conn)
    finally:
        conn.close()

    progress.set(0.05, f"checking what “{subject}” actually means")
    try:
        found = disambiguate.parse(
            researcher.ask(disambiguate.brief(subject, keys)))
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 — a lost question, never a lost run
        progress.log(f"could not check the name for ambiguity ({exc}) — "
                     f"carrying on without asking")
        return {}

    if not found["ambiguous"]:
        progress.log(f"“{subject}” names one product — nothing to ask")
        return disambiguate.scope(found)

    # Written to the job row so a client can render them *while the run
    # continues*. The reader answering is a refinement, not a gate.
    progress.partial({"questions": found["questions"], "why": found["why"],
                      "stopped_at": "disambiguation"})
    progress.log(f"{found['why']}" if found["why"] else "this name is ambiguous")
    for question in found["questions"]:
        progress.log(f"  ? {question['ask']} — assuming {question['default']!r}"
                     + (f" ({question['because']})" if question["because"] else ""))

    scope = disambiguate.scope(found, params.get("answers") or {})
    said = disambiguate.sentence(scope)
    if said:
        progress.log(said)
    return scope


def site_register(settings, params: dict, progress: Progress) -> dict:
    """Teach this installation to read a website (B115, and the reader's own
    "I cannot open the extension on pages that aren't registered").

    An agent reads the page and writes the adapter; `app/sites.py` checks it
    and `app.sqlite` keeps it. Nothing reaches the store: a site this copy
    learned is not pack content, and a pack that later ships an adapter for the
    same host wins over it.
    """
    from app import sites
    from app.providers import harness, harness_researcher

    host = sites.host_of(params.get("host") or "")
    if not host:
        raise ValueError("which site? `host` is required")
    url = str(params.get("url") or f"https://{host}/")

    conn = connect(settings.store_path)
    try:
        keys = identity_keys_text(conn)
    finally:
        conn.close()

    if not harness.available():
        raise ValueError(
            "no coding-agent CLI on PATH, so Kriko cannot read the site by "
            "itself. Hand the brief to your own agent through the MCP server "
            "and post the adapter back, or write it yourself on the Sites "
            "screen."
        )
    researcher = harness_researcher(
        preferred=str(params.get("harness") or ""),
        app_state_path=settings.app_state_path,
        timeout=float(params.get("timeout_seconds") or harness.TIMEOUT_SECONDS),
    )
    researcher.on_action = progress.log
    researcher.check_cancelled = progress.check
    progress.set(0.1, f"reading {host}")
    progress.log(f"site: {host} — {url}")

    reply = researcher.ask(sites.BRIEF.format(site=host, url=url, keys=keys))
    progress.check()
    progress.set(0.7, "checking the adapter")
    progress.log(reply.strip()[:4000] or "(the agent printed nothing)")

    from app.packauthor import _payload  # the same fence reader every door uses

    spec = _payload(reply)
    app_conn = state.connect(settings.app_state_path)
    try:
        if not spec:
            state.set_site_request(
                app_conn, host, state="refused",
                detail="the agent printed no JSON object")
            raise ValueError(
                "the agent printed no adapter. Nothing was stored — the run's "
                "log holds what it did say"
            )
        try:
            checked = sites.check(spec, host=host)
        except sites.SiteRefused as exc:
            state.set_site_request(app_conn, host, state="refused", detail=str(exc))
            raise ValueError(f"the adapter was refused: {exc}") from exc
        state.save_local_adapter(
            app_conn, host=host, spec=checked, source="agent",
            pack_id=str(params.get("pack_id") or checked.get("pack_id") or ""),
        )
        state.set_site_request(app_conn, host, state="done",
                               detail=f"{len(checked.get('fields') or {})} field(s)")
    finally:
        app_conn.close()

    progress.set(
        1.0,
        f"{host} can be read now — {len(checked.get('fields') or {})} field(s). "
        f"Open a listing there and press the extension button."
    )
    return {"host": host, "adapter": checked, "url": url}


def identity_keys_text(conn) -> str:
    """The identity keys the installed packs declare, for a brief.

    Read off the store rather than named here, for the reason every list in
    this file is: the engine knows no category, and a key an agent invented
    would map a page into a lookup that resolves to nothing. `is_identity` is
    the pack's own mark — the same rows `identity_vocabulary` reads.
    """
    rows = conn.execute(
        "SELECT DISTINCT s.pack_id, s.kind, a.key FROM attributes a"
        " JOIN subjects s USING (subject_id, pack_id)"
        " JOIN packs p ON p.pack_id = s.pack_id"
        " WHERE a.is_identity = 1 AND p.enabled = 1"
        " ORDER BY s.pack_id, s.kind, a.key"
    ).fetchall()
    if not rows:
        return "(no packs are installed, so there are no keys to map into yet)"
    by_pack: dict[tuple, list[str]] = {}
    for row in rows:
        by_pack.setdefault((row["pack_id"], row["kind"]), []).append(row["key"])
    return "\n".join(
        f"* `{pack}` / `{kind}`: " + ", ".join(f"`{key}`" for key in sorted(set(keys)))
        for (pack, kind), keys in by_pack.items()
    )


def verify(settings, params: dict, progress: Progress) -> dict:
    """Re-read the sources behind claims that are already installed (B128).

    *"As well as the button: verify the knowledge here — again an agent
    operation."* Half of it existed: `app/factcheck.py` re-reads the page behind
    **one** claim on a reader's press. What did not exist is the *operation* —
    the whole screen at once, as a job, with a row in the feed and a result that
    outlives the request.

    No model and no agent: the question is "does the quote still appear on the
    page", which a substring test answers honestly and an LLM would answer
    confidently. That is also why it is free and why it can run over hundreds of
    claims without a budget.

    It reports and never retracts. A `missing` verdict is a signal beside the
    reader's own marks, not a deletion — pages get rewritten, and the engine has
    no authority to remove a pack's claim on the strength of a fetch.
    """
    from app import factcheck, findings

    conn = connect(settings.store_path)
    try:
        pack_id = str(params.get("pack_id") or "")
        subject_id = str(params.get("subject_id") or "")
        limit = max(1, min(int(params.get("limit") or 50), 500))
        sql = (
            "SELECT c.claim_id, c.pack_id, c.subject_id, t.title"
            " FROM claims c LEFT JOIN claim_text t"
            "   ON t.claim_id = c.claim_id AND t.pack_id = c.pack_id"
            " WHERE 1 = 1"
        )
        args: list = []
        if pack_id:
            sql += " AND c.pack_id = ?"
            args.append(pack_id)
        if subject_id:
            sql += " AND c.subject_id = ?"
            args.append(subject_id)
        sql += " ORDER BY c.claim_id LIMIT ?"
        args.append(limit)
        rows = conn.execute(sql, args).fetchall()
        if not rows:
            raise ValueError(
                "no installed claims match that. Verify runs over what is in "
                "the store, not over a draft"
            )

        app_conn = state.connect(settings.app_state_path)
        verdicts: dict[str, int] = {}
        grounding: dict[str, int] = {}
        checked = []
        try:
            for index, row in enumerate(rows, start=1):
                progress.check()
                progress.set(index / max(1, len(rows)), f"re-reading {index}/{len(rows)}")
                sources = [
                    dict(one)
                    for one in conn.execute(
                        "SELECT s.url, e.quote FROM evidence e"
                        # `USING (source_id, pack_id)`, like the single-claim
                        # router: a source id is unique within a pack and two
                        # packs may carry the same page.
                        " JOIN sources s USING (source_id, pack_id)"
                        " WHERE e.claim_id = ? AND e.pack_id = ?"
                        " ORDER BY CASE e.stance WHEN 'supports' THEN 0 ELSE 1 END",
                        (row["claim_id"], row["pack_id"]),
                    ).fetchall()
                ]
                answer = factcheck.check_claim(sources)
                verdicts[answer["verdict"]] = verdicts.get(answer["verdict"], 0) + 1
                state.record_fact_check(
                    app_conn,
                    pack_id=row["pack_id"],
                    claim_id=row["claim_id"],
                    verdict=answer["verdict"],
                    detail=answer.get("detail", ""),
                    sources=answer.get("sources", []),
                    subject_id=row["subject_id"] or "",
                    title=row["title"] or "",
                )
                per_evidence = findings.regrounded(
                    conn, settings.app_state_path, row["pack_id"], row["claim_id"]
                )
                for one in per_evidence:
                    grounding[one["verdict"]] = grounding.get(one["verdict"], 0) + 1
                checked.append(
                    {"claim_id": row["claim_id"], "title": row["title"] or "",
                     "verdict": answer["verdict"], "grounding": per_evidence}
                )
                if answer["verdict"] != factcheck.QUOTED:
                    progress.log(
                        f"{answer['verdict']}: “{row['title'] or row['claim_id']}”"
                    )
                if any(one["verdict"] == "ungrounded" for one in per_evidence):
                    progress.log(
                        "ungrounded: the page this install kept for "
                        f"“{row['title'] or row['claim_id']}” no longer "
                        "carries the quote"
                    )
        finally:
            app_conn.close()
    finally:
        conn.close()

    progress.set(
        1.0,
        ", ".join(f"{count} {name}" for name, count in sorted(verdicts.items()))
        or "nothing to check",
    )
    return {
        "checked": len(checked),
        "verdicts": verdicts,
        "grounding": grounding,
        "claims": checked,
    }


def bench(settings, params: dict, progress: Progress) -> dict:
    """Run the fixed cases across the planes, and measure (B111).

    A job rather than a request for the ordinary reason — three cases on two
    planes is minutes of work — and for one more: it spends money on the paid
    plane, so it has to be cancellable and its budget has to be visible in the
    row that started it.

    The planes are asked for explicitly or discovered. The `agent` plane is
    never included: its `gather` returns nothing by design, so benchmarking it
    would measure the brief writer and report zero of everything.
    """
    from app import bench as bench_mod

    conn = connect(settings.store_path)
    try:
        chosen = [
            one.strip()
            for one in str(params.get("planes") or "").split(",")
            if one.strip()
        ] or bench_mod.planes_available(settings)
        if not chosen:
            raise ValueError(
                "no plane can run here: install a coding-agent CLI for the "
                "harness plane, or add the API keys for the paid one"
            )
        limit = int(params.get("cases") or bench_mod.DEFAULT_CASES)
        pack_id = str(params.get("pack_id") or "")
        # Ground truth where a pack ships it (B126), derived cases otherwise.
        # A gold case measures correctness — what a competent run should have
        # found and what it must not claim — and a derived one measures
        # discipline. Preferring the first whenever it exists is the whole
        # point of having authored it.
        found = bench_mod.gold_cases(conn, pack_id=pack_id, limit=limit)
        graded = bool(found)
        if not found:
            found = bench_mod.cases(conn, pack_id=pack_id, limit=limit)
        if not found:
            raise ValueError("no subjects installed, so there is nothing to measure")
    finally:
        conn.close()

    # Which protocols to sweep. Empty string means "whatever the plane would
    # choose for itself", which is the honest default: a benchmark that always
    # swept every protocol would multiply a reader's bill by three to answer a
    # question they did not ask. Naming them is how B123's table gets filled.
    protocols_asked = [
        one.strip() for one in str(params.get("protocols") or "").split(",") if one.strip()
    ] or [""]

    # How many times each measurement is repeated. Language models are
    # stochastic, so one run of a case is a sample reported as a constant —
    # and two protocols cannot be compared from one observation each.
    reps = max(1, min(int(params.get("reps") or 1), 10))

    # Which search provider answered. Swept only when the reader names more
    # than one, for the same reason the protocols are: measuring an axis
    # nobody asked about multiplies the bill to answer a question nobody
    # asked. Empty string means whichever one this installation would pick.
    searches_asked = [
        one.strip()
        for one in str(params.get("searches") or params.get("search") or "").split(",")
        if one.strip()
    ] or [""]

    batch_id = secrets.token_hex(8)
    app_conn = state.connect(settings.app_state_path)
    rows = []
    try:
        total = (
            len(found) * len(chosen) * len(protocols_asked)
            * len(searches_asked) * reps
        )
        done = 0
        for case in found:
            for plane in chosen:
                for protocol, search, rep in [
                    (one, engine, index)
                    for one in protocols_asked
                    for engine in searches_asked
                    for index in range(1, reps + 1)
                ]:
                    progress.check()
                    progress.set(
                        done / max(1, total),
                        f"{plane}: {case.get('label') or case['subject_id']}",
                    )
                    row = bench_mod.run_case(
                        settings,
                        case,
                        plane=plane,
                        protocol=protocol,
                        max_documents=int(params.get("max_documents") or 3),
                        budget_usd=float(
                            params.get("budget_usd") or bench_mod.DEFAULT_BUDGET_USD
                        ),
                        batch_id=batch_id,
                        search=search,
                    )
                    row["rep"] = rep
                    state.record_bench(app_conn, row)
                    rows.append(row)
                    done += 1
                    # One line per measurement, so the reader watching the job
                    # sees the comparison build rather than a number at the end.
                    progress.log(
                        f"{plane}{' · ' + protocol if protocol else ''}"
                        f"{' · ' + search if search else ''} · "
                        f"{row['subject']}: "
                        + (
                            f"failed — {row['error']}"
                            if row.get("error")
                            else f"{row.get('accepted', 0)} kept, "
                            f"{row.get('refused', 0)} refused, "
                            f"{row.get('documents', 0)} source(s), "
                            f"{(row.get('ms') or 0) / 1000:.1f}s"
                            + (f", {row['tokens']} tokens" if row.get("tokens") else "")
                        )
                    )
        summary = state.bench_summary(app_conn)
        scored = bench_mod.scored(rows)
    finally:
        app_conn.close()

    progress.set(1.0, f"{len(rows)} measurement(s) across {len(chosen)} plane(s)")
    return {
        "batch_id": batch_id,
        "cases": [case["subject_id"] for case in found],
        "planes": chosen,
        "protocols": protocols_asked,
        "rows": rows,
        "summary": summary,
        "graded": graded,
        # Recall, precision and hallucination with their intervals, when the
        # cases carried ground truth. Absent rather than zeroed when they did
        # not: "nothing was graded" and "it scored zero" are opposite facts.
        "scored": scored,
        "reps": reps,
    }


HANDLERS = {
    "research": research,
    "bench": bench,
    "agenda_run": agenda_run,
    "research_undo": research_undo,
    "pack_build": pack_build,
    "pack_author": pack_author,
    "pack_amend": pack_amend,
    "verify": verify,
    "site_register": site_register,
    "pack_update": pack_update,
}
