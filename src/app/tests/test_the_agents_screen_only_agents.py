"""B164: Agents shows the agents and nothing else (decision D5).

The top-N run and the unattended schedule loop went with their screens. What
the reader asked for was the sections gone; what makes that true rather than
cosmetic is that nothing still runs them: no endpoint starts a top-N run, no
endpoint sets a schedule, and a schedule saved before this change does not
start a background thread at boot.

What stays is how research starts per product (`/api/research-planes`,
`/api/research`), and the read-only agenda the skill and the MCP server use.
"""

import importlib.util

from fastapi.testclient import TestClient

from app.web import state
from app.web.app import create_app
from app.web.settings import Settings


def _settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


def test_no_endpoint_starts_a_top_n_run(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert client.post("/api/agenda/run", json={"rows": 3}).status_code == 404


def test_no_endpoint_reads_or_sets_a_schedule(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert client.get("/api/schedule").status_code == 404
        assert client.put("/api/schedule", json={"enabled": True}).status_code == 404
        assert client.post("/api/schedule/check").status_code == 404


def test_a_schedule_saved_earlier_starts_nothing_at_boot(tmp_path):
    settings = _settings(tmp_path)
    conn = state.connect(settings.app_state_path)
    try:
        # What the old PUT stored. The key is left in place (user data) and
        # simply never read.
        state.put_settings(conn, {"schedule": {"enabled": True, "every_hours": 1}})
    finally:
        conn.close()
    app = create_app(settings)
    with TestClient(app):
        assert not hasattr(app.state, "schedule")


def test_the_scheduler_module_is_gone():
    assert importlib.util.find_spec("app.web.schedule") is None


def test_the_reads_the_skill_and_per_product_runs_use_stay(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert client.get("/api/agenda").status_code == 200
        assert client.get("/api/research-planes").status_code == 200
