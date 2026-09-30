"""research-2: a reader's own read must not queue behind `warm_models()`.

`warm_models()` starts a background probe at startup so the first visit to
Agents/Connect does not pay the ~2s a CLI's `models` subcommand costs. Before
this fix, `models_for` serialised every caller — the warm-up thread included —
on one lock per harness, so a request landing while the warm-up was still
probing waited for that exact probe instead of finding a cache: the thing the
warm-up existed to avoid happened to the first reader anyway.
"""

import threading
import time

from app.providers import harness


def _slow_command(executable, *argv, **kw):
    time.sleep(0.4)
    return "vendor/model-a\nvendor/model-b\n"


def test_an_ordinary_read_does_not_wait_for_an_in_flight_probe(monkeypatch, tmp_path):
    exe = tmp_path / "fake-cli"
    exe.write_text("", encoding="utf-8")
    one = harness.Harness(
        id="fake", label="Fake", executable=str(exe), model_source="models",
    )
    monkeypatch.setattr(harness, "locate", lambda h: str(exe))
    monkeypatch.setattr(harness, "_ask", _slow_command)
    harness._MODELS.clear()
    harness._ASKING.clear()

    # Start the "warm-up" probe on a background thread, exactly as
    # warm_models() does, and give it time to actually acquire the lock.
    warmup = threading.Thread(target=lambda: harness.models_for(one), daemon=True)
    warmup.start()
    time.sleep(0.1)

    started = time.monotonic()
    result = harness.models_for(one)
    elapsed = time.monotonic() - started

    assert elapsed < 0.2, (
        f"an ordinary read blocked {elapsed:.2f}s behind the warm-up probe "
        "instead of serving whatever was cached"
    )
    assert result == []  # nothing cached yet — the warm-up hasn't finished
    warmup.join(timeout=2)


def test_a_fresh_reask_still_waits_for_a_real_answer(monkeypatch, tmp_path):
    exe = tmp_path / "fake-cli"
    exe.write_text("", encoding="utf-8")
    one = harness.Harness(
        id="fake2", label="Fake2", executable=str(exe), model_source="models",
    )
    monkeypatch.setattr(harness, "locate", lambda h: str(exe))
    monkeypatch.setattr(harness, "_ask", _slow_command)
    harness._MODELS.clear()
    harness._ASKING.clear()

    result = harness.models_for(one, fresh=True)
    assert result == ["vendor/model-a", "vendor/model-b"]
