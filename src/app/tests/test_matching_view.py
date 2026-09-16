"""What a reader — or the person debugging for them — is told about a match.

The engine's half of this is tested in `kriko/tests/test_lookup_score.py`.
This is the half the reader actually meets: the answer carries its own doubt,
and there is a second door that explains where the doubt came from.

It runs on the same fixture `test_web.py` uses, which is a drill and a
toolshop. That is the point: the reported bug was about a car, and nothing
about the fix knows what a car is.
"""

import pytest
from fastapi.testclient import TestClient

from app.matching import next_step, scoring, verdict
from app.web.app import create_app
from app.web.settings import Settings
from app.tests.test_web import ADAPTER, PACK  # the drill pack and its adapter

import json
import textwrap

from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "p"
    for sub in ("vocabulary", "data", "research", "adapters"):
        (root / sub).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(PACK["toml"]), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(
        textwrap.dedent(PACK["terms"]), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(
        textwrap.dedent(PACK["subjects"]), encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(
        textwrap.dedent(PACK["claims"]), encoding="utf-8")
    (root / "research" / "principle.md").write_text("Only the expensive.",
                                                    encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n',
                                                      encoding="utf-8")
    (root / "adapters" / "toolshop.json").write_text(json.dumps(ADAPTER),
                                                     encoding="utf-8")
    store_path = tmp_path / "store.sqlite"
    conn = connect(store_path)
    packstore.install(conn, build.build(root, tmp_path / "p.kpack"))
    conn.close()
    with TestClient(create_app(Settings(
        store_path=store_path,
        analysis_log_path=tmp_path / "analyses.jsonl",
        app_state_path=tmp_path / "app.sqlite",
    ))) as tc:
        yield tc


URL = "https://toolshop.invalid/item/dhp484"


#: The adapter reads the maker out of the page title against the pack's own
#: identity vocabulary, so a title is part of a realistic page rather than
#: decoration — without one the identity is a model and nothing else.
TITLE = "Makita DHP484 combi drill"


def _analyze(client, title=TITLE, **fields):
    return client.post(
        "/api/analyze", json={"url": URL, "title": title, "fields": fields}).json()


def _diagnose(client, url=URL, title=TITLE, **fields):
    return client.post(
        "/api/diagnose/identity",
        json={"url": url, "title": title, "fields": fields}).json()


# ── the answer carries its own doubt ─────────────────────────────────────

def test_an_exact_answer_says_so_and_asks_nothing(client):
    body = _analyze(client, **{"Model No": "DHP484"})
    assert body["verdict"] == "recognised"
    assert body["score"] == 1.0
    assert body["next_step"]["action"] == "none"


def test_a_miss_names_the_nearest_thing_rather_than_going_quiet(client):
    """The reported bug, in its general form: nothing found, nothing said.

    A page whose model no pack holds used to come back as a bare `no_match`.
    It now comes back naming what it nearly was and what to do about it.
    """
    body = _analyze(client, **{"Model No": "DHP999"})
    assert body["verdict"] == "unrecognised"
    assert body["next_step"]["action"] in {"research", "install"}
    assert body["next_step"]["say"], "a dead end is the bug"


def test_the_losers_come_back_too_so_nothing_has_to_be_guessed_at(client):
    body = _analyze(client, **{"Model No": "DHP999"})
    assert body["considered"], "no candidates means nothing to explain with"
    best = body["considered"][0]
    assert best["label"]
    assert {key["how"] for key in best["keys"]} <= {
        "exact", "similar", "conflict", "absent"}


# ── the diagnostic door ──────────────────────────────────────────────────

def test_the_diagnostic_shows_the_whole_chain(client):
    out = _diagnose(client, **{"Model No": "DHP484", "Hours Used": "900"})
    assert out["adapter"]["id"] == "toolshop"
    assert out["adapter"]["source"] == "pack"
    assert out["page"]["identity"] == {"brand": "makita", "model": "DHP484"}
    assert out["page"]["context"]["usage_hours"] == 900
    assert out["outcome"]["method"] == "exact"
    assert out["outcome"]["claims"] >= 1


def test_the_diagnostic_explains_a_miss_key_by_key(client):
    out = _diagnose(client, **{"Model No": "DHP999"})
    assert out["outcome"]["verdict"] == "unrecognised"
    keys = {one["key"]: one for one in out["considered"][0]["keys"]}
    assert keys["model"]["supplied"] == "DHP999"
    assert keys["model"]["held"], "what the catalog holds is the half you cannot see"


def test_an_unreadable_site_is_a_finding_not_an_error(client):
    """`/analyze` 404s here, and that is right for an answer. Not for a trace.

    "Nothing reads this site" is the commonest explanation for a silent panel,
    so the endpoint whose job is explaining silences must return it as a
    result a client renders, never as an exception it has to catch.
    """
    out = _diagnose(client, url="https://nobody-reads-this.invalid/x")
    assert out["outcome"]["method"] == "no_adapter"
    assert out["next_step"]["action"] == "register_site"


def test_the_diagnostic_leaves_no_trace_in_the_readers_history(client):
    """Debugging is not asking. A history full of attempts is not a history."""
    before = len(client.get("/api/history").json()["items"])
    _diagnose(client, **{"Model No": "DHP484"})
    assert len(client.get("/api/history").json()["items"]) == before


def test_the_diagnostic_and_the_answer_agree(client):
    """Two doors, one call. A diagnostic that disagrees is worse than none."""
    answer = _analyze(client, **{"Model No": "DHP484"})
    trace = _diagnose(client, **{"Model No": "DHP484"})
    assert trace["outcome"]["method"] == answer["method"]
    assert trace["outcome"]["coverage"] == answer["coverage"]
    assert trace["page"]["identity"] == answer["identity"]


# ── the words, without a server ──────────────────────────────────────────

class _Res:
    def __init__(self, method, considered=(), score=1.0):
        self.method = method
        self.considered = considered
        self.score = score
        self.notes = ""
        self.flags = ()
        self.subject_ids = ()


def test_a_matched_subject_with_nothing_known_is_a_gap_not_a_clean_bill():
    step = next_step(_Res("exact"), "MATCHED_NO_DATA")
    assert step["action"] == "research"
    assert "clean bill of health" in step["say"]


def test_an_unknown_method_never_reads_as_recognised():
    """A method the engine gains tomorrow must not default to confidence."""
    assert verdict(_Res("something_new")) == "unrecognised"


def test_scoring_rounds_rather_than_leaking_float_noise():
    assert scoring(_Res("exact", score=0.6666666))["score"] == 0.6667
