"""A publication date, from the page that carried it to the row that keeps it.

`sources.published_at` was written by nobody for months while two builders
read it correctly and the ranking never touched it -- honestly empty rather
than secretly weighted, which is why it was a backlog entry and not an
incident. The scraping pipeline is one way in; this covers the other, the
research plane an agent drives, where the markup exists for exactly as long as
it takes to turn it into prose.

The distinction these tests defend is the one the column exists for: when the
world published a thing is not when this machine read it. A fetch date
standing in for a publication date would make every source look current, which
is worse than an empty column because it cannot be told apart from a real
answer.
"""

from kriko.research.base import Document, Fetched, ResearchTask


def _task():
    return ResearchTask(
        subject_id="s",
        subject_label="S",
        subject_kind="product",
        pack_id="demo",
        queries=("q",),
        max_documents=1,
    )


def test_a_reader_may_answer_with_bare_text_or_with_a_date():
    """The richer reply is optional, so no existing reader is broken by it."""
    assert Fetched("prose").published_at == ""
    assert Fetched("prose", "2021-04-05").published_at == "2021-04-05"


def test_a_document_that_was_never_dated_says_so_with_nothing():
    assert Document(url="u", text="t").published_at == ""


def test_the_engine_takes_a_date_from_a_reader_that_found_one():
    from kriko.research.api import ApiResearcher

    def search(query, limit):
        return [{"url": "https://example.invalid/a", "title": "A", "site": "example.invalid"}]

    def fetch(url):
        return Fetched("a body of prose long enough to keep", "2021-04-05")

    found = ApiResearcher(search, fetch, lambda *a, **k: "").gather(
        _task()
    )
    assert [one.published_at for one in found] == ["2021-04-05"]


def test_a_reader_still_answering_with_a_string_is_not_punished():
    from kriko.research.api import ApiResearcher

    def search(query, limit):
        return [{"url": "https://example.invalid/a", "title": "A", "site": "example.invalid"}]

    found = ApiResearcher(
        search, lambda url: "a body of prose long enough to keep", lambda *a, **k: ""
    ).gather(
        _task()
    )
    assert [one.published_at for one in found] == [""]
