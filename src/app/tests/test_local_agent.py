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
from app.providers.local_inference import LocalInferenceError


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


def test_quick_answer_repairs_bad_json_once_and_keeps_source_and_self_checks():
    answer = json.dumps({"risks": [{"title": "Pump failure", "url": "https://a.test/1", "quote": "the pump failed"}], "specs": []})
    complete = Sequence(["not JSON", answer, '{"verdicts":[{"index":0,"supported":true,"reason":"the page reports it"}]}'])
    asker = local_agent.LocalAsker(Plan('["failure reports"]'), complete,
        searcher([{"url": "https://a.test/1"}]), reader({"https://a.test/1": "An owner said the pump failed."}),
        model="small", search_provider="stub")
    assert asker.ask_quick("Widget MK2") == answer
    assert asker.telemetry["queries"] == ["Widget MK2 problems owner reports", "Widget MK2 failures review"]
    assert asker.telemetry["repairs"] == 1
    assert asker.telemetry["verification"][0]["quote_in_read_page"] is True
    assert asker.telemetry["self_verify"]["verdicts"][0]["supported"] is True
    assert len(complete.prompts) == 3


def test_second_search_learns_from_the_first_pages():
    plan = Sequence(['["Widget MK2 pump recall"]'])
    answer = json.dumps({"risks": [{"title": "Pump failure", "url": "https://a.test/2", "quote": "the pump failed"}], "specs": []})
    complete = Sequence(['{"risks":[],"specs":[]}', answer, '{"verdicts":[]}'])
    asker = local_agent.LocalAsker(plan, complete,
        lambda query, limit: [{"url": "https://a.test/2" if "recall" in query else "https://a.test/1"}],
        reader({"https://a.test/1": "The first review names a revised pump.", "https://a.test/2": "A recall says the pump failed."}),
        model="small", search_provider="stub")
    assert asker.ask_quick("Widget MK2") == answer
    assert "first review names a revised pump" in plan.prompts[0]
    assert asker.telemetry["queries"][-1] == "Widget MK2 pump recall"
    assert len(asker.telemetry["queries"]) == 3


def test_invalid_answer_is_a_distinct_bounded_failure():
    complete = Sequence(["not JSON", "still not JSON"])
    asker = local_agent.LocalAsker(Plan('["query"]'), complete,
        searcher([{"url": "https://a.test/1"}]), reader({"https://a.test/1": "readable page"}),
        model="small", search_provider="stub")
    with pytest.raises(LocalInferenceError) as error:
        asker.ask_quick("Widget")
    assert error.value.code == "invalid_json"
    assert complete.calls == 2


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


def test_only_the_hosted_search_is_asked_in_parallel(monkeypatch):
    from app import providers
    from app.providers import exa_mcp, openserp

    monkeypatch.setattr(exa_mcp, "search_with_fallback", lambda: (lambda q, n: []))
    monkeypatch.setattr(openserp, "searcher", lambda base: (lambda q, n: []))
    hosted = providers.local_asker(base_url="http://127.0.0.1:1", serving_name="m",
                                   search_kind="exa")
    scraped = providers.local_asker(base_url="http://127.0.0.1:1", serving_name="m")
    assert hosted.parallel_search and not scraped.parallel_search


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
    assert any("slow page" in line for line in said)


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
    allowed = socket.prompt_chars_allowed()
    assert allowed == int((8192 - socket.max_tokens - 128) * local_inference.CHARS_PER_TOKEN)

    silent = local_inference.OpenAICompatSocket("http://127.0.0.1:1", "other")
    assert silent.context_tokens() == local_inference.DEFAULT_CONTEXT_TOKENS
