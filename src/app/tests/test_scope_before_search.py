"""What a subject is worth, decided before the first search is spent.

The reader's words: "the agent needs a thinking before going out on the
internet and searching: how complex this product is, how big the resource pool
must be". The dial said five retrievals to a keyboard and to a car alike; a
car's five went on its gearbox and its three findings were one system's.

The scope is a small model call that reads only the subject; these tests keep
the model out of it and pin what is done with its answer, and that a subject
that cannot be scoped still gets researched.
"""

import json

import pytest

from app import keys, quicklook
from app.providers import agentplan, apiagent, kriko_agent, mistral


def _scope_reply(complexity="complex", *names):
    names = names or ("engine", "gearbox", "brakes", "electrics", "suspension", "body")
    return json.dumps({"complexity": complexity, "aspects": [
        {"name": name, "query": f"Widget 2014 {name} problems"} for name in names]})


# ── reading the model's answer ───────────────────────────────────────────────

def test_a_fenced_reply_is_read_as_a_scope():
    scope = agentplan.parse_scope("Here you go:\n```json\n" + _scope_reply() + "\n```")
    assert scope.complexity == "complex"
    assert [one.name for one in scope.aspects][:2] == ["engine", "gearbox"]
    assert scope.aspects[0].query == "Widget 2014 engine problems"


@pytest.mark.parametrize("reply", [
    "", "no object here", "{broken", '{"aspects": []}', '{"aspects": "engine"}',
    '{"complexity": "complex"}', '{"aspects": [{"name": "", "query": "x"}, {"name": "y"}]}',
    '["engine"]', None,
])
def test_an_unreadable_reply_is_no_scope_not_an_error(reply):
    assert agentplan.parse_scope(reply) is None


def test_aspects_are_bounded_deduplicated_and_one_line():
    many = [{"name": f"part {n}", "query": f"Widget part {n}"} for n in range(30)]
    many.insert(1, {"name": "PART 0", "query": "a repeat in other case"})
    many.append({"name": "x\n`y`" + "z" * 200, "query": "q\nr " + "w" * 300})
    scope = agentplan.parse_scope(json.dumps({"complexity": "complex", "aspects": many}))
    assert len(scope.aspects) == agentplan.MAX_ASPECTS
    assert len({one.name.casefold() for one in scope.aspects}) == len(scope.aspects)

    odd = agentplan.parse_scope(json.dumps({"aspects": [
        {"name": "x\n`y`" + "z" * 200, "query": "q\nr " + "w" * 300}]}))
    name, query = odd.aspects[0].name, odd.aspects[0].query
    assert "\n" not in name + query and "`" not in name + query
    assert len(name) <= 40 and len(query) <= 100


@pytest.mark.parametrize(("count", "expected"), [(1, "simple"), (2, "simple"), (3, "moderate"),
                                                 (5, "moderate"), (6, "complex"), (8, "complex")])
def test_a_missing_or_unknown_complexity_is_read_from_how_many_aspects(count, expected):
    aspects = [{"name": f"a{n}", "query": f"Widget a{n}"} for n in range(count)]
    for given in ({}, {"complexity": "elaborate"}):
        scope = agentplan.parse_scope(json.dumps({**given, "aspects": aspects}))
        assert scope.complexity == expected


# ── what the scope is worth ──────────────────────────────────────────────────

def _scope(complexity, count):
    return agentplan.Scope(complexity, tuple(
        agentplan.Aspect(f"a{n}", f"Widget a{n}") for n in range(count)))


def test_a_complex_subject_gets_more_retrievals_than_a_simple_one_under_the_same_dial():
    dial = 5
    simple = agentplan.scoped_calls(_scope("simple", 2), dial)
    moderate = agentplan.scoped_calls(_scope("moderate", 4), dial)
    complex_ = agentplan.scoped_calls(_scope("complex", 7), dial)
    assert simple < dial < complex_
    assert simple <= moderate <= complex_


@pytest.mark.parametrize("dial", range(0, 20))
@pytest.mark.parametrize("complexity", agentplan.COMPLEXITIES)
@pytest.mark.parametrize("count", [1, 3, 8])
def test_the_budget_never_leaves_its_bounds(dial, complexity, count):
    calls = agentplan.scoped_calls(_scope(complexity, count), dial)
    assert agentplan.MIN_SCOPED_CALLS <= calls <= agentplan.MAX_SCOPED_CALLS
    # One per aspect and one for what they miss, but never under the floor.
    assert calls <= max(agentplan.MIN_SCOPED_CALLS, count + 1)
    assert calls <= max(agentplan.MIN_SCOPED_CALLS, dial) + agentplan.EXTRA_CALLS[complexity]


def test_a_findings_cap_grows_with_complexity_and_defaults_without_a_scope():
    caps = [agentplan.risk_cap(_scope(name, 3)) for name in agentplan.COMPLEXITIES]
    assert caps == sorted(caps) and len(set(caps)) == 3
    assert agentplan.risk_cap(None) == agentplan.DEFAULT_RISK_CAP == quicklook.MAX_RISKS


def test_the_checklist_carries_every_aspect_and_owns_up_to_what_it_cannot_reach():
    scope = _scope("complex", 6)
    text = agentplan.scope_checklist(scope, 8)
    assert all(f"Widget a{n}" in text for n in range(6))
    assert "You cannot reach all" not in text
    short = agentplan.scope_checklist(scope, 4)
    assert "do the first 3" in short
    assert all(f"Widget a{n}" in short for n in range(6))     # still all listed


def test_the_record_says_which_aspects_have_a_finding_and_which_do_not():
    scope = _scope("complex", 4)
    risks = [{"aspect": "a0"}, {"aspect": "A0"}, {"aspect": "a2"}, {"aspect": "nothing"}, {}]
    record = agentplan.scope_record(scope, risks, calls=7)
    assert record["calls"] == 7 and record["complexity"] == "complex"
    assert {one["name"]: one["findings"] for one in record["aspects"]} == {
        "a0": 2, "a1": 0, "a2": 1, "a3": 0}
    assert record["untagged"] == 2
    line = agentplan.scope_line(record)
    assert "2 of 4 aspects" in line and "a0 2" in line and "none for: a1, a3" in line
    assert agentplan.scope_record(None, risks) == {}
    assert agentplan.scope_line({}) == ""


# ── the quick look, with and without one ─────────────────────────────────────

def test_a_scoped_brief_carries_a_cap_and_an_aspect_tag_and_an_unscoped_one_is_unchanged():
    scoped = quicklook.brief("Widget", scope=_scope("complex", 6))
    assert f"At most {agentplan.RISK_CAPS['complex']} risks" in scoped
    assert '"aspect"' in scoped
    assert "no target number" not in scoped.lower()

    plain = quicklook.brief("Widget")
    assert f"At most {quicklook.MAX_RISKS} risks" in plain
    assert '"aspect"' not in plain
    assert "no target number of lines" in plain


def _reply(count, severities=()):
    risks = [{"title": f"fault {n}", "why": "w", "check": "", "url": "https://a.example/p",
              "quote": f"quote {n}", "aspect": f"a{n % 3}",
              "severity": severities[n] if n < len(severities) else "medium"}
             for n in range(count)]
    return "```json\n" + json.dumps({"risks": risks, "specs": []}) + "\n```"


SOURCES = {"https://a.example/p": " ".join(f"quote {n}" for n in range(30))}


def test_parse_keeps_the_cap_it_is_given_and_the_aspect_tag():
    found = quicklook.parse(_reply(9), SOURCES, max_risks=10)
    assert len(found["risks"]) == 9
    assert {one["aspect"] for one in found["risks"]} == {"a0", "a1", "a2"}
    assert len(quicklook.parse(_reply(9), SOURCES)["risks"]) == quicklook.MAX_RISKS


def test_past_the_cap_the_most_serious_findings_stay_not_the_first_written():
    severities = ["low", "low", "low", "medium", "medium", "medium", "high", "high"]
    found = quicklook.parse(_reply(8, severities), SOURCES, max_risks=4)
    assert [one["severity"] for one in found["risks"]] == ["high", "high", "medium", "medium"]
    # Equal severities keep the agent's own order.
    assert [one["title"] for one in found["risks"]] == [
        "fault 6", "fault 7", "fault 3", "fault 4"]


# ── a finding is not lost to a mistyped address ──────────────────────────────

LONG_QUOTE = "the crankcase breather clogs and the engine starts burning oil"
PAGES = {
    "https://forum.example/thread/42?page=2": f"Owners say {LONG_QUOTE} after 60,000 km.",
    "https://other.example/review": "A different page that says nothing of the kind.",
}


def _one(url, quote, **extra):
    risk = {"title": "Oil burning", "why": "w", "check": "", "url": url, "quote": quote,
            "severity": "high", **extra}
    return "```json\n" + json.dumps({"risks": [risk], "specs": []}) + "\n```"


def test_a_finding_citing_an_address_the_search_never_returned_is_kept_on_the_page_that_has_it():
    """Every finding the Golf and keyboard runs dropped had this one cause."""
    found = quicklook.parse(_one("https://forum.example/thread/42", LONG_QUOTE), PAGES)
    assert found["dropped"] == 0
    (risk,) = found["risks"]
    assert risk["sources"][0]["url"] == "https://forum.example/thread/42?page=2"
    assert risk["sources"][0]["domain"] == "forum.example"
    assert risk["sources"][0].get("grounded") is True
    assert risk["sources"][0]["quote"] == LONG_QUOTE


def test_a_quote_no_page_carries_is_still_dropped():
    found = quicklook.parse(_one("https://forum.example/thread/42", "words nobody ever wrote"), PAGES)
    assert found["risks"] == [] and found["dropped"] == 1


def test_a_short_quote_is_not_hunted_across_pages():
    found = quicklook.parse(_one("https://nowhere.example/x", "burning oil"), PAGES)
    assert found["risks"] == [] and found["dropped"] == 1


def test_a_known_address_whose_page_lacks_the_quote_is_not_moved_to_another_page():
    wrong = _one("https://other.example/review", LONG_QUOTE)
    found = quicklook.parse(wrong, PAGES)
    assert found["risks"] == [] and found["dropped"] == 1


def test_the_page_nearest_the_cited_address_wins_when_two_carry_the_quote():
    pages = {"https://a.example/unrelated": f"x {LONG_QUOTE}",
             "https://forum.example/thread/42?page=2": f"y {LONG_QUOTE}"}
    found = quicklook.parse(_one("https://forum.example/thread/42", LONG_QUOTE), pages)
    assert found["risks"][0]["sources"][0]["url"] == "https://forum.example/thread/42?page=2"


def test_a_specification_with_a_mistyped_address_is_kept_the_same_way():
    reply = "```json\n" + json.dumps({"risks": [], "specs": [{
        "name": "Fuel", "value": "petrol", "url": "https://nowhere.example/spec",
        "quote": LONG_QUOTE}]}) + "\n```"
    found = quicklook.parse(reply, PAGES)
    assert [one["name"] for one in found["specs"]] == ["Fuel"]
    assert found["specs"][0]["url"] == "https://forum.example/thread/42?page=2"


def test_a_finding_tagged_with_its_search_query_still_counts_for_its_aspect():
    scope = _scope("moderate", 3)
    record = agentplan.scope_record(scope, [{"aspect": "Widget a1"}, {"aspect": "widget a2"}])
    assert {one["name"]: one["findings"] for one in record["aspects"]} == {
        "a0": 0, "a1": 1, "a2": 1}
    assert record["untagged"] == 0


def test_a_tag_that_carries_the_aspect_name_and_the_query_beside_it_still_counts():
    # What a live run wrote: "<aspect>: <the query it searched>".
    scope = agentplan.Scope("moderate", (
        agentplan.Aspect("Backlight failures", "G413 backlight not working"),
        agentplan.Aspect("Keycap wear", "G413 keycap wear")))
    record = agentplan.scope_record(scope, [
        {"aspect": "Backlight failures: G413 backlight not working"},
        {"aspect": "Keycap wear - shiny keys"},
        {"aspect": "Build quality"}])
    assert {one["name"]: one["findings"] for one in record["aspects"]} == {
        "Backlight failures": 1, "Keycap wear": 1}
    assert record["untagged"] == 1


def test_an_aspect_name_that_only_starts_another_word_is_not_a_match():
    scope = agentplan.Scope("moderate", (
        agentplan.Aspect("Key", "keys"), agentplan.Aspect("Keycap wear", "keycaps")))
    record = agentplan.scope_record(scope, [{"aspect": "Keycap wear: keycaps"}])
    assert {one["name"]: one["findings"] for one in record["aspects"]} == {
        "Key": 0, "Keycap wear": 1}


# ── scoping, as the researcher does it ───────────────────────────────────────

class _Researcher(apiagent.ApiAgentResearcher):
    """The built-in stack with its model replaced: each `_run` answers from a script."""

    def __init__(self, scope_reply, research_reply):
        super().__init__(apiagent.KRIKO_AGENT, converse=lambda *a, **k: mistral.Reply())
        self.prompts: list[tuple[str, bool]] = []
        self.echoed: list[str] = []
        self._scope_reply, self._research_reply = scope_reply, research_reply
        self._echo = self.echoed.append

    def _run(self, prompt, on_line=None, *, search=True):
        self.prompts.append((prompt, search))
        if not search:
            if isinstance(self._scope_reply, Exception):
                raise self._scope_reply
            return self._scope_reply
        return self._research_reply


def test_the_quick_look_scopes_first_with_no_tools_then_researches_under_the_scope():
    researcher = _Researcher(_scope_reply(), _reply(3))
    researcher.on_text = lambda _t: None
    live = researcher.on_text
    researcher.ask_quick("2014 Widget 1.2 Comfortline")

    (first, first_tools), (second, second_tools) = researcher.prompts
    assert first_tools is False and "2014 Widget 1.2 Comfortline" in first
    assert second_tools is True
    assert f"At most {agentplan.RISK_CAPS['complex']} risks" in second
    assert researcher.scope.complexity == "complex"
    assert researcher.on_text is live            # muted for the scope call, then given back


@pytest.mark.parametrize("scope_reply", ["no json at all", RuntimeError("provider down")])
def test_a_subject_that_cannot_be_scoped_is_still_researched_on_the_dial(scope_reply):
    researcher = _Researcher(scope_reply, _reply(3))
    answer = researcher.ask_quick("2014 Widget 1.2 Comfortline")

    assert answer == _reply(3)
    assert researcher.scope is None
    assert f"At most {quicklook.MAX_RISKS} risks" in researcher.prompts[-1][0]
    assert any("could not scope" in line for line in researcher.echoed)


def test_a_cancel_during_the_scope_call_still_ends_the_job():
    class Cancelled(Exception):
        pass

    researcher = _Researcher(_scope_reply(), _reply(3))
    flag = {"on": False}

    def check():
        if flag["on"]:
            raise Cancelled

    researcher.check_cancelled = check
    original = researcher._run

    def run(prompt, on_line=None, *, search=True):
        flag["on"] = True                      # the reader presses Stop mid-call
        return original(prompt, on_line, search=search)

    researcher._run = run
    with pytest.raises(Cancelled):
        researcher.ask_quick("2014 Widget 1.2 Comfortline")
    assert all(search is False for _p, search in researcher.prompts)    # no research followed


def test_a_question_about_failures_is_scoped_once_and_other_questions_are_not():
    researcher = _Researcher(_scope_reply(), "answer")
    researcher.question = "Any known problems or recall notices for the Widget X100?"
    researcher.ask("brief", allow_tools=True)
    researcher.ask("brief again", allow_tools=True)
    assert [search for _p, search in researcher.prompts].count(False) == 1
    assert researcher.scope is not None

    plain = _Researcher(_scope_reply(), "answer")
    plain.question = "Is the Widget X100 worth buying?"
    plain.ask("brief", allow_tools=True)
    assert all(search for _p, search in plain.prompts)           # no scope call
    assert plain.scope is None

    classify = _Researcher(_scope_reply(), "answer")
    classify.question = "Any known problems with the Widget X100?"
    classify.ask("classify this", allow_tools=False)
    assert classify.scope is None and len(classify.prompts) == 1  # a tool-less ask never scopes


def test_only_the_built_in_stack_scopes():
    other = apiagent.ApiAgentResearcher(
        apiagent.KRIKO_AGENT, converse=lambda *a, **k: mistral.Reply())
    other.agent = type("Other", (), {"id": "someone-else", "label": "Other"})()
    assert other.scope_for("2014 Widget") is None


# ── the turn that follows ────────────────────────────────────────────────────

def _stop_stream(monkeypatch, sent):
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")

    def stream(_url, payload, _headers, _timeout, _on_event, **_kwargs):
        sent.append(json.loads(json.dumps(payload)))
        return 0, "stop here"

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)


def test_a_scoped_turn_is_sized_to_its_subject_and_told_what_to_cover(monkeypatch):
    sent: list[dict] = []
    _stop_stream(monkeypatch, sent)
    steps: list[str] = []
    scope = agentplan.parse_scope(_scope_reply())
    kriko_agent.converse("brief", thoroughness=50, scope=scope, on_step=steps.append)

    assert "Kriko Agent: research budget 7 retrieval(s), 120 s" in steps   # 6 aspects + 1
    assert any(line.startswith("scope: complex, 6 aspect(s)") for line in steps)
    system = sent[0]["messages"][0]["content"]
    assert all(f"Widget 2014 {name} problems" in system
               for name in ("engine", "gearbox", "brakes", "electrics", "suspension", "body"))

    unscoped: list[str] = []
    kriko_agent.converse("brief", thoroughness=50, on_step=unscoped.append)
    assert "Kriko Agent: research budget 5 retrieval(s), 120 s" in unscoped
    assert not any(line.startswith("scope:") for line in unscoped)


def test_a_simple_subject_is_researched_with_less_than_the_dial_gives(monkeypatch):
    _stop_stream(monkeypatch, [])
    steps: list[str] = []
    scope = agentplan.parse_scope(_scope_reply("simple", "keys", "cable"))
    kriko_agent.converse("brief", thoroughness=100, scope=scope, on_step=steps.append)
    assert "Kriko Agent: research budget 3 retrieval(s), 120 s" in steps


def test_the_readers_money_cap_still_holds_a_scoped_turn(monkeypatch):
    _stop_stream(monkeypatch, [])
    steps: list[str] = []
    scope = agentplan.parse_scope(_scope_reply())
    kriko_agent.converse("brief", thoroughness=100, scope=scope, max_tool_calls=2,
                         on_step=steps.append)
    assert "Kriko Agent: research budget 2 retrieval(s), 120 s" in steps
