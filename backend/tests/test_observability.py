"""docs/design_flaws.md "Observability gap": full-payload logging, debug read
path, and the replay diff must actually work end to end without a browser/DB
client.
"""

from fastapi.testclient import TestClient

from backend import config
from backend.api.main import run_analysis
from backend.observability import log_analysis_jsonl, read_by_id, read_recent
from backend.tools.replay import _diff_and_print, compute_diff


# ── JSONL writer/reader ──────────────────────────────────────────────────────

def test_log_and_read_recent_round_trip(tmp_path):
    path = tmp_path / "analyses.jsonl"
    log_analysis_jsonl({"id": "a1", "ad_metadata": {"model": "Golf 7"}}, path=path)
    log_analysis_jsonl({"id": "a2", "ad_metadata": {"model": "Clio 5"}}, path=path)

    records = read_recent(limit=10, path=path)
    assert [r["id"] for r in records] == ["a2", "a1"]  # most-recent-first


def test_read_recent_filters_by_model_case_insensitive(tmp_path):
    path = tmp_path / "analyses.jsonl"
    log_analysis_jsonl({"id": "a1", "ad_metadata": {"model": "Golf 7"}}, path=path)
    log_analysis_jsonl({"id": "a2", "ad_metadata": {"model": "Clio 5"}}, path=path)

    assert [r["id"] for r in read_recent(limit=10, model="golf", path=path)] == ["a1"]


def test_read_recent_respects_limit(tmp_path):
    path = tmp_path / "analyses.jsonl"
    for i in range(5):
        log_analysis_jsonl({"id": f"a{i}"}, path=path)

    assert [r["id"] for r in read_recent(limit=2, path=path)] == ["a4", "a3"]


def test_read_recent_missing_file_returns_empty(tmp_path):
    assert read_recent(limit=10, path=tmp_path / "nope.jsonl") == []


def test_read_by_id_finds_or_misses(tmp_path):
    path = tmp_path / "analyses.jsonl"
    log_analysis_jsonl({"id": "a1"}, path=path)
    log_analysis_jsonl({"id": "a2"}, path=path)

    assert read_by_id("a2", path=path)["id"] == "a2"
    assert read_by_id("nope", path=path) is None


def test_log_analysis_jsonl_never_raises_on_bad_path(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")  # forces mkdir(parents=True) to fail
    log_analysis_jsonl({"id": "x"}, path=blocker / "analyses.jsonl")  # must not raise


# ── /debug/analyses endpoint ─────────────────────────────────────────────────

def test_debug_analyses_endpoint_404_by_default(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_DEBUG_ENDPOINT", False)
    from backend.api.main import app
    assert TestClient(app).get("/debug/analyses").status_code == 404


def test_debug_analyses_endpoint_returns_logged_records_when_enabled(monkeypatch, tmp_path):
    log_path = tmp_path / "analyses.jsonl"
    monkeypatch.setattr(config, "ENABLE_DEBUG_ENDPOINT", True)
    monkeypatch.setattr(config, "ANALYSES_LOG_PATH", log_path)
    log_analysis_jsonl({"id": "a1", "ad_metadata": {"model": "Golf 7"}})

    from backend.api.main import app
    client = TestClient(app)
    resp = client.get("/debug/analyses?limit=5")

    assert resp.status_code == 200
    assert resp.json()["analyses"][0]["id"] == "a1"


# ── replay diffing (pure, no DB) ─────────────────────────────────────────────

def test_compute_diff_reports_no_change_for_identical_responses():
    resp = {"coverage_state": "risks_found", "matched_variant_ids": ["v1"], "risks": [{"title": "X"}]}
    assert compute_diff(resp, dict(resp)) == []


def test_compute_diff_reports_coverage_state_change():
    logged = {"coverage_state": "not_matched", "matched_variant_ids": [], "risks": []}
    new = {"coverage_state": "risks_found", "matched_variant_ids": ["v1"], "risks": []}
    diff = compute_diff(logged, new)
    assert any("coverage_state" in line for line in diff)
    assert any("matched_variant_ids" in line for line in diff)


def test_compute_diff_reports_added_and_removed_risks():
    logged = {"coverage_state": "risks_found", "matched_variant_ids": ["v1"],
              "risks": [{"title": "DQ200 mechatronics fault"}]}
    new = {"coverage_state": "risks_found", "matched_variant_ids": ["v1"],
           "risks": [{"title": "DQ381 mechatronics fault"}]}
    diff = compute_diff(logged, new)
    assert any("now shown" in line and "DQ381" in line for line in diff)
    assert any("no longer shown" in line and "DQ200" in line for line in diff)


# ── run_analysis() is the single source of truth for both /analyze and replay ──

def test_run_analysis_is_deterministic_for_replay(db, megane4_claims):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2020,
        "fuel_type": "diesel", "transmission": "manual",
        "engine_volume_cc": 1500, "power_hp": 90, "mileage_km": 50000,
    }
    _ctx1, _match1, _served1, resp1 = run_analysis(meta, db)
    _ctx2, _match2, _served2, resp2 = run_analysis(meta, db)

    assert resp1.model_dump(mode="json") == resp2.model_dump(mode="json")


# ── replay._diff_and_print integrated against the real matcher/resolver ─────

def test_diff_and_print_surfaces_a_claim_the_pipeline_no_longer_serves(db, megane4_claims, capsys):
    """Simulates the exact scenario replay exists for: a logged response that
    predates a fix (e.g. a sibling-code-contaminated claim removed from the
    part YAML) no longer matches what the current pipeline serves.
    """
    meta = {
        "make": "Renault", "model": "Megane", "year": 2020,
        "fuel_type": "diesel", "transmission": "manual",
        "engine_volume_cc": 1500, "power_hp": 90, "mileage_km": 50000,
    }
    stale_record = {
        "id": "stale-1",
        "ad_metadata": meta,
        "response": {
            "coverage_state": "risks_found",
            "matched_variant_ids": ["megane4_k9k_90"],
            "risks": [
                {"title": "Injector failure on 1.5 dCi"},
                {"title": "A claim the current pipeline no longer serves"},
            ],
        },
    }

    _diff_and_print(stale_record, db)
    out = capsys.readouterr().out

    assert "stale-1" in out
    assert "no longer shown" in out
    assert "A claim the current pipeline no longer serves" in out
    # Still-present claim must NOT show up as a change.
    assert "Injector failure on 1.5 dCi" not in out.split("no longer shown")[1]


def test_diff_and_print_reports_no_change_when_response_still_matches(db, megane4_claims, capsys):
    meta = {
        "make": "Renault", "model": "Megane", "year": 2020,
        "fuel_type": "diesel", "transmission": "manual",
        "engine_volume_cc": 1500, "power_hp": 90, "mileage_km": 50000,
    }
    _ctx, _match, _served, resp = run_analysis(meta, db)
    record = {"id": "fresh-1", "ad_metadata": meta, "response": resp.model_dump(mode="json")}

    _diff_and_print(record, db)
    out = capsys.readouterr().out

    assert "no change" in out
