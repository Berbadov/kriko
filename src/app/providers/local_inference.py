"""A completion socket for a local inference server.

Lives in `app/providers/` with the other sockets, not in the engine, for the
same reason `llm.py` does: the OpenAI-compatible wire protocol says
`"model"` and the domain-free guard bans that word from `kriko/` — a
protocol's vocabulary is the protocol's business, and the split between
engine shape and provider sockets is where that boundary is drawn.

Speaks `/v1/chat/completions`, the surface every serious local engine
exposes, so the plane never learns which binary is behind the port.

**It fails out loud (B171).** The paid sockets return an empty string on any
failure, which is right for a plane whose outage should cost a document, not a
run. Here the outage *is* the run: a server that is down, has no model of that
name, or answers after the timeout made every earlier local run end as "0
claims kept" with no word of why. So this socket raises `LocalInferenceError`
whose text names the address and the reason in the reader's terms, and the
plane says it in the job log.
"""

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

#: Long enough for a small model on a CPU to read a page and write a JSON
#: array, which is minutes rather than the 45 seconds a hosted API needs.
#: The reader can change it (Settings, "Local machine"); this is the default.
DEFAULT_TIMEOUT = 300.0

#: The reply budget, in tokens. A findings reply is a short JSON array; a
#: model that runs past this is composing prose, and an unbounded reply is
#: how a small model turns one page into twenty minutes on a CPU. `None`
#: means the server's own default (nothing sent on the wire).
DEFAULT_MAX_TOKENS = 1024

#: The context window assumed when the server will not say: Ollama's own
#: default. Too small costs a page; too large and the server silently drops
#: the front of the prompt, which is the instructions.
DEFAULT_CONTEXT_TOKENS = 4096
#: Characters per token, rounded down on purpose: an estimate that is low
#: leaves room, one that is high overflows the window.
CHARS_PER_TOKEN = 3.0
#: Tokens kept free beside the reply budget, for the chat template.
_TEMPLATE_TOKENS = 128

#: What a server says when the program that runs its models is missing, as
#: opposed to the machine lacking memory for one. Both are HTTP 500 and only the
#: words tell them apart.
INCOMPLETE_WORDS = ("llama-server", "binary not found")

#: Servers (by address) whose last call said the install is not whole, and the
#: sentence to show for it. Kept in memory: a restart asks the server again, and
#: the first failing call finds it out again. See `runtime_incomplete`.
_incomplete: dict[str, str] = {}


def runtime_incomplete(base_url: str) -> str:
    """Why the server at `base_url` cannot run a model, or "" when nothing says it cannot."""
    return _incomplete.get(base_url.rstrip("/"), "")


def forget_incomplete(base_url: str = "") -> None:
    """The install was repaired (or the reader says so): ask the server afresh."""
    if base_url:
        _incomplete.pop(base_url.rstrip("/"), None)
    else:
        _incomplete.clear()


#: A second try after these, because a local server's failure modes are
#: transient in exactly this way: an idle process paged out to disk answers
#: late and dies mid-reply, then answers fine (Ollama loading a model on its
#: first call; a proxy closing an idle keep-alive). Only these retry, once;
#: a 400 or 404 is an answer, not a hiccup.
_RETRY_STATUS = frozenset((408, 429, 500, 502, 503, 504))

#: The reply a findings extraction must produce, as a JSON schema. Sent as the
#: `json_schema` response format so a server that supports grammar constraint
#: cannot answer in prose. The keys are the plane's own reply shape
#: (`kriko.research.local._REPLY_SHAPE`), nothing about any category.
FINDINGS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            key: {"type": "string"}
            for key in ("source_url", "title", "domain", "severity",
                        "quote", "body", "advice")
        },
        "required": ["source_url", "title", "quote", "body"],
    },
}


class LocalInferenceError(RuntimeError):
    """The local server did not produce a completion, and why, in words."""

    def __init__(self, message: str, *, code: str = "inference_error"):
        super().__init__(message)
        self.code = code


class OpenAICompatSocket:
    """A completion socket for a local inference server.

    Speaks the OpenAI-compatible `/v1/chat/completions` surface that every
    serious local engine exposes, so the plane never learns which binary
    is behind the port. `response_json_schema` is sent as the `json_schema`
    response format — engine-level grammar constraint, the strongest guarantee
    a small socket can get — and dropped for one retry when the server
    refuses it (HTTP 400), since a server that cannot constrain its output
    can still answer.

    Temperature 0 for extraction: creativity in front of a grounding gate
    buys refusals, not findings.
    """

    def __init__(self, base_url: str, serving_name: str,
                 timeout: float = DEFAULT_TIMEOUT,
                 temperature: float = 0.0,
                 context_chars: int = 12000,
                 max_tokens: int | None = DEFAULT_MAX_TOKENS,
                 response_json_schema: dict | str = "",
                 reasoning_effort: str = "", runtime_options: dict | None = None):
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.serving_name = serving_name
        self.timeout = timeout
        self.temperature = temperature
        self.context_chars = context_chars
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort.strip()
        self.runtime_options = dict(runtime_options or {})
        if isinstance(response_json_schema, str):
            response_json_schema = (json.loads(response_json_schema)
                                    if response_json_schema.strip() else {})
        self._schema = response_json_schema or {}
        self.tokens_used: int | None = None
        #: The two halves, for `app.meter.Meter`, which reads them off any
        #: completer by attribute.
        self.tokens_in: int | None = None
        self.tokens_out: int | None = None
        self.model = serving_name
        self.calls = 0
        #: The last reply's `finish_reason` ("stop", "length", ...), for the
        #: plane to say *why* a reply was short instead of guessing.
        self.last_finish_reason = ""
        self.truncated = 0
        self.usage_complete = True
        self.last_usage_complete = False
        self._context: int | None = None

    def __call__(self, prompt: str) -> str:
        return self.complete(prompt)

    def set_schema(self, schema: dict) -> None:
        self._schema = schema

    def complete(self, prompt: str) -> str:
        body = {
            "model": self.serving_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "stream": False,
        }
        if isinstance(self.max_tokens, int) and self.max_tokens > 0:
            body["max_tokens"] = self.max_tokens
        # A model that thinks first (Qwen 3.5 and kin) spends the whole reply
        # budget on its reasoning and answers with an empty string: a 0.8B
        # model took 12 s to write nothing, and under a second to answer once
        # told not to think. Extraction wants the answer, so thinking is off
        # unless the reader chose an effort. A server that does not know the
        # field is handled below (HTTP 400 drops it and retries).
        body["reasoning_effort"] = self.reasoning_effort or "none"
        if self._schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "findings", "schema": self._schema},
            }
        try:
            payload = self._post(body)
        except urllib.error.HTTPError as error:
            if error.code in _RETRY_STATUS:
                # Transient: the model was loading, the proxy dropped an
                # idle connection. One plain retry, schema dropped too,
                # since a server caught mid-load can refuse it as well.
                body.pop("response_format", None)
                body.pop("reasoning_effort", None)
                try:
                    payload = self._post(body)
                except urllib.error.HTTPError as again:
                    raise self._refused(again) from again
                except Exception as other:  # noqa: BLE001
                    raise self._failed(other) from other
            elif error.code == 400 and ("response_format" in body
                                         or "reasoning_effort" in body):
                # The server cannot take a field it does not know: it cannot
                # constrain its output, or it does not speak this effort
                # dialect. Either optional field may be the refused one, so
                # they are dropped one at a time — schema first, the older
                # refusal — and each drop earns one retry.
                payload = None
                for optional in ("response_format", "reasoning_effort"):
                    if optional not in body:
                        continue
                    body.pop(optional)
                    try:
                        payload = self._post(body)
                        break
                    except urllib.error.HTTPError as again:
                        if again.code != 400:
                            raise self._refused(again) from again
                    except Exception as other:  # noqa: BLE001
                        raise self._failed(other) from other
                if payload is None:
                    raise self._refused(error) from error
            else:
                raise self._refused(error) from error
        except Exception as error:  # noqa: BLE001 - named for the reader below
            raise self._failed(error) from error
        self.calls += 1
        _incomplete.pop(self.base_url.rstrip("/"), None)  # it answered: whatever was wrong is not now
        self._count(payload)
        choices = payload.get("choices") if isinstance(payload, dict) else None
        first = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first, dict) else None
        finish = str(first.get("finish_reason") or "") if isinstance(first, dict) else ""
        self.last_finish_reason = finish
        if finish == "length":
            self.truncated += 1
        text = str((message or {}).get("content") or "") if isinstance(message, dict) else ""
        if not text.strip():
            if finish == "length":
                raise LocalInferenceError(
                    f"{self.base_url} cut {self.serving_name!r} off at "
                    f"{self.max_tokens} tokens before it wrote anything. The "
                    "page may be too long for this model's context.", code="truncated")
            raise LocalInferenceError(
                f"{self.base_url} answered with an empty reply from "
                f"{self.serving_name!r}: the model produced no text. Try a "
                "larger model, or check that it is loaded.", code="empty_reply")
        return text

    def context_tokens(self) -> int:
        """The window the server runs this model with, in tokens.

        Asked of the server, because it is a runtime setting rather than a
        property of the model: Ollama loads a model trained on 32k at 4k
        unless told otherwise, and a prompt past it is cut from the front
        without an error. Each engine says it in its own place (Ollama's
        `/api/ps`, llama-server's `/props`, LM Studio's `/api/v0/models`).
        `DEFAULT_CONTEXT_TOKENS` when none answers. Kept once found; not
        kept while unknown, since Ollama only lists a model once loaded.
        """
        requested = self.runtime_options.get("num_ctx")
        if isinstance(requested, int) and requested > 0:
            return requested
        if self._context:
            return self._context
        found = self._ask_context()
        if found:
            self._context = found
        return found or DEFAULT_CONTEXT_TOKENS

    def prompt_chars_allowed(self) -> int:
        """How many characters of prompt fit beside the reply budget."""
        reply = self.max_tokens if isinstance(self.max_tokens, int) else 1024
        tokens = self.context_tokens() - reply - _TEMPLATE_TOKENS
        return max(0, int(tokens * CHARS_PER_TOKEN))

    def _ask_context(self) -> int | None:
        def get(path: str):
            try:
                with urllib.request.urlopen(self.base_url + path, timeout=5) as resp:
                    return json.loads(resp.read().decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001 - an engine that does not say is "unknown"
                return None

        def number(value) -> int | None:
            return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

        ps = get("/api/ps")
        if isinstance(ps, dict):
            for one in ps.get("models") or []:
                if isinstance(one, dict) and self.serving_name in (one.get("name"), one.get("model")):
                    if number(one.get("context_length")):
                        return one["context_length"]
        props = get("/props")
        if isinstance(props, dict):
            settings = props.get("default_generation_settings") or {}
            value = number(settings.get("n_ctx")) if isinstance(settings, dict) else None
            if value:
                return value
        studio = get("/api/v0/models/" + urllib.parse.quote(self.serving_name, safe=""))
        if isinstance(studio, dict):
            return number(studio.get("loaded_context_length"))
        return None

    def _post(self, body: dict) -> dict:
        if self.runtime_options:
            # Loader options are not part of the OpenAI API. Use Ollama's
            # native endpoint only for settings that resolve identified as
            # supported; never silently send ignored GPU fields to /v1.
            native = {"model": self.serving_name, "messages": body["messages"],
                      "stream": False,
                      **({"think": False} if body.get("reasoning_effort") == "none" else {}),
                      "options": {
                          **self.runtime_options, "temperature": body["temperature"],
                          **({"num_predict": body["max_tokens"]} if "max_tokens" in body else {})}}
            if "response_format" in body:
                native["format"] = body["response_format"]["json_schema"]["schema"]
            request = urllib.request.Request(
                self.base_url + "/api/chat", data=json.dumps(native).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                result = json.load(resp)
            incoming, outgoing = result.get("prompt_eval_count"), result.get("eval_count")
            usage = {"prompt_tokens": incoming, "completion_tokens": outgoing}
            if isinstance(incoming, int) and isinstance(outgoing, int):
                usage["total_tokens"] = incoming + outgoing
            return {"choices": [{"message": result.get("message", {}),
                                 "finish_reason": result.get("done_reason", "stop")}], "usage": usage}
        request = urllib.request.Request(
            self.base_url + "/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def _count(self, payload) -> None:
        usage = payload.get("usage") if isinstance(payload, dict) else None
        self.last_usage_complete = isinstance(usage, dict) and (
            isinstance(usage.get("total_tokens"), int) and not isinstance(usage.get("total_tokens"), bool)
            or all(isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool)
                   for key in ("prompt_tokens", "completion_tokens")))
        if not isinstance(usage, dict):
            self.usage_complete = False
            return
        for field, key in (("tokens_in", "prompt_tokens"),
                           ("tokens_out", "completion_tokens")):
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                setattr(self, field, (getattr(self, field) or 0) + value)
        total = usage.get("total_tokens")
        if isinstance(total, int) and not isinstance(total, bool):
            self.tokens_used = (self.tokens_used or 0) + total
        elif all(isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool)
                 for key in ("prompt_tokens", "completion_tokens")):
            self.tokens_used = (self.tokens_used or 0) + usage["prompt_tokens"] + usage["completion_tokens"]
        else:
            self.usage_complete = False

    def _refused(self, error: urllib.error.HTTPError) -> LocalInferenceError:
        detail = ""
        try:
            raw = json.loads(error.read().decode("utf-8", "replace"))
            found = raw.get("error") if isinstance(raw, dict) else ""
            detail = (found.get("message") if isinstance(found, dict) else found) or ""
        except Exception:  # noqa: BLE001 - the status alone is enough
            pass
        if error.code >= 500 and any(word in str(detail).casefold() for word in INCOMPLETE_WORDS):
            # The server is up and lists its models, but the program that runs
            # them is not there: an install that never finished. Saying so
            # here, once, is what lets the screen stop calling it ready.
            said = (f"{self.base_url} is installed but incomplete: its model runner is missing "
                    f"({str(detail)[:120]}). In Kriko, open Local LLM and press Set up Ollama, "
                    "which repairs it; models you downloaded are kept.")
            _incomplete[self.base_url.rstrip("/")] = said
            return LocalInferenceError(said, code="runtime_incomplete")
        if error.code == 404:
            return LocalInferenceError(
                f"{self.base_url} has no model named {self.serving_name!r}"
                + (f" ({detail})" if detail else "")
                + ". Download one in that app, then pick it in Settings, Local machine.")
        return LocalInferenceError(
            f"{self.base_url} answered HTTP {error.code}"
            + (f": {str(detail)[:200]}" if detail else ""))

    def _failed(self, error: Exception) -> LocalInferenceError:
        if isinstance(error, (TimeoutError, socket.timeout)) or (
                isinstance(error, urllib.error.URLError)
                and isinstance(error.reason, (TimeoutError, socket.timeout))):
            return LocalInferenceError(
                f"{self.base_url} did not answer within {self.timeout:g} s. A "
                "model on a CPU can be slow: raise the timeout in Settings, "
                "Local machine, or use a smaller model.", code="timeout")
        if isinstance(error, (urllib.error.URLError, OSError)):
            return LocalInferenceError(
                f"{self.base_url} is not reachable (server down). Start the "
                "local model server, or change its address in Settings, Local machine.")
        return LocalInferenceError(
            f"{self.base_url} answered something that is not a completion "
            f"({type(error).__name__}).")
