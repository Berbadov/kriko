"""B152.7: finding the agent CLIs is a PATH x PATHEXT walk — about 200 ms on
the reader's machine, paid by every screen that reads `/api/prefs`. It is
remembered for a few seconds, and forgotten the moment anything that changes
the answer does."""

from app.providers import harness


def _count_walks(monkeypatch):
    walks = []

    def fake(one):
        walks.append(one.executable)
        return f"/bin/{one.executable}"

    monkeypatch.setattr(harness, "_locate", fake)
    harness.forget_located()
    return walks


def test_a_second_ask_does_not_walk_the_path_again(monkeypatch):
    walks = _count_walks(monkeypatch)
    one = harness.KNOWN[0]
    assert harness.locate(one) == harness.locate(one) == f"/bin/{one.executable}"
    assert walks == [one.executable]


def test_a_changed_path_is_a_fresh_walk(monkeypatch):
    walks = _count_walks(monkeypatch)
    one = harness.KNOWN[0]
    harness.locate(one)
    monkeypatch.setenv("PATH", "/somewhere/new")
    harness.locate(one)
    assert len(walks) == 2


def test_check_again_forgets_what_was_found(monkeypatch):
    walks = _count_walks(monkeypatch)
    one = harness.KNOWN[0]
    harness.locate(one)
    harness.forget_located()
    harness.locate(one)
    assert len(walks) == 2


def test_the_memory_runs_out(monkeypatch):
    walks = _count_walks(monkeypatch)
    one = harness.KNOWN[0]
    clock = [1000.0]
    monkeypatch.setattr(harness.time, "monotonic", lambda: clock[0])
    harness.locate(one)
    clock[0] += harness.LOCATE_TTL_S + 1
    harness.locate(one)
    assert len(walks) == 2


def test_an_expired_model_list_is_served_while_it_is_asked_again(monkeypatch):
    """The Settings screen waited ~7 s once `MODELS_TTL` ran out; it now shows
    the list it had and the ask runs behind it."""
    import threading

    one = next(h for h in harness.KNOWN if h.model_source == "models" and not h.unusable)
    monkeypatch.setattr(harness, "locate", lambda h: "/bin/x")
    monkeypatch.setattr(harness, "_stamp", lambda e: 1.0)
    monkeypatch.setattr(harness, "_MODELS", {})
    monkeypatch.setattr(harness, "_ASKING", {})
    asked = threading.Event()
    answers = iter([["old-model"], ["new-model"]])

    def ask(h, e):
        asked.set()
        return next(answers)

    monkeypatch.setattr(harness, "_from_models_command", ask)
    clock = [1000.0]
    monkeypatch.setattr(harness.time, "monotonic", lambda: clock[0])
    assert harness.models_for(one) == ["old-model"]

    asked.clear()
    clock[0] += harness.MODELS_TTL + 1
    assert harness.models_for(one) == ["old-model"]   # no wait
    assert asked.wait(5)
    for _ in range(100):
        if harness.models_for(one) == ["new-model"]:
            break
        threading.Event().wait(0.02)
    assert harness.models_for(one) == ["new-model"]
