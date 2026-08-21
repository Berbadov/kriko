from knowledge.ledger import db
from ops import ledger_run as run


def test_dry_run_spends_nothing(tmp_path, capsys, monkeypatch):
    dbp = tmp_path / "l.db"
    conn = db.connect(dbp)
    db.insert_document(conn, url="https://x.test/a", source_type="page",
                       raw_text="kronik arıza sorunu " * 500, target_hint="dq381")
    conn.close()
    # any real LLM call must explode
    monkeypatch.setattr("knowledge.ledger.extraction.extract_grounded",
                        lambda t: (_ for _ in ()).throw(AssertionError("LLM called")))
    assert run.main(["extract", "--db", str(dbp), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "estimated" in out.lower() and "$" in out


def test_all_pipeline_offline(tmp_path, monkeypatch):
    dbp = tmp_path / "l.db"
    conn = db.connect(dbp)
    db.insert_document(conn, url="https://x.test/a", source_type="page",
                       raw_text="the DQ381 mechatronic has a chronic solenoid failure",
                       target_hint="dq381")
    conn.close()
    monkeypatch.setattr("knowledge.ledger.extraction.extract_grounded", lambda t: [{
        "title": "DQ381 mechatronic solenoid failure", "domain": "transmission",
        "severity": "medium", "rationale": "solenoid wear", "inspection_advice": "scan",
        "quote": "chronic solenoid failure", "engine_or_variant_hint": "DQ381",
        "quote_grounded": True}])
    import json
    from knowledge.tests.test_ledger_verdict import VALID, _FakeMsg
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _FakeMsg(json.dumps(dict(VALID, severity="medium")))
    monkeypatch.setattr("knowledge.ledger.verdict._client", lambda: FakeClient())
    monkeypatch.setattr("knowledge.ledger.resolve.component_registry",
                        lambda: {"DQ381": "dq381"})
    # Keep the "offline" run hermetic: point backfill at empty dirs so it
    # exercises only the injected document, not the repo's real knowledge/cache
    # and backend/data/claims (whose volume would otherwise drift the test).
    (tmp_path / "empty_cache").mkdir()
    (tmp_path / "empty_claims").mkdir()
    monkeypatch.setattr(run, "_CACHE_DIR", tmp_path / "empty_cache")
    monkeypatch.setattr(run, "_CLAIMS_DIR", tmp_path / "empty_claims")

    rc = run.main(["all", "--db", str(dbp),
                   "--export-dir", str(tmp_path / "out")])
    assert rc == 0
    assert (tmp_path / "out" / "dq381.yaml").exists()


def test_report_command(tmp_path, capsys):
    dbp = tmp_path / "l.db"
    conn = db.connect(dbp)
    conn.execute("INSERT INTO runs (started_at, stage, model, calls, tokens_in,"
                 " tokens_out, usd) VALUES ('t','verdict','m',1,10,5,0.01)")
    conn.commit(); conn.close()
    assert run.main(["report", "--db", str(dbp)]) == 0
    assert "verdict" in capsys.readouterr().out
