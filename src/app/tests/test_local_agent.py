"""The local asker's own legwork: queries, then pages read together.

No model and no network: the plan, the search, the fetcher and the reader are
stubs built here, exactly as the local plane's tests build theirs. What is
under test is the orchestration - which queries are kept, which pages are
read, what the model is handed, and what happens when a page will not read.
"""

import threading

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


def test_the_local_run_reports_its_live_stages_and_engine_counters():
    asker, _, _ = make(
        '["widget problems"]',
        [{"url": "https://a.test/1", "title": "A"}],
        {"https://a.test/1": "The widget gearbox can fail."})
    snapshots = []
    asker.on_telemetry = snapshots.append

    asker.ask("widget problems")

    assert [one["stage"] for one in snapshots] == [
        "planning searches", "searching the web", "reading pages",
        "learning from the first pages", "answering from pages",
        "self-verifying answer", "checking cited quotes",
    ]
    assert snapshots[-1]["queries"] == ["widget problems"]
    assert snapshots[-1]["pages_read"] == 1
    assert snapshots[-1]["pages"] == ["https://a.test/1"]
    assert snapshots[-1]["model_calls"] == 4


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
                    '["widget gearbox failure", "widget owners forum"]',
                    '[]'])
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
    assert len(prompts) == 3
    assert asked == ["widget gearbox failure", "widget owners forum"]
    assert local_agent.LocalAsker._usable('["' + "word " * 20 + '"]') == []


def test_the_second_search_round_uses_the_first_pages_to_fill_a_gap():
    replies = iter([
        '["gearbox failures"]',
        '["gearbox owner repair reports"]',
    ])
    prompts = []
    searches = []

    def planner(prompt):
        prompts.append(prompt)
        return next(replies)

    def search(query, limit):
        searches.append(query)
        page = "first" if query == "gearbox failures" else "followup"
        return [{"url": f"https://a.test/{page}", "title": page}]

    pages = {
        "https://a.test/first": "Owners report gearbox failures under load.",
        "https://a.test/followup": "A repair shop replaced the gearbox twice.",
    }
    complete = Complete('{"risks":[]}')
    asker = local_agent.LocalAsker(
        planner, complete, search, reader(pages),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None

    asker.ask("widget gearbox reliability")

    assert searches == ["gearbox failures", "gearbox owner repair reports"]
    assert "Owners report gearbox failures" in prompts[1]
    assert "https://a.test/first" in complete.prompts[0]
    assert "https://a.test/followup" in complete.prompts[0]
    assert asker.queries == ["gearbox failures", "gearbox owner repair reports"]
    assert list(asker.sources) == ["https://a.test/first", "https://a.test/followup"]


def test_a_followup_planner_repairs_one_bad_json_reply_and_keeps_the_run():
    replies = iter([
        '["given widget query"]',
        "not json",
        '["new widget owner reports"]',
    ])
    plan_prompts = []
    searched = []

    def planner(prompt):
        plan_prompts.append(prompt)
        return next(replies)

    def search(query, limit):
        searched.append(query)
        suffix = "first" if query == "given widget query" else "followup"
        return [{"url": f"https://a.test/{suffix}", "title": suffix}]

    asker = local_agent.LocalAsker(
        planner, Complete('{"risks":[]}'), search,
        reader({"https://a.test/first": "first page text",
                "https://a.test/followup": "follow-up page text"}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None

    asker.ask("widget")

    assert len(plan_prompts) == 3
    assert "first page text" in plan_prompts[1]
    assert searched == ["given widget query", "new widget owner reports"]
    assert list(asker.sources) == ["https://a.test/first", "https://a.test/followup"]


def test_the_model_self_check_is_bounded_retried_and_kept_with_telemetry():
    answer = (
        '{"risks":['
        '{"title":"Gearbox failure","why":"The gearbox fails under load.",'
        '"url":"https://a.test/1","quote":"gearbox fails under load"},'
        '{"title":"Made-up fault","why":"The switch catches fire.",'
        '"url":"https://a.test/1","quote":"the switch catches fire"}]}'
    )
    verdicts = iter([
        "not json",
        '{"items":[{"index":0,"verdict":"supported"},'
        '{"index":1,"verdict":"unsupported"}]}',
    ])

    class Verifier(Complete):
        def __call__(self, prompt):
            self.prompts.append(prompt)
            return next(verdicts)

    verifier = Verifier()
    asker = local_agent.LocalAsker(
        Plan('[]'), Complete(answer),
        searcher([{"url": "https://a.test/1", "title": "A"}]),
        reader({"https://a.test/1": "The gearbox fails under load."}),
        model="m", search_provider="stub", verify=verifier,
        given_queries=["widget gearbox failures"])
    asker.on_action = lambda line: None

    asker.ask("widget")

    assert len(verifier.prompts) == 2
    assert "Gearbox failure" in verifier.prompts[0]
    assert "The gearbox fails under load." in verifier.prompts[0]
    assert asker.self_verification == {
        "status": "complete", "verdict": "mixed", "checked": 2,
        "supported": 1, "unsupported": 1, "unclear": 0,
        "items": [
            {"index": 0, "verdict": "supported"},
            {"index": 1, "verdict": "unsupported"},
        ],
    }
    assert asker.telemetry("complete")["self_verification"]["verdict"] == "mixed"
    assert asker.model_calls == 3


def test_self_check_preserves_raw_risk_indexes_when_non_objects_are_skipped():
    answer = '{"risks":[null,{"title":"One"},false,{"title":"Three"}]}'
    verifier = Complete(
        '{"items":[{"index":1,"verdict":"supported"},'
        '{"index":3,"verdict":"unclear"}]}')
    asker = local_agent.LocalAsker(
        Plan('[]'), Complete(answer), lambda *_: [], lambda *_: "",
        model="m", search_provider="stub", verify=verifier)

    asker._self_verify(answer)

    assert asker.self_verification == {
        "status": "complete", "verdict": "inconclusive", "checked": 2,
        "supported": 1, "unsupported": 0, "unclear": 1,
        "items": [
            {"index": 1, "verdict": "supported"},
            {"index": 3, "verdict": "unclear"},
        ],
    }


def test_quote_repair_changes_only_a_quote_that_the_page_can_ground():
    page = ("Owners report the hinge came loose after four months. "
            "The port stops charging.")
    answer = (
        '{"risks":['
        '{"title":"Loose hinge","why":"Owners report a loose hinge.",'
        '"url":"https://a.test/1","quote":"a hinge failed"},'
        '{"title":"Grounded port","why":"The port stops charging.",'
        '"url":"https://a.test/1","quote":"port stops charging"}]}'
    )
    repair = Complete(
        '{"items":[{"index":0,"quote":"hinge came loose after four months"},'
        '{"index":1,"quote":"invented words"}]}')
    asker = local_agent.LocalAsker(
        Plan('[]'), Complete(answer), lambda *_: [], lambda *_: "",
        model="m", search_provider="stub", repair=repair)
    asker.sources = {"https://a.test/1": page}

    fixed = asker._repair_quotes(answer)

    from app.packauthor import _payload

    risks = _payload(fixed)["risks"]
    assert risks[0]["quote"] == "hinge came loose after four months"
    assert risks[0]["title"] == "Loose hinge"
    assert risks[0]["why"] == "Owners report a loose hinge."
    assert risks[1]["quote"] == "port stops charging"
    assert len(repair.prompts) == 1
    assert '"index": 0' in repair.prompts[0]
    assert '"index": 1' not in repair.prompts[0]
    assert asker.quote_repair == {
        "status": "complete", "checked": 1, "repaired": 1, "unrepaired": 0,
    }
    assert asker.model_calls == 1


def test_quote_repair_rejects_a_quote_from_a_different_fetched_page():
    answer = (
        '{"risks":[{"title":"Loose hinge","why":"It loosens.",'
        '"url":"https://a.test/1","quote":"not on this page"}]}'
    )
    repair = Complete(
        '{"items":[{"index":0,"quote":"a charging port can fail"}]}')
    asker = local_agent.LocalAsker(
        Plan('[]'), Complete(answer), lambda *_: [], lambda *_: "",
        model="m", search_provider="stub", repair=repair)
    asker.sources = {
        "https://a.test/1": "The hinge screws may loosen over time.",
        "https://b.test/2": "A charging port can fail.",
    }

    fixed = asker._repair_quotes(answer)

    from app.packauthor import _payload

    assert _payload(fixed)["risks"][0]["quote"] == "not on this page"
    assert asker.quote_repair == {
        "status": "unrepaired", "checked": 1, "repaired": 0, "unrepaired": 1,
    }


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
