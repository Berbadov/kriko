import threading
import time

import pytest

from app import agentresources


def test_source_quota_is_shared_across_threads(monkeypatch):
    monkeypatch.setenv("KRIKO_MAX_OUTBOUND", "8")
    monkeypatch.setenv("KRIKO_MAX_PER_SOURCE", "1")
    entered = threading.Event()
    release = threading.Event()

    def first():
        with agentresources.slot("outbound", "same.example"):
            entered.set()
            release.wait(2)

    thread = threading.Thread(target=first)
    thread.start()
    assert entered.wait(1)
    with pytest.raises(TimeoutError):
        with agentresources.slot("outbound", "same.example", timeout=0.04):
            pass
    release.set()
    thread.join(1)
    assert not thread.is_alive()


def test_waiting_busy_source_does_not_block_an_unrelated_source(monkeypatch):
    monkeypatch.setenv("KRIKO_MAX_OUTBOUND", "2")
    monkeypatch.setenv("KRIKO_MAX_PER_SOURCE", "1")
    entered = threading.Event()
    release = threading.Event()
    waiting = threading.Event()

    def first():
        with agentresources.slot("outbound", "busy.example"):
            entered.set()
            release.wait(2)

    def same_source_waiter():
        waiting.set()
        with agentresources.slot("outbound", "busy.example", timeout=1):
            pass

    holder = threading.Thread(target=first)
    holder.start()
    assert entered.wait(1)
    waiter = threading.Thread(target=same_source_waiter)
    waiter.start()
    assert waiting.wait(1)
    time.sleep(0.04)  # let it enter the host limiter's wait queue
    try:
        with agentresources.slot("outbound", "free.example", timeout=0.2):
            pass
    finally:
        release.set()
        holder.join(1)
        waiter.join(1)
    assert not holder.is_alive()
    assert not waiter.is_alive()


def test_waiting_slot_checks_cancellation_and_cleans_waiter(monkeypatch):
    monkeypatch.setenv("KRIKO_MAX_LOCAL_INFERENCE", "1")
    entered = threading.Event()
    release = threading.Event()
    thread = threading.Thread(target=lambda: _hold_inference(entered, release))
    thread.start()
    assert entered.wait(1)
    checks = 0

    def cancel():
        nonlocal checks
        checks += 1
        if checks > 1:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        with agentresources.slot("inference", check=cancel):
            pass
    release.set()
    thread.join(1)
    with agentresources.slot("inference", timeout=0.1):
        pass


def _hold_inference(entered, release):
    with agentresources.slot("inference"):
        entered.set()
        release.wait(2)


def test_idle_policy_uses_available_memory():
    assert agentresources.idle_policy(ram_available_mb=128) == "release"
    assert agentresources.idle_policy(ram_available_mb=8192) == "keep"


def test_native_memory_snapshot_reports_positive_host_ram():
    snapshot = agentresources.memory_snapshot()
    assert snapshot is not None
    total_bytes, available_bytes = snapshot
    assert total_bytes > 0
    assert 0 <= available_bytes <= total_bytes
    assert agentresources.total_memory_gib() > 0


def test_unknown_native_memory_is_conservative(monkeypatch):
    monkeypatch.setattr(agentresources, "memory_snapshot", lambda: None)
    assert agentresources.total_memory_gib() <= 8
    assert agentresources.idle_policy() == "release"


def test_pacing_wait_checks_cancellation():
    source = "test-cancelable-pacing"
    agentresources.pace(source, 0.5)
    checks = 0

    def cancel():
        nonlocal checks
        checks += 1
        if checks > 1:
            raise RuntimeError("cancelled")

    began = time.monotonic()
    with pytest.raises(RuntimeError, match="cancelled"):
        agentresources.pace(source, 0.5, check=cancel)
    assert time.monotonic() - began < 0.2
