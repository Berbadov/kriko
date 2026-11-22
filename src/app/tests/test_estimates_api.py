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

def _quote(quote_id="q1", vendor="Vendor A", price=100.0, currency="TRY", **extra):
    return {"quote_id": quote_id, "vendor": vendor, "seller": vendor, "url": "",
            "unit_price": price, "currency": currency, "vat_rate": 20.0,
            "vat_included": False, "delivery_days": 7, "warranty_months": 24,
            "quote_date": "2026-11-01", "valid_until": "2026-12-01",
            "note": "", "selected": False, **extra}


def test_quotes_round_trip_and_exactly_one_is_selected(tmp_path):
    client = _client(tmp_path)
    line = _line()
    line["quotes"] = [
        _quote("a", "Alpha", 100.0, selected=True),
        _quote("b", "Beta", 90.0, selected=True),
        _quote("c", "Gamma", 110.0, selected=False, vat_included=True),
    ]
    saved = client.post("/api/estimates", json={
        "name": "Quotes", "currency": "TRY", "vat_rate": 20,
        "lines": [line],
    }).json()["estimate"]
    quotes = saved["lines"][0]["quotes"]
    assert [q["vendor"] for q in quotes] == ["Alpha", "Beta", "Gamma"]
    assert [q["selected"] for q in quotes] == [True, False, False]
    assert quotes[2]["vat_included"] is True
    # the selected quote is what a reader without quote support sees
    assert saved["lines"][0]["unit_price"] == 100.0
    # the response carries a reason for every quote, none of them invented
    for quote in quotes:
        assert quote["risk"]["level"] in ("red", "amber", "green", "unknown")
        assert quote["risk"]["reasons"]
    assert [row["rank"] for row in saved["lines"][0]["ranking"]][0] == 1


def test_a_legacy_price_reads_as_one_migrated_quote(tmp_path):
    client = _client(tmp_path)
    estimate = client.post("/api/estimates", json={
        "name": "Old", "currency": "EUR", "lines": [_line()],
    }).json()["estimate"]
    quotes = estimate["lines"][0]["quotes"]
    assert len(quotes) == 1
    assert quotes[0]["vendor"] == "Migrated price"
    assert quotes[0]["unit_price"] == 249.0
    assert quotes[0]["currency"] == "EUR"
    assert quotes[0]["selected"] is True


def test_a_line_with_no_price_and_no_quote_stays_unpriced(tmp_path):
    client = _client(tmp_path)
    line = _line()
    line["unit_price"] = None
    estimate = client.post("/api/estimates", json={"name": "X", "lines": [line]}).json()["estimate"]
    assert estimate["lines"][0]["quotes"] == []
    assert estimate["lines"][0]["unit_price"] is None


def test_deleting_an_estimate_deletes_its_quotes(tmp_path):
    client = _client(tmp_path)
    line = _line()
    line["quotes"] = [_quote()]
    estimate = client.post("/api/estimates", json={"name": "X", "lines": [line]}).json()["estimate"]
    client.delete(f"/api/estimates/{estimate['estimate_id']}")

    from app.web import state
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        assert conn.execute("SELECT COUNT(*) FROM estimate_quotes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM estimate_lines").fetchone()[0] == 0
    finally:
        conn.close()


def test_fx_and_vat_defaults_are_kept_and_bounded(tmp_path):
    client = _client(tmp_path)
    saved = client.post("/api/estimates", json={
        "name": "Rates", "currency": "TRY", "vat_rate": 10,
        "fx": {"TRY": 1, "EUR": 58.2, "USD": 50.4694, "source": "TCMB",
               "date": "2026-11-19"},
        "lines": [],
    }).json()["estimate"]
    assert saved["vat_rate"] == 10.0
    assert saved["fx"]["EUR"] == 58.2
    assert saved["fx"]["source"] == "TCMB"
    read = client.get(f"/api/estimates/{saved['estimate_id']}").json()["estimate"]
    assert read["fx"] == saved["fx"]


def test_depreciation_fields_survive_a_round_trip(tmp_path):
    client = _client(tmp_path)
    line = _line()
    line.update({"depreciation": "declining_balance", "life_years": 7,
                 "salvage": 500.0, "vuk_rate": 20.0})
    saved = client.post("/api/estimates", json={"name": "Asset", "lines": [line]}).json()["estimate"]
    stored = saved["lines"][0]
    assert stored["depreciation"] == "declining_balance"
    assert stored["life_years"] == 7
    assert stored["salvage"] == 500.0
    assert stored["vuk_rate"] == 20.0


def test_the_list_can_carry_the_newest_estimates_in_full_in_one_read(tmp_path):
    """Five screens want the lines and quote risk; one request must give them."""
    client = _client(tmp_path)
    for index in range(3):
        client.post("/api/estimates", json={
            "name": f"Estimate {index}", "currency": "USD", "years": 3,
            "lines": [_line(f"s{index}", f"Product {index}", 1, 100.0 + index)],
        })
    plain = client.get("/api/estimates").json()
    assert "estimates" not in plain and len(plain["items"]) == 3

    full = client.get("/api/estimates?full=1&limit=2").json()
    assert len(full["items"]) == 2
    assert len(full["estimates"]) == 2
    first = full["estimates"][0]
    assert first["lines"], "the lines come with the list"
    assert [row["estimate_id"] for row in full["estimates"]] == [row["estimate_id"] for row in full["items"]]
    # the same decoration a single read gives: ranking and quote risk
    single = client.get(f"/api/estimates/{first['estimate_id']}").json()["estimate"]
    assert single == first


def test_a_full_list_is_capped_so_it_cannot_be_asked_for_everything(tmp_path):
    client = _client(tmp_path)
    for index in range(25):
        client.post("/api/estimates", json={"name": f"E{index}", "currency": "USD", "lines": [_line(f"s{index}")]})
    full = client.get("/api/estimates?full=1&limit=100").json()
    assert len(full["items"]) == 100 or len(full["items"]) == 25
    assert len(full["estimates"]) == 20
