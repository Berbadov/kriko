"""Follow-up questions about a shortlist, asked of the reader's own agent.

The Compare screen lines up checks the reader already has; what it never let
them do is ask the question the table raises — "which of these has the
cheaper known fix" — anywhere but in their head. A question is a job rather
than a request because it runs an agent that may search for a few minutes,
and because the answer is worth outliving the page: it is stored beside the
comparison it was about, so reopening the draft reopens the conversation.

The brief is assembled from the stored answers themselves, never from the
engine: each check's own claims and specifications are passed through
verbatim, so a question about any category works without this layer knowing
any category (G6). Nothing the agent replies is filed as knowledge — this is
the reader's own decision support, not a submission path, and it writes only
to `app.sqlite`.
"""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.web import state
from app.agentledger import RequestConflict
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/compare-drafts", tags=["compare"])


def _why_agent_cannot_run(harness_id: str, app_home) -> str:
    """Why a named agent cannot run here, in the engine's own words.

    Compare offers the agents this engine listed, so this refusal is reached
    when a named one stopped being offerable between that list and the press —
    an agent uninstalled, a key removed — or when an interface names one
    directly. Either way the reader is owed the reason and the way out, in the
    vocabulary they can act on: a missing key, a trial used up, a CLI not
    installed. This asks the engine's own resolver for that sentence rather
    than writing a second copy of it here, so an agent added to either roster
    is explained without an edit.
    """
    from app import keys
    from app.providers import apiagent, harness as harness_mod

    row = apiagent.BY_ID.get(harness_id)
    if row is not None:
        # The key resolver's own refusal, which already distinguishes a key
        # that was never saved from a trial that is used up (`sharekeys`).
        for provider in (row.key, *row.also_needs):
            try:
                keys.require(provider, shared_home=app_home)
            except Exception as error:  # noqa: BLE001 — the reason is the reply
                return f"{row.label} cannot run here: {error}"
        return f"{row.label} cannot run here. {row.install_hint}"
    cli = next((one for one in harness_mod.KNOWN if one.id == harness_id), None)
    if cli is not None:
        return f"{cli.label} is not installed here. {cli.install_hint}".strip()
    return f"The selected research agent is unavailable: {harness_id}"


def _require_selected_agent(request: Request, backend: str, harness: str) -> None:
    """A named pick must be runnable on this installation before queueing."""
    from app import keys, localplane, prefs
    from app.providers import apiagent, harness as harness_mod

    path = request.app.state.settings.app_state_path
    if backend == "local":
        if harness and harness != prefs.LOCAL_PICK:
            raise HTTPException(422, "Choose the Local agent for the local research plane.")
        plan = localplane.resolve(path, with_search=False)
        if not plan.get("ready"):
            raise HTTPException(503, "The selected local agent is unavailable. "
                                + str(plan.get("reason") or "Start a local model first."))
        return
    if harness == prefs.LOCAL_PICK:
        raise HTTPException(422, "The Local agent requires backend='local'.")
    if harness:
        # resolve_agent deliberately falls back to another installed CLI.
        # A named choice is a contract, so compare against exact IDs here.
        api_ids = {agent.id for agent in apiagent.available(
            keys.env_path(path.parent), shared_home=path.parent)}
        cli_ids = {agent.id for agent in harness_mod.available()}
        if harness not in (api_ids | cli_ids):
            raise HTTPException(503, _why_agent_cannot_run(harness, path.parent))

class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    harness: str = Field(default="", max_length=200)
    backend: Literal["harness", "local"] = "harness"
    client_request_id: str = Field(default="", max_length=200)


@router.get("/{draft_id}/questions")
def list_questions(draft_id: str, conn=Depends(get_app_state)) -> dict:
    return {"items": state.compare_questions(conn, draft_id)}


@router.post("/{draft_id}/questions")
def ask_question(
    draft_id: str, body: QuestionRequest,
    request: Request, conn=Depends(get_app_state),
) -> dict:
    """Store the question, then start the job that answers it.

    The row is written before the job is submitted, so a question asked the
    moment before a crash is a row that says "asked", not a question that
    never existed. The job's params carry the question id; its handler writes
    the answer back onto that row when the agent replies.
    """
    if not state.get_compare_draft(conn, draft_id):
        raise HTTPException(404, f"no draft {draft_id}")
    request_id = f"compare:{body.client_request_id}" if body.client_request_id else ""
    request_payload = {
        "draft_id": draft_id, "question": body.question.strip(),
        "harness": body.harness, "backend": body.backend}
    if request_id:
        prior = conn.execute(
            "SELECT input_json, record_id FROM question_requests WHERE request_id=?",
            (request_id,)).fetchone()
        if prior:
            canonical = json.dumps(request_payload, sort_keys=True, ensure_ascii=False)
            if prior["input_json"] != canonical:
                raise HTTPException(409, "This request ID was already used for a different question.")
            existing = next((one for one in state.compare_questions(conn, draft_id)
                             if one["question_id"] == prior["record_id"]), None)
            if existing and existing.get("job_id"):
                return {**existing, "kind": "compare_ask"}
    _require_selected_agent(request, body.backend, body.harness)
    try:
        record_id = state.reserve_question(conn, request_id, request_payload)
        question = state.record_compare_question(
            conn, draft_id, body.question.strip(), question_id=record_id)
    except RequestConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    runner = request.app.state.jobs
    try:
        params = {
            "draft_id": draft_id,
            "question_id": question["question_id"],
            "question": question["question"],
            "harness": body.harness,
            "backend": body.backend,
        }
        job_id = (runner.submit("compare_ask", params, client_request_id=request_id)
                  if request_id else runner.submit("compare_ask", params))
    except KeyError as exc:  # pragma: no cover - the handler is registered
        raise HTTPException(400, str(exc)) from exc
    state.set_compare_question_job(
        conn, draft_id, question["question_id"], job_id)
    return {**question, "job_id": job_id, "kind": "compare_ask"}


class ProductResearchRequest(BaseModel):
    lookup_id: str = Field(min_length=1, max_length=200)
    #: Empty is the engine's own "you choose" pick, the same shape a question
    #: may already send (`QuestionRequest.harness` defaults to ""). It has to be
    #: allowed: a column whose stored agent is not on this machine offers the
    #: reader a press that asks the engine to resolve one, and the engine's
    #: answer — the fallback it made, or the key, trial or install it is
    #: missing — is the only honest answer to that press. A refusal here would
    #: replace that sentence with a validation error.
    harness: str = Field(default="", max_length=200)
    backend: Literal["harness", "local"] = "harness"
    client_request_id: str = Field(default="", max_length=200)


@router.post("/{draft_id}/research")
def research_product(
    draft_id: str, body: ProductResearchRequest,
    request: Request, conn=Depends(get_app_state),
) -> dict:
    """Run a fresh quick look for one saved Compare product.

    A shortlist can contain catalog checks or quick looks. Both resolve through
    saved_answer, so every column gets the same research action and the result
    is an ordinary durable quick-look job the client can poll and add to the
    draft after it succeeds.
    """
    draft = state.get_compare_draft(conn, draft_id)
    if not draft:
        raise HTTPException(404, f"no draft {draft_id}")
    if body.lookup_id not in draft["lookup_ids"]:
        raise HTTPException(404, f"product {body.lookup_id} is not in this comparison")
    answer = state.saved_answer(conn, body.lookup_id)
    if answer is None:
        raise HTTPException(409, f"product {body.lookup_id} has no completed saved check")
    response = answer.get("response") or {}
    identity = response.get("identity") if isinstance(response, dict) else {}
    identity = identity if isinstance(identity, dict) else {}
    product = " ".join(str(
        (response.get("product") if isinstance(response, dict) else "")
        or identity.get("product") or identity.get("name") or identity.get("label")
        or answer.get("label") or "").split())
    assumed = " ".join(str((response.get("assumed") or "")
                            if isinstance(response, dict) else "").split())
    if assumed and assumed.casefold() not in product.casefold():
        product = f"{product} ({assumed})"
    if not product:
        raise HTTPException(409, f"product {body.lookup_id} has no name to research")
    listing = response.get("listing") if isinstance(response, dict) else {}
    listing = listing if isinstance(listing, dict) else {}
    page: dict = {
        "facts": listing.get("facts") if isinstance(listing.get("facts"), dict) else {},
        "description": str(listing.get("description") or ""),
    }
    page_url = str(listing.get("url") or "")
    params = {
        "product": product, "backend": body.backend, "harness": body.harness,
        "page": page, "page_url": page_url,
        "compare_draft_id": draft_id, "compare_lookup_id": body.lookup_id,
    }
    runner = request.app.state.jobs
    request_id = f"compare-product:{body.client_request_id}" if body.client_request_id else ""
    if request_id:
        prior = runner.ledger.lookup(client_request_id=request_id)
        if prior:
            expected = {"kind": "quick_look", "params": params}
            if prior["input"] != expected:
                raise HTTPException(409, "This request ID was already used for different product research.")
            return {"job_id": prior["job_id"], "kind": "quick_look", "draft_id": draft_id,
                    "lookup_id": body.lookup_id, "product": product,
                    "backend": body.backend, "harness": body.harness}
    current = state.get_compare_draft(conn, draft_id)
    if not current:
        raise HTTPException(404, f"no draft {draft_id}")
    if body.lookup_id not in current["lookup_ids"]:
        raise HTTPException(404, f"product {body.lookup_id} is not in this comparison")
    _require_selected_agent(request, body.backend, body.harness)
    try:
        job_id = (runner.submit("quick_look", params, client_request_id=request_id)
                  if request_id else runner.submit("quick_look", params))
    except RequestConflict as error:
        raise HTTPException(409, str(error)) from error
    except KeyError as error:
        raise HTTPException(400, str(error)) from error
    return {"job_id": job_id, "kind": "quick_look", "draft_id": draft_id,
            "lookup_id": body.lookup_id, "product": product,
            "backend": body.backend, "harness": body.harness}

