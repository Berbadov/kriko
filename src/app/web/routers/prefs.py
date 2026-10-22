"""What the reader chose, and what it costs.

Two endpoints, one screen. `app/prefs.py` holds the choices — which agent,
which model, which search provider — and `app/costs.py` holds what has been
spent and what the next run is likely to cost. They are served together
because at the moment of choosing a plane they are the same decision, and a
preference a reader sets without being shown the bill is how a surprise
happens.
"""

import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app import costs, evidence, prefs
from app.providers import local_runtimes, proxypool, websearch
from app.web.deps import get_app_state

router = APIRouter(prefix="/api", tags=["prefs"])


#: The longest a stored preference may be. One bound for all of them: every
#: value here is a short name — a harness id, a model id, an effort level.
VALUE_MAX = 200
#: The proxy pool is a list of addresses, so it cannot be a "short name".
POOL_MAX = 6000


class PrefsWrite(BaseModel):
    """Every field optional, and empty means "whatever the machine offers".

    Not a required set: a reader with one CLI installed should never have to
    name it, and an installation that has never opened this screen must behave
    exactly as it did before the screen existed.

    **The accepted keys are `prefs.KEYS`, not a list written out here.** They
    used to be a hand-written eleven, and that list named three harnesses out
    of five with no effort key at all — so a model chosen for Mistral Vibe or
    Gemini CLI was dropped by this schema before `prefs.write` ever saw it, and
    the effort dial was dead end to end. Nothing reported a failure: the screen
    re-renders from this endpoint's own reply, so it said "Saved." and then
    showed "CLI default" again.

    `app/prefs.py` derives its keys from the harness roster for exactly this
    reason — the stale copy simply lived one layer up, which is the failure
    mode `CLAUDE.md`'s scalability rule is about. Accepting extras and
    filtering to `prefs.KEYS` in the handler keeps the vocabulary just as
    closed as spelling it out did (`prefs.write` filters to the same set), and
    a harness added to the roster is storable the moment it exists.
    """

    model_config = ConfigDict(extra="allow")


@router.get("/prefs")
def read_prefs(fresh: bool = False, conn=Depends(get_app_state)) -> dict:
    """`fresh` re-asks each CLI for its model list instead of using the cache —
    the button a reader presses after signing in or updating a CLI."""
    return prefs.choices(conn, fresh=fresh)


@router.get("/agent-availability")
def agent_availability(conn=Depends(get_app_state)) -> dict:
    """The small agent roster needed by the shell while the app starts.

    The shell needs a default agent before the reader opens any settings. The
    full preferences document also discovers model lists and can start CLI and
    provider probes, so startup uses this filesystem/key-only view instead.
    Detailed model and capability discovery stays behind `/api/prefs`, which
    the reader opens from Settings.
    """
    from app.providers import apiagent, harness

    chosen = prefs.read(conn)
    rows = [
        {"id": one.id, "label": one.label, "local": False}
        for one in harness.available()
    ]
    rows.extend(
        {"id": one.id, "label": one.label, "local": False}
        for one in apiagent.available()
    )
    # Do not probe a local model server during startup. Keep a configured local
    # agent in the roster, including the one the reader already selected.
    if (chosen.get(prefs.HARNESS) == prefs.LOCAL_PICK
            or chosen.get(prefs.LOCAL_URL) or chosen.get(prefs.LOCAL_MODEL)):
        rows.append({"id": prefs.LOCAL_PICK, "label": "Local agent", "local": True})
    return {
        "harnesses": rows,
        "chosen": {prefs.HARNESS: chosen.get(prefs.HARNESS, "")},
    }


@router.put("/prefs")
def write_prefs(body: PrefsWrite, conn=Depends(get_app_state)) -> dict:
    """Store what the reader chose, and answer with what is now stored.

    The filter to `prefs.KEYS` is what keeps the key space closed now that the
    schema accepts extras — a browser on localhost still cannot write a row
    this installation does not define. The length bound moves here with it,
    since there is no per-field `max_length` left to carry it.
    """
    written = {
        key: str(value)[:POOL_MAX if key == prefs.PROXY_POOL else VALUE_MAX]
        for key, value in body.model_dump().items()
        if value is not None and key in prefs.KEYS
    }
    if prefs.SEARCH in written and written[prefs.SEARCH] not in {"", *websearch.KNOWN}:
        raise HTTPException(422, detail="search_provider must be one of: " + ", ".join(websearch.KNOWN))
    if prefs.SEARCH_FALLBACK in written:
        value = written[prefs.SEARCH_FALLBACK].strip().casefold()
        names = [] if value in {"", websearch.NONE} else [one.strip() for one in value.split(",")]
        if any(one not in websearch.KNOWN for one in names):
            raise HTTPException(
                422, detail="search_fallback must be empty, 'none' or a comma-separated list of: "
                + ", ".join(websearch.KNOWN))
        written[prefs.SEARCH_FALLBACK] = ",".join(dict.fromkeys(names)) if names else value
    if prefs.LOCAL_RUNTIME in written:
        known = {one["id"] for one in local_runtimes.runtimes()}
        if written[prefs.LOCAL_RUNTIME] not in {"", *known}:
            raise HTTPException(422, detail="local_runtime must be one of: " + ", ".join(sorted(known)))
    if prefs.LOCAL_URL in written and written[prefs.LOCAL_URL]:
        address = local_runtimes.valid_address(written[prefs.LOCAL_URL])
        if not address:
            raise HTTPException(
                422, detail="local_url must be an http(s) address without credentials or query parameters")
        written[prefs.LOCAL_URL] = address
    if prefs.PROXY_ENABLED in written:
        if written[prefs.PROXY_ENABLED] not in {"", "0", "1"}:
            raise HTTPException(422, detail="proxy_enabled must be 0 or 1")
        written[prefs.PROXY_ENABLED] = "1" if written[prefs.PROXY_ENABLED] == "1" else "0"
    if prefs.PROXY_POOL in written:
        lines = [one for one in written[prefs.PROXY_POOL].replace(",", "\n").split() if one]
        pool = proxypool.parse_pool(written[prefs.PROXY_POOL])
        if len(pool) != len(dict.fromkeys(lines)):
            raise HTTPException(
                422, detail="proxy_pool takes one http(s) address per line, like http://host:8080, "
                "with no login in it: save the login under Keys")
        written[prefs.PROXY_POOL] = "\n".join(pool)
    for key in (prefs.AGENT_TRANSPORT, prefs.CODEX_TRANSPORT):
        if key in written and written[key] not in {"", "auto", "exec", "persistent"}:
            raise HTTPException(422, detail=f"{key} must be auto, exec, or persistent")
    if (prefs.CLASSIFICATION_PROVIDER in written
            and written[prefs.CLASSIFICATION_PROVIDER] not in {"", "agent", "typesafe"}):
        raise HTTPException(422, detail="classification_provider must be agent or typesafe")
    for key in (prefs.LOCAL_OUTPUT_LANGUAGE, prefs.LOCAL_SEARCH_LANGUAGE):
        if key not in written:
            continue
        value = written[key]
        valid = value == "auto" if key == prefs.LOCAL_OUTPUT_LANGUAGE else False
        valid = valid or bool(re.fullmatch(r"[a-z]{2,3}(?:-[A-Z]{2})?", value))
        if not valid:
            raise HTTPException(
                422,
                detail=(
                    f"{key} must be 'auto' (output only) or a language tag "
                    "such as en or tr-TR"
                ),
            )
    if (prefs.INFO_SENSITIVITY in written
            and written[prefs.INFO_SENSITIVITY] not in {"", *evidence.SENSITIVITIES}):
        raise HTTPException(
            422, detail="info_sensitivity must be all, hide_thin, or strict")
    if prefs.MARKET_REGION in written and written[prefs.MARKET_REGION] not in prefs.REGIONS:
        raise HTTPException(422, detail="market_region must be a supported region code")
    for key in prefs.KRIKO_AGENT_TUNING_KEYS:
        if key not in written:
            continue
        try:
            percent = int(written[key])
        except ValueError as error:
            raise HTTPException(422, detail=f"{key} must be an integer from 0 to 100") from error
        if not 0 <= percent <= 100:
            raise HTTPException(422, detail=f"{key} must be an integer from 0 to 100")
        written[key] = str(percent)
    if prefs.LLM_BASE_URL in written and written[prefs.LLM_BASE_URL]:
        endpoint = written[prefs.LLM_BASE_URL].rstrip("/")
        parsed = urlsplit(endpoint)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise HTTPException(422, detail="llm_base_url must be an http(s) endpoint without credentials or query parameters")
        written[prefs.LLM_BASE_URL] = endpoint
    if prefs.LOCAL_CONTEXT in written and written[prefs.LOCAL_CONTEXT].strip():
        try:
            context_tokens = int(written[prefs.LOCAL_CONTEXT])
        except ValueError as error:
            raise HTTPException(
                422,
                detail="local_context_tokens must be an integer from 2048 to 32768",
            ) from error
        if not 2048 <= context_tokens <= 32768:
            raise HTTPException(
                422,
                detail="local_context_tokens must be an integer from 2048 to 32768",
            )
        written[prefs.LOCAL_CONTEXT] = str(context_tokens)
    prefs.write(conn, written)
    if prefs.PROXY_ENABLED in written or prefs.PROXY_POOL in written:
        proxypool.forget()
    return prefs.choices(conn)


@router.get("/costs")
def read_costs(conn=Depends(get_app_state)) -> dict:
    """What has been spent here, what the next run is likely to cost, and why
    there is no credit balance on this screen."""
    return costs.overview(conn)
