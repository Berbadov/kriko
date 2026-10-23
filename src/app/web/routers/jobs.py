"""Starting, watching and stopping the two operations that grow a pack.

The router owns no logic — the handlers are in `app/web/tasks.py` and the state
machine is in `app/web/state.py`. What it owns is the promise G6's delivery
constraint makes: a durable id comes back immediately, the status is readable
afterwards even across a restart, and a failure arrives as a message rather
than as silence.

A client that wants to follow a job polls `GET /api/jobs/{job_id}`. The row is
the single source of the truth, so a client that reconnects mid-job sees it.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AliasChoices, BaseModel, Field

from app import prefs
from app.agentledger import RequestConflict
from app.web import livefeed, state, tasks
from app.web.deps import get_app_state, get_jobs

router = APIRouter(prefix="/api", tags=["jobs"])


class ResearchRequest(BaseModel):
    client_request_id: str = Field("", max_length=200)
    subject_id: str
    pack_id: str | None = None
    #: Empty means `tasks.default_backend()`: the best plane that is free
    #: *and* can actually gather. It was `agent`, which gathers nothing by
    #: design, so on a machine with a coding-agent CLI installed the Research
    #: button rendered a brief and reported success — the reader's "run
    #: nothing again". Resolved at run time, because whether a CLI is
    #: installed is a fact about the machine, not about this schema.
    #:
    #: The rule that survives unchanged: a button that quietly starts
    #: *spending money* is a button people stop pressing. `api` is still
    #: never chosen by omission.
    backend: str = ""
    budget_usd: float = 0.0
    #: `0` means "whatever the scale says", and that is why the default is not
    #: 5 any more. A truthy default silently won over every preset, so the dial
    #: would have moved the label and nothing else — the exact bug where a
    #: control appears to work and does not.
    max_documents: int = Field(0, ge=0, le=50)
    #: How deep to go: `quick` | `standard` | `deep` | `custom`.
    #:
    #: One name instead of four numbers, and the numbers still work — an
    #: explicit `max_documents` or `budget_usd` wins over whatever the preset
    #: proposes, because the dial is a bundle of these knobs rather than a wall
    #: around them. Empty means the default, and an unknown name means the
    #: default too: a request from an older client, or with a typo, should run
    #: rather than be refused.
    scale: str = Field("", max_length=32)
    model: str = Field("", max_length=200, validation_alias=AliasChoices("model", "llm"))
    harness: str = Field("", max_length=64)
    search: str = Field("", max_length=64)
    #: Which kinds of source to go to first (`prefs.SOURCE_KINDS`); empty
    #: means the Agents tab's stored choice.
    source_kinds: list[str] = Field(default_factory=list, max_length=12)


class UpdateRequest(BaseModel):
    #: Empty means "everything the index has something newer for". Naming one
    #: pack is the exception, not the shape of the operation.
    pack_id: str | None = None
    index_url: str | None = None


class CatalogDraftRequest(BaseModel):
    category: str = Field(min_length=1, max_length=500)
    harness: str = Field(default="", max_length=200)


@router.post("/packs/author")
def author_catalog(body: CatalogDraftRequest, runner=Depends(get_jobs)):
    """Research a data-only draft. Installing it is a separate reader action."""
    return _submit(runner, "pack_author", {"category": body.category.strip(), "harness": body.harness})


@router.post("/agents/check")
def check_agent(runner=Depends(get_jobs)):
    return _submit(runner, "agent_check", {})


def _submit(runner, kind: str, params: dict) -> dict:
    try:
        request_id = params.pop("client_request_id", "")
        job_id = (runner.submit(kind, params, client_request_id=request_id) if request_id
                  else runner.submit(kind, params))
    except RequestConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"job_id": job_id, "kind": kind}


@router.post("/research")
def start_research(body: ResearchRequest, runner=Depends(get_jobs)):
    params = body.model_dump()
    selected = str(params.get("harness") or "").strip()
    if (selected != prefs.LOCAL_PICK and selected
            and str(params.get("backend") or "harness") in ("", "harness")):
        from app import keys
        from app.providers import apiagent, harness
        settings = runner.settings
        app_home = settings.app_state_path.parent
        available = ({agent.id for agent in harness.available()}
                     | {agent.id for agent in apiagent.available(
                         keys.env_path(app_home), shared_home=app_home)})
        if selected not in available:
            raise HTTPException(503, f"The selected research agent is unavailable: {selected}")
    if params.get("harness") == prefs.LOCAL_PICK:
        # The Local model row is a plane, not a CLI: naming it as a harness
        # would fall back to whichever CLI is installed (`resolve_agent`).
        params.update(harness="", backend="local")
    return _submit(runner, "research", params)


@router.get("/packs/updates")
def check_pack_updates(
    index_url: str | None = Query(default=None),
    fresh: bool = Query(default=False),
    runner=Depends(get_jobs),
):
    """Is anything newer? Answered in the request — it is one small fetch.

    `fresh` is the reader's own "Check for updates" press; every other caller
    (the hint bar on every screen) leaves it false and gets the server's
    cached answer instead of paying for a round trip to a remote index on
    every navigation — see `tasks.check_updates`.
    """
    return tasks.check_updates(runner.settings, index_url or "", fresh=fresh)


@router.post("/packs/harvest")
def start_harvest(runner=Depends(get_jobs)):
    """File every finished quick look into the catalog that holds its product. No agent."""
    return _submit(runner, "pack_harvest", {"install": True})


@router.post("/packs/update")
def start_update(body: UpdateRequest, runner=Depends(get_jobs)):
    return _submit(runner, "pack_update", body.model_dump())


@router.post("/agents/{agent_id}/install")
def install_agent(agent_id: str, runner=Depends(get_jobs)):
    """Install this agent for the reader (or, for `local`, Ollama and a small model)."""
    from app import agentinstall

    if not agentinstall.can_install(agent_id):
        raise HTTPException(404, f"there is no one-click install for {agent_id!r}")
    return _submit(runner, "agent_install", {"agent_id": agent_id})


@router.get("/jobs")
def list_jobs(
    limit: int = Query(30, ge=1, le=200),
    app_state=Depends(get_app_state),
    runner=Depends(get_jobs),
):
    # Decorated here too, not only on the single-job read: the Jobs screen
    # builds its list from this, so without it a reload is what makes an
    # unanswered question disappear. The scheduler's counts ride along, so the
    # screen can say "2 running of 4 at once" beside the rows.
    return {"items": [_with_attention(row)
                      for row in state.list_jobs(app_state, limit)],
            **runner.concurrency()}


def _with_attention(row: dict) -> dict:
    """Mark a job that has put something to the reader.

    "If the agent is waiting on my answer, that must be unmissable." It is not
    *waiting* — the identification pass states its defaults and carries on, by
    design (`app/disambiguate.py`) — but it is the one thing on the screen
    worth looking at, and a question rendered as another log line is a question
    nobody answers.

    Derived here rather than stored, because the questions are already in the
    job's own partial result and a second copy is a second thing to keep in
    step. It survives the run finishing: the answers make the *next* run exact,
    so they are worth offering beside "run it again" long after this one ended.
    """
    result = row.get("result") or {}
    questions = result.get("questions") if isinstance(result, dict) else None
    row["attention"] = {
        "kind": "questions",
        "count": len(questions),
        "say": (
            f"{len(questions)} question(s) about what this is — it carried on "
            f"with its own answers. Yours would make the next run exact."
        ),
        "questions": questions,
    } if isinstance(questions, list) and questions else None
    # B176: the dark panel's events, only while the run is live. A finished
    # run's panel is its log, and fifty finished rows should not each carry a
    # second copy of it.
    if not row.get("done"):
        row["feed"] = livefeed.feed_of(row.get("log") or "")
    return row


@router.get("/jobs/{job_id}")
def get_job(job_id: str, app_state=Depends(get_app_state)):
    row = state.get_job(app_state, job_id)
    if row is None:
        raise HTTPException(404, f"no such job: {job_id}")
    return _with_attention(row)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, runner=Depends(get_jobs)):
    outcome = runner.cancel(job_id)
    if outcome is None:
        raise HTTPException(404, f"no such job: {job_id}")
    return {"job_id": job_id, "state": outcome}


class SayRequest(BaseModel):
    """A line for a job that is still running."""

    text: str = ""


@router.post("/jobs/{job_id}/say")
def say_to_job(job_id: str, body: SayRequest, app_state=Depends(get_app_state)):
    """Answer a run while it is running.

    The gap B120 named and left open: the prompt went in once and the
    transcript came out, so a run that paused on a question could be watched
    and stopped and nothing else. This is the reply path, and it is the same
    shape as cancel — a row the running handler reads between steps, because
    the handler is a thread in this process and this request arrives on
    another.

    `delivered: false` rather than a 409 when the run has already ended. The
    reader was answering a question that stopped mattering while they typed;
    that is not a mistake to refuse them for, but they must not be told it
    landed.
    """
    if state.get_job(app_state, job_id) is None:
        raise HTTPException(404, f"no such job: {job_id}")
    delivered = state.say_to_job(app_state, job_id, body.text)
    return {"job_id": job_id, "delivered": delivered}


class RetryRequest(BaseModel):
    """What the reader adds when running it again.

    `answers` is the return path for `_with_attention`'s questions, keyed by
    question id. It is optional and the body itself is optional, so the plain
    "run it again" button keeps posting nothing — this endpoint gained a way
    to carry answers without gaining a requirement to.

    Deliberately a *new run* rather than a resumption of the old one: the
    identification pass never blocked on the answer (see `app/disambiguate.py`),
    so there is no paused run to resume. The answers make the next run exact,
    which is the only thing they were ever able to do.
    """

    answers: dict[str, str] = Field(default_factory=dict)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, body: RetryRequest | None = None,
              app_state=Depends(get_app_state), runner=Depends(get_jobs)):
    """Run the same work again, as a new row.

    A new job rather than a reset of the old one: the failed attempt's log is
    the only record of *why* it failed, and reusing the row would delete the
    evidence at the exact moment someone is looking into it. The two are linked
    by `retry_of` in the new job's params, so the pair stays readable.

    Refused while the original is still going — "retry" on a running job means
    the reader wanted to cancel it, and quietly starting a second copy of a
    research run is how you get two writers on one subject.
    """
    row = state.get_job(app_state, job_id)
    if row is None:
        raise HTTPException(404, f"no such job: {job_id}")
    if not row["done"]:
        raise HTTPException(409, f"job {job_id} is still {row['state']}")
    params = dict(row["params"] or {})
    params["retry_of"] = job_id
    # Merged onto whatever the first run was given, so answering one question
    # does not discard the answers of an earlier round.
    given = {key: value for key, value in (body.answers if body else {}).items()
             if str(value).strip()}
    if given:
        params["answers"] = {**(params.get("answers") or {}), **given}
    try:
        child = runner.retry(row["kind"], params)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"job_id": child, "kind": row["kind"]}


