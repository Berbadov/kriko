"""The reader as a buyer: a profile, a ledger, fit, and a committed pick.

Reads and writes `app.sqlite` only. Nothing here touches the knowledge store,
and nothing here changes a ranking of claims: this router is the reader's own
memory of what they need and what they bought (`app/buyer.py`), and the
decision Kriko makes from it (`app/pick.py`, `app/advice.py`).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import advice, audit, buyer, pick, pricewatch
from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/buyer", tags=["buyer"])


class ProfileRequest(BaseModel):
    about: str = Field(default="", max_length=4000)
    budget: dict = Field(default_factory=dict)
    must: list[str] | str = Field(default_factory=list)
    avoid: list[str] | str = Field(default_factory=list)
    prefer: list[str] | str = Field(default_factory=list)
    distrust: list[str] | str = Field(default_factory=list)
    priorities: dict = Field(default_factory=dict)


@router.get("/profile")
def read_profile(conn=Depends(get_app_state)) -> dict:
    profile = buyer.read(conn)
    return {"profile": profile, "empty": buyer.is_empty(profile),
            "priorities": list(buyer.PRIORITIES), "tally": buyer.tally(conn),
            "brief": buyer.brief(conn)}


@router.put("/profile")
def write_profile(body: ProfileRequest, conn=Depends(get_app_state)) -> dict:
    profile = buyer.save(conn, body.model_dump())
    return {"profile": profile, "empty": buyer.is_empty(profile)}


class PurchaseRequest(BaseModel):
    name: str = Field(max_length=300)
    url: str = Field(default="", max_length=2000)
    price: float | str | None = None
    currency: str = Field(default="", max_length=8)
    ask_after_days: int = Field(default=buyer.ASK_AFTER_DAYS, ge=1, le=365)


@router.get("/purchases")
def list_purchases(conn=Depends(get_app_state)) -> dict:
    return {"items": buyer.purchases(conn), "due": buyer.due(conn), "tally": buyer.tally(conn),
            "record": pick.track_record(conn)}


@router.post("/purchases")
def add_purchase(body: PurchaseRequest, conn=Depends(get_app_state)) -> dict:
    """"I bought this". Kriko asks how it went after `ask_after_days`."""
    try:
        return buyer.record_purchase(conn, body.name, url=body.url, price=body.price,
                                     currency=body.currency, ask_after_days=body.ask_after_days)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


class AnswerRequest(BaseModel):
    verdict: str
    reason: str = Field(default="", max_length=600)


@router.post("/purchases/{purchase_id}/answer")
def answer_purchase(purchase_id: str, body: AnswerRequest, conn=Depends(get_app_state)) -> dict:
    try:
        row = buyer.answer(conn, purchase_id, body.verdict, body.reason)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if row is None:
        raise HTTPException(404, f"no purchase {purchase_id}")
    return row


@router.post("/purchases/{purchase_id}/snooze")
def snooze_purchase(purchase_id: str, conn=Depends(get_app_state)) -> dict:
    if not buyer.snooze(conn, purchase_id):
        raise HTTPException(404, f"no unanswered purchase {purchase_id}")
    return {"snoozed": purchase_id}


@router.delete("/purchases/{purchase_id}")
def forget_purchase(purchase_id: str, conn=Depends(get_app_state)) -> dict:
    if not buyer.forget_purchase(conn, purchase_id):
        raise HTTPException(404, f"no purchase {purchase_id}")
    return {"deleted": purchase_id}


class FitItem(BaseModel):
    name: str = Field(default="", max_length=400)
    text: str = Field(default="", max_length=2000)
    price: float | str | None = None
    currency: str = Field(default="", max_length=8)
    seller: str = Field(default="", max_length=200)


class FitRequest(BaseModel):
    items: list[FitItem] = Field(max_length=60)


@router.post("/fit")
def fit_items(body: FitRequest, conn=Depends(get_app_state)) -> dict:
    """How each product on a results page sits against what the reader said they need.

    Cheap and local: words and numbers against the profile, no model. A reader
    with no profile gets `profile: false` and nothing to draw.
    """
    profile = buyer.read(conn)
    if buyer.is_empty(profile):
        return {"profile": False, "items": []}
    return {"profile": True, "items": [
        buyer.fit(profile, name=one.name, text=one.text, price=one.price,
                  currency=one.currency, seller=one.seller) for one in body.items]}


class PickRequest(BaseModel):
    lookup_ids: list[str] = Field(default_factory=list, max_length=8)
    draft_id: str = Field(default="", max_length=64)
    #: Every queued product that has a saved answer.
    queue: bool = False


def stored_answers(conn, body: PickRequest) -> list[dict]:
    ids = list(body.lookup_ids)
    if body.draft_id:
        draft = state.get_compare_draft(conn, body.draft_id)
        if not draft:
            raise HTTPException(404, f"no draft {body.draft_id}")
        ids += draft["lookup_ids"]
    if body.queue:
        ids += [one["lookup_id"] for one in state.research_queue(conn) if one["lookup_id"]]
    seen: list[str] = []
    for one in ids:
        if one and one not in seen:
            seen.append(one)
    return [stored for stored in (state.saved_answer(conn, one) for one in seen[:8]) if stored]


@router.post("/pick")
def pick_now(body: PickRequest, conn=Depends(get_app_state)) -> dict:
    """The shortlist ranked for this reader, and a winner, with no agent involved."""
    answers = stored_answers(conn, body)
    if not answers:
        raise HTTPException(422, "no saved checks to rank: add products to the shortlist first")
    return pick.rank(conn, answers)


class AdviceRequest(PickRequest):
    mode: str = "pick"
    question: str = Field(default="", max_length=600)
    harness: str = Field(default="", max_length=200)
    backend: str = Field(default="harness", pattern="^(harness|local)$")


@router.post("/advice")
def advise(body: AdviceRequest, request: Request, conn=Depends(get_app_state)) -> dict:
    """Start the job that says the decision well: `pick`, `debate`, `tco` or `timing`."""
    if body.mode not in advice.MODES:
        raise HTTPException(422, f"mode is one of {', '.join(advice.MODES)}")
    answers = stored_answers(conn, body)
    needed = 2 if body.mode in ("pick", "debate") else 1
    if len(answers) < needed:
        raise HTTPException(422, f"{body.mode} needs {needed} saved check"
                                 f"{'s' if needed > 1 else ''}; add products to the shortlist first")
    job_id = request.app.state.jobs.submit("buyer_advice", {
        "mode": body.mode, "question": body.question, "harness": body.harness,
        "backend": body.backend, "lookup_ids": [one["lookup_id"] for one in answers]})
    return {"job_id": job_id, "kind": "buyer_advice", "mode": body.mode}


@router.get("/picks/record")
def picks_record(conn=Depends(get_app_state)) -> dict:
    return pick.track_record(conn)


class PageRequest(BaseModel):
    """A scraped page, as `/api/analyze` takes it. Only what a purchase needs is read."""
    url: str = Field(max_length=2000)
    fields: dict = Field(default_factory=dict)
    title: str = Field(default="", max_length=600)
    description: str = Field(default="", max_length=6000)
    product_name: str = Field(default="", max_length=300)


@router.post("/page")
def page_as_a_purchase(body: PageRequest, conn=Depends(get_app_state)) -> dict:
    """What Kriko can say about this page as a purchase: price memory, audit, fit, watch.

    Read off the scrape and the reader's own rows, so it is the same for a page
    no pack knows. A separate call from `/api/analyze` on purpose: a price
    verdict is true on the day the page was read and a profile changes when the
    reader edits it, so neither belongs in an answer the extension caches for
    hours or the app saves for good. Calling it also remembers the page's price.
    """
    name = (body.product_name or body.title.split(" | ")[0]).strip()[:300]
    out: dict = {"price": None, "audit": None, "fit": None, "watch": None, "profile": False,
                 "name": name}
    offer = pricewatch.observe(conn, body.url, name, body.fields)
    if offer:
        out["price"] = pricewatch.judge(conn, body.url, offer)
        out["price"]["series"] = pricewatch.series(conn, body.url)[-60:]
        out["price"]["elsewhere"] = [
            {"host": one["host"], "url": one["url"], "price": one["price"], "currency": one["currency"]}
            for one in pricewatch.elsewhere(conn, name, body.url, offer.get("currency", ""))[:3]]
    out["watch"] = pricewatch.watch_for(conn, body.url)
    listing = audit.listing(url=body.url, title=body.title or name, description=body.description,
                            fields=body.fields)
    # A page that says nothing worth flagging carries no audit at all.
    out["audit"] = listing if (listing["flags"] or listing["claims"]["items"]
                               or listing["reviews"]) else None
    profile = buyer.read(conn)
    if not buyer.is_empty(profile):
        out["profile"] = True
        text = " ".join(str(value) for value in body.fields.values())
        out["fit"] = buyer.fit(
            profile, name=name, text=f"{body.title} {body.description} {text}",
            price=(offer or {}).get("price"), currency=(offer or {}).get("currency", ""),
            seller=listing["seller"]["signals"].get("seller_name", ""))
    return out


@router.get("/privacy")
def what_is_kept(request: Request, conn=Depends(get_app_state)) -> dict:
    """What Kriko remembers about the reader as a buyer, where, and that none of it leaves this computer."""
    return {**buyer.holdings(conn), "where": str(request.app.state.settings.app_state_path),
            "leaves_this_computer": False,
            "note": "Kept in a file on this computer. Nothing here is sent anywhere. Your agent "
                    "sees your profile only when you ask it something, and only the part a "
                    "question needs."}


@router.delete("/privacy/{what}")
def forget(what: str, conn=Depends(get_app_state)) -> dict:
    """Forget one kind of it (`profile`, `purchases`, `prices`, `watches`, `picks`) or `everything`."""
    try:
        return {"forgotten": what, "rows": buyer.forget(conn, what)}
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
