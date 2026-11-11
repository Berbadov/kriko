"""Saved cost estimates: `/api/estimates` — the Estimate screen's persistence.

An estimate is the reader's own decision record (which equipment, how many, at
what price, over how many years), so it lives in `app.sqlite`, survives a
restart, and is exactly what the window exports to Excel/CSV.
"""

from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings


def _client(tmp_path):
    return TestClient(
        create_app(
            Settings(
                store_path=tmp_path / "knowledge.sqlite",
                app_state_path=tmp_path / "app.sqlite",
                analysis_log_path=tmp_path / "analyses.jsonl",
            )
        )
    )


def _line(subject="drill-1", label="Makita DHP484", quantity=2, unit_price=249.0):
    return {"subject_id": subject, "pack_id": "tools", "label": label,
            "quantity": quantity, "unit_price": unit_price, "note": ""}


def test_an_estimate_is_saved_with_its_lines_and_read_back(tmp_path):
    client = _client(tmp_path)
    body = client.post("/api/estimates", json={
        "name": "Workshop fit-out", "currency": "EUR", "years": 7,
        "maintenance_pct": 6.5, "discount_pct": 9.0,
        "lines": [_line(), _line("saw-1", "Festool KS 60", 1, 549.0)],
    }).json()
    estimate = body["estimate"]
    assert estimate["name"] == "Workshop fit-out"
    assert estimate["currency"] == "EUR"
    assert [l["label"] for l in estimate["lines"]] == ["Makita DHP484", "Festool KS 60"]
    assert estimate["lines"][0]["quantity"] == 2
    assert estimate["lines"][0]["unit_price"] == 249.0

    listed = client.get("/api/estimates").json()["items"]
    assert [i["estimate_id"] for i in listed] == [estimate["estimate_id"]]
    assert listed[0]["lines"] == 2

    again = _client(tmp_path).get(f"/api/estimates/{estimate['estimate_id']}").json()
    assert again["estimate"] == estimate


def test_saving_again_replaces_the_lines_rather_than_merging(tmp_path):
    client = _client(tmp_path)
    estimate = client.post("/api/estimates", json={
        "name": "First", "lines": [_line(), _line("saw-1", "Saw", 1, 100.0)],
    }).json()["estimate"]
    updated = client.post("/api/estimates", json={
        "estimate_id": estimate["estimate_id"], "name": "Second", "lines": [_line()],
    }).json()["estimate"]
    assert updated["estimate_id"] == estimate["estimate_id"]
    assert updated["name"] == "Second"
    assert [l["label"] for l in updated["lines"]] == ["Makita DHP484"]
    assert len(_client(tmp_path).get("/api/estimates").json()["items"]) == 1


def test_a_line_without_a_price_is_kept_as_null_not_zero(tmp_path):
    """Null means "no price known yet"; zero would read as free, and an
    accountant's file must not say free for something unpriced."""
    client = _client(tmp_path)
    line = _line()
    line["unit_price"] = None
    estimate = client.post("/api/estimates", json={"name": "X", "lines": [line]}).json()["estimate"]
    assert estimate["lines"][0]["unit_price"] is None


def test_an_estimate_can_be_deleted_and_a_gone_one_is_404(tmp_path):
    client = _client(tmp_path)
    estimate = client.post("/api/estimates", json={"name": "X", "lines": []}).json()["estimate"]
    path = f"/api/estimates/{estimate['estimate_id']}"
    assert client.delete(path).json() == {"deleted": estimate["estimate_id"]}
    assert client.get(path).status_code == 404
    assert client.delete(path).status_code == 404
    assert client.get("/api/estimates").json()["items"] == []


def test_updating_an_unknown_estimate_is_a_404_not_a_new_row(tmp_path):
    client = _client(tmp_path)
    reply = client.post("/api/estimates", json={"estimate_id": "nope", "name": "X"})
    assert reply.status_code == 404
    assert client.get("/api/estimates").json()["items"] == []


def test_the_bounds_hold_against_a_pasted_payload(tmp_path):
    """The schema rejects out-of-range values; the state layer clamps whatever
    still gets through (it is also called by non-HTTP writers), so the stored
    row is bounded either way."""
    client = _client(tmp_path)
    reply = client.post("/api/estimates", json={
        "name": "x" * 5000, "years": 999, "maintenance_pct": -5,
        "discount_pct": 250, "lines": [_line() for _ in range(500)],
    })
    assert reply.status_code == 422

    from app.web import state
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        saved = state.save_estimate(conn, {
            "name": "ok", "years": 99, "maintenance_pct": 500, "discount_pct": -1,
            "lines": [_line() for _ in range(500)],
        })
        assert saved["years"] == 30
        assert saved["maintenance_pct"] == 100.0
        assert saved["discount_pct"] == 0.0
        assert len(saved["lines"]) == state.ESTIMATE_MAX_LINES
    finally:
        conn.close()


def test_a_line_keeps_its_label_even_when_the_subject_is_not_installed(tmp_path):
    """The export must not depend on the catalog still containing the product:
    the label travels with the line."""
    client = _client(tmp_path)
    line = _line(subject="gone-1", label="Discontinued thing")
    estimate = client.post("/api/estimates", json={"name": "X", "lines": [line]}).json()["estimate"]
    assert estimate["lines"][0]["label"] == "Discontinued thing"
