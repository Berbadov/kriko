"""Two keys, a file with the right mode, and nothing readable back.

The paid research plane needs an Exa key and an OpenAI-compatible key. Until
this landed the only way to supply them was to export a variable before
launching, which for a double-clicked desktop app is not a way at all. So there
is `~/.kriko/env` and a settings screen that writes it.

The three things these tests hold, in order of how badly each would fail:

1. **No response body contains a key.** Not the success body, not the error
   body, not a validation message. Tested by putting a distinctive string in
   and searching *every* response — including refusals — for it, because the
   leak that matters is in the message nobody reads.
2. **Mode 0600, from the moment the file exists.** The write is atomic and the
   mode is set on the temporary file before the content goes in: a key that is
   world-readable for one syscall has already been read.
3. **An exported variable wins, and says so.** `load` never overwrites, so a
   reader running from a shell keeps their shell's key — and a reader who
   cannot see *that* would paste into Settings repeatedly and watch nothing
   change.

**No test here needs an API key.** That is the spec's rule and it is what keeps
this suite runnable: every provider adapter takes its callables injected, so
there is nothing to reach and nothing to spend.
"""

import os
import stat
import sys

import pytest
from fastapi.testclient import TestClient

from app import keys
from app.web.app import create_app
from app.web.settings import Settings

#: Distinctive enough that finding it in a response body cannot be a
#: coincidence, and shaped like the real thing so a masking bug that only
#: triggers on long values is still caught.
FIXTURE = "sk-test-DO-NOT-LEAK-0123456789abcdef4f2a"


def _client(tmp_path):
    return TestClient(
        create_app(
            Settings(
                store_path=tmp_path / "knowledge.sqlite",
                app_state_path=tmp_path / "app.sqlite",
                analysis_log_path=tmp_path / "analyses.jsonl",
            )
        )
    )


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """No provider variable leaks in from the developer's own shell.

    Without this, a machine with `EXA_API_KEY` exported would report every
    provider present and the presence tests would pass for the wrong reason.
    """
    for provider in keys.PROVIDERS:
        monkeypatch.delenv(provider.env, raising=False)
    yield


# ── the file ─────────────────────────────────────────────────────────────


def test_the_env_file_is_readable_only_by_its_owner(tmp_path):
    """0600, because the threat this has is another account on the machine.

    Not the keychain: that would cost a dependency plus a Linux fallback, and
    the file sits beside a store that is already readable by anything running
    as this user. Mode bits stop the other account and claim nothing more.
    """
    path = tmp_path / "env"
    keys.save({"exa": FIXTURE}, path)
    mode = stat.S_IMODE(path.stat().st_mode)
    if sys.platform == "win32":
        pytest.skip("no POSIX mode bits to assert")
    assert mode == 0o600, f"the key file is mode {mode:o}"


def test_a_blank_value_does_not_erase_a_stored_key(tmp_path):
    """The screen cannot show a key, so a form cannot round-trip one.

    A save that treated every empty field as "clear this" would wipe the key
    the reader never touched every time they set the other one.
    """
    path = tmp_path / "env"
    keys.save({"exa": FIXTURE}, path)
    keys.save({"openai": "other-key", "exa": ""}, path)
    assert keys.parse(path.read_text())["EXA_API_KEY"] == FIXTURE


def test_the_file_is_parsed_the_way_every_other_tool_parses_one(tmp_path):
    """Comments, blanks, `export ` and quotes — and one bad line costs nothing.

    People paste this file from somewhere else. Raising on a stray line would
    lose the good key that followed it.
    """
    path = tmp_path / "env"
    path.write_text(
        "# a comment\n"
        "\n"
        'export EXA_API_KEY="quoted"\n'
        "not-an-assignment\n"
        "OPENAI_API_KEY = spaced \n"
    )
    parsed = keys.parse(path.read_text())
    assert parsed["EXA_API_KEY"] == "quoted"
    assert parsed["OPENAI_API_KEY"] == "spaced"


def test_an_exported_variable_wins_and_is_reported_as_the_source(tmp_path, monkeypatch):
    """`load` never overwrites, and `status` says which one is in force.

    The failure this prevents is silent: a reader with `EXA_API_KEY` in their
    shell pastes a new key in Settings, the file changes, the run keeps using
    the old one, and nothing on screen explains it.
    """
    path = tmp_path / "env"
    keys.save({"exa": FIXTURE}, path)
    monkeypatch.setenv("EXA_API_KEY", "from-the-shell")
    assert keys.load(path) == []  # nothing set: the variable was already there
    exa = next(item for item in keys.status(path) if item["id"] == "exa")
    assert exa["source"] == "environment"
    assert exa["hint"] == "…hell"


def test_a_stored_key_reports_the_file_as_its_source(tmp_path, monkeypatch):
    """After `load` the file's key *is* the environment variable.

    Calling that "environment" would hide the file the reader just edited, so
    `status` compares the two rather than asking only whether a variable is set.
    """
    path = tmp_path / "env"
    keys.save({"exa": FIXTURE}, path)
    keys.load(path)
    monkeypatch.setenv("EXA_API_KEY", FIXTURE)
    exa = next(item for item in keys.status(path) if item["id"] == "exa")
    assert exa["source"] == "file"


def test_the_paid_plane_is_not_ready_on_one_key(tmp_path):
    """Both, not either: the plane searches *and* reads.

    Half-configured is not a degraded mode — it is a run that fails on its
    first document — so the API card stays inert until both are there.
    """
    path = tmp_path / "env"
    keys.save({"exa": FIXTURE}, path)
    assert keys.ready(path) is False
    keys.save({"openai": FIXTURE}, path)
    assert keys.ready(path) is True


def test_asking_for_a_key_that_is_not_set_refuses_rather_than_returning_blank(
    tmp_path, monkeypatch
):
    """`MissingKey`, so the answer is a screen instead of a vendor's 401."""
    from app.providers import MissingKey

    monkeypatch.setattr(keys, "env_path", lambda home=None: tmp_path / "env")
    with pytest.raises(MissingKey) as raised:
        keys.require("openai")
    assert "Settings" in str(raised.value)


def test_the_hint_is_four_characters_and_a_short_key_is_not_truncated():
    """Enough to tell two keys apart, not enough to be worth capturing."""
    assert keys.hint(FIXTURE) == "…4f2a"
    assert keys.hint("short") == "•••••"
    assert keys.hint("") == ""


# ── the endpoint ─────────────────────────────────────────────────────────


def test_the_keys_endpoint_never_returns_a_key(tmp_path):
    """Every response from the router, success and failure, searched for it.

    This is the load-bearing test of the whole feature. A settings screen that
    can read a key back is a screen that can leak one into a screenshot, a
    browser history or a support log — and there is no feature that needs it.
    """
    client = _client(tmp_path)
    responses = [
        client.put("/api/keys", json={"values": {"exa": FIXTURE}}),
        client.get("/api/keys"),
        # The error paths, which is where a message would quote its input.
        client.put("/api/keys", json={"values": {"nonsense": FIXTURE}}),
        client.put("/api/keys", json={"values": {"exa": ""}}),
        client.delete("/api/keys/nonsense"),
        client.delete("/api/keys/exa"),
    ]
    for response in responses:
        assert FIXTURE not in response.text, (
            f"{response.request.method} {response.request.url.path} "
            f"({response.status_code}) put a key in its body"
        )


def test_saving_a_key_makes_it_present_with_a_hint(tmp_path):
    client = _client(tmp_path)
    client.put("/api/keys", json={"values": {"exa": FIXTURE}})
    body = client.get("/api/keys").json()
    exa = next(item for item in body["providers"] if item["id"] == "exa")
    assert exa["present"] is True
    assert exa["hint"] == "…4f2a"
    assert body["ready"] is False  # openai still missing


def test_forgetting_a_key_removes_it_from_the_running_process_too(tmp_path):
    """A key removed in Settings that the next run still spends with is not removed."""
    client = _client(tmp_path)
    client.put("/api/keys", json={"values": {"exa": FIXTURE}})
    assert os.environ.get("EXA_API_KEY") == FIXTURE
    client.delete("/api/keys/exa")
    assert os.environ.get("EXA_API_KEY") is None
    body = client.get("/api/keys").json()
    assert all(not item["present"] for item in body["providers"])


def test_only_declared_providers_can_be_written(tmp_path):
    """The endpoint is not an arbitrary-environment-variable write.

    A caller that could put any `KEY=value` into a file this process later
    loads into its own environment would be a localhost-reachable way to set
    `PATH` or `LD_PRELOAD` for the next launch. Two named providers is the
    whole feature.
    """
    client = _client(tmp_path)
    refused = client.put("/api/keys", json={"values": {"LD_PRELOAD": "/tmp/x.so"}})
    assert refused.status_code == 400
    written = tmp_path / "env"
    assert not written.exists() or "LD_PRELOAD" not in written.read_text()


def test_each_provider_states_what_it_receives(tmp_path):
    """A promise about what leaves this machine, next to the thing that keeps it.

    The Check screen's "nothing sent anywhere" is true of the default plane and
    false of this one, so the screen that turns it on is where the difference
    has to be written down.
    """
    body = _client(tmp_path).get("/api/keys").json()
    for item in body["providers"]:
        assert item["purpose"].strip(), f"{item['id']} says nothing about its purpose"
        assert "Never" in item["purpose"], (
            f"{item['id']} says what it receives but not what it does not"
        )
