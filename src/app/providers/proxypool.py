"""Rotating proxies for pages that block Kriko's reads. Off unless the reader turns it on.

The reader's words (#271): "rotating proxies for aversion", taken as *evasion*:
pages and search engines that block or rate-limit Kriko's reads, so requests
are spread over a pool. That is a policy decision about other people's sites
and the reader makes it, once, in Settings. So:

* **Off by default**, with a switch that says what it does. Nothing here reads
  a setting that was never written, and a disabled pool is `None`.
* **No list of sites.** What gets routed is decided by what was *measured*: a
  host is routed through the pool only after a direct read of it was refused
  (HTTP 403 or 429) or answered with a bot check, and only for a while
  (`BLOCK_MEMORY`). A site that never blocked Kriko never sees a proxy.
* **No evasion beyond rotation.** No CAPTCHA, login or paywall is touched; a
  page that stays blocked after `MAX_TRIES` different proxies is reported as
  "could not be read" and is not retried. `robots.txt` is honoured before any
  proxied attempt, and the same pacing and per-host limits apply, because the
  request still goes through `network.urlopen`.
* **A failed proxy is retired** for `RETIRE_SECONDS`, then tried again. When no
  healthy proxy is left the read is made directly, and the log says so.
* **Credentials come from the key store** (`keys.PROVIDERS["proxy"]`), as one
  `user:password` that is added to a proxy's address only inside the handler
  that connects to it. The settings hold addresses without credentials, and
  every line written to a log names a proxy by its place in the pool and its
  host, never by its credentials.

Readers consult `shared()`: the pool the saved settings describe, or `None`.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger(__name__)

#: Statuses that mean "this site has decided not to answer Kriko", as opposed to
#: "the site is down". 429 is a rate limit; the reader asked for exactly that
#: to be spread over a pool, and pacing on Kriko's own side still applies.
BLOCK_STATUSES = frozenset({403, 429})

#: A proxy that refuses us, or whose own gateway fails, is the proxy's
#: failure and not the site's.
PROXY_FAILURES = frozenset({407, 502, 504})

#: Different proxies one page is tried through before it is called unreadable.
MAX_TRIES = 3
RETIRE_SECONDS = 300.0
#: How long a measured block routes that host through the pool.
BLOCK_MEMORY = 1800.0
ROBOTS_TTL = 3600.0
MAX_PROXIES = 50

SETTING_ENABLED = "proxy_enabled"
SETTING_POOL = "proxy_pool"

AGENT = "Kriko"


@dataclass(frozen=True)
class Proxy:
    index: int
    address: str  # scheme://host:port, never with credentials


def valid_address(text: str) -> str:
    """`text` as `scheme://host[:port]`, or "" when it is not an http(s) proxy address.

    Credentials in the address are refused rather than stripped: they belong in
    the key store, and silently dropping them would hide a mistake.
    """
    value = str(text or "").strip().rstrip("/")
    try:
        parts = urllib.parse.urlsplit(value)
        _ = parts.port
    except ValueError:
        return ""
    if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment or parts.path):
        return ""
    return value


def parse_pool(text: str) -> list[str]:
    """Addresses from a list typed one per line (commas and spaces also split)."""
    seen: list[str] = []
    for part in str(text or "").replace(",", "\n").split():
        address = valid_address(part)
        if address and address not in seen:
            seen.append(address)
    return seen[:MAX_PROXIES]


def credentials() -> str:
    """The saved `user:password`, or "" (open proxy or one that trusts this address)."""
    from app import keys
    from app.providers import MissingKey

    try:
        return keys.require("proxy")
    except MissingKey:
        return ""


class _State:
    """What the pool has learned, shared by every view of it."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.lock = threading.Lock()
        self.cursor = 0
        self.retired: dict[int, float] = {}
        self.blocked: dict[str, tuple[int, float]] = {}
        self.counts = {"proxied_reads": 0, "direct_fallbacks": 0, "unreadable": 0, "retirements": 0}
        self.robots: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}


class Router:
    """A pool of proxies and what has been measured about the sites it is used for."""

    def __init__(self, addresses: list[str], login: str = "", *,
                 clock: Callable[[], float] = time.monotonic,
                 sink: Callable[[str], Any] | None = None,
                 _state: _State | None = None) -> None:
        self.proxies = [Proxy(index, address) for index, address in enumerate(addresses)]
        self._login = login
        self._state = _state or _State(clock)
        self.sink = sink

    # ── the log ──────────────────────────────────────────────────────────
    def view(self, sink: Callable[[str], Any] | None) -> "Router":
        """The same pool and memory, writing its lines to `sink` (a job's log)."""
        other = copy.copy(self)
        other.sink = sink
        return other

    def scrub(self, text: object) -> str:
        out = " ".join(str(text or "").split())
        for secret in {self._login, *self._login.split(":", 1)}:
            if len(secret) >= 3:
                out = out.replace(secret, "[login]")
                out = out.replace(urllib.parse.quote(secret, safe=""), "[login]")
        return out[:240]

    def say(self, line: str) -> None:
        text = self.scrub(line)
        log.info("%s", text)
        if self.sink is not None:
            try:
                self.sink(text)
            except Exception:  # noqa: BLE001 - a log line never fails a read
                pass

    def label(self, proxy: Proxy) -> str:
        host = urllib.parse.urlsplit(proxy.address).netloc
        return f"proxy {proxy.index + 1} of {len(self.proxies)} ({host})"

    # ── what was measured ────────────────────────────────────────────────
    def should_route(self, host: str) -> bool:
        """Whether a direct read of this host was measured as blocked, recently."""
        state = self._state
        with state.lock:
            seen = state.blocked.get(host.casefold())
            return seen is not None and state.clock() - seen[1] < BLOCK_MEMORY

    def note_blocked(self, host: str) -> None:
        state = self._state
        with state.lock:
            count, _ = state.blocked.get(host.casefold(), (0, 0.0))
            state.blocked[host.casefold()] = (count + 1, state.clock())
        if count == 0:
            self.say(f"{host} refused a direct read; its pages are read through the pool for a while")

    def note_clear(self, host: str) -> None:
        """A direct read worked: the block is over, so the pool stops being used for it."""
        state = self._state
        with state.lock:
            state.blocked.pop(host.casefold(), None)

    def note(self, counter: str) -> None:
        with self._state.lock:
            self._state.counts[counter] = self._state.counts.get(counter, 0) + 1

    # ── the pool ─────────────────────────────────────────────────────────
    def retire(self, proxy: Proxy, why: object) -> None:
        state = self._state
        with state.lock:
            state.retired[proxy.index] = state.clock() + RETIRE_SECONDS
            state.counts["retirements"] += 1
        self.say(f"{self.label(proxy)} failed ({self.scrub(why)}); not used for {int(RETIRE_SECONDS)} s")

    def healthy(self) -> list[Proxy]:
        state = self._state
        with state.lock:
            now = state.clock()
            for index in [i for i, until in state.retired.items() if until <= now]:
                del state.retired[index]
            return [one for one in self.proxies if one.index not in state.retired]

    def candidates(self) -> list[Proxy]:
        """Up to `MAX_TRIES` different healthy proxies, rotating: each call starts one further on."""
        alive = self.healthy()
        if not alive:
            return []
        state = self._state
        with state.lock:
            start = state.cursor % len(alive)
            state.cursor += 1
        ordered = alive[start:] + alive[:start]
        return ordered[:MAX_TRIES]

    def opener(self, proxy: Proxy, *handlers: Any) -> urllib.request.OpenerDirector:
        """An opener that connects through `proxy`. The login exists only in here."""
        address = proxy.address
        if self._login:
            user, _, password = self._login.partition(":")
            parts = urllib.parse.urlsplit(address)
            address = urllib.parse.urlunsplit((
                parts.scheme,
                f"{urllib.parse.quote(user, safe='')}"
                + (f":{urllib.parse.quote(password, safe='')}" if password else "")
                + f"@{parts.netloc}",
                "", "", ""))
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": address, "https": address}), *handlers)

    # ── robots.txt ───────────────────────────────────────────────────────
    def robots_allow(self, url: str, *, fetch: Callable[[str], str | None] | None = None) -> bool:
        """Whether the site's `robots.txt` lets Kriko read `url`.

        Asked directly (never through the pool) and remembered. A site with no
        readable `robots.txt` has said nothing, which is permission, the usual
        rule; one that says "disallow" is respected: the pool is for sites that
        refuse by blocking, not for ones that have asked not to be read.
        """
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        state = self._state
        with state.lock:
            known = state.robots.get(origin)
            if known and state.clock() - known[0] < ROBOTS_TTL:
                parser = known[1]
                return True if parser is None else parser.can_fetch(AGENT, url)
        text = (fetch or _fetch_robots)(origin + "/robots.txt")
        parser = None
        if text is not None:
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(text.splitlines())
        with state.lock:
            state.robots[origin] = (state.clock(), parser)
        return True if parser is None else parser.can_fetch(AGENT, url)

    # ── what Settings shows ──────────────────────────────────────────────
    def snapshot(self) -> dict:
        state = self._state
        healthy = {one.index for one in self.healthy()}
        with state.lock:
            now = state.clock()
            blocked = sorted(
                ((host, count) for host, (count, at) in state.blocked.items()
                 if now - at < BLOCK_MEMORY),
                key=lambda row: (-row[1], row[0]))
            return {**state.counts,
                    "blocked_hosts": [{"host": host, "count": count} for host, count in blocked[:20]],
                    "healthy": len(healthy), "pool": len(self.proxies)}


def _fetch_robots(url: str) -> str | None:
    """The text of a `robots.txt`, or None when there is none to read."""
    from app.providers import network

    try:
        request = urllib.request.Request(url, headers={"User-Agent": f"{AGENT}/1.0"})
        with network.urlopen(request, timeout=5.0) as response:
            if response.getcode() != 200:
                return None
            return response.read(500_000).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


# ── the pool the saved settings describe ─────────────────────────────────

_lock = threading.Lock()
_path: Any = None
_cached: tuple[float, Any, Router | None] | None = None
#: How long a read of the settings is reused, so a page read does not open the
#: settings file, and a change in Settings is still seen within seconds.
SETTINGS_TTL = 5.0


def remember_path(app_state_path: Any) -> None:
    """Tell this module where the settings live (the web app does, once)."""
    global _path, _cached
    with _lock:
        _path = app_state_path
        _cached = None


def forget() -> None:
    """Re-read the settings on the next read. Called after the reader saves them."""
    global _cached
    with _lock:
        _cached = None


def from_settings(chosen: dict, clock: Callable[[], float] = time.monotonic) -> Router | None:
    """The pool for stored settings: `None` unless it is on and has an address."""
    if str(chosen.get(SETTING_ENABLED) or "").strip() not in {"1", "true", "yes", "on"}:
        return None
    addresses = parse_pool(str(chosen.get(SETTING_POOL) or ""))
    return Router(addresses, credentials(), clock=clock) if addresses else None


def shared() -> Router | None:
    """The reader's pool, or None: the switch is off, nothing is configured, or the settings are unreadable."""
    global _cached
    with _lock:
        path = _path
        cached = _cached
    if path is None:
        return None
    now = time.monotonic()
    if cached is not None and cached[1] == path and now - cached[0] < SETTINGS_TTL:
        return cached[2]
    router: Router | None = None
    try:
        from app.web import state

        conn = state.connect(path)
        try:
            stored = state.all_settings(conn)
        finally:
            conn.close()
        previous = cached[2] if cached is not None and cached[1] == path else None
        router = from_settings({key: stored.get(key) for key in (SETTING_ENABLED, SETTING_POOL)})
        # Keep what was learned while the same pool stays configured.
        if (router is not None and previous is not None
                and [p.address for p in previous.proxies] == [p.address for p in router.proxies]
                and previous._login == router._login):
            router = previous
    except Exception:  # noqa: BLE001 - a read never fails because of a proxy setting
        router = None
    with _lock:
        _cached = (now, path, router)
    return router


def reader_options(sink: Callable[[str], Any] | None = None) -> dict:
    """Keyword arguments for a page reader: `{}` when no pool is on."""
    router = shared()
    return {"proxies": router.view(sink)} if router is not None else {}


def status(conn) -> dict:
    """What Settings draws: the switch, the pool, the login's presence, what was measured."""
    from app import keys
    from app.web import state

    stored = state.all_settings(conn)
    enabled = str(stored.get(SETTING_ENABLED) or "").strip() in {"1", "true", "yes", "on"}
    pool = parse_pool(str(stored.get(SETTING_POOL) or ""))
    router = shared() if enabled else None
    saved = any(row["id"] == "proxy" and row["present"] for row in keys.status())
    return {
        "enabled": enabled,
        "pool": pool,
        "login_saved": saved,
        "active": bool(enabled and pool),
        "learned": router.snapshot() if router is not None else None,
        "limits": {"tries": MAX_TRIES, "retire_seconds": int(RETIRE_SECONDS),
                   "block_memory_seconds": int(BLOCK_MEMORY)},
    }


#: The page Check asks each proxy for: an address kept by IANA for examples.
CHECK_TARGET = "https://example.com/"


def check(addresses: list[str], target: str = "") -> list[dict]:
    """Ask each proxy for one small public page, and say which answered.

    The reader's own press. It spends one request per proxy at `target`, a page
    kept for exactly this, never at a site the reader reads.
    """
    target = target or CHECK_TARGET
    router = Router(addresses, credentials())
    rows = []
    for proxy in router.proxies:
        began = time.monotonic()
        row: dict = {"address": proxy.address, "ok": False, "ms": 0, "error": ""}
        try:
            opener = router.opener(proxy)
            with opener.open(urllib.request.Request(
                    target, headers={"User-Agent": f"{AGENT}/1.0"}), timeout=10.0) as response:
                row["ok"] = 200 <= int(response.getcode()) < 300
                if not row["ok"]:
                    row["error"] = f"answered HTTP {response.getcode()}"
        except urllib.error.HTTPError as error:
            row["error"] = ("the proxy wants a login: save one under Keys" if error.code == 407
                            else f"answered HTTP {error.code}")
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            reason = getattr(error, "reason", error)
            row["error"] = router.scrub(f"could not connect ({type(reason).__name__})")
        row["ms"] = int((time.monotonic() - began) * 1000)
        rows.append(row)
    return rows
