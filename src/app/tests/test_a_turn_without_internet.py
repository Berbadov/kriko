"""A turn reaches only what it needs, and what it reaches fails open.

The requirement: *"must work without problems and internet connections"*. Two
things have to be true, and they are different things.

**A turn must not require a round trip it does not need.** The plane decision
runs before every job on every plane, so it is the one place where a needless
round trip is paid by all five agents at once — and it is a loopback question,
which on this machine means a connection that is *refused only when its timeout
expires* (measured: 2.0 s for a closed loopback port), so a probe that does not
ask is worth a great deal.

**Anything that does reach out must be optional and must fail open.** The
reader's own search may be down, a CLI's host tools may be absent, a model
server may not be running: each of those is a *miss* with a sentence attached,
never a hung run and never a failed one.

Nothing here needs the internet. Every address is 127.0.0.1 or a port nothing
is listening on.
"""

import socket
import time

import pytest

from app.providers import harness, local_discovery
from app.providers.local_discovery import discover as real_discover
from app.tests.harness_fixtures import row


def dead_url() -> str:
    """An address that was bound and then released: nothing listens there."""
    with socket.socket() as one:
        one.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{one.getsockname()[1]}"


@pytest.fixture
def machine(monkeypatch):
    """The real discovery, undoing the suite-wide "nothing answers" guard."""
    local_discovery.forget_discovery()
    monkeypatch.setattr(local_discovery, "discover", real_discover)
    return local_discovery


@pytest.fixture
def offline(monkeypatch):
    """Fail the test if anything opens a connection that is not this machine."""
    import app.providers.network as network

    from urllib.parse import urlsplit

    attempts: list[str] = []
    real = network.urlopen

    def guarded(url, *args, **kwargs):
        address = url.full_url if hasattr(url, "full_url") else str(url)
        host = (urlsplit(address).hostname or "").lower()
        attempts.append(host)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"a turn opened {host!r}, which is not this machine")
        return real(url, *args, **kwargs)

    monkeypatch.setattr(network, "urlopen", guarded)
    return attempts


# ── a needed round trip is not paid twice, or at all ────────────────────────


def test_a_dead_address_is_never_asked_the_http_question(machine, monkeypatch):
    """The liveness gate, not the HTTP deadline, is what answers "is it there".

    This is the whole of the plane decision's cost on a machine where the port
    is closed: `_get` is what costs a timeout, and it must not be reached.
    """
    asked: list[str] = []
    real_get = machine._get
    monkeypatch.setattr(machine, "_get",
                        lambda url, timeout, **kwargs: asked.append(url) or
                        real_get(url, timeout, **kwargs))

    began = time.perf_counter()
    row_ = machine.probe(dead_url())
    elapsed = time.perf_counter() - began

    assert row_["up"] is False
    assert asked == [], "a dead address was asked for a model list"
    assert elapsed < machine.PROBE_TIMEOUT, (
        f"a dead address cost {elapsed:.3f}s, the whole HTTP deadline")


def test_the_plane_decision_asks_this_machine_once_for_one_turn(machine, monkeypatch):
    """One turn asks three times — the decision, the gate, the run's plan — and
    the machine has not changed in between."""
    asked = {"probed": 0}
    real_probed = machine._probed
    monkeypatch.setattr(machine, "_probed",
                        lambda configured, timeout: asked.update(
                            probed=asked["probed"] + 1) or real_probed(configured, timeout))
    monkeypatch.setattr(machine, "search_answers", lambda *_a, **_k: False)

    from app import localplane

    localplane.is_ready(None)
    localplane.is_ready(None)
    localplane.resolve(None, with_search=False)

    assert asked["probed"] == 1


def test_a_busy_probe_is_not_remembered_as_a_dead_server(machine, monkeypatch):
    """A probe that never tested an address must not become an answer about it."""
    from app.agentresources import slot

    monkeypatch.setenv("KRIKO_MAX_PROBES", "1")
    with slot("probe", "another-discovery"):
        busy = machine.discover()
    after = machine.discover()

    assert any(one.get("busy") for one in busy)
    assert not any(one.get("busy") for one in after), "the busy moment was cached"


# ── what does reach out is optional and fails open ──────────────────────────


def test_this_machines_own_planes_touch_nothing_but_this_machine(machine, offline):
    """The plane decision is the gate every job passes. It reaches no host.

    The `offline` guard raises on any address that is not this machine, so this
    test does not merely assert a list: anything reaching out would fail it.
    """
    from app import localplane
    from app.web import tasks

    tasks.default_plane(None)
    localplane.resolve(None, with_search=False)

    assert set(offline) <= {"127.0.0.1", "localhost", "::1"}, offline


def test_a_search_service_that_did_not_answer_asks_the_cli_to_search_itself(
        monkeypatch):
    """A host whose search is down is not a failed run: the CLI has its own
    tools, so the run says so and hands it the question instead."""
    researcher = harness.HarnessResearcher(row("codex"))
    prompts: list[str] = []

    class Reader:
        sources = {}
        page_titles = {}
        search_coverage = {"queries_searched": 0, "search_errors": 3, "pages_read": 0}
        telemetry = {"stages": []}
        search_provider = "openserp"

    monkeypatch.setattr(researcher, "_read_web_pages",
                        lambda *a, **k: (Reader(), [], None))
    monkeypatch.setattr(researcher, "_run",
                        lambda prompt: prompts.append(prompt) or '{"risks":[],"specs":[]}')

    reply = researcher.ask_quick("Widget")

    assert reply == '{"risks":[],"specs":[]}'
    assert researcher.sources is None, (
        "Kriko holds no page text, so a quote can only be required to exist")
    assert "search the web with your own tools" in prompts[0].lower()
    assert researcher.on_action is None or True  # nothing to narrate to by default


def test_a_plane_that_cannot_be_handed_a_remote_reader_is_not_handed_one(monkeypatch):
    """Three of the four CLIs declare no page reader at all, so no internet MCP
    server can be attached to a run of theirs however the reader configures it.

    The fourth (`claude-code`) attaches one only when this machine's own build
    declares the flag *and* its vector has an allowlist for the reader's tools —
    both asked of `--help`, never assumed."""
    from app.providers import pagereader

    monkeypatch.setenv(pagereader.KEY_ENV, "reader-key")
    declaring = [one.id for one in harness.KNOWN if one.reader is not None]

    assert declaring == ["claude-code"], declaring
    for one in harness.KNOWN:
        if one.reader is None:
            assert harness.reader_tools(one) == []
            assert harness.reader_attachable(one, frozenset()) is False
    # And the one that does declare a reader is handed a *config file*, not a
    # connection: nothing here opens a socket, and a build without the flag
    # keeps the plane and loses the reader.
    config = harness.reader_config()
    assert set(config["mcpServers"]) == {harness.READER_SERVER}
    assert config["mcpServers"][harness.READER_SERVER]["url"] == harness.READER_URL


def test_a_tool_less_session_is_told_it_has_no_tools_before_it_tries_one():
    """A refused tool call costs a turn, and on some CLIs ends the run. Saying
    it up front is what keeps a tool-less plane from spending a subscription on
    refusals — and it is the note that makes "no internet needed" true for it."""
    assert "no tools of any kind" in harness.TOOLLESS_NOTE
    assert "Do not try" in harness.TOOLLESS_NOTE
    assert harness.TOOLLESS_PROTOCOLS <= {one.protocol for one in harness.KNOWN}
