"""Resident workers for Claude Code and ACP agents: reuse, isolation, failure.

The servers below are stand-ins that remember one thing per conversation, so a
test can ask whether the second request could see the first. The Claude one
mirrors the behaviour checked against the real CLI: `/clear` answers with
`conversation_reset`, a fresh `system/init` and an empty `result` carrying a new
session id.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app import agentresources
from app.providers.codex_transport import DeliveryUncertain, TransportUnavailable, TurnCancelled
from app.providers.resident import (
    ResidentError,
    ResidentProfile,
    ResidentRequest,
    ResidentTransport,
)

FAKE_CLAUDE = r'''import json, os, sys, time, uuid
mode = os.environ.get("FAKE_MODE", "ok")
log = os.environ.get("FAKE_LOG")
session = str(uuid.uuid4())
memory = None
def send(value):
    sys.stdout.write(json.dumps(value) + "\n"); sys.stdout.flush()
def record(value):
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(value) + "\n")
def result(text, **extra):
    send({"type": "result", "subtype": "success", "is_error": False, "result": text,
          "session_id": session, "uuid": str(uuid.uuid4()),
          "usage": {"input_tokens": 10, "output_tokens": 2}, "total_cost_usd": 0.01, **extra})
for line in sys.stdin:
    msg = json.loads(line)
    record(msg)
    if msg.get("type") == "control_request":
        if msg["request"]["subtype"] == "interrupt" and mode == "hang_then_stop":
            result("", is_error=True, subtype="error_during_execution")
        continue
    text = msg["message"]["content"][0]["text"]
    if text == "/clear":
        memory = None
        session = str(uuid.uuid4())
        send({"type": "conversation_reset"})
        send({"type": "system", "subtype": "init", "session_id": session})
        result("")
        continue
    send({"type": "system", "subtype": "init", "session_id": session, "model": "fake"})
    send({"type": "rate_limit_event"})
    if mode == "gate":
        # Hold the answer until the test opens the gate: lets a test count
        # how many workers are alive while none of them has finished.
        while not os.path.exists(os.environ["FAKE_GATE"]):
            time.sleep(0.02)
    if mode in ("hang", "hang_then_stop"):
        continue
    if mode == "crash":
        os._exit(0)
    if mode == "long_line":
        send({"type": "user", "pad": "x" * 200000})
    if text.startswith("remember "):
        memory = text.split(" ", 1)[1]
        answer = "OK"
    elif text.startswith("recall"):
        answer = memory or "NONE"
    else:
        answer = "answer"
    send({"type": "stream_event", "session_id": session, "event": {"type": "content_block_delta",
          "delta": {"type": "text_delta", "text": answer}}})
    send({"type": "assistant", "session_id": session, "message": {"content": [{"type": "text", "text": answer}]}})
    if mode == "ask_permission":
        send({"type": "control_request", "request_id": "perm-1", "request": {"subtype": "can_use_tool"}})
    result(answer, **({"is_error": True, "subtype": "error_max_turns"} if mode == "max_turns" else {}))
'''

FAKE_ACP = r'''import json, os, sys, time, uuid
mode = os.environ.get("FAKE_MODE", "ok")
log = os.environ.get("FAKE_LOG")
memory = {}
count = 0
pending = None
def send(value):
    sys.stdout.write(json.dumps(value) + "\n"); sys.stdout.flush()
def record(value):
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(value) + "\n")
def update(session, **body):
    send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": session, "update": body}})
for line in sys.stdin:
    msg = json.loads(line)
    record(msg)
    method = msg.get("method")
    if method is None:
        continue
    if method == "initialize":
        if mode == "bad_init":
            send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": "no"}})
        else:
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": 1,
                  "agentCapabilities": {"sessionCapabilities": {"close": {}}}}})
    elif method == "session/new":
        count += 1
        sid = f"s-{os.getpid()}-{count}"
        memory[sid] = None
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"sessionId": sid}})
    elif method == "session/prompt":
        sid = msg["params"]["sessionId"]
        text = msg["params"]["prompt"][0]["text"]
        pending = (msg["id"], sid)
        if mode == "hang":
            update(sid, sessionUpdate="agent_thought_chunk", content={"type": "text", "text": "thinking"})
            continue
        if mode == "permission":
            send({"jsonrpc": "2.0", "id": "perm-1", "method": "session/request_permission",
                  "params": {"sessionId": sid, "toolCall": {"toolCallId": "t1"}, "options": [
                      {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
                      {"optionId": "deny", "name": "Reject", "kind": "reject_once"}]}})
            record(json.loads(sys.stdin.readline()))
        if text.startswith("remember "):
            memory[sid] = text.split(" ", 1)[1]; answer = "OK"
        elif text.startswith("recall"):
            answer = memory[sid] or "NONE"
        else:
            answer = "answer"
        update(sid, sessionUpdate="agent_message_chunk", content={"type": "text", "text": answer[:2]})
        update(sid, sessionUpdate="agent_message_chunk", content={"type": "text", "text": answer[2:]})
        update(sid, sessionUpdate="tool_call", toolCallId="t2", title="shell", kind="execute")
        reason = "refusal" if mode == "refusal" else "end_turn"
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": reason,
              "usage": {"inputTokens": 7, "outputTokens": 3, "totalTokens": 10}}})
    elif method == "session/cancel":
        if pending:
            send({"jsonrpc": "2.0", "id": pending[0], "result": {"stopReason": "cancelled"}})
    elif method == "session/close":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
'''


class Factory:
    def __init__(self, script: Path) -> None:
        self.script = script
        self.starts = 0

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        self.starts += 1
        return subprocess.Popen([sys.executable, str(self.script)], **kwargs)


def _profile(wire: str, tmp_path: Path, mode: str = "ok", **extra: Any) -> ResidentProfile:
    exe = tmp_path / "agent.exe"
    if not exe.exists():
        exe.write_text("fake", encoding="utf-8")
    env = {"FAKE_MODE": mode, "FAKE_LOG": str(tmp_path / f"{wire}-{mode}.jsonl")}
    return ResidentProfile(wire, (str(exe), *extra.pop("argv", ())), str(tmp_path), env, **extra)


@pytest.fixture
def claude(tmp_path: Path):
    script = tmp_path / "claude.py"
    script.write_text(FAKE_CLAUDE, encoding="utf-8")
    factory = Factory(script)
    pool = ResidentTransport(popen=factory, idle_seconds=600, low_memory_idle_seconds=600)
    yield pool, factory, tmp_path
    pool.close()


@pytest.fixture
def acp(tmp_path: Path):
    script = tmp_path / "acp.py"
    script.write_text(FAKE_ACP, encoding="utf-8")
    factory = Factory(script)
    pool = ResidentTransport(popen=factory, idle_seconds=600, low_memory_idle_seconds=600)
    yield pool, factory, tmp_path
    pool.close()


def _log(tmp_path: Path, wire: str, mode: str = "ok") -> list[dict]:
    path = tmp_path / f"{wire}-{mode}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


# ── Claude Code ──────────────────────────────────────────────────────────────


def test_claude_reuses_one_process_and_isolates_conversations(claude) -> None:
    pool, factory, tmp_path = claude
    profile = _profile("claude", tmp_path)
    first = pool.run(profile, ResidentRequest("remember PINEAPPLE"))
    second = pool.run(profile, ResidentRequest("recall the codeword"))
    assert first.text == "OK"
    assert second.text == "NONE"  # /clear ran between them
    assert factory.starts == 1
    assert second.metrics["reused_worker"] is True
    assert second.metrics["handshake_ms"] == 0.0
    # Readiness: a new worker's start to its first message; a reused one's /clear.
    assert first.metrics["ready_ms"] is not None and first.metrics["ready_ms"] >= 0
    assert second.metrics["ready_ms"] == second.metrics["reset_ms"] >= 0
    assert first.context_id != second.context_id
    sent = [m["message"]["content"][0]["text"] for m in _log(tmp_path, "claude") if m.get("type") == "user"]
    assert sent == ["remember PINEAPPLE", "/clear", "recall the codeword"]


def test_claude_delivers_events_text_usage_and_the_agents_own_result(claude) -> None:
    pool, _, tmp_path = claude
    lines: list[str] = []
    text: list[str] = []
    delivery: list[str] = []
    result = pool.run(_profile("claude", tmp_path), ResidentRequest(
        "hello", on_line=lines.append, on_text=text.append,
        on_delivery=lambda status, *rest: delivery.append(status)))
    assert result.text == "answer"
    assert text == ["answer"]
    assert delivery == ["not_sent", "not_sent", "unknown", "accepted"]
    assert result.envelope["total_cost_usd"] == 0.01
    assert result.usage["input_tokens"] == 10
    kinds = [json.loads(line)["type"] for line in lines]
    assert "rate_limit_event" not in kinds  # chatter is dropped before it is queued
    assert kinds[-1] == "result"


def test_claude_reports_an_error_the_agent_put_in_its_result(claude) -> None:
    pool, _, tmp_path = claude
    result = pool.run(_profile("claude", tmp_path, "max_turns"), ResidentRequest("hello"))
    assert result.envelope["is_error"] is True
    assert result.envelope["subtype"] == "error_max_turns"


def test_claude_denies_what_the_agent_asks_kriko_to_allow(claude) -> None:
    pool, _, tmp_path = claude
    pool.run(_profile("claude", tmp_path, "ask_permission"), ResidentRequest("hello"))
    time.sleep(0.2)
    replies = [m for m in _log(tmp_path, "claude", "ask_permission") if m.get("type") == "control_response"]
    assert replies and replies[0]["response"]["subtype"] == "error"


def test_claude_profiles_that_differ_get_their_own_workers(claude) -> None:
    pool, factory, tmp_path = claude
    pool.max_workers = 1  # one slot: the second profile must evict the idle first
    pool.run(_profile("claude", tmp_path, model="a"), ResidentRequest("hello"))
    pool.run(_profile("claude", tmp_path, model="b"), ResidentRequest("hello"))
    pool.run(_profile("claude", tmp_path, model="b"), ResidentRequest("hello"))
    assert factory.starts == 2


def test_four_reader_runs_each_get_their_own_agent_process_at_once(tmp_path: Path) -> None:
    """Reproduction: with the reader's choice of four, four runs must be four processes.

    The agent-child budget was the profile's two, so the third and fourth run
    waited for a worker while the job said it was running. Each run is busy on
    its own worker here; none is reused, so the count is the number of
    processes alive while none has answered.
    """
    script = tmp_path / "claude.py"
    script.write_text(FAKE_CLAUDE, encoding="utf-8")
    factory = Factory(script)
    pool = ResidentTransport(popen=factory, idle_seconds=600, low_memory_idle_seconds=600)
    gate = tmp_path / "gate-open"
    base = _profile("claude", tmp_path, mode="gate")
    profile = ResidentProfile(base.wire, base.argv, base.cwd, {**base.env, "FAKE_GATE": str(gate)})
    errors: list[BaseException] = []

    def ask() -> None:
        try:
            pool.run(profile, ResidentRequest("hello", timeout=60))
        except BaseException as exc:  # noqa: BLE001 - reported by the assertion below
            errors.append(exc)

    agentresources.set_agent_children_floor(4)
    threads = [threading.Thread(target=ask) for _ in range(4)]
    try:
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 20
        while factory.starts < 4 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert factory.starts == 4
    finally:
        gate.write_text("open", encoding="utf-8")
        for thread in threads:
            thread.join(30)
        pool.close()
        agentresources.set_agent_children_floor(0)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []


def test_claude_lines_longer_than_a_default_limit_are_read(claude) -> None:
    pool, _, tmp_path = claude
    result = pool.run(_profile("claude", tmp_path, "long_line"), ResidentRequest("hello"))
    assert result.text == "answer"


def test_claude_cancel_stops_the_turn_and_keeps_a_worker_that_stopped(claude) -> None:
    pool, factory, tmp_path = claude
    profile = _profile("claude", tmp_path, "hang_then_stop")
    cancel = threading.Event()
    threading.Timer(0.4, cancel.set).start()
    with pytest.raises(TurnCancelled):
        pool.run(profile, ResidentRequest("hello", timeout=20), cancel_event=cancel)
    assert pool.worker_count() == 1  # it said it stopped, so it is not quarantined


def test_claude_cancel_of_a_worker_that_does_not_stop_quarantines_it(claude) -> None:
    pool, factory, tmp_path = claude
    profile = _profile("claude", tmp_path, "hang")
    cancel = threading.Event()
    threading.Timer(0.4, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(TurnCancelled):
        pool.run(profile, ResidentRequest("hello", timeout=20), cancel_event=cancel)
    assert time.monotonic() - started < 6
    assert pool.worker_count() == 0


def test_claude_crash_after_the_prompt_is_uncertain_and_never_replayed(claude) -> None:
    pool, factory, tmp_path = claude
    seen: list[str] = []
    with pytest.raises(DeliveryUncertain):
        pool.run(_profile("claude", tmp_path, "crash"), ResidentRequest(
            "hello", on_delivery=lambda status, *rest: seen.append(status)))
    assert seen[-1] == "unknown"
    assert factory.starts == 1
    assert pool.worker_count() == 0


def test_claude_timeout_is_uncertain_and_quarantines(claude) -> None:
    pool, _, tmp_path = claude
    with pytest.raises(DeliveryUncertain):
        pool.run(_profile("claude", tmp_path, "hang"), ResidentRequest("hello", timeout=0.6))
    assert pool.worker_count() == 0


def test_a_missing_executable_is_unavailable_before_anything_is_sent(claude) -> None:
    pool, _, tmp_path = claude
    profile = ResidentProfile("claude", (str(tmp_path / "absent"),), str(tmp_path), {})
    seen: list[str] = []
    with pytest.raises(TransportUnavailable):
        pool.run(profile, ResidentRequest("hello", on_delivery=lambda status, *rest: seen.append(status)))
    assert seen == ["not_sent"]


def test_a_wire_nobody_registered_is_unavailable(claude) -> None:
    pool, _, tmp_path = claude
    with pytest.raises(TransportUnavailable):
        pool.run(_profile("agy", tmp_path), ResidentRequest("hello"))


def test_release_idle_frees_workers_but_not_busy_ones(claude) -> None:
    pool, factory, tmp_path = claude
    pool.run(_profile("claude", tmp_path), ResidentRequest("hello"))
    assert pool.release_idle() == 1
    assert pool.worker_count() == 0
    pool.run(_profile("claude", tmp_path), ResidentRequest("hello"))
    assert factory.starts == 2


def test_a_warmed_worker_is_the_one_the_turn_reuses(claude) -> None:
    """The start a quiet turn pays is the start a later request must not."""
    pool, factory, tmp_path = claude
    profile = _profile("claude", tmp_path)

    assert pool.warm(profile) is True
    pool.run(profile, ResidentRequest("hello"))

    assert factory.starts == 1


def test_a_warm_up_that_cannot_start_is_not_an_error(claude) -> None:
    pool, _factory, tmp_path = claude
    absent = ResidentProfile("claude", (str(tmp_path / "absent"),), str(tmp_path), {})

    assert pool.warm(absent) is False


# ── ACP ──────────────────────────────────────────────────────────────────────


def test_acp_opens_a_fresh_session_per_request_on_one_process(acp) -> None:
    pool, factory, tmp_path = acp
    profile = _profile("acp", tmp_path)
    first = pool.run(profile, ResidentRequest("remember PINEAPPLE"))
    second = pool.run(profile, ResidentRequest("recall the codeword"))
    assert (first.text, second.text) == ("OK", "NONE")
    assert factory.starts == 1
    assert first.context_id != second.context_id
    assert second.usage["totalTokens"] == 10
    methods = [m.get("method") for m in _log(tmp_path, "acp")]
    assert methods.count("session/new") == 2
    assert methods.count("session/close") == 2  # the agent said it can free sessions
    init = next(m for m in _log(tmp_path, "acp") if m.get("method") == "initialize")
    assert init["params"]["clientCapabilities"] == {
        "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}


def test_acp_streams_text_and_says_when_a_tool_was_asked_for(acp) -> None:
    pool, _, tmp_path = acp
    text, actions, delivery = [], [], []
    result = pool.run(_profile("acp", tmp_path), ResidentRequest(
        "hello", on_text=text.append, on_action=actions.append,
        on_delivery=lambda status, *rest: delivery.append(status)))
    assert result.text == "answer" and text == ["an", "swer"]
    assert any("grants the agent no tools" in line for line in actions)
    assert delivery == ["not_sent", "not_sent", "unknown", "accepted"]


def test_acp_refuses_a_permission_request_with_the_agents_own_reject_option(acp) -> None:
    pool, _, tmp_path = acp
    pool.run(_profile("acp", tmp_path, "permission"), ResidentRequest("hello"))
    answer = [m for m in _log(tmp_path, "acp", "permission") if m.get("id") == "perm-1"]
    assert answer[0]["result"]["outcome"] == {"outcome": "selected", "optionId": "deny"}


def test_acp_a_stop_that_is_not_end_of_turn_is_an_error_not_an_answer(acp) -> None:
    pool, _, tmp_path = acp
    with pytest.raises(ResidentError, match="refusal"):
        pool.run(_profile("acp", tmp_path, "refusal"), ResidentRequest("hello"))
    assert pool.worker_count() == 0


def test_acp_cancel_asks_the_session_to_stop(acp) -> None:
    pool, _, tmp_path = acp
    cancel = threading.Event()
    def received(status, *_args):
        if status == "accepted":
            cancel.set()
    with pytest.raises(TurnCancelled):
        pool.run(_profile("acp", tmp_path, "hang"),
                 ResidentRequest("hello", timeout=20, on_delivery=received), cancel_event=cancel)
    assert any(m.get("method") == "session/cancel" for m in _log(tmp_path, "acp", "hang"))
    assert pool.worker_count() == 1  # the agent answered `cancelled`


def test_acp_handshake_failure_is_unavailable_so_auto_can_fall_back(acp) -> None:
    pool, _, tmp_path = acp
    seen: list[str] = []
    with pytest.raises(TransportUnavailable):
        pool.run(_profile("acp", tmp_path, "bad_init"), ResidentRequest(
            "hello", on_delivery=lambda status, *rest: seen.append(status)))
    assert seen == ["not_sent"]
    assert pool.worker_count() == 0


def test_identity_hashes_the_environment_and_never_stores_it(tmp_path: Path) -> None:
    a = _profile("acp", tmp_path)
    secret = ResidentProfile(a.wire, a.argv, a.cwd, {**a.env, "MISTRAL_API_KEY": "sk-secret"})
    other = ResidentProfile(a.wire, a.argv, a.cwd, {**a.env, "MISTRAL_API_KEY": "sk-other"})
    assert secret.identity() != other.identity() != a.identity()
    assert "sk-secret" not in secret.identity()
