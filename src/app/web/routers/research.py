"""The unattended run, and the way back out of one.

Three surfaces, and the last is the reason the others are allowed to exist:

* `GET /api/research-planes` says which planes exist and what each one costs.
* `GET /api/research-runs` says what each run cost and what it added.
* `GET /api/usage` adds the sums up, which no per-run row can answer.
* `DELETE /api/research-runs/{id}` takes a run's claims back out.

The order matters. An unattended multi-row run that could not be reversed would
be a liability rather than a feature — a reader who lets it loose and dislikes
the result has to trust the claims or hand-delete them one by one — so the undo
landed before the loop that needs it, and both live here rather than in
`routers/jobs.py` because they are one story.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app import prefs
from app.web import observability, state
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
        "Kriko reads with a model running on this computer (Ollama, LM Studio "
        "or llama-server, with a model downloaded) and searches through a "
        "search service on this machine when one answers, otherwise through "
        "Exa's free hosted search. Costs nothing and needs no keys."
    ),
}


def local_endpoints(app_state_path=None) -> dict:
    """Whether this machine can run the local plane, and how it was found.

    Asked of the machine every time, by `app.localplane.resolve`: the servers
    at their conventional loopback addresses plus the configured one, each
    with the model list it reports itself, and which search is in use. The
    probes are short and side by side because the planes screen is not allowed
    to hang on a server that is down, which is the normal state of a box where
    none has been started yet. `ready` is false with a `reason` that says what
    to do, and the card stays up either way.
    """
    from app import localplane

    return localplane.resolve(app_state_path)


@router.get("/local-plane")
def local_plane(request: Request) -> dict:
    """The local machine plane's status, for Settings and the planes card,
    with what the reader has saved so the form can show it."""
    from app import localplane

    path = getattr(request.app.state.settings, "app_state_path", None)
    return {**local_endpoints(path), "stored": localplane.stored(path)}


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
            row.update(local_endpoints(
                getattr(request.app.state.settings, "app_state_path", None)))
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
    # The local plane is listed first while it is ready (B172): it is the one an
    # unnamed run uses then, and a list should open on what will run.
    planes.sort(key=lambda one: not (one["id"] == "local" and one.get("ready")))
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
