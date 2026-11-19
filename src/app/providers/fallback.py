"""Which agent answers when the first one cannot: failure classes, the breaker,
and the research plane that moves a run from one agent to the next.

In memory, per process, on purpose. A cooldown lasts minutes and a restart
costs at most one more failed attempt, so persisting it would buy a schema
change for little, the same reason the resident-session and account caches are
module state (`harness.py`).
"""

import re
import threading
import time
from dataclasses import dataclass, field

LIMIT = "limit"
AUTH = "auth"
START = "start"
TIMEOUT = "timeout"
NETWORK = "network"

FAILURES_TO_OPEN = 3
FAILURE_WINDOW_SECONDS = 300.0
BASE_COOLDOWN_SECONDS = 60.0
LIMIT_COOLDOWN_SECONDS = 600.0
SIGN_IN_COOLDOWN_SECONDS = 600.0
MAX_COOLDOWN_SECONDS = 1800.0

_AUTH_NEEDLES = ("not logged in", "please run /login", "unauthorized", "authentication",
                 "invalid api key", "oauth", "sign in again", "log in again",
                 "refresh token", "missingkey")
_LIMIT_NEEDLES = ("usage limit", "rate limit", "limit reached", "quota", "5-hour limit",
                  "weekly limit", "hit your", "credit balance", "budget exhausted")
_START_NEEDLES = ("enoent", "not recognized", "cannot find the path", "not on path",
                  "not installed", "did not initialize", "did not start", "not responding")
_TIMEOUT_NEEDLES = ("did not finish within", "timed out", "timeout")
_SERVER = re.compile(r"\b(?:http|status|error)\D{0,12}5\d\d\b|bad gateway|"
                     r"service unavailable|connection refused|connection reset|"
                     r"network is unreachable")

REASONS = {
    LIMIT: "its account hit a usage or billing limit",
    AUTH: "it is not signed in",
    START: "it did not start",
    TIMEOUT: "it timed out before answering",
    NETWORK: "its provider failed (network or server error)",
}


def classify(error: BaseException) -> str:
    """The failure class a run may fall over on, or `""` for any other error.

    Cancellation and the run's own budget stop are never a reason to change
    agent, and neither is a content or validation error: another agent would
    fail the same way or the reader asked for the stop.
    """
    name = type(error).__name__.lower()
    if getattr(error, "cancelled", False) or "cancel" in name or "budget" in name:
        return ""
    if isinstance(error, TimeoutError):
        return TIMEOUT
    if isinstance(error, ConnectionError):
        return NETWORK
    low = str(error).lower()
    if any(needle in low for needle in _AUTH_NEEDLES):
        return AUTH
    if any(needle in low for needle in _LIMIT_NEEDLES):
        return LIMIT
    if any(needle in low for needle in _START_NEEDLES):
        return START
    if any(needle in low for needle in _TIMEOUT_NEEDLES):
        return TIMEOUT
    if _SERVER.search(low):
        return NETWORK
    return ""


@dataclass
class _Health:
    until: float = 0.0
    state: str = ""
    reason: str = ""
    opens: int = 0
    recent: list[float] = field(default_factory=list)


class Breakers:
    """Per-agent health: an agent is skipped from `until` on, then probed.

    A limit or a sign-in failure opens at once. Start, timeout and network
    failures open after `FAILURES_TO_OPEN` within the window. The cooldown
    doubles with each opening, up to a cap, and a success forgets it all.
    """

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._health: dict[str, _Health] = {}
        self._lock = threading.Lock()

    def available(self, agent_id: str) -> bool:
        health = self._health.get(agent_id)
        return health is None or self._clock() >= health.until

    def record_success(self, agent_id: str) -> None:
        with self._lock:
            self._health.pop(agent_id, None)

    def record_failure(self, agent_id: str, failure: str, reason: str = "") -> None:
        now = self._clock()
        with self._lock:
            health = self._health.setdefault(agent_id, _Health())
            if failure in (LIMIT, AUTH):
                health.opens += 1
                base = LIMIT_COOLDOWN_SECONDS if failure == LIMIT else SIGN_IN_COOLDOWN_SECONDS
                span = base if failure == AUTH else min(
                    base * 2 ** (health.opens - 1), MAX_COOLDOWN_SECONDS)
            else:
                probing = health.opens > 0 and now >= health.until
                health.recent = [at for at in health.recent
                                 if now - at < FAILURE_WINDOW_SECONDS] + [now]
                if not probing and len(health.recent) < FAILURES_TO_OPEN:
                    return
                health.opens += 1
                health.recent = []
                span = min(BASE_COOLDOWN_SECONDS * 2 ** (health.opens - 1),
                           MAX_COOLDOWN_SECONDS)
            health.until = now + span
            health.state = "signed_out" if failure == AUTH else "cooling"
            health.reason = reason or REASONS.get(failure, failure)

    def status(self, agent_id: str) -> dict:
        health = self._health.get(agent_id)
        if health is None or self._clock() >= health.until:
            return {"state": "ready", "cooling_until": 0.0, "reason": ""}
        return {
            "state": health.state,
            "cooling_until": time.time() + (health.until - self._clock()),
            "reason": health.reason,
        }


BREAKERS = Breakers()


class ChainResearcher:
    """A research plane that moves to the next agent when the current one fails.

    Every call on it is a step. When the agent answering a step fails with a
    class `classify` names, the same call runs again on the next agent that is
    available, and the switch is reported through `on_switch`. A call that
    returned keeps its result, so only the step that failed is repeated.
    """

    def __init__(self, agents, build, *, breakers: Breakers | None = None,
                 on_switch=None) -> None:
        self._agents = list(agents)
        self._build = build
        self._breakers = BREAKERS if breakers is None else breakers
        self._on_switch = on_switch
        self._at = 0
        self._active = None
        self._settings: dict = {}
        self._switches: list[str] = []

    @property
    def answered_by(self):
        return self._agents[self._at]

    def report_switches(self, callback) -> None:
        self._on_switch = callback

    @property
    def switches(self) -> list[str]:
        return list(self._switches)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        value = getattr(self._current(), name)
        if not callable(value):
            return value
        return lambda *args, **kwargs: self._call(name, *args, **kwargs)

    def __setattr__(self, name, value) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        self._settings[name] = value
        if self._active is not None:
            setattr(self._active, name, value)

    def _current(self):
        if self._active is None:
            self._active = self._build(self._agents[self._at])
            for name, value in self._settings.items():
                setattr(self._active, name, value)
        return self._active

    def _call(self, name, *args, **kwargs):
        while True:
            try:
                result = getattr(self._current(), name)(*args, **kwargs)
            except Exception as error:  # noqa: BLE001 - classified below, else re-raised
                if not self._switch(error):
                    raise
                continue
            self._breakers.record_success(self._agents[self._at].id)
            return result

    def _switch(self, error: Exception) -> bool:
        failure = classify(error)
        if not failure:
            return False
        failed = self._agents[self._at]
        self._breakers.record_failure(failed.id, failure, str(error))
        for at in range(self._at + 1, len(self._agents)):
            nxt = self._agents[at]
            if not self._breakers.available(nxt.id):
                continue
            try:
                built = self._build(nxt)
            except Exception:  # noqa: BLE001 - an agent that cannot start is skipped
                continue
            self._at, self._active = at, built
            for name, value in self._settings.items():
                setattr(built, name, value)
            from app.agentledger import redact

            line = (f"Switched to {nxt.label}: {REASONS[failure]}. "
                    f"{failed.label} said: {redact(str(error), limit=160)}")
            self._switches.append(line)
            if self._on_switch is not None:
                self._on_switch(line)
            return True
        return False
