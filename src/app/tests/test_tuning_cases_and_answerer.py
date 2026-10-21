"""Cases from the reader's own chats (opt-in, local), and the answerer's wiring to Settings."""

import json
import socket
import time

import pytest

from app import prefs
from app.tests import tuning_fakes as fakes
from app.tuning import agents as agent_mod
from app.tuning import cases, cli, cost
from app.tuning.answer import ChatAnswerer
from app.tuning.scrub import scrub
from app.web import state, tasks


@pytest.fixture
def conn(tmp_path):
    connection = state.connect(tmp_path / "app.sqlite")
    yield connection
    connection.close()


def _thread(conn, title, *messages):
    thread = state.create_chat_thread(conn, title)
    for role, text in messages:
        state.add_chat_message(conn, thread["thread_id"], role=role, text=text)
    return thread["thread_id"]


# ── proposing cases ─────────────────────────────────────────────────────────

def test_naming_no_conversation_proposes_nothing(conn):
    _thread(conn, "boat", ("reader", "Is the Acme Widget MK2 any good for a small boat?"))
    assert cases.propose_from_chats(conn, []) == []


def test_only_the_named_conversation_is_read(conn):
    wanted = _thread(conn, "boat", ("reader", "Is the Acme Widget MK2 any good for a small boat?"))
    _thread(conn, "private", ("reader", "Something personal I did not opt in about my health"))
    found = cases.propose_from_chats(conn, [wanted])
    assert [one["question"] for one in found] == ["Is the Acme Widget MK2 any good for a small boat?"]
    assert found[0]["source"] == "chat" and found[0]["criteria"] == []


def test_a_later_question_is_a_follow_up_and_carries_its_history_only_when_asked_for(conn):
    thread = _thread(conn, "boat",
                     ("reader", "Is the Acme Widget MK2 any good for a small boat?"),
                     ("agent", "It is rated for marine use."),
                     ("reader", "And how long does its seal last in salt water?"))
    assert len(cases.propose_from_chats(conn, [thread])) == 1
    both = cases.propose_from_chats(conn, [thread], follow_ups=True)
    assert len(both) == 2 and both[0]["history"] == []
    assert [one["role"] for one in both[1]["history"]] == ["reader", "agent"]
    cases.validate(both)


def test_credentials_and_addresses_are_scrubbed_from_what_is_proposed(conn):
    thread = _thread(conn, "x", ("reader", "Use my key sk-live-9f8e7d6c5b4a39281706f5e4d3c2 and "
                                           "mail me@example.org about the Acme Widget MK2 seal"))
    question = cases.propose_from_chats(conn, [thread])[0]["question"]
    assert "sk-live" not in question and "me@example.org" not in question
    assert "Acme Widget MK2 seal" in question


def test_proposing_reads_locally_and_calls_no_agent_and_opens_no_connection(conn, monkeypatch):
    thread = _thread(conn, "boat", ("reader", "Is the Acme Widget MK2 any good for a small boat?"))

    def refuse(*_args, **_kwargs):
        raise AssertionError("proposing cases must not touch the network or an agent")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(agent_mod, "open_agent", refuse)
    monkeypatch.setattr(agent_mod, "roster", refuse)
    assert len(cases.propose_from_chats(conn, [thread])) == 1


def test_listing_threads_shows_titles_and_counts_and_not_what_was_said(conn):
    _thread(conn, "boat motor", ("reader", "A secret question about the Acme Widget MK2 seal"))
    listed = cases.saved_threads(conn)
    assert listed[0]["title"] == "boat motor" and listed[0]["questions"] == 1
    assert "secret question" not in json.dumps(listed)


def test_the_command_writes_a_file_the_reader_can_edit_and_run(conn, tmp_path, capsys):
    thread = _thread(conn, "boat", ("reader", "Is the Acme Widget MK2 any good for a small boat?"))
    out = tmp_path / "mine.json"
    code = cli.main(["propose", "--state", str(tmp_path / "app.sqlite"), "--thread", thread, "--out", str(out)])
    assert code == 0 and "Nothing was sent anywhere" in capsys.readouterr().out
    loaded = cases.load_file(out)
    assert cases.validate(loaded)[0]["question"].startswith("Is the Acme Widget")


def test_without_a_thread_the_command_lists_instead_of_reading(conn, tmp_path, capsys):
    _thread(conn, "boat", ("reader", "Is the Acme Widget MK2 any good for a small boat?"))
    assert cli.main(["propose", "--state", str(tmp_path / "app.sqlite")]) == 0
    assert "--thread" in capsys.readouterr().out


def test_a_case_set_is_fingerprinted_by_its_questions_and_rubrics_only():
    base = [{"id": "a", "question": "q one?", "criteria": []}]
    assert cases.fingerprint(base) == cases.fingerprint([{**base[0], "references": ["https://x.example"]}])
    assert cases.fingerprint(base) != cases.fingerprint([{**base[0], "question": "q two?"}])


@pytest.mark.parametrize("bad,message", [
    ([], "no cases"),
    ([{"id": "a", "question": ""}], "no question"),
    ([{"id": "a", "question": "x"}, {"id": "a", "question": "y"}], "duplicate id"),
    ([{"id": "a", "question": "x", "criteria": [{"id": "k"}]}], "needs its fact"),
])
def test_a_malformed_case_set_is_refused_with_what_is_wrong(bad, message):
    with pytest.raises(ValueError, match=message):
        cases.validate(bad)


def test_the_benchmark_corpus_loads_as_valid_cases():
    corpus = cases.bench_cases()
    assert len(cases.validate(corpus)) == 9 and {one["source"] for one in corpus} == {"bench"}


# ── the answerer is the reader's stack, in a scratch state ──────────────────

@pytest.fixture
def reader(tmp_path):
    path = tmp_path / "reader" / "app.sqlite"
    path.parent.mkdir()
    connection = state.connect(path)
    prefs.write(connection, {prefs.HARNESS: "codex", prefs.SEARCH: "tavily"})
    connection.close()
    return path


def _preference(agent=fakes.ANSWERER, search="tavily"):
    return agent_mod.Preference(agent, search)


def _fake_turn(monkeypatch, behave):
    seen: dict = {}

    def chat_ask(settings, params, progress):
        conn = state.connect(settings.app_state_path)
        try:
            seen["prefs"] = prefs.read(conn)
            seen["path"] = settings.app_state_path
        finally:
            conn.close()
        seen["params"] = params
        return behave(settings, params, progress)

    monkeypatch.setattr(tasks, "chat_ask", chat_ask)
    return seen


def test_the_scratch_state_carries_the_readers_settings_and_leaves_their_history_alone(reader, monkeypatch):
    seen = _fake_turn(monkeypatch, lambda s, p, progress: progress.partial(
        {"answer": "An answer [https://maker.example/a].", "sources": ["web_search", "https://maker.example/a"],
         "activity": [{"kind": "read", "state": "done", "url": "https://forum.example/t"}],
         "agent": {"id": "codex", "label": "Codex", "model": "model-a"}}))
    got = ChatAnswerer(reader, _preference()).answer({"id": "c1", "question": "Does it rust?"})
    assert seen["prefs"][prefs.SEARCH] == "tavily" and seen["prefs"][prefs.HARNESS] == "codex"
    assert seen["path"] != reader
    assert got.text.startswith("An answer") and got.agent["id"] == "codex"
    assert got.read_urls == ["https://maker.example/a", "https://forum.example/t"]
    conn = state.connect(reader)
    try:
        assert state.chat_threads(conn) == []                    # nothing landed in the reader's history
        assert prefs.read(conn)[prefs.HARNESS] == "codex"
    finally:
        conn.close()


def test_an_override_changes_the_scratch_state_only(reader, monkeypatch):
    seen = _fake_turn(monkeypatch, lambda s, p, progress: progress.partial({"answer": "ok"}))
    other = agent_mod.AgentRef("claude-code", "Claude Code", "harness")
    ChatAnswerer(reader, _preference(other, "exa"), override_agent=True, override_search=True).answer(
        {"id": "c1", "question": "Does it rust?"})
    assert seen["prefs"][prefs.HARNESS] == "claude-code" and seen["prefs"][prefs.SEARCH] == "exa"
    assert seen["params"]["harness"] == "claude-code"
    conn = state.connect(reader)
    try:
        assert prefs.read(conn)[prefs.HARNESS] == "codex"
    finally:
        conn.close()


def test_the_local_model_is_asked_through_the_local_backend(reader, monkeypatch):
    seen = _fake_turn(monkeypatch, lambda s, p, progress: progress.partial({"answer": "ok"}))
    ChatAnswerer(reader, _preference(fakes.LOCAL), override_agent=True).answer({"id": "c1", "question": "q?"})
    assert (seen["params"]["harness"], seen["params"]["backend"]) == ("local", "local")


def test_a_clarifying_question_is_the_answer_and_says_so(reader, monkeypatch):
    _fake_turn(monkeypatch, lambda s, p, progress: {"answer": "", "questions": [{"ask": "Which variant?"}],
                                                    "agent": {"id": "codex"}})
    got = ChatAnswerer(reader, _preference()).answer({"id": "c1", "question": "Can I soak them?"})
    assert got.text == "Which variant?" and got.asked_question is True


def test_a_follow_up_is_answered_with_the_conversation_before_it(reader, monkeypatch):
    seen_history = {}

    def behave(settings, params, progress):
        conn = state.connect(settings.app_state_path)
        try:
            seen_history["roles"] = [one["role"] for one in state.chat_history(
                conn, params["thread_id"], before=params["message_id"])]
        finally:
            conn.close()
        progress.partial({"answer": "ok"})

    _fake_turn(monkeypatch, behave)
    ChatAnswerer(reader, _preference()).answer({
        "id": "c1", "question": "And in salt water?",
        "history": [{"role": "reader", "text": "Is it good for a boat?"}, {"role": "agent", "text": "Yes."}]})
    assert seen_history["roles"] == ["reader", "agent"]


def test_a_failure_in_the_turn_is_an_error_on_the_answer_not_an_exception(reader, monkeypatch):
    def boom(*_):
        raise RuntimeError("the search service is down")

    _fake_turn(monkeypatch, boom)
    got = ChatAnswerer(reader, _preference()).answer({"id": "c1", "question": "q?"})
    assert got.error == "RuntimeError: the search service is down" and got.text == ""


def test_a_case_that_outlasts_its_ceiling_ends_as_a_timeout(reader, monkeypatch):
    def slow(settings, params, progress):
        time.sleep(0.05)
        progress.check()

    _fake_turn(monkeypatch, slow)
    got = ChatAnswerer(reader, _preference(), timeout=0.01).answer({"id": "c1", "question": "q?"})
    assert got.error.startswith("timeout:")


def test_the_turns_own_usage_is_kept_when_it_reports_one(reader, monkeypatch):
    def metered(settings, params, progress):
        from app.turnusage import TurnUsage

        TurnUsage(budget=0.5).record({"usd": 0.02, "tokens": 500})
        progress.partial({"answer": "ok"})

    _fake_turn(monkeypatch, metered)
    got = ChatAnswerer(reader, _preference()).answer({"id": "c1", "question": "q?"})
    assert (got.usd, got.tokens) == (0.02, 500)


# ── secrets, and the cost shown first ───────────────────────────────────────

@pytest.mark.parametrize("text,gone", [
    ("token=abcdef123456 and more", "abcdef123456"),
    ("Authorization: Bearer abcdefghijklmnop12345", "abcdefghijklmnop12345"),
    ("https://x.example/p?q=1&api_key=SECRETVALUE99&z=2", "SECRETVALUE99"),
    ("ghp_abcdefghijklmnopqrstuvwxyz0123", "ghp_abcdefghijklmnopqrstuvwxyz0123"),
])
def test_credential_shapes_are_removed(text, gone):
    assert gone not in scrub(text)


def test_ordinary_prose_and_product_urls_survive_scrubbing():
    text = "The Acme MK2 (https://maker.example/widget-mk2/specs) is rated for 8 bar."
    assert scrub(text) == text


def test_the_plan_prices_a_per_token_agent_from_the_price_list_and_never_invents_one():
    api = agent_mod.AgentRef("openai-compatible-api", "OpenAI-compatible", "api", "gpt-4o-mini")
    unknown = agent_mod.AgentRef("openai-compatible-api", "OpenAI-compatible", "api", "no-such-model")
    shape = cost.plan([fakes.CASE] * 2, fakes.ANSWERER, api, "tavily", reps=2)
    assert shape["attempts"] == 4
    assert shape["grader_cost"]["usd"] and shape["grader_cost"]["usd"] > 0
    assert shape["answerer_cost"]["usd"] is None and "plan" in shape["answerer_cost"]["basis"]
    assert cost.plan([fakes.CASE], fakes.ANSWERER, unknown, "x")["grader_cost"]["usd"] is None
    assert cost.plan([fakes.CASE], fakes.LOCAL, fakes.GRADER, "x")["answerer_cost"]["usd"] == 0.0
    assert "price not known" in cost.describe(cost.plan([fakes.CASE], fakes.ANSWERER, unknown, "x"))
