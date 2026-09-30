"""What an agent should research next, and whether the ordering earns its keep.

The row this belongs to (B82) states its own gate: *an agent given only the
brief picks a subject a human would have picked*. Test 1 is that gate, read as
the smallest honest version of it — a subject the log was asked about twice
outranks an alphabetically-earlier gap nobody has ever asked about. It is the
test that fails against `coverage_gaps`, which is where an agent gets its
ordering today.

The rest hold the things that make the agenda safe to hand to a harness: a
`NOT_MATCHED` identity is never offered as a research task, a changed source
page is never a retraction, an unreadable log is a worse ordering rather than
an error, and no row carries a listing URL.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import agenda
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings
from kriko.store.db import connect

ROOT = Path(__file__).resolve().parents[3]


def _pack(conn, pack_id="p", enabled=1):
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled) VALUES (?, ?, '1.0.0', 1, '2026-01-01',"
        " 'digest', ?)",
        (pack_id, pack_id, enabled),
    )


def _subject(conn, subject_id, label, pack_id="p"):
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label) VALUES (?, ?, 'k', ?)",
        (subject_id, pack_id, label),
    )


def _claim(conn, claim_id, subject_id, pack_id="p", title="A claim"):
    conn.execute(
        "INSERT INTO claims (claim_id, pack_id, subject_id, kind, domain,"
        " severity, created_at) VALUES (?, ?, ?, 'known_issue', 'd', 'high',"
        " '2026-01-01')",
        (claim_id, pack_id, subject_id),
    )
    conn.execute(
        "INSERT INTO claim_text (claim_id, pack_id, lang, title) VALUES (?, ?, 'en', ?)",
        (claim_id, pack_id, title),
    )


def _evidence(conn, claim_id, pack_id="p", source_id="src"):
    conn.execute(
        "INSERT OR IGNORE INTO sources (source_id, pack_id, url, domain)"
        " VALUES (?, ?, 'https://example.test/a', 'example.test')",
        (source_id, pack_id),
    )
    conn.execute(
        "INSERT INTO evidence (evidence_id, pack_id, claim_id, source_id, quote)"
        " VALUES (?, ?, ?, ?, 'a quote')",
        (f"e-{claim_id}", pack_id, claim_id, source_id),
    )


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "k.sqlite")
    _pack(conn)
    conn.commit()
    yield conn
    conn.close()


def _log(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    return path


def _asked(subject_id, times):
    return [{"coverage": "MATCHED_NO_DATA", "subjects": [subject_id]}] * times


# ── 1. the gate B82 states ────────────────────────────────────────────────


def test_a_subject_the_reader_asked_about_outranks_an_earlier_letter(store, tmp_path):
    """The whole point of the row, and the test `coverage_gaps` fails.

    Two gaps, neither holding anything. One was analysed twice; the other has
    an alphabetically earlier label and has never been asked about. An agent
    reading the first row must get the one someone wanted.
    """
    _subject(store, "s-audi", "Aaa never asked about")
    _subject(store, "s-zeta", "Zzz asked about twice")
    store.commit()
    log = _log(tmp_path / "a.jsonl", _asked("s-zeta", 2))

    rows = agenda.compute(store, log_path=log)["rows"]

    assert [r["subject_id"] for r in rows] == ["s-zeta", "s-audi"]
    assert rows[0]["asked"] == 2
    # And the row says what to do, not only where it ranked.
    assert "research_brief" in rows[0]["why"]


# ── 2. the signal no gap list can carry ───────────────────────────────────


def test_an_identity_the_catalog_cannot_name_is_not_a_research_task(store, tmp_path):
    _subject(store, "s1", "A known thing")
    store.commit()
    log = _log(tmp_path / "a.jsonl", [
        {"coverage": "NOT_MATCHED", "identity": {"make": "x", "model": "y"}, "subjects": []},
    ])

    rows = agenda.compute(store, log_path=log)["rows"]
    unknown = [r for r in rows if r["kind"] == "unknown_subject"]

    assert len(unknown) == 1
    # No subject id, because there is no subject: `submit_findings` could not
    # accept anything filed against this row, and a row that invited it would
    # get a finding attached to the wrong product.
    assert unknown[0]["subject_id"] == ""
    assert "catalog" in unknown[0]["why"]
    assert json.loads(unknown[0]["identity"]) == {"make": "x", "model": "y"}


def test_two_lookups_of_the_same_unknown_thing_are_one_row(store, tmp_path):
    # Field order is the adapter's business; a reader who looked at the same
    # car twice asked once about one thing, not once about two.
    _subject(store, "s1", "A known thing")
    store.commit()
    log = _log(tmp_path / "a.jsonl", [
        {"coverage": "NOT_MATCHED", "identity": {"make": "x", "model": "y"}},
        {"coverage": "NOT_MATCHED", "identity": {"model": "y", "make": "x"}},
    ])

    unknown = [r for r in agenda.compute(store, log_path=log)["rows"]
               if r["kind"] == "unknown_subject"]
    assert len(unknown) == 1
    assert unknown[0]["asked"] == 2


def test_a_lookup_that_resolved_and_found_nothing_is_a_research_row(store, tmp_path):
    # MATCHED_NO_DATA is the case the catalog *did* name. It is an
    # `empty_subject` with a `subject_id` an agent can file against, and
    # treating it as an unknown identity would lose that.
    _subject(store, "s1", "A known thing")
    store.commit()
    log = _log(tmp_path / "a.jsonl", [
        {"coverage": "MATCHED_NO_DATA", "identity": {"make": "x"}, "subjects": ["s1"]},
    ])

    rows = agenda.compute(store, log_path=log)["rows"]
    assert [r["kind"] for r in rows] == ["empty_subject"]
    assert rows[0]["subject_id"] == "s1"


# ── 3. a changed page is a signal, not a retraction ───────────────────────


def test_a_source_that_changed_becomes_a_re_read_and_nothing_else(store, tmp_path):
    _subject(store, "s1", "A thing")
    _claim(store, "c1", "s1")
    store.commit()
    app_state = state.connect(tmp_path / "app.sqlite")
    state.record_fact_check(
        app_state, pack_id="p", claim_id="c1", verdict="missing",
        detail="", sources=[{"url": "https://example.test/a", "verdict": "missing"}],
        subject_id="s1", title="A claim",
    )

    rows = agenda.compute(store, app_state=app_state, log_path=tmp_path / "none.jsonl")["rows"]
    stale = [r for r in rows if r["kind"] == "stale_claim"]

    assert stale and stale[0]["claim_id"] == "c1"
    assert "re-read" in stale[0]["why"]
    # The claim is untouched in the engine's store — the agenda reads, and a
    # verdict about someone else's web page has no business retracting a pack.
    assert store.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
    app_state.close()


# ── 4. reproducible ───────────────────────────────────────────────────────


def test_the_order_is_total_so_two_runs_agree(store, tmp_path):
    for i in range(6):
        _subject(store, f"s{i}", f"Subject {i}")
    store.commit()
    log = _log(tmp_path / "a.jsonl", _asked("s3", 2) + _asked("s5", 2))

    first = agenda.compute(store, log_path=log)
    second = agenda.compute(store, log_path=log)
    assert json.dumps(first) == json.dumps(second)
    # Equal demand falls back to the ids, not to insertion order.
    assert [r["subject_id"] for r in first["rows"][:2]] == ["s3", "s5"]


# ── 5. emptiness is not failure ───────────────────────────────────────────


def test_an_installation_with_no_packs_gets_no_agenda(tmp_path):
    conn = connect(tmp_path / "k.sqlite")
    assert agenda.compute(conn)["rows"] == []
    assert "no packs" in agenda.compute(conn)["note"]
    conn.close()


def test_a_disabled_pack_is_not_research(tmp_path):
    conn = connect(tmp_path / "k.sqlite")
    _pack(conn, "off", enabled=0)
    _subject(conn, "s1", "A thing", pack_id="off")
    conn.commit()
    assert agenda.compute(conn)["rows"] == []
    conn.close()


def test_no_analyses_yet_still_orders_by_gap(store, tmp_path):
    _subject(store, "s1", "A thing")
    store.commit()
    result = agenda.compute(store, log_path=tmp_path / "missing.jsonl")
    assert [r["subject_id"] for r in result["rows"]] == ["s1"]
    assert "no analyses" in result["note"]


# ── 6. a broken input degrades the ordering, never the request ────────────


def test_an_unreadable_log_is_a_note_not_an_exception(store, tmp_path):
    _subject(store, "s1", "A thing")
    store.commit()
    bad = tmp_path / "a.jsonl"
    bad.write_text("{not json at all\n", encoding="utf-8")

    result = agenda.compute(store, log_path=bad)
    # `load_records` tolerates a malformed line by design, so this is the
    # weaker claim: whatever it does, the agenda still answers.
    assert [r["subject_id"] for r in result["rows"]] == ["s1"]


def test_an_app_state_that_cannot_be_read_costs_only_the_stale_rows(store, tmp_path):
    _subject(store, "s1", "A thing")
    store.commit()

    class Broken:
        def execute(self, *a, **k):
            raise RuntimeError("gone")

    result = agenda.compute(store, app_state=Broken(), log_path=tmp_path / "none.jsonl")
    assert [r["kind"] for r in result["rows"]] == ["empty_subject"]


# ── 7. what the harness sees of the reader ────────────────────────────────


def test_no_row_carries_the_listing_the_reader_was_looking_at(store, tmp_path):
    """The log holds URLs and advert text; an agenda row is handed to whatever
    harness the reader wired. The bar is that a row would be unremarkable in a
    screenshot: a product identity, never a page they visited."""
    _subject(store, "s1", "A thing")
    store.commit()
    log = _log(tmp_path / "a.jsonl", [{
        "coverage": "NOT_MATCHED",
        "identity": {"make": "x", "model": "y"},
        "url": "https://www.sahibinden.com/ilan/private-123456/detay",
        "ad_metadata": {"title": "SAHIBINDEN TEMIZ", "description": "call me"},
        "context": {"usage_km": 190000},
    }])

    blob = json.dumps(agenda.compute(store, log_path=log))
    assert "sahibinden" not in blob.lower()
    assert "call me" not in blob


# ── 8. the door ───────────────────────────────────────────────────────────


def test_the_route_answers_the_same_rows(tmp_path):
    conn = connect(tmp_path / "k.sqlite")
    _pack(conn)
    _subject(conn, "s1", "A thing")
    conn.commit()
    conn.close()
    log = _log(tmp_path / "a.jsonl", _asked("s1", 3))

    app = create_app(Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=log,
    ))
    with TestClient(app) as client:
        body = client.get("/api/agenda").json()

    assert body["rows"][0]["subject_id"] == "s1"
    assert body["rows"][0]["asked"] == 3
    assert body["counts"]["empty_subject"] == 1


def test_the_route_can_be_asked_about_one_pack(tmp_path):
    conn = connect(tmp_path / "k.sqlite")
    _pack(conn, "p")
    _pack(conn, "q")
    _subject(conn, "s1", "A thing", pack_id="p")
    _subject(conn, "s2", "Another", pack_id="q")
    conn.commit()
    conn.close()

    app = create_app(Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    ))
    with TestClient(app) as client:
        body = client.get("/api/agenda?pack_id=q").json()

    assert [r["subject_id"] for r in body["rows"]] == ["s2"]


def test_thin_claims_are_ranked_but_never_hidden(store, tmp_path):
    # A claim with a single source is thin; one with none at all is not weak
    # evidence but no evidence, and belongs to the gap list rather than here.
    # Same distinction `weakest_claims` already draws — asserted from the
    # consumer's side so the agenda cannot quietly change it.
    _subject(store, "s1", "A thing")
    _claim(store, "c1", "s1", title="Thinly supported")
    _evidence(store, "c1")
    store.commit()

    rows = agenda.compute(store, log_path=tmp_path / "none.jsonl")["rows"]
    assert [r["kind"] for r in rows] == ["thin_subject"]
    assert rows[0]["claim_id"] == "c1"
    # One source, and the row says so rather than saying "weak": the count is
    # what lets an agent decide it needs a *second, independent* one.
    assert rows[0]["independent_sources"] == 1


# ── 9. the skill's snapshot, and why a stale one is harmless ─────────────


def test_the_skill_carries_the_agenda_and_says_the_tool_wins(tmp_path):
    """A skill file is written to a harness's config directory once and then
    goes stale while the store changes underneath it. The fix is not to
    regenerate it on a timer — it is to say, in the file, which of the two is
    authoritative."""
    from app import agentskill

    conn = connect(tmp_path / "k.sqlite")
    _pack(conn)
    _subject(conn, "s1", "A thing nobody has researched")
    conn.commit()
    log = _log(tmp_path / "a.jsonl", _asked("s1", 4))
    rows = agenda.compute(conn, log_path=log)["rows"]

    body = agentskill.render(conn, rows)
    conn.close()

    assert "A thing nobody has researched" in body
    assert "asked about 4" in body
    assert "research_agenda" in body
    assert "the tool is right" in body


def test_the_skill_carries_the_pack_s_own_identification_method(tmp_path):
    """The agenda says what to research next; `research/skill.md` says how to
    tell what a subject even is before searching for it. Phase 5 of
    docs/superpowers/specs/2026-09-09-knowledge-building-design.md composes
    both into the generated skill, alongside the principle — an agent that
    only got the ordering would search a label instead of the attribute that
    actually discriminates."""
    from app import agentskill

    conn = connect(tmp_path / "k.sqlite")
    _pack(conn)
    conn.execute(
        "INSERT INTO pack_assets VALUES (?,?,?,?)",
        ("p", "research/skill.md", "skill",
         "Search the discriminating attribute, not the label."),
    )
    _subject(conn, "s1", "A thing")
    conn.commit()

    body = agentskill.render(conn)
    conn.close()

    assert "Search the discriminating attribute, not the label." in body


def test_a_skill_built_without_a_snapshot_is_still_a_skill(tmp_path):
    # The caller that has no business reading a reader's history passes
    # nothing, and gets the protocol without the head start.
    from app import agentskill

    conn = connect(tmp_path / "k.sqlite")
    _pack(conn)
    _subject(conn, "s1", "A thing")
    conn.commit()
    body = agentskill.render(conn)
    conn.close()

    assert body and "## What to research next" not in body
    assert "research_agenda" in body  # the loop still names it


def test_the_mcp_tool_and_the_route_are_the_same_computation(tmp_path, monkeypatch):
    """Two doors, one answer. `app/findings.py` exists because a claim's
    provenance must not depend on which door it came in; an ordering has the
    same property — an agent and the reader looking at the same installation
    must not be shown different work."""
    from app import mcp_server

    conn = connect(tmp_path / "k.sqlite")
    _pack(conn)
    _subject(conn, "s1", "A thing")
    conn.commit()
    conn.close()
    log = _log(tmp_path / "a.jsonl", _asked("s1", 2))
    monkeypatch.setattr(mcp_server, "STORE_PATH", tmp_path / "k.sqlite")
    monkeypatch.setenv("KRIKO_ANALYSES_LOG", str(log))

    through_mcp = mcp_server.research_agenda()

    app = create_app(Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=log,
    ))
    with TestClient(app) as client:
        through_http = client.get("/api/agenda").json()

    assert through_mcp["rows"] == through_http["rows"]

