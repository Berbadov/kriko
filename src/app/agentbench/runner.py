"""Run a task: the real quick-look job, one agent, the fixed web.

What is under test is `tasks.quick_look` as the app runs it. Nothing about the
agent's side is stubbed for a real agent: Kriko resolves the reader's settings,
builds the queries, reads the pages through the fixed web, hands them to the
CLI, and grounds what comes back. A scripted agent differs in one place only,
the CLI's reply (`simulated`).

Each trial runs in its own throwaway app state, so a benchmark neither reads
nor writes the reader's history, and two trials cannot influence one another.
"""

import shutil
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest import mock

from app.agentbench import checks, simulated
from app.agentbench.web import FakeWeb

if TYPE_CHECKING:
    from app.web.jobs import Progress

#: How long one trial may take, as a quick look's own ceiling does.
TRIAL_TIMEOUT_SECONDS = 240.0

PROFILES = ("reader", "clean")


class AgentUnavailable(Exception):
    """The agent cannot run here; the report says why instead of scoring it."""


def classify(agent: str) -> dict:
    """What kind of agent this is and which CLI runs it, or why it cannot run.

    Raises `AgentUnavailable` for an agent that is not installed, and for one
    that browses for itself: no fixture can stand in for the real web it uses,
    so scoring it against one would measure nothing.
    """
    from app.providers import harness

    if simulated.is_simulated(agent):
        return {"agent": agent, "kind": "host-read", "harness_id": "codex",
                "simulated": agent[len(simulated.PREFIX):]}
    if agent == "local":
        from app import localplane

        if not localplane.is_ready(None):
            raise AgentUnavailable("the local model server is not reachable")
        return {"agent": agent, "kind": "local", "harness_id": "", "simulated": ""}
    known = {one.id: one for one in harness.KNOWN}
    if agent not in known:
        raise AgentUnavailable(
            f"unknown agent {agent!r}; known: local, {', '.join(sorted(known))}, "
            + ", ".join(simulated.names()))
    if agent not in harness.HOST_READ_HARNESSES:
        raise AgentUnavailable(
            f"{agent} browses with its own tools, which a fixed web cannot replace; "
            f"gradable agents: local, {', '.join(sorted(harness.HOST_READ_HARNESSES))}")
    if agent not in {one.id for one in harness.available()}:
        raise AgentUnavailable(f"{agent} is not installed here")
    return {"agent": agent, "kind": "host-read", "harness_id": agent, "simulated": ""}


def _seed_settings(root: Path, info: dict, task: dict, profile: str,
                   reader_state: Path | None):
    """The trial's own app state: the reader's settings or a clean one, then the task's."""
    from app import bench, prefs
    from app.web import state
    from app.web.settings import Settings

    settings = Settings(
        store_path=root / "knowledge.sqlite",
        app_state_path=root / "app.sqlite",
        analysis_log_path=root / "analyses.jsonl",
    )
    conn = state.connect(settings.app_state_path)
    conn.close()
    if profile == "reader" and reader_state is not None:
        bench._copy_settings(reader_state, settings.app_state_path)
    conn = state.connect(settings.app_state_path)
    try:
        chosen = {prefs.HARNESS: prefs.LOCAL_PICK if info["kind"] == "local" else info["harness_id"]}
        if profile == "clean" and info["harness_id"]:
            # A clean state still has a level to obey, or "obeys the effort" would
            # pass by there being nothing to obey.
            from app.providers import harness

            row = next(one for one in harness.KNOWN if one.id == info["harness_id"])
            level = next((one for one in row.effort_choices if one != "low"), "")
            if level:
                chosen[prefs.harness_effort_key(info["harness_id"])] = level
        chosen.update({key: str(value) for key, value in (task.get("settings") or {}).items()})
        prefs.write(conn, chosen)
        return settings, prefs.read(conn)
    finally:
        conn.close()


def run_trial(task: dict, agent: str, *, rep: int = 1, profile: str = "reader",
              reader_state: Path | None = None,
              timeout: float = TRIAL_TIMEOUT_SECONDS) -> dict:
    """One agent on one task once: the observation, the graded checks, the cost."""
    from app.providers import harness as harness_mod
    from app.web import state, tasks
    from app import bench

    info = classify(agent)
    root = Path(tempfile.mkdtemp(prefix="kriko-agentbench-"))
    try:
        settings, effective = _seed_settings(root, info, task, profile, reader_state)
        params = {
            "product": task["product"],
            "page": task.get("page") or {"facts": {}, "description": ""},
            "page_url": f"https://shop.example/{task['id']}",
            "harness": info["harness_id"],
            "backend": "local" if info["kind"] == "local" else "",
            "timeout_seconds": timeout,
        }
        conn = state.connect(settings.app_state_path)
        try:
            job_id = state.create_job(conn, "quick_look", params)
        finally:
            conn.close()
        progress = bench._Silent()
        progress.job_id = job_id

        web = FakeWeb(task.get("pages") or [])
        captured: dict = {"prompts": []}
        result: dict = {}
        error = ""
        started = time.perf_counter()
        with ExitStack() as stack:
            stack.enter_context(web.installed())
            if info["simulated"]:
                codex = next(one for one in harness_mod.KNOWN if one.id == "codex")

                def scripted(_self, prompt):
                    captured["prompts"].append(prompt)
                    return simulated.reply(info["simulated"], task, prompt)

                stack.enter_context(mock.patch.object(harness_mod, "available", lambda: [codex]))
                stack.enter_context(mock.patch.object(
                    harness_mod, "cached_efforts_for", lambda _one: None))
                stack.enter_context(mock.patch.object(
                    harness_mod.HarnessResearcher, "_run", scripted))
            for module, name in ((tasks, "_local_asker"),):
                original = getattr(module, name)
                stack.enter_context(mock.patch.object(
                    module, name, _capturing(original, captured)))
            import app.providers as providers

            stack.enter_context(mock.patch.object(
                providers, "harness_researcher",
                _capturing(providers.harness_researcher, captured)))
            try:
                result = tasks.quick_look(settings, params, cast("Progress", progress))
            except Exception as exc:  # noqa: BLE001 - a failed trial is a measurement
                error = f"{type(exc).__name__}: {exc}"
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        researcher = captured.get("researcher")
        sources = getattr(researcher, "sources", None)
        observation = checks.Observation(
            task=task, result=result, reply=str(captured.get("reply") or ""),
            shown=dict(sources) if isinstance(sources, dict) else None,
            queries=tuple(web.queries), search_languages=frozenset(web.languages),
            pages_opened=tuple(web.opened), kind=info["kind"], settings=effective,
            requested_effort=str(getattr(researcher, "requested_effort", "") or ""),
            requested_model=str(getattr(researcher, "requested_model", "") or ""),
            effort_settled=str(getattr(researcher, "effort_settled", "") or ""),
            harness_id=info["harness_id"], error=error)
        graded = checks.grade(observation)
        return {
            "task": task["id"], "dimension": task.get("dimension", ""),
            "agent": agent, "rep": rep, "profile": profile,
            "resolved": checks.resolved(graded) and not error,
            "error": error,
            "checks": [one.as_dict() for one in graded],
            "claims": checks.delivered_ids(observation),
            "measure": {
                "ms": elapsed_ms,
                "tokens": getattr(researcher, "tokens_used", None),
                "usd": getattr(researcher, "spent", None)
                if getattr(researcher, "cost_basis", "") == "per_token" else None,
                "delivered": len(result.get("risks") or []),
                "refused": int(result.get("dropped") or 0),
                "pages_shown": len(observation.shown) if observation.shown is not None else None,
                "pages_fetched": len(web.opened),
                "searches": len(web.searches),
            },
            # The trajectory: enough to see what happened without re-running it.
            "trajectory": {
                "queries": list(web.queries), "opened": list(web.opened),
                "prompt": (captured["prompts"] or [""])[0][:6000],
                "reply": observation.reply[:6000],
                "delivered": [{"title": one.get("title"), "sources": one.get("sources")}
                              for one in result.get("risks") or []],
                "log": list(progress.lines)[-60:],
                "effort": observation.requested_effort, "model": observation.requested_model,
            },
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _capturing(factory, captured: dict):
    """The agent factory, remembering the agent it built and what it replied.

    The reply is wrapped on `ask_quick`, the one door a quick look answers
    through, so the raw answer is graded before Kriko's gate touched it.
    """
    def build(*args, **kwargs):
        researcher = factory(*args, **kwargs)
        captured["researcher"] = researcher
        ask = getattr(researcher, "ask_quick", None)
        if callable(ask):
            def ask_quick(*a, **k):
                reply = ask(*a, **k)
                captured["reply"] = reply
                return reply
            researcher.ask_quick = ask_quick
        return researcher
    return build


def run_bench(tasks_: list[dict], agents: list[str], *, reps: int = 3, profile: str = "reader",
              reader_state: Path | None = None, timeout: float = TRIAL_TIMEOUT_SECONDS,
              on_trial=None) -> dict:
    """Every task by every agent, `reps` times: the raw material of a report.

    An agent that cannot run is listed with its reason and is not scored, so it
    never counts as a failure it did not earn, and never as a pass.
    """
    from app.agentbench import suite as suite_mod

    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {', '.join(PROFILES)}")
    runnable, skipped = [], {}
    for agent in agents:
        try:
            classify(agent)
            runnable.append(agent)
        except AgentUnavailable as why:
            skipped[agent] = str(why)
    trials = []
    for task in tasks_:
        for agent in runnable:
            for rep in range(1, max(1, reps) + 1):
                trial = run_trial(task, agent, rep=rep, profile=profile,
                                  reader_state=reader_state, timeout=timeout)
                trials.append(trial)
                if on_trial is not None:
                    on_trial(trial)
    suite = suite_mod.load()
    return {"suite": {"id": suite["id"], "version": suite["version"]},
            "profile": profile, "reps": max(1, reps), "agents": runnable,
            "skipped": skipped, "tasks": [one["id"] for one in tasks_], "trials": trials}
