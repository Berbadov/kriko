"""An agent search and a quick search run together, and the report names the sites each one checked.

The offline half proves the instrument: the taps see every search and page open,
the lanes really overlap, and the report says what only one lane saw. The live
half spends real searches and an agent, so it runs only when asked:

    KRIKO_LIVE_SEARCH=1 KRIKO_LIVE_PRODUCT="Brand Model" KRIKO_LIVE_AGENT=claude-code \
        pytest src/app/tests/test_live_search_side_by_side.py -k live -s

The report lands in `KRIKO_LIVE_OUT` (default `~/.kriko/live-search/<time>/`).
"""

import json
import os
import threading
from pathlib import Path

import pytest

from app import livesearch
from app.providers import fetch, openserp
from app.web.settings import Settings


def _web(monkeypatch, pages):
    """A search service and a page reader standing in for the real sockets under the taps."""
    def searcher(*_a, **_k):
        def search(query, limit=5, **_kw):
            return [{"url": url, "title": url} for url in pages][:limit]
        search.check_cancelled = None
        return search

    def reader(*_a, **_k):
        return lambda url, **_kw: fetch.Fetched(pages.get(url, ""))

    monkeypatch.setattr(openserp, "searcher", searcher)
    monkeypatch.setattr(fetch, "reader", reader)


def _scratch_state(monkeypatch, tmp_path):
    monkeypatch.setattr(livesearch, "_seed", lambda root, agent: Settings(
        store_path=tmp_path / "k.sqlite", app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl"))


def test_the_taps_see_every_search_and_page_open_and_leave_the_sockets_as_they_were(monkeypatch):
    pages = {"https://www.forum.test/t/1?token=abc": "owners report a loose hinge " * 5,
             "https://dead.test/gone": ""}
    _web(monkeypatch, pages)
    before = (openserp.searcher, fetch.reader)
    tap = livesearch.Tap()
    restore = tap.install()
    search = openserp.searcher("", "")
    read = fetch.reader()
    search.check_cancelled = "set by the caller"
    for url in pages:
        read(url)
    search("Brand Model failures", 5, engines="bing")
    restore()

    assert (openserp.searcher, fetch.reader) == before
    assert search.check_cancelled == "set by the caller"
    assert [one["host"] for one in tap.opened] == ["forum.test", "dead.test"]
    assert [one["readable"] for one in tap.opened] == [True, False]
    assert all("token" not in one["url"] for one in tap.opened)
    assert tap.searches[0]["engines"] == "bing"
    assert tap.searches[0]["results"] == ["https://www.forum.test/t/1", "https://dead.test/gone"]


def test_a_search_that_fails_is_recorded_and_still_raises(monkeypatch):
    def searcher(*_a, **_k):
        def search(query, limit=5, **_kw):
            raise RuntimeError("no engine answered")
        return search

    monkeypatch.setattr(openserp, "searcher", searcher)
    tap = livesearch.Tap()
    restore = tap.install()
    with pytest.raises(RuntimeError, match="no engine"):
        openserp.searcher("", "")("anything")
    restore()
    assert "no engine answered" in tap.searches[0]["error"]


def test_a_lane_that_fails_is_a_finding_and_the_sockets_come_back(monkeypatch, tmp_path):
    _scratch_state(monkeypatch, tmp_path)
    before = (openserp.searcher, fetch.reader)

    def broken(settings, params, progress):
        raise ValueError("the agent is not signed in")

    monkeypatch.setattr("app.web.tasks.quick_look", broken)
    result = livesearch.run_lane("quick", "Brand Model", "claude-code")
    assert "not signed in" in result["error"]
    assert result["sites"] == [] and (openserp.searcher, fetch.reader) == before


def test_a_quick_lane_reports_the_sites_its_searches_and_reads_touched(monkeypatch, tmp_path):
    pages = {"https://reviews.test/brand-model": "the hinge fails after a year " * 6,
             "https://forum.test/t/9": ""}
    _web(monkeypatch, pages)
    _scratch_state(monkeypatch, tmp_path)

    def quick(settings, params, progress):
        found = openserp.searcher("", "")("Brand Model hinge", 5)
        read = fetch.reader()
        for hit in found:
            read(hit["url"])
        progress.log("a quick look at Brand Model")
        return {"risks": [{"title": "Hinge fails", "sources": [
            {"url": "https://reviews.test/brand-model?utm=1", "quote": "x"}]}],
            "spent_usd": None, "tokens_used": 120}

    monkeypatch.setattr("app.web.tasks.quick_look", quick)
    result = livesearch.run_lane("quick", "Brand Model", "claude-code")

    by_host = {site["host"]: site for site in result["sites"]}
    assert set(by_host) == {"reviews.test", "forum.test"}
    assert "page read by Kriko" in by_host["reviews.test"]["how"]
    assert "cited in the answer" in by_host["reviews.test"]["how"]
    assert "page read failed" in by_host["forum.test"]["how"]
    assert result["claims"] == [{"title": "Hinge fails", "urls": ["https://reviews.test/brand-model"]}]
    assert result["cost"]["tokens"] == 120 and not result["error"]


def test_an_agent_lane_counts_the_pages_the_agent_opened_itself(monkeypatch, tmp_path):
    _scratch_state(monkeypatch, tmp_path)

    class Agent:
        on_action = None
        spent, tokens_used = None, None

        def ask(self, brief):
            self.on_action('searched "Brand Model problems"')
            self.on_action("fetched https://www.owners.test/brand-model?session=zzz")
            self.on_action("fetched https://manual.test/brand-model.pdf")
            return json.dumps({"risks": [{
                "title": "Loose hinge", "why": "reported", "check": "open it twice",
                "severity": "medium", "url": "https://owners.test/brand-model",
                "quote": "the hinge loosens"}], "specs": []})

    monkeypatch.setattr("app.providers.harness_researcher", lambda **_k: Agent())
    result = livesearch.run_lane("agent", "Brand Model", "claude-code")

    assert result["agent_searches"] == ["Brand Model problems"]
    assert {site["host"] for site in result["sites"]} == {"owners.test", "manual.test"}
    assert "opened by the agent" in next(
        site for site in result["sites"] if site["host"] == "manual.test")["how"]
    assert all("session" not in url for site in result["sites"] for url in site["urls"])


def test_the_agent_lane_refuses_the_local_model_which_has_no_tools_of_its_own():
    with pytest.raises(ValueError, match="tools of its own"):
        livesearch.run_lane("agent", "Brand Model", "local")


def test_both_lanes_run_at_the_same_moment_not_one_after_the_other():
    meeting = threading.Barrier(2)

    def lane(name, product, agent, timeout):
        meeting.wait(timeout=5)  # serial lanes never meet, and this raises
        return {"lane": name, "product": product, "agent": agent, "started": 100.0 if name == "agent" else 101.0,
                "ended": 110.0, "seconds": 9.0, "error": "", "answer": "", "claims": [],
                "cost": {}, "searches": [], "opened": [], "log": [], "sites": []}

    report = livesearch.run_side_by_side("Brand Model", "claude-code", runner=lane)
    assert set(report["lanes"]) == {"agent", "quick"}
    assert report["overlap_seconds"] == 9.0


def test_the_report_says_which_sites_only_one_lane_checked(tmp_path):
    def result(name, hosts):
        return {"lane": name, "product": "Brand Model", "agent": "claude-code", "started": 1.0,
                "ended": 2.0, "seconds": 1.0, "error": "", "answer": "", "cost": {},
                "claims": [{"title": "Hinge fails", "urls": ["https://a.test/x"]}],
                "searches": [{"query": "Brand Model hinge", "engines": "", "at": 0.0, "ms": 40,
                              "results": [], "error": ""}],
                "opened": [{"url": f"https://{h}/p", "host": h, "at": 0.0, "ms": 5, "chars": 99,
                            "readable": True, "error": ""} for h in hosts],
                "log": [], "sites": [{"host": h, "how": ["page read by Kriko"], "urls": [f"https://{h}/p"]}
                                     for h in hosts]}

    lanes = {"agent": result("agent", ["a.test", "b.test"]), "quick": result("quick", ["a.test", "c.test"])}
    assert livesearch.compare(lanes) == {"shared": ["a.test"],
                                         "only": {"agent": ["b.test"], "quick": ["c.test"]}}
    report = {"product": "Brand Model", "agent": "claude-code", "when": "now", "lanes": lanes,
              "comparison": livesearch.compare(lanes), "overlap_seconds": 1.0}
    as_json, as_text = livesearch.write(report, tmp_path / "out")
    text = as_text.read_text(encoding="utf-8")
    assert "Only agent: b.test" in text and "Only quick: c.test" in text and "Both: a.test" in text
    assert json.loads(as_json.read_text(encoding="utf-8"))["product"] == "Brand Model"


def test_a_report_never_carries_a_secret_or_a_query_string():
    env = {"SOME_API_KEY": "sk-live-0123456789abcdef", "HOME": "/root"}
    assert livesearch.scrub("failed with sk-live-0123456789abcdef", env) == "failed with [redacted]"
    assert livesearch.plain_url("https://x.test/p?token=abc#frag") == "https://x.test/p"
    assert livesearch.urls_in("see https://x.test/a?k=1, and (https://y.test/b).") == [
        "https://x.test/a", "https://y.test/b"]


LIVE = pytest.mark.skipif(not os.environ.get("KRIKO_LIVE_SEARCH"),
                          reason="spends real searches and an agent; set KRIKO_LIVE_SEARCH=1")


@LIVE
def test_live_an_agent_search_and_a_quick_search_side_by_side():
    product = os.environ.get("KRIKO_LIVE_PRODUCT", "").strip()
    assert product, "name the product to look up in KRIKO_LIVE_PRODUCT"
    agent = os.environ.get("KRIKO_LIVE_AGENT", "").strip()
    report = livesearch.run_side_by_side(product, agent)
    out = Path(os.environ.get("KRIKO_LIVE_OUT") or Path.home() / ".kriko" / "live-search" / report["when"].replace(":", ""))
    _, as_text = livesearch.write(report, out)
    print("\n" + as_text.read_text(encoding="utf-8") + f"\nReport: {out}")

    for lane, one in report["lanes"].items():
        assert not one["error"], f"{lane} failed: {one['error']}"
        assert one["sites"], f"{lane} checked no site at all"
    # Concurrency is the point: serial lanes would have no moment in common.
    assert report["overlap_seconds"] > 0
    # The quick search reads pages itself, so its searches and page opens are all on record.
    quick = report["lanes"]["quick"]
    assert quick["searches"] and quick["opened"]
