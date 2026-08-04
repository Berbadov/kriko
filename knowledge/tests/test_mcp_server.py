"""MCP server tools — the $0 agent path end to end.

The kriko_research agent's whole loop is: add_document -> add_evidence ->
run_pipeline_pass. These tests pin that loop against a tmp ledger: writes
are idempotent, agent evidence lands with extractor_version=1, the verdict
pass is deterministic (model='import', $0), LLM-eligible evidence is left
pending, and the pass is logged at model='agent' with usd=0.
"""

import json

import pytest

from knowledge.ledger import db, verdict
from knowledge.mcp import server

DATA_STUB = """part_id: k9k
title: Renault K9K 1.5 dCi
claims: []
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "parts" / "engine").mkdir(parents=True)
    (data / "variants" / "engine").mkdir(parents=True)
    (data / "fitment").mkdir(parents=True)
    (data / "parts" / "engine" / "k9k.yaml").write_text(DATA_STUB)
    monkeypatch.setattr(server, "LEDGER_PATH", tmp_path / "ledger.db")
    monkeypatch.setattr(server, "EXPORT_DIR", tmp_path / "export")
    monkeypatch.setattr(server, "DATA_DIR", data)
    return data


def _seed_agent_evidence() -> dict:
    d = server.add_document(
        "https://example.com/k9k-timing", "page",
        "K9K timing belt failures cluster around 120k km.", target_hint="k9k")
    e = server.add_evidence(
        d["doc_id"], "K9K timing belt premature wear", severity="high",
        domain="engine", rationale="Known weakness on K9K diesel units.",
        inspection_advice="Check belt replacement history.",
        quote="belt failures cluster around 120k km", component_hint="k9k")
    return {"doc": d, "ev": e}


def test_add_document_is_hash_idempotent(env):
    d1 = server.add_document("https://a", "page", "same text", target_hint="k9k")
    d2 = server.add_document("https://b", "page", "same text", target_hint="k9k")
    assert d1["created"] is True and d2["created"] is False
    assert d1["doc_id"] == d2["doc_id"]
    assert server.add_document("", "page", "text")["error"]


def test_add_evidence_writes_agent_version_and_dedupes(env):
    d = server.add_document("https://a", "page", "text", target_hint="k9k")
    e1 = server.add_evidence(d["doc_id"], "T", severity="high", domain="engine",
                             component_hint="k9k")
    e2 = server.add_evidence(d["doc_id"], "T", severity="high", domain="engine")
    assert e1["created"] is True and e2["created"] is False
    assert e1["evidence_id"] == e2["evidence_id"]
    assert server.add_evidence(d["doc_id"], "X", severity="extreme")["error"]
    conn = db.connect(server.LEDGER_PATH)
    row = conn.execute("SELECT extractor_version FROM evidence WHERE id=?",
                       (e1["evidence_id"],)).fetchone()
    conn.close()
    assert row["extractor_version"] == verdict.AGENT_EXTRACTOR_VERSION


def test_agent_loop_produces_import_verdict_at_zero_cost(env):
    _seed_agent_evidence()
    stats = server.run_pipeline_pass()
    assert stats["verdicts"] >= 1
    assert stats["exported"] >= 1
    conn = db.connect(server.LEDGER_PATH)
    row = conn.execute("SELECT model, usd FROM verdicts LIMIT 1").fetchone()
    run = conn.execute("SELECT model, usd FROM runs WHERE stage='agent_pass'"
                       ).fetchone()
    conn.close()
    assert row["model"] == "import"
    assert row["usd"] == 0
    assert run is not None and run["model"] == "agent" and run["usd"] == 0


def test_llm_evidence_never_gets_import_verdict(env):
    _seed_agent_evidence()
    server.run_pipeline_pass()
    conn = db.connect(server.LEDGER_PATH)
    d = conn.execute("SELECT id FROM documents LIMIT 1").fetchone()
    llm_ev = db.insert_evidence(
        conn, doc_id=d["id"],
        claim={"title": "fresh LLM finding", "domain": "engine",
               "severity": "high"},
        span_start=None, span_end=None, extractor_version=2)
    conn.execute("INSERT INTO resolutions VALUES (?,?,?,?)",
                 (llm_ev, "k9k", "alias", 1))
    conn.execute("INSERT INTO clusters (component_id, domain, cluster_version)"
                 " VALUES ('k9k','engine',1)")
    conn.execute("INSERT INTO cluster_members VALUES (?, ?)",
                 (conn.execute("SELECT MAX(id) FROM clusters").fetchone()[0],
                  llm_ev))
    conn.commit()
    conn.close()
    saved = server.run_pipeline_pass()
    conn = db.connect(server.LEDGER_PATH)
    pending = verdict.pending_clusters(conn)
    conn.close()
    assert saved["verdicts"] == 0
    assert len(pending) == 1  # the LLM-eligible cluster stays pending


def test_pending_verdicts_splits_deterministic_vs_llm(env):
    from knowledge.ledger import cluster, resolve
    _seed_agent_evidence()
    conn = db.connect(server.LEDGER_PATH)
    resolve.resolve_all(conn)
    cluster.rebuild_clusters(conn)
    conn.close()
    p = server.pending_verdicts()
    assert p["import_ready"] >= 1
    assert p["est_usd"] >= 0


def test_get_part_and_coverage_report_read_stub(env):
    part = server.get_part("k9k")
    assert part["part_id"] == "k9k"
    assert part["part_type"] == "engine"
    rep = server.coverage_report()
    assert isinstance(rep, list)


def test_remediate_import_only_runs_without_budget(env):
    _seed_agent_evidence()
    stats = server.run_remediate_import_only()
    assert stats["verdicts"] >= 1
    assert "lost_ingested" in stats


def test_spend_summary_reports_agent_rows(env):
    _seed_agent_evidence()
    server.run_pipeline_pass()
    s = server.spend_summary()
    stages = {r["stage"] for r in s["rows"]}
    assert "agent_pass" in stages
    assert s["total_usd"] == 0
