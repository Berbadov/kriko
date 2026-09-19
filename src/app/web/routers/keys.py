"""Setting a key, and never reading one back.

Four endpoints and a hard rule: **no response body from this router may
contain a key.** Not on success, not in a validation message, not in an
exception. `test_the_keys_endpoint_never_returns_a_key` asserts it by putting a
known string in and searching every response — including the error paths — for
it, because the leak that matters is the one in the message nobody reads.

`app/keys.py` holds the storage and the masking; this file is only the door.
"""

import json
import os
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import keys, operations

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


class KeyTest(BaseModel):
    provider: str


TEST_TIMEOUT = 20.0


def _post_raw(url: str, payload: dict, headers: dict, timeout: float = TEST_TIMEOUT) -> bytes:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _timed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _row(provider_id: str, llm: str = "") -> dict:
    return {
        "provider": provider_id,
        "ok": False,
        "latency_ms": 0,
        "error": "",
        "detail": "",
        "results": None,
        "tokens_in": None,
        "tokens_out": None,
        "tokens": None,
        "usd": None,
        "llm": llm,
    }


def _refused(provider_id: str, latency_ms: int, error: str, detail: str, llm: str = "") -> dict:
    out = _row(provider_id, llm)
    out.update({"latency_ms": latency_ms, "error": error, "detail": detail})
    return out


def _transport_refused(provider_id: str, start: float, exc: Exception, llm: str = "") -> dict:
    latency = _timed_ms(start)
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return _refused(provider_id, latency, "unauthorized", f"provider refused the key (HTTP {exc.code})", llm)
        return _refused(provider_id, latency, f"http_{exc.code}", f"provider answered HTTP {exc.code}", llm)
    if isinstance(exc, TimeoutError):
        return _refused(provider_id, latency, "timeout", "provider did not answer in time", llm)
    if isinstance(exc, urllib.error.URLError):
        if isinstance(exc.reason, TimeoutError):
            return _refused(provider_id, latency, "timeout", "provider did not answer in time", llm)
        return _refused(provider_id, latency, "unreachable", f"provider could not be reached ({type(exc.reason).__name__})", llm)
    if isinstance(exc, OSError):
        return _refused(provider_id, latency, "unreachable", f"provider could not be reached ({type(exc).__name__})", llm)
    return _refused(provider_id, latency, "error", f"{type(exc).__name__}: {exc}", llm)


def _counted(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _priced(name: str, tokens_in: int | None, tokens_out: int | None) -> float | None:
    if tokens_in is None or tokens_out is None:
        return None
    from app import modelcatalogue
    from app.web.settings import KRIKO_HOME

    return modelcatalogue.price(name, tokens_in, tokens_out, KRIKO_HOME)


def _search_base(provider_id: str) -> str:
    if provider_id == "tavily":
        from app.providers import tavily as tavily_provider

        return (os.environ.get("TAVILY_BASE_URL") or tavily_provider.DEFAULT_BASE_URL).rstrip("/")
    from app.providers import exa as exa_provider

    return (os.environ.get("EXA_BASE_URL") or exa_provider.DEFAULT_BASE_URL).rstrip("/")


def _completion_base(provider_id: str) -> str:
    if provider_id == "anthropic":
        from app.providers import anthropic_llm as anthropic_provider

        return (os.environ.get("ANTHROPIC_BASE_URL") or anthropic_provider.DEFAULT_BASE_URL).rstrip("/")
    from app.providers import llm as openai_provider

    return (os.environ.get("LLM_BASE_URL") or openai_provider.DEFAULT_BASE_URL).rstrip("/")


def _test_search(provider_id: str, key: str) -> dict:
    start = time.monotonic()
    url = _search_base(provider_id) + "/search"
    if provider_id == "tavily":
        payload = {
            "api_key": key,
            "query": "test",
            "max_results": 1,
            "search_depth": "basic",
            "include_answer": False,
        }
        headers = {"content-type": "application/json"}
    else:
        payload = {"query": "test", "numResults": 1, "type": "auto"}
        headers = {"x-api-key": key}
    try:
        raw = _post_raw(url, payload, headers)
    except Exception as exc:
        return _transport_refused(provider_id, start, exc)
    try:
        body = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return _refused(provider_id, _timed_ms(start), "malformed", "provider answered something that is not JSON")
    if not isinstance(body, dict):
        return _refused(provider_id, _timed_ms(start), "malformed", "provider answered something without results")
    results = body.get("results")
    if not isinstance(results, list):
        return _refused(provider_id, _timed_ms(start), "malformed", "provider answered something without results")
    hits = [item for item in results if isinstance(item, dict) and str(item.get("url") or "").strip()]
    latency = _timed_ms(start)
    if not hits:
        out = _refused(provider_id, latency, "empty", "provider answered but returned no results")
        out["results"] = 0
        return out
    out = _row(provider_id)
    out.update({"ok": True, "latency_ms": latency, "results": len(hits)})
    return out


def _openai_verdict(provider_id: str, start: float, name: str, body: dict) -> dict:
    row = _row(provider_id, name)
    choices = body.get("choices")
    if not isinstance(choices, list):
        row.update({"latency_ms": _timed_ms(start), "error": "malformed", "detail": "provider answered something without text"})
        return row
    usage = body.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    tokens_in = _counted(usage.get("prompt_tokens"))
    tokens_out = _counted(usage.get("completion_tokens"))
    total = _counted(usage.get("total_tokens"))
    if total is not None:
        tokens = total
    elif tokens_in is not None or tokens_out is not None:
        tokens = (tokens_in or 0) + (tokens_out or 0)
    else:
        tokens = None
    row.update({
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens": tokens,
        "usd": _priced(name, tokens_in, tokens_out),
    })
    if not choices:
        row.update({"latency_ms": _timed_ms(start), "error": "empty", "detail": "provider answered but returned no text"})
        return row
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    text = (message or {}).get("content") if isinstance(message, dict) else ""
    if not str(text or "").strip():
        row.update({"latency_ms": _timed_ms(start), "error": "empty", "detail": "provider answered but returned no text"})
        return row
    row.update({"ok": True, "latency_ms": _timed_ms(start), "error": "", "detail": ""})
    return row


def _anthropic_verdict(provider_id: str, start: float, name: str, body: dict) -> dict:
    row = _row(provider_id, name)
    content = body.get("content")
    if not isinstance(content, list):
        row.update({"latency_ms": _timed_ms(start), "error": "malformed", "detail": "provider answered something without text"})
        return row
    usage = body.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    tokens_in = _counted(usage.get("input_tokens"))
    tokens_out = _counted(usage.get("output_tokens"))
    if tokens_in is not None or tokens_out is not None:
        tokens = (tokens_in or 0) + (tokens_out or 0)
    else:
        tokens = None
    row.update({
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens": tokens,
        "usd": _priced(name, tokens_in, tokens_out),
    })
    text = "".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
    if not text.strip():
        row.update({"latency_ms": _timed_ms(start), "error": "empty", "detail": "provider answered but returned no text"})
        return row
    row.update({"ok": True, "latency_ms": _timed_ms(start), "error": "", "detail": ""})
    return row


def _test_completion(provider_id: str, key: str) -> dict:
    start = time.monotonic()
    if provider_id == "anthropic":
        from app.providers.anthropic_llm import API_VERSION

        name = (os.environ.get("ANTHROPIC_MODEL") or "").strip()
        if not name:
            return _refused(provider_id, _timed_ms(start), "no_model", "no Anthropic LLM chosen")
        url = _completion_base(provider_id) + "/messages"
        payload = {
            "model": name,
            "max_tokens": 8,
            "temperature": 0.0,
            "messages": [{"role": "user", "content": "Reply with the word ok."}],
        }
        headers = {"x-api-key": key, "anthropic-version": API_VERSION}
    else:
        from app.providers import llm as llm_provider

        name = llm_provider.model_name()
        url = _completion_base(provider_id) + "/chat/completions"
        payload = {
            "model": name,
            "messages": [{"role": "user", "content": "Reply with the word ok."}],
            "temperature": 0.0,
            "max_tokens": 8,
        }
        headers = {"authorization": f"Bearer {key}"}
    try:
        raw = _post_raw(url, payload, headers)
    except Exception as exc:
        return _transport_refused(provider_id, start, exc, name)
    try:
        body = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return _refused(provider_id, _timed_ms(start), "malformed", "provider answered something that is not JSON", name)
    if not isinstance(body, dict):
        return _refused(provider_id, _timed_ms(start), "malformed", "provider answered something without text", name)
    if provider_id == "anthropic":
        return _anthropic_verdict(provider_id, start, name, body)
    return _openai_verdict(provider_id, start, name, body)


def _run_provider_test(provider_id: str) -> dict:
    from app.providers import MissingKey

    try:
        key = keys.require(provider_id)
    except MissingKey as exc:
        return _refused(provider_id, 0, "missing_key", str(exc))
    except Exception as exc:
        return _refused(provider_id, 0, "error", f"{type(exc).__name__}: {exc}")
    try:
        if provider_id in ("exa", "tavily"):
            return _test_search(provider_id, key)
        if provider_id in ("openai", "anthropic"):
            return _test_completion(provider_id, key)
        return _refused(provider_id, 0, "unsupported", f"no self-test for {provider_id}")
    except Exception as exc:
        return _refused(provider_id, 0, "error", f"{type(exc).__name__}: {exc}")


@router.post("/test")
def check(request: Request, body: KeyTest) -> dict:
    provider_id = body.provider.strip().lower()
    if provider_id not in keys.BY_ID:
        raise HTTPException(404, f"unknown provider {body.provider}")
    path = getattr(request.app.state.settings, "app_state_path")
    with operations.record(path, door="app", name="key_test", kind="read", arguments={"provider": provider_id}) as outcome:
        result = _run_provider_test(provider_id)
        outcome["response"] = operations.summarise(result)
        tokens = result.get("tokens")
        if isinstance(tokens, int) and not isinstance(tokens, bool):
            outcome["tokens"] = tokens
        usd = result.get("usd")
        if isinstance(usd, (int, float)) and not isinstance(usd, bool):
            outcome["usd"] = float(usd)
        return result
