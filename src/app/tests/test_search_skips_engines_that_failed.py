"""A blocked search engine is left out of later queries, then retried."""

import json

from app.providers import openserp


class _Reply:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _asked(monkeypatch, replies):
    seen = []

    def urlopen(request, timeout=None):
        seen.append(request.full_url)
        return _Reply(replies.pop(0))

    monkeypatch.setattr(openserp.urllib.request, "urlopen", urlopen)
    return seen


def _reset():
    openserp._failed_at.clear()


def test_an_engine_the_service_reports_failed_is_not_asked_again(monkeypatch):
    _reset()
    hit = {"url": "https://example.test/a", "title": "a", "domain": "example.test"}
    seen = _asked(monkeypatch, [
        {"results": [hit], "meta": {"engines_failed": ["ecosia"]}},
        {"results": [hit], "meta": {}},
    ])
    search = openserp.searcher(engine="google,ecosia,bing")
    search("one")
    search("two")
    assert "engines=google%2Cecosia%2Cbing" in seen[0]
    assert "engines=google%2Cbing" in seen[1]
    _reset()


def test_the_engine_is_tried_again_after_the_cooldown(monkeypatch):
    _reset()
    hit = {"url": "https://example.test/a", "title": "a", "domain": "example.test"}
    seen = _asked(monkeypatch, [
        {"results": [hit], "meta": {"engines_failed": ["ecosia"]}},
        {"results": [hit], "meta": {}},
    ])
    search = openserp.searcher(engine="google,ecosia")
    search("one")
    openserp._failed_at["ecosia"] -= openserp.ENGINE_COOLDOWN_SECONDS + 1
    search("two")
    assert "engines=google%2Cecosia" in seen[1]
    _reset()


def test_when_every_engine_failed_they_are_all_asked_anyway(monkeypatch):
    _reset()
    openserp._failed_at.update({"google": 1e12, "bing": 1e12})
    assert openserp._engines_to_ask("google,bing") == "google,bing"
    _reset()


def test_a_google_click_through_with_an_opaque_token_is_not_a_result():
    assert openserp._is_ad_or_search_redirect("https://www.google.com/goto?url=CAESjQEB6zsw")
    assert not openserp._is_ad_or_search_redirect("https://www.google.com/search?q=widget")
