"""Shared access: a password that works here and nowhere else.

The reader's words: *"i give them a password they paste it into settings and then
they can use kriko agent easily on my api keys ... so password should not work
outside of kriko app"*, and *"a few query allowance for the first timer unknown
people"*.

What these tests hold, in the order each would fail:

1. **A code and its password are one secret.** A wrong password opens nothing; a
   code changed by one character opens nothing; the keys are never written in
   the clear anywhere under the reader's folder.
2. **The build is what makes it app-bound.** A code sealed in a build with one
   pepper does not open in a build with another, so a password on its own —
   pasted into a script, a browser, anything that is not this app — is worth
   nothing.
3. **The trial is counted, and it ends.** One question, one count, and the
   refusal names what to do next instead of failing as a missing key.
4. **The whole friend path, with no real key anywhere.** Owner makes a code from
   a password, friend pastes it, both provider keys resolve from the grant, and a
   researched Kriko Agent turn runs on them; a trial bundle does the same with no
   password at all.
5. **A row means a question will be answered.** Kriko Agent researches with
   Mercury *and* DeepSeek, so it is listed only when both resolve — and a bundle
   this build's pepper cannot open is no trial, not a count of questions.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import keys, sharekeys
from app.web.app import create_app
from app.web.settings import Settings

MERCURY = "sk-mercury-DO-NOT-LEAK-0123456789abcdef"
DEEPSEEK = "sk-deepseek-DO-NOT-LEAK-0123456789abcdef"
PASSWORD = "correct horse battery"


@pytest.fixture
def where(tmp_path, monkeypatch):
    """A reader's own folder, with a pepper this build carries."""
    monkeypatch.setenv("KRIKO_SHARE_PEPPER", "a-build-pepper-for-tests")
    return tmp_path


@pytest.fixture
def borrowed_keys(where, monkeypatch):
    """A machine whose only keys are the ones shared access opened.

    Without this the suite asks the machine running it: a developer with
    Mercury and DeepSeek saved in `~/.kriko/env` would make an agent look
    available for reasons the test is not about, and one with a grant of their
    own would do the same. Everything the trial needs is under `where`.
    """
    monkeypatch.setattr(keys, "env_path", lambda home=None: where / "env")
    monkeypatch.setattr(sharekeys, "home", lambda: where)
    monkeypatch.delenv("MERCURY_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    return where


def _full_trial(where, monkeypatch, questions: int = sharekeys.TRIAL_QUESTIONS):
    """Bake the trial `tools/make_trial_access.py` bakes: the whole agent stack."""
    monkeypatch.setattr(sharekeys, "TRIAL_FILE", where / "trial_access.json")
    sharekeys.write_trial(
        sharekeys.make_trial({"mercury": MERCURY, "deepseek": DEEPSEEK},
                             questions=questions),
        where=sharekeys.TRIAL_FILE)
    return sharekeys.TRIAL_FILE


def _code(**over):
    return sharekeys.make_access(PASSWORD, {"mercury": MERCURY, "deepseek": DEEPSEEK, **over})


def test_a_code_and_its_password_are_one_secret(where):
    code = _code()

    assert sharekeys.open_access(code, PASSWORD) == {"mercury": MERCURY, "deepseek": DEEPSEEK}
    with pytest.raises(sharekeys.ShareError, match="password is not the one"):
        sharekeys.open_access(code, PASSWORD + "!")
    with pytest.raises(sharekeys.ShareError, match="not look like an access code"):
        sharekeys.open_access("not-a-code", PASSWORD)
    damaged = code[:-2] + ("aa" if not code.endswith("aa") else "bb")
    with pytest.raises(sharekeys.ShareError):
        sharekeys.open_access(damaged, PASSWORD)


def test_a_short_password_is_refused_before_anything_is_sealed(where):
    with pytest.raises(sharekeys.ShareError, match="at least 8 characters"):
        sharekeys.make_access("short", {"mercury": MERCURY})


def test_the_build_is_what_makes_the_password_app_bound(where, monkeypatch):
    code = _code()

    monkeypatch.setenv("KRIKO_SHARE_PEPPER", "a-different-build-pepper")
    with pytest.raises(sharekeys.ShareError, match="password is not the one"):
        sharekeys.open_access(code, PASSWORD)


def test_a_build_with_no_pepper_says_so(where, monkeypatch):
    monkeypatch.delenv("KRIKO_SHARE_PEPPER", raising=False)
    monkeypatch.setattr(sharekeys, "_baked_pepper", lambda: "")

    assert sharekeys.bound() is False
    assert sharekeys.status(where)["bound"] is False


def test_an_unlocked_grant_is_kept_sealed_and_never_in_the_clear(where):
    sharekeys.unlock(_code(), PASSWORD, label="Ada", where=where)

    stored = (where / "shared.json").read_text(encoding="utf-8")
    assert MERCURY not in stored and DEEPSEEK not in stored
    assert "sealed" in json.loads(stored)["grant"]
    assert sharekeys.granted("mercury", where=where) == MERCURY
    assert sharekeys.origin("mercury", where=where) == "shared"
    assert sharekeys.status(where)["grant"] == {
        "present": True, "label": "Ada", "providers": ["deepseek", "mercury"],
        "state": "shared"}


def test_a_folder_copied_to_another_machine_cannot_open_the_grant(where):
    sharekeys.unlock(_code(), PASSWORD, where=where)
    copied = where / "copied"
    copied.mkdir()
    # The grant travelled; the device key it was sealed under did not.
    (copied / "shared.json").write_text((where / "shared.json").read_text(encoding="utf-8"),
                                        encoding="utf-8")

    assert sharekeys.granted("mercury", where=copied) == ""
    assert "paste" in sharekeys.refusal("mercury", where=copied).casefold()


def test_forgetting_a_grant_leaves_no_keys_behind(where):
    sharekeys.unlock(_code(), PASSWORD, where=where)
    sharekeys.forget(where)

    assert sharekeys.granted("mercury", where=where) == ""
    assert sharekeys.status(where)["grant"]["present"] is False


def test_the_key_resolver_falls_back_to_a_shared_grant(where, monkeypatch):
    monkeypatch.setattr(sharekeys, "home", lambda: where)
    monkeypatch.delenv("MERCURY_API_KEY", raising=False)
    sharekeys.unlock(_code(), PASSWORD, where=where)

    assert keys.require("mercury") == MERCURY
    assert keys.origin("mercury") == "shared"
    # The reader's own key still wins over the one they were given.
    monkeypatch.setenv("MERCURY_API_KEY", "own-key")
    assert keys.require("mercury") == "own-key"
    assert keys.origin("mercury") == "environment"


def test_a_shared_grant_in_a_custom_app_home_is_discovered_and_used(
        where, monkeypatch):
    """Unlock, picker readiness, and provider execution share one app home."""
    from app import prefs
    from app.providers import apiagent, harness_researcher, kriko_agent
    from app.providers.kriko_agent_cache import RetrievalCache
    from app.web import state

    friend = where / "friend-home"
    friend.mkdir()
    app_state_path = friend / "app.sqlite"
    default_home = where / "different-default-home"
    monkeypatch.setattr(keys, "env_path", lambda home=None: (home or default_home) / "env")
    monkeypatch.delenv("MERCURY_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(
        kriko_agent, "RetrievalCache", lambda _path=None: RetrievalCache(where / "cache.sqlite3"),
    )

    client = TestClient(create_app(Settings(
        store_path=friend / "knowledge.sqlite",
        app_state_path=app_state_path,
        analysis_log_path=friend / "analyses.jsonl",
    )))
    opened = client.post("/api/keys/shared/unlock", json={
        "code": _code(), "password": PASSWORD, "label": "Friend",
    })
    assert opened.status_code == 200, opened.text
    assert "MERCURY_API_KEY" not in os.environ
    assert "DEEPSEEK_API_KEY" not in os.environ
    # Both halves of the stack come out of the grant, and the screen, the
    # picker and the researched turn below all ask this one resolver.
    assert keys.require("mercury", shared_home=friend) == MERCURY
    assert keys.require("deepseek", shared_home=friend) == DEEPSEEK
    assert keys.origin("mercury", shared_home=friend) == "shared"

    assert apiagent.KRIKO_AGENT in apiagent.available(shared_home=friend)
    conn = state.connect(app_state_path)
    try:
        ready, _missing = prefs.api_agent_rows(conn)
    finally:
        conn.close()
    assert any(one["id"] == apiagent.KRIKO_AGENT.id for one in ready)
    researcher = harness_researcher(
        preferred=apiagent.KRIKO_AGENT.id, app_state_path=app_state_path)
    assert researcher.agent.id == apiagent.KRIKO_AGENT.id

    model_turns = []
    search_headers = []

    def stream(url, payload, headers, _timeout, on_event, **_kwargs):
        if not url.endswith("/chat/completions"):
            return 0, "unexpected endpoint"
        assert headers["authorization"] == f"Bearer {MERCURY}"
        assert payload["model"] == kriko_agent.MODEL
        model_turns.append(payload)
        assert payload["tool_choice"] == ("required" if len(model_turns) == 1 else "auto")
        if len(model_turns) == 1:
            on_event({"choices": [{
                "delta": {"tool_calls": [{
                    "index": 0, "id": "search-1", "type": "function",
                    "function": {"name": "search", "arguments":
                                  json.dumps({"query": "Widget official specs"})},
                }]}, "finish_reason": "tool_calls",
            }]})
            return 1, ""
        assert "The Widget has a 1 TB drive." in " ".join(
            str(message.get("content") or "") for message in payload["messages"]
            if message.get("role") == "tool")
        on_event({"choices": [{
            "delta": {"content": "The supplied specification says the Widget has a 1 TB drive."},
            "finish_reason": "stop",
        }]})
        return 1, ""

    def search(url, payload, headers, _timeout):
        assert url.endswith("/tools/search")
        search_headers.append(headers)
        return {"results": [{
            "url": "https://maker.example/widget",
            "title": "Widget specifications",
            "content": "The Widget has a 1 TB drive.",
        }]}, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    monkeypatch.setattr(kriko_agent, "post_json_or_why", search)
    reply_text = researcher.ask("Research the Widget", allow_tools=True)

    assert reply_text == "The supplied specification says the Widget has a 1 TB drive."
    assert researcher.retrieval_requests == 1
    assert researcher.sources["https://maker.example/widget"] == "The Widget has a 1 TB drive."
    assert search_headers == [{"authorization": f"Bearer {DEEPSEEK}"}]


def test_the_trial_gives_a_few_questions_and_then_says_what_to_do(
        where, borrowed_keys, monkeypatch):
    _full_trial(where, monkeypatch)

    assert sharekeys.allowance(where)["left"] == sharekeys.TRIAL_QUESTIONS
    # Both halves of the one stack the trial exists for: Mercury writes the
    # answer and DeepSeek retrieves the evidence it quotes.
    assert keys.require("mercury") == MERCURY
    assert keys.require("deepseek") == DEEPSEEK
    assert keys.origin("mercury") == keys.origin("deepseek") == "trial"

    for _ in range(sharekeys.TRIAL_QUESTIONS):
        sharekeys.charge(where)
    assert sharekeys.allowance(where)["left"] == 0
    with pytest.raises(Exception, match="trial for this computer is used up"):
        keys.require("mercury")
    assert "add your own Mercury and DeepSeek keys" in sharekeys.refusal("mercury", where=where)


def test_a_trial_bundle_this_build_cannot_open_is_no_trial(
        where, borrowed_keys, monkeypatch):
    """A bundle from another pepper is not counted, and not spent.

    Otherwise the screen draws "10 questions left" from a bundle nobody can
    open, which is a count the engine did not report.
    """
    _full_trial(where, monkeypatch, questions=7)
    assert sharekeys.allowance(where)["left"] == 7
    assert sharekeys.allowance(where)["available"] is True

    monkeypatch.setenv("KRIKO_SHARE_PEPPER", "a-different-build-pepper")

    assert sharekeys.trial_keys() == {}
    assert sharekeys.allowance(where)["available"] is False
    assert sharekeys.granted("mercury", where=where) == ""
    assert sharekeys.origin("mercury", where=where) == ""
    with pytest.raises(Exception, match="Mercury needs a key"):
        keys.require("mercury")


def test_a_trial_is_never_baked_without_a_pepper(where, monkeypatch):
    """`_pepper_key` has a constant fallback, so an unbound bundle opens in any
    build without a pepper. Nothing may seal one."""
    monkeypatch.delenv("KRIKO_SHARE_PEPPER", raising=False)
    monkeypatch.setattr(sharekeys, "_baked_pepper", lambda: "")

    with pytest.raises(sharekeys.ShareError, match="no share pepper"):
        sharekeys.make_trial({"mercury": MERCURY, "deepseek": DEEPSEEK})


def test_kriko_agent_is_offered_only_with_the_key_its_researched_turn_needs(
        where, borrowed_keys, monkeypatch):
    """A row is a promise that the reader's question will be answered.

    Kriko Agent researches with Mercury *and* DeepSeek, so a trial carrying only
    the planning key is not offered: the row would be drawn and then refuse the
    searched answer. The shipped tool bakes both, and this is the rule that
    keeps a half-written bundle from reaching a friend's screen.
    """
    from app.providers import apiagent

    monkeypatch.setattr(sharekeys, "TRIAL_FILE", where / "trial_access.json")
    sharekeys.write_trial(sharekeys.make_trial({"mercury": MERCURY}, questions=1),
                          where=sharekeys.TRIAL_FILE)
    # The planning key is there; the retrieval key is not.
    assert sharekeys.granted("mercury", where=where) == MERCURY
    assert apiagent.KRIKO_AGENT not in apiagent.available(
        trial_reservation_id="question-1")

    _full_trial(where, monkeypatch, questions=1)
    assert apiagent.KRIKO_AGENT in apiagent.available(trial_reservation_id="question-1")


def test_a_question_on_the_trial_is_counted_before_the_model_is_asked(
        where, borrowed_keys, monkeypatch):
    """Kriko Agent charges one question per turn, whatever the turn then does."""
    from app.providers import kriko_agent

    _full_trial(where, monkeypatch, questions=3)
    monkeypatch.setattr(kriko_agent.keys, "origin", lambda provider, **_kw: "trial")
    monkeypatch.setattr(kriko_agent, "post_sse_or_why",
                        lambda *a, **k: (1, "Mercury is unreachable"))
    steps: list[str] = []

    reply = kriko_agent.converse("Research the Widget", on_step=steps.append)

    assert reply.error
    assert sharekeys.allowance(where)["used"] == 1
    assert any("free trial" in line for line in steps)


def test_one_trial_question_can_make_several_model_calls_and_finish_the_last(
        where, borrowed_keys, monkeypatch):
    """One reader question, several model calls, one counted trial question.

    The bundle carries the whole stack, as `tools/make_trial_access.py` bakes
    it: the clarification call needs Mercury, and the researched answer needs
    DeepSeek Search as well. One reservation covers both, is charged once, and
    is still open for the last call after the count reached its limit.
    """
    from app.providers import apiagent, harness_researcher, kriko_agent
    from app.providers.kriko_agent_cache import RetrievalCache

    _full_trial(where, monkeypatch, questions=1)
    monkeypatch.setattr(
        kriko_agent, "RetrievalCache",
        lambda _path=None: RetrievalCache(where / "cache.sqlite3"))
    turns: list[dict] = []
    searches: list[dict] = []

    def stream(_url, payload, _headers, _timeout, on_event, **_kwargs):
        turns.append(payload)
        if len(turns) == 1:  # the tool-less clarification
            on_event({"choices": [{
                "delta": {"content": "It is the Widget."}, "finish_reason": "stop"}]})
            return 1, ""
        if len(turns) == 2:  # the researched turn asks for a search
            on_event({"choices": [{
                "delta": {"tool_calls": [{
                    "index": 0, "id": "search-1", "type": "function",
                    "function": {"name": "search", "arguments": json.dumps(
                        {"query": "Widget specifications"})}}]},
                "finish_reason": "tool_calls"}]})
            return 1, ""
        on_event({"choices": [{
            "delta": {"content": "The searched answer."}, "finish_reason": "stop"}]})
        return 1, ""

    def search(url, _payload, headers, _timeout):
        assert url.endswith("/tools/search")
        searches.append(headers)
        return {"results": [{
            "url": "https://maker.example/widget",
            "title": "Widget specifications",
            "content": "The Widget has a 1 TB drive.",
        }]}, ""

    monkeypatch.setattr(kriko_agent, "post_sse_or_why", stream)
    monkeypatch.setattr(kriko_agent, "post_json_or_why", search)

    assert apiagent.KRIKO_AGENT in apiagent.available(trial_reservation_id="question-1")
    researcher = harness_researcher(preferred=apiagent.KRIKO_AGENT.id,
                                    trial_reservation_id="question-1")
    assert researcher.trial_reservation_id == "question-1"

    first = researcher.ask("Clarify the product", allow_tools=False)
    assert first == "It is the Widget."
    # The question is spent now, and the answer being written is not refused for
    # it: the reservation keeps the trial open to the reader's last call.
    assert sharekeys.allowance(where)["used"] == 1
    assert apiagent.KRIKO_AGENT in apiagent.available(trial_reservation_id="question-1")

    second = researcher.ask("Research the Widget")
    assert second == "The searched answer."
    assert researcher.retrieval_requests == 1
    assert searches == [{"authorization": f"Bearer {DEEPSEEK}"}]
    assert sharekeys.allowance(where)["used"] == 1

    refused = kriko_agent.converse(
        "A new user question", search=False, trial_reservation_id="question-2")
    assert "trial for this computer is used up" in refused.error
    assert len(turns) == 3


def test_concurrent_trial_reservations_are_idempotent_and_do_not_lose_counts(
        where, monkeypatch):
    monkeypatch.setattr(sharekeys, "TRIAL_FILE", where / "trial_access.json")
    sharekeys.write_trial(
        sharekeys.make_trial({"mercury": MERCURY, "deepseek": DEEPSEEK}, questions=2),
        where=sharekeys.TRIAL_FILE)

    def reserve(reservation_id):
        try:
            sharekeys.charge(where, reservation_id=reservation_id)
            return reservation_id
        except sharekeys.ShareError:
            return ""

    with ThreadPoolExecutor(max_workers=12) as pool:
        accepted = list(pool.map(reserve, (f"question-{i}" for i in range(40))))
    accepted_ids = [reservation_id for reservation_id in accepted if reservation_id]
    assert len(accepted_ids) == 2
    assert sharekeys.allowance(where)["used"] == 2

    with ThreadPoolExecutor(max_workers=12) as pool:
        left = list(pool.map(lambda _i: sharekeys.charge(
            where, reservation_id=accepted_ids[0]), range(40)))
    assert left == [0] * 40
    assert sharekeys.allowance(where)["used"] == 2


# ── the door ────────────────────────────────────────────────────────────


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("KRIKO_SHARE_PEPPER", "a-build-pepper-for-tests")
    return TestClient(
        create_app(
            Settings(
                store_path=tmp_path / "knowledge.sqlite",
                app_state_path=tmp_path / "app.sqlite",
                analysis_log_path=tmp_path / "analyses.jsonl",
            )
        )
    )


def test_the_endpoints_never_return_a_key(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.put("/api/keys", json={"values": {"mercury": MERCURY, "deepseek": DEEPSEEK}})

    made = client.post("/api/keys/shared/make", json={"password": PASSWORD})
    assert made.status_code == 200 and made.json()["code"]
    assert MERCURY not in made.text and DEEPSEEK not in made.text
    assert PASSWORD not in made.text

    # A second installation, given the code and the password.
    other = tmp_path / "friend"
    other.mkdir()
    friend = TestClient(
        create_app(Settings(store_path=other / "knowledge.sqlite",
                            app_state_path=other / "app.sqlite",
                            analysis_log_path=other / "analyses.jsonl")))
    opened = friend.post("/api/keys/shared/unlock",
                         json={"code": made.json()["code"], "password": PASSWORD, "label": "Ada"})
    assert opened.status_code == 200, opened.text
    assert MERCURY not in opened.text and DEEPSEEK not in opened.text
    assert PASSWORD not in opened.text
    assert opened.json()["status"]["grant"]["present"] is True
    assert MERCURY not in (other / "shared.json").read_text(encoding="utf-8")

    # Every reply the shared-access screen reads, searched for the whole secret.
    status = friend.get("/api/keys/shared/status")
    forgotten = friend.delete("/api/keys/shared")
    listing = friend.get("/api/keys")
    assert status.json()["grant"]["label"] == "Ada"
    for reply in (status, forgotten, listing):
        assert MERCURY not in reply.text and DEEPSEEK not in reply.text
        assert PASSWORD not in reply.text
        assert made.json()["code"] not in reply.text

    assert friend.get("/api/keys/shared/status").json()["grant"]["present"] is False
    assert friend.get("/api/keys").json()["providers"]


def test_a_wrong_password_is_a_sentence_not_a_500(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.put("/api/keys", json={"values": {"mercury": MERCURY, "deepseek": DEEPSEEK}})
    code = client.post("/api/keys/shared/make", json={"password": PASSWORD}).json()["code"]

    refused = client.post("/api/keys/shared/unlock", json={"code": code, "password": "wrong-one"})
    assert refused.status_code == 422
    assert "password" in refused.json()["detail"]


def test_making_a_code_without_keys_says_which_key_is_missing(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    # The machine running the suite may have keys of its own; this is about what
    # the endpoint says when there are none. `keys.require` is the whole door.
    def refuse(provider):
        from app.providers import MissingKey

        raise MissingKey(f"{provider} needs a key — set one in Settings")

    monkeypatch.setattr(keys, "require", refuse)
    refused = client.post("/api/keys/shared/make", json={"password": PASSWORD})
    assert refused.status_code == 422
    assert "needs a key" in refused.json()["detail"]
