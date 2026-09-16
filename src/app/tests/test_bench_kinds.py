"""B126 §3/§9 — `bulk` and `validation` are real case kinds, not declared and
unused. `specific` already had `test_the_benchmark.py`; this covers the other
two, plus the dispatcher that routes between all three.
"""

import pytest

from app import bench
from app.web.settings import Settings
from kriko.store.db import connect


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


@pytest.fixture
def store(settings):
    conn = connect(settings.store_path)
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    for index in "abcd":
        conn.execute(
            "INSERT INTO subjects (subject_id, pack_id, kind, label)"
            " VALUES (?, 'probe', 'product', ?)",
            (f"s{index}", f"Thing {index}"),
        )
    conn.commit()
    return conn


# ── the dispatcher ───────────────────────────────────────────────────────────

def test_a_specific_case_still_goes_through_the_ordinary_path(settings, store, monkeypatch):
    from app.web import tasks

    calls = []

    def fake_research(measured_settings, params, progress):
        calls.append(params)
        return {"documents": 1, "accepted": [], "rejected": [], "llm": "x"}

    monkeypatch.setattr(tasks, "research", fake_research)
    row = bench.run_case(
        settings, {"subject_id": "sa", "pack_id": "probe", "kind": "specific"},
        plane="harness",
    )
    assert row["kind"] == "specific"
    assert len(calls) == 1


def test_an_unknown_kind_falls_back_to_specific_rather_than_crashing(settings, store, monkeypatch):
    from app.web import tasks

    monkeypatch.setattr(
        tasks, "research",
        lambda *a, **k: {"documents": 0, "accepted": [], "rejected": [], "llm": "x"},
    )
    row = bench.run_case(
        settings, {"subject_id": "sa", "pack_id": "probe", "kind": "something_new"},
        plane="harness",
    )
    assert "error" not in row or "no such protocol" not in row.get("error", "")
    assert row["kind"] == "specific"


# ── bulk ─────────────────────────────────────────────────────────────────────

def test_bulk_runs_every_named_subject_and_aggregates(settings, store, monkeypatch):
    from app.web import tasks

    seen = []

    def fake_research(measured_settings, params, progress):
        seen.append(params["subject_id"])
        return {
            "documents": 2, "accepted": [{"title": "kept"}],
            "rejected": [{"title": "no", "reason": "x"}],
            "tokens_used": 100, "spent_usd": 0.01, "llm": "x",
        }

    monkeypatch.setattr(tasks, "research", fake_research)
    case = {
        "subject_id": "sa", "subject_ids": ["sa", "sb", "sc"], "kind": "bulk",
        "pack_id": "probe",
    }
    row = bench.run_case(settings, case, plane="harness")
    assert row["kind"] == "bulk"
    assert seen == ["sa", "sb", "sc"]
    assert row["accepted"] == 3  # one kept per subject, three subjects
    assert row["refused"] == 3
    assert row["documents"] == 6
    assert row["usd"] == pytest.approx(0.03)
    assert row["claims_per_minute"] is not None
    assert row["missing_subjects"] == []


def test_bulk_counts_an_uninstalled_subject_rather_than_dropping_it_silently(
    settings, store, monkeypatch
):
    """A case whose subject was uninstalled mid-run is exactly the kind of
    thing this benchmark exists to notice."""
    from app.web import tasks

    def fake_research(measured_settings, params, progress):
        if params["subject_id"] == "sb":
            raise KeyError("no subject sb is installed")
        return {"documents": 1, "accepted": [{"title": "kept"}], "rejected": [], "llm": "x"}

    monkeypatch.setattr(tasks, "research", fake_research)
    case = {"subject_id": "sa", "subject_ids": ["sa", "sb"], "kind": "bulk", "pack_id": "probe"}
    row = bench.run_case(settings, case, plane="harness")
    assert row["missing_subjects"] == ["sb"]
    assert row["accepted"] == 1
    assert "error" not in row  # not every subject failed, so this is a partial measurement


def test_bulk_reports_an_error_when_every_subject_fails(settings, store, monkeypatch):
    from app.web import tasks

    monkeypatch.setattr(tasks, "research", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("boom")))
    case = {"subject_id": "sa", "subject_ids": ["sa", "sb"], "kind": "bulk", "pack_id": "probe"}
    row = bench.run_case(settings, case, plane="harness")
    assert "error" in row
    assert row["missing_subjects"] == ["sa", "sb"]


def test_bulk_with_no_subject_ids_at_all_is_an_error_not_a_crash(settings, store):
    row = bench.run_case(
        settings, {"kind": "bulk", "pack_id": "probe"}, plane="harness",
    )
    assert "error" in row


def test_bulk_writes_nothing_to_the_real_store(settings, store, monkeypatch):
    from app.web import tasks

    def fake_research(measured_settings, params, progress):
        conn = connect(measured_settings.store_path)
        conn.execute(
            "INSERT INTO claims (claim_id, pack_id, subject_id, kind, domain,"
            " severity, author_confidence, created_at)"
            " VALUES ('bench', 'probe', ?, 'known_issue', 'engine', 'high', 0.6,"
            " datetime('now'))",
            (params["subject_id"],),
        )
        conn.commit()
        conn.close()
        return {"documents": 1, "accepted": [{"title": "kept"}], "rejected": [], "llm": "x"}

    monkeypatch.setattr(tasks, "research", fake_research)
    case = {"subject_id": "sa", "subject_ids": ["sa", "sb"], "kind": "bulk", "pack_id": "probe"}
    bench.run_case(settings, case, plane="harness")
    assert store.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0


# ── validation ───────────────────────────────────────────────────────────────

@pytest.fixture
def stored_claim(store):
    store.execute(
        "INSERT INTO claims (claim_id, pack_id, subject_id, kind, domain,"
        " severity, author_confidence, created_at, title)"
        " VALUES ('c1', 'probe', 'sa', 'known_issue', 'transmission', 'high',"
        " 0.6, datetime('now'), 'DSG mechatronics unit fails')"
    )
    store.execute(
        "INSERT INTO sources (source_id, pack_id, url)"
        " VALUES ('src1', 'probe', 'https://e.example/page')"
    )
    store.execute(
        "INSERT INTO evidence (evidence_id, pack_id, claim_id, source_id, quote)"
        " VALUES ('ev1', 'probe', 'c1', 'src1', 'the mechatronics unit fails often')"
    )
    store.commit()
    return store


def test_validation_confirms_a_quote_still_on_its_page(settings, stored_claim):
    def opener(request, timeout=0):
        class _Resp:
            headers = {"Content-Type": "text/plain"}

            def read(self, n=None):
                return b"Owners report the mechatronics unit fails often on this gearbox."

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    case = {"subject_id": "sa", "pack_id": "probe", "kind": "validation"}
    row = bench.run_case(settings, case, plane="harness", opener=opener)
    assert row["kind"] == "validation"
    assert row["accepted"] == 1
    assert row["refused"] == 0


def test_validation_detects_drift_when_the_page_no_longer_says_it(settings, stored_claim):
    def opener(request, timeout=0):
        class _Resp:
            headers = {"Content-Type": "text/plain"}

            def read(self, n=None):
                return b"This page has been completely rewritten."

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    case = {"subject_id": "sa", "pack_id": "probe", "kind": "validation"}
    row = bench.run_case(settings, case, plane="harness", opener=opener)
    assert row["accepted"] == 0
    assert row["refused"] == 1


def test_validation_with_no_stored_claims_is_an_error_not_a_crash(settings, store):
    case = {"subject_id": "sa", "pack_id": "probe", "kind": "validation"}
    row = bench.run_case(settings, case, plane="harness")
    assert "error" in row


def test_validation_needs_no_network_and_no_llm(settings, stored_claim, monkeypatch):
    """The whole point of the kind: mechanical, offline, no self-grading
    model in the data path."""
    import urllib.request

    def explode(*a, **k):
        raise AssertionError("validation must not touch the real network")

    monkeypatch.setattr(urllib.request, "urlopen", explode)

    def opener(request, timeout=0):
        class _Resp:
            headers = {"Content-Type": "text/plain"}

            def read(self, n=None):
                return b"the mechatronics unit fails often"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    case = {"subject_id": "sa", "pack_id": "probe", "kind": "validation"}
    row = bench.run_case(settings, case, plane="harness", opener=opener)
    assert row["accepted"] == 1
