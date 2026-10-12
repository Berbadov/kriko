"""Setting a key, and never reading one back.

Three endpoints and a hard rule: **no response body from this router may
contain a key.** Not on success, not in a validation message, not in an
exception. `test_the_keys_endpoint_never_returns_a_key` asserts it by putting a
known string in and searching every response — including the error paths — for
it, because the leak that matters is the one in the message nobody reads.

`app/keys.py` holds the storage and the masking; this file is only the door.
"""

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import keys

router = APIRouter(prefix="/api/keys", tags=["keys"])


class KeyWrite(BaseModel):
    #: A dict of `{provider_id: key}`, and only the providers `app/keys.py`
    #: declares — anything else is ignored rather than written. See the note on
    #: `PROVIDERS` for why this is not a free-form environment write.
    values: dict[str, str] = Field(default_factory=dict)


def _path(request: Request):
    """The env file beside this app's store, not a fixed ~/.kriko.

    Derived from `Settings.app_state_path`'s parent so a test pointed at a
    temporary home writes there — the alternative is a test suite that puts
    fixture keys in the developer's real `~/.kriko/env`.
    """
    settings = request.app.state.settings
    return keys.env_path(getattr(settings, "app_state_path").parent)


@router.get("")
def read(request: Request) -> dict:
    """Which providers have a key, where it came from, and its last four."""
    items = keys.status(_path(request))
    return {
        "providers": items,
        # Not `all(item["present"] ...)`: that would require *every* search
        # provider present, including the optional ones, so setting Tavily up
        # would have made a previously-ready installation report itself not
        # ready until Exa was added too. `keys.ready()` is the real question —
        # any one search key, and every non-optional key.
        "ready": keys.ready(_path(request)),
        "path": str(_path(request)),
    }


@router.put("")
def write(request: Request, body: KeyWrite) -> dict:
    """Store one or more keys. Blank values are ignored, not destructive.

    A form that submits every field on every save would otherwise clear a key
    the reader never touched — the screen cannot show them, so it cannot round
    -trip them either. Clearing is `DELETE`.
    """
    unknown = [
        name for name in (body.values or {}) if name.strip().lower() not in keys.BY_ID
    ]
    if unknown:
        # The provider *names* are safe to echo; the values never are.
        raise HTTPException(400, f"unknown provider(s): {', '.join(sorted(unknown))}")
    # Normalised once: `keys.save` matches provider ids case-insensitively,
    # so the echo back into `os.environ` below must resolve the same way.
    values = {str(k).strip().lower(): str(v) for k, v in (body.values or {}).items()}
    written = keys.save(values, _path(request))
    # Straight into this process's environment as well, overwriting: the
    # adapters read `os.environ`, and a key saved in Settings that only takes
    # effect after a restart is a key the reader will conclude did not save.
    # `keys.load` deliberately does not overwrite — that is its precedence
    # rule — so a fresh paste is set here explicitly.
    for provider_id in written:
        os.environ[keys.BY_ID[provider_id].env] = values[provider_id].strip()
    return {"saved": written, **read(request)}


@router.delete("/{provider_id}")
def forget(request: Request, provider_id: str) -> dict:
    if provider_id.strip().lower() not in keys.BY_ID:
        raise HTTPException(404, f"unknown provider {provider_id}")
    removed = keys.remove(provider_id, _path(request))
    return {"removed": removed, **read(request)}
