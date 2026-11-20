"""Saved cost estimates: equipment lines from installed catalogs, the vendor
quotes behind each line, and the forecast assumptions under them.

The Estimate screen builds these; accountants and capital managers read them.
State lives in `app.sqlite` (`state.estimates`), never in the knowledge store:
an estimate names subjects but is not knowledge - no pack reads it, and
uninstalling a pack leaves it standing. Export to Excel/CSV happens in the
window from this same payload, so what the reader saves is exactly what the
file contains.

Money rules, stated here because every screen and export depends on them:

* A quote carries its own currency and VAT rate, and says whether the number
  typed is net or gross. Nothing is guessed: a quote with no currency is the
  estimate's currency, and a quote with no rate uses the estimate's default.
* `fx` is TRY per one unit of each currency, TCMB's own direction. A manual
  table and a fetched bulletin are the same shape; `source` says which.
* The selected quote drives the line total and the forecast. Other quotes are
  compared beside it, never added to it.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import quoterisk
from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/estimates", tags=["estimates"])


class EstimateQuote(BaseModel):
    quote_id: str = Field(default="", max_length=64)
    vendor: str = Field(default="", max_length=200)
    seller: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=1000)
    unit_price: float | None = Field(default=None, ge=0)
    currency: str = Field(default="", max_length=8)
    vat_rate: float = Field(default=20.0, ge=0, le=100)
    vat_included: bool = False
    delivery_days: int | None = Field(default=None, ge=0, le=3650)
    warranty_months: int | None = Field(default=None, ge=0, le=600)
    quote_date: str = Field(default="", max_length=10)
    valid_until: str = Field(default="", max_length=10)
    note: str = Field(default="", max_length=state.ESTIMATE_NOTE_CHARS)
    selected: bool = False


class EstimateLine(BaseModel):
    subject_id: str = Field(default="", max_length=200)
    pack_id: str = Field(default="", max_length=100)
    label: str = Field(default="", max_length=300)
    quantity: int = Field(default=1, ge=1, le=1_000_000)
    unit_price: float | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=state.ESTIMATE_NOTE_CHARS)
    #: straight_line | declining_balance | vuk.
    depreciation: str = Field(default="straight_line", max_length=24)
    life_years: int | None = Field(default=None, ge=1, le=50)
    salvage: float | None = Field(default=None, ge=0)
    #: The rate read off GİB's published list for the VUK method, percent.
    vuk_rate: float | None = Field(default=None, ge=0, le=100)
    quotes: list[EstimateQuote] = Field(default_factory=list,
                                        max_length=state.ESTIMATE_MAX_QUOTES)


class EstimateWrite(BaseModel):
    """Every field optional except the lines: a save always carries the whole
    board, because lines are replaced rather than merged."""

    estimate_id: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=state.ESTIMATE_NAME_CHARS)
    currency: str = Field(default="USD", max_length=8)
    years: int = Field(default=5, ge=1, le=30)
    maintenance_pct: float = Field(default=5.0, ge=0, le=100)
    discount_pct: float = Field(default=8.0, ge=0, le=100)
    vat_rate: float = Field(default=20.0, ge=0, le=100)
    fx: dict[str, float | str] = Field(default_factory=dict)
    lines: list[EstimateLine] = Field(default_factory=list,
                                      max_length=state.ESTIMATE_MAX_LINES)


def _decorated(estimate: dict) -> dict:
    """The saved estimate plus what a reader needs to judge each quote.

    Risk and landed-cost rank are computed on read from the same pure
    functions every other surface uses, so a change to `sellers.json` shows up
    here without a migration, and nothing is frozen into the saved row.
    """
    currency = estimate.get("currency") or "USD"
    rates = estimate.get("fx") or {}
    today = date.today()
    for line in estimate.get("lines", []):
        quotes = line.get("quotes") or []
        risks = {q.get("quote_id"): quoterisk.quote_risk(q, today=today) for q in quotes}
        for quote in quotes:
            quote["risk"] = risks.get(quote.get("quote_id"))
        ranking = quoterisk.rank_quotes(
            quotes, estimate_currency=currency, rates=rates, today=today)
        line["ranking"] = [
            {
                "quote_id": row.get("quote_id"),
                "rank": row.get("rank"),
                "landed": row.get("landed"),
                "reasons": row.get("rank_reasons", []),
            }
            for row in ranking
        ]
    return estimate


@router.get("")
def list_estimates(limit: int = 100, conn=Depends(get_app_state)) -> dict:
    return {"items": state.list_estimates(conn, limit=limit)}


@router.post("")
def save_estimate(body: EstimateWrite, conn=Depends(get_app_state)) -> dict:
    try:
        estimate = state.save_estimate(conn, body.model_dump())
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, f"this estimate cannot be saved: {exc}") from exc
    return {"estimate": _decorated(estimate)}


@router.get("/{estimate_id}")
def read_estimate(estimate_id: str, conn=Depends(get_app_state)) -> dict:
    found = state.get_estimate(conn, estimate_id)
    if found is None:
        raise HTTPException(404, f"no estimate {estimate_id}")
    return {"estimate": _decorated(found)}


@router.delete("/{estimate_id}")
def remove_estimate(estimate_id: str, conn=Depends(get_app_state)) -> dict:
    if not state.delete_estimate(conn, estimate_id):
        raise HTTPException(404, f"no estimate {estimate_id}")
    return {"deleted": estimate_id}
