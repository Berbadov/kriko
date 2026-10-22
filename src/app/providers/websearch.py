"""The web search Chat and research use: one provider, others behind it.

Four providers can answer "search the web": OpenSERP (a service on this
machine, no key, the default), and DeepSeek, Exa and Tavily (hosted, one key
each). Until now a turn used exactly one of them and took its failure as the
end of the search. OpenSERP is the free one and also the iffy one: its own
notes (`openserp.py`) record engines that answer with a challenge, engines that
time out and an engine that answers empty about half the time. When that is
the only door, a flaky engine becomes "the web has nothing on this".

So the choice is an **order**, not a single pick: the provider the reader
chose (OpenSERP when they chose none), then the providers behind it.

* A provider that **raises** or **returns nothing** hands the query to the next
  one, and the job log says which failed, why, and who is asking next.
* **Automatic** (the reader chose no order) puts DeepSeek behind OpenSERP when,
  and only when, a DeepSeek key is saved. Saving that key is the reader's
  consent to sending it queries; no other hosted provider is ever asked unless
  the reader put it in the order.
* **Cancel is not a failure.** The reader pressing stop raises through the
  chain; nothing is tried after it.
* Every attempt is counted (`record`), so Settings can show when a provider
  last answered and how often it has not. That is the *measurement* behind
  "OpenSERP is iffy": the reader sees the error rate rather than being told.

Nothing here knows a category and nothing here logs a key: reasons come from
the adapters (a status and a host), and anything that still looks like a saved
key is removed before it is written (`scrub`).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

from kriko.research.politeness import LocalSearchError

OPENSERP = "openserp"

#: The providers this app has code for. A closed engineering vocabulary, like
#: `keys.SEARCH_PROVIDERS`: integrations, not data that grows with coverage.
KNOWN = (OPENSERP, "deepseek", "exa", "tavily")

LABELS = {OPENSERP: "OpenSERP", "deepseek": "DeepSeek", "exa": "Exa", "tavily": "Tavily"}

#: What the reader is told about each, in the words Settings shows.
NOTES = {
    OPENSERP: "Runs on this computer. No key. Sometimes a search engine blocks it or answers nothing.",
    "deepseek": "Hosted. Needs a key. Receives only the words searched.",
    "exa": "Hosted. Needs a key. Receives only the words searched.",
    "tavily": "Hosted. Needs a key. Receives only the words searched.",
}

#: The automatic fallback: DeepSeek, once it has a key.
AUTOMATIC_FALLBACK = ("deepseek",)

#: Written to the fallback setting to mean "nothing behind the first choice".
NONE = "none"

#: Where outcomes are kept, in `app.sqlite`'s settings. Not in `prefs.KEYS`, so
#: nothing a browser sends can write it.
HEALTH_KEY = "search_health"
#: How many recent outcomes the error rate is taken over.
WINDOW = 20

#: Attributes of a cancel. `jobs.Cancelled` sets one; the readers' own do too.
_CANCEL_NAMES = {"Cancelled", "FetchCancelled", "StreamCancelled", "CancelledError"}


def label(provider: str) -> str:
    return LABELS.get(provider, provider)


def is_cancel(error: BaseException) -> bool:
    return bool(getattr(error, "cancelled", False)) or type(error).__name__ in _CANCEL_NAMES


def needs_key(provider: str) -> bool:
    return provider != OPENSERP


def has_key(provider: str) -> bool:
    """Whether this provider could be asked now: OpenSERP always, others with a key."""
    if not needs_key(provider):
        return True
    from app import keys

    return provider in keys.search_providers()


def scrub(text: object) -> str:
    """`text` with any saved or exported key removed, and one line long."""
    from app import keys

    out = " ".join(str(text or "").split())
    for item in keys.PROVIDERS:
        value = str(os.environ.get(item.env) or "").strip()
        if len(value) >= 6:
            out = out.replace(value, "[key]")
    return out[:240]


# ── the order ────────────────────────────────────────────────────────────

def parse_fallback(value: str) -> list[str] | None:
    """The stored fallback list; `None` means automatic, `[]` means none."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.casefold() == NONE:
        return []
    out: list[str] = []
    for part in text.split(","):
        name = part.strip().casefold()
        if name in KNOWN and name not in out:
            out.append(name)
    return out


def order(chosen: dict) -> dict:
    """`{primary, fallback, automatic, effective}` for the stored choices.

    `effective` is what a search will try, in order: the first choice, then
    the fallbacks that can be asked (a keyed provider without its key is not
    tried, and is not an error: it is simply not asked).
    """
    from app import prefs

    primary = str(chosen.get(prefs.SEARCH) or "").strip().casefold()
    if primary not in KNOWN:
        primary = OPENSERP
    stored = parse_fallback(chosen.get(prefs.SEARCH_FALLBACK, ""))
    automatic = stored is None
    behind = list(AUTOMATIC_FALLBACK) if stored is None else stored
    fallback = [name for name in behind if name != primary]
    effective = [primary] + [name for name in fallback if has_key(name)]
    return {"primary": primary, "fallback": fallback, "automatic": automatic,
            "effective": effective}


# ── health ───────────────────────────────────────────────────────────────

_health_lock = threading.Lock()


def _read_health(conn) -> dict:
    from app.web import state

    raw = state.all_settings(conn).get(HEALTH_KEY)
    return raw if isinstance(raw, dict) else {}


def _row_of(stored: dict, provider: str) -> dict:
    row = stored.get(provider)
    return row if isinstance(row, dict) else {}


def record(app_state_path, provider: str, outcome: str, reason: str = "") -> None:
    """Count one attempt: `ok`, `empty` or `error`. Never raises.

    A recorder that could fail a search would make the measurement the reason
    for the thing it measures.
    """
    if app_state_path is None or provider not in KNOWN:
        return
    try:
        from app.web import state

        with _health_lock:
            conn = state.connect(app_state_path)
            try:
                health = _read_health(conn)
                row = _row_of(health, provider)
                now = round(time.time())
                recent = (str(row.get("recent") or "") + outcome[:1])[-WINDOW:]
                row.update(recent=recent, calls=int(row.get("calls") or 0) + 1)
                if outcome == "ok":
                    row["last_success"] = now
                else:
                    row["last_failure"] = now
                    row["last_problem"] = scrub(reason) or (
                        "returned nothing" if outcome == "empty" else "failed")
                health[provider] = row
                state.put_settings(conn, {HEALTH_KEY: health})
            finally:
                conn.close()
        from app import usage

        usage.record(app_state_path, "web_search", source=provider, ok=(outcome == "ok"))
    except Exception:  # noqa: BLE001 - see the docstring
        return


def health(conn) -> dict[str, dict]:
    """Per provider: last success, last failure and the recent miss rate."""
    try:
        stored = _read_health(conn)
    except Exception:  # noqa: BLE001 - a health panel is never why Settings fails
        stored = {}
    out: dict[str, dict] = {}
    for provider in KNOWN:
        row = _row_of(stored, provider)
        recent = str(row.get("recent") or "")
        out[provider] = {
            "calls": int(row.get("calls") or 0),
            "recent": len(recent),
            "last_success": row.get("last_success"),
            "last_failure": row.get("last_failure"),
            "last_problem": str(row.get("last_problem") or ""),
            # Not-ok over the last `WINDOW`: errors and empty answers both
            # leave the reader without results, which is what is measured.
            "miss_rate": (round(sum(1 for one in recent if one != "o") / len(recent), 2)
                          if recent else None),
        }
    return out


# ── the chain ────────────────────────────────────────────────────────────

#: Seconds one search may take in all, across every provider it tries. A
#: caller that passes no deadline — `chatdata` asks for a search with none —
#: must not be able to hang a turn on a provider that accepted the connection
#: and then went quiet, and the per-recv socket timeout does not bound that.
BUDGET = 25.0


class Chain:
    """`search(query, limit)` over an ordered list of providers.

    `members` is `[(provider, build)]`; `build()` makes that provider's
    searcher and is called at most once, and only when it is first needed.
    The first member is built at once, so a misconfiguration surfaces where
    the turn is set up (as before), while the ones behind it are built only on
    the day the first one fails.

    **Every call is bounded.** The whole call gets `timeout` seconds (or
    `BUDGET`); each provider is given what is left of it, and a provider that
    cannot take a deadline at all is run beside the chain and abandoned when
    the budget runs out, exactly as the local plane abandons a slow search
    worker. What each provider said is kept in `attempts`, which is what the
    log line and `local_search_plan.attempts_said` read.
    """

    def __init__(self, members: list[tuple[str, Callable[[], Callable[..., list]]]], *,
                 log: Callable[[str], Any] | None = None,
                 app_state_path=None, language: str = "en") -> None:
        self.members = members
        self._log = log
        self._app_state_path = app_state_path
        self._built: dict[int, Callable[..., list]] = {}
        self._check: Callable[[], Any] | None = None
        self.language = language
        #: What each provider said on the last call: `{provider, label,
        #: outcome, reason, results}`. Read, never written, by the job log.
        self.attempts: list[dict] = []
        # The chain bounds itself, whatever the caller passed, so a plane that
        # asks it for a deadline gets one honoured down to each provider.
        self.supports_timeout = True
        if members:
            self._searcher(0)

    # the cancel hook: stored once, handed to every member as it is built
    @property
    def check_cancelled(self):
        return self._check

    @check_cancelled.setter
    def check_cancelled(self, check) -> None:
        self._check = check
        for built in self._built.values():
            try:
                built.check_cancelled = check  # type: ignore[attr-defined]
            except (AttributeError, TypeError):
                pass

    @property
    def providers(self) -> list[str]:
        return [provider for provider, _ in self.members]

    def _searcher(self, index: int):
        if index not in self._built:
            built = self.members[index][1]()
            try:
                built.check_cancelled = self._check  # type: ignore[attr-defined]
            except (AttributeError, TypeError):
                pass
            self._built[index] = built
        return self._built[index]

    def _say(self, line: str) -> None:
        if self._log is not None:
            try:
                self._log(line)
            except Exception:  # noqa: BLE001 - a log line never fails a search
                pass

    def _budget_for(self, searcher, left: float) -> float | None:
        """What this provider may take: the smaller of `left` and its own default.

        A provider that declares `default_timeout` keeps it — the chain's
        budget is a ceiling, never a longer leash than the provider chose for
        itself — and one that takes no deadline gets `None`, which means "run
        it beside the chain and abandon it when the budget runs out".
        """
        own = getattr(searcher, "default_timeout", None)
        if not getattr(searcher, "supports_timeout", False):
            return None
        if isinstance(own, (int, float)) and not isinstance(own, bool):
            return min(left, float(own))
        return left

    def _beside(self, call: Callable[[], list], left: float) -> tuple[list | None, str]:
        """Run `call` beside the chain: its answer, or why it ran out of time."""
        box: list[Any] = []

        def run() -> None:
            try:
                box.append(call())
            except BaseException as error:  # noqa: BLE001 - reported to the caller
                box.append(error)

        worker = threading.Thread(target=run, name="kriko-search-provider", daemon=True)
        worker.start()
        worker.join(max(0.0, left))
        if worker.is_alive():
            return None, f"did not answer within {left:.1f}s"
        if not box:
            return None, "answered nothing"
        if isinstance(box[0], BaseException):
            raise box[0]
        return box[0], ""

    def _call_member(self, searcher, query: str, limit: int, options: dict,
                     left: float) -> list[dict]:
        """Ask one provider, inside what is left of its share of the budget.

        A provider that takes a deadline gets one and answers in place. One
        that does not — an adapter built before this — runs beside the chain
        and is abandoned when the share is spent, exactly as the local plane
        abandons a search worker that outlived its budget.
        """
        allowed = self._budget_for(searcher, left)
        if allowed is not None:
            return searcher(query, limit, timeout=allowed, **options)

        def run() -> list[dict]:
            if getattr(searcher, "supports_timeout", False):
                return searcher(query, limit, timeout=left, **options)
            return searcher(query, limit, **options)

        beside, why = self._beside(run, left)
        if why:
            raise LocalSearchError(why)
        return beside or []
    def __call__(self, query: str, limit: int = 5, timeout: float | None = None,
                 kind: str = "", **options) -> list[dict]:
        """One search: the providers in order, inside one deadline.

        `kind` is the kind of source to go to, and it is the *agent's* decision:
        when the caller names none, the query's own words decide
        (`local_search_plan.choose_kinds`), the query is asked with that kind's
        marker word, and the line written to the job log says which kind was
        targeted, which words were used and what came back.
        """
        from app.providers import local_search_plan as plan

        budget = BUDGET if timeout is None else max(0.0, float(timeout))
        deadline = time.monotonic() + budget
        chosen = kind if kind in plan.SOURCE_KINDS else ""
        if not chosen:
            asked = plan.choose_kinds(query, limit=1)
            chosen = asked[0] if asked else ""
        effective = plan.marked_query(query, chosen, self.language) if chosen else query
        self.attempts = []
        failures: list[tuple[str, str, BaseException]] = []
        answered_empty = False
        for index, (provider, _build) in enumerate(self.members):
            if self._check is not None:
                self._check()
            name = label(provider)
            later = [label(one) for one, _ in self.members[index + 1:]]
            then = f"; falling back to {later[0]}" if later else ""
            left = deadline - time.monotonic()
            if left <= 0:
                why = f"the search ran out of its {budget:.0f}s budget"
                self.attempts.append({"provider": provider, "label": name,
                                      "outcome": "timeout", "reason": why, "results": 0})
                failures.append((name, why, LocalSearchError(why)))
                self._say(f"web search: {name} was not asked ({why})")
                continue
            # The budget is shared with the providers still to try, so one
            # provider that goes quiet cannot spend the turn that the ones
            # behind it were going to answer in.
            share = left / max(1, len(self.members) - index)
            try:
                found = self._call_member(self._searcher(index), effective, limit,
                                          options, share)
            except Exception as error:  # noqa: BLE001 - classified just below
                if is_cancel(error):
                    raise
                why = scrub(error) or type(error).__name__
                record(self._app_state_path, provider, "error", why)
                self.attempts.append({"provider": provider, "label": name,
                                      "outcome": "error", "reason": why, "results": 0})
                failures.append((name, why, error))
                self._say(f"web search: {name} failed ({why}){then}")
                continue
            if found:
                record(self._app_state_path, provider, "ok")
                self.attempts.append({"provider": provider, "label": name,
                                      "outcome": "ok", "reason": "", "results": len(found)})
                if index:
                    self._say(f"web search: {name} answered ({len(found)} results)")
                self._say(plan.searched_line(chosen, effective, found))
                return found
            record(self._app_state_path, provider, "empty")
            answered_empty = True
            self.attempts.append({"provider": provider, "label": name,
                                  "outcome": "empty", "reason": "returned nothing",
                                  "results": 0})
            self._say(f"web search: {name} returned nothing{then}")
        self._say(plan.searched_line(chosen, effective, (),
                                     plan.attempts_said(self.attempts) or "no provider answered"))
        if not failures:
            return []
        if len(failures) == 1 and len(self.members) == 1:
            sole = failures[0][2]
            if isinstance(sole, LocalSearchError):
                raise sole  # one provider, as before: its own error
            # A transport failure (a permit that never came free, a socket that
            # died) is the planes' own vocabulary, so the reason reaches the
            # run instead of stopping it with a type it does not handle.
            raise LocalSearchError(failures[0][1]) from sole
        if answered_empty:
            return []  # something answered, with nothing: not an outage
        raise LocalSearchError("; ".join(f"{name}: {why}" for name, why, _ in failures))


# ── building ─────────────────────────────────────────────────────────────

def _hosted_factory(provider: str, app_state_path) -> Callable[[], Callable[..., list]]:
    def build():
        if provider == "deepseek":
            from app.providers import deepseek

            return deepseek.searcher()
        from app import providers

        return providers._searcher(app_state_path, provider)[0]

    return build


def openserp_for_chat(chosen: dict) -> Callable[..., list]:
    """The local search service as chat uses it: three engines, bounded to 8 s."""
    from app import prefs
    from app.providers import openserp

    return openserp.searcher(
        chosen.get(prefs.LOCAL_SEARCH_URL, ""), engine="duckduckgo,bing,google",
        language=chosen.get(prefs.LOCAL_SEARCH_LANGUAGE) or "en", timeout=8.0,
        mode="any")


def build(chosen: dict, app_state_path, *, log=None, check=None,
          openserp_factory: Callable[[dict], Callable[..., list]] = openserp_for_chat
          ) -> Chain:
    """The chain for the reader's saved choices.

    A first choice the reader named that cannot be built (a hosted provider
    without its key) raises `MissingKey`, as it always did: they asked for
    something specific and are told it is not there. Providers behind it that
    cannot be asked are left out (`order`).
    """
    from app import prefs

    plan = order(chosen)
    language = str(chosen.get(prefs.LOCAL_SEARCH_LANGUAGE) or "en")
    members: list[tuple[str, Callable[[], Callable[..., list]]]] = []
    for provider in plan["effective"]:
        if provider == OPENSERP:
            members.append((provider, lambda: openserp_factory(chosen)))
        else:
            members.append((provider, _hosted_factory(provider, app_state_path)))
    chain = Chain(members, log=log, app_state_path=app_state_path, language=language)
    if check is not None:
        chain.check_cancelled = check
    return chain


def status(conn) -> dict:
    """What Settings draws: each provider, the order, and how each has done."""
    from app import keys, prefs

    chosen = prefs.read(conn)
    plan = order(chosen)
    seen = health(conn)
    present = set(keys.search_providers())
    return {
        "providers": [
            {"id": one, "label": label(one), "needs_key": needs_key(one),
             "key_saved": (one in present) if needs_key(one) else None,
             "ready": has_key(one), "note": NOTES[one], "health": seen[one]}
            for one in KNOWN
        ],
        "primary": plan["primary"],
        "fallback": plan["fallback"],
        "automatic": plan["automatic"],
        "effective": plan["effective"],
    }


def probe(conn, app_state_path, provider: str, query: str = "") -> dict:
    """Run one query through one provider alone, and say what came back.

    The reader's own press, so it is allowed to cost the one query. It counts
    in the provider's health like any other search.
    """
    from app import prefs

    text = " ".join((query or "").split())[:128] or "reliability of home electric heaters"
    began = time.monotonic()
    out: dict = {"provider": provider, "label": label(provider), "query": text,
                 "ok": False, "results": [], "error": "", "ms": 0}
    if provider not in KNOWN:
        out["error"] = "unknown search provider"
        return out
    if not has_key(provider):
        out["error"] = f"{label(provider)} needs a key. Add it under Keys."
        return out
    try:
        chosen = prefs.read(conn)
        if provider == OPENSERP:
            search = openserp_for_chat(chosen)
        else:
            search = _hosted_factory(provider, app_state_path)()
        found = search(text, 5)
    except Exception as error:  # noqa: BLE001 - the answer is the reason
        out["error"] = scrub(error) or type(error).__name__
        out["ms"] = int((time.monotonic() - began) * 1000)
        record(app_state_path, provider, "error", out["error"])
        return out
    out["ms"] = int((time.monotonic() - began) * 1000)
    out["results"] = [{"title": str(hit.get("title") or "")[:160], "url": str(hit.get("url") or ""),
                       "site": str(hit.get("site") or "")}
                      for hit in (found or []) if isinstance(hit, dict)][:5]
    if out["results"]:
        out["ok"] = True
        record(app_state_path, provider, "ok")
    else:
        out["error"] = "it answered, with no results"
        record(app_state_path, provider, "empty")
    return out
