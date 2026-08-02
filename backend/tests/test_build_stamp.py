"""B15 — deploy-staleness guard: the running build is stamped into /health and
every /analyze response.

The 2026-07-13 incident (39 risk cards served by a ~23h-stale image — see
test_serving_cap_regression.py) was invisible: nothing reported which artifact
was actually serving, so pre-fix behaviour shipped silently. The stamp makes a
stale deploy visible — /health for the operator, the `build` field for the
extension footer and the analyses.jsonl replay log.
"""

from fastapi.testclient import TestClient

from backend import config
from backend.api.main import app
from backend.db.session import get_db

STAMP = {"commit": "a0b39d1", "build_time": "2026-07-22T15:02:31+03:00"}


def _use_stamp(monkeypatch):
    monkeypatch.setattr(config, "GIT_COMMIT", STAMP["commit"])
    monkeypatch.setattr(config, "GIT_BUILD_TIME", STAMP["build_time"])


def test_health_reports_the_build_stamp(monkeypatch):
    _use_stamp(monkeypatch)

    body = TestClient(app).get("/health").json()

    assert body["status"] == "ok"
    assert body["commit"] == STAMP["commit"]
    assert body["build_time"] == STAMP["build_time"]


def test_health_stamp_is_always_present_never_crashes():
    # Env vars absent (the test env sets neither) → the config fallback must
    # still serve a non-empty stamp ("unknown"), not an import error or a 500.
    body = TestClient(app).get("/health").json()
    assert body["commit"] and isinstance(body["commit"], str)
    assert body["build_time"] and isinstance(body["build_time"], str)


def test_analyze_response_carries_the_build_stamp(db, megane4_variants, monkeypatch, tmp_path):
    """Same stale-deploy mirror as test_serving_cap_regression: the buyer-facing
    response (and its analyses.jsonl record) must name the build that produced
    it, or replay debugging compares output against the wrong code.
    """
    _use_stamp(monkeypatch)
    # Keep the best-effort JSONL logger off the real logs/ file.
    monkeypatch.setattr(config, "ANALYSES_LOG_PATH", tmp_path / "analyses.jsonl")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    try:
        resp = TestClient(app).post("/analyze", json={"ad_metadata": {
            "make": "Renault", "model": "Megane", "year": 2020, "fuel_type": "diesel",
            "engine_volume_cc": 1461, "power_hp": 90, "mileage_km": 50000,
        }})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["build"] == STAMP


def test_analyze_unavailable_response_still_carries_the_stamp(monkeypatch, tmp_path):
    """The error path is where the stamp matters most: "unavailable" served by a
    stale build is exactly the incident shape B15 guards against.
    """
    _use_stamp(monkeypatch)
    monkeypatch.setattr(config, "ANALYSES_LOG_PATH", tmp_path / "analyses.jsonl")

    import backend.api.main as main_mod

    def _boom(meta, db):
        raise RuntimeError("db down")

    monkeypatch.setattr(main_mod, "run_analysis", _boom)

    resp = TestClient(app).post("/analyze", json={"ad_metadata": {"make": "Renault"}})

    assert resp.status_code == 200
    assert resp.json()["coverage_state"] == "unavailable"
    assert resp.json()["build"] == STAMP
