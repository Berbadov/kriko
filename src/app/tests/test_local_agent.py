"""The local asker's own legwork: queries, then pages read together.

No model and no network: the plan, the search, the fetcher and the reader are
stubs built here, exactly as the local plane's tests build theirs. What is
under test is the orchestration - which queries are kept, which pages are
read, what the model is handed, and what happens when a page will not read.
"""

import threading
import json

import pytest

from app.providers import local_agent
from app.providers.local_identity import ProductIdentity
from app.providers.local_inference import LocalInferenceError
from app.providers.local_pipeline import EXTRACT_SCHEMA
from app.tests.test_local_quicklook_output import PipelineModel


@pytest.fixture(autouse=True)
def short_pages_count(monkeypatch):
    """The stub pages here are a few words; a real page is not."""
    monkeypatch.setattr(local_agent, "MIN_PAGE_CHARS", 0)


class Plan:
    """The socket that proposes queries; scripted per test."""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class Complete:
    def __init__(self, reply: str = ""):
        self.reply = reply
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class Sequence(Complete):
    def __init__(self, replies):
        super().__init__()
        self.replies = iter(replies)
        self.calls = 0

    def __call__(self, prompt):
        self.prompts.append(prompt)
        self.calls += 1
        return next(self.replies)


class FirstPageBroken(PipelineModel):
    """The first evidence pass answers with no JSON; every later one is sound."""

    def json(self, prompt, schema):
        if schema == EXTRACT_SCHEMA and "extract" not in self.stages():
            self.calls.append(("extract", prompt, self.max_tokens))
            return "I found a pump failure but did not write JSON."
        return super().json(prompt, schema)


def test_a_malformed_page_is_said_and_the_other_page_still_grounds_its_card():
    good = "https://a.test/2"
    model = FirstPageBroken(findings=[{"title": "Pump failure", "why": "An owner reported it.",
                                       "needle": "the pump failed"}])
    asker = local_agent.LocalAsker(model, model,
        searcher([{"url": "https://a.test/1"}, {"url": good}]),
        reader({"https://a.test/1": "Widget MK2 forum: the first thread is about tyres.",
                good: "Widget MK2 owners report that the pump failed after a month."}),
        model="small", search_provider="stub")
    answer = json.loads(asker.ask_quick("Widget MK2"))
    assert [one["title"] for one in answer["risks"]] == ["Pump failure"]
    assert answer["risks"][0]["sources"][0]["url"] == good
    assert "the pump failed" in answer["risks"][0]["sources"][0]["quote"]
    # The malformed page is named as the error, and the check ran on the card.
    assert [row["stage"] for row in asker.coverage["errors"]] == ["https://a.test/1"]
    assert "verify" in model.stages()


def test_a_page_returned_by_two_queries_is_read_once():
    searched: list[str] = []
    model = PipelineModel(findings=[{"title": "Pump failure", "why": "An owner reported it.",
                                     "needle": "the pump failed"}],
                          queries=["Widget MK2 pump recall", "Widget MK2 pump failure"])
    asker = local_agent.LocalAsker(model, model,
        lambda query, limit: searched.append(query) or [{"url": "https://a.test/2"}],
        reader({"https://a.test/2": "Widget MK2 owners report that the pump failed."}),
        model="small", search_provider="stub")
    asker.ask_quick("Widget MK2")
    assert len(searched) >= 2
    assert model.stages().count("extract") == 1
    assert list(asker.sources) == ["https://a.test/2"]


def test_an_unreadable_evidence_reply_is_a_bounded_failure():
    model = PipelineModel(broken=("extract",))
    asker = local_agent.LocalAsker(model, model,
        searcher([{"url": "https://a.test/1"}]),
        reader({"https://a.test/1": "Widget MK2 owners report that the pump failed."}),
        model="small", search_provider="stub")
    with pytest.raises(LocalInferenceError, match="No evidence pass completed"):
        asker.ask_quick("Widget MK2")
    # One attempt for the one page, and no repair round after it.
    assert model.stages().count("extract") == 1


def searcher(hits, started=None, gate=None):
    def search(query, limit):
        if started is not None:
            started.append(query)
        if gate is not None:
            gate()
        return hits[:limit]
    return search


def reader(texts):
    def fetch(url):
        return texts.get(url, "")
    return fetch


def make(plan_reply, hits, texts, **over):
    plan = Plan(plan_reply)
    complete = Complete()
    asker = local_agent.LocalAsker(
        plan, complete, searcher(hits), reader(texts),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    return asker, plan, complete


def test_pages_are_named_in_the_prompt_with_their_urls():
    asker, _, complete = make(
        '["q1", "q2"]',
        [{"url": "https://a.test/1", "title": "A"},
         {"url": "https://a.test/2", "title": "B"}],
        {"https://a.test/1": "alpha text", "https://a.test/2": "beta text"})
    asker.ask("what goes wrong with the widget")
    assert "https://a.test/1" in complete.prompts[0]
    assert "alpha text" in complete.prompts[0]
    assert "https://a.test/2" in complete.prompts[0]


def test_an_unreadable_page_is_a_miss_not_a_failure():
    asker, _, complete = make(
        '["q1"]',
        [{"url": "https://a.test/gone", "title": "G"},
         {"url": "https://a.test/here", "title": "H"}],
        {"https://a.test/here": "the only readable page"})
    asker.ask("widget problems")
    assert "the only readable page" in complete.prompts[0]
    assert "https://a.test/gone" not in complete.prompts[0]


def test_a_raising_fetcher_is_a_miss_not_a_crash():
    def broken(url):
        raise RuntimeError("connection reset")
    plan = Plan('["q1"]')
    complete = Complete()
    asker = local_agent.LocalAsker(
        plan, complete, searcher([{"url": "https://a.test/x", "title": "X"}]),
        broken, model="m", search_provider="stub")
    asker.on_action = lambda line: None
    with pytest.raises(LocalInferenceError):
        asker.ask("widget problems")


def test_duplicate_queries_are_searched_once():
    asked: list[str] = []
    plan = Plan('["widget problems", "Widget Problems", " " , "widget faults"]')
    complete = Complete()
    asker = local_agent.LocalAsker(
        plan, complete,
        searcher([{"url": "https://a.test/1", "title": "A"}],
                 started=asked),
        reader({"https://a.test/1": "text"}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert len(asked) == 2


def test_pages_are_read_side_by_side_not_one_after_another():
    lock = threading.Lock()
    inside = []
    released = threading.Event()

    def gate():
        with lock:
            inside.append(1)
        if len(inside) >= 2:
            released.set()
        assert released.wait(5.0), "pages were fetched one at a time"

    plan = Plan('["q"]')
    complete = Complete()
    def fetch(url):
        gate()
        return f"text {url.rsplit('/', 1)[-1]}"

    asker = local_agent.LocalAsker(
        plan, complete,
        searcher([{"url": f"https://a.test/{i}", "title": str(i)}
                  for i in range(local_agent.MAX_PAGES)]),
        fetch,
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert len(complete.prompts) == 1


def test_the_searches_go_out_together_on_a_hosted_search():
    """Three queries, three searches in flight at once, not one by one."""
    inside: list[int] = []
    lock = threading.Lock()
    all_in = threading.Event()

    def gate():
        with lock:
            inside.append(1)
            if len(inside) >= 3:
                all_in.set()
        assert all_in.wait(5.0), "searches ran one at a time"

    plan = Plan('["q1", "q2", "q3"]')
    asker = local_agent.LocalAsker(
        plan, Complete(),
        searcher([{"url": "https://a.test/1", "title": "A"}], gate=gate),
        reader({"https://a.test/1": "text"}),
        model="m", search_provider="stub", parallel_search=True)
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert len(inside) == 3


def test_parallel_search_checks_cancellation_only_on_the_job_thread():
    """Search callbacks may run in workers; the job's SQLite connection may not."""
    owner = threading.get_ident()
    calls = []

    def search(query, limit):
        search.check_cancelled()
        calls.append(query)
        return [{"url": "https://a.test/1", "title": "A"}]

    search.check_cancelled = None
    asker = local_agent.LocalAsker(
        Plan("[]"), Complete(), search, reader({"https://a.test/1": "text"}),
        model="m", search_provider="stub", parallel_search=True)

    def owner_only_check():
        assert threading.get_ident() == owner, "job state was read in a search worker"

    asker.check_cancelled = owner_only_check
    asker.on_action = lambda line: None
    pages = asker._read(["q1", "q2"], identity=None)
    assert pages == [("https://a.test/1", "text")]
    assert set(calls) == {"q1", "q2"}


def test_parallel_search_reports_a_completed_query_while_another_is_slow():
    """A quick first response is visible without waiting for the slowest query."""
    slow_started = threading.Event()
    release_slow = threading.Event()
    fast_reported = threading.Event()
    said = []

    def search(query, limit):
        if query == "slow":
            slow_started.set()
            assert release_slow.wait(2)
        return [{"url": f"https://{query}.test/1", "title": query}]

    asker = local_agent.LocalAsker(
        Plan("[]"), Complete(), search, reader({
            "https://fast.test/1": "fast page", "https://slow.test/1": "slow page",
        }), model="m", search_provider="stub", parallel_search=True)
    def record(line):
        said.append(line)
        if "search returned" in line and "fast" in line:
            fast_reported.set()

    asker.on_action = record
    worker = threading.Thread(target=lambda: asker._read(["fast", "slow"]))
    worker.start()
    try:
        assert slow_started.wait(1)
        assert fast_reported.wait(0.5), "fast query was hidden behind the slow query"
    finally:
        release_slow.set()
        worker.join(2)
    assert not worker.is_alive()


def test_cancelling_parallel_search_stops_waiting_without_a_sqlite_cross_thread_check():
    slow_started = threading.Event()
    worker_stopped = threading.Event()
    checks = [0]

    def search(query, limit):
        if query == "slow":
            slow_started.set()
            while True:
                try:
                    search.check_cancelled()
                except local_agent.LocalSearchError:
                    worker_stopped.set()
                    return []
                threading.Event().wait(0.01)
        return [{"url": "https://fast.test/1", "title": "fast"}]

    search.check_cancelled = None
    asker = local_agent.LocalAsker(
        Plan("[]"), Complete(), search,
        reader({"https://fast.test/1": "fast page"}), model="m",
        search_provider="stub", parallel_search=True)

    def cancel_after_search_starts():
        checks[0] += 1
        if checks[0] > 1:
            raise RuntimeError("cancelled")

    asker.check_cancelled = cancel_after_search_starts
    worker = threading.Thread(target=lambda: _expect_cancelled_search(asker))
    worker.start()
    assert slow_started.wait(1)
    worker.join(1)
    assert not worker.is_alive(), "the canceled job waited for a search future"
    assert worker_stopped.wait(1), "the search worker did not see its stop signal"


def test_quicklook_reads_first_query_pages_while_secondary_search_is_still_running():
    secondary_started = threading.Event()
    first_page_started = threading.Event()
    first_page_reported = threading.Event()
    release_secondary = threading.Event()
    result = []

    def search(query, limit):
        if query == "secondary":
            secondary_started.set()
            assert release_secondary.wait(2)
        return [{"url": f"https://{query}.test/report", "title": query}]

    def fetch(url):
        first_page_started.set()
        return f"A sourced report about {url}."

    asker = local_agent.LocalAsker(
        Plan("[]"), Complete(), search, fetch,
        model="m", search_provider="openserp")
    def report(line):
        if "page fetched; checking product match: https://first.test/report" in line:
            first_page_reported.set()
    asker.on_action = report
    worker = threading.Thread(
        target=lambda: result.extend(asker._read(["first", "secondary"], quick=True)))
    worker.start()
    try:
        assert secondary_started.wait(1)
        assert first_page_started.wait(0.5), "page reading waited for the secondary search"
        assert first_page_reported.wait(0.5), "the first fetched page was hidden by a secondary search"
    finally:
        release_secondary.set()
        worker.join(2)
    assert not worker.is_alive()
    assert result and result[0][0] == "https://first.test/report"


def test_quicklook_keeps_completed_pages_when_search_budget_expires(monkeypatch):
    monkeypatch.setattr(local_agent, "QUICK_SEARCH_DEADLINE", 0.08)
    monkeypatch.setattr(local_agent, "QUICK_READ_DEADLINE", 0.5)
    slow_started = threading.Event()
    release_slow = threading.Event()
    seen_timeouts = []

    def search(query, limit, *, timeout=None):
        seen_timeouts.append(timeout)
        if query == "slow":
            slow_started.set()
            release_slow.wait(1)
        return [{"url": f"https://{query}.test/report", "title": query}]

    search.supports_timeout = True
    asker = local_agent.LocalAsker(
        Plan("[]"), Complete(), search,
        reader({"https://fast.test/report": "A sufficiently sourced report."}),
        model="m", search_provider="openserp")
    asker.on_action = lambda _line: None
    import time
    started = time.monotonic()
    try:
        pages = asker._read(["fast", "slow"], quick=True)
    finally:
        release_slow.set()
    elapsed = time.monotonic() - started

    assert slow_started.is_set()
    assert elapsed < 0.5
    assert pages == [("https://fast.test/report", "A sufficiently sourced report.")]
    assert asker.search_coverage["search_errors"] == 1
    assert len(seen_timeouts) == 2
    assert all(0 < timeout <= 0.08 for timeout in seen_timeouts)


def test_quicklook_passes_remaining_read_budget_and_disables_fallbacks(monkeypatch):
    monkeypatch.setattr(local_agent, "QUICK_READ_DEADLINE", 0.5)
    received = []

    def search(query, limit, **_kwargs):
        return [{"url": "https://source.test/report", "title": "Owner report"}]

    def fetch(url, **kwargs):
        received.append(kwargs)
        return "A sufficiently long report about a product issue. " * 3

    fetch.supports_cancel_check = True
    fetch.supports_timeout = True
    fetch.supports_fallback = True
    asker = local_agent.LocalAsker(
        Plan("[]"), Complete(), search, fetch,
        model="m", search_provider="openserp")
    asker.on_action = lambda _line: None

    pages = asker._read(["owner report"], quick=True)

    assert pages and pages[0][0] == "https://source.test/report"
    assert 0 < received[0]["timeout"] <= 0.5
    assert received[0]["allow_fallback"] is False
    assert callable(received[0]["check_cancelled"])


def test_one_query_quicklook_preserves_the_jobs_cancellation_exception(monkeypatch):
    from app.providers import openserp
    from app.web.jobs import Cancelled

    calls = []

    def urlopen(_request, **kwargs):
        calls.append("request")
        kwargs["check"]()

    monkeypatch.setattr(openserp.network, "urlopen", urlopen)
    search = openserp.searcher(engine="duck,bing,google", timeout=8.0)
    asker = local_agent.LocalAsker(
        Plan("[]"), Complete(), search, reader({}),
        model="m", search_provider="openserp")
    checks = [0]

    def cancel_during_request():
        checks[0] += 1
        if checks[0] == 2:
            raise Cancelled("reader stopped this run")

    asker.check_cancelled = cancel_during_request
    asker.on_action = lambda _line: None

    with pytest.raises(Cancelled, match="reader stopped this run"):
        asker._read(["one product query"], quick=True)

    assert calls == ["request"]


def test_quicklook_uses_a_fast_secondary_query_while_primary_search_is_pending():
    primary_started = threading.Event()
    fast_page_started = threading.Event()
    release_primary = threading.Event()

    def search(query, limit):
        if query == "primary":
            primary_started.set()
            assert release_primary.wait(2)
        return [{"url": f"https://{query}.test/report", "title": query}]

    def fetch(url):
        if url == "https://fast.test/report":
            fast_page_started.set()
        return f"A report about {url}."

    asker = local_agent.LocalAsker(
        Plan("[]"), Complete(), search, fetch,
        model="m", search_provider="openserp", parallel_search=True)
    asker.on_action = lambda _line: None
    worker = threading.Thread(
        target=lambda: asker._read(["primary", "fast"], quick=True))
    worker.start()
    try:
        assert primary_started.wait(1)
        assert fast_page_started.wait(0.5), "fast secondary hits waited behind the primary search"
    finally:
        release_primary.set()
        worker.join(2)
    assert not worker.is_alive()


def _expect_cancelled_search(asker):
    with pytest.raises(RuntimeError, match="cancelled"):
        asker._read(["fast", "slow"])


def test_a_local_scraper_is_searched_one_query_at_a_time():
    """No burst at a public search engine from the reader's own address."""
    inside = [0]
    most = [0]
    lock = threading.Lock()

    def search(query, limit):
        with lock:
            inside[0] += 1
            most[0] = max(most[0], inside[0])
        import time
        time.sleep(0.05)
        with lock:
            inside[0] -= 1
        return [{"url": f"https://a.test/{query}", "title": query}]

    asker = local_agent.LocalAsker(
        Plan('["q1", "q2", "q3"]'), Complete(), search,
        reader({f"https://a.test/q{i}": "text" for i in (1, 2, 3)}),
        model="m", search_provider="openserp")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert most[0] == 1


def test_a_page_that_never_answers_does_not_hold_the_run(monkeypatch):
    """The slow page is abandoned at the deadline; the others are read."""
    monkeypatch.setattr(local_agent, "READ_DEADLINE", 0.5)
    stuck = threading.Event()
    said: list[str] = []

    def fetch(url):
        if url.endswith("/slow"):
            stuck.wait(10.0)
            return "too late"
        return "the readable page"

    asker = local_agent.LocalAsker(
        Plan('["q"]'), Complete(),
        searcher([{"url": "https://a.test/slow", "title": "S"},
                  {"url": "https://a.test/fast", "title": "F"}]),
        fetch, model="m", search_provider="stub")
    asker.on_action = said.append
    import time
    started = time.monotonic()
    asker.ask("widget")
    stuck.set()
    assert time.monotonic() - started < 5.0
    assert list(asker.sources) == ["https://a.test/fast"]
    assert any("still waiting" in line for line in said)


def test_a_long_page_is_cut_around_the_queries_not_from_the_top():
    """The window a small model reads is the page's part about the subject.

    The kept text is also what the quotes are checked against, so a quote
    from the part the model never saw is still refused.
    """
    menu = "\n\n".join(f"Menu entry number {i} of the site" for i in range(400))
    page = ("Widget page\n\n" + menu
            + "\n\nThe widget gearbox fails at 60 000 km, owners report.")
    asker = local_agent.LocalAsker(
        Plan('["widget gearbox fails"]'), Complete(),
        searcher([{"url": "https://a.test/1", "title": "A"}]),
        reader({"https://a.test/1": page}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    kept = asker.sources["https://a.test/1"]
    assert len(kept) <= local_agent.PAGE_CHARS
    assert "gearbox fails at 60 000 km" in kept
    assert kept.startswith("Widget page")


def test_a_stub_page_is_a_miss_and_a_spare_takes_its_place(monkeypatch):
    """A cookie wall or an 'access denied' is not one of the pages read."""
    monkeypatch.setattr(local_agent, "MIN_PAGE_CHARS", 80)
    monkeypatch.setattr(local_agent, "MAX_PAGES", 1)
    asker = local_agent.LocalAsker(
        Plan('["q"]'), Complete(),
        searcher([{"url": "https://a.test/wall", "title": "W"},
                  {"url": "https://a.test/real", "title": "R"}]),
        reader({"https://a.test/wall": "Access denied",
                "https://a.test/real": "A real page. " * 30}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert list(asker.sources) == ["https://a.test/real"]


def test_product_document_hits_are_kept_ahead_of_unrelated_video_results(monkeypatch):
    monkeypatch.setattr(local_agent, "MAX_PAGES", 1)
    identity = ProductIdentity(
        canonical_name="Acme Motor Oil XW-40", variant="XW-40",
        identifiers=("XW-40",), unknowns=("approval specification",))
    hits = ([{"url": f"https://video{i}.test/watch", "title": "Electric brush review"}
             for i in range(8)]
            + [{"url": "https://acme.test/xw40", "title": "Acme Motor Oil XW-40 technical data sheet"}])
    fetched = []

    def fetch(url):
        fetched.append(url)
        return "Acme Motor Oil XW-40 technical data: product specifications and approvals."

    asker = local_agent.LocalAsker(
        Plan("[]"), Complete(), searcher(hits), fetch,
        model="m", search_provider="stub")
    pages = asker._read(['"Acme Motor Oil XW-40" manufacturer technical data'],
                        identity=identity, prefer_issues=True)

    assert [url for url, _ in pages] == ["https://acme.test/xw40"]
    assert "https://acme.test/xw40" in fetched
    assert len(fetched) <= 1 + local_agent.SPARE_PAGES
    assert asker.relevant_sources == dict(pages)


def test_unrelated_hits_use_only_the_small_spare_fetch_budget(monkeypatch):
    monkeypatch.setattr(local_agent, "MAX_PAGES", 1)
    identity = ProductIdentity(canonical_name="Acme Motor Oil XW-40",
                               identifiers=("XW-40",))
    hits = [{"url": f"https://video{i}.test/watch", "title": "Electric brush review"}
            for i in range(20)]
    fetched = []
    asker = local_agent.LocalAsker(
        Plan("[]"), Complete(), searcher(hits),
        lambda url: fetched.append(url) or "Electric brush review and cleaning advice.",
        model="m", search_provider="stub")

    pages = asker._read(["Acme Motor Oil XW-40 failure"], identity=identity,
                        prefer_issues=True)

    assert pages == []
    assert len(fetched) <= 1 + local_agent.SPARE_PAGES


class Fitted(Complete):
    """A completion socket that knows its window, as the real one does."""

    max_tokens = 100

    def __init__(self, allowed: int):
        super().__init__()
        self.allowed = allowed

    def prompt_chars_allowed(self) -> int:
        return self.allowed

    def context_tokens(self) -> int:
        return 4096


def test_the_prompt_is_fitted_to_the_models_window():
    """A server cuts an overflowing prompt from the front, silently; the
    front is the instructions. So the pages share what the brief leaves,
    and the sources are exactly what was shown."""
    long_page = "\n\n".join(f"Paragraph {i} about the widget gearbox." for i in range(400))
    complete = Fitted(allowed=6000)
    asker = local_agent.LocalAsker(
        Plan('["widget gearbox"]'), complete,
        searcher([{"url": f"https://a.test/{i}", "title": str(i)} for i in range(3)]),
        reader({f"https://a.test/{i}": long_page for i in range(3)}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert len(complete.prompts[0]) <= 6000
    shown = complete.prompts[0]
    for text in asker.sources.values():
        assert text in shown


def test_too_small_a_window_shows_fewer_pages_whole_enough_to_quote():
    long_page = "\n\n".join(f"Paragraph {i} about the widget gearbox." for i in range(400))
    complete = Fitted(allowed=local_agent.MIN_SHARE * 2 + 1500)
    asker = local_agent.LocalAsker(
        Plan('["widget gearbox"]'), complete,
        searcher([{"url": f"https://a.test/{i}", "title": str(i)} for i in range(5)]),
        reader({f"https://a.test/{i}": long_page for i in range(5)}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert 1 <= len(asker.sources) < 5
    assert all(len(text) >= local_agent.MIN_SHARE // 2 for text in asker.sources.values())


class Windowed(Fitted):
    """The real socket's two numbers: research budget and whole window."""

    def __init__(self, allowed: int, window: int):
        super().__init__(allowed)
        self.window = window

    def window_chars(self) -> int:
        return self.window


def test_a_long_brief_is_charged_to_the_window_not_to_the_evidence_budget():
    """#181: an 11.7k-character authoring brief against a 12k research budget
    left no room on a 16k window, which holds about 45k characters. The brief
    is measured against the window; the evidence against the budget."""
    page = "\n\n".join(f"Paragraph {i} about the widget gearbox." for i in range(400))
    pages = {f"https://site{n}.test/r": f"Site {n}. " + page for n in range(3)}
    complete = Windowed(allowed=12000, window=45000)
    asker = local_agent.LocalAsker(
        Plan('["widget gearbox"]'), complete,
        searcher([{"url": f"https://site{i}.test/r", "title": str(i)} for i in range(3)]),
        reader(pages),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    brief = "widget\n" + "Write the catalog this way. " * 420  # ~11.8k characters
    asker.ask(brief)
    assert len(asker.sources) == 3
    shown = sum(len(text) for text in asker.sources.values())
    assert 3 * local_agent.MIN_SHARE <= shown <= 12000
    assert len(complete.prompts[0]) <= 45000


def test_a_brief_the_window_cannot_hold_says_its_numbers():
    complete = Windowed(allowed=12000, window=9000)
    asker = local_agent.LocalAsker(
        Plan('["q"]'), complete, searcher([{"url": "https://a.test/1", "title": "A"}]),
        reader({"https://a.test/1": "text " * 400}), model="m", search_provider="stub")
    asker.on_action = lambda line: None
    with pytest.raises(local_agent.LocalInferenceError) as raised:
        asker.ask("widget\n" + "x" * 11000)
    assert "4096-token window holds about 9000" in str(raised.value)


def test_the_reply_budget_is_said_to_the_model():
    complete = Fitted(allowed=100_000)
    asker = local_agent.LocalAsker(
        Plan('["q"]'), complete, searcher([{"url": "https://a.test/1", "title": "A"}]),
        reader({"https://a.test/1": "text"}), model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert "about 60 words" in complete.prompts[0]


def test_a_url_or_a_sentence_is_not_a_query_and_the_planner_is_asked_again():
    """Measured on a 3B model: its "query" was a url from the reply format."""
    replies = iter(['["https://www.example.test/review", "www.example.test"]',
                    '["widget gearbox failure", "widget owners forum"]'])
    prompts: list[str] = []

    def planner(prompt):
        prompts.append(prompt)
        return next(replies)

    asked: list[str] = []
    asker = local_agent.LocalAsker(
        planner, Complete(),
        searcher([{"url": "https://a.test/1", "title": "A"}], started=asked),
        reader({"https://a.test/1": "text"}), model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert len(prompts) == 2
    assert asked == ["widget gearbox failure", "widget owners forum"]
    assert local_agent.LocalAsker._usable('["' + "word " * 20 + '"]') == []


def test_the_socket_asks_the_server_for_its_window(monkeypatch):
    """Ollama says it in `/api/ps`; nothing answering is the 4k default."""
    import io
    import json as _json

    from app.providers import local_inference

    socket = local_inference.OpenAICompatSocket("http://127.0.0.1:1", "m:3b")
    answers = {"/api/ps": {"models": [{"name": "m:3b", "context_length": 8192}]}}

    def urlopen(url, timeout=0):
        path = url.removeprefix("http://127.0.0.1:1")
        if path not in answers:
            raise OSError("nothing here")
        return io.BytesIO(_json.dumps(answers[path]).encode())

    monkeypatch.setattr(local_inference.urllib.request, "urlopen", urlopen)
    assert socket.context_tokens() == 8192
    # The window holds the whole prompt at CHARS_PER_TOKEN; the research
    # budget (`context_chars`) bounds only the evidence (#181).
    assert socket.window_chars() == int((8192 - socket.max_tokens - 128) * local_inference.CHARS_PER_TOKEN)
    assert socket.prompt_chars_allowed() == min(socket.context_chars,
                                                8192 - socket.max_tokens - 128 - 128)

    silent = local_inference.OpenAICompatSocket("http://127.0.0.1:1", "other")
    assert silent.context_tokens() == local_inference.DEFAULT_CONTEXT_TOKENS


# ---- one site is not research ----
#
# The reader's words: the small agent is "sticking to one resource". Two of the
# three pages it read were the same forum, because hits were taken in the order
# they came and one site topped every query.

from app.providers.local_components import search as search_round


def _hits(*urls):
    return [{"url": url} for url in urls]


def test_every_query_gets_its_best_page_before_any_gets_its_second():
    first = _hits("https://a.test/1", "https://a.test/2", "https://a.test/3")
    second = _hits("https://b.test/1", "https://b.test/2")
    assert search_round.diversify([first, second], 4, seen=set(), per_host=9) == [
        "https://a.test/1", "https://b.test/1", "https://a.test/2", "https://b.test/2"]


def test_one_site_cannot_fill_the_list():
    forum = _hits(*[f"https://forum.test/t/{i}" for i in range(6)])
    other = _hits("https://review.test/x", "https://shop.test/y")
    wanted = search_round.diversify([forum, other], 5, seen=set())
    assert [u for u in wanted if "forum.test" in u] == ["https://forum.test/t/0", "https://forum.test/t/1"]
    assert "https://review.test/x" in wanted and "https://shop.test/y" in wanted


def test_www_and_the_bare_host_are_one_site():
    assert search_round.host_of("https://www.Example.com/a") == search_round.host_of("https://example.com/b")


def test_a_url_already_read_is_not_asked_again():
    seen = {"https://a.test/1"}
    wanted = search_round.diversify([_hits("https://a.test/1", "https://a.test/2")], 3, seen=seen)
    assert wanted == ["https://a.test/2"] and "https://a.test/2" in seen


def test_a_page_that_will_not_load_is_replaced_by_a_spare():
    queries = ["q1", "q2"]
    hits = {"q1": _hits("https://a.test/1", "https://a.test/2"), "q2": _hits("https://b.test/1", "https://c.test/1")}
    refused = {"https://a.test/1"}

    def fetch(url):
        if url in refused:
            raise OSError("403")
        return f"readable text of {url}"

    pages, tried = search_round.gather(
        lambda query, n: hits[query], fetch, queries, seen=set(), searched=set(),
        limit=3, hits_per_query=2)
    assert len(pages) == 3, "three pages were asked for and three readable ones exist"
    assert "https://a.test/1" in tried and all(url != "https://a.test/1" for url, _ in pages)


def _identity_reply(name: str) -> str:
    return json.dumps({"canonical_name": name, "aliases": [], "variant": "",
                       "identifiers": [], "unknowns": [], "evidence": []})


class Structured(Complete):
    """The real socket's structured door, which the identity step uses."""

    def json(self, prompt: str, schema: dict) -> str:
        return self(prompt)


def _namer(reply: str):
    asker = local_agent.LocalAsker(
        Plan("[]"), Structured(reply), searcher([]), reader({}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    return asker


def test_the_seller_words_are_taken_off_a_listing_title():
    """#181: "DEMİRAY OTODAN DEĞİŞENSİZ BAKIMLI COROLLA 1.8 HYBRID" was
    authored, searched and named as a whole. The product inside it is."""
    title = "DEMİRAY OTODAN DEĞİŞENSİZ BAKIMLI COROLLA 1.8 HYBRID"
    assert _namer(_identity_reply("COROLLA 1.8 HYBRID")).name_product(title) == "COROLLA 1.8 HYBRID"


def test_a_name_not_in_the_title_is_not_taken_and_the_title_is_no_news():
    title = "DEMİRAY OTODAN DEĞİŞENSİZ BAKIMLI COROLLA 1.8 HYBRID"
    # Invented words are refused by grounding; the title itself is "".
    assert _namer(_identity_reply("Toyota Prius 2.0")).name_product(title) == ""
    assert _namer(_identity_reply(title)).name_product(title) == ""
