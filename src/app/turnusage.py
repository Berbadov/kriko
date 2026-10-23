"""Account for all requests in one conversational turn, including metadata.

The reader asked for "token count plus context window bars". A chat turn makes
several calls (the words to search, the answer, the labels), so this adds them
up, keeps each call's own record, and says what it knows and what it does not:

- `tokens_in` and `tokens_out` are summed only when **every** call reported
  both. A plane that reports a total and no split (some harness CLIs) leaves
  them `None`: the screen says "not reported", it does not guess.
- The context bar's *used* number is the largest prompt one call of the turn
  was sent (`peak_in`), which is a measurement. It is never an estimate made
  from characters; there is no ratio in this file.
- The window is the model's, from the catalogue (`models.toml`) or, for the
  model on this machine, the context the server was asked to hold. A model
  the catalogue has no row for has no window, and the bar says so.

The result fields (names are stable, the screens read them):

    spent_usd, tokens                 totals, `None` unless every call reported
    tokens_in, tokens_out             the split, `None` unless every call had one
    usage                             `calls`, `priced_calls`, `split_calls`,
                                      `measured_usd`, `measured_tokens`,
                                      `peak_in`, `complete`, `per_call` (one
                                      `{usd, tokens, tokens_in, tokens_out}` each)
    context                           `model`, `window`, `window_source`
                                      (`catalogue` or `setting`), `used`,
                                      `state` (`measured`, `not_reported`,
                                      `pending`), `fill` (0 to 1 or `None`),
                                      and `history`: `messages`, `sent`,
                                      `trimmed`, `dropped_replies`,
                                      `omitted_requests`

A job's snapshots and result carry all of these. A saved chat's agent
messages carry the same fields under `spend`, read back from the job that
answered, so nothing is stored twice.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from kriko.research import BudgetExceeded


def _count(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


@dataclass
class TurnUsage:
    budget: float = 0.5
    measured_usd: float = 0.0
    measured_tokens: int = 0
    priced: int = 0
    tokenized: int = 0
    calls: int = 0
    measured_in: int = 0
    measured_out: int = 0
    split: int = 0
    peak_in: int | None = None
    per_call: list[dict] = field(default_factory=list)

    def parameters(self, params: dict) -> dict:
        remaining = self.budget - self.measured_usd
        if remaining <= 0:
            raise BudgetExceeded("The conversation turn reached its spending limit; no further request was sent.")
        return {**params, "budget_usd": remaining}

    def record(self, usage: dict) -> None:
        self.calls += 1
        usd, tokens = usage.get("usd"), _count(usage.get("tokens"))
        tin, tout = _count(usage.get("tokens_in")), _count(usage.get("tokens_out"))
        if isinstance(usd, (int, float)) and usd >= 0:
            self.measured_usd += usd
            self.priced += 1
        if tokens is not None:
            self.measured_tokens += tokens
            self.tokenized += 1
        elif tin is not None and tout is not None:
            # A plane that reports the split and no total still counted them.
            tokens = tin + tout
            self.measured_tokens += tokens
            self.tokenized += 1
        if tin is not None and tout is not None:
            self.measured_in += tin
            self.measured_out += tout
            self.split += 1
            self.peak_in = tin if self.peak_in is None else max(self.peak_in, tin)
        self.per_call.append({
            "usd": round(usd, 6) if isinstance(usd, (int, float)) and usd >= 0 else None,
            "tokens": tokens,
            "tokens_in": tin, "tokens_out": tout})

    def snapshot(self) -> dict:
        every = bool(self.calls)
        return {"spent_usd": round(self.measured_usd, 6) if every and self.priced == self.calls else None,
                "tokens": self.measured_tokens if every and self.tokenized == self.calls else None,
                "tokens_in": self.measured_in if every and self.split == self.calls else None,
                "tokens_out": self.measured_out if every and self.split == self.calls else None,
                "usage": {"calls": self.calls, "priced_calls": self.priced,
                          "split_calls": self.split,
                          "measured_usd": round(self.measured_usd, 6),
                          "measured_tokens": self.measured_tokens,
                          "peak_in": self.peak_in,
                          "complete": every and self.priced == self.calls and self.tokenized == self.calls,
                          "per_call": [dict(one) for one in self.per_call]}}

    def context(self, model: str = "", *, history: Sequence[dict] = (), home=None,
                local_window: int | None = None) -> dict:
        """What the context bar draws: how full the model's window is, and how
        the history sent to it was trimmed. `local_window` is the context the
        model on this machine was asked to hold, used only for that model."""
        window, source = window_for(model, home=home, local_window=local_window)
        if self.peak_in is not None:
            state = "measured"
        elif self.calls:
            state = "not_reported"
        else:
            state = "pending"
        return {"model": model, "window": window, "window_source": source,
                "used": self.peak_in, "state": state,
                "fill": round(self.peak_in / window, 4) if self.peak_in is not None and window else None,
                "history": history_trim(history)}


def usage_of(researcher) -> dict:
    """One call's usage as the plane reports it, read from the researcher.

    `usd` and `tokens` as before; `tokens_in` and `tokens_out` where the plane
    splits them: an API agent or the local model says so itself, and a harness
    CLI says it in the run's own context counts (input, cache writes and cache
    reads in; output out). Anything it does not say stays `None`.
    """
    out = {"usd": getattr(researcher, "spent", getattr(researcher, "cost_usd", None)),
           "tokens": getattr(researcher, "tokens_used", None),
           "tokens_in": getattr(researcher, "tokens_in", None),
           "tokens_out": getattr(researcher, "tokens_out", None)}
    if out["tokens_in"] is None or out["tokens_out"] is None:
        run = (getattr(researcher, "telemetry", None) or {}).get("run") or {}
        counts = run.get("context") if isinstance(run, dict) else None
        if isinstance(counts, dict):
            parts = [_count(counts.get(key)) for key in
                     ("input_tokens", "cache_creation_tokens", "cache_read_tokens")]
            written = _count(counts.get("output_tokens"))
            if written is not None and any(one is not None for one in parts):
                out["tokens_in"] = sum(one or 0 for one in parts)
                out["tokens_out"] = written
    return out


def window_for(model: str, *, home=None, local_window: int | None = None) -> tuple[int | None, str]:
    """`(tokens, where it came from)`, or `(None, "")` when nobody knows.

    The catalogue wins, because its row is the reader's own correction of a
    shipped number; the setting is for the model on this machine, whose window
    is whatever it was asked to hold. Nothing here names a model.
    """
    from app import modelcatalogue

    row = modelcatalogue.load(home).get(model) if model else None
    size = _count((row or {}).get("context"))
    if size:
        return size, "catalogue"
    if local_window:
        return local_window, "setting"
    return None, ""


def history_trim(history: Sequence[dict]) -> dict:
    """How much of the saved conversation the agent is shown, by `chat.py`'s own limits.

    Read-only on the same cut `chat._history_text` makes (`chat.split_history`):
    replies older than the newest messages that fit `HISTORY_BUDGET` are not
    sent again, and an older request is left out when it no longer fits.
    """
    from app import chat

    messages = len(history)
    recent, older = chat.split_history(history)
    recent_text = "\n".join(
        f"{'Reader' if one.get('role') == 'reader' else 'Agent'}: "
        f"{chat._clip(one.get('text', ''), chat.HISTORY_CHARS)}" for one in recent)
    budget = max(0, chat.HISTORY_BUDGET - len(recent_text))
    omitted = 0
    for one in older:
        if one.get("role") != "reader":
            continue
        line = "Reader: " + chat._clip(one.get("text", ""), chat.HISTORY_CHARS)
        if len(line) + 1 <= budget:
            budget -= len(line) + 1
        else:
            omitted += 1
    dropped = sum(1 for one in older if one.get("role") != "reader")
    return {"messages": messages, "sent": messages - dropped - omitted,
            "trimmed": bool(dropped or omitted),
            "dropped_replies": dropped, "omitted_requests": omitted}
