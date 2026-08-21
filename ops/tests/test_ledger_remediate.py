"""ledger.remediate — auto-remediation loop driver (B19).

Coverage findings are the trigger: every part-level finding (zero-claim part,
missing part, automatic variant with no real gearbox part) becomes an
unattended acquire → extract → resolve → cluster → verdict → export pass.
No human invokes the research CLI; the loop logs each run to
logs/remediation.jsonl for scheduling decisions.
"""

import json

import yaml

from ops.reports.coverage import Finding, Report, build_report
from knowledge.ledger import db
from ops import remediate


# ── remediation_plan ─────────────────────────────────────────────────────────


def test_plan_maps_zero_claim_finding_to_part_and_type():
    report = Report(findings=[
        Finding("zero_claim_part", "dw5", "part YAML has 0 claims",
                part_id="dw5", axis="transmission"),
    ])
    assert remediate.remediation_plan(report) == [("dw5", "transmission")]


def test_plan_maps_missing_part_via_fitment_axis():
    report = Report(findings=[
        Finding("missing_part", "ghost", "no part YAML",
                part_id="ghost", axis="electrical"),
    ])
    assert remediate.remediation_plan(report) == [("ghost", "electrical")]


def test_plan_maps_auto_variant_no_tx_part_to_transmission():
    report = Report(findings=[
        Finding("auto_variant_no_tx_part", "vid", "no tx part",
                part_id="dc9", axis="transmission"),
    ])
    assert remediate.remediation_plan(report) == [("dc9", "transmission")]


def test_plan_skips_orphan_and_emissions_findings():
    report = Report(findings=[
        Finding("orphan_part", "unused", "no fitment row references this part",
                part_id="unused", axis="engine"),
        Finding("variant_no_emissions", "vid", "diesel without emissions"),
    ])
    assert remediate.remediation_plan(report) == []


def test_plan_dedupes_multiple_findings_for_same_part():
    report = Report(findings=[
        Finding("zero_claim_part", "dw5", "0 claims", part_id="dw5", axis="transmission"),
        Finding("missing_part", "dw5", "no YAML", part_id="dw5", axis="transmission"),
    ])
    assert remediate.remediation_plan(report) == [("dw5", "transmission")]


# ── lost-source ingestion (parity-lost claims' cited pages) ──────────────────


def test_lost_source_urls_collects_only_claims_with_urls(tmp_path, monkeypatch):
    import yaml as _yaml
    from knowledge.ledger.parity import _source_urls

    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "eng1.yaml").write_text(_yaml.dump({
        "part_id": "eng1", "part_type": "engine",
        "claims": [{"claim_key": "new_c", "title": "fresh title", "domain": "engine",
                    "severity": "medium", "status": "review", "rationale": "r",
                    "inspection_advice": "a", "sources": []}],
    }, sort_keys=False))
    legacy_parts = tmp_path / "parts"
    (legacy_parts / "engine").mkdir(parents=True)
    (legacy_parts / "engine" / "eng1.yaml").write_text(_yaml.dump({
        "part_id": "eng1", "part_type": "engine",
        "claims": [
            {"claim_key": "old_sourced", "title": "old sourced claim", "domain": "engine",
             "severity": "medium", "status": "review", "rationale": "r",
             "inspection_advice": "a",
             "sources": [{"source_url": "https://example.com/a"},
                         {"source_url": "https://example.com/b"}]},
            {"claim_key": "old_unsourced", "title": "old unsourced claim", "domain": "engine",
             "severity": "medium", "status": "review", "rationale": "r",
             "inspection_advice": "a", "sources": []},
        ],
    }, sort_keys=False))
    (tmp_path / "claims").mkdir()

    conn = db.connect(tmp_path / "l.db")
    lost = remediate.lost_source_urls(conn, export_dir, tmp_path)
    assert [(u, h) for u, h, _c in lost] == [("example.com/a", "eng1"),
                                              ("example.com/b", "eng1")]
    conn.close()


def test_ingest_lost_sources_fetches_and_ingests(tmp_path, monkeypatch):
    import yaml as _yaml
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "eng1.yaml").write_text(_yaml.dump({
        "part_id": "eng1", "part_type": "engine", "claims": [],
    }, sort_keys=False))
    legacy_parts = tmp_path / "parts"
    (legacy_parts / "engine").mkdir(parents=True)
    (legacy_parts / "engine" / "eng1.yaml").write_text(_yaml.dump({
        "part_id": "eng1", "part_type": "engine",
        "claims": [{"claim_key": "old", "title": "old claim", "domain": "engine",
                    "severity": "medium", "status": "review", "rationale": "r",
                    "inspection_advice": "a",
                    "sources": [{"source_url": "https://example.com/x"}]}],
    }, sort_keys=False))
    (tmp_path / "claims").mkdir()

    monkeypatch.setattr("knowledge.ledger.acquire._fetch_page_text",
                        lambda url: "page text about failure")
    conn = db.connect(tmp_path / "l.db")
    n = remediate.ingest_lost_sources(conn, export_dir, tmp_path)
    assert n == 1
    row = conn.execute("SELECT url, target_hint FROM documents").fetchone()
    assert row["url"] == "https://example.com/x"
    assert row["target_hint"] == "eng1"
    conn.close()


# ── run(): full pass, offline ────────────────────────────────────────────────


def _gap_catalog(tmp_path):
    """One automatic variant whose transmission part exists but is empty."""
    v, f, p = tmp_path / "variants", tmp_path / "fitment", tmp_path / "parts"
    v.mkdir(parents=True); f.mkdir(parents=True); p.mkdir(parents=True)
    (v / "t.yaml").write_text(yaml.dump([{
        "id": "t1_auto", "make": "t", "model": "m", "generation": "I",
        "engine_code": "E1", "engine_family": "eng1", "fuel": "petrol",
        "displacement_cc": 1200, "power_min_hp": 100, "power_max_hp": 100,
        "transmission": "automatic", "transmission_code": "tc1",
        "electrical_code": "elec1", "body_code": "body1",
        "year_from": 2020, "market": "TR", "notes": "n",
    }], sort_keys=False))
    (f / "t.yaml").write_text(yaml.dump([{
        "variant_id": "t1_auto", "engine_family": "eng1",
        "transmission_code": "tc1", "electrical_code": "elec1", "body_code": "body1",
    }], sort_keys=False))
    for ptype in ("engine", "electrical", "body"):
        (p / ptype).mkdir(exist_ok=True)
    (p / "engine" / "eng1.yaml").write_text(yaml.dump({
        "part_id": "eng1", "part_type": "engine",
        "claims": [{"claim_key": "c1", "title": "t", "domain": "engine",
                    "severity": "low", "status": "verified", "rationale": "r",
                    "inspection_advice": "a", "sources": []}],
    }, sort_keys=False))
    for pid, ptype in (("elec1", "electrical"), ("body1", "body")):
        (p / ptype / f"{pid}.yaml").write_text(yaml.dump({
            "part_id": pid, "part_type": ptype,
            "claims": [{"claim_key": f"c_{pid}", "title": "t", "domain": ptype,
                        "severity": "low", "status": "verified", "rationale": "r",
                        "inspection_advice": "a", "sources": []}],
        }, sort_keys=False))
    (p / "transmission").mkdir()
    (p / "transmission" / "tc1.yaml").write_text(yaml.dump({
        "part_id": "tc1", "part_type": "transmission", "claims": [],
    }, sort_keys=False))
    return v, f, p


def test_run_researches_gap_parts_and_logs_telemetry(tmp_path, monkeypatch):
    from knowledge.ledger.costs import Budget

    dbp = tmp_path / "l.db"
    conn = db.connect(dbp)
    v, f, p = _gap_catalog(tmp_path)

    called = {}
    monkeypatch.setattr(remediate.acquire, "acquire_part",
                        lambda conn, pid, ptype, max_sources=15: (
                            called.setdefault("acquire", []).append((pid, ptype)),
                            {"ingested": 2, "discovered": 3, "skipped_duplicate": 1,
                             "skipped_fetch": 0, "skipped_german": 0, "skipped_foreign": 0})[1])
    monkeypatch.setattr(remediate.extraction, "extract_pending",
                        lambda conn, budget: 4)
    monkeypatch.setattr(remediate.resolve, "resolve_all", lambda conn: {})
    monkeypatch.setattr(remediate.cluster, "rebuild_clusters", lambda conn: 1)
    monkeypatch.setattr(remediate.verdict, "run_verdicts",
                        lambda conn, budget, max_workers=0: 3)
    monkeypatch.setattr(remediate.export, "export_all",
                        lambda conn, out_dir: [out_dir / "tc1.yaml"])
    monkeypatch.setattr(remediate, "LOG_PATH", tmp_path / "logs" / "remediation.jsonl")

    stats = remediate.run(conn, tmp_path, tmp_path / "out", Budget(max_usd=1.0))

    assert called["acquire"] == [("tc1", "transmission")]
    assert stats["ingested"] == 2
    assert stats["extracted"] == 4
    assert stats["verdicts"] == 3
    assert stats["exported"] == 1
    line = json.loads((tmp_path / "logs" / "remediation.jsonl").read_text())
    assert line["parts"] == [{"part_id": "tc1", "part_type": "transmission"}]
    assert line["findings"] >= 1
    conn.close()


def test_run_with_no_actionable_findings_logs_zero_parts(tmp_path, monkeypatch):
    from knowledge.ledger.costs import Budget

    conn = db.connect(tmp_path / "l.db")
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "variants").mkdir(); (empty / "fitment").mkdir(); (empty / "parts").mkdir()

    monkeypatch.setattr(remediate.acquire, "acquire_part",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no acquire")))
    monkeypatch.setattr(remediate, "LOG_PATH", tmp_path / "logs" / "remediation.jsonl")

    stats = remediate.run(conn, empty, tmp_path / "out", Budget(max_usd=1.0))
    assert stats["parts"] == []
    assert stats["findings"] == 0
    conn.close()
