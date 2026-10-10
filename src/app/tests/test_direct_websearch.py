import io
import urllib.error

import pytest

from app.providers import websearch
from kriko.research.politeness import LocalSearchError


def test_result_links_are_unwrapped_and_navigation_is_not_evidence():
    body = '<a href="/settings">Settings</a><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fforum.example%2Ffailure">Owner &amp; repair</a>'
    assert websearch.parse(body) == [{"url": "https://forum.example/failure", "title": "Owner & repair", "site": "forum.example"}]


def test_rate_limited_engine_is_cooled_down_and_repeat_queries_are_cached():
    called = []
    def opener(request, **kwargs):
        called.append(request.full_url)
        if "first.example" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 429, "limited", {}, None)
        return io.BytesIO(b'<h2><a href="https://forum.example/failure">Widget repair report</a></h2>')
    search = websearch.searcher(opener=opener, clock=lambda: 100,
        providers=(("first", "https://first.example/?q={query}"), ("second", "https://second.example/?q={query}")))
    assert search("widget failures", 3)[0]["site"] == "forum.example"
    search("widget failures", 3)
    assert len(called) == 2
    search("widget repairs", 3)
    assert len(called) == 3 and "second.example" in called[-1]


def test_challenges_are_reported_instead_of_returned_as_sources():
    with pytest.raises(LocalSearchError, match="challenge"):
        websearch.parse('<form class="anomaly-modal">Please solve this</form>')


def test_all_provider_failures_have_a_named_error():
    def opener(*args, **kwargs):
        raise urllib.error.URLError("offline")
    with pytest.raises(LocalSearchError, match="duckduckgo.*bing"):
        websearch.searcher(opener=opener)("widget failures")


def test_bing_redirects_resolve_to_original_sources():
    import base64
    url = "https://forum.example/failure"
    encoded = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    body = f'<h2><a href="https://www.bing.com/ck/a?!&amp;u=a1{encoded}&amp;ntb=1">Repair report</a></h2>'
    assert websearch.parse(body)[0]["url"] == url


def test_unrelated_result_sets_do_not_become_research_sources():
    assert not websearch.relevant({"title": "Game downloads", "url": "https://games.example"}, "Northstar AX-1040R2 failures")
    assert websearch.relevant({"title": "Northstar AX-1040R2 repair report", "url": "https://forum.example"}, "Northstar AX-1040R2 failures")
