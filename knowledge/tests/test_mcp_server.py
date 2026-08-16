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
    monkeypatch.setattr(server, "GENERATIONS_DIR", tmp_path / "generations")
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


# ── Quote grounding (B23) ─────────────────────────────────────────────────────
#
# add_evidence used to set quote_grounded=bool(quote): any string counted as
# grounded, so a fabricated citation was indistinguishable from a real one. The
# quote must actually appear in the document the agent submitted.


def test_quote_grounded_ignores_case_and_whitespace():
    raw = "The DQ200 hydraulic\naccumulator   fails early."
    assert server._quote_grounded("hydraulic accumulator FAILS early", raw)


def test_quote_grounded_rejects_text_not_in_the_document():
    raw = "The DQ200 hydraulic accumulator fails early."
    assert not server._quote_grounded("mechatronic unit fails at 60k km", raw)


def test_add_evidence_rejects_a_fabricated_quote_and_writes_nothing(env):
    d = server.add_document("https://a", "page",
                            "The DQ200 hydraulic accumulator fails early.",
                            target_hint="k9k")
    out = server.add_evidence(d["doc_id"], "Invented failure", severity="high",
                              domain="transmission",
                              quote="mechatronic unit fails at 60k km")
    assert "error" in out
    conn = db.connect(server.LEDGER_PATH)
    n = conn.execute("SELECT COUNT(*) c FROM evidence").fetchone()["c"]
    conn.close()
    assert n == 0


def test_add_evidence_accepts_a_quote_present_in_the_document(env):
    d = server.add_document("https://a", "page",
                            "The DQ200 hydraulic accumulator fails early.",
                            target_hint="k9k")
    out = server.add_evidence(d["doc_id"], "DQ200 accumulator failure",
                              severity="high", domain="transmission",
                              quote="hydraulic accumulator fails early")
    assert out.get("created") is True


def test_add_evidence_still_allows_an_empty_quote(env):
    """An absent quote is a gap, not a fabrication — it stays ungrounded."""
    d = server.add_document("https://a", "page", "some text", target_hint="k9k")
    out = server.add_evidence(d["doc_id"], "No quote", severity="low",
                              domain="engine")
    assert out.get("created") is True
    conn = db.connect(server.LEDGER_PATH)
    row = conn.execute("SELECT quote_grounded FROM evidence WHERE id=?",
                       (out["evidence_id"],)).fetchone()
    conn.close()
    assert not row["quote_grounded"]


# ── onboard_model / submit_trims (B23) ────────────────────────────────────────


def _trim(**over):
    t = {"id": "meg4_k9k_110", "generation": "IV", "engine_code": "K9K",
         "engine_family": "k9k", "fuel": "diesel", "displacement_cc": 1461,
         "power_min_hp": 110, "power_max_hp": 110, "transmission": "manual",
         "transmission_code": "manual", "year_from": 2016, "year_to": 2020,
         "notes": "1.5 dCi 110"}
    t.update(over)
    return t


def test_onboard_model_reports_a_missing_scaffold(env):
    out = server.onboard_model("renault", "megane_4")
    assert out["has_variants"] is False
    assert out["has_fitment"] is False
    assert out["parts"] == []


def test_submit_trims_writes_variants_and_fitment(env):
    out = server.submit_trims("renault", "megane_4", [_trim()],
                              source_urls=["https://specs.example/megane"])
    assert out.get("errors") in (None, [])
    assert (env / "variants" / "renault_megane_4.yaml").exists()
    assert (env / "fitment" / "renault_megane_4.yaml").exists()
    assert out["rows_written"] == 1


def test_submit_trims_rejects_invalid_rows_without_writing(env):
    out = server.submit_trims("renault", "megane_4", [_trim(fuel="steam")],
                              source_urls=[])
    assert out["errors"]
    assert not (env / "variants" / "renault_megane_4.yaml").exists()


def test_submit_trims_records_spec_sources_in_the_ledger(env):
    server.submit_trims("renault", "megane_4", [_trim()],
                        source_urls=["https://specs.example/megane"])
    conn = db.connect(server.LEDGER_PATH)
    rows = conn.execute(
        "SELECT url, source_type, target_hint FROM documents").fetchall()
    conn.close()
    assert any(r["source_type"] == "spec"
               and r["target_hint"] == "renault_megane_4" for r in rows)


def test_submit_trims_reports_rows_left_draft(env):
    t = _trim(id="meg4_unsourced")
    del t["power_min_hp"], t["power_max_hp"]
    out = server.submit_trims("renault", "megane_4", [t], source_urls=[])
    assert out["rows_draft"] == 1


def test_onboard_model_lists_part_work_after_scaffolding(env):
    server.submit_trims("renault", "megane_4",
                        [_trim(engine_family="k9k")], source_urls=[])
    out = server.onboard_model("renault", "megane_4")
    assert out["has_variants"] is True
    parts = {p["part_id"]: p["state"] for p in out["parts"]}
    assert parts["k9k"] == "zero_claim"  # stub exists in the fixture, no claims


def test_onboard_model_flags_a_part_with_no_yaml_as_missing(env):
    server.submit_trims("renault", "megane_4",
                        [_trim(engine_family="nonexistent_engine")],
                        source_urls=[])
    out = server.onboard_model("renault", "megane_4")
    parts = {p["part_id"]: p["state"] for p in out["parts"]}
    assert parts["nonexistent_engine"] == "missing"


# ── Generation research: phase 1 of onboarding (B23) ─────────────────────────


def _g(**over):
    d = {"generation": 1, "name": "I (GA)", "year_from": 2016, "year_to": 2023,
         "source_urls": ["https://example.invalid/q2"]}
    d.update(over)
    return d


def test_list_generations_is_empty_before_research(env):
    assert server.list_generations("audi", "q2")["generations"] == []
    assert server.list_generations("audi", "q2")["researched"] is False


def test_submit_generations_writes_a_lineup(env):
    out = server.submit_generations("audi", "q2", [_g(), _g(generation=2,
                                    year_from=2024, year_to=None)])
    assert out["errors"] == []
    assert out["keys"] == ["q2_1", "q2_2"]
    got = server.list_generations("audi", "q2")
    assert got["researched"] is True
    assert [x["generation"] for x in got["generations"]] == [1, 2]


def test_submit_generations_rejects_an_unsourced_lineup(env):
    out = server.submit_generations("audi", "q2", [_g(source_urls=[])])
    assert out["errors"]
    assert server.list_generations("audi", "q2")["researched"] is False


def test_submit_generations_resolves_a_scraped_display_name(env):
    out = server.submit_generations(
        "volkswagen", "VW CC 1.4 TSI", [_g()], canonical_model="passat_cc")
    assert out["model"] == "passat_cc"
    assert server.list_generations("volkswagen", "VW CC 1.4 TSI")["researched"]
