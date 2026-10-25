"""App actions: what Kriko Agent may change, and what it may only propose."""

import json

import pytest

from app import agentactions, buyer, keys
from app.providers import apiagent, kriko_agent, mistral
from app.web import state


@pytest.fixture()
def app_db(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        yield conn, tmp_path / "app.sqlite"
    finally:
        conn.close()


def _tool_call(name, arguments, *, index=0, call_id=None):
    return {
        "index": index,
        "id": call_id or f"call-{index}",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def test_remember_saves_one_profile_row_and_deduplicates(app_db):
    _conn, path = app_db
    first = agentactions.execute("remember", {"fact": "I need it quiet", "list": "must"},
                                 app_state_path=path)
    assert first["status"] == "done"
    assert first["action"]["kind"] == "remember"
    assert first["action"]["status"] == "done"

    again = agentactions.execute("remember", {"fact": "I need it quiet", "list": "must"},
                                 app_state_path=path)
    assert again["status"] == "done"
    assert again["action"]["title"] == "Already known"

    conn = state.connect(path)
    try:
        profile = buyer.read(conn)
    finally:
        conn.close()
    assert profile["must"] == ["I need it quiet"]


def test_remember_rejects_an_unknown_list_without_writing(app_db):
    _conn, path = app_db
    result = agentactions.execute("remember", {"fact": "x", "list": "wishlist"},
                                  app_state_path=path)
    assert result["status"] == "failed"
    assert "no list" in result["note"]


def test_open_names_a_real_screen_only():
    opened = agentactions.execute("open", {"screen": "catalogs"},
                                  app_state_path="unused")
    assert opened["status"] == "proposed"
    assert opened["action"]["status"] == "proposed"
    assert agentactions.execute("open", {"screen": "not-a-screen"},
                                app_state_path="unused")["status"] == "failed"


def test_the_action_vocabulary_is_closed():
    assert agentactions.tool_names() == {"remember", "open", "start_quick_look"}
    assert agentactions.execute("delete_everything", {}, app_state_path="unused")["status"] == "failed"


def test_a_quick_look_is_a_proposal_with_a_public_listing_only():
    proposed = agentactions.start_quick_look(
        product="Bosch GBH 2-26", page_url="https://shop.example/drill?ref=1#top")
    assert proposed["status"] == "proposed"
    assert proposed["action"]["params"] == {
        "product": "Bosch GBH 2-26",
        "page_url": "https://shop.example/drill?ref=1",
    }

    refused = agentactions.start_quick_look(
        product="Bosch GBH 2-26", page_url="javascript:alert(1)")
    assert refused["status"] == "failed"
    assert "public http" in refused["note"]


def test_the_action_endpoint_starts_only_a_proposed_quick_look():
    from fastapi import HTTPException

    from app.web.routers import agent_actions

    class Runner:
        def __init__(self):
            self.started = []

        def submit(self, kind, params, **kwargs):
            self.started.append((kind, params))
            return "job-1"

    runner = Runner()
    started = agent_actions.run_agent_action(
        agent_actions.AgentActionRequest(
            name="start_quick_look", arguments={"product": "Bosch GBH 2-26"}),
        runner=runner,
    )
    assert started["kind"] == "quick_look"
    assert runner.started[0][0] == "quick_look"
    assert runner.started[0][1]["product"] == "Bosch GBH 2-26"

    with pytest.raises(HTTPException) as refused:
        agent_actions.run_agent_action(
            agent_actions.AgentActionRequest(name="remember", arguments={"fact": "x"}),
            runner=runner,
        )
    assert refused.value.status_code == 400


def test_the_bounded_arguments_keep_remember_fields():
    message = {"role": "assistant", "content": None, "tool_calls": [
        _tool_call("remember", {"fact": "never a Samsung", "list": "avoid"}),
        _tool_call("open", {"screen": "history", "item": "last week"}, index=1),
    ]}
    bounded = kriko_agent._bound_tool_calls(message)
    remembered = json.loads(bounded["tool_calls"][0]["function"]["arguments"])
    opened = json.loads(bounded["tool_calls"][1]["function"]["arguments"])
    assert remembered == {"fact": "never a Samsung", "list": "avoid"}
    assert opened == {"screen": "history", "item": "last week"}


def test_a_remember_call_is_an_action_not_a_billed_search(monkeypatch, app_db):
    _conn, path = app_db
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")
    turn = 0

    def stream(_url, payload, _headers, _timeout, on_event, **_kwargs):
        nonlocal turn
        turn += 1
        assert any(tool["function"]["name"] == "remember" for tool in payload["tools"])
        if turn == 1:
            on_event({"choices": [{
                "delta": {"tool_calls": [_tool_call(
                    "remember", {"fact": "I need it quiet", "list": "must"})]},
                "finish_reason": "tool_calls",
            }]})
            on_event({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
        else:
            # The tool result is in the transcript the model reads.
            assert any("Saved to Must have" in str(row.get("content") or "")
                       for row in payload["messages"] if row.get("role") == "tool")
            on_event({"choices": [{
                "delta": {"content": "Saved: you need it quiet."}, "finish_reason": "stop",
            }]})
            on_event({"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 30}})
        return 1, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    reply = kriko_agent.converse(
        "Remember that I need it quiet",
        app_action=lambda name, args: agentactions.execute(name, args, app_state_path=path),
    )

    assert reply.error == ""
    assert reply.text == "Saved: you need it quiet."
    assert reply.retrieval_requests == 0
    assert reply.billed_tool_calls == 0
    assert [action["kind"] for action in reply.actions] == ["remember"]
    assert reply.actions[0]["status"] == "done"


def test_an_open_action_is_proposed_rather_than_claimed(monkeypatch):
    monkeypatch.setattr(keys, "require", lambda provider, **_kw: f"fixture-{provider}")
    turn = 0

    def stream(_url, _payload, _headers, _timeout, on_event, **_kwargs):
        nonlocal turn
        turn += 1
        if turn == 1:
            on_event({"choices": [{
                "delta": {"tool_calls": [_tool_call("open", {"screen": "history"})]},
                "finish_reason": "tool_calls",
            }]})
        else:
            on_event({"choices": [{
                "delta": {"content": "History is one press away."},
                "finish_reason": "stop",
            }]})
        on_event({"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 10}})
        return 1, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    reply = kriko_agent.converse(
        "Show me my history",
        app_action=lambda name, args: agentactions.execute(name, args, app_state_path="unused"),
    )
    assert reply.error == ""
    assert reply.actions[0]["kind"] == "open"
    assert reply.actions[0]["status"] == "proposed"
    assert reply.actions[0]["params"]["screen"] == "history"


def test_the_api_researcher_offers_app_actions_when_it_has_app_state(tmp_path):
    researcher = apiagent.ApiAgentResearcher(
        apiagent.KRIKO_AGENT, app_state_path=tmp_path / "app.sqlite",
        converse=lambda *_a, **_k: mistral.Reply(),
    )
    assert researcher._app_action is not None
    result = researcher._app_action("remember", {"fact": "quiet", "list": "prefer"})
    assert result["status"] == "done"
    # The adapter records the action from the reply it accounted, not from the
    # executor's return value, so a screen cannot show an action twice.
    researcher._account(mistral.Reply(actions=[result["action"]]))
    assert researcher.agent_actions == [result["action"]]


def test_a_saved_message_keeps_its_actions(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        thread = state.create_chat_thread(conn, "one")
        action = agentactions.execute(
            "remember", {"fact": "quiet", "list": "prefer"},
            app_state_path=tmp_path / "app.sqlite")["action"]
        message = state.add_chat_message(
            conn, thread["thread_id"], role="agent", text="Saved.",
            actions=[action])
    finally:
        conn.close()
    assert message["actions"][0]["kind"] == "remember"
    assert message["actions"][0]["detail"] == "quiet"
