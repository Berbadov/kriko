from datetime import UTC, datetime, timedelta

from app import productinsights
from app.tests.test_web import client as catalog_client
from kriko.store.db import connect

client = catalog_client


def test_batch_is_local_bounded_and_does_not_fill_history(client):
    before = client.get("/api/history").json()["items"]
    reply = client.post("/api/products/scan", json={"items": [
        {"name": "Makita DHP484", "url": "https://toolshop.invalid/item/tool"},
        {"name": "Never Seen Product"},
        {"name": "Widget Bit"},
    ]})
    assert reply.status_code == 200
    items = reply.json()["items"]
    assert items[0]["level"] == "high"
    assert items[1]["level"] == "unknown"
    assert items[2]["level"] == "low"
    assert client.get("/api/history").json()["items"] == before
    assert client.post("/api/products/scan", json={"items": [{}] * 61}).status_code == 422


def test_url_scan_prefers_saved_canonical_url_and_never_fetches_page(client):
    saved = client.post("/api/analyze", json={
        "url": "https://toolshop.invalid/item/1?utm_source=old", "title": "Makita drill",
        "fields": {"brand": "makita", "model": "DHP484"},
    }).json()
    result = client.post("/api/products/scan", json={"items": [
        {"url": "https://toolshop.invalid/item/1?utm_source=new#tab"},
        {"url": "https://shop.invalid/Makita-DHP484"},
    ]}).json()["items"]
    assert result[0]["lookup_id"] == saved["lookup_id"]
    assert result[0]["basis"] == "saved page check"
    assert result[1]["level"] in ("uncertain", "unknown")
    assert result[1]["basis"].startswith("URL words only")


def test_freshness_uses_oldest_evidence_not_the_saved_check_date(client):
    store = connect(client.store_path)
    old = (datetime.now(UTC) - timedelta(days=45)).isoformat()
    new = datetime.now(UTC).isoformat()
    store.execute("UPDATE sources SET retrieved_at = ?", (new,))
    store.execute("UPDATE sources SET retrieved_at = ? WHERE url = 'https://e.invalid/x'", (old,))
    store.commit()
    claims = [{"pack_id": "tools", "sources": [{"url": "https://e.invalid/x"}, {"url": "https://f.invalid/y"}]}]
    fresh = productinsights.freshness(store, claims)
    assert fresh["last_verified"] == old
    assert fresh["stale"]
    assert not productinsights.freshness(store, claims, days=90)["stale"]
    store.execute("UPDATE sources SET retrieved_at = '' WHERE url = 'https://f.invalid/y'")
    store.commit()
    assert productinsights.freshness(store, claims, days=90)["undated_sources"] == 1
    assert productinsights.freshness(store, [], days=90)["stale"]
    store.close()


def test_costs_keep_repair_quotes_and_currencies_separate():
    costs = productinsights.costs([
        {"title": "Bearing", "sources": [{"url": "https://maker.invalid/part", "quote": "Product is $900. Replacement kit costs 30 EUR plus labour."}]},
        {"title": "Motor", "sources": [{"url": "https://maker.invalid/motor", "quote": "Replacement costs $400.", "stance": "refutes"}]},
        {"title": "Board", "sources": [{"url": "javascript:alert(1)", "quote": "Repair costs $20."}]},
    ])
    assert len(costs["items"]) == 1
    assert costs["items"][0]["prices"] == ["30 EUR"]
    assert costs["missing"] == ["Motor", "Board"]


def test_report_retains_sources_and_escapes_untrusted_text(client):
    saved = client.post("/api/lookup", json={"identity": {"brand": "makita", "model": "DHP484"}}).json()
    lookup_id = saved["lookup_id"]
    report = client.get(f"/api/products/checks/{lookup_id}/report")
    assert report.status_code == 200
    assert "text/html" in report.headers["content-type"]
    assert "attachment" in report.headers["content-disposition"]
    assert "https://e.invalid/x" in report.text
    assert "Packs past 400 hours drift." in report.text
    data = client.get(f"/api/products/checks/{lookup_id}/report-data").json()
    assert data["html"] == report.text
    row = {"label": '<script>alert(1)</script>', "response": {"claims": [{"title": "<b>title</b>", "sources": [{"url": "javascript:alert(1)", "quote": "<img src=x>"}]}]}}
    html = productinsights.report(row, {"last_verified": None, "stale": True, "basis": "Unknown"}, {"note": "", "items": [], "missing": []})
    assert "<script>" not in html
    assert "javascript:" not in html
    assert "&lt;img" in html
    assert client.get("/api/products/checks/missing/report").status_code == 404


def test_saved_product_can_refresh_after_research_without_resetting_source_dates(client):
    store = connect(client.store_path)
    subject_id = store.execute("SELECT subject_id FROM subjects WHERE label = 'Makita DHP484'").fetchone()[0]
    store.close()
    saved = client.post(f"/api/products/{subject_id}/check").json()
    lookup_id = saved["lookup_id"]
    before = client.get(f"/api/products/checks/{lookup_id}/insights").json()
    assert before["target"]["subject_id"] == subject_id
    refreshed = client.post(f"/api/lookup/{lookup_id}/refresh").json()
    assert refreshed["refreshed"]
    assert refreshed["lookup_id"] == lookup_id
    after = client.get(f"/api/products/checks/{lookup_id}/insights").json()
    assert after["freshness"] == before["freshness"]
