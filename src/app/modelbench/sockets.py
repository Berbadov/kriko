"""How each kind of candidate is reached, and what it admits to spending.

Three transports, one narrow interface: `answer(prompt) -> Reply`. Everything
above this module — the runner, the scorer, the report — is written against
`Reply` and cannot tell a local model from a CLI, which is what makes a table
with both in it mean anything.

The three transports report cost very differently, and pretending otherwise
would be the single easiest way to make this benchmark lie:

* **`local` and `api`** speak the OpenAI wire format and send a `usage` block.
  Both halves arrive (`prompt_tokens`, `completion_tokens`), so the split is
  real and a price can be computed from it.
* **`harness`** is a process. It may meter itself or it may not, and the number
  it produces is the *whole session* — its own system prompt, its tool
  descriptions, every turn — not the brief we handed it. Mistral's CLI does
  report a total this way; its stream carries none, but its session
  `meta.json` does. That number is a fact about the CLI, and a reader comparing
  it with a local model's 900 tokens is comparing exactly the thing that
  decides the phone's architecture.

So `Reply.usage` is a word, never a zero:

    "reported"        in and out, from the endpoint's own usage block
    "reported_total"  one total, from a CLI that meters itself
    "estimated"       nobody counted; in and out approximated from characters
    "none"            nobody counted, and no estimate was safe to make

`estimated` is only ever offered where we saw the *whole* prompt — that is,
`local` and `api`. A harness's real input is mostly invisible to us, so an
estimate of it would be a fabricated number that looks exactly like a measured
one. There, no count is reported and the character counts carry the comparison.
"""

import math
from dataclasses import dataclass, field

#: Characters per token, for the estimate. Four is the customary English and
#: JSON figure, and it is a *proxy*: it is only ever used to fill `estimated`
#: rows, which no measured mean is allowed to read.
CHARS_PER_TOKEN = 4.0


@dataclass
class Reply:
    """One answer, with everything known about what it cost."""

    text: str = ""
    model: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_total: int | None = None
    usage: str = "none"
    finish_reason: str = ""
    usd: float | None = None
    #: Characters we sent and characters that came back. Recorded for *every*
    #: reply including the ones nobody metered, because it is the one cost
    #: figure that is identical in meaning across all three transports.
    brief_chars: int = 0
    reply_chars: int = 0
    runtime: dict = field(default_factory=dict)

    @property
    def metered(self) -> bool:
        """Did anybody actually count? `estimated` is not a count."""
        return self.usage in ("reported", "reported_total")


def estimate_tokens(text: str) -> int:
    """A labelled approximation, never a measurement. See the module docstring."""
    return max(1, int(math.ceil(len(text or "") / CHARS_PER_TOKEN)))


class NoSocket(RuntimeError):
    """This candidate cannot be reached here, and the reason is the message.

    A distinct type because the answer is a row a reader acts on — "the local
    server does not list qwen3.5:4b", "no key for anthropic" — not a crash.
    """


class LocalSocket:
    """A model on this machine, over its OpenAI-compatible endpoint.

    Deliberately the plain socket rather than the app's local *pipeline*: the
    pipeline is what Kriko does around a model (triage, evidence selection, the
    grounding gate), and this benchmark measures the model. A pipeline that
    rescues a weak model would otherwise be scored as a strong one.
    """

    def __init__(self, candidate, *, app_state_path=None, timeout: float = 300.0,
                 max_tokens: int | None = 1024, temperature: float = 0.0,
                 check_cancelled=None):
        from app import localplane
        from app.providers.local_inference import OpenAICompatSocket

        resolved = localplane.resolve(app_state_path, with_search=False)
        if not resolved.get("ready"):
            raise NoSocket(
                f"no local model server is ready: {resolved.get('reason') or 'not found'}"
            )
        models = [str(one) for one in resolved.get("models") or []]
        if candidate.model not in models:
            raise NoSocket(
                f"{resolved.get('name') or 'the local server'} does not list "
                f"{candidate.model!r}; it lists: {', '.join(models) or 'nothing'}"
            )
        self.model = candidate.model
        self._socket = OpenAICompatSocket(
            candidate.base_url or str(resolved.get("url") or ""),
            candidate.model,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            context_tokens=resolved.get("context_tokens"),
            runtime_options=resolved.get("runtime_options") or {},
        )
        if check_cancelled is not None:
            self._socket.set_cancel_check(check_cancelled)

    def answer(self, prompt: str) -> Reply:
        text = self._socket.complete(prompt)
        socket = self._socket
        tokens_in = _int_or_none(getattr(socket, "tokens_in", None))
        tokens_out = _int_or_none(getattr(socket, "tokens_out", None))
        total = _int_or_none(getattr(socket, "tokens_used", None))
        if total is None and (tokens_in is not None or tokens_out is not None):
            total = (tokens_in or 0) + (tokens_out or 0)
        complete = getattr(socket, "usage_complete", True)
        if tokens_in is not None or tokens_out is not None:
            usage = "reported"
        elif isinstance(total, int) and not complete:
            # A total nobody can split. Kept, and named for what it is.
            usage = "reported_total"
        else:
            # Nobody counted, and we saw the whole prompt, so an estimate is
            # honest here in a way it never is for a CLI.
            tokens_in = estimate_tokens(prompt)
            tokens_out = estimate_tokens(text)
            total = tokens_in + tokens_out
            usage = "estimated"
        return Reply(
            text=text, model=self.model,
            tokens_in=tokens_in, tokens_out=tokens_out, tokens_total=total,
            usage=usage,
            finish_reason=str(getattr(socket, "last_finish_reason", "") or ""),
            brief_chars=len(prompt or ""), reply_chars=len(text or ""),
            runtime={"endpoint": getattr(socket, "base_url", "")},
        )


class ApiSocket:
    """A paid per-token endpoint, over the catalogue's routing table.

    The price comes from the reader's own `models.toml`, so a gateway's rates
    are whatever the reader corrected them to rather than a number compiled in
    here — and a model with no row reports tokens and no dollars, which is the
    difference between "free" and "unknown".
    """

    def __init__(self, candidate, *, max_tokens: int | None = 1024):
        from app.providers import MissingKey, completer_for

        try:
            self._complete = completer_for(candidate.model, max_tokens=max_tokens)
        except MissingKey as exc:
            raise NoSocket(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — an unreachable endpoint is a row
            raise NoSocket(f"{type(exc).__name__}: {exc}") from exc
        self.model = candidate.model

    def answer(self, prompt: str) -> Reply:
        from app import modelcatalogue

        text = self._complete(prompt)
        complete = self._complete
        tokens_in = _int_or_none(getattr(complete, "tokens_in", None))
        tokens_out = _int_or_none(getattr(complete, "tokens_out", None))
        total = _int_or_none(getattr(complete, "tokens_used", None))
        if total is None and (tokens_in is not None or tokens_out is not None):
            total = (tokens_in or 0) + (tokens_out or 0)
        if tokens_in is not None or tokens_out is not None:
            usage = "reported"
        elif total is not None:
            usage = "reported_total"
        else:
            tokens_in = estimate_tokens(prompt)
            tokens_out = estimate_tokens(text)
            total = tokens_in + tokens_out
            usage = "estimated"
        usd = None
        if tokens_in is not None and tokens_out is not None:
            usd = modelcatalogue.price(self.model, tokens_in, tokens_out)
        return Reply(
            text=text, model=self.model,
            tokens_in=tokens_in, tokens_out=tokens_out, tokens_total=total,
            usage=usage, usd=usd,
            finish_reason=str(getattr(complete, "last_finish_reason", "") or ""),
            brief_chars=len(prompt or ""), reply_chars=len(text or ""),
        )


class HarnessSocket:
    """A coding-agent CLI, driven the way the app drives it.

    Reusing `HarnessResearcher` rather than spawning the binary here is not
    laziness: that class owns everything hard about a CLI — which flags this
    build actually has, how to read a stream-json envelope, how to unwrap
    Mistral's reply, how to meter a session that reports no usage on its own
    stream. A second spawn path would drift from it and measure a different
    thing than the app runs.

    Its `tokens_used` is the whole session, so it is reported as
    `reported_total` and never split into halves we did not see.
    """

    def __init__(self, candidate, *, app_state_path=None, timeout: float = 300.0,
                 check_cancelled=None):
        from app.providers import harness_researcher

        harness_id = candidate.harness or ""
        available = _harness_ids()
        if harness_id and harness_id not in available:
            raise NoSocket(
                f"no coding-agent CLI named {harness_id!r} on this machine; "
                f"found: {', '.join(available) or 'none'}"
            )
        self.model = candidate.model or harness_id
        self._researcher = harness_researcher(
            preferred=harness_id,
            timeout=timeout,
            app_state_path=app_state_path,
            model=candidate.model,
        )
        if check_cancelled is not None:
            # The CLI's stream polls this once per line. It is the only thing
            # that may interrupt a child process mid-run.
            self._researcher.check_cancelled = check_cancelled

    def answer(self, prompt: str) -> Reply:
        researcher = self._researcher
        text = researcher.ask(prompt)
        total = _int_or_none(getattr(researcher, "tokens_used", None))
        tokens_in = _int_or_none(getattr(researcher, "tokens_in", None))
        tokens_out = _int_or_none(getattr(researcher, "tokens_out", None))
        if tokens_in is not None or tokens_out is not None:
            usage = "reported"
            if total is None:
                total = (tokens_in or 0) + (tokens_out or 0)
        elif total is not None:
            usage = "reported_total"
        else:
            # No estimate: the CLI's real prompt is mostly its own, and a
            # fabricated input count would look exactly like a measured one.
            usage = "none"
        return Reply(
            text=text, model=str(getattr(researcher, "model", "") or self.model),
            tokens_in=tokens_in, tokens_out=tokens_out, tokens_total=total,
            usage=usage,
            finish_reason=str(getattr(researcher, "last_finish_reason", "") or ""),
            brief_chars=len(prompt or ""), reply_chars=len(text or ""),
            runtime={"harness": str(getattr(getattr(researcher, "harness", None),
                                           "id", ""))},
        )


def socket_for(candidate, *, app_state_path=None, timeout: float = 300.0,
               max_tokens: int | None = 1024, temperature: float = 0.0,
               check_cancelled=None):
    """The transport for this candidate, or `NoSocket` saying why not.

    Every branch raises the same type for the same reason, so the runner has
    one failure to turn into a row and the report has one sentence to print.
    """
    if candidate.kind == "local":
        return LocalSocket(candidate, app_state_path=app_state_path, timeout=timeout,
                           max_tokens=max_tokens, temperature=temperature,
                           check_cancelled=check_cancelled)
    if candidate.kind == "api":
        return ApiSocket(candidate, max_tokens=max_tokens)
    if candidate.kind == "harness":
        return HarnessSocket(candidate, app_state_path=app_state_path,
                             timeout=timeout, check_cancelled=check_cancelled)
    raise NoSocket(f"no transport for candidate kind {candidate.kind!r}")


def _harness_ids() -> list[str]:
    try:
        from app.providers import harness

        return [str(getattr(one, "id", "")) for one in harness.available()]
    except Exception:  # noqa: BLE001 — an unreachable CLI list is an empty list
        return []


def _int_or_none(value) -> int | None:
    """`None` for anything that is not an honest integer.

    `bool` is an `int` in Python, and `True` tokens is not a measurement.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
