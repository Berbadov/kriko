"""Running a proposed app action that spends the reader's credits.

Only one action reaches this door: `start_quick_look`. It is proposed by the
agent as a card and submitted here only after the reader presses Start. The
agent cannot call this route, and a web page's text cannot either: the model's
tool vocabulary only proposes, and the card is the reader's consent.

`remember` and `open` do not need a job. `remember` is already written when the
tool runs; `open` is performed by the window.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import agentactions
from app.agentledger import RequestConflict
from app.web.deps import get_jobs

router = APIRouter(prefix="/api", tags=["agent-actions"])

#: The actions that may be started here. A closed set: this is not a general
#: job-submission door, and every entry has a proposal the screen already drew.
RUNNABLE = {"start_quick_look"}


class AgentActionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    arguments: dict = Field(default_factory=dict)
    client_request_id: str = Field(default="", max_length=200)


@router.post("/agent-actions")
def run_agent_action(body: AgentActionRequest, runner=Depends(get_jobs)) -> dict:
    if body.name not in RUNNABLE:
        raise HTTPException(400, "that action is not runnable from this endpoint")
    if body.name == "start_quick_look":
        proposal = agentactions.start_quick_look(
            product=str(body.arguments.get("product") or ""),
            page_url=str(body.arguments.get("page_url") or ""),
        )
        if proposal["status"] != "proposed" or not isinstance(proposal.get("action"), dict):
            raise HTTPException(422, str(proposal.get("note") or "the Quick Look proposal is not valid"))
        action = proposal["action"]
        params = {
            "product": str(action["params"].get("product") or ""),
            "page_url": str(action["params"].get("page_url") or ""),
            # Empty harness/backend: the Quick Look resolves the reader's saved
            # agent the same way the extension's own button does.
            "harness": "",
            "backend": "",
            "budget_usd": 0.0,
        }
        try:
            if body.client_request_id:
                job_id = runner.submit("quick_look", params,
                                       client_request_id=body.client_request_id)
            else:
                job_id = runner.submit("quick_look", params)
        except RequestConflict as error:
            raise HTTPException(409, str(error)) from error
        except KeyError as error:
            raise HTTPException(400, str(error)) from error
        return {"job_id": job_id, "kind": "quick_look", "action": action}
    raise HTTPException(400, "that action is not implemented")
