"""Offline tests for the TR SGM structured feed -- no HTTP."""

import pytest

from knowledge.ledger import db
from knowledge.ledger.feeds import recalls_tr


def _recall(number, component, summary, year="2018"):
    return {"recallNumber": number, "component": component, "summary": summary,
            "consequence": "May increase crash risk.", "remedy": "Free repair.",
            "modelYear": year}


def _getter(payloads):
    def get(url):
        for kw, recs in payloads.items():
            if kw.lower() in url.lower():
                return {"recalls": recs}
        return {"recalls": []}
    return get


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "l.db")


def test_classify_brake():
    assert recalls_tr._classify("fren kaliperi ariza") == ("brakes", "body")


def test_classify_engine():
    assert recalls_tr._classify("motor ariza") == ("engine", "alias")


def test_classify_unknown():
    assert recalls_tr._classify("unknown component") == ("general", "body")


def test_ingest_writes_structured_doc_and_evidence(conn):
    g = _getter({"renault": [
        _recall("TR-2020-001", "motor", "Engine overheating risk"),
        _recall("TR-2020-002", "fren", "Brake caliper may seize"),
    ]})
    s = recalls_tr.ingest_recalls(conn, "renault", "megane_4", getter=g)
    assert s["ingested"] == 2
    ev = conn.execute("SELECT title, severity FROM evidence ORDER BY title").fetchall()
    assert len(ev) == 2
    assert all(e["severity"] == "high" for e in ev)


def test_ingest_dedups_on_rerun(conn):
    same = _recall("TR-2020-001", "motor", "Same issue")
    g = lambda url: {"recalls": [same]}
    s1 = recalls_tr.ingest_recalls(conn, "renault", "megane_4", getter=g)
    s2 = recalls_tr.ingest_recalls(conn, "renault", "megane_4", getter=g)
    assert s1["ingested"] == 1
    assert s2["ingested"] == 0


def test_fetch_errors_counted_not_fatal(conn):
    def boom(url):
        raise RuntimeError("network down")
    s = recalls_tr.ingest_recalls(conn, "renault", "megane_4", getter=boom)
    assert s["errors"] > 0
    assert s["ingested"] == 0


def test_catalog_models_reads_variants_dir():
    models = recalls_tr.catalog_models()
    assert ("volkswagen", "golf_7") in models
    assert ("renault", "megane_4") in models
