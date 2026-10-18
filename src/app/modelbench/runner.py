"""One candidate, one case, one repetition — measured, or failed as a row.

The runner's whole contract is short and load-bearing:

* **Nothing raises.** Except cancellation, which must, because a reader who
  pressed stop is not a measurement. Every other failure — a server that is
  not running, a CLI that is not logged in, a reply that is not JSON, a
  request that never returns — becomes a `Measurement` carrying an `error`.
  A benchmark that raised would lose the rows it had already paid for and
  would report a plane as absent instead of as broken, which is the exact
  distinction the reader needs.
* **The prompt is built once per case and shared.** `corpus.prompt` is pure, so
  every candidate in a sweep sees byte-identical text; the fingerprint travels
  with the row so a reader can prove it after the fact.
* **The clock covers the whole exchange.** Not the socket call alone: a harness
  CLI has to start a process, and that cost is real to whoever waits for the
  answer on a phone.
"""

import time
from dataclasses import dataclass, field

from app.modelbench import corpus, metrics
from app.modelbench.sockets import NoSocket, Reply, socket_for


@dataclass
class Measurement:
    """One row: what was asked, what came back, what it cost, whether it worked."""

    candidate_id: str = ""
    candidate_label: str = ""
    kind: str = ""
    model: str = ""
    harness: str = ""
    case_id: str = ""
    dimension: str = ""
    set_id: str = ""
    set_version: str = ""
    prompt_fingerprint: str = ""
    prompt_chars: int = 0
    rep: int = 1
    ms: int | None = None
    error: str = ""
    #: The transport's own account of the exchange, kept whole so nothing the
    #: socket learned is lost between here and the report.
    reply: Reply = field(default_factory=Reply)
    #: The scored answer. Empty lists and `None`s on a failed row, never zeros:
    #: a failure has no recall, and 0.0 would read as "answered, found nothing".
    score: dict = field(default_factory=dict)
    answer_key: dict = field(default_factory=dict)
    #: Only present when the caller asked for it. A reply is useful for reading
    #: one failure closely and is a liability in a stored table, so it is opt-in
    #: rather than always on.
    text: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.error)

    @property
    def graded(self) -> bool:
        """Did this row produce something a score can be computed from?"""
        return not self.failed and bool(self.score)

    def as_dict(self, *, with_text: bool = False) -> dict:
        out = {
            "candidate": self.candidate_id,
            "candidate_label": self.candidate_label,
            "kind": self.kind,
            "model": self.model,
            "harness": self.harness,
            "case": self.case_id,
            "dimension": self.dimension,
            "set_id": self.set_id,
            "set_version": self.set_version,
            "prompt_fingerprint": self.prompt_fingerprint,
            "prompt_chars": self.prompt_chars,
            "rep": self.rep,
            "ms": self.ms,
            "error": self.error,
            "tokens_in": self.reply.tokens_in,
            "tokens_out": self.reply.tokens_out,
            "tokens_total": self.reply.tokens_total,
            "usage": self.reply.usage,
            "usd": self.reply.usd,
            "finish_reason": self.reply.finish_reason,
            "brief_chars": self.reply.brief_chars,
            "reply_chars": self.reply.reply_chars,
            "score": dict(self.score),
        }
        if with_text:
            out["text"] = self.text
        return out


def run_case(candidate, case: dict, *, rep: int = 1, app_state_path=None,
             timeout: float = 300.0, max_tokens: int | None = 1024,
             temperature: float = 0.0, check_cancelled=None,
             with_text: bool = False) -> Measurement:
    """Measure `candidate` on `case` once.

    `app_state_path` is read, never written: a harness CLI is asked which model
    the reader configured for it, and the local server is asked what it serves.
    A benchmark that changed either would be measuring its own side effects.
    """
    from app.web.jobs import Cancelled

    prompt = corpus.prompt(case)
    row = Measurement(
        candidate_id=candidate.id,
        candidate_label=candidate.label,
        kind=candidate.kind,
        model=candidate.model or candidate.harness,
        harness=candidate.harness,
        case_id=str(case.get("id") or ""),
        dimension=str(case.get("dimension") or ""),
        set_id=str(case.get("set_id") or ""),
        set_version=str(case.get("set_version") or ""),
        prompt_fingerprint=corpus.prompt_fingerprint(case),
        prompt_chars=len(prompt),
        rep=rep,
        answer_key=corpus.answer_key(case),
    )
    if check_cancelled is not None:
        check_cancelled()
    started = time.perf_counter()
    socket = None
    try:
        socket = socket_for(candidate, app_state_path=app_state_path,
                            timeout=timeout, max_tokens=max_tokens,
                            temperature=temperature, check_cancelled=check_cancelled)
        if check_cancelled is not None:
            check_cancelled()
        reply = socket.answer(prompt)
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 — a failed case is a measurement
        row.ms = int((time.perf_counter() - started) * 1000)
        row.error = f"{type(exc).__name__}: {exc}"
        # Salvage a count the transport managed before it gave up. A run that
        # spent 40k tokens and then timed out spent them, and dropping that
        # would make the slowest, most expensive failure look free.
        row.reply = _salvage(socket, prompt)
        return row

    row.ms = int((time.perf_counter() - started) * 1000)
    row.reply = reply
    row.text = reply.text if with_text else ""
    if not (reply.text or "").strip():
        # An empty answer is scored, not thrown away: it is the honest result of
        # a model that produced nothing, and on an abstention case it may even
        # be correct. `metrics.verdict` decides that, not this function.
        row.error = ""
    row.score = metrics.verdict(case, reply.text, corpus.documents(case))
    return row


def _salvage(socket, prompt: str) -> Reply:
    """Whatever the transport had already counted when it failed.

    Duck-typed like the rest of this package: a socket that never got far
    enough to own those attributes yields an empty `Reply`, which reads as
    "nobody counted" rather than as zero.
    """
    if socket is None:
        return Reply()
    inner = getattr(socket, "_socket", None) or getattr(socket, "_complete", None)
    source = inner if inner is not None else socket
    tokens_in = _int_or_none(getattr(source, "tokens_in", None))
    tokens_out = _int_or_none(getattr(source, "tokens_out", None))
    total = _int_or_none(getattr(source, "tokens_used", None))
    if total is None and (tokens_in is not None or tokens_out is not None):
        total = (tokens_in or 0) + (tokens_out or 0)
    if tokens_in is None and tokens_out is None and total is None:
        return Reply(brief_chars=len(prompt or ""))
    usage = ("reported" if tokens_in is not None or tokens_out is not None
             else "reported_total")
    return Reply(
        model=str(getattr(source, "model", "") or ""),
        tokens_in=tokens_in, tokens_out=tokens_out, tokens_total=total,
        usage=usage, brief_chars=len(prompt or ""),
        finish_reason=str(getattr(source, "last_finish_reason", "") or ""),
    )


def _int_or_none(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


__all__ = ["Measurement", "NoSocket", "run_case"]
