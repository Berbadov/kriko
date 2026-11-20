"""Exchange rates for the Estimate screen, fetched only on a press."""

from fastapi import APIRouter, HTTPException

from app import fx

router = APIRouter(prefix="/api/fx", tags=["fx"])


@router.get("/tcmb")
def tcmb(force: bool = False) -> dict:
    try:
        return fx.today_rates(force=force)
    except Exception as exc:  # noqa: BLE001 - the screen needs a sentence, not a stack
        raise HTTPException(502, f"could not read today's TCMB rates: {exc}") from exc
