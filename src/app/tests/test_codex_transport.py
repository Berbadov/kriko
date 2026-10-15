from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app.providers.codex_transport import (
    CodexProfile,
    CodexRequest,
    CodexTransport,
    DeliveryUncertain,
    TurnCancelled,
    _final_text,
)


FAKE_SERVER = r'''import json, os, sys, time, uuid
mode = os.environ.get("FAKE_MODE", "ok")
log = os.environ.get("FAKE_LOG")
count = 0
current = None
def send(value):
    sys.stdout.write(json.dumps(value) + "\n")
    sys.stdout.flush()
def record(value):
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(value) + "\n")
for line in sys.stdin:
    req = json.loads(line)
    record(req)
    method = req.get("method")
    if method == "initialize":
        send({"jsonrpc":"2.0", "id":req["id"], "result":{"userAgent":"fake"}})
    elif method == "initialized":
        pass
    elif method == "thread/start":
        if mode == "slow_thread":
            time.sleep(2)
        count += 1
        current = {"threadId":f"thread-{os.getpid()}-{count}", "turnId":None}
        send({"jsonrpc":"2.0", "id":req["id"], "result":{"thread":{"id":current["threadId"]}, "model":"fake-model"}})
    elif method == "turn/start":
        current["turnId"] = f"turn-{uuid.uuid4()}"
        if mode == "crash":
            send({"jsonrpc":"2.0", "id":req["id"], "result":{"turn":{"id":current["turnId"]}}})
            os._exit(0)
        send({"jsonrpc":"2.0", "method":"turn/started", "params":{"threadId":current["threadId"], "turn":{"id":current["turnId"], "status":"inProgress"}}})
        send({"jsonrpc":"2.0", "id":req["id"], "result":{"turn":{"id":current["turnId"]}}})
        send({"jsonrpc":"2.0", "method":"turn/completed", "params":{"threadId":current["threadId"], "turn":{"id":"stale-turn", "status":"completed", "items":[]}}})
        if mode == "forbidden":
            send({"jsonrpc":"2.0", "method":"item/started", "params":{"threadId":current["threadId"], "turnId":current["turnId"], "item":{"id":"shell", "type":"commandExecution"}}})
        elif mode == "capability":
            send({"jsonrpc":"2.0", "id":"approval-1", "method":"item/commandExecution/requestApproval", "params":{"threadId":current["threadId"], "turnId":current["turnId"]}})
            reply = sys.stdin.readline()
            if reply:
                record(json.loads(reply))
            send({"jsonrpc":"2.0", "method":"turn/completed", "params":{"threadId":current["threadId"], "turn":{"id":current["turnId"], "status":"failed", "error":{"message":"command approval denied"}, "items":[]}}})
        elif mode == "cancel":
            continue
        elif mode == "long_stream":
            # A real answer streams one delta per token; 1500 deltas written in a
            # burst is past both the per-turn cap and the 64-line reader queue.
            answer = "".join(f"w{i} " for i in range(1500))
            for start in range(0, len(answer), 4):
                send({"jsonrpc":"2.0", "method":"item/agentMessage/delta", "params":{"threadId":current["threadId"], "turnId":current["turnId"], "itemId":"item-1", "delta":answer[start:start+4]}})
            send({"jsonrpc":"2.0", "method":"turn/completed", "params":{"threadId":current["threadId"], "turn":{"id":current["turnId"], "status":"completed", "items":[{"type":"agentMessage", "id":"item-1", "text":answer}]}}})
        elif mode == "long_answer":
            # The whole final answer travels in one turn/completed line.
            answer = "a" * 100_000
            send({"jsonrpc":"2.0", "method":"turn/completed", "params":{"threadId":current["threadId"], "turn":{"id":current["turnId"], "status":"completed", "items":[{"type":"agentMessage", "id":"item-1", "text":answer}]}}})
        else:
            send({"jsonrpc":"2.0", "method":"item/agentMessage/delta", "params":{"threadId":current["threadId"], "turnId":current["turnId"], "itemId":"item-1", "delta":"answer"}})
            send({"jsonrpc":"2.0", "method":"thread/tokenUsage/updated", "params":{"threadId":current["threadId"], "turnId":current["turnId"], "tokenUsage":{"inputTokens":12,"outputTokens":3}}})
            if mode == "cache_write":
                with open(os.path.join(os.environ["CODEX_HOME"], "models_cache.json"), "w", encoding="utf-8") as f:
                    json.dump({"refreshed": time.time()}, f)
            send({"jsonrpc":"2.0", "method":"turn/completed", "params":{"threadId":current["threadId"], "turn":{"id":current["turnId"], "status":"completed", "items":[{"type":"agentMessage", "id":"item-1", "text":"answer"}]}}})
    elif method == "turn/interrupt":
        send({"jsonrpc":"2.0", "method":"turn/completed", "params":{"threadId":req["params"]["threadId"], "turn":{"id":req["params"]["turnId"], "status":"interrupted", "items":[]}}})
'''


class FakeFactory:
    def __init__(self, script: Path) -> None:
        self.script = script
        self.starts = 0

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.Popen[str]:
        self.starts += 1
        return subprocess.Popen([sys.executable, str(self.script)], **kwargs)


@pytest.fixture
def environment(tmp_path: Path) -> tuple[Path, Path, Path]:
    exe = tmp_path / "codex.exe"
    exe.write_text("fake", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text("", encoding="utf-8")
    script = tmp_path / "fake_server.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return exe, home, script


def make_profile(exe: Path, home: Path, tmp_path: Path, mode: str = "ok") -> CodexProfile:
    return CodexProfile(
        executable=str(exe), home_dir=str(home), cwd=str(tmp_path), model="requested-model",
        effort="high", env={"FAKE_MODE": mode, "FAKE_LOG": str(tmp_path / f"{mode}.jsonl")},
    )


def make_transport(script: Path, *, idle_seconds: float = 600) -> tuple[CodexTransport, FakeFactory]:
    factory = FakeFactory(script)
    return CodexTransport(popen=factory, idle_seconds=idle_seconds, low_memory_idle_seconds=idle_seconds), factory


def request(**kwargs: Any) -> CodexRequest:
    return CodexRequest(prompt="research this", output_schema={"type": "object"}, **kwargs)


def test_final_text_selects_final_phase_and_ignores_other_phases() -> None:
    turn = {
        "items": [
            {"type": "agentMessage", "phase": "commentary", "text": "Searching..."},
            {"type": "agentMessage", "phase": "partial_answer", "text": "Draft: {"},
            {"type": "agentMessage", "phase": "final_answer", "text": '{"ok": true}'},
            {"type": "agentMessage", "phase": "future_phase", "text": "must not replace final"},
        ]
    }
    assert _final_text(turn) == '{"ok": true}'


def test_final_text_falls_back_to_phase_less_messages_for_older_servers() -> None:
    turn = {
        "items": [
            {"type": "agentMessage", "text": "legacy answer"},
            {"type": "agentMessage", "phase": "commentary", "text": "aside"},
        ]
    }
    assert _final_text(turn) == "legacy answer"


def test_reuses_resident_process_with_fresh_thread_and_routes_usage(environment: tuple[Path, Path, Path], tmp_path: Path) -> None:
    exe, home, script = environment
    transport, factory = make_transport(script)
    profile = make_profile(exe, home, tmp_path)
    texts: list[str] = []
    try:
        first = transport.run(profile, request(), on_text=texts.append)
        second = transport.run(profile, request())
        assert factory.starts == 1
        assert first.thread_id != second.thread_id
        assert first.turn_id != second.turn_id
        assert first.text == "answer"
        assert first.usage == {"inputTokens": 12, "outputTokens": 3}
        assert first.metrics["model"] == "fake-model"
        assert first.metrics["reused_worker"] is False
        assert second.metrics["reused_worker"] is True
        assert second.metrics["worker_start_ms"] == 0
        assert second.metrics["handshake_ms"] == 0
        for field in ("queue_ms", "worker_start_ms", "handshake_ms", "thread_start_ms", "turn_accept_ms", "total_ms"):
            assert first.metrics[field] >= 0
        assert first.metrics["first_text_ms"] is not None
        assert second.metrics["first_text_ms"] is not None
        assert texts == ["answer"]
    finally:
        transport.close()


def test_profile_config_change_starts_new_worker(environment: tuple[Path, Path, Path], tmp_path: Path) -> None:
    exe, home, script = environment
    transport, factory = make_transport(script)
    profile = make_profile(exe, home, tmp_path)
    try:
        transport.run(profile, request())
        (home / "config.toml").write_text("# changed\n", encoding="utf-8")
        transport.run(profile, request())
        assert factory.starts == 2
    finally:
        transport.close()


def test_native_models_cache_refresh_does_not_restart_worker(environment: tuple[Path, Path, Path], tmp_path: Path) -> None:
    exe, home, script = environment
    transport, factory = make_transport(script)
    profile = make_profile(exe, home, tmp_path, "cache_write")
    try:
        transport.run(profile, request())
        assert (home / "models_cache.json").exists()
        second = transport.run(profile, request())
        assert factory.starts == 1
        assert second.metrics["reused_worker"] is True
    finally:
        transport.close()


def test_late_events_for_another_turn_are_ignored(environment: tuple[Path, Path, Path], tmp_path: Path) -> None:
    exe, home, script = environment
    transport, _ = make_transport(script)
    try:
        result = transport.run(make_profile(exe, home, tmp_path), request())
        assert result.text == "answer"
        assert all(event["params"].get("turn", {}).get("id") != "stale-turn" for event in result.events)
    finally:
        transport.close()


def test_child_crash_after_turn_write_is_uncertain_and_not_retried(environment: tuple[Path, Path, Path], tmp_path: Path) -> None:
    exe, home, script = environment
    transport, factory = make_transport(script)
    states: list[tuple[str, str, str, Any]] = []
    try:
        with pytest.raises(DeliveryUncertain):
            transport.run(make_profile(exe, home, tmp_path, "crash"), request(), on_delivery=lambda *args: states.append(args))
        assert factory.starts == 1
        assert states[0][0] == "not_sent"
        assert "unknown" in [item[0] for item in states]
    finally:
        transport.close()


def test_cancel_interrupts_exact_turn_and_keeps_worker_if_it_stops(environment: tuple[Path, Path, Path], tmp_path: Path) -> None:
    exe, home, script = environment
    transport, _ = make_transport(script)
    cancelled = threading.Event()
    accepted = threading.Event()
    accepted_ids: dict[str, str] = {}
    errors: list[BaseException] = []
    profile = make_profile(exe, home, tmp_path, "cancel")

    def run_job() -> None:
        try:
            def delivered(status: str, context_id: str, turn_id: str, _detail: Any) -> None:
                if status == "accepted":
                    accepted_ids.update(thread_id=context_id, turn_id=turn_id)
                    accepted.set()
            transport.run(
                profile, request(timeout=10), cancel_event=cancelled,
                on_delivery=delivered,
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_job)
    thread.start()
    assert accepted.wait(5)
    cancelled.set()
    thread.join(5)
    try:
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], TurnCancelled)
        assert len(transport._workers) == 1 and not transport._workers[0].quarantined
        records = [json.loads(line) for line in (tmp_path / "cancel.jsonl").read_text(encoding="utf-8").splitlines()]
        interrupt = next(row for row in records if row.get("method") == "turn/interrupt")
        assert interrupt["params"] == {"threadId": accepted_ids["thread_id"], "turnId": accepted_ids["turn_id"]}
    finally:
        transport.close()


def test_server_capability_request_is_denied(environment: tuple[Path, Path, Path], tmp_path: Path) -> None:
    exe, home, script = environment
    transport, _ = make_transport(script)
    profile = make_profile(exe, home, tmp_path, "capability")
    try:
        with pytest.raises(DeliveryUncertain):
            transport.run(profile, request())
        records = [json.loads(line) for line in (tmp_path / "capability.jsonl").read_text(encoding="utf-8").splitlines()]
        reply = next(row for row in records if row.get("id") == "approval-1")
        assert "error" in reply and reply["error"]["message"] == "client capability denied"
    finally:
        transport.close()


def test_a_long_streamed_answer_is_a_result_not_a_failed_turn(
    environment: tuple[Path, Path, Path], tmp_path: Path,
) -> None:
    """Regression: the per-turn event cap raised on the 257th event, and every
    streamed token is an event. Real research replies stream hundreds of deltas,
    so each was failed a few seconds into the turn, recorded as DeliveryUncertain.
    The same burst also overran the 64-line reader queue, which killed the
    worker; a busy consumer must make the reader wait, not fail the turn."""
    exe, home, script = environment
    transport, _ = make_transport(script)
    profile = make_profile(exe, home, tmp_path, "long_stream")
    try:
        result = transport.run(profile, request())
        assert result.text == "".join(f"w{i} " for i in range(1500)).strip()
        assert result.metrics["event_count"] > 256
    finally:
        transport.close()


def test_a_final_answer_longer_than_one_protocol_line_is_not_rejected(
    environment: tuple[Path, Path, Path], tmp_path: Path,
) -> None:
    """Regression: a whole answer arrives as one JSON line, and a 64 KiB line
    cap failed any answer past roughly 16k tokens, well inside what a research
    reply can be. The cap is a memory guard, so it must sit above a real answer."""
    exe, home, script = environment
    transport, _ = make_transport(script)
    profile = make_profile(exe, home, tmp_path, "long_answer")
    try:
        result = transport.run(profile, request())
        assert result.text == "a" * 100_000
    finally:
        transport.close()


def test_forbidden_item_quarantines_without_returning_a_result(
    environment: tuple[Path, Path, Path], tmp_path: Path,
) -> None:
    exe, home, script = environment
    transport, _ = make_transport(script)
    profile = make_profile(exe, home, tmp_path, "forbidden")
    try:
        with pytest.raises(DeliveryUncertain):
            transport.run(profile, request())
        assert not transport._workers
    finally:
        transport.close()


def test_idle_worker_can_be_released(environment: tuple[Path, Path, Path], tmp_path: Path) -> None:
    exe, home, script = environment
    transport, _ = make_transport(script, idle_seconds=0)
    try:
        transport.run(make_profile(exe, home, tmp_path), request())
        assert transport._workers
        transport._reap_once()
        assert not transport._workers
    finally:
        transport.close()


def test_release_idle_frees_shared_child_slots_for_legacy_providers(
    environment: tuple[Path, Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agentresources import slot

    exe, home, script = environment
    monkeypatch.setenv("KRIKO_MAX_AGENT_CHILDREN", "2")
    transport, factory = make_transport(script)
    profile = make_profile(exe, home, tmp_path, "cancel")
    accepted = [threading.Event(), threading.Event()]
    cancelled = [threading.Event(), threading.Event()]
    errors: list[BaseException] = []

    def run_job(index: int) -> None:
        def on_delivery(status: str, *_: Any) -> None:
            if status == "accepted":
                accepted[index].set()
        try:
            transport.run(profile, request(timeout=8), cancel_event=cancelled[index], on_delivery=on_delivery)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run_job, args=(index,)) for index in range(2)]
    try:
        for thread in threads:
            thread.start()
        assert all(event.wait(5) for event in accepted)
        assert factory.starts == 2
        for event in cancelled:
            event.set()
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive()
        assert len(errors) == 2 and all(isinstance(error, TurnCancelled) for error in errors)
        with pytest.raises(TimeoutError):
            with slot("agent_child", timeout=0.05):
                pass
        assert transport.release_idle() == 2
        with slot("agent_child", timeout=0.1):
            pass
    finally:
        transport.close()


def test_release_idle_leaves_an_active_worker_untouched(
    environment: tuple[Path, Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe, home, script = environment
    monkeypatch.setenv("KRIKO_MAX_AGENT_CHILDREN", "2")
    transport, _ = make_transport(script)
    profile = make_profile(exe, home, tmp_path, "cancel")
    accepted = [threading.Event(), threading.Event()]
    cancel = [threading.Event(), threading.Event()]
    errors: list[BaseException] = []

    def active_job(index: int) -> None:
        def on_delivery(status: str, *_: Any) -> None:
            if status == "accepted":
                accepted[index].set()
        try:
            transport.run(profile, request(timeout=8), cancel_event=cancel[index],
                          on_delivery=on_delivery)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=active_job, args=(index,)) for index in range(2)]
    try:
        for thread in threads:
            thread.start()
        assert all(event.wait(5) for event in accepted)
        cancel[0].set()
        threads[0].join(5)
        assert not threads[0].is_alive()
        active_worker = next(worker for worker in transport._workers if worker.busy)
        assert transport.release_idle() == 1
        assert active_worker in transport._workers and active_worker.busy
        assert not active_worker.quarantined
        cancel[1].set()
        threads[1].join(5)
        assert not threads[1].is_alive()
        assert len(errors) == 2 and all(isinstance(error, TurnCancelled) for error in errors)
    finally:
        for event in cancel:
            event.set()
        for thread in threads:
            if thread.is_alive():
                thread.join(5)
        transport.close()


def test_optional_model_effort_and_schema_are_not_invented(environment: tuple[Path, Path, Path], tmp_path: Path) -> None:
    exe, home, script = environment
    transport, _ = make_transport(script)
    profile = CodexProfile(executable=str(exe), home_dir=str(home), cwd=str(tmp_path), model="", effort="",
                           env={"FAKE_LOG": str(tmp_path / "ok.jsonl")})
    try:
        result = transport.run(profile, CodexRequest(prompt="answer"))
        assert result.text == "answer"
        rows = [json.loads(line) for line in (tmp_path / "ok.jsonl").read_text(encoding="utf-8").splitlines()]
        params = next(row["params"] for row in rows if row.get("method") == "turn/start")
        assert "model" not in params and "effort" not in params and "outputSchema" not in params
    finally:
        transport.close()


def test_cancel_check_exception_propagates_unchanged(environment: tuple[Path, Path, Path], tmp_path: Path) -> None:
    exe, home, script = environment
    transport, _ = make_transport(script)
    error = RuntimeError("job cancellation sentinel")
    calls = 0

    def check_cancelled() -> None:
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise error

    try:
        with pytest.raises(RuntimeError) as caught:
            transport.run(make_profile(exe, home, tmp_path), request(timeout=10), check_cancelled=check_cancelled)
        assert caught.value is error
        assert len(transport._workers) == 1 and not transport._workers[0].quarantined
    finally:
        transport.close()


def test_saturated_pool_waits_outside_lock_then_replaces_idle_profile(
    environment: tuple[Path, Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe, home, script = environment
    monkeypatch.setenv("KRIKO_MAX_AGENT_CHILDREN", "1")
    transport, factory = make_transport(script)
    first_profile = make_profile(exe, home, tmp_path, "cancel")
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    second_profile = CodexProfile(
        executable=str(exe), home_dir=str(home), cwd=str(other_cwd), model="different-model",
        effort="low", env={"FAKE_LOG": str(tmp_path / "second.jsonl")},
    )
    first_cancel = threading.Event()
    first_errors: list[BaseException] = []
    second_results: list[Any] = []

    def first_job() -> None:
        try:
            transport.run(first_profile, request(timeout=8), cancel_event=first_cancel)
        except BaseException as exc:
            first_errors.append(exc)

    def second_job() -> None:
        try:
            second_results.append(transport.run(second_profile, request(timeout=8)))
        except BaseException as exc:
            second_results.append(exc)

    first_thread = threading.Thread(target=first_job)
    first_thread.start()
    time.sleep(.25)
    second_thread = threading.Thread(target=second_job)
    second_thread.start()
    time.sleep(.2)
    assert second_thread.is_alive()
    first_cancel.set()
    first_thread.join(5)
    second_thread.join(8)
    try:
        assert not first_thread.is_alive() and not second_thread.is_alive()
        assert len(first_errors) == 1 and isinstance(first_errors[0], TurnCancelled)
        assert len(second_results) == 1 and getattr(second_results[0], "text", None) == "answer"
        assert factory.starts == 2
    finally:
        transport.close()


def test_one_absolute_deadline_times_out_without_capability_fallback(
    environment: tuple[Path, Path, Path], tmp_path: Path,
) -> None:
    exe, home, script = environment
    transport, factory = make_transport(script)
    states: list[tuple[str, str, str, Any]] = []
    try:
        with pytest.raises(TimeoutError):
            transport.run(
                make_profile(exe, home, tmp_path, "slow_thread"),
                request(timeout=0.8),
                on_delivery=lambda *args: states.append(args),
            )
        assert factory.starts == 1
        assert all(row.get("method") != "turn/start" for row in (
            json.loads(line) for line in (tmp_path / "slow_thread.jsonl").read_text(encoding="utf-8").splitlines()
        ))
        assert [item[0] for item in states] == ["not_sent"]
    finally:
        transport.close()
