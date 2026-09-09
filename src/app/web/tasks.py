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


def _researcher(params: dict):
    """The plane this run asked for, wired to whatever it needs.

    The `agent` plane needs nothing, which is why it is the default and why it
    is the one that works on a machine with no keys. The `api` plane needs
    three callables, and `app/providers/` is where the sockets live — the
    engine owns none, so `kriko.research` could never have built this itself.
    """
    backend = str(params.get("backend") or "agent").lower()
    if backend != "api":
        return get_researcher({"backend": backend})
    from app.providers import api_researcher

    price = float(params.get("price_per_call") or DEFAULT_PRICE_PER_CALL)
    return api_researcher(price_per_call=price)


def _budget(params: dict) -> float:
    """The ceiling, with the paid plane's floor applied.

    A caller may raise it or lower it; a caller may not leave the paid plane
    uncapped by omission.
    """
    named = float(params.get("budget_usd") or 0.0)
    if str(params.get("backend") or "agent").lower() != "api":
        return named
    return named if named > 0 else DEFAULT_BUDGET_USD


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
            state.close_research_run(conn, self.run_id, outcome, self.spent())
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

        researcher = _researcher(params)
        if provenance is not None:
            provenance.open(researcher)
        brief = researcher.brief(task)
        progress.set(0.2, f"{researcher.name} plane ({researcher.cost_basis})")
        emit.describe(plane=researcher.name)
        emit.event(f"{researcher.name} plane, cost {researcher.cost_basis}")
        progress.check()

        documents = researcher.gather(task)
        progress.log(f"gathered {len(documents)} document(s)")
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
            emit.skip_stage(
                "extraction",
                f"the {researcher.name} plane fetches nothing itself — the brief is the output",
            )
        else:
            emit.open_stage("extraction", f"reading {len(documents)} source(s)")
        for index, document in enumerate(documents, start=1):
            progress.check()
            progress.set(
                0.2 + 0.6 * index / max(1, len(documents)),
                f"reading {document.site_or_channel or document.url}",
            )
            emit.count(chars=len(document.text or ""))
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
        verdicts = {"accepted": [], "rejected": []}
        if findings:
            emit.open_stage("ingestion", f"checking {len(findings)} finding(s)")
            progress.set(0.85, f"checking {len(findings)} finding(s)")
            verdicts = accept_findings(conn, subject_id, pack_id, findings)
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

        progress.set(1.0, f"{len(verdicts.get('accepted', []))} claim(s) kept")
        # Not closed here: `research` closes the row on every path out,
        # which is the only way the failing paths get one too.
        spent = provenance.spent() if provenance is not None else None
        return {
            "run_id": emit.run_id,
            "spent_usd": spent,
            "budget_usd": task.budget_usd or None,
            "subject": task.subject_label,
            "pack_id": pack_id,
            **_describe_plane(researcher),
            "cost_basis": researcher.cost_basis,
            "queries": list(task.rendered_queries()),
            "brief": brief,
            "documents": len(documents),
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
    backend = str(params.get("backend") or "agent").lower()
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
        done.append(
            {
                "subject_id": row["subject_id"],
                "subject": result.get("subject") or "",
                "run_id": result.get("run_id") or "",
                "kept": len(result.get("accepted") or []),
                "refused": len(result.get("rejected") or []),
                "spent_usd": result.get("spent_usd"),
            }
        )

    kept = sum(item.get("kept") or 0 for item in done)
    progress.set(1.0, f"{kept} claim(s) kept across {len(done)} subject(s)")
    return {
        "rows": done,
        "subjects": len(subjects),
        "needs_a_subject": needs_a_subject,
        "kept": kept,
        "plane": backend,
        "budget_usd": ceiling or None,
        "spent_usd": spent_total if backend == "api" else None,
        "stopped": stopped,
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
        progress.set(0.1 + 0.8 * share, f"downloading {candidate.pack_id} {candidate.version}")
        path = packsource.download(
            candidate,
            into,
            lambda read, total: progress.set(
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


HANDLERS = {
    "research": research,
    "agenda_run": agenda_run,
    "research_undo": research_undo,
    "pack_build": pack_build,
    "pack_update": pack_update,
}
