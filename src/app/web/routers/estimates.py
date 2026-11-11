"""Saved cost estimates: equipment lines from installed catalogs plus the
forecast assumptions behind them.

The Estimate screen builds these; accountants and capital managers read them.
State lives in `app.sqlite` (`state.estimates`), never in the knowledge store:
an estimate names subjects but is not knowledge — no pack reads it, and
uninstalling a pack leaves it standing. Export to Excel/CSV happens in the
window from this same payload, so what the reader saves is exactly what the
file contains.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/estimates", tags=["estimates"])


class EstimateLine(BaseModel):
    subject_id: str = Field(default="", max_length=200)
    pack_id: str = Field(default="", max_length=100)
    label: str = Field(default="", max_length=300)
    quantity: int = Field(default=1, ge=1, le=1_000_000)
    unit_price: float | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=state.ESTIMATE_NOTE_CHARS)


class EstimateWrite(BaseModel):
    """Every field optional except the lines: a save always carries the whole
    board, because lines are replaced rather than merged."""

    estimate_id: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=state.ESTIMATE_NAME_CHARS)
    currency: str = Field(default="USD", max_length=8)
    years: int = Field(default=5, ge=1, le=30)
    maintenance_pct: float = Field(default=5.0, ge=0, le=100)
    discount_pct: float = Field(default=8.0, ge=0, le=100)
    lines: list[EstimateLine] = Field(default_factory=list,
                                      max_length=state.ESTIMATE_MAX_LINES)


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
    return {"estimate": estimate}


@router.get("/{estimate_id}")
def read_estimate(estimate_id: str, conn=Depends(get_app_state)) -> dict:
    found = state.get_estimate(conn, estimate_id)
    if found is None:
        raise HTTPException(404, f"no estimate {estimate_id}")
    return {"estimate": found}


@router.delete("/{estimate_id}")
def remove_estimate(estimate_id: str, conn=Depends(get_app_state)) -> dict:
    if not state.delete_estimate(conn, estimate_id):
        raise HTTPException(404, f"no estimate {estimate_id}")
    return {"deleted": estimate_id}
