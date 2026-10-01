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
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app import packautoupdate, packsource

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


#: The first half of every "no agent" refusal. The API agent is named because
#: it is the door a reader without a CLI has, and it runs only once picked.
NO_AGENT = ("No agent to run: no coding-agent CLI on PATH, and the Mistral API "
            "agent is not picked (Settings → Agents; it needs a Mistral key in "
            "Settings → Research), so")


def default_backend(app_state_path=None) -> str:
    """The plane a run gets when the caller names none.

    It used to be `agent` unconditionally, and `agent` fetches nothing by
    design — it writes a brief for somebody else to read. On a machine with a
    coding-agent CLI installed that made pressing **Research** produce a brief
    and a `succeeded / 0 claim(s) kept`, which is the second time the reader
    reported the same experience: "run nothing again".

    So: the best plane that can actually gather. `harness` when a CLI is on
    PATH or the reader picked an API agent that has its key (B153), `agent`
    otherwise. An API agent bills per token, so it runs only when picked and
    always under a ceiling (`_budget`). `api` is still never chosen by
    omission — a tool that starts spending money because a key happened to be
    in the environment is a tool people stop trusting, and that reasoning was
    always about the paid plane rather than about defaulting to a no-op.

    **The local machine plane goes first** (B172) when it is ready and the
    reader has not picked an agent of their own: a model on this machine costs
    nothing and asks for no account. A reader who picked an agent in Settings
    made a choice and keeps it; one whose local server is down or has no model
    falls through to the next plane, and `default_plane` says why.
    """
    return default_plane(app_state_path)[0]


def default_plane(app_state_path=None) -> tuple[str, str]:
    """`(plane, why)`: what an unnamed run gets, and the reason in words.

    The reason is what the run's log prints, so a reader who expected one plane
    and got another can see which fact decided it.
    """
    from app import localplane

    local = {"ready": False, "reason": ""}
    try:
        local = localplane.resolve(app_state_path, with_search=False)
    except Exception:  # noqa: BLE001 - a probe must never fail a run
        pass
    chose = localplane.reader_chose_an_agent(app_state_path)
    if local["ready"] and not chose:
        return "local", (
            f"the local plane is first when it is ready: {local['model']} on "
            f"{local['name']} at {local['url']}")
    skipped = ""
    if local["ready"]:
        skipped = "an agent is picked in Settings, which goes before the local plane"
    elif local["reason"]:
        skipped = f"the local plane is not ready ({local['reason']})"
    try:
        from app.providers import agent_ready

        if agent_ready(app_state_path):
            return "harness", (f"{skipped}; using the harness plane" if skipped
                               else "a coding agent is available")
    except Exception:  # noqa: BLE001 - a missing CLI must never fail a run
        pass
    return "agent", (f"{skipped}; no coding agent either, so the agent plane "
                     "(a brief, nothing fetched)" if skipped
                     else "no coding agent is available")


class LocalNotReady(RuntimeError):
    """The local plane was asked for and cannot run; the text says why and
    what to do. A failed job with that text, never a run of "0 claims"."""


def _local_plan(params: dict) -> dict:
    """What a local run uses, resolved off the running server (B171).

    The run's own `model` counts only when the server lists it: the Run screen
    carries the paid plane's model name, and a name from another provider's
    namespace would be a 404 from a server that has perfectly good models.
    """
    from app import localplane

    plan = localplane.resolve(
        params.get("app_state_path"),
        url=str(params.get("llm_base_url") or ""),
        search_url=str(params.get("search_base_url") or ""),
    )
    if not plan["ready"]:
        raise LocalNotReady(plan["reason"])
    asked = str(params.get("model") or "").strip()
    if asked in plan["models"]:
        plan["model"] = asked
    if float(params.get("timeout_seconds") or 0) > 0:
        plan["timeout"] = float(params["timeout_seconds"])
    return plan


def _use_local_ask(settings, params: dict) -> bool:
    """Whether a job that `ask`s runs on the local model rather than a CLI.

    When the run names the local plane (the extension door does, for a reader
    who has no agent of their own), or when no agent could run it and the
    local model can. An agent that is there keeps the job: local is first only
    where the door decides so (B172), never by overriding a CLI here.
    """
    if str(params.get("backend") or "").lower() == "local":
        return True
    from app import localplane
    from app.providers import agent_ready

    path = getattr(settings, "app_state_path", None)
    if agent_ready(path, str(params.get("harness") or "")):
        return False
    return localplane.is_ready(path)


def _local_asker(settings, params: dict, progress: Progress):
    """The local model as the job's researcher, wired like a harness one."""
    from app.providers import local_asker

    plan = _local_plan({**params, "app_state_path": settings.app_state_path})
    researcher = local_asker(
        base_url=plan["url"], serving_name=plan["model"],
        search_base_url=plan["search_url"], search_kind=plan["search_kind"],
        timeout=plan["timeout"],
        given_queries=[str(one).strip() for one in (params.get("queries") or [])
                       if str(one).strip()])
    progress.log(f"local plane: {plan['line']}")
    researcher.on_action = progress.log
    researcher.check_cancelled = progress.check
    researcher.replies = progress.replies
    return researcher


def _researcher(params: dict):
    """The plane this run asked for, wired to whatever it needs.

    The `agent` plane needs nothing, which is why it is the default and why it
    is the one that works on a machine with no keys. The `api` plane needs
    three callables, and `app/providers/` is where the sockets live — the
    engine owns none, so `kriko.research` could never have built this itself.
    """
    backend = str(params.get("backend") or default_backend(params.get("app_state_path"))).lower()
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
            # And "which model" rides the same params: a per-run choice wins,
            # a stored per-harness choice applies, otherwise the CLI default.
            model=str(params.get("model") or ""),
        )
    if backend == "local":
        # Sockets and pacing are interface decisions, which is why this
        # branch lives here rather than being a `get_researcher` backend:
        # the engine owns no sockets and no politeness policy. The scheduler
        # sources mirror the SERP adapter's engine names, so rotation maps
        # one-to-one onto what a challenge page rotated away from.
        from app.providers import local_researcher
        from kriko.research.politeness import PolitenessScheduler

        plan = _local_plan(params)
        if plan["search_kind"] == "exa":
            # One hosted source, and a pace kinder than the free endpoint's
            # own limits need.
            sources = {"exa": float(params.get("min_interval") or 1.0)}
        else:
            engines = str(params.get("engines") or "duckduckgo,bing,ecosia")
            sources = {
                engine.strip(): float(params.get("min_interval") or 3.5)
                for engine in engines.split(",") if engine.strip()
            }
        return local_researcher(
            base_url=plan["url"],
            serving_name=plan["model"],
            search_base_url=plan["search_url"],
            search_kind=plan["search_kind"],
            timeout=plan["timeout"],
            engine=sources and next(iter(sources)) or "",
            scheduler=PolitenessScheduler(sources or {"duckduckgo": 3.5}),
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


def _bills_per_token(params: dict, app_state_path=None) -> bool:
    """Whether this run's plane charges the reader per token.

    The paid plane always does. The harness plane does when the agent it
    resolves to is an API agent (`app/providers/apiagent.py`), and then it
    gets the paid plane's floor, because the bill is just as real.
    """
    path = app_state_path or params.get("app_state_path")
    backend = str(params.get("backend") or default_backend(path)).lower()
    if backend == "api":
        return True
    if backend != "harness":
        return False
    try:
        from app.providers import bills_per_token

        return bills_per_token(path, str(params.get("harness") or ""))
    except Exception:  # noqa: BLE001 — a resolution error is the run's to report
        return False


def _source_ceiling(params: dict) -> str:
    """The Run screen's sources slider, as a sentence at the end of the brief.

    A coding-agent CLI has no flag for "read at most N pages", so the ceiling
    is asked for in the prompt. Empty when the reader set none (B175).
    """
    wanted = int(params.get("max_documents") or 0)
    if wanted <= 0:
        return ""
    return (
        f"\n\nRead at most {wanted} source{'s' if wanted != 1 else ''} in total "
        f"for this task, then write what they support."
    )


def _cap_agent(researcher, params: dict) -> None:
    """Give a per-token agent the ceiling its caller named.

    For the jobs that `ask` rather than `gather` (a quick look, a draft): no
    `ResearchTask` carries a budget to them. A CLI is left alone, since a
    ceiling on a subscription would reach its budget flag and cap nothing
    the reader pays for.
    """
    named = float(params.get("budget_usd") or 0.0)
    if named > 0 and getattr(researcher, "cost_basis", "") == "per_token":
        researcher.budget_usd = named


def _budget(params: dict, app_state_path=None) -> float:
    """The ceiling, with the paid plane's floor applied.

    A caller may raise it or lower it; a caller may not leave the paid plane
    uncapped by omission.

    A *named* scale brings its own ceiling (`app/scale.py`), because a Deep run
    stopped at a Quick run's ceiling is a reader refused the depth they chose,
    and a Quick run allowed a Deep run's ceiling is a cap doing nothing.

    A run that names no scale keeps `DEFAULT_BUDGET_USD` exactly as before, and
    that condition is load-bearing rather than tidiness: letting the default
    preset's ceiling apply to every unscaled run would have raised the standing
    per-subject budget five-fold for every caller that never asked for a dial —
    the agenda among them. A choice nobody made must not cost anybody money.
    """
    named = float(params.get("budget_usd") or 0.0)
    if not _bills_per_token(params, app_state_path):
        return named
    if named > 0:
        return named
    wanted = str(params.get("scale") or "").strip()
    if wanted:
        from app import scale

        return scale.applied(wanted, params)["cap_usd"] or DEFAULT_BUDGET_USD
    return DEFAULT_BUDGET_USD


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
    "local": (
        "the local model read nothing usable. The lines above say whether the "
        "search, a page, or the model itself failed; Settings, Local machine "
        "shows which server and model are in use."
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
        self._budget = _budget(params, self._path)
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
        progress.partial(result)
        progress.check()
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
        # One dial, resolved once. An explicit `max_documents` still wins —
        # the presets are bundles of these knobs, never a wall around them.
        from app import scale as scaling

        depth = scaling.applied(str(params.get("scale") or ""), params)
        # Live, per stage and per model, while the run spends — rather than
        # one number on the way out, which arrives too late to act on and
        # cannot say where the money went.
        from app.meter import Meter
        from app.web.settings import KRIKO_HOME

        ceiling = _budget(params, getattr(settings, "app_state_path", None))
        meter = Meter(home=KRIKO_HOME, cap_usd=ceiling)
        task = plan_task(
            conn,
            subject_id,
            pack_id,
            budget_usd=ceiling,
            max_documents=depth["max_documents"],
        )
        progress.set(0.1, f"planning {task.subject_label}")
        # Recorded on the run, so a thin pack reads as "this was a Quick run"
        # rather than as a quality failure — which is the difference between a
        # reader adjusting the dial and a reader losing confidence in the tool.
        emit.describe(scale=depth["scale"], sources_allowed=depth["max_documents"])
        progress.log(
            f"{depth['scale']} — up to {depth['max_documents']} source(s)"
            + (f", capped at ${depth['cap_usd']:.2f}" if depth["cap_usd"] else "")
        )
        emit.describe(pack_id=pack_id, subject=task.subject_label)
        for query in task.rendered_queries():
            progress.log(f"query: {query}")
            emit.event(f"query: {query}", detail_kind="query")

        # The interface's own database, so the plane can read what this
        # installation has measured about the model it is about to use.
        researcher = _researcher({**params, "app_state_path": settings.app_state_path})
        # Which plane and why (B172): a reader who expected one plane and got
        # another should be able to read the fact that decided it.
        why = ("named for this run" if params.get("backend")
               else default_plane(settings.app_state_path)[1])
        progress.log(f"plane: {researcher.name}. {why[:1].upper()}{why[1:]}.")
        # What the plane does while it does it (B121). Duck-typed, like
        # `tokens_used` below: a plane that can narrate gets somewhere to
        # narrate to, and one that cannot is unaffected. The job log is the
        # channel because it already streams to the app and to `kriko tui` —
        # the actions needed a sender, not a second transport.
        if hasattr(researcher, "on_action"):
            researcher.on_action = progress.log
        if hasattr(researcher, "check_cancelled"):
            researcher.check_cancelled = progress.check
        # The return path — see the same pair in the handlers below. Guarded
        # like its neighbours because not every researcher is a harness, and a
        # plane that cannot be spoken to simply is not given a way to listen.
        if hasattr(researcher, "replies"):
            researcher.replies = progress.replies
        if provenance is not None:
            provenance.open(researcher)
        brief = researcher.brief(task)
        progress.set(0.2, f"{researcher.name} plane ({researcher.cost_basis})")
        emit.describe(plane=researcher.name)
        emit.event(f"{researcher.name} plane, cost {researcher.cost_basis}")
        progress.check()

        progress.partial({
            "subject_id": subject_id, "pack_id": pack_id,
            "brief": brief, "stopped_at": "discovery",
        })
        try:
            documents = researcher.gather(task)
        except Cancelled:
            gathered = getattr(researcher, "_documents", [])
            progress.partial({
                "subject_id": subject_id, "pack_id": pack_id,
                "brief": brief, "stopped_at": "discovery",
                "documents": len(gathered),
                "retained_documents": [asdict(one) for one in gathered],
            })
            raise
        progress.partial({
            "subject_id": subject_id, "pack_id": pack_id,
            "brief": brief, "stopped_at": "discovery",
            "documents": len(documents),
            "retained_documents": [asdict(one) for one in documents],
        })
        progress.check()
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
            # Both meters, per document: the partial is what survives a
            # cancel, the tally is what the screen shows while it runs.
            complete = getattr(researcher, "_complete", None)
            if complete is not None:
                meter.observe("extract", complete)
                said = meter.crossed()
                if said:
                    progress.log(said)
                    emit.event(said, level="warn")
                if meter.over_cap():
                    # Cleanly, keeping everything gathered so far. A cap that
                    # truncates silently or crashes teaches the reader the
                    # number does nothing.
                    progress.log(
                        f"stopping at this run's ${meter.cap_usd:.2f} cap — "
                        f"{len(documents) - index} source(s) not read")
                    emit.close_stage(detail="stopped at the cost cap")
                    break
            # Per document, because a run stopped halfway through ten sources
            # has read the first five and that is worth keeping.
            progress.partial({
                "subject_id": subject_id, "pack_id": pack_id,
                "documents": len(documents), "findings": len(findings),
                "retained_documents": [asdict(one) for one in documents],
                "pending_findings": findings, "brief": brief,
                "stopped_at": "extraction",
                "spend": meter.snapshot(),
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
            progress.partial({
                "subject_id": subject_id, "pack_id": pack_id,
                "documents": len(documents), "findings": len(findings),
                "retained_documents": [asdict(one) for one in documents],
                "pending_findings": findings, "brief": brief,
                "stopped_at": "extraction", "spend": meter.snapshot(),
            })
            progress.check()
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
            "retained_documents": [asdict(one) for one in documents],
            "pending_findings": findings, "brief": brief,
            "stopped_at": "extraction",
            "spend": meter.snapshot(),
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
                "verdicts": verdicts, "brief": brief,
                "retained_documents": [asdict(one) for one in documents],
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


def _uncounted(progress: Progress, row: dict, ceiling: float) -> float:
    """What a billed row whose cost nobody counted is taken to have spent.

    Its whole ceiling. Adding nothing would let the shared ceiling never trip,
    and an unattended run would keep billing a model with no price row after
    row; counting the most it could have spent ends the walk early instead.
    """
    progress.log(f"{row['subject_id']}: cost unknown — counted at its ${ceiling:.2f} ceiling")
    return ceiling


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
    backend = str(params.get("backend") or default_backend(settings.app_state_path)).lower()
    ceiling = float(params.get("budget_usd") or 0.0)
    # An API agent on the harness plane bills like the paid plane, so an
    # unattended run of it gets the same shared ceiling rather than one
    # default per row with no total.
    billed = _bills_per_token(params, settings.app_state_path)
    if ceiling <= 0 and billed:
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
            if billed:
                # It may have been billed before it failed, and nothing here
                # can say how much — so it is counted at the most it could have.
                spent_total += _uncounted(progress, row, remaining)
            continue
        row_spent = result.get("spent_usd")
        if billed and row_spent is None:
            row_spent = _uncounted(progress, row, remaining)
        spent_total += float(row_spent or 0.0)
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
        "spent_usd": spent_total if billed else None,
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


#: How long a check's answer is good for. Every screen that shows a hint
#: about pack updates asks on every navigation (B145 perf-3/knowledge-2); this
#: is what turns "one real fetch to a remote index per navigation" into "one
#: real fetch per five minutes", which is the difference between an endpoint
#: that is fast on repeat visits and one that never gets fast at all. Keyed by
#: URL, not global, so a reader who points this at their own index during
#: development never sees another URL's stale answer.
_UPDATES_CACHE_TTL = 300
_updates_cache: dict[str, tuple[float, list, str | None, str | None, str]] = {}


def _friendly_index_error(exc: Exception) -> str:
    """A sentence, not a protocol code — see B145 apicode-1/knowledge-21.

    `HTTPError: HTTP Error 404: Not Found` is accurate and useless to a reader
    with no terminal: it names a status they cannot act on. Distinguishing
    "nothing published" from "nothing reachable" is the one thing worth
    keeping, because the remedy differs (wait for a release vs. check the
    network); everything else collapses to one plain sentence. The exception
    itself keeps travelling as `error_detail`, for whoever files the bug.
    """
    import urllib.error

    if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
        return "The pack index has nothing published yet."
    if isinstance(exc, (urllib.error.URLError, OSError)):
        return "The pack download site could not be reached."
    return "Could not check for pack updates."


def _updates_payload(url: str, rows, candidates: list, error: str | None,
                      error_detail: str | None, checked_at: str) -> dict:
    if error:
        return {
            "index_url": url,
            "error": error,
            "error_detail": error_detail,
            "checked_at": checked_at,
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
    return {
        "index_url": url,
        "error": None,
        "error_detail": None,
        "checked_at": checked_at,
        "packs": payload,
    }


def check_updates(settings, index_url: str = "", *, fresh: bool = False) -> dict:
    """Compare what is installed against what the index offers.

    Synchronous and cheap — one small JSON fetch, and only when the cache
    below is cold or `fresh` is asked for — so it is a request rather than a
    job. Network failure is reported as a value, not raised: "we could not
    reach the index" is a legitimate answer to "is anything newer", and a 500
    would make the Packs screen look broken when only the network is.

    `fresh=False` (every screen's own background hint) reuses the last answer
    for this URL within `_UPDATES_CACHE_TTL`, so the remote fetch that used to
    happen on every navigation now happens at most once per window — see
    B145 perf-3, knowledge-2, knowledge-19. `fresh=True` is the reader's own
    "Check for updates" press: it always pays for the round trip, and its
    answer refills the cache for every other screen too.
    """
    import time

    url = index_url or settings.pack_index_url
    conn = connect(settings.store_path)
    try:
        rows = _installed_rows(conn)
    finally:
        conn.close()

    cached = _updates_cache.get(url)
    if not fresh and cached is not None and time.monotonic() - cached[0] < _UPDATES_CACHE_TTL:
        _, candidates, error, error_detail, checked_at = cached
        return _updates_payload(url, rows, candidates, error, error_detail, checked_at)

    try:
        candidates = packsource.fetch_index(url)
        error = None
        error_detail = None
    except Exception as exc:  # noqa: BLE001 — unreachable is an answer, not a crash
        candidates = []
        error = _friendly_index_error(exc)
        error_detail = f"{type(exc).__name__}: {exc}"

    checked_at = _now()
    _updates_cache[url] = (time.monotonic(), candidates, error, error_detail, checked_at)
    return _updates_payload(url, rows, candidates, error, error_detail, checked_at)


def _note_automatic_pass(settings, params: dict) -> None:
    """Remember that the weekly background pass ended well (B166)."""
    if params.get("automatic"):
        packautoupdate.record_success(settings.app_state_path)


def pack_update(settings, params: dict, progress: Progress) -> dict:
    """Download and install every pack the index has something newer for.

    Goes through `packstore.install` like every other door: an updated pack is
    not a special kind of pack, and a second install path is a second place for
    the immutability rule to be forgotten.
    """
    only = params.get("pack_id") or ""
    index_url = params.get("index_url") or settings.pack_index_url
    progress.set(0.05, f"reading {index_url}")
    try:
        candidates = packsource.fetch_index(index_url)
    except Exception as exc:  # noqa: BLE001 — a sentence, not a protocol code
        # Same mapping as `check_updates`: this job's failure message is what
        # settings-2's Welcome screen shows the reader verbatim, and a raw
        # HTTPError read as "the engine died" (B145 settings-2).
        raise RuntimeError(_friendly_index_error(exc)) from exc
    progress.log(f"index offers {len(candidates)} pack(s)")

    conn = connect(settings.store_path)
    try:
        rows = _installed_rows(conn)
    finally:
        conn.close()

    known = {row["pack_id"] for row in rows}
    wanted = [d for d in updates.plan(rows, candidates) if d.actionable]
    # The background pass (B166) only follows what is already installed: a
    # pack the reader removed is not something a clock may bring back.
    if not params.get("installed_only"):
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
        _note_automatic_pass(settings, params)
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
    _note_automatic_pass(settings, params)
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
    from app.providers import agent_ready, harness, harness_researcher

    category = str(params.get("category") or "").strip()
    if not category:
        raise ValueError(
            "name the category in a few words — 'cordless drills', 'espresso "
            "machines'. It is the only thing an agent cannot infer")

    if _use_local_ask(settings, params):
        # No coding agent, or the door chose the local model (B171): the same
        # job on a model served from this machine.
        researcher = _local_asker(settings, params, progress)
    else:
        if not agent_ready(settings.app_state_path, str(params.get("harness") or "")):
            # Said in full rather than as "no harness": a reader whose opencode is
            # installed deserves to know why it is not being driven, and a reader
            # with neither deserves the other door rather than a dead end.
            blocked = "; ".join(one.unusable for one in harness.found_but_unusable())
            raise ValueError(
                f"{NO_AGENT} Kriko cannot author a pack by itself. Install a coding "
                "agent, pick the Mistral API agent, run a local model server "
                "(Ollama or LM Studio, with a model downloaded), or hand the brief "
                "to your own agent through the MCP server (Agents → Connect) and "
                "let it use `draft_pack`."
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
        _cap_agent(researcher, params)
        # The forty-minute silence this job used to be (B121). A pack author is
        # the longest-running thing in the app and the one whose log most needed
        # to say something before it finished.
        researcher.on_action = progress.log
        researcher.check_cancelled = progress.check
        # The return path. Same wiring, opposite direction: `check` asks whether
        # the reader wants this stopped, `replies` asks whether they have said
        # anything to it. A run that pauses on a question was previously a window.
        researcher.replies = progress.replies
    # A product check (B168, B169). `product_only` is the name this mode had
    # when it minted one pack per product; a retried old row still says it, and
    # now takes the same path as a new one.
    product = str(params.get("product") or "").strip() or (
        category if params.get("product_only") else "")
    if product:
        return _product_check(settings, researcher, params, progress, product, category)
    # ── the cheap pass, before the expensive one ─────────────────────────
    #
    # "It never asks me anything." A pack built on the wrong variant is worse
    # than no pack, because it is confidently wrong — and the point of asking
    # *here* is that the expensive research has not happened yet. Nothing waits
    # on the answer: see `app/disambiguate.py` for why non-blocking is not a
    # compromise but the automation principle holding.
    scope, asked, asked_why = _disambiguate(
        settings, researcher, category, params, progress)

    progress.set(0.15, f"{researcher.search_provider} is reading up on {category}")
    progress.log(f"category: {category}")

    prompt = packauthor.brief(category, scope=scope)
    # What the listing says (B150): the reader asked for the agents to
    # settle the exact version from the page, not to ask them for it.
    from app import pagefacts

    prompt += pagefacts.block(params.get("page"))
    prompt += _source_ceiling(params)
    reply = researcher.ask(prompt)
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
    installed = _install_draft(settings, written, progress) if params.get("install") else ""
    progress.set(
        1.0,
        f"drafted {written['pack_id']} — {written['subjects']} subject(s), "
        f"{written['claims']} claim(s). "
        + ("Installed." if installed
           else "Nothing is installed yet: read it on Knowledge and press Install.")
    )
    written["category"] = category
    written["scope"] = scope
    if getattr(researcher, "cost_basis", "") == "per_token":
        written["spent_usd"] = getattr(researcher, "spent", None)
    # Carried into the *final* result, not left in the partial one: a
    # succeeding run replaces its partial result wholesale, so questions kept
    # only there are visible on a cancelled run and on no other. They outlive
    # this run on purpose — the answers make the *next* run exact, which is
    # why `_with_attention` offers them beside "run it again".
    if asked:
        written["questions"] = asked
        written["why"] = asked_why
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


#: How long a quick look may take before it is not quick. Long enough for a
#: few searches and three pages on a slow connection; short enough that the
#: reader is still on the listing when it answers. (B148)
QUICK_LOOK_TIMEOUT_SECONDS = 240


def quick_look(settings, params: dict, progress: Progress) -> dict:
    """A chat-speed answer for a product no pack knows yet. (B148)

    The reader's words: "in normal claude or Mistral vibe chat they can search
    web and answer instantly". The only door for an unknown product was a whole
    pack authored from scratch, so the listing showed nothing for forty
    minutes and then showed a draft. This is one short call at the lowest
    effort the CLI takes; the deeper run (`deepen_job_id`) starts beside it.

    Writes nothing to the store, which is why it may run beside a job that
    does. The risks are a job result the panel renders, each with the page and
    quote it claims — `quicklook.parse` drops the rest. The deepen job started
    beside it reads that result and is what puts the product and its risks in a
    category pack (B168): this handler only says which pack it thinks the
    product belongs in, from the installed ones it is shown.
    """
    from app import categorypack, quicklook
    from app.providers import harness_researcher
    from kriko.research import pack_asset

    product = str(params.get("product") or "").strip()
    if not product:
        raise ValueError("name the product — the quick look has nothing else to go on")

    principle = ""
    attributes = ""
    pack_id = str(params.get("pack_id") or "")
    if pack_id:
        store = connect(settings.store_path)
        try:
            principle = pack_asset(store, pack_id, "research/principle.md")
            # The pack's own names for what it records about a product, minus
            # the keys that identify it (B173).
            from app.termlabel import term_label

            attributes = "\n".join(
                f"* {term_label(row['label_json'], row['term_id'])}"
                for row in store.execute(
                    "SELECT term_id, label_json FROM terms"
                    " WHERE pack_id = ? AND role = 'attribute'"
                    "   AND term_id NOT IN (SELECT key FROM attributes"
                    "                        WHERE pack_id = ? AND is_identity = 1)"
                    " ORDER BY term_id", (pack_id, pack_id)))
        finally:
            store.close()

    if _use_local_ask(settings, params):
        researcher = _local_asker(settings, params, progress)
    else:
        researcher = harness_researcher(
            preferred=str(params.get("harness") or ""),
            app_state_path=settings.app_state_path,
            timeout=float(params.get("timeout_seconds") or QUICK_LOOK_TIMEOUT_SECONDS),
            # Low, whatever the reader's everyday dial says: this is the chat-speed
            # pass. A CLI that does not declare `low` has it dropped rather than
            # refused (`harness_researcher`), so the dial never costs the run.
            effort="low",
        )
        _cap_agent(researcher, params)
        researcher.on_action = progress.log
        researcher.check_cancelled = progress.check

    try:
        packs = categorypack.choice_block(categorypack.candidates(settings.store_path))
    except Exception:  # noqa: BLE001 - a list of packs is never why a look fails
        packs = ""
    progress.set(0.1, f"a quick look at {product}")
    reply = researcher.ask(
        quicklook.brief(product, principle, params.get("page"), packs, attributes))
    progress.check()
    # The API agent keeps what its search returned per url; a CLI keeps
    # nothing, and `None` tells the parser there is nothing to check against.
    found = quicklook.parse(reply, getattr(researcher, "sources", None))
    kept = len(found["risks"])
    spent = getattr(researcher, "spent", None)
    billed = getattr(researcher, "cost_basis", "") == "per_token"
    progress.set(1.0, (
        f"{kept} risk(s) found" if kept else "nothing it could source in the time")
        + (f", {found['dropped']} unsourced dropped" if found["dropped"] else "")
        + ((f", ${spent:.2f}" if spent is not None else ", cost unknown") if billed else ""))
    return {
        "product": product,
        **found,
        "deepen_job_id": str(params.get("deepen_job_id") or ""),
        "harness": getattr(getattr(researcher, "harness", None), "id", ""),
        "model": str(getattr(researcher, "model", "") or ""),
        "cost_basis": getattr(researcher, "cost_basis", "subscription"),
        "spent_usd": spent if billed else None,
        "tokens_used": getattr(researcher, "tokens_used", None),
    }


def _install_draft(settings, written: dict, progress: Progress) -> str:
    """Install what was just drafted, the way the reader's Install press does.

    Asked for by the reader for the listing's "Research this product" (B148):
    "yes it should install itslef". The same build-then-install path as
    `POST /api/packs/drafts/{slug}/install`, so nothing here is a second
    definition of a valid pack: both go through `categorypack.install_draft`,
    which raises the draft's version when its content changed (B170). A draft
    that will not build or install stays a draft and the log says why — fail
    open, never a failed run over work that is still on disk to fix.
    """
    from app import categorypack

    slug = written.get("slug") or ""
    try:
        done = categorypack.install_draft(settings.store_path, slug)
    except Exception as exc:  # noqa: BLE001 — the draft is kept either way
        progress.log(f"kept as a draft, not installed: {exc}")
        return ""
    written["installed"] = True
    written["pack_id"] = done["pack_id"]
    written["version"] = done["version"]
    written["digest"] = done["digest"][:12]
    if done["bumped"]:
        progress.log(f"version raised to {done['version']}")
    if done["absorbed"]:
        progress.log(f"kept {done['absorbed']} claim(s) from earlier research")
    progress.log(f"installed {done['pack_id']} {done['version']}")
    return done["pack_id"]


#: How long a deepen job waits for the quick look started beside it. The quick
#: look has its own ceiling; the extra minute is for it to be queued behind two
#: others in its lane.
QUICK_WAIT_SECONDS = QUICK_LOOK_TIMEOUT_SECONDS + 60
#: How long to wait for that quick look to exist at all. It is submitted a
#: moment after this job, so a longer silence means there is none (a retry, or
#: a caller that started this job alone).
QUICK_APPEAR_SECONDS = 5.0
QUICK_POLL_SECONDS = 0.2


def _await_quick_look(settings, progress: Progress) -> dict:
    """What the quick look beside this job concluded, or `{}`.

    The deepen job needs the quick look's answer before it can choose a pack:
    which installed pack the product belongs in, and the sourced risks that
    become its claims. Waiting is bounded and a missing or failed quick look is
    an empty answer, never a failed check: the product still joins a pack, just
    without those risks.
    """
    conn = state.connect(settings.app_state_path)
    try:
        began = time.monotonic()
        said = False
        while True:
            progress.check()
            job = state.quick_look_for(conn, progress.job_id)
            waited = time.monotonic() - began
            if job is None:
                if waited > QUICK_APPEAR_SECONDS:
                    return {}
            elif job["done"]:
                return (job["result"] or {}) if job["state"] == state.SUCCEEDED else {}
            elif waited > QUICK_WAIT_SECONDS:
                progress.log("the quick look is taking too long; carrying on without it")
                return {}
            if not said:
                progress.set(0.02, "waiting for the quick look")
                said = True
            time.sleep(QUICK_POLL_SECONDS)
    finally:
        conn.close()


def _page_reader():
    """The reader a quote is checked against. One place, so a test hands it a page."""
    from app.providers import fetch

    return fetch.reader(15.0)


def _sourced_items(quick: dict, proposed) -> tuple[list[dict], int]:
    """Claims that name a page, from the quick look and from the agent's reply.

    Returns the items for `categorypack.ground` and how many of the agent's
    claims named no page at all. Those are not carried over: a product check
    keeps a claim only with a source (B168).
    """
    items = [
        {"title": one.get("title"), "body": one.get("body"),
         "advice": one.get("advice"), "severity": one.get("severity"),
         "evidence": list(one.get("sources") or [])}
        for one in quick.get("risks") or [] if isinstance(one, dict)
    ]
    bare = 0
    for claim in proposed or []:
        if not isinstance(claim, dict):
            continue
        evidence = [
            {"url": one.get("url"), "quote": one.get("quote")}
            for one in claim.get("evidence") or [] if isinstance(one, dict)
        ]
        if not evidence:
            bare += 1
            continue
        items.append({
            "title": claim.get("title"), "body": claim.get("body"),
            "advice": claim.get("advice"), "severity": claim.get("severity"),
            "domain": claim.get("domain"), "evidence": evidence,
        })
    return items, bare


def _product_check(settings, researcher, params: dict, progress: Progress,
                   product: str, category: str) -> dict:
    """One product, into a pack for its category (B168, B169, B170).

    The reader's words: "Singular product searches must not create a new pack
    each time". The flow is in `docs/superpowers/specs/2026-09-29-category-
    packs-design.md`; in short, the quick look beside this job names an
    installed pack the product belongs in (or none), the agent adds the
    product to that pack or authors a pack for the category, the quick look's
    risks are re-read against their pages and attached as sourced claims, and
    the pack is installed at a raised version.

    Fails open at each step that a person would otherwise be asked about: no
    quick look, no readable page or no fitting pack each mean less is kept,
    never that the check stops. Only an agent reply that is not a pack fails.
    """
    from app import categorypack, packauthor, pagefacts
    from kriko.gates import load_gates

    quick = _await_quick_look(settings, progress)
    said = str(quick.get("category") or "").strip()
    target = categorypack.resolve(
        categorypack.candidates(settings.store_path),
        pack=str(quick.get("pack") or ""), category=said)

    scope, asked, asked_why = _disambiguate(settings, researcher, product, params, progress)

    listing = pagefacts.block(params.get("page"))
    naming = said or category or product
    if target:
        progress.log(f"{product} belongs in {target['name']} ({target['pack_id']})")
        progress.set(0.15, f"adding {product} to {target['name']}")
        prompt = packauthor.amend_brief(
            packauthor.draft_state(settings.store_path, target["slug"]),
            packauthor.product_note(product, scope)) + listing
    else:
        progress.log(f"no installed catalog fits; authoring one for {naming}")
        progress.set(0.15, f"{researcher.search_provider} is reading up on {naming}")
        prompt = (
            packauthor.brief(naming, scope=scope)
            + packauthor.category_appendix(
                product, naming, categorypack.taken_ids(settings.store_path))
            + listing)
    reply = researcher.ask(prompt)
    progress.check()
    progress.set(0.7, "writing the draft")
    progress.log(reply.strip()[:4000] or "(the agent printed nothing)")

    payload = packauthor.read_payload(reply)[0]
    proposed = payload.pop("claims", None) if payload else None
    categorypack.admit(payload, product)

    joined = bool(target)
    slug = target["slug"] if target else ""
    try:
        if target:
            written = packauthor.amend(
                settings.store_path, slug, reply, payload=payload,
                allow_nothing_new=True)
        else:
            try:
                written = packauthor.author(
                    settings.store_path, reply, category=naming, payload=payload)
            except packauthor.PackExists as exists:
                # The id it chose already has a draft: the product goes there.
                progress.log(f"{exists.pack_id} already has a draft; the product joins it")
                joined, slug = True, exists.slug
                written = packauthor.amend(
                    settings.store_path, slug, reply, payload=payload,
                    allow_nothing_new=True)
    except packauthor.PackRefused as exc:
        # Fail open when the pack already names this product: an agent that
        # returned nothing new for a product that is already there has not
        # failed, and the sourced claims below still have a subject to join.
        held = categorypack.holds(settings.store_path, slug, product) if slug else None
        if held is None:
            raise ValueError(f"the agent did not produce a usable pack: {exc}") from exc
        written = held
        progress.log(f"nothing new from the agent; {product} is already in the catalog")

    for name in written["files"]:
        progress.log(f"wrote {name}")
    if written.get("notes"):
        progress.log(f"the author noted: {written['notes']}")

    items, bare = _sourced_items(quick, proposed)
    if bare:
        progress.log(f"{bare} claim(s) named no page and were left out")
    progress.set(0.8, f"checking {len(items)} quote(s) against their pages")
    kept, dropped = categorypack.ground(items, _page_reader())
    progress.check()
    for one in dropped:
        progress.log(f"left out {one['title']!r}: {one['reason']}")

    vocab = None
    if joined:
        store = connect(settings.store_path)
        try:
            vocab = load_gates(store, written["pack_id"])
        finally:
            store.close()
    attached = categorypack.attach(
        settings.store_path, written["slug"], product, kept,
        subject_rows=written.get("subject_rows"), vocab=vocab)
    for one in attached["refused"]:
        progress.log(f"left out {one['title']!r}: {one['reason']}")

    installed = _install_draft(settings, written, progress) if params.get("install") else ""
    where = written["name"]
    progress.set(
        1.0,
        f"{product} is in {where}: {attached['claims_added']} sourced claim(s) added"
        + (f", version {written['version']}. Installed." if installed
           else ". Nothing is installed yet."))
    written.update({
        "category": said or (target["name"] if target else naming),
        "scope": scope, "product": product, "joined": joined,
        "subject": attached["subject"],
        "claims_added": attached["claims_added"],
        "evidence_added": attached["evidence_added"],
        "left_out": dropped,
    })
    written["claims"] = int(written.get("claims") or 0) + attached["claims_added"]
    if getattr(researcher, "cost_basis", "") == "per_token":
        written["spent_usd"] = getattr(researcher, "spent", None)
    if asked:
        written["questions"] = asked
        written["why"] = asked_why
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
    from app.providers import agent_ready, harness, harness_researcher

    slug = str(params.get("slug") or "").strip()
    if not slug:
        raise ValueError("which draft? `slug` is required")
    note = str(params.get("note") or "").strip()

    state_of = packauthor.draft_state(settings.store_path, slug)
    if _use_local_ask(settings, params):
        researcher = _local_asker(settings, params, progress)
    else:
        if not agent_ready(settings.app_state_path, str(params.get("harness") or "")):
            raise ValueError(
                f"{NO_AGENT} Kriko cannot extend this draft by itself. Hand the "
                "brief to your own agent through the MCP server (Agents → Connect) "
                "— `amend_draft` gives you the same brief."
            )

        researcher = harness_researcher(
            preferred=str(params.get("harness") or ""),
            app_state_path=settings.app_state_path,
            timeout=float(
                params.get("timeout_seconds") or harness.AUTHOR_TIMEOUT_SECONDS),
        )
        _cap_agent(researcher, params)
        researcher.on_action = progress.log
        researcher.check_cancelled = progress.check
        # The return path. Same wiring, opposite direction: `check` asks whether
        # the reader wants this stopped, `replies` asks whether they have said
        # anything to it. A run that pauses on a question was previously a window.
        researcher.replies = progress.replies
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

    # Events on `ingestion`, not a stage of its own. `STAGES` is a closed
    # vocabulary and `open_stage` refuses anything outside it — so the
    # "repair" stage this first tried to open raised `ValueError` and would
    # have killed every run that reached the loop. It is the right refusal:
    # repair is not a fifth phase of the pipeline, it is acceptance asking
    # once more, and it runs *after* ingestion and feeds back into it rather
    # than sitting anywhere in the sequence.
    emit.event(f"re-asking for {len(again)} finding(s)", stage="ingestion")
    progress.log(
        f"{len(again)} finding(s) were refused for a field that can be "
        f"rewritten — asking once more"
    )
    progress.check()
    try:
        mended = researcher.repair(task, again, wanted)
    except (Cancelled, BudgetExceeded):
        raise
    except Exception as exc:  # noqa: BLE001 — a failed repair is not a failed run
        emit.event(f"could not re-ask: {exc}", level="warn", stage="ingestion")
        return verdicts

    progress.check()
    kept = [one for one in mended if explanation(one)]
    if not kept:
        emit.event("nothing came back with the field filled in",
                   level="warn", stage="ingestion")
        return verdicts

    second = accept_findings(conn, subject_id, pack_id, kept, retain=retain)
    emit.event(
        f"{len(second.get('accepted', []))} of {len(again)} kept on the "
        f"second attempt", stage="ingestion")

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


def _disambiguate(settings, researcher, subject, params,
                  progress) -> tuple[dict, list, str]:
    """One short call: is this name one product or several?

    Returns `(scope, questions, why)` — the scope record (what was settled,
    and which parts of it were *assumed* rather than confirmed), plus the
    questions themselves so the caller can carry them into its own result.

    The questions are returned rather than left in `progress.partial` because
    a succeeding run's final result *replaces* the partial one (`finish_job`
    in `app/web/jobs.py`). Anything written here and not carried out by the
    caller therefore exists only until the run succeeds — which is every run
    a reader actually waits for. That is how a fully-built question mechanism
    came to reach the screen as log prose and nothing else.

    Never raises and never waits: a disambiguation that failed must cost the
    reader a question, not the run behind it, so every failure path here
    returns the same empty scope the run had before this existed.
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
            researcher.ask(disambiguate.brief(subject, keys, params.get("page"))))
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 — a lost question, never a lost run
        progress.log(f"could not check the name for ambiguity ({exc}) — "
                     f"carrying on without asking")
        return {}, [], ""

    if not found["ambiguous"]:
        progress.log(f"“{subject}” names one product — nothing to ask")
        return disambiguate.scope(found), [], ""

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
    return scope, found["questions"], found["why"]


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
        # A CLI that can fetch the page's markup, never the API agent: an
        # adapter is selectors, and search text has no elements to select.
        api=False,
    )
    researcher.on_action = progress.log
    researcher.check_cancelled = progress.check
    # The return path. Same wiring, opposite direction: `check` asks whether
    # the reader wants this stopped, `replies` asks whether they have said
    # anything to it. A run that pauses on a question was previously a window.
    researcher.replies = progress.replies
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
        state.set_site_request(
            app_conn, host, state="done",
            detail=f"{len(checked.get('identity') or {})} identity key(s), "
                   f"{len(checked.get('context') or {})} context")
    finally:
        app_conn.close()

    progress.set(
        1.0,
        f"{host} can be read now — {len(checked.get('identity') or {})} "
        f"identity key(s). Open a listing there and press the extension button."
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
        # The fixed, versioned set first (B185, D6): a benchmark that reads
        # the installed packs measures whatever happens to be installed, and
        # the reader's own packs are drafted by the very agents being judged.
        # A pack's gold set still runs when named, so an author can measure
        # their own bar; it is never the default.
        from app import benchcases
        found = benchcases.case_rows(limit)
        graded = bool(found)
        if not found:
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

    # Which models answered. The axis §2.6 asks for first, and swept on the
    # same terms as every other one here: only when named. A benchmark that
    # swept the catalogue by default would multiply the bill by however many
    # models the reader happens to have priced.
    models_asked = [
        one.strip()
        for one in str(params.get("models") or params.get("model") or "").split(",")
        if one.strip()
    ] or [""]

    batch_id = secrets.token_hex(8)
    app_conn = state.connect(settings.app_state_path)
    rows = []
    try:
        # Each LLM on the plane that names it (`bench.pairs`): crossing the
        # harness CLIs' names with the paid catalogue's made runs that could
        # only fail.
        runs_of = bench_mod.pairs(
            chosen, [one for one in models_asked if one], bench_mod.llm_owners(),
        )
        total = (
            len(found) * len(runs_of) * len(protocols_asked)
            * len(searches_asked) * reps
        )
        done = 0
        for case in found:
            for plane, model_for_plane in runs_of:
                for protocol, search, model, rep in [
                    (one, engine, model_for_plane, index)
                    for one in protocols_asked
                    for engine in searches_asked
                    for index in range(1, reps + 1)
                ]:
                    progress.check()
                    progress.set(
                        done / max(1, total),
                        f"{plane}: "
                        f"{case.get('label') or case.get('product') or case.get('subject_id')}",
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
                        model=model,
                        check_cancelled=progress.check,
                    )
                    row["rep"] = rep
                    state.record_bench(app_conn, row)
                    rows.append(row)
                    done += 1
                    progress.partial({
                        "batch_id": batch_id, "rows": rows,
                        "measurements": done, "stopped_at": "benchmark",
                    })
                    progress.check()
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

    failed = sum(1 for row in rows if row.get("error"))
    message = f"{len(rows)} measurement(s) across {len(chosen)} plane(s)"
    if failed:
        message += f", {failed} failed"
    progress.set(1.0, message)
    if rows and failed == len(rows):
        # ops-1: every case in this run raised before it could be scored. A
        # `succeeded` job with an empty readout ("No benchmark runs yet")
        # reads as nothing having run at all — the reader needs the red
        # state, not a quiet miscount. The rows themselves are still on the
        # job's own partial result (state.partial_of), so nothing measured
        # is lost by failing loudly here.
        raise RuntimeError(f"every case failed — {rows[0]['error']}")
    return {
        "batch_id": batch_id,
        "cases": [case.get("id") or case.get("subject_id") for case in found],
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


#: How long a follow-up question about a comparison may take. A shortlist
#: question is a reading task, not an authoring one: it is the same scale as
#: a quick look, and giving it the authoring timeout would leave the reader
#: staring at "running" for most of an hour over a question they wanted in
#: minutes.
COMPARE_ASK_TIMEOUT_SECONDS = 900


def compare_ask(settings, params: dict, progress: Progress) -> dict:
    """Answer a follow-up question about a comparison, with the table it is
    about attached (B193).

    * "adding multiple products side by side, add follow up questions to
    agents regarding to that"*. The Compare screen lines up checks the
    reader already has; this is the question the table raises ("which of
    these has the cheaper known fix") asked of their own agent, with each
    column's claims and specifications passed through verbatim so any
    category works without this layer knowing one (G6).

    Writes nothing to the knowledge store. The reply is the reader's own
    decision support, stored on the question row in `app.sqlite` by
    `answer_compare_question` — never a submission, never a claim.
    """
    from app.providers import agent_ready, harness_researcher
    draft_id = str(params.get("draft_id") or "").strip()
    question_id = str(params.get("question_id") or "").strip()
    question = str(params.get("question") or "").strip()
    if not (draft_id and question_id and question):
        raise ValueError("which question? `draft_id` and `question_id` are required")
    app_state = state.connect(settings.app_state_path)
    try:
        draft = state.get_compare_draft(app_state, draft_id)
        if not draft:
            raise ValueError(f"no draft {draft_id}")
        answers = []
        for lookup_id in draft["lookup_ids"]:
            stored = state.get_lookup(app_state, lookup_id)
            if stored:
                answers.append(stored)
    finally:
        app_state.close()
    if len(answers) < 2:
        raise ValueError("this draft lines up fewer than two saved checks")
    progress.set(0.05, "lining up the shortlist")
    for stored in answers:
        progress.log(f"{stored['label']}: {len(stored['response'].get('claims') or [])} known risk(s)")
    if _use_local_ask(settings, params):
        researcher = _local_asker(settings, params, progress)
    else:
        if not agent_ready(settings.app_state_path, str(params.get("harness") or "")):
            raise ValueError(
                f"{NO_AGENT} Kriko cannot answer this by itself. Hand the "
                "question and the table to your own agent (Agents → "
                "Connect), or run one of the planes in Settings → Research."
            )
        researcher = harness_researcher(
            preferred=str(params.get("harness") or ""),
            app_state_path=settings.app_state_path,
            timeout=float(
                params.get("timeout_seconds") or COMPARE_ASK_TIMEOUT_SECONDS),
        )
        _cap_agent(researcher, params)
        researcher.on_action = progress.log
        researcher.check_cancelled = progress.check
    progress.set(0.2, f"asking: {question[:120]}")
    reply = researcher.ask(_compare_brief(question, answers)).strip()
    progress.check()
    progress.log(reply[:4000] or "(the agent printed nothing)")
    progress.set(0.9, "writing the answer down")
    app_state = state.connect(settings.app_state_path)
    try:
        row = state.answer_compare_question(
            app_state, draft_id, question_id, reply, progress.job_id)
    finally:
        app_state.close()
    if not row:
        raise ValueError("the question is gone — the draft was deleted while it ran")
    progress.set(1.0, "answered" if reply else "the agent printed nothing")
    return {"draft_id": draft_id, "question_id": question_id, "answer": reply}


def _compare_brief(question: str, answers: list[dict]) -> str:
    """The table the question is about, as the agent's own reading material.

    Every word of it comes from the stored answers themselves — labels,
    claim titles, bodies and specifications as the packs wrote them — so the
    brief works for any category and stays honest about what this install
    actually knows. No invented fields, no invented risks: a column with no
    claims says so, which is itself an answer to some questions.
    """
    lines = [
        "The reader has these products side by side and asks:",
        f"QUESTION: {question}",
        "",
        "Answer about the products below, using their recorded risks and "
        "specifications. Where the records do not answer the question, say "
        "so plainly rather than guessing. Do not invent risks.",
        "",
    ]
    for stored in answers:
        response = stored["response"]
        lines.append(f"## {stored['label']}")
        claims = response.get("claims") or []
        if claims:
            lines.append("Known risks:")
            for claim in claims:
                severity = str(claim.get("severity") or "")
                line = f"- [{severity}] {claim.get('title') or ''}"
                if claim.get("body"):
                    line += f": {claim['body']}"
                if claim.get("advice"):
                    line += f" (advice: {claim['advice']})"
                lines.append(line)
        else:
            lines.append("Known risks: none recorded.")
        if response.get("context"):
            units = _context_units_of(response)
            for key, value in sorted(response["context"].items()):
                unit = units.get(key, "")
                lines.append(f"- {key}: {value}{(' ' + unit) if unit else ''}")
        lines.append("")
    return "\n".join(lines)


def _context_units_of(response: dict) -> dict:
    """The units a lookup's context was written in, best-effort.

    The stored response carries `context_units` when the answer came from
    `/api/lookup`; an older or hand-built row does not, and a missing dict
    must degrade to no units rather than a crash inside a job.
    """
    units = response.get("context_units")
    return units if isinstance(units, dict) else {}


HANDLERS = {
    "research": research,
    "bench": bench,
    "agenda_run": agenda_run,
    "research_undo": research_undo,
    "pack_build": pack_build,
    "pack_author": pack_author,
    "quick_look": quick_look,
    "pack_amend": pack_amend,
    "verify": verify,
    "site_register": site_register,
    "pack_update": pack_update,
    "compare_ask": compare_ask,
}
