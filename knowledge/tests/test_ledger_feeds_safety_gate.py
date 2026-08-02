"""Offline tests for the EU Safety Gate structured feed -- no HTTP.

The getter is injected with raw XML bytes (the weekly index + per-week detail
payloads), so the tests exercise the real XML parsing path, not a fake JSON
shape."""

import pytest

from knowledge.ledger import db
from knowledge.ledger.feeds import safety_gate

_WEEKLY_INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<Safety-Gate>
  <weeklyReport>
    <reference>Report-2026-30</reference>
    <URL>https://sg.test/weekly/detail/1</URL>
  </weeklyReport>
  <weeklyReport>
    <reference>Report-2026-29</reference>
    <URL>https://sg.test/weekly/detail/2</URL>
  </weeklyReport>
  <weeklyReport>
    <reference>Report-2026-28</reference>
    <URL>https://sg.test/weekly/detail/3</URL>
  </weeklyReport>
</Safety-Gate>"""


def _notif(case, product, brand, category, danger, url):
    return {
        "case": case, "product": product, "brand": brand,
        "category": category, "danger": danger, "url": url,
    }


def _weekly_xml(notifications):
    parts = []
    for n in notifications:
        parts.append(
            "<notifications>"
            f"<caseNumber>{n['case']}</caseNumber>"
            f"<category><![CDATA[{n['category']}]]></category>"
            f"<product><![CDATA[{n['product']}]]></product>"
            f"<brand><![CDATA[{n['brand']}]]></brand>"
            f"<danger><![CDATA[{n['danger']}]]></danger>"
            f"<reference><![CDATA[{n['url']}]]></reference>"
            "</notifications>"
        )
    body = "".join(parts)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Safety-Gate><report_week>30</report_week>{body}</Safety-Gate>""".encode()


def _getter(reports):
    def get(url):
        if url == safety_gate.INDEX_URL:
            return _WEEKLY_INDEX
        return reports[url]
    return get


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "l.db")


def test_classify_brake_keyword():
    assert safety_gate._classify("brake failure recall") == ("brakes", "body")


def test_classify_airbag_keyword():
    assert safety_gate._classify("airbag deployment issue") == ("body", "body")


def test_classify_engine_keyword():
    assert safety_gate._classify("engine overheating") == ("engine", "alias")


def test_classify_unknown():
    assert safety_gate._classify("unknown issue") == ("general", "body")


def test_fetch_filters_by_brand():
    getter = _getter({
        "https://sg.test/weekly/detail/1": _weekly_xml([
            _notif("SR/001/26", "Megane", "Renault", "Motor vehicles",
                   "Brake recall", "https://sg.test/alert/1"),
        ]),
        "https://sg.test/weekly/detail/2": _weekly_xml([
            _notif("SR/002/26", "Corolla", "Toyota", "Motor vehicles",
                   "Airbag fault", "https://sg.test/alert/2"),
        ]),
        "https://sg.test/weekly/detail/3": _weekly_xml([
            _notif("SR/003/26", "Golf", "Volkswagen", "Motor vehicles",
                   "Brake recall", "https://sg.test/alert/3"),
        ]),
    })
    alerts = safety_gate.fetch_alerts("renault", "megane_4", getter=getter, delay=0)
    assert len(alerts) == 1
    assert alerts[0]["referenceNumber"] == "SR/001/26"
    assert alerts[0]["url"] == "https://sg.test/alert/1"
    assert alerts[0]["title"] == "Megane"


def test_ingest_writes_structured_doc_and_evidence(conn):
    getter = _getter({
        "https://sg.test/weekly/detail/1": _weekly_xml([
            _notif("SR/001/26", "Megane", "Renault", "Motor vehicles",
                   "Rear brake caliper may seize.", "https://sg.test/alert/1"),
        ]),
        "https://sg.test/weekly/detail/2": _weekly_xml([
            _notif("SR/002/26", "Clio", "Renault", "Motor vehicles",
                   "Driver airbag may not deploy.", "https://sg.test/alert/2"),
        ]),
        "https://sg.test/weekly/detail/3": _weekly_xml([]),
    })
    s = safety_gate.ingest_alerts(conn, "renault", "megane_4", getter=getter)
    assert s["ingested"] == 2
    rows = conn.execute(
        "SELECT url, source_type, site_or_channel FROM documents ORDER BY url"
    ).fetchall()
    assert all(r["source_type"] == "structured" for r in rows)
    assert all(r["site_or_channel"] == "EU Safety Gate" for r in rows)
    ev = conn.execute(
        "SELECT title, severity, quote_grounded FROM evidence ORDER BY title"
    ).fetchall()
    assert len(ev) == 2
    assert all(e["severity"] == "high" for e in ev)
    assert all(e["quote_grounded"] == 1 for e in ev)


def test_ingest_dedups_on_rerun(conn):
    xml = _weekly_xml([
        _notif("SR/010/26", "Megane", "Renault", "Motor vehicles",
               "Same description", "https://sg.test/alert/10"),
    ])
    getter = _getter({
        "https://sg.test/weekly/detail/1": xml,
        "https://sg.test/weekly/detail/2": _weekly_xml([]),
        "https://sg.test/weekly/detail/3": _weekly_xml([]),
    })
    s1 = safety_gate.ingest_alerts(conn, "renault", "megane_4", getter=getter)
    s2 = safety_gate.ingest_alerts(conn, "renault", "megane_4", getter=getter)
    assert s1["ingested"] == 1
    assert s2["ingested"] == 0


def test_broken_week_is_skipped_not_fatal(conn):
    def get(url):
        if url == safety_gate.INDEX_URL:
            return _WEEKLY_INDEX
        if url == "https://sg.test/weekly/detail/2":
            raise RuntimeError("network down")
        return _weekly_xml([
            _notif("SR/020/26", "Megane", "Renault", "Motor vehicles",
                   "Steering may fail.", "https://sg.test/alert/20"),
            _notif("SR/021/26", "Clio", "Renault", "Motor vehicles",
                   "Wiper defect.", "https://sg.test/alert/21"),
        ])
    s = safety_gate.ingest_alerts(conn, "renault", "megane_4", getter=get)
    # The failed week is skipped, the surviving weeks still ingest.
    assert s["ingested"] == 2
    assert s["errors"] == 0


def test_fetch_errors_counted_not_fatal(conn):
    def boom(url):
        raise RuntimeError("network down")
    s = safety_gate.ingest_alerts(conn, "renault", "megane_4", getter=boom)
    assert s["errors"] > 0
    assert s["ingested"] == 0


def test_catalog_models_reads_variants_dir():
    models = safety_gate.catalog_models()
    assert ("volkswagen", "golf_7") in models
    assert ("renault", "megane_4") in models
