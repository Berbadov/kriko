"""A researched product's saved check, made or refreshed on the engine.

The window used to build a product's identity itself and post it to
`/api/lookup`, which saved a new row every time. This door takes only the
product, reads its identity from the catalog, and keeps one saved check per
product (see `app/web/productchecks.py`).
"""

from fastapi import APIRouter, Depends, HTTPException

from app.web import productchecks
from app.web.deps import get_app_state, get_store

router = APIRouter(prefix="/api/products", tags=["products"])


@router.post("/{subject_id}/check")
def check_product(subject_id: str, app_state=Depends(get_app_state),
                  store=Depends(get_store)) -> dict:
    try:
        return productchecks.ensure_check(app_state, store, subject_id)
    except productchecks.ProductNotFound as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
