"""A small model that thinks first still answers, and what it quotes is readable.

A reader's friend ran Qwen 3.5 0.8B through Ollama: the model spent the whole
reply budget on its reasoning, `content` came back empty, and the run failed.
Asked not to think it answers the same prompt in under a second.
"""

import io
import json
import urllib.error
import pytest

from app.providers import pagereader
from app.providers import local_inference
from app.providers.local_inference import OpenAICompatSocket


def _socket(**kwargs):
    sent = []
    one = OpenAICompatSocket("http://127.0.0.1:11434", "qwen3.5:0.8b", **kwargs)

    def post(body):
        sent.append(dict(body))
        return {"choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}], "usage": {}}

    one._post = post
    return one, sent


def test_thinking_is_off_unless_the_reader_chose_an_effort():
    one, sent = _socket()
    one.complete("hi")
    assert sent[0]["reasoning_effort"] == "none"


def test_a_chosen_effort_wins():
    one, sent = _socket(reasoning_effort="high")
    one.complete("hi")
    assert sent[0]["reasoning_effort"] == "high"


def test_a_reasoning_effort_refusal_keeps_the_evidence_schema():
    one, sent = _socket(reasoning_effort="low", response_json_schema={"type": "array"})

    def post(body):
        sent.append(dict(body))
        if "reasoning_effort" in body:
            refusal = json.dumps({"error": {"message": "reasoning_effort is not supported"}})
            raise urllib.error.HTTPError(
                one.base_url + "/v1/chat/completions", 400, "Bad Request", {},
                io.BytesIO(refusal.encode()))
        return {"choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
                "usage": {}}

    one._post = post
    assert one("hi") == "[]"
    assert "reasoning_effort" in sent[0]
    assert sent[1]["response_format"] == {
        "type": "json_schema", "json_schema": {"name": "findings", "schema": {"type": "array"}}}
    assert "reasoning_effort" not in sent[1]
    assert one.structured_output == {"mode": "json_schema", "reason": ""}
    assert one("again") == "[]"
    assert "reasoning_effort" not in sent[2]


def test_json_object_fallback_is_reported_and_reused():
    one, sent = _socket(response_json_schema={"type": "array"})

    def post(body):
        sent.append(dict(body))
        if body.get("response_format", {}).get("type") == "json_schema":
            refusal = json.dumps({"error": {"message": "response_format.type only accepts json_object"}})
            raise urllib.error.HTTPError(
                one.base_url + "/v1/chat/completions", 500, "Internal Server Error", {},
                io.BytesIO(refusal.encode()))
        return {"choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
                "usage": {}}

    one._post = post
    assert one.json("first", {"type": "array"}) == "[]"
    assert one.structured_output == {"mode": "json_object", "reason": "json_schema_refused"}
    assert one.json("second", {"type": "object"}) == "[]"
    assert len(sent) == 3
    assert sent[1]["response_format"] == {"type": "json_object", "schema": {"type": "array"}}
    assert sent[2]["response_format"] == {"type": "json_object", "schema": {"type": "object"}}


def test_ambiguous_bad_request_keeps_reasoning_effort_when_schema_was_the_problem():
    one, sent = _socket(response_json_schema={"type": "array"})

    def post(body):
        sent.append(dict(body))
        if body.get("response_format", {}).get("type") == "json_schema":
            refusal = json.dumps({"error": {"message": "unknown field"}})
            raise urllib.error.HTTPError(
                one.base_url + "/v1/chat/completions", 400, "Bad Request", {},
                io.BytesIO(refusal.encode()))
        return {"choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
                "usage": {}}

    one._post = post
    assert one.json("first", {"type": "array"}) == "[]"
    assert one.structured_output == {"mode": "json_object", "reason": "json_schema_refused"}
    assert one.json("second", {"type": "object"}) == "[]"
    assert "reasoning_effort" in sent[-1]


def test_when_neither_schema_spelling_works_the_socket_reports_degradation():
    one, sent = _socket(response_json_schema={"type": "array"})

    def post(body):
        sent.append(dict(body))
        if "response_format" in body:
            refusal = json.dumps({"error": {"message": "response_format is not supported"}})
            raise urllib.error.HTTPError(
                one.base_url + "/v1/chat/completions", 400, "Bad Request", {},
                io.BytesIO(refusal.encode()))
        return {"choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
                "usage": {}}

    one._post = post
    assert one.json("first", {"type": "array"}) == "[]"
    assert one.structured_output == {
        "mode": "unconstrained", "reason": "response_format_refused"}
    assert one.json("second", {"type": "object"}) == "[]"
    assert "response_format" not in sent[-1]


def test_native_ollama_maps_the_json_object_compatibility_spelling():
    one = OpenAICompatSocket("http://127.0.0.1:11434", "gemma4:e2b",
                             runtime_options={"num_ctx": 4096})
    body = {"messages": [{"role": "user", "content": "prompt"}],
            "temperature": 0, "response_format": {
                "type": "json_object", "schema": {"type": "array"}}}

    assert one._native(body, stream=False)["format"] == {"type": "array"}


def test_structured_prompt_budget_uses_runtime_context_and_utf8_bytes():
    one, sent = _socket(runtime_options={"num_ctx": 4096})
    one.max_tokens = 768
    one.json("é" * 2000, {"type": "array"})
    assert sent and one.prompt_bytes_allowed() == (4096 - 768 - 128 - 128) * 2
    with pytest.raises(local_inference.LocalInferenceError, match="context budget"):
        one.json("界" * 3000, {"type": "array"})


def test_utf8_decoded_as_windows_1252_is_repaired_line_by_line():
    broken = "triggerâ€”it runs\ncafÃ© au lait"
    assert pagereader.unmangle(broken) == "trigger—it runs\ncafé au lait"


def test_honest_text_is_left_alone():
    honest = "café — and a real Ã in a name\nsecond line"
    assert pagereader.unmangle(honest) == honest


def test_one_bad_line_does_not_cost_the_good_ones():
    text = "fine é\nÃA stays\ntriggerâ€”it"
    got = pagereader.unmangle(text).splitlines()
    assert got == ["fine é", "ÃA stays", "trigger—it"]
