"""The evidence gate on both doors: a sourced claim must match its own source.

`app.categorypack.ground` is where a claim with a quote and a url is accepted,
and both doors reach it — an agent's "Add to a pack" and a job's harvest through
`_file_quick_look`, and a research run through `accept_findings`. So the gate is
wired there, once, and these tests prove the wiring rather than the rule: the
rule has its own tests in `app/tests/test_the_nli_evidence_gate.py`.

Every test here uses a fake verifier. No model is downloaded, and none of this
needs the optional `nli` extra.
"""

from pathlib import Path
import sys

import pytest
import yaml

from app import categorypack
from app.findings import accept_findings
from app.nli_gate import NliGate
from app.tests.test_category_packs import (
    V8_PAGE,
    V8_QUOTE,
    _check,
    _script_v8,
)
from app.tests.test_category_packs import world as _category_world
from kriko.store.db import connect

world = _category_world

TITLE = "Scyrox V8 Gaming Mouse"
#: What the page says, and what a claim that restates it looks like. The quoted
#: sentence is the real one either way: the gate asks what it *means*.
RESTATES = "Scroll wheel wears"
REFUTES = "Scroll wheel never skips, at any age"
UNRELATED = "The cable frays where it meets the shell"


class FakeVerifier:
    """Entailment when the claim restates the quote, contradiction when it says
    the opposite, neutral otherwise. Decided from the words, so the test says
    which verdict it is exercising by writing the claim."""

    name = "fake-nli"

    def verify(self, premise, hypothesis):
        premise, hypothesis = premise.casefold(), hypothesis.casefold()
        if "never skips" in hypothesis:
            return "contradiction", 0.97
        if "wheel" in hypothesis and "wheel" in premise:
            return "entailment", 0.96
        return "neutral", 0.88


def _item(title: str) -> dict:
    return {"title": title, "body": title,
            "evidence": [{"url": V8_PAGE, "quote": V8_QUOTE}]}


class Fetched:
    """The reader's answer: the page's text, which `ground` widens the quote in."""

    def __init__(self, text: str) -> None:
        self.text = text


@pytest.fixture
def page():
    # The quote, in a sentence that says what it says: the widened premise.
    return Fetched(f"The review found that {V8_QUOTE}. Nothing else was measured.")


# ── ground: the one place a sourced claim is accepted ────────────────────

def test_a_claim_its_source_restates_enters(page):
    kept, dropped = categorypack.ground([_item(RESTATES)], lambda _: page,
                                        nli=NliGate(FakeVerifier()))
    assert [one["title"] for one in kept] == [RESTATES]
    assert dropped == []
    assert kept[0]["nli"]["verdict"] == "entailment"
    assert kept[0]["nli"]["verifier"] == "fake-nli"


def test_a_claim_its_source_refutes_is_dropped(page):
    kept, dropped = categorypack.ground([_item(REFUTES)], lambda _: page,
                                        nli=NliGate(FakeVerifier()))
    assert kept == []
    assert [one["title"] for one in dropped] == [REFUTES]
    assert dropped[0]["reason"].startswith("nli: ")


def test_a_claim_its_source_never_mentions_is_held_out(page):
    kept, dropped = categorypack.ground([_item(UNRELATED)], lambda _: page,
                                        nli=NliGate(FakeVerifier()))
    assert kept == []
    assert [one["title"] for one in dropped] == [UNRELATED]
    assert "does not clearly support" in dropped[0]["reason"]


def test_a_held_claim_keeps_the_evidence_it_failed_on(page):
    """So an automated retry can re-source it without fetching the page again."""
    _, dropped = categorypack.ground([_item(UNRELATED)], lambda _: page,
                                     nli=NliGate(FakeVerifier()))
    assert dropped[0]["evidence"][0]["quote"] == V8_QUOTE
    assert dropped[0]["nli"]["verdict"] == "neutral"


def test_with_no_gate_every_sourced_claim_passes_unchanged(page):
    """Fail open: the desktop installer has no model, and must lose nothing."""
    kept, dropped = categorypack.ground(
        [_item(RESTATES), _item(REFUTES), _item(UNRELATED)], lambda _: page)
    assert len(kept) == 3
    assert dropped == []
    assert all("nli" not in one for one in kept)


def test_the_verdict_travels_into_the_claim_as_provenance(page):
    """Stored on the evidence entry, which the engine schema leaves free-form —
    so a machine with a model and one without write the same `content_digest`
    shape, and a verdict is never a schema change."""
    row = categorypack._claim_row(
        {"kind": "product", "identity": {}},
        {**_item(RESTATES), "nli": {"verdict": "entailment", "score": 0.96,
                                    "decision": "accept", "verifier": "fake-nli"}},
        "general")
    assert row["evidence"][0]["nli"]["verdict"] == "entailment"
    assert row["evidence"][0]["quote"] == V8_QUOTE


# ── the job path: an agent's catalog through "Add to a pack" ─────────────

def _claims(world) -> list[dict]:
    root = categorypack.packdraft.open_draft(world.settings.store_path, "gaming-mice").root
    return yaml.safe_load((root / "data" / "claims.yaml").read_text(encoding="utf-8")) or []


def test_an_agents_catalog_keeps_only_the_claim_its_page_supports(world, monkeypatch):
    """The case this exists for: a report that sounds sourced and is not.

    The agent writes three claims over one real quote — one that restates it,
    one that says the opposite, one about something the page never mentions.
    All three pass the quote check, because the quote is real. Only the first
    belongs in the catalog.
    """
    from app.web import tasks

    _script_v8(world.script)
    monkeypatch.setattr(tasks, "_nli_gate", lambda: NliGate(FakeVerifier()))
    _, done = _check(world, TITLE)

    titles = [one["text"]["en"]["title"] for one in _claims(world)]
    assert RESTATES in titles
    assert REFUTES not in titles
    assert UNRELATED not in titles
    assert done["result"]["claims_added"] == 1, done["result"]


# ── the acceptance path: a research run's findings ───────────────────────

DOCUMENT = f"The review found that {V8_QUOTE}. Nothing else was measured."


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "k.sqlite")
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')")
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label)"
        " VALUES ('s1', 'probe', 'product', 'Thing s1')")
    conn.commit()
    return conn


def _finding(title: str) -> dict:
    return {"title": title, "rationale": title + " — reported by owners, worth checking.",
            "quote": V8_QUOTE, "document_text": DOCUMENT,
            "source_url": V8_PAGE, "component": "sensor"}


def test_a_finding_its_document_refutes_is_refused(store):
    out = accept_findings(store, "s1", "probe", [_finding(REFUTES)],
                          nli=NliGate(FakeVerifier()))
    assert out["accepted"] == []
    assert [one["title"] for one in out["nli_dropped"]] == [REFUTES]
    assert out["rejected"][0]["reason"].startswith("nli: ")


def test_a_finding_its_document_does_not_support_is_held(store):
    out = accept_findings(store, "s1", "probe", [_finding(UNRELATED)],
                          nli=NliGate(FakeVerifier()))
    assert out["accepted"] == []
    assert [one["title"] for one in out["nli_held"]] == [UNRELATED]
    # Held, not refused for a field: there is nothing to rewrite, only a
    # source to find, so `_repair` must not ask the model to try again.
    assert not out["rejected"][0].get("fix")
    assert "held because the page quoted does not clearly support" in out["summary"]
    assert "find a source that says it plainly" in out["next"]


def test_a_finding_its_document_restates_is_kept_with_its_verdict(store):
    out = accept_findings(store, "s1", "probe", [_finding(RESTATES)],
                          nli=NliGate(FakeVerifier()))
    assert [one["title"] for one in out["accepted"]] == [RESTATES]
    assert out["accepted"][0]["nli"]["verdict"] == "entailment"
    assert out["nli_held"] == [] and out["nli_dropped"] == []


def test_with_no_gate_the_acceptance_path_is_unchanged(store):
    """The fail-open promise, at the door both MCP and the web jobs use."""
    out = accept_findings(store, "s1", "probe",
                          [_finding(RESTATES), _finding(REFUTES), _finding(UNRELATED)])
    assert len(out["accepted"]) == 3
    assert out["nli_held"] == [] and out["nli_dropped"] == []
    assert all("nli" not in one for one in out["accepted"])


def test_the_mcp_and_cli_door_asks_for_this_machines_gate(monkeypatch, store):
    """`agentops.submit` is the door that does not need MCP. With no model it
    passes None down and every sourced finding is kept, marked unchecked."""
    from app import agentops
    from app import nli_gate

    monkeypatch.setattr(nli_gate, "gate_from_env", lambda: None)
    out = agentops.submit(store, app_state_path=store_path_of(store), door="cli",
                          subject_id="s1", pack_id="probe",
                          findings=[_finding(RESTATES), _finding(REFUTES)])
    assert len(out["accepted"]) == 2
    assert all("nli" not in one for one in out["accepted"])


def store_path_of(store) -> Path:
    return Path(store.execute("PRAGMA database_list").fetchone()["file"])


def test_the_web_job_reads_the_gate_once(monkeypatch):
    from app import nli_gate
    from app.web import tasks

    calls = []
    monkeypatch.setattr(nli_gate, "gate_from_env", lambda: calls.append(1) or None)
    assert tasks._nli_gate() is None
    assert calls == [1]


def test_a_checkpoint_that_will_not_load_is_a_gate_that_is_off(monkeypatch):
    """A model that cannot be loaded must not fail the job that asked for it."""
    from app import nli_gate
    from app.web import tasks

    class Unloadable:
        def __init__(self, *args, **kwargs):
            raise OSError("the checkpoint is not on this machine")

    monkeypatch.setattr(nli_gate, "TransformersNliVerifier", Unloadable)
    # The extra is "installed" for this test, so the load is what fails.
    monkeypatch.setitem(sys.modules, "transformers", object())
    monkeypatch.setitem(sys.modules, "torch", object())
    gate = nli_gate.gate_from_env({"KRIKO_NLI_MODEL": "owner/nli"})
    assert gate is not None and gate.name == "unavailable"
    # …and the job door reads that as "off", so the claim passes unchanged.
    monkeypatch.setattr(nli_gate, "gate_from_env", lambda: gate)
    assert tasks._nli_gate() is None
