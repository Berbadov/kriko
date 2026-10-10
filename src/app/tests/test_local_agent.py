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
    # One answer prompt carrying every page. The self-check after it, and the
    # shape repair an empty reply earns, are further calls by design; the
    # answer is still one completion, not one per page.
    answers = [one for one in complete.prompts
               if "These are the only sources you have" in one
               and "Your last reply" not in one]
    assert len(answers) == 1


class Scripted:
    """A socket with one reply per call, for the rounds that ask twice."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_a_broken_json_plan_reply_is_repaired_not_fatal():
    plan = Scripted(["i will help you search!", "ok, searching now", '["q1"]'])
    complete = Complete()
    asker = local_agent.LocalAsker(
        plan, complete,
        searcher([{"url": f"https://a.test/{n}", "title": str(n)}
                   for n in range(3)]),
        reader({f"https://a.test/{n}": f"text {n}" for n in range(3)}),
        model="m", search_provider="stub")
    said = []
    asker.on_action = said.append
    asker.ask("widget problems")
    # Three asks of the planner: the first reply, the repair re-ask, the
    # one that held the shape. Round one found three pages, so no fourth
    # (the round-two refinement) was ever needed.
    assert len(plan.prompts) == 3
    assert "Your last reply" in plan.prompts[1]
    assert any(line.startswith("query reply was not a JSON array")
               for line in said)
    assert "text 0" in complete.prompts[0]


def test_a_model_that_never_holds_the_shape_falls_back_to_plain_queries():
    asked = []
    plan = Scripted(["no", "still no", "no json at all"])
    complete = Complete()
    asker = local_agent.LocalAsker(
        plan, complete,
        searcher([{"url": "https://a.test/1", "title": "A"}], started=asked),
        reader({"https://a.test/1": "text"}),
        model="m", search_provider="stub")
    said = []
    asker.on_action = said.append
    task = ("# Quick look: what is known to go wrong with this one?\n\n"
            "    Acme Widget Pro W200\n\nSomeone is looking at this.")
    asker.ask(task)
    assert asked[:3] == ["Acme Widget Pro W200 problems",
                         "Acme Widget Pro W200 failures",
                         "Acme Widget Pro W200 owner reports"]
    assert any(line.startswith("fell back to plain queries") for line in said)


def test_the_second_round_searches_what_the_first_missed():
    asked = []

    def search(query, limit):
        asked.append(query)
        if "problems" in query:
            return [{"url": "https://a.test/only", "title": "one"}]
        return [{"url": "https://a.test/new", "title": "new"}]

    plan = Scripted(['["widget problems"]', '["widget teardown"]'])
    complete = Complete()
    asker = local_agent.LocalAsker(
        plan, complete, search,
        reader({"https://a.test/only": "the one readable page",
                "https://a.test/new": "the page round two found"}),
        model="m", search_provider="stub")
    said = []
    asker.on_action = said.append
    asker.ask("widget")
    # One readable page after round one, so round two ran, and its query
    # found a page round one's query never named.
    assert asked == ["widget problems", "widget teardown"]
    assert any(line.startswith("searching again") for line in said)
    prompt = complete.prompts[0]
    assert "the one readable page" in prompt
    assert "the page round two found" in prompt


def test_a_full_first_round_never_pays_for_a_second():
    asked = []

    def search(query, limit):
        asked.append(query)
        return [{"url": f"https://a.test/{n}", "title": str(n)}
                for n in range(3)][:limit]

    plan = Scripted(['["q1"]', '["should never be asked"]'])
    complete = Complete()
    asker = local_agent.LocalAsker(
        plan, complete, search,
        reader({f"https://a.test/{n}": f"page {n}" for n in range(3)}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("widget")
    assert asked == ["q1"]
    assert len(plan.prompts) == 1


def test_pages_are_sized_to_the_model_s_own_context():
    long_text = "battery drains fast on this device " * 120
    other_text = "unrelated shipping policy boilerplate " * 120
    plan = Plan('["q"]')
    complete = Complete()
    complete.context_chars = 5000
    asker = local_agent.LocalAsker(
        plan, complete,
        searcher([{"url": f"https://a.test/{i}", "title": str(i)}
                  for i in range(local_agent.MAX_PAGES)]),
        reader({f"https://a.test/{i}":
                long_text if i == 0 else other_text
                for i in range(local_agent.MAX_PAGES)}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    asker.ask("battery")
    # The task, source instructions, URL headings, and reply all need room.
    # Evidence must remain identical to what the answer prompt showed.
    assert len(asker.sources) == 2
    assert len(complete.prompts[0]) + local_agent.triage.REPLY_ROOM <= 5000
    shown = [asker.sources[url] for url, _ in
             sorted(asker.sources.items())]
    for text in shown:
        assert text in complete.prompts[0]


def test_triage_prefers_the_page_that_matches_the_task():
    pages = [("https://a.test/away", "unrelated words entirely"),
             ("https://a.test/battery", "battery life is short")]
    chosen = local_agent.triage.choose(
        pages, task="battery", queries=[], budget=3500 + len("battery"),
        at_most=local_agent.MAX_PAGES, page_cap=local_agent.PAGE_CHARS)
    assert [url for url, _ in chosen] == ["https://a.test/battery"]


def test_a_prose_answer_is_asked_again_for_the_json_shape():
    """The small model's prose answer: real risks, no JSON object, nothing a
    door can render. One bounded re-ask — the same repair the planner does
    for queries — and the answer that comes back shaped wins."""
    plan = Plan('["q"]')
    prose = "Here are the risks I found, in prose, with no JSON anywhere."
    fenced = '```json {"risks": []} ```'
    verdict = '{"unsupported": [], "note": "carried"}'
    complete = Scripted([prose, fenced, verdict])
    asker = local_agent.LocalAsker(
        plan, complete, searcher([{"url": "https://a.test/1", "title": "A"}]),
        reader({"https://a.test/1": "text"}),
        model="m", search_provider="stub")
    said = []
    asker.on_action = said.append
    got = asker.ask("widget problems")
    # The answer, its shape repair, the self-check: three calls, in order.
    assert got == fenced
    assert len(complete.prompts) == 3
    assert "no JSON object" in complete.prompts[1]
    assert "in prose" in complete.prompts[1]
    assert any("asking for the shape again" in line for line in said)


def test_a_prose_answer_twice_keeps_the_first_reply():
    plan = Plan('["q"]')
    prose = "prose risks, no JSON"
    complete = Scripted([prose, "still prose, still no JSON"])
    asker = local_agent.LocalAsker(
        plan, complete, searcher([{"url": "https://a.test/1", "title": "A"}]),
        reader({"https://a.test/1": "text"}),
        model="m", search_provider="stub")
    said = []
    asker.on_action = said.append
    got = asker.ask("widget problems")
    assert got == prose
    assert any("keeping the first" in line for line in said)


def test_a_bare_json_answer_never_pays_for_a_shape_repair():
    """Bare JSON is a less careful model, not a broken reply: the fence
    reader takes it, so the repair never runs."""
    plan = Plan('["q"]')
    bare = '{"risks": []}'
    verdict = '{"unsupported": [], "note": ""}'
    complete = Scripted([bare, verdict])
    asker = local_agent.LocalAsker(
        plan, complete, searcher([{"url": "https://a.test/1", "title": "A"}]),
        reader({"https://a.test/1": "text"}),
        model="m", search_provider="stub")
    asker.on_action = lambda line: None
    got = asker.ask("widget problems")
    assert got == bare
    assert len(complete.prompts) == 2


def test_the_self_check_runs_and_its_verdict_is_kept():
    plan = Plan('["q"]')
    answer = '```json {"risks": []} ```'
    verdict = ('{"unsupported": [{"title": "battery", "reason": '
               '"the page is about another variant"}], "note": "thin"}')
    complete = Scripted([answer, verdict])
    asker = local_agent.LocalAsker(
        plan, complete, searcher([{"url": "https://a.test/1", "title": "A"}]),
        reader({"https://a.test/1": "text"}),
        model="m", search_provider="stub")
    said = []
    asker.on_action = said.append
    got = asker.ask("widget problems")
    assert got == answer
    assert len(complete.prompts) == 2
    assert "You are checking an answer" in complete.prompts[1]
    assert any("reads its own answer" in line for line in said)
    assert asker.verification == {
        "unsupported": [{"title": "battery",
                          "reason": "the page is about another variant"}],
        "note": "thin"}
    assert "1 risk(s) not carried" in said[-1]


def test_a_broken_self_check_never_kills_the_answer():
    plan = Plan('["q"]')
    answer = '```json {"risks": []} ```'
    complete = Scripted([answer, RuntimeError("out of memory")])
    asker = local_agent.LocalAsker(
        plan, complete, searcher([{"url": "https://a.test/1", "title": "A"}]),
        reader({"https://a.test/1": "text"}),
        model="m", search_provider="stub")
    said = []
    asker.on_action = said.append
    got = asker.ask("widget problems")
    assert got == answer
    assert asker.verification["error"] == "out of memory"
    assert any("self-check could not run" in line for line in said)


def test_a_model_cut_off_before_it_writes_falls_back_to_plain_queries():
    """The reasoning-budget cutoff: the server answers, `finish_reason`
    "length", nothing written. The old script died at its first call; the
    plain queries take the search so the model still gets its run."""
    asked = []
    plan = Scripted([local_agent.plan.LocalInferenceError("cut off at 1024")])
    complete = Complete()
    asker = local_agent.LocalAsker(
        plan, complete,
        searcher([{"url": "https://a.test/1", "title": "A"}], started=asked),
        reader({"https://a.test/1": "text"}),
        model="m", search_provider="stub")
    said = []
    asker.on_action = said.append
    task = ("# Quick look: what is known to go wrong with this one?\n\n"
            "    Acme Widget Pro W200\n")
    asker.ask(task)
    assert asked[0] == "Acme Widget Pro W200 problems"
    assert any("falling back to plain queries" in line for line in said)
    assert "text" in complete.prompts[0]
