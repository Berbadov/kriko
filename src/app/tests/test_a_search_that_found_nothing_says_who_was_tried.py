"""A search that found nothing says who was tried and what each one said.

"No results" is an answer a reader can act on only when it names the doors it
knocked on. The local plane's `nothing_read` already told apart a service that
did not answer, one that answered empty, and results that would not read; what
it did not say was *which* providers said what, so "the search service" stood
in for one provider or three, and a key that was refused read the same as a
service that was not running.
"""

from app.providers import local_agent, websearch
from app.providers.local_search_plan import attempts_said, nothing_read
from app.web import steps
from kriko.research.politeness import LocalSearchError


def test_nothing_read_names_every_provider_and_what_it_said():
    coverage = {
        "queries_searched": 0, "search_errors": 2,
        "search_attempts": [
            {"provider": "OpenSERP", "outcome": "error",
             "reason": "the SERP answered with a challenge page"},
            {"provider": "DeepSeek", "outcome": "error",
             "reason": "api.deepseek.com answered HTTP 401 (the key was refused)"},
        ],
    }

    said = nothing_read(coverage)

    assert "did not answer" in said, "the cause is still named first"
    assert "OpenSERP" in said and "challenge page" in said
    assert "DeepSeek" in said and "401" in said


def test_an_empty_answer_says_which_provider_answered_empty():
    coverage = {"queries_searched": 2, "search_errors": 0, "unique_hits": 0,
                "search_attempts": [{"provider": "openserp", "outcome": "empty",
                                     "reason": "answered, with no results"}]}
    said = nothing_read(coverage, "http://127.0.0.1:7000")
    assert "no results" in said and "openserp" in said


def test_a_reader_who_was_never_told_why_is_not_a_case_here():
    assert attempts_said([]) == ""
    assert attempts_said([{"provider": "x", "outcome": "ok"}]) == ""


def _asker(search):
    asker = local_agent.LocalAsker(lambda prompt: "[]", lambda prompt: "", search,
                                   lambda url, **_options: "",
                                   model="m", search_provider="openserp")
    asker.on_action = lambda line: None
    return asker


def test_a_run_whose_searches_all_failed_says_who_was_tried():
    def refused(query, limit=5, **_options):
        raise LocalSearchError("the search service is not running (connection refused)")

    asker = _asker(refused)
    pages = asker._read(["Widget MK2 problems"])

    assert pages == []
    reason = nothing_read(asker.search_coverage)
    assert "did not answer" in reason
    assert "openserp" in reason and "connection refused" in reason


def test_the_chain_quotes_each_provider_it_tried_in_its_own_line():
    said: list[str] = []

    def refusing(query, limit=5, **_options):
        raise LocalSearchError("connection refused")

    def empty(query, limit=5, **_options):
        return []

    chain = websearch.Chain([("openserp", lambda: refusing), ("deepseek", lambda: empty)],
                            log=said.append)
    assert chain("Widget MK2 owner reports", 5, timeout=2.0) == []
    line = next(one for one in said if one.startswith("searched"))
    assert "OpenSERP" in line and "connection refused" in line
    assert "DeepSeek" in line
    # And it is a search step, not a note: the reader can filter a run by it.
    classified = steps.classify(line)
    assert classified["source"] == "search"
    assert classified["title"] == line[:300]
