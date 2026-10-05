"""Getting a model onto this machine, for the local plane.

A `POST` starts a `model_pull` job: a download is minutes of work and may be
gigabytes, so it is a row with progress and cancel like every other long
operation. Only Ollama can be driven over HTTP; the other runtimes get a plain
refusal that says where to get a model instead of a button that cannot work.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import modelpull
from app.web.deps import get_jobs

router = APIRouter(prefix="/api", tags=["local-models"])

#: Names the reader may hear in a refusal, for runtimes this app knows of.
_OTHER = {"lmstudio": "LM Studio", "llamacpp": "llama.cpp"}


class PullRequest(BaseModel):
    runtime: str = "ollama"
    model: str


@router.get("/local-models")
def local_models(request: Request) -> dict:
    """The models Ollama holds, with its own sizes; empty when it is not up.

    Other servers list names only (`/api/local-plane`), so this answers for
    the one runtime that reports more.
    """
    base = modelpull.ollama_base(request.app.state.settings.app_state_path)
    return {
        "runtime": "ollama" if base else None,
        "url": base or None,
        "models": modelpull.installed(base) if base else [],
    }


@router.post("/local-models/pull")
def pull_model(body: PullRequest, runner=Depends(get_jobs)) -> dict:
    runtime = body.runtime.strip().lower()
    model = body.model.strip()
    if runtime != "ollama":
        name = _OTHER.get(runtime, runtime or "that runtime")
        raise HTTPException(
            400, f"Kriko downloads models through Ollama only. Get the model in {name}.")
    if not modelpull.valid_name(model):
        raise HTTPException(422, "That is not a model name Ollama would accept.")
    job_id = runner.submit("model_pull", {"runtime": "ollama", "model": model})
    return {"job_id": job_id, "kind": "model_pull"}
