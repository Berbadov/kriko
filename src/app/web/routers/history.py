"""Past answers, so a reload is not a loss.

Reads and writes `app.sqlite` only. Nothing here touches the knowledge store,
and nothing here changes a ranking — this router is the UI's memory, not the
engine's.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import followup
from app.web import state, tasks
from app.web.deps import get_app_state, get_jobs, get_store

router = APIRouter(prefix="/api", tags=["history"])


def label_for(identity: dict, fallback: str = "lookup") -> str:
    """A human-readable name for a lookup.

    Built from whatever the pack's identity keys happen to be: the engine has
    no title for a query, and this must stay true for any category, so the
    values are joined in the order the caller sent them rather than picked by
    name. Naming a key here would be the hardcoded-list bug in a new place.
    """
    values = [str(v) for v in identity.values() if str(v).strip()]
    return " ".join(values) or fallback


@router.get("/history")
def history(
    limit: int = Query(20, ge=1, le=200),
    app_state=Depends(get_app_state),
    store=Depends(get_store),
    q: str = "",
    offset: int = 0,
):
    """Recent checks, each with the category its pack names (B182).

    The category is the name of the pack that answered, read from the engine
    store at request time so a renamed or uninstalled pack is reflected
    rather than frozen into a stored row. A check no pack answered has an
    empty category, and the screen names that group itself.
    """
    q = q.strip()[:200]
    offset = max(0, offset)
    items = state.recent(app_state, limit, query=q, offset=offset)
    names = {
        row["pack_id"]: row["name"]
        for row in store.execute("SELECT pack_id, name FROM packs")
    }
    for item in items:
        ids = item.pop("pack_ids")
        subject_ids = item.pop("subject_ids")
        if not ids and subject_ids:
            # A check that matched a product but found no risk names no pack
            # in its claims; the product it matched still belongs to one.
            marks = ",".join("?" * len(subject_ids))
            ids = [
                row["pack_id"]
                for row in store.execute(
                    "SELECT DISTINCT pack_id FROM subjects"
                    f" WHERE subject_id IN ({marks}) ORDER BY pack_id",
                    subject_ids,
                )
            ]
        item["packs"] = [{"pack_id": i, "name": names[i]} for i in ids if i in names]
        item["category"] = item["packs"][0]["name"] if item["packs"] else ""
    return {"items": items, "offset": offset, "has_more": len(items) == limit}


@router.get("/history/records")
def history_records(request: Request, limit: int = Query(200, ge=1, le=1000),
                    app_state=Depends(get_app_state), store=Depends(get_store)):
    """Checks, agent runs, queue entries and pack builds with explicit kinds."""
    checks = history(min(limit, 200), app_state, store)["items"]
    items = [{**row, "kind": "check", "status": "succeeded", "agent": ""} for row in checks]
    names = {row["pack_id"]: row["name"] for row in store.execute("SELECT pack_id, name FROM packs")}
    jobs = state.list_jobs(app_state, limit)
    catalogs = []
    if any(one["kind"] == "quick_look" and one["state"] == state.SUCCEEDED for one in jobs):
        try:
            from app import categorizer

            profiles = categorizer.installed_catalogs(request.app.state.settings.store_path)
            catalogs = [{"pack_id": one["pack_id"], "name": one["name"],
                         "enabled": one["enabled"], "editable": one["editable"]}
                        for one in profiles]
        except Exception:  # noqa: BLE001 - history stays readable if definitions cannot be loaded
            profiles = []
    else:
        profiles = []
    for job in jobs:
        params, result = job["params"], job.get("result") or {}
        pack = str(params.get("pack_id") or result.get("pack_id") or "")
        assignment = None
        category = names.get(pack, "")
        if job["kind"] == "quick_look" and job["state"] == state.SUCCEEDED:
            assignment = state.quicklook_category(app_state, job["job_id"])
            from app import categorizer

            fresh = categorizer.deterministic(
                str(params.get("product") or result.get("product") or ""),
                result, profiles,
            )
            profiles_by_id = {one["pack_id"] for one in profiles}
            missing_target = bool(
                assignment and assignment.get("status") == "assigned"
                and assignment.get("pack_id") not in profiles_by_id
            )
            if (assignment is None or missing_target
                    or (assignment.get("status") != "assigned"
                        and fresh["status"] == "assigned")):
                assignment = state.save_quicklook_category(
                    app_state, job["job_id"], fresh,
                )
            if assignment["status"] == "assigned":
                category = assignment["pack_name"] or names.get(assignment["pack_id"], "")
                pack = assignment["pack_id"]
            else:
                category = str(result.get("category") or "")
        items.append({"lookup_id": "job:" + job["job_id"], "created_at": job["created_at"],
                      "label": params.get("product") or params.get("category") or params.get("subject_id") or job["kind"],
                      "source": job["kind"], "kind": "pack_build" if job["kind"] == "pack_build" else "run",
                      "status": job["state"], "agent": result.get("harness") or params.get("harness") or params.get("backend", ""),
                      "claim_count": len(result.get("risks") or []), "category": category,
                      "packs": [{"pack_id": pack, "name": names.get(pack, category or pack)}] if pack else [],
                      "categorization": assignment if job["kind"] == "quick_look" else None})
    for queued in state.queue_history(app_state):
        items.append({"lookup_id": "queue:" + queued["queue_id"], "created_at": queued["added_at"],
                      "label": queued["name"], "source": queued["url"], "kind": "queue",
                      "status": queued["state"], "agent": "", "claim_count": 0, "category": "", "packs": []})
    items.sort(key=lambda row: (row["created_at"], row["lookup_id"]), reverse=True)
    return {"items": items[:limit], "categorization_catalogs": catalogs}


class ManualCategoryRequest(BaseModel):
    pack_id: str = Field(min_length=1, max_length=200)


def _quicklook_job(conn, job_id: str) -> dict:
    job = state.get_job(conn, job_id)
    if not job or job["kind"] != "quick_look":
        raise HTTPException(404, f"no saved quick look {job_id}")
    if job["state"] != state.SUCCEEDED:
        raise HTTPException(409, "The quick look must finish before it can be categorized.")
    return job


@router.post("/quick-looks/{job_id}/categorize")
def categorize_saved_quick_look(job_id: str, request: Request,
                                app_state=Depends(get_app_state), runner=Depends(get_jobs)):
    """Ask the configured agent to classify one saved look, using no web search."""
    look = _quicklook_job(app_state, job_id)
    from app import categorizer

    profiles = categorizer.installed_catalogs(request.app.state.settings.store_path)
    if not profiles:
        raise HTTPException(409, "No installed catalogs are available to classify this look.")
    for one in state.list_jobs(app_state, 200):
        if (one["kind"] == "categorize_quick_look" and not one["done"]
                and one["params"].get("quick_job_id") == job_id):
            return {"job_id": one["job_id"], "kind": one["kind"], "quick_job_id": job_id}
    params = look["params"]
    job_params = {
        "quick_job_id": job_id,
        "backend": params.get("backend") or "",
        "harness": params.get("harness") or "",
        "model": params.get("model") or "",
        "timeout_seconds": params.get("timeout_seconds") or 0,
        "budget_usd": tasks.CATEGORIZATION_BUDGET_USD,
    }
    try:
        new_job = runner.submit("categorize_quick_look", job_params)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"job_id": new_job, "kind": "categorize_quick_look", "quick_job_id": job_id}


@router.post("/quick-looks/{job_id}/category")
def assign_saved_quick_look_category(job_id: str, body: ManualCategoryRequest,
                                     request: Request,
                                     app_state=Depends(get_app_state)):
    """Save the reader's catalog choice after automatic classification abstains."""
    _quicklook_job(app_state, job_id)
    from app import categorizer

    profiles = categorizer.installed_catalogs(request.app.state.settings.store_path)
    assignment = categorizer.manual(body.pack_id, profiles)
    if assignment is None:
        raise HTTPException(422, "Choose an installed catalog from the list.")
    return state.save_quicklook_category(app_state, job_id, assignment)


@router.get("/lookup/{lookup_id}")
def get_lookup(lookup_id: str, app_state=Depends(get_app_state)):
    row = state.get_lookup(app_state, lookup_id)
    if row is None:
        raise HTTPException(404, f"no such lookup: {lookup_id}")
    return row


class FollowupRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@router.get("/lookup/{lookup_id}/questions")
def lookup_questions(lookup_id: str, app_state=Depends(get_app_state)):
    if state.saved_answer(app_state, lookup_id) is None:
        raise HTTPException(404, f"no such lookup: {lookup_id}")
    return {"items": state.lookup_questions(app_state, lookup_id)}


@router.post("/lookup/{lookup_id}/questions")
def ask_lookup(lookup_id: str, body: FollowupRequest,
               app_state=Depends(get_app_state), runner=Depends(get_jobs)):
    if state.saved_answer(app_state, lookup_id) is None:
        raise HTTPException(404, f"no such lookup: {lookup_id}")
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "Write a question first.")
    params = {"lookup_id": lookup_id, "question": question,
              "backend": tasks.default_backend(runner.settings.app_state_path),
              "budget_usd": tasks.DEFAULT_BUDGET_USD,
              "max_tokens": followup.MAX_TOKENS}
    return {"job_id": runner.submit("lookup_ask", params), "kind": "lookup_ask"}


@router.delete("/history/{lookup_id}")
def forget(lookup_id: str, app_state=Depends(get_app_state)):
    if not state.delete_lookup(app_state, lookup_id):
        raise HTTPException(404, f"no such lookup: {lookup_id}")
    return {"deleted": True, "lookup_id": lookup_id}


class SettingsPatch(BaseModel):
    """Whatever the interface wants remembered.

    Free-form on purpose: `mode` is the only key today, and the backend has no
    business knowing that buyer/author exist — the projection is a frontend
    concern (see the design doc, decision 3). A typed field per preference
    would make every new UI toggle a backend change.
    """

    values: dict = Field(default_factory=dict)


@router.get("/settings")
def read_settings(app_state=Depends(get_app_state)):
    return state.all_settings(app_state)


@router.post("/settings")
def write_settings(body: SettingsPatch, app_state=Depends(get_app_state)):
    return state.put_settings(app_state, body.values)


