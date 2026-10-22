"""SearXNG answers one JSON page; the adapter maps it to the search shape.

The service is not bundled and not assumed: these tests hand the adapter the
bytes an instance would send, so they run offline and describe the contract
the rest of the engine relies on.
"""

from __future__ import annotations

import json

import pytest

from app.providers import searxng


def page(results: list[dict]) -> bytes:
    return json.dumps({"results": results, "number_of_results": len(results)}).encode()


def test_a_json_page_becomes_the_shape_the_engine_searches_with() -> None:
    seen: dict[str, str] = {}

    def transport(url: str, timeout: float) -> bytes:
        seen["url"] = url
        return page([
            {"url": "https://www.ifixit.com/Answers/View/1/trigger",
             "title": "Trigger stuck", "engine": "google"},
            {"url": "https://example.com/a", "title": "", "engine": "duckduckgo"},
        ])

    search = searxng.searcher("http://searx.local:8888", transport=transport)
    hits = search("dyson trigger", 5)

    assert hits == [
        {"url": "https://www.ifixit.com/Answers/View/1/trigger",
         "title": "Trigger stuck", "site": "google"},
        {"url": "https://example.com/a", "title": "", "site": "duckduckgo"},
    ]
    assert "format=json" in seen["url"]
    assert "q=dyson+trigger" in seen["url"]


def test_the_limit_caps_what_the_page_offered() -> None:
    def transport(url: str, timeout: float) -> bytes:
        return page([{"url": f"https://example.com/{index}", "title": ""}
                     for index in range(9)])

    assert len(searxng.searcher(transport=transport)("anything", 3)) == 3


def test_an_html_answer_names_the_setting_that_turns_json_on() -> None:
    def transport(url: str, timeout: float) -> bytes:
        return b"<!doctype html><html><body>results</body></html>"

    with pytest.raises(searxng.LocalSearchError, match="search.formats"):
        searxng.searcher(transport=transport)("anything", 3)


def test_a_dead_instance_is_a_search_error_with_the_reason() -> None:
    def transport(url: str, timeout: float) -> bytes:
        raise OSError("connection refused")

    with pytest.raises(searxng.LocalSearchError, match="connection refused"):
        searxng.searcher(transport=transport)("anything", 3)


def test_rows_without_a_url_are_dropped_rather_than_read() -> None:
    def transport(url: str, timeout: float) -> bytes:
        return page([{"title": "no address"}, {"url": "https://example.com/ok"}])

    hits = searxng.searcher(transport=transport)("anything", 5)
    assert [hit["url"] for hit in hits] == ["https://example.com/ok"]
