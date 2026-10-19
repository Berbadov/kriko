"""Two live searches side by side, and what each one checked.

    python -m app.livesearch "Brand Model 123" --agent claude-code

An agent product search (the agent browses with its own tools) and a quick
search (`tasks.quick_look`: Kriko searches, reads the pages, the agent
answers) start at the same moment, each in its own process with its own
throwaway app state. When both are done the report says, per lane, which
queries went out, which pages were opened and which sites that makes, what the
lane claimed and how long it took, and then which sites only one of them saw.

It spends what a real run spends and needs the web, so the gate never runs it:
`test_live_search_side_by_side.py` runs it only when `KRIKO_LIVE_SEARCH` is set.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from app.winprocess import hidden_startup

LANES = ("agent", "quick")
LANE_TIMEOUT_SECONDS = 240.0
_URL = re.compile(r"https?://[^\s<>\"'`)\]}]+")
_AGENT_SEARCH = re.compile(r'^searched "(.*)"$')
_NOTEWORTHY = ("did not answer", "search failed", "will search the web itself", "unreadable")
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|AUTH", re.IGNORECASE)


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def plain_url(url: str) -> str:
    """The address without the query or fragment, which is where tokens ride."""
    parts = urlsplit(url.rstrip(".,;:"))
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def urls_in(text: str) -> list[str]:
    return [plain_url(found) for found in _URL.findall(text or "")]


def scrub(text: str, env: dict[str, str] | None = None) -> str:
    """The text with every secret this process holds taken out."""
    clean = str(text or "")
    for name, value in sorted((os.environ if env is None else env).items()):
        if _SECRET_NAME.search(name) and len(value) >= 12:
            clean = clean.replace(value, "[redacted]")
    return clean


class _Forward:
    """A recording stand-in that is still the real thing to whoever holds it.

    Callers set `check_cancelled` and friends on the function they were handed;
    those writes must land on the real socket, which reads them from itself.
    """

    def __init__(self, inner: Callable[..., Any], record: Callable[..., Any]):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_record", record)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._record(self._inner, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._inner, name, value)


class Tap:
    """Records every search and every page open that goes through the real sockets."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.began = time.time()
        self.searches: list[dict] = []
        self.opened: list[dict] = []

    def _search(self, inner: Callable[..., Any], query: str, *args: Any, **kwargs: Any) -> Any:
        started, error = time.time(), ""
        hits: list = []
        try:
            hits = inner(query, *args, **kwargs)
            return hits
        except Exception as exc:  # noqa: BLE001 - recorded, then raised as it was
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            with self.lock:
                self.searches.append({
                    "query": str(query), "engines": str(kwargs.get("engines") or ""),
                    "at": round(started - self.began, 2),
                    "ms": int((time.time() - started) * 1000),
                    "results": [plain_url(str(one.get("url") or "")) for one in hits or []
                                if isinstance(one, dict)],
                    "error": scrub(error)[:300]})

    def _read(self, inner: Callable[..., Any], url: str, *args: Any, **kwargs: Any) -> Any:
        started, error = time.time(), ""
        got: Any = None
        try:
            got = inner(url, *args, **kwargs)
            return got
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            text = str(getattr(got, "text", got) or "")
            with self.lock:
                self.opened.append({
                    "url": plain_url(str(url)), "host": host_of(str(url)),
                    "at": round(started - self.began, 2),
                    "ms": int((time.time() - started) * 1000),
                    "chars": len(text), "readable": bool(text.strip()),
                    "error": scrub(error)[:300]})

    def install(self) -> Callable[[], None]:
        """Wrap the search service and the page reader; returns the way back."""
        from app.providers import fetch, openserp

        real_searcher, real_reader = openserp.searcher, fetch.reader

        def searcher(*args: Any, **kwargs: Any) -> Any:
            return _Forward(real_searcher(*args, **kwargs), self._search)

        def reader(*args: Any, **kwargs: Any) -> Any:
            return _Forward(real_reader(*args, **kwargs), self._read)

        openserp.searcher, fetch.reader = searcher, reader

        def restore() -> None:
            openserp.searcher, fetch.reader = real_searcher, real_reader
        return restore


def agent_searches(lines: list[str]) -> list[str]:
    """The queries an agent ran with its own tools, as the job log narrates them."""
    return [found.group(1) for found in map(_AGENT_SEARCH.match, lines) if found]


def checked(searches: list[dict], opened: list[dict], agent_lines: list[str],
            cited: list[str]) -> list[dict]:
    """Every site the lane touched, once, with how it came to touch it."""
    sites: dict[str, dict] = {}

    def note(url: str, how: str) -> None:
        host = host_of(url)
        if not host:
            return
        site = sites.setdefault(host, {"host": host, "how": set(), "urls": set()})
        site["how"].add(how)
        site["urls"].add(plain_url(url))

    for one in opened:
        note(one["url"], "page read by Kriko" if one["readable"] else "page read failed")
    for one in searches:
        for url in one["results"]:
            note(url, "in search results")
    for line in agent_lines:
        for url in urls_in(line):
            note(url, "opened by the agent")
    for url in cited:
        note(url, "cited in the answer")
    return [{"host": site["host"], "how": sorted(site["how"]),
             "urls": sorted(site["urls"])} for site in sorted(sites.values(), key=lambda s: s["host"])]


def _seed(root: Path, agent: str):
    """A throwaway app state that keeps the reader's settings and none of their history."""
    from app import bench, prefs
    from app.web import state
    from app.web.settings import Settings

    reader_state = Settings().app_state_path
    settings = Settings(store_path=root / "knowledge.sqlite", app_state_path=root / "app.sqlite",
                        analysis_log_path=root / "analyses.jsonl")
    state.connect(settings.app_state_path).close()
    if Path(reader_state).exists():
        bench._copy_settings(reader_state, settings.app_state_path)
    conn = state.connect(settings.app_state_path)
    try:
        if agent:
            prefs.write(conn, {prefs.HARNESS: prefs.LOCAL_PICK if agent == "local" else agent})
    finally:
        conn.close()
    return settings


def run_lane(lane: str, product: str, agent: str = "", *,
             timeout: float = LANE_TIMEOUT_SECONDS) -> dict:
    """One lane, here, now: the product asked about and everything it did."""
    if lane not in LANES:
        raise ValueError(f"lane must be one of {', '.join(LANES)}")
    if lane == "agent" and agent == "local":
        raise ValueError("the agent lane needs an agent with tools of its own, not the local model")
    from app import bench, quicklook
    from app.web import tasks

    tap = Tap()
    restore = tap.install()
    root = Path(tempfile.mkdtemp(prefix="kriko-livesearch-"))
    progress = bench._Silent()
    started = time.time()
    error, reply = "", ""
    claims: list[dict] = []
    result: dict = {}
    cost: dict = {}
    try:
        settings = _seed(root, agent)
        if lane == "quick":
            params = {"product": product, "page": {"facts": {}, "description": ""},
                      "page_url": "", "harness": "" if agent == "local" else agent,
                      "backend": "local" if agent == "local" else "",
                      "timeout_seconds": timeout}
            result = tasks.quick_look(settings, params, progress)  # type: ignore[arg-type]
            reply = json.dumps({"risks": result.get("risks"), "specs": result.get("specs")})
            claims = [{"title": str(one.get("title") or ""),
                       "urls": [plain_url(str(s.get("url") if isinstance(s, dict) else s))
                                for s in one.get("sources") or []]}
                      for one in result.get("risks") or [] if isinstance(one, dict)]
            cost = {"usd": result.get("spent_usd"), "tokens": result.get("tokens_used")}
        else:
            from app.providers import harness_researcher

            researcher = harness_researcher(preferred=agent, timeout=timeout,
                                            app_state_path=settings.app_state_path)
            researcher.on_action = progress.log
            reply = researcher.ask(quicklook.brief(product, "", None, "", "")).strip()
            found = quicklook.parse(reply, None)
            claims = [{"title": str(one.get("title") or ""), "urls": urls_in(json.dumps(one))}
                      for one in found.get("risks") or [] if isinstance(one, dict)]
            cost = {"usd": getattr(researcher, "spent", None),
                    "tokens": getattr(researcher, "tokens_used", None)}
    except Exception as exc:  # noqa: BLE001 - a lane that failed is a finding
        error = scrub(f"{type(exc).__name__}: {exc}")[:600]
    finally:
        restore()
        import shutil

        shutil.rmtree(root, ignore_errors=True)
    ended = time.time()
    cited = [url for claim in claims for url in claim["urls"]]
    lines = [scrub(line)[:400] for line in progress.lines]
    return {
        "lane": lane, "product": product, "agent": agent or "(reader's pick)",
        "started": started, "ended": ended, "seconds": round(ended - started, 1),
        "error": error, "answer": scrub(reply)[:4000], "claims": claims, "cost": cost,
        "searches": tap.searches, "opened": tap.opened, "log": lines[-80:],
        "agent_searches": agent_searches(lines),
        "notes": [line for line in lines if any(mark in line for mark in _NOTEWORTHY)][:10],
        "sites": checked(tap.searches, tap.opened, lines, cited),
    }


def lane_in_process(lane: str, product: str, agent: str, timeout: float) -> dict:
    """The real lane runner: a process of its own, so the two cannot share a socket or a lock."""
    with tempfile.TemporaryDirectory(prefix="kriko-lane-") as holder:
        out = Path(holder) / "lane.json"
        command = [sys.executable, "-m", "app.livesearch", "--lane", lane, "--agent", agent,
                   "--timeout", str(timeout), "--lane-out", str(out), product]
        began = time.time()
        try:
            done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                  timeout=timeout + 120, startupinfo=hidden_startup(),
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return _lost(lane, product, agent, began, "the lane did not finish in time")
        if out.exists():
            return json.loads(out.read_text(encoding="utf-8"))
        return _lost(lane, product, agent, began,
                     scrub(f"exit {done.returncode}: {(done.stderr or done.stdout)[-400:]}"))


def _lost(lane: str, product: str, agent: str, began: float, why: str) -> dict:
    ended = time.time()
    return {"lane": lane, "product": product, "agent": agent or "(reader's pick)",
            "started": began, "ended": ended, "seconds": round(ended - began, 1), "error": why,
            "answer": "", "claims": [], "cost": {}, "searches": [], "opened": [], "log": [],
            "agent_searches": [], "notes": [], "sites": []}


def run_side_by_side(product: str, agent: str = "", lanes: tuple[str, ...] = LANES, *,
                     timeout: float = LANE_TIMEOUT_SECONDS,
                     runner: Callable[[str, str, str, float], dict] = lane_in_process) -> dict:
    """Every lane at the same moment, then the comparison of what they checked."""
    with ThreadPoolExecutor(max_workers=len(lanes)) as pool:
        futures = {lane: pool.submit(runner, lane, product, agent, timeout) for lane in lanes}
        results = {lane: future.result() for lane, future in futures.items()}
    return {"product": product, "agent": agent or "(reader's pick)",
            "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "lanes": results, "comparison": compare(results),
            "overlap_seconds": overlap(results)}


def overlap(results: dict[str, dict]) -> float:
    """How long all the lanes were running at once: proof they did not take turns."""
    if len(results) < 2:
        return 0.0
    start = max(one["started"] for one in results.values())
    end = min(one["ended"] for one in results.values())
    return round(max(0.0, end - start), 1)


def compare(results: dict[str, dict]) -> dict:
    hosts = {lane: {site["host"] for site in one["sites"]} for lane, one in results.items()}
    everyone = set.intersection(*hosts.values()) if hosts else set()
    return {"shared": sorted(everyone),
            "only": {lane: sorted(found - set().union(
                *(other for name, other in hosts.items() if name != lane)))
                for lane, found in hosts.items()}}


def markdown(report: dict) -> str:
    out = [f"# Live search: {report['product']}", "",
           f"Agent: {report['agent']}. Run: {report['when']}. "
           f"Both lanes were running together for {report['overlap_seconds']} s.", ""]
    for lane, one in report["lanes"].items():
        pages = Counter(site["host"] for site in one["sites"])
        read = Counter(page["host"] for page in one["opened"] if page["readable"])
        out += [f"## {lane}", "",
                f"{one['seconds']} s, {len(one['searches']) + len(one.get('agent_searches', []))} search(es), "
                f"{len(one['opened'])} page open(s), {len(pages)} site(s), "
                f"{len(one['claims'])} claim(s)"
                + (f", cost {one['cost']}" if any(one["cost"].values()) else "") + ".", ""]
        if one["error"]:
            out += [f"**Failed:** {one['error']}", ""]
        if one.get("agent_searches"):
            out += ["Searched by the agent itself:", *[f"- `{q}`" for q in one["agent_searches"]], ""]
        if one.get("notes"):
            out += ["Worth knowing:", *[f"- {line}" for line in one["notes"]], ""]
        if one["searches"]:
            out += ["Queries Kriko sent:", *[f"- `{s['query']}` ({s['ms']} ms, {len(s['results'])} result(s)"
                                  + (f", error: {s['error']}" if s["error"] else "") + ")"
                                  for s in one["searches"]], ""]
        if one["sites"]:
            out += ["Sites checked:", *[
                f"- {site['host']}: {', '.join(site['how'])}"
                + (f" ({read[site['host']]} readable)" if read[site["host"]] else "")
                for site in one["sites"]], ""]
        if one["claims"]:
            out += ["Claims:", *[f"- {c['title']} ({', '.join(c['urls']) or 'no source'})"
                                 for c in one["claims"]], ""]
    both = report["comparison"]
    out += ["## What they checked", "",
            "Both: " + (", ".join(both["shared"]) or "no site in common"), ""]
    out += [f"Only {lane}: " + (", ".join(found) or "nothing") for lane, found in both["only"].items()]
    return "\n".join(out) + "\n"


def write(report: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    as_json, as_text = directory / "report.json", directory / "report.md"
    as_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    as_text.write_text(markdown(report), encoding="utf-8")
    return as_json, as_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.livesearch", description=__doc__)
    parser.add_argument("product")
    parser.add_argument("--agent", default="", help="agent id (e.g. claude-code); default is the reader's pick")
    parser.add_argument("--lanes", default=",".join(LANES))
    parser.add_argument("--timeout", type=float, default=LANE_TIMEOUT_SECONDS)
    parser.add_argument("--out", default="", help="directory for report.json and report.md")
    parser.add_argument("--lane", default="", help=argparse.SUPPRESS)
    parser.add_argument("--lane-out", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.lane:
        result = run_lane(args.lane, args.product, args.agent, timeout=args.timeout)
        Path(args.lane_out).write_text(json.dumps(result), encoding="utf-8")
        return 0
    chosen = tuple(one for one in args.lanes.split(",") if one)
    report = run_side_by_side(args.product, args.agent, chosen, timeout=args.timeout)
    out = Path(args.out) if args.out else (
        Path.home() / ".kriko" / "live-search" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    _, as_text = write(report, out)
    print(as_text.read_text(encoding="utf-8"))
    print(f"Report: {out}")
    return 0 if all(not one["error"] for one in report["lanes"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
