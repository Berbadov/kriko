"""Offline tests for the NHTSA structured feed — recorded responses, no HTTP."""

import pytest

from knowledge.ledger import db, resolve
from knowledge.ledger.feeds import nhtsa


def _recall(campaign, component, summary, year="2015"):
    return {"NHTSACampaignNumber": campaign, "Component": component,
            "Summary": summary, "Consequence": "May increase crash risk.",
            "Remedy": "Dealer will repair free of charge.",
            "ModelYear": year, "ReportReceivedDate": "01/01/2020"}


def _getter_by_url(payloads):
    def get(url):
        for frag, payload in payloads.items():
            if frag in url:
                return {"results": payload}
        return {"results": []}
    return get


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "l.db")


def test_classify_component_routing():
    assert nhtsa._classify("POWER TRAIN:AUTOMATIC TRANSMISSION") == ("transmission", "alias")
    assert nhtsa._classify("ENGINE AND ENGINE COOLING") == ("engine", "alias")
    assert nhtsa._classify("ELECTRICAL SYSTEM:SOFTWARE") == ("electrical", "elec")
    assert nhtsa._classify("AIR BAGS:FRONTAL") == ("body", "body")
    assert nhtsa._classify("SERVICE BRAKES, HYDRAULIC") == ("brakes", "body")
    assert nhtsa._classify("UNKNOWN THING") == ("general", "body")


def test_ingest_writes_structured_doc_and_evidence(conn):
    getter = _getter_by_url({"make=volkswagen": [
        _recall("18V464000", "STEERING:COLUMN LOCK", "Silicate build-up on switch."),
        _recall("16V913000", "AIR BAGS:FRONTAL", "Airbag may not deploy."),
    ]})
    s = nhtsa.ingest_recalls(conn, "volkswagen", "golf_7", us_model="golf",
                             getter=getter)
    assert s["ingested"] == 2
    rows = conn.execute(
        "SELECT url, source_type, site_or_channel, target_hint FROM documents"
        " ORDER BY url").fetchall()
    assert {r["source_type"] for r in rows} == {"structured"}
    assert {r["site_or_channel"] for r in rows} == {"NHTSA"}
    ev = conn.execute("SELECT title, domain, severity, quote_grounded,"
                      " extractor_version FROM evidence ORDER BY title").fetchall()
    assert len(ev) == 2
    assert all(e["severity"] == "high" for e in ev)
    assert all(e["quote_grounded"] == 1 for e in ev)
    assert all(e["extractor_version"] == nhtsa.FEEDS_EXTRACTOR_VERSION for e in ev)
    domains = {e["domain"] for e in ev}
    assert domains == {"suspension", "body"}


def test_ingest_dedups_across_years_and_reruns(conn):
    same = _recall("18V464000", "STEERING:COLUMN LOCK", "Silicate build-up.")
    getter = lambda url: {"results": [same]}
    s1 = nhtsa.ingest_recalls(conn, "volkswagen", "golf_7", us_model="golf",
                              getter=getter)
    s2 = nhtsa.ingest_recalls(conn, "volkswagen", "golf_7", us_model="golf",
                              getter=getter)
    assert s1["ingested"] == 1                     # 8 years, one campaign
    assert s2["ingested"] == 0
    assert conn.execute("SELECT count(*) FROM evidence").fetchone()[0] == 1


def test_resolution_routes_body_recall_and_alias_recall(conn):
    getter = _getter_by_url({"make=volkswagen": [
        _recall("16V913000", "AIR BAGS:FRONTAL", "Airbag may not deploy."),
        _recall("19V099000", "POWER TRAIN:AUTOMATIC TRANSMISSION",
                "The DQ200 7-speed DSG mechatronic unit may lose pressure."),
    ]})
    nhtsa.ingest_recalls(conn, "volkswagen", "golf_7", us_model="golf",
                         getter=getter)
    counts = resolve.resolve_all(conn)
    by_ev = dict(conn.execute(
        "SELECT r.evidence_id, r.component_id FROM resolutions r").fetchall())
    comps = sorted(by_ev.values())
    # airbag recall → golf7_body via part hint; DQ200 recall → dq200 via alias
    assert comps == ["dq200", "golf7_body"]
    assert counts["alias"] >= 1 and counts["hint"] >= 1


def test_catalog_models_reads_variants_dir():
    models = nhtsa.catalog_models()
    assert ("volkswagen", "golf_7") in models
    assert ("renault", "megane_4") in models


def test_fetch_errors_are_counted_not_fatal(conn):
    def boom(url):
        raise RuntimeError("network down")
    s = nhtsa.ingest_recalls(conn, "volkswagen", "golf_7", us_model="golf",
                             getter=boom)
    assert s["errors"] == s["years"] > 0
    assert s["ingested"] == 0
