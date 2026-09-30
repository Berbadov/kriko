"""The unattended run, and the way back out of one.

Four surfaces, and the third is the reason the first two are allowed to exist:

* `GET /api/research-planes` says which planes exist and what each one costs.
* `POST /api/agenda/run` walks the agenda without being told what to research.
* `GET /api/research-runs` says what each run cost and what it added.
* `GET /api/usage` adds the sums up, which no per-run row can answer.
* `GET|PUT /api/schedule` is the unattended loop, off until it is turned on.
* `DELETE /api/research-runs/{id}` takes a run's claims back out.

The order matters. An unattended multi-row run that could not be reversed would
be a liability rather than a feature — a reader who lets it loose and dislikes
the result has to trust the claims or hand-delete them one by one — so the undo
landed before the loop that needs it, and both live here rather than in
`routers/jobs.py` because they are one story.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AliasChoices, BaseModel, Field

from app import prefs
from app.web import observability, schedule, state
from app.web.deps import get_app_state, get_jobs

router = APIRouter(prefix="/api", tags=["research"])


#: What each plane is for, in the reader's terms. The engine's `cost_basis`
#: is accurate and says nothing — "per_token" is not an answer to "what will
#: this cost me" — so the sentence lives here, where the interface's words
#: belong, beside the machine-readable value rather than instead of it.
PLANE_WORDS = {
    "harness": (
        "Kriko runs your coding agent for you, headlessly, and files what it "
        "finds. Costs nothing beyond the subscription you already pay for, "
        "and needs the agent's command-line tool installed."
    ),
    "agent": (
        "You do the run yourself: Kriko writes the brief, your agent reads it "
        "through the MCP server and files the findings back. Costs nothing "
        "beyond your subscription, and needs a harness connected on the "
        "Wiring tab."
    ),
    "api": (
        "Kriko searches and reads by itself, unattended. Costs money per run, "
        "capped by a budget you set, and needs both keys below."
    ),
    "local": (
        "Kriko searches and reads with services on this machine — a local "
        "SERP for search and a local inference server for reading. Costs "
        "nothing and needs no keys; needs OpenSERP on 127.0.0.1:7000 and an "
        "OpenAI-compatible server (llama-server, Ollama) on 127.0.0.1:8080."
    ),
}


def local_endpoints() -> dict:
    """Whether this machine's own services answer, and where they were sought.

    The probe is one HEAD with a one-second timeout per service, in a thread,
    because the planes screen is not allowed to hang on a service that is
    down — which is the normal state of a box where OpenSERP has not been
    started yet. The card stays up either way; `ready` only dims it, and the
    two rows say which half is missing so the fix is one command.
    """
    from concurrent.futures import ThreadPoolExecutor

    import urllib.request

    from app.providers import llm, openserp

    def _answers(url: str) -> bool:
        try:
            urllib.request.urlopen(url, timeout=1.0)
            return True
        except Exception:  # noqa: BLE001 - a down service is an answer, not an error
            return False

    inference = (llm._env("LLM_BASE_URL", "http://127.0.0.1:8080")).rstrip("/")
    serp = openserp.DEFAULT_BASE_URL
    with ThreadPoolExecutor(max_workers=2) as pool:
        inference_up = pool.submit(_answers, inference).result()
        serp_up = pool.submit(_answers, serp).result()
    missing = [
        name for name, up in (("the inference server", inference_up),
                              ("the SERP", serp_up)) if not up
    ]
    return {
        "ready": inference_up and serp_up,
        "reason": "" if not missing else "not running: " + " and ".join(missing),
        "inference_url": inference,
        "serp_url": serp,
    }


@router.get("/research-planes")
def list_planes(
    request: Request, llm: str = "", search: str = "", harness: str = "",
    conn=Depends(get_app_state),
) -> dict:
    """The planes knowledge gets built on, and whether each one can run now.

    Read off the researcher classes rather than restated in the frontend, for
    the same reason `/api/pipeline/runs` hands over its stage labels: a second
    copy of a vocabulary is a second place to forget when it changes. What the
    interface adds is the sentence and the readiness — `cost_basis` is the
    engine's word and the reader's question is "can I press this".

    Returns no key and no hint. `/api/keys` is the only surface that describes
    what is stored, and even that one returns only a masked tail.
    """
    from app.providers import harness as harness_mod
    from app.providers.harness import HarnessResearcher
    from kriko.research import AgentResearcher, ApiResearcher, LocalPlane

    selection = prefs.effective(conn, model=llm, search=search, harness=harness)
    installed = harness_mod.available()
    planes = []
    for cls in (HarnessResearcher, AgentResearcher, ApiResearcher, LocalPlane):
        row = {
            "id": cls.name,
            "cost_basis": cls.cost_basis,
            "what": PLANE_WORDS.get(cls.name, ""),
            # The `agent` plane's readiness is a *harness config* question,
            # which `/api/agent-targets` already answers and this must not
            # second-guess. The other two have a prerequisite this router can
            # see: a key, or an executable on PATH.
            "ready": True,
            "needs_keys": cls.name == "api",
        }
        if cls.name == "api":
            row.update(ready=selection["ready"], reason=selection["reason"],
                       llm=selection["llm"], search=selection["search"])
        if cls.name == "local":
            row.update(local_endpoints())
        if cls.name == "harness":
            row.update(ready=selection["harness_ready"],
                       selected_harness=selection["harness"],
                       reason=selection["harness_note"])
            # Named, not counted. "no coding-agent CLI found" is answerable
            # only if the reader knows which names were looked for.
            # The resolved path, not just the name. A reader whose PATH does
            # not carry `claude` still has one on disk, and `locate` finds it
            # (see its docstring) — but "Kriko found a harness" and "Kriko
            # found *this* binary" are different sentences, and only the
            # second one can be checked against what they installed.
            # Each installed harness carries its model choice: what is stored
            # for it, what the CLI itself offers, and whether a choice is
            # even drivable. A model dropdown without this is a guess with
            # a text field — the reader asked for Sonnet vs Haiku vs Opus
            # *by name*, and the names live with the CLI, not in Kriko.
            lists = harness_mod.models_for_each(installed)
            # The API agents (B153) in the same two lists, so the run screen
            # offers the one the reader keyed in the same picker as a CLI.
            api_rows, api_missing = prefs.api_agent_rows(conn)
            row["harnesses"] = [
                {
                    "id": h.id,
                    "label": h.label,
                    "command": h.executable,
                    "path": harness_mod.locate(h),
                    "needs_account": h.needs_account,
                    # `llm` on the wire, `model` in the code: the frontend
                    # may not name a pack's identity keys, and one of them
                    # is "model" (see SERVED_AS in routers/bench.py).
                    "llm": prefs.for_harness(conn, h.id),
                    "llms": lists.get(h.id, []),
                    "llms_note": harness_mod.models_note(h, lists.get(h.id, [])),
                    "llm_hint": h.model_hint,
                    # `model_env` counts, for the reason `app/prefs.py` gives
                    # at the same expression: Mistral Vibe has no `--model`,
                    # its switch is an environment variable. Keyed on the flag
                    # alone, Settings offered the picker and both *run* screens
                    # hid it — so the harness a reader added to stop spending
                    # Claude tokens could not be given a model where it is
                    # actually launched. Two copies of one expression is how
                    # they came to disagree; a test now asserts the two
                    # endpoints answer the same for every harness.
                    "llm_selectable": bool(h.model_flag or h.model_env),
                    # The second dial, served here too. Settings could set an
                    # effort and neither run screen could, which made it a
                    # preference the reader had to leave the run to change.
                    "effort": prefs.effort_for_harness(conn, h.id),
                    "efforts": harness_mod.efforts_for(h),
                    "effort_hint": h.effort_hint,
                }
                for h in installed
            ] + api_rows
            row["looked_for"] = [h.executable for h in harness_mod.KNOWN]
            # Missing, with somewhere to go: a name and a command are not
            # actionable, a download page and an install command are. The
            # account line is the cost answer — every headless run bills to
            # a subscription, quota or key the reader already holds.
            installed_ids = {h.id for h in installed}
            row["missing"] = [
                {
                    "id": h.id,
                    "label": h.label,
                    "command": h.executable,
                    "download_url": h.download_url,
                    "install_hint": h.install_hint,
                    "needs_account": h.needs_account,
                }
                for h in harness_mod.KNOWN
                if h.id not in installed_ids and not h.unusable
            ] + api_missing
            # The manual path: where Kriko looked beyond PATH, and the one
            # variable that adds another directory to that search.
            from pathlib import Path as _Path

            row["dirs_env"] = harness_mod.DIRS_ENV
            row["search_dirs"] = [
                str(_Path.home() / part) for part in harness_mod.KNOWN[0].homes
            ]
            # Installed, found, and deliberately not driven — with the reason.
            # "My opencode is installed, why isn't Kriko using it" is a fair
            # question and silence is not an answer to it: `opencode run` has
            # no flag that restricts which tools the agent may use, and the
            # allowlist is the reason this plane is allowed to exist.
            row["unusable"] = [
                {"id": h.id, "label": h.label, "command": h.executable,
                 "path": harness_mod.locate(h), "why": h.unusable}
                for h in harness_mod.found_but_unusable()
            ]
        planes.append(row)
    # The plane an unnamed run resolves to on this machine, so the screen can
    # mark it rather than making the reader guess which button is the default.
    from app.web.tasks import default_backend

    return {"planes": planes,
            "default": default_backend(
                getattr(request.app.state.settings, "app_state_path", None))}


def resolve_research_subject(store, *, q: str = "", subject_id: str = "") -> dict:
    from kriko.lookup import find

    q, subject_id = q.strip(), subject_id.strip()
    if bool(q) == bool(subject_id):
        raise HTTPException(422, "provide exactly one of q or subject_id")
    if subject_id:
        matches = [dict(row) for row in store.execute(
            "SELECT s.subject_id, s.pack_id, s.label FROM subjects s"
            " JOIN packs p USING (pack_id)"
            " WHERE s.subject_id = ? AND p.enabled = 1",
            (subject_id,),
        )]
    else:
        matches = find.search(store, q, limit=20)
    if not matches:
        raise HTTPException(404, "no installed subject matches this product")
    if len(matches) != 1:
        raise HTTPException(409, {
            "message": "choose a specific subject before researching",
            "items": matches,
        })
    return {key: matches[0][key] for key in ("subject_id", "pack_id")}


class AgendaRunRequest(BaseModel):
    #: How far down the agenda to go. Small by default: this is the button
    #: pressed by somebody who is not watching.
    rows: int = Field(10, ge=1, le=100)
    pack_id: str | None = None
    #: Empty means "the best free plane that can actually gather" —
    #: `tasks.default_backend()`, resolved at run time rather than frozen
    #: here, because whether a coding-agent CLI is installed is a fact about
    #: the machine and can change between two presses of the button. The
    #: unattended door is still the last place a default should start
    #: *spending*: `api` is never chosen by omission.
    backend: str = ""
    #: The ceiling for the whole run, not per row. Zero on the `api` plane is
    #: replaced by `tasks.DEFAULT_AGENDA_BUDGET_USD` rather than meaning
    #: unlimited — see the note there.
    budget_usd: float = Field(0.0, ge=0.0, le=100.0)
    max_documents: int = Field(5, ge=1, le=50)
    model: str = Field("", max_length=200, validation_alias=AliasChoices("model", "llm"))
    harness: str = Field("", max_length=64)
    search: str = Field("", max_length=64)


@router.post("/agenda/run")
def start_agenda_run(body: AgendaRunRequest, runner=Depends(get_jobs)) -> dict:
    return {
        "job_id": runner.submit("agenda_run", body.model_dump()),
        "kind": "agenda_run",
    }


class ScheduleRequest(BaseModel):
    """The unattended loop, as the reader sets it.

    Every field optional: the screen saves the one control the reader touched,
    and a PUT that had to carry all six would make a partial save silently
    reset the rest.
    """

    enabled: bool | None = None
    every_hours: float | None = Field(None, ge=schedule.MIN_HOURS, le=24 * 30)
    rows: int | None = Field(None, ge=1, le=100)
    #: Not validated against a list here — `schedule.decide` refuses an
    #: unknown plane by name, and one place to refuse is better than two that
    #: can disagree.
    plane: str | None = None
    budget_usd: float | None = Field(None, ge=0.0, le=100.0)
    max_documents: int | None = Field(None, ge=1, le=50)


@router.get("/schedule")
def read_schedule(app_state=Depends(get_app_state)) -> dict:
    """What the loop is set to, and what it last did.

    The history is returned even when the loop is off, because "it ran four
    times and the last one kept nothing" is precisely what a reader wants to
    see *after* switching it off.
    """
    return schedule.status(app_state)


@router.put("/schedule")
def write_schedule(
    body: ScheduleRequest, request: Request, app_state=Depends(get_app_state)
) -> dict:
    """Save it, and start or stop the thread to match.

    Applied to the running process rather than only stored, because a setting
    that needs a restart to take effect is a setting a reader will conclude is
    broken. Turning it off stops the thread; turning it on starts one, and
    the first tick still waits out the startup grace.
    """
    stored = {
        key: value
        for key, value in body.model_dump().items()
        if value is not None
    }
    merged = {**schedule.settings_for(app_state), **stored}
    state.put_settings(app_state, {schedule.KEY: merged})

    loop = getattr(request.app.state, "schedule", None)
    if loop is not None:
        if schedule.settings_for(app_state)["enabled"]:
            loop.start()
        else:
            loop.stop()
    return schedule.status(app_state)


@router.post("/schedule/check")
def check_schedule(request: Request, app_state=Depends(get_app_state)) -> dict:
    """Run one tick now, and say what it decided.

    The manual half of an automatic feature, and the reason it exists is
    trust: a reader who turns on a loop that will next act in twenty-four
    hours has no way to find out whether it *would* act. This returns the same
    sentence the loop would have recorded — including the refusals, which are
    the answers worth having.
    """
    loop = getattr(request.app.state, "schedule", None)
    if loop is None:
        raise HTTPException(503, "this process has no scheduler")
    decision = loop.tick(from_timer=False)
    return {
        "ran": decision.run,
        "reason": decision.reason,
        "due_at": decision.due_at,
        **schedule.status(app_state),
    }


@router.get("/research-runs")
def list_runs(
    limit: int = Query(50, ge=1, le=200), app_state=Depends(get_app_state)
) -> dict:
    """Provenance, newest first: plane, model, provider, spend, claims still in.

    `claims` is counted rather than stored, so a run that has been undone reads
    as zero here instead of still advertising what it once added.
    """
    return {"runs": state.research_runs(app_state, limit)}


@router.get("/usage")
def read_usage(request: Request, app_state=Depends(get_app_state)) -> dict:
    """Everything this installation has spent, and everything it was asked.

    Two halves, because a reader asking "what has this cost me" is asking
    about both and neither half can answer alone. `research` sums the runs
    that wrote claims *in*; `analyses` counts the lookups that read them back
    *out*, off the JSONL log whose contents nothing reachable has ever read.
    Together they are the only place the ratio is visible: a hundred analyses
    served by four runs is a very different installation from four analyses
    served by a hundred.

    Nothing here is computed from a guess. A plane that cannot count leaves
    its column null all the way to the wire, and `metered_runs` says how many
    of the runs behind a total were counted at all — see
    `state.usage_totals`.
    """
    return {
        "research": state.usage_totals(app_state),
        "analyses": observability.summarise(
            request.app.state.settings.analysis_log_path
        ),
    }


@router.get("/research-runs/{run_id}")
def read_run(run_id: str, app_state=Depends(get_app_state)) -> dict:
    run = state.get_research_run(app_state, run_id)
    if run is None:
        raise HTTPException(404, f"no research run {run_id}")
    claims = state.run_claims(app_state, run_id)
    return {
        **run,
        "claims_detail": claims,
        # The one thing a screen must not do is offer an undo that would do
        # nothing. A run whose claims are all gone says so instead.
        "undoable": any(not item["removed_at"] for item in claims),
    }


@router.delete("/research-runs/{run_id}")
def undo_run(run_id: str, app_state=Depends(get_app_state), runner=Depends(get_jobs)):
    """Start the undo. A job, because it writes once per claim.

    Refused up front for a run that does not exist — a 404 is the honest
    answer, and queuing a job that will immediately fail would report the
    mistake as a failed run instead of as a bad request.
    """
    if state.get_research_run(app_state, run_id) is None:
        raise HTTPException(404, f"no research run {run_id}")
    return {
        "job_id": runner.submit("research_undo", {"run_id": run_id}),
        "kind": "research_undo",
    }
