"""The politeness scheduler: one gate in front of every network socket.

Two rules the reader set, and this module is where they become mechanics
rather than hopes:

  * **Fail fast.** A socket that answers with a block page must not be
    waited on. The caller marks the source hot, rotates to the next one,
    and the hot one cools down on its own.
  * **Stay polite.** No provider sees a burst. A global budget on in-flight
    requests plus a per-source token bucket with jitter keeps the walking
    pace regardless of how many queries a run wants.

Nothing here knows what a query is, what a category is, or what a search
engine is. Sources are names a caller supplies; the scheduler decides only
*when* and *which*. That is the same split as `Spend` in `base.py`: the
shape lives in the engine, the choosing does not.

No thread, no loop, no asyncio: a synchronous machine whose `acquire`
computes the soonest legal moment and sleeps until then. A scheduler that
needs an event loop to enforce politeness is a scheduler a plain script
will bypass.
"""

import random
import time
from dataclasses import dataclass

#: Seconds a source sits out after answering with a block, challenge or
#: empty page. Long enough that a provider's hot-window clears; short enough
#: that a run with several sources never stalls on one of them being rude.
COOLDOWN_SECONDS = 900.0

#: How many requests may be in flight across ALL sources at once. Two, not
#: one: a rotate-on-fail needs a second slot to move into without waiting,
#: and more than two is a walking pace turning into a burst.
MAX_IN_FLIGHT = 2

#: Default per-source rate: one request per 3.5 seconds, jittered ±25%.
DEFAULT_MIN_INTERVAL = 3.5
_JITTER = 0.25

#: How long `acquire` may sleep before returning control. The caller
#: retries; politeness is enforced across retries, not by holding a lock
#: for minutes.
_MAX_SLEEP = 20.0

_BLOCK_MARKERS = (
    "captcha", "challenge", "unusual traffic", "are you a robot",
    "verify you are a human", "access denied", "blocked",
    "attention required",
)


#: The canonical "this source answered with a challenge" signal, raised by
#: whatever socket the plane was handed and caught by the plane itself.
#: Defined here — the politeness module — because both sides need it and the
#: engine is the layer they share: a provider's search adapter raises it,
#: the plane's except clause reads it, and a second copy anywhere would let
#: a block page arrive as an ordinary failure, which is the bug this class
#: exists to prevent.
class LocalSearchError(RuntimeError):
    """The source answered with a challenge rather than results. Rotate."""


@dataclass
class _Source:
    name: str
    interval: float
    next_ready: float = 0.0
    hot_until: float = 0.0
    failures: int = 0

    @property
    def available(self) -> bool:
        now = time.monotonic()
        return now >= self.next_ready and now >= self.hot_until


class PolitenessScheduler:
    """One gate for every outbound request a run makes.

    Construct with source names and per-source intervals; call `acquire`
    before any request and `report` after. `acquire` never raises on a hot
    source — it returns the *next available* source instead, which is the
    fail-fast rule: a blocked provider costs the run one rotation, not a
    wait.

    Intervals are enforced with monotonic-clock token times rather than a
    counter, so a run that pauses for ten minutes (a person reading, a
    batch between subjects) does not bank credit it never paid for.
    """

    def __init__(self, sources: dict[str, float] | None = None,
                 max_in_flight: int = MAX_IN_FLIGHT,
                 cooldown: float = COOLDOWN_SECONDS):
        if not sources:
            raise ValueError("a scheduler needs at least one source")
        self._sources: dict[str, _Source] = {
            name: _Source(name=name, interval=max(0.0, float(interval)))
            for name, interval in sources.items()
        }
        self._order = list(self._sources)
        self._max_in_flight = max(1, int(max_in_flight))
        self._cooldown = max(0.0, float(cooldown))
        self._in_flight = 0
        self._cursor = 0
        self.stats = {
            "requests": 0, "rotations": 0, "blocked": 0,
            "cooled_down": 0,
        }

    def acquire(self, preferred: str = "") -> tuple[str, float]:
        """The source to use now, and how long to sleep before sending.

        The sleep is the caller's job on purpose: a scheduler that sleeps
        internally cannot be tested with a fake clock and cannot let a
        caller interleave cancellation checks. The returned delay is capped
        at `_MAX_SLEEP`, so a long queue is a series of short waits with
        the caller deciding whether to continue, never a held lock.

        `preferred` is a hint, not a promise. When the preferred source is
        hot or spent, the rotation picks the next available one — the
        fail-fast rule outranks the caller's preference.
        """
        self._in_flight += 1
        try:
            if self._in_flight > self._max_in_flight:
                self._in_flight -= 1
                return ("", min(_MAX_SLEEP, self._soonest_ready()))
            source = self._pick(preferred)
            if source is None:
                self._in_flight -= 1
                return ("", min(_MAX_SLEEP, self._soonest_ready()))
            delay = max(0.0, source.next_ready - time.monotonic())
            if delay > 0:
                jitter = random.uniform(-_JITTER, _JITTER) * source.interval
                delay = max(0.0, delay + jitter)
            source.next_ready = time.monotonic() + source.interval
            self.stats["requests"] += 1
            return (source.name, delay)
        except Exception:
            self._in_flight -= 1
            raise

    def release(self) -> None:
        """One in-flight slot returned. Call after the request, always."""
        self._in_flight = max(0, self._in_flight - 1)

    def report(self, source: str, *, blocked: bool = False,
               failed: bool = False) -> None:
        """What the request saw. The scheduler decides the consequences."""
        entry = self._sources.get(source)
        if entry is None:
            return
        if blocked:
            entry.hot_until = time.monotonic() + self._cooldown
            entry.failures += 1
            self.stats["blocked"] += 1
            self.stats["cooled_down"] += 1
        elif failed:
            entry.failures += 1
        else:
            entry.failures = 0

    def is_hot(self, source: str) -> bool:
        entry = self._sources.get(source)
        return bool(entry and time.monotonic() < entry.hot_until)

    def _pick(self, preferred: str) -> _Source | None:
        now = time.monotonic()
        for offset in range(len(self._order)):
            name = self._order[(self._cursor + offset) % len(self._order)]
            entry = self._sources[name]
            if now >= entry.next_ready and now >= entry.hot_until:
                self._cursor = (self._cursor + offset + 1) % len(self._order)
                if name != preferred:
                    self.stats["rotations"] += 1
                return entry
        return None

    def _soonest_ready(self) -> float:
        ready = [entry.next_ready for entry in self._sources.values()
                 if time.monotonic() < entry.hot_until + 0
                 or entry.hot_until <= time.monotonic()]
        candidates = [entry.next_ready for entry in self._sources.values()
                      if entry.hot_until <= time.monotonic()]
        return (min(candidates) - time.monotonic()) if candidates else (
            min(ready) - time.monotonic() if ready else 1.0)


def looks_blocked(status: int, body: str = "") -> bool:
    """Whether an HTTP reply is a challenge rather than an answer.

    Status first — a 403 or 429 is a provider saying "stop" in band, and
    in-band words are read before page words. Then markers, casefolded,
    because block pages are generated from templates, not literature.
    Only the first 4 KB is read: a challenge page is small, and scanning a
    full document for the word "blocked" would flag every forum thread
    that mentions one.
    """
    if status in (401, 403, 429) or 500 <= status < 600:
        return False if status >= 500 else True
    if not body:
        return False
    head = body[:4096].casefold()
    return any(marker in head for marker in _BLOCK_MARKERS)
