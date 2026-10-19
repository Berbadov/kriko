"""TypeSafe System One adapter used for opt-in product catalog choices.

This provider only transports one typed Choice request. Catalog roster
construction and answer validation live in ``app.categorizer`` so network
output never gets to name an arbitrary installed pack.
"""

from app import keys
from app.providers._http import TIMEOUT, post_json_or_why
from app.providers import MissingKey

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.14.0"


def evaluate(payload: dict, *, api_key: str | None = None,
             timeout: float = TIMEOUT) -> tuple[dict, str]:
    """Send a TypeSafe System One request and return its safe response/error."""
    try:
        token = str(api_key or keys.require("typesafe") or "").strip()
    except MissingKey:
        return {}, "Add a TypeSafe (Jev) key in Settings → Keys."
    if not token:
        return {}, "Add a TypeSafe API key in Settings → Keys."
    return post_json_or_why(
        ENDPOINT, payload, {"authorization": f"Bearer {token}"}, timeout=timeout,
    )
