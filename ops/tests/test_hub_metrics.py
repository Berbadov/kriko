"""kriko-hub metrics — the numbers the dashboard shows, pinned by tests.

The hub renders the same tables and estimates as the CLI panel; a regression
in a query or an estimate here shows up as a failing render, not a wrong
dashboard.
"""

import json

from ops.hub import metrics
from knowledge.ledger import db

DATA_STUB = """part_id: k9k
title: Renault K9K 1.5 dCi
claims:
  - title: K9K timing belt premature wear
    severity: high
    domain: engine
"""


def _seed(data_dir):
    (data_dir / "parts" / "engine").mkdir(parents=True)
    (data_dir / "variants" / "engine").mkdir(parents=True)
    (data_dir / "fitment").mkdir(parents=True)
    (data_dir / "parts" / "engine" / "k9k.yaml").write_text(DATA_STUB)
    return data_dir


def test_spend_reports_total_and_split(tmp_path):
    c = db.connect(tmp_path / "l.db")
    c.execute("INSERT INTO runs (started_at, stage, model, calls, tokens_in,"
              " tokens_out, usd) VALUES ('t','extract','deepseek-v4-flash',"
              "10,1000,2000,0.01)")
    c.commit()
    s = metrics.spend(c)
    assert s["total_usd"] == 0.01
    assert s["rows"][0]["stage"] == "extract"
    assert "verdicts_import" in s and "verdicts_llm" in s


def test_pending_on_empty_ledger_is_zero(tmp_path):
    c = db.connect(tmp_path / "l.db")
    p = metrics.pending(c)
    assert p["extract_chunks"] == 0
    assert p["verdict_pending"] == 0
    assert p["import_ready"] == 0 and p["llm"] == 0
    assert p["extract_usd"] == 0.0


def test_parts_and_part_detail_read_stub(tmp_path):
    data = _seed(tmp_path)
    plist = metrics.parts(data)
    assert plist == [{"part_id": "k9k", "part_type": "engine", "claims": 1}]
    detail = metrics.part_detail(data, "k9k")
    assert detail["claims"][0]["title"] == "K9K timing belt premature wear"
    assert metrics.part_detail(data, "nope") is None


def test_documents_round_trip_and_recent_runs(tmp_path):
    c = db.connect(tmp_path / "l.db")
    doc_id = db.insert_document(c, url="https://a", source_type="page",
                                raw_text="text", target_hint="k9k")
    docs = metrics.documents(c)
    assert docs[0]["id"] == doc_id
    got = metrics.document(c, doc_id)
    assert got["raw_text"] == "text"
    assert metrics.document(c, 999) is None
    assert metrics.recent_runs(c) == []


def test_last_remediation_reads_log(tmp_path):
    log = tmp_path / "remediation.jsonl"
    log.write_text(json.dumps({"ts": "t", "parts": [], "usd": 0.0}) + "\n" +
                   json.dumps({"ts": "t2", "parts": ["k9k"], "ingested": 2,
                               "usd": 0.0}))
    last = metrics.last_remediation(log)
    assert last["parts"] == ["k9k"]
    assert metrics.last_remediation(tmp_path / "missing.jsonl") is None


def test_catalog_counts_read_stub_catalog(tmp_path):
    data = _seed(tmp_path)
    c = metrics.catalog_counts(data)
    assert c == {"parts": 1, "variants": 0, "fitment": 0, "claims": 1}


def test_findings_reads_stub_catalog(tmp_path):
    data = _seed(tmp_path)
    f = metrics.findings(data)
    assert isinstance(f, list)
    assert all({"kind", "subject", "message", "part_id", "axis"} <= set(x)
               for x in f)
