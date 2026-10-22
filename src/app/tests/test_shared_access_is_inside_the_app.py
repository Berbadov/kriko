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
"""

import json

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


def test_the_trial_gives_a_few_questions_and_then_says_what_to_do(where, monkeypatch):
    monkeypatch.setattr(sharekeys, "home", lambda: where)
    monkeypatch.setattr(sharekeys, "TRIAL_FILE", where / "trial_access.json")
    sharekeys.write_trial(sharekeys.make_trial({"mercury": MERCURY}), where=sharekeys.TRIAL_FILE)
    monkeypatch.delenv("MERCURY_API_KEY", raising=False)

    assert sharekeys.allowance(where)["left"] == sharekeys.TRIAL_QUESTIONS
    assert keys.require("mercury") == MERCURY
    assert keys.origin("mercury") == "trial"

    for _ in range(sharekeys.TRIAL_QUESTIONS):
        sharekeys.charge(where)
    assert sharekeys.allowance(where)["left"] == 0
    with pytest.raises(Exception, match="trial for this computer is used up"):
        keys.require("mercury")
    assert "add your own Mercury and DeepSeek keys" in sharekeys.refusal("mercury", where=where)


def test_a_question_on_the_trial_is_counted_before_the_model_is_asked(where, monkeypatch):
    """Kriko Agent charges one question per turn, whatever the turn then does."""
    from app.providers import kriko_agent

    monkeypatch.setattr(sharekeys, "home", lambda: where)
    monkeypatch.setattr(sharekeys, "TRIAL_FILE", where / "trial_access.json")
    sharekeys.write_trial(
        sharekeys.make_trial({"mercury": MERCURY, "deepseek": DEEPSEEK}),
        where=sharekeys.TRIAL_FILE)
    monkeypatch.delenv("MERCURY_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(kriko_agent.keys, "origin", lambda provider: "trial")
    monkeypatch.setattr(kriko_agent, "post_sse_or_why",
                        lambda *a, **k: (1, "Mercury is unreachable"))
    steps: list[str] = []

    reply = kriko_agent.converse("Research the Widget", on_step=steps.append)

    assert reply.error
    assert sharekeys.allowance(where)["used"] == 1
    assert any("free trial" in line for line in steps)


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
    assert opened.json()["status"]["grant"]["present"] is True
    assert MERCURY not in (other / "shared.json").read_text(encoding="utf-8")

    assert friend.get("/api/keys/shared/status").json()["grant"]["label"] == "Ada"
    assert friend.delete("/api/keys/shared").json()["grant"]["present"] is False
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
