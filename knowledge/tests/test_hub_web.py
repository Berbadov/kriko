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


def test_state_snapshot_shape(client):
    s = client.get("/api/state").json()
    for k in ("counts", "spend", "pending", "parts", "documents",
              "findings", "runs"):
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
