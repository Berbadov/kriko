"""Transport usage survives malformed answers and stays honest when incomplete."""

import pytest

from app.providers import anthropic_llm, llm
from app.providers.completion_asker import CompletionAsker
from app.providers.local_agent import LocalAsker
from app.providers.local_inference import OpenAICompatSocket


@pytest.mark.parametrize("adapter", [llm, anthropic_llm])
def test_output_ceiling_and_failed_answer_still_count_usage(monkeypatch, adapter):
    seen = []

    def transport(_url, body, _headers):
        seen.append(body)
        if adapter is llm:
            return {"usage": {"prompt_tokens": 17, "completion_tokens": 9},
                    "choices": [{"finish_reason": "length", "message": {"content": ""}}]}
        return {"usage": {"input_tokens": 17, "output_tokens": 9},
                "stop_reason": "max_tokens", "content": []}

    monkeypatch.setattr(adapter, "post_json", transport)
    complete = adapter.completer(api_key="fixture", model="fixture-model", max_tokens=9)
    assert complete("evidence") == ""
    assert seen[0]["max_tokens"] == 9
    assert complete.tokens_used == 26
    assert complete.usage_complete
    assert complete.last_finish_reason == "length"


@pytest.mark.parametrize("adapter", [llm, anthropic_llm])
def test_missing_usage_after_a_counted_call_is_not_reported_as_free(monkeypatch, adapter):
    first = ({"usage": {"prompt_tokens": 17, "completion_tokens": 9}}
             if adapter is llm else {"usage": {"input_tokens": 17, "output_tokens": 9}})
    replies = iter([first, {}])
    monkeypatch.setattr(adapter, "post_json", lambda *a: next(replies))
    complete = adapter.completer(api_key="fixture", model="fixture-model")
    complete("first")
    complete("second")
    assert complete.tokens_used == 26, "known usage is retained"
    assert not complete.usage_complete, "it is not the entire run's usage"
    assert CompletionAsker(complete).spent is None


def test_local_stage_missing_usage_does_not_borrow_the_previous_calls_count():
    socket = OpenAICompatSocket("http://127.0.0.1:1", "fixture-model")
    socket._count({"usage": {"prompt_tokens": 17, "completion_tokens": 9}})
    asker = LocalAsker(socket, socket, None, None, model="fixture-model", search_provider="fixture")
    asker._measured("answer", socket, lambda: socket._count({}))
    assert asker.tokens_used == 26
    assert not asker.usage_complete
    assert asker.metrics[0]["tokens_used"] is None


def test_boolean_usage_is_not_a_token_measurement():
    socket = OpenAICompatSocket("http://127.0.0.1:1", "fixture-model")
    socket._count({"usage": {"total_tokens": True}})
    assert socket.tokens_used is None
    assert not socket.usage_complete
