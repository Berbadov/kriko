"""A local run asks all its engines, not the first one named.

The research handler listed `bing,duckduckgo,ecosia` for pacing and then gave
the searcher only the first, so every research run depended on Bing alone,
the engine that answers empty about half the time (4 of 8 queries, measured).
Ecosia, blocked on every query, held a place in the list for nothing.
"""

from app.providers import openserp
from app.web import tasks


def plan():
    return {"url": "http://127.0.0.1:11434", "model": "m", "search_url": "",
            "search_kind": "openserp", "timeout": 10.0, "runtime_options": None,
            "context_tokens": None, "output_language": "auto",
            "search_language": "en", "line": "ready"}


def test_a_research_run_searches_through_every_engine(monkeypatch):
    asked = []
    real = openserp.searcher

    def recording(base_url="", engine="", **kwargs):
        asked.append(engine)
        return real(base_url, engine=engine, **kwargs)

    monkeypatch.setattr(openserp, "searcher", recording)
    monkeypatch.setattr(tasks, "_local_plan", lambda params, **kw: plan())
    plane = tasks._researcher({"backend": "local"})
    assert asked == [openserp.LOCAL_ENGINES]
    assert set(asked[0].split(",")) == {"google", "duckduckgo"}
    assert plane._scheduler is not None
    assert set(plane._scheduler._sources) == {"google", "duckduckgo"}


def test_a_named_engine_list_is_honoured_whole(monkeypatch):
    asked = []
    real = openserp.searcher
    monkeypatch.setattr(openserp, "searcher",
                        lambda base_url="", engine="", **kw: asked.append(engine) or real(
                            base_url, engine=engine, **kw))
    monkeypatch.setattr(tasks, "_local_plan", lambda params, **kw: plan())
    tasks._researcher({"backend": "local", "engines": "duckduckgo, google"})
    assert asked == ["duckduckgo,google"]


def test_no_engine_that_blocks_every_query_is_asked_by_default():
    assert "ecosia" not in openserp.LOCAL_ENGINES


def test_an_engine_that_answered_a_different_product_is_not_asked():
    """Bing answered a quoted Sony model with WhatsApp, and won the race by
    being fast. It is not in the shipped set; `carries_name` guards the rest."""
    assert "bing" not in openserp.LOCAL_ENGINES
