import json
import yaml
from knowledge.ledger import db, ingest
from knowledge.sources.base import Document


def test_ingest_document_stores_hint_not_attribution(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    doc = Document(text="DQ200 accumulator fails", url="https://x.test/dsg",
                   site_or_channel="x.test")
    doc_id = ingest.ingest_document(conn, doc, "page", target_hint="dq381")
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert row["target_hint"] == "dq381"
    assert row["raw_text"] == "DQ200 accumulator fails"


def test_backfill_cache_dir(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "part_dq381_transmission_candidates.json").write_text(json.dumps([{
        "claim": {"title": "DQ200 hydraulic pressure failure", "domain": "transmission",
                  "severity": "high", "rationale": "r", "inspection_advice": "i",
                  "quote": "q", "engine_or_variant_hint": "DQ200"},
        "doc": {"text": "full page text about DSG", "url": "https://x.test/dsg",
                "site_or_channel": "x.test"},
    }]))
    docs, ev = ingest.backfill_cache_dir(conn, cache)
    assert (docs, ev) == (1, 1)
    row = conn.execute(
        "SELECT e.component_hint, d.target_hint FROM evidence e"
        " JOIN documents d ON d.id=e.doc_id"
    ).fetchone()
    assert row["component_hint"] == "DQ200"
    assert row["target_hint"] == "dq381_transmission"
    # idempotent: re-run adds nothing
    assert ingest.backfill_cache_dir(conn, cache) == (0, 0)


def test_backfill_claims_dir(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    claims = tmp_path / "claims"
    claims.mkdir()
    (claims / "renault_megane_4.yaml").write_text(yaml.dump([{
        "claim_key": "megane4_k9k_injectors", "title": "K9K injector fouling",
        "domain": "engine", "severity": "medium", "rationale": "r",
        "inspection_advice": "i", "status": "verified",
        "sources": [{"source_url": "https://s.test/a", "site_or_channel": "s.test",
                     "quote": "K9K injectors foul at high mileage"}],
    }]))
    docs, ev = ingest.backfill_claims_dir(conn, claims)
    assert (docs, ev) == (1, 1)
    assert ingest.backfill_claims_dir(conn, claims) == (0, 0)  # idempotent
