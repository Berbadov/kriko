"""A permit that is never released must not hold a search forever.

`network.urlopen` took its host permit with no timeout, and a permit with no
timeout waits in a loop until one is free (`agentresources._Limiter.acquire`).
A leaked permit, or a burst of reads against one host, therefore left every
later request for that host waiting with nothing said — the search never
answered, and never failed either, which is the worst of the two for a turn
that is holding a job open.
"""

import threading
import time

import pytest

from app import agentresources
from app.providers import network, websearch
from kriko.research.politeness import LocalSearchError


def _hold(kind: str, key: str, held: threading.Event, release: threading.Event):
    def holder():
        with agentresources.slot(kind, key):
            held.set()
            release.wait(5)
    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    assert held.wait(2), "the permit holder never got its slot"
    return thread


def test_a_network_permit_that_is_never_released_gives_up_and_says_why(monkeypatch):
    monkeypatch.setenv("KRIKO_MAX_OUTBOUND", "1")
    monkeypatch.setenv("KRIKO_MAX_PER_SOURCE", "1")
    monkeypatch.setattr(network, "PERMIT_WAIT", 0.3)
    held, release = threading.Event(), threading.Event()
    _hold("outbound", "busy.test", held, release)
    began = time.monotonic()
    try:
        with pytest.raises(TimeoutError) as caught:
            network.urlopen("http://busy.test/x", timeout=30.0)
    finally:
        release.set()

    assert time.monotonic() - began < 2.0
    said = str(caught.value)
    assert "outbound" in said and "busy.test" in said
    assert "permit" in said, "the reason names what it waited for"


def test_the_permit_wait_is_inside_the_requests_own_budget(monkeypatch):
    """A caller that gave a request 0.4 s does not wait 30 s for a slot."""
    monkeypatch.setenv("KRIKO_MAX_OUTBOUND", "1")
    monkeypatch.setenv("KRIKO_MAX_PER_SOURCE", "1")
    held, release = threading.Event(), threading.Event()
    _hold("outbound", "busy.test", held, release)
    began = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            network.urlopen("http://busy.test/x", timeout=0.4)
    finally:
        release.set()
    assert time.monotonic() - began < 1.5


def test_a_search_over_a_held_permit_reports_it_instead_of_hanging(monkeypatch):
    monkeypatch.setenv("KRIKO_MAX_OUTBOUND", "1")
    monkeypatch.setenv("KRIKO_MAX_PER_SOURCE", "1")
    monkeypatch.setattr(network, "PERMIT_WAIT", 0.2)
    held, release = threading.Event(), threading.Event()
    _hold("outbound", "forum.test", held, release)
    said: list[str] = []

    def blocked(query, limit=5, **_options):
        network.urlopen("http://forum.test/search", timeout=5.0)
        return [{"url": "https://forum.test/1", "title": "never reached"}]

    chain = websearch.Chain([("openserp", lambda: blocked)], log=said.append)
    began = time.monotonic()
    try:
        with pytest.raises(LocalSearchError) as caught:
            chain("owner reports", 5, timeout=3.0)
    finally:
        release.set()

    assert time.monotonic() - began < 2.0
    assert "permit" in str(caught.value)
    assert any("permit" in line for line in said)
