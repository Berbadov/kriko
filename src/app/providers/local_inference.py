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

from collections.abc import Callable, Iterator
import json
import queue
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from app.providers import network

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
#: A deliberately low UTF-8 byte estimate for a prompt token. Counting bytes
#: instead of Python characters keeps accents and non-Latin text from getting
#: a larger budget just because one character occupies several bytes.
PROMPT_BYTES_PER_TOKEN = 2

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


#: Every `(server, model)` this process has asked for a completion since the
#: last `release`. A server keeps a model in memory after its last request
#: (Ollama for five minutes by default), so a finished run went on holding
#: gigabytes of video memory while Kriko sat in the background.
_held: set[tuple[str, str]] = set()
_held_lock = threading.Lock()


def _hold(base_url: str, serving_name: str) -> None:
    with _held_lock:
        _held.add((base_url.rstrip("/"), serving_name))


def release(timeout: float = 10.0) -> list[str]:
    """Ask each server to unload every model this process ran; the names let go.

    Called when no work is left, so the memory is the host's again the moment
    a run ends rather than whenever the server's own timer runs out. Ollama
    unloads on a request with `keep_alive` 0. A server without that endpoint
    answers 404 and keeps its own policy; nothing here can fail a run.
    """
    with _held_lock:
        held = sorted(_held)
        _held.clear()
    released = []
    for base_url, name in held:
        request = urllib.request.Request(
            base_url + "/api/generate",
            data=json.dumps({"model": name, "keep_alive": 0}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with network.urlopen(request, timeout=timeout, kind="inference") as response:
                response.read()
            released.append(name)
        except Exception:  # noqa: BLE001 - a server that cannot unload keeps its own timer
            pass
    return released


#: A second try after these, because a local server's failure modes are
#: transient in exactly this way: an idle process paged out to disk answers
#: late and dies mid-reply, then answers fine (Ollama loading a model on its
#: first call; a proxy closing an idle keep-alive). Only these retry, once;
#: a 400 or 404 is an answer, not a hiccup.
_RETRY_STATUS = frozenset((408, 429, 500, 502, 503, 504))


def _read_body(error: urllib.error.HTTPError) -> str:
    """An error's body as text, left readable for whoever reads it next."""
    import io

    try:
        raw = error.read() or b""
    except Exception:  # noqa: BLE001 - an unreadable body is an empty one
        raw = b""
    error.fp = io.BytesIO(raw)
    try:
        error.read = error.fp.read  # type: ignore[method-assign,assignment]
    except Exception:  # noqa: BLE001
        pass
    return raw.decode("utf-8", "replace")

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


def _event(event: dict, native: bool) -> tuple[str, str, dict | None]:
    """One streamed event as `(text, finish reason, usage)`, in either dialect."""
    if native:
        message = event.get("message")
        text = str(message.get("content") or "") if isinstance(message, dict) else ""
        finish = str(event.get("done_reason") or "stop") if event.get("done") else ""
        counted = None
        if event.get("done") and ("prompt_eval_count" in event or "eval_count" in event):
            counted = {"prompt_tokens": event.get("prompt_eval_count"),
                       "completion_tokens": event.get("eval_count")}
        return text, finish, counted
    choices = event.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    part = choice.get("delta") if isinstance(choice.get("delta"), dict) else choice.get("message")
    text = str(part.get("content") or "") if isinstance(part, dict) else ""
    usage = event.get("usage")
    return text, str(choice.get("finish_reason") or ""), (usage if isinstance(usage, dict) else None)


class _OwnerCancelled(BaseException):
    """Carry an owner's cancellation through transport error handling unchanged."""

    def __init__(self, original: BaseException):
        super().__init__(str(original))
        self.original = original


class _ReaderStopped(Exception):
    """A network-reader thread was asked to stop by its owner."""


def _abort_response_read(response) -> None:
    """Abort the underlying socket without closing its buffered reader cross-thread."""
    raw = getattr(response, "_response", response)
    fp = getattr(raw, "fp", None)
    sock = getattr(getattr(fp, "raw", None), "_sock", None)
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass
    abort = getattr(response, "abort", None)
    if callable(abort):
        abort()


class OpenAICompatSocket:
    """A completion socket for a local inference server.

    Speaks the OpenAI-compatible `/v1/chat/completions` surface that every
    serious local engine exposes, so the plane never learns which binary
    is behind the port. `response_json_schema` is sent as the `json_schema`
    response format — engine-level grammar constraint, the strongest guarantee
    a small socket can get. A refusal of another optional field keeps that
    schema; when the server rejects the format, the socket tries `json_object`
    before an unconstrained completion and reports that degradation.

    Temperature 0 for extraction: creativity in front of a grounding gate
    buys refusals, not findings.
    """

    def __init__(self, base_url: str, serving_name: str,
                 timeout: float = DEFAULT_TIMEOUT,
                 temperature: float = 0.0,
                 context_chars: int = 12000,
                 max_tokens: int | None = DEFAULT_MAX_TOKENS,
                 response_json_schema: dict | str = "",
                 reasoning_effort: str = "", runtime_options: dict | None = None,
                 context_tokens: int | None = None, native_ollama: bool = False):
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.serving_name = serving_name
        self.timeout = timeout
        self.temperature = temperature
        self.context_chars = context_chars
        self.language_instruction = ""
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort.strip()
        self.runtime_options = dict(runtime_options or {})
        self._requested_context = max(2048, min(32768, context_tokens)) if context_tokens else None
        if native_ollama:
            self.runtime_options["num_ctx"] = self._requested_context or DEFAULT_CONTEXT_TOKENS
        if isinstance(response_json_schema, str):
            response_json_schema = (json.loads(response_json_schema)
                                    if response_json_schema.strip() else {})
        self._schema = response_json_schema or {}
        self._response_format_mode = "json_schema" if self._schema else "not_requested"
        self._response_format_reason = ""
        self._reasoning_effort_supported = True
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
        # Installed by LocalAsker's _MeasuredSocket. This callback can touch a
        # job's SQLite connection, so it is only called on the socket owner
        # thread; reader threads see only a thread-safe stop event.
        self.check_cancelled: Callable[[], None] | None = None

    def set_cancel_check(self, check: Callable[[], None] | None) -> None:
        self.check_cancelled = check

    def _check_cancel(self) -> None:
        if self.check_cancelled is not None:
            self.check_cancelled()

    def _read_cancelable(self, response, read):
        """Read a whole response off-thread while the owner polls cancellation.

        `Progress.check` owns a SQLite connection and must not be invoked from
        the reader. Closing the response is safe from the owner thread and
        interrupts a socket read so its outbound permit is released promptly.
        """
        result_queue: queue.Queue = queue.Queue(maxsize=1)

        def reader() -> None:
            try:
                result_queue.put((True, read()))
            except BaseException as error:
                result_queue.put((False, error))

        thread = threading.Thread(target=reader, name="kriko-inference-read", daemon=True)
        thread.start()
        try:
            while True:
                try:
                    self._check_cancel()
                except BaseException as error:
                    _abort_response_read(response)
                    thread.join(timeout=0.5)
                    raise _OwnerCancelled(error) from None
                try:
                    ok, value = result_queue.get(timeout=0.025)
                except queue.Empty:
                    continue
                if ok:
                    return value
                raise value
        finally:
            # On success/errors, the surrounding response context closes it;
            # on cancellation its socket was aborted above to interrupt it.
            if thread.is_alive():
                _abort_response_read(response)
                thread.join(timeout=0.2)

    def _response_lines(self, request):
        """Yield network lines while the owner thread checks job cancellation."""
        events: queue.Queue = queue.Queue(maxsize=16)
        stop = threading.Event()
        holder: dict[str, object] = {}
        holder_lock = threading.Lock()

        def publish(value) -> bool:
            while not stop.is_set():
                try:
                    events.put(value, timeout=0.05)
                    return True
                except queue.Full:
                    continue
            return False

        def check_stopped() -> None:
            if stop.is_set():
                raise _ReaderStopped()

        def reader() -> None:
            response = None
            try:
                with network.urlopen(request, timeout=self.timeout, kind="inference",
                                    check=check_stopped) as response:
                    with holder_lock:
                        holder["response"] = response
                    for raw in response:
                        if not publish(("line", raw)):
                            return
                publish(("done", None))
            except BaseException as error:
                publish(("error", error))

        thread = threading.Thread(target=reader, name="kriko-inference-stream", daemon=True)
        thread.start()
        interrupted = False
        try:
            while True:
                try:
                    self._check_cancel()
                except BaseException as error:
                    stop.set()
                    with holder_lock:
                        response = holder.get("response")
                    if response is not None:
                        _abort_response_read(response)
                    interrupted = True
                    thread.join(timeout=0.5)
                    raise _OwnerCancelled(error) from None
                try:
                    kind, value = events.get(timeout=0.025)
                except queue.Empty:
                    continue
                if kind == "line":
                    yield value
                elif kind == "error":
                    raise value
                else:
                    return
        finally:
            stop.set()
            with holder_lock:
                response = holder.get("response")
            if response is not None and not interrupted:
                try:
                    response.close()
                except Exception:
                    pass
            thread.join(timeout=0.2)

    def __call__(self, prompt: str) -> str:
        return self.complete(prompt)

    def set_schema(self, schema: dict) -> None:
        self._schema = schema
        if schema and self._response_format_mode == "not_requested":
            self._response_format_mode = "json_schema"

    @property
    def structured_output(self) -> dict[str, str]:
        """The structured-output mode negotiated for this socket, without raw server errors."""
        return {"mode": self._response_format_mode, "reason": self._response_format_reason}

    def json(self, prompt: str, schema: dict) -> str:
        previous = self._schema
        self._schema = schema
        if schema and self._response_format_mode == "not_requested":
            self._response_format_mode = "json_schema"
        try:
            if len(prompt.encode("utf-8")) > self.prompt_bytes_allowed():
                raise LocalInferenceError("Local prompt exceeds the configured context budget.")
            return self.complete(prompt)
        finally:
            self._schema = previous

    def complete(self, prompt: str) -> str:
        _hold(self.base_url, self.serving_name)
        prompt = self.language_instruction + prompt
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
        if self._reasoning_effort_supported:
            body["reasoning_effort"] = self.reasoning_effort or "none"
        if self._schema:
            if self._response_format_mode == "json_schema":
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "findings", "schema": self._schema},
                }
            elif self._response_format_mode == "json_object":
                body["response_format"] = {"type": "json_object", "schema": self._schema}
        try:
            payload = self._post(body)
        except urllib.error.HTTPError as error:
            said = _read_body(error)
            format_mentioned = self._format_field_mentioned(said)
            spelled = self._other_schema_spelling(body, error.code, said)
            if spelled is not None:
                payload = spelled
            elif error.code in _RETRY_STATUS:
                # Transient: the model was loading, the proxy dropped an
                # idle connection. Retry with the same evidence grammar.
                try:
                    payload = self._post(body)
                except urllib.error.HTTPError as again:
                    raise self._refused(again) from again
                except _OwnerCancelled as stopped:
                    raise stopped.original from None
                except Exception as other:  # noqa: BLE001
                    raise self._failed(other) from other
            elif error.code == 400 and ("response_format" in body
                                         or "reasoning_effort" in body):
                # Retain the evidence grammar when the error names the other
                # optional field. For an ambiguous 400, remove the advisory
                # reasoning hint first; only then negotiate or drop the schema.
                payload = None
                order = self._refusal_order(body, said)
                schema_spelling_tried = format_mentioned
                last_error = error
                last_said = said
                reasoning_probe_pending = False
                for optional in order:
                    if optional not in body:
                        continue
                    if (optional == "response_format" and not schema_spelling_tried
                            and ("reasoning_effort" not in body or
                                 self._format_field_mentioned(last_said))):
                        schema_spelling_tried = True
                        spelled = self._other_schema_spelling(
                            body, last_error.code, last_said, force=True)
                        if spelled is not None:
                            payload = spelled
                            break
                    body.pop(optional)
                    if optional == "reasoning_effort":
                        if ("reasoning_effort" in last_said.casefold()
                                and not self._format_field_mentioned(last_said)):
                            self._reasoning_effort_supported = False
                        else:
                            reasoning_probe_pending = True
                    elif optional == "response_format":
                        self._response_format_mode = "unconstrained"
                        self._response_format_reason = "response_format_refused"
                    try:
                        payload = self._post(body)
                        if reasoning_probe_pending:
                            self._reasoning_effort_supported = False
                        break
                    except urllib.error.HTTPError as again:
                        if again.code != 400:
                            raise self._refused(again) from again
                        reasoning_probe_pending = False
                        again_said = _read_body(again)
                        if ("response_format" in body and not schema_spelling_tried
                                and self._format_field_mentioned(again_said)):
                            schema_spelling_tried = True
                            spelled = self._other_schema_spelling(
                                body, again.code, again_said, force=True)
                            if spelled is not None:
                                payload = spelled
                                break
                        last_error = again
                        last_said = again_said
                    except _OwnerCancelled as stopped:
                        raise stopped.original from None
                    except Exception as other:  # noqa: BLE001
                        raise self._failed(other) from other
                if payload is None:
                    raise self._refused(error) from error
            else:
                raise self._refused(error) from error
        except _OwnerCancelled as stopped:
            raise stopped.original from None
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
            raise self._empty(finish)
        return text

    def stream(self, prompt: str, on_text: Callable[[str], None]) -> str:
        """`complete`, with each piece of the reply handed to `on_text` as it is written.

        Returns the same reply `complete` would. A reply bound to a schema is
        whole or nothing, so that case answers through `complete` and hands the
        whole reply over once. A server that answers without streaming hands
        its reply over as one piece. An exception from `on_text` (a job asked to
        stop, for one) ends the stream and is raised as it is.
        """
        if self._schema:
            text = self.complete(prompt)
            on_text(text)
            return text
        _hold(self.base_url, self.serving_name)
        body: dict = {
            "model": self.serving_name,
            "messages": [{"role": "user", "content": self.language_instruction + prompt}],
            "temperature": self.temperature,
            "stream": True,
        }
        if not self.runtime_options:
            # The token counts come at the end of the stream when asked for, and
            # `_count` reads them the same way it reads a whole reply's.
            body["stream_options"] = {"include_usage": True}
        if isinstance(self.max_tokens, int) and self.max_tokens > 0:
            body["max_tokens"] = self.max_tokens
        body["reasoning_effort"] = self.reasoning_effort or "none"
        pieces: list[str] = []
        finish, usage = "", None
        for piece, reason, counted in self._events(body):
            if piece:
                pieces.append(piece)
                on_text(piece)
            finish = reason or finish
            usage = counted or usage
        self.calls += 1
        _incomplete.pop(self.base_url.rstrip("/"), None)
        self._count({"usage": usage} if usage else {})
        self.last_finish_reason = finish
        if finish == "length":
            self.truncated += 1
        text = "".join(pieces)
        if not text.strip():
            raise self._empty(finish)
        return text

    def _events(self, body: dict) -> Iterator[tuple[str, str, dict | None]]:
        """Each event of one streamed reply, as `(text, finish reason, usage)`.

        Reads the OpenAI stream (server-sent `data:` lines), or Ollama's native
        stream (one JSON object a line) when runtime options must reach the
        server. An optional field the server refuses is dropped and the request
        is sent again, as `complete` does. Nothing is retried once a piece of the
        reply has been handed on, because a retry would repeat what was said.
        """
        native = bool(self.runtime_options)
        while True:
            sent = self._native(body, stream=True) if native else body
            url = self.base_url + ("/api/chat" if native else "/v1/chat/completions")
            request = urllib.request.Request(
                url, data=json.dumps(sent).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            delivered = False
            try:
                for raw in self._response_lines(request):
                    line = raw.decode("utf-8", "replace").strip()
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if not line or line.startswith(":") or line == "[DONE]":
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict):
                        delivered = True
                        yield _event(event, native)
                return
            except _OwnerCancelled as stopped:
                raise stopped.original from None
            except urllib.error.HTTPError as error:
                if delivered:
                    raise self._refused(error) from error
                optional = [key for key in ("stream_options", "reasoning_effort") if key in body]
                if error.code == 400 and optional:
                    body.pop(optional[0])
                    continue
                raise self._refused(error) from error
            except Exception as error:  # noqa: BLE001 - named for the reader below
                raise self._failed(error) from error

    def _empty(self, finish: str) -> LocalInferenceError:
        """Why a reply with no text is an error, said in the reader's terms."""
        if finish == "length":
            return LocalInferenceError(
                f"{self.base_url} cut {self.serving_name!r} off at "
                f"{self.max_tokens} tokens before it wrote anything. The "
                "page may be too long for this model's context.", code="truncated")
        return LocalInferenceError(
            f"{self.base_url} answered with an empty reply from "
            f"{self.serving_name!r}: the model produced no text. Try a "
            "larger model, or check that it is loaded.", code="empty_reply")

    def _native(self, body: dict, *, stream: bool) -> dict:
        """The body Ollama's native chat endpoint takes, from an OpenAI-shaped one."""
        native = {"model": self.serving_name, "messages": body["messages"],
                  "stream": stream,
                  **({"think": False} if body.get("reasoning_effort") == "none" else {}),
                  "options": {
                      **self.runtime_options, "temperature": body["temperature"],
                      **({"num_predict": body["max_tokens"]} if "max_tokens" in body else {})}}
        if "response_format" in body:
            fmt = body["response_format"]
            native["format"] = (fmt["json_schema"]["schema"]
                                 if fmt.get("type") == "json_schema" else fmt["schema"])
        return native

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
            return min(self._context, self._requested_context or 32768)
        found = self._ask_context()
        if found:
            self._context = found
        return min(found or DEFAULT_CONTEXT_TOKENS, self._requested_context or 32768)

    def prompt_chars_allowed(self) -> int:
        """How many characters of prompt fit beside the reply budget."""
        reply = self.max_tokens if isinstance(self.max_tokens, int) else 1024
        tokens = self.context_tokens() - reply - _TEMPLATE_TOKENS
        return max(0, min(self.context_chars, int(tokens - 128)))

    def prompt_bytes_allowed(self, *, reply_tokens: int | None = None) -> int:
        """A conservative UTF-8 byte budget for one prompt.

        The extraction pipeline needs both its policy and source evidence in
        one request. Treating every byte as one token made ordinary 4k
        contexts reject those requests before showing any evidence. Two bytes
        per token remains conservative for multilingual text while using the
        model's actual context and the stage's own reply reservation.
        """
        reply = (reply_tokens if isinstance(reply_tokens, int) and reply_tokens > 0
                 else self.max_tokens if isinstance(self.max_tokens, int) else 1024)
        tokens = self.context_tokens() - reply - _TEMPLATE_TOKENS - 128
        return max(0, int(tokens * PROMPT_BYTES_PER_TOKEN))

    def window_chars(self) -> int:
        """How many characters of prompt the window itself holds beside the reply.

        Not `prompt_chars_allowed`: that is the research budget, one character
        a token and capped at `context_chars`, and it bounds the evidence. The
        whole prompt (instructions and evidence) is bounded by the window, at
        `CHARS_PER_TOKEN`. Measuring the instructions against the evidence
        budget left a 16k window no room after an 11.7k-character authoring
        brief (#181).
        """
        reply = self.max_tokens if isinstance(self.max_tokens, int) else 1024
        tokens = self.context_tokens() - reply - _TEMPLATE_TOKENS
        return max(0, int(tokens * CHARS_PER_TOKEN))

    def _ask_context(self) -> int | None:
        def get(path: str):
            try:
                with network.urlopen(self.base_url + path, timeout=5, kind="inference",
                                     check=self._check_cancel) as resp:
                    raw = self._read_cancelable(resp, resp.read)
                    return json.loads(raw.decode("utf-8", "replace"))
            except _OwnerCancelled as stopped:
                raise stopped.original from None
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
            native = self._native(body, stream=False)
            request = urllib.request.Request(
                self.base_url + "/api/chat", data=json.dumps(native).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with network.urlopen(request, timeout=self.timeout, kind="inference",
                                 check=self._check_cancel) as resp:
                result = json.loads(self._read_cancelable(resp, resp.read).decode(
                    "utf-8", "replace"))
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
        with network.urlopen(request, timeout=self.timeout, kind="inference",
                             check=self._check_cancel) as resp:
            return json.loads(self._read_cancelable(resp, resp.read).decode(
                "utf-8", "replace"))

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

    def _other_schema_spelling(self, body: dict, status: int, said: str,
                               *, force: bool = False) -> dict | None:
        """The same constraint in the spelling a server that refused ours takes.

        Ollama and llama.cpp's own server take `json_schema`; llama-cpp-python's
        server (and some others) refuse it, by name, and take the schema under
        `json_object` instead. Dropping the constraint there let a small model
        answer in prose, so the other spelling is tried first. None when the
        refusal is not about the response format, or that spelling fails too.
        """
        fmt = body.get("response_format")
        if not isinstance(fmt, dict) or fmt.get("type") != "json_schema" or status not in (400, 422, 500):
            return None
        if not force and not self._format_field_mentioned(said):
            return None
        body["response_format"] = {"type": "json_object", "schema": fmt["json_schema"]["schema"]}
        try:
            result = self._post(body)
        except _OwnerCancelled as stopped:
            raise stopped.original from None
        except urllib.error.HTTPError as again:
            # Neither spelling: the original refusal path drops the field.
            body["response_format"] = fmt
            _read_body(again)
            return None
        self._response_format_mode = "json_object"
        self._response_format_reason = "json_schema_refused"
        return result

    @staticmethod
    def _format_field_mentioned(said: str) -> bool:
        folded = said.casefold()
        return "response_format" in folded or "json_schema" in folded

    @classmethod
    def _refusal_order(cls, body: dict, said: str) -> tuple[str, ...]:
        """Drop the named unsupported field first; ambiguous errors keep schema longest."""
        fields = tuple(name for name in ("reasoning_effort", "response_format") if name in body)
        folded = said.casefold()
        names_reasoning = "reasoning_effort" in folded
        names_format = cls._format_field_mentioned(said)
        if names_reasoning and not names_format:
            return ("reasoning_effort", "response_format")
        if names_format and not names_reasoning:
            return ("response_format", "reasoning_effort")
        # `reasoning_effort` is advisory; retaining the output schema matters
        # to the evidence parser and validators.
        return ("reasoning_effort", "response_format") if fields else ()

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
