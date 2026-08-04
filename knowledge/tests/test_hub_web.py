"""kriko-hub web API — the browser dashboard's data plane (B20 web edition).

Requires fastapi (+ httpx for TestClient), i.e. run under the .venv
(.venv/bin/python -m pytest knowledge/tests/test_hub_web.py). The system
python suite skips these via importorskip.
"""

import tempfile
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from knowledge.hub import web  # noqa: E402


@pytest.fixture
def client():
    return TestClient(web.app)


def test_index_serves_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "kriko-hub" in r.text
    assert "/static/hub.js" in r.text and "/static/style.css" in r.text


def test_static_assets_served(client):
    assert client.get("/static/hub.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_state_has_catalog_kpis(client):
    d = client.get("/api/state").json()
    cat = d["catalog"]
    assert set(cat) == {"parts", "variants", "fitment", "claims"}
    assert all(isinstance(v, int) and v >= 0 for v in cat.values())
    assert "findings" not in d  # heavy report stays out of the poll path


def test_coverage_endpoint_on_demand_and_cached(client):
    d = client.get("/api/coverage").json()
    assert isinstance(d["findings"], list)
    assert "ts" in d
    again = client.get("/api/coverage").json()
    assert again["ts"] == d["ts"]  # cached within TTL


def test_table_endpoint_reports_row_count(client):
    d = client.get("/api/table/documents").json()
    assert isinstance(d["count"], int)
    assert "head" in d and "body" in d
    assert client.get("/api/table/nope").status_code == 404


def test_served_js_parses_when_node_available(client):
    """Regression guard: the page's JS must stay syntactically valid. The
    2026-08-04 bug: a \\n escape inside the page string became a literal
    newline in the served script, killing every click handler. Skipped when
    node is not installed."""
    node = __import__("shutil").which("node")
    if not node:
        pytest.skip("node not installed")
    js = client.get("/static/hub.js").text
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(js)
        path = f.name
    r = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_state_snapshot_shape(client):
    s = client.get("/api/state").json()
    for k in ("counts", "spend", "pending", "parts", "documents",
              "catalog", "runs"):
        assert k in s
    assert s["counts"]["documents"] > 0


def test_part_and_doc_routes(client):
    parts = client.get("/api/state").json()["parts"]
    pid = parts[0]["part_id"]
    p = client.get(f"/api/part/{pid}")
    assert p.status_code == 200 and p.json()["part_id"] == pid
    assert client.get("/api/part/nope").status_code == 404
    d = client.get("/api/doc/1")
    assert d.status_code in (200, 404)


def test_table_browser(client):
    r = client.get("/api/table/documents")
    assert r.status_code == 200
    assert "url" in r.json()["head"]
    assert client.get("/api/table/not_a_table").status_code == 404


def test_run_validates_argv(client):
    assert client.post("/api/run", json={"argv": "x"}).status_code == 400
    assert client.post("/api/run", json={"argv": []}).status_code == 400
    assert client.post("/api/run",
                       json={"argv": ["rm", "-rf", "/"]}).status_code == 400


def test_run_report_streams_to_log(tmp_path):
    client = TestClient(web.app)
    db_path = tmp_path / "l.db"
    r = client.post("/api/run", json={"argv": ["report", "--db", str(db_path)]})
    assert r.status_code == 200
    buf = ""
    for _ in range(200):
        lg = client.get("/api/log").json()
        if not lg["running"] and lg["buf"]:
            buf = lg["buf"]
            break
        time.sleep(0.05)
    assert "TOTAL" in buf


def test_stop_idempotent(client):
    r = client.post("/api/stop")
    assert r.status_code == 200
    assert "stopped" in r.json()
