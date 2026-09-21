import json

import yaml

from packs.cars.pipeline.ledger import ingest
from packs.cars.pipeline.sources.base import Document
from kriko.ledger import db


def test_flag_blocked_sources_marks_only_blocked_domains(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    good = db.insert_document(
        conn,
        url="https://what-breaks.com/k9k",
        source_type="page",
        raw_text="belt engine",
        target_hint="k9k",
    )
    bad = db.insert_document(
        conn,
        url="https://www.enginecode.uk/k9k-820-specs",
        source_type="page",
        raw_text="timing chain",
        target_hint="k9k",
    )
    ev_good = db.insert_evidence(
        conn,
        doc_id=good,
        claim={
            "title": "K9K timing belt",
            "domain": "engine",
            "severity": "high",
            "rationale": "r",
            "inspection_advice": "i",
            "quote": "q",
            "engine_or_variant_hint": "K9K",
            "quote_grounded": True,
        },
        span_start=None,
        span_end=None,
        extractor_version=0,
    )
    ev_bad = db.insert_evidence(
        conn,
        doc_id=bad,
        claim={
            "title": "K9K timing chain",
            "domain": "engine",
            "severity": "high",
            "rationale": "r",
            "inspection_advice": "i",
            "quote": "q",
            "engine_or_variant_hint": "K9K",
            "quote_grounded": True,
        },
        span_start=None,
        span_end=None,
        extractor_version=0,
    )

    assert ingest.flag_blocked_sources(conn) == 1
    flags = dict(
        conn.execute("SELECT evidence_id, reason FROM evidence_flags").fetchall()
    )
    assert flags == {ev_bad: "blocked_source"}
    assert ev_good not in flags
    # Idempotent: a second pass flags nothing new.
    assert ingest.flag_blocked_sources(conn) == 0


def test_flag_foreign_language_marks_only_german(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    doc = db.insert_document(
        conn,
        url="https://x.test/k9k",
        source_type="page",
        raw_text="t",
        target_hint="k9k",
    )
    en = db.insert_evidence(
        conn,
        doc_id=doc,
        claim={
            "title": "K9K timing belt failure",
            "domain": "engine",
            "severity": "high",
            "rationale": "The belt snaps and valves collide with pistons.",
            "inspection_advice": "i",
            "quote": "q",
            "engine_or_variant_hint": "K9K",
            "quote_grounded": True,
        },
        span_start=None,
        span_end=None,
        extractor_version=0,
    )
    de = db.insert_evidence(
        conn,
        doc_id=doc,
        claim={
            "title": "Zahnriemen: Frühzeitiger Verschleiß und Rissgefahr",
            "domain": "engine",
            "severity": "high",
            "rationale": "Der Zahnriemen kann frühzeitig verschleißen und reißen, "
            "wodurch Ventile und Kolben kollidieren und der Motor zerstört wird.",
            "inspection_advice": "i",
            "quote": "q",
            "engine_or_variant_hint": "K9K",
            "quote_grounded": True,
        },
        span_start=None,
        span_end=None,
        extractor_version=0,
    )

    assert ingest.flag_foreign_language(conn) == 1
    flags = dict(
        conn.execute("SELECT evidence_id, reason FROM evidence_flags").fetchall()
    )
    assert flags == {de: "foreign_language"}
    assert en not in flags
    assert ingest.flag_foreign_language(conn) == 0  # idempotent


def test_ingest_document_stores_hint_not_attribution(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    doc = Document(
        text="DQ200 accumulator fails",
        url="https://x.test/dsg",
        site_or_channel="x.test",
    )
    doc_id = ingest.ingest_document(conn, doc, "page", target_hint="dq381")
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert row["target_hint"] == "dq381"
    assert row["raw_text"] == "DQ200 accumulator fails"


def test_ingest_document_threads_published_at(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    doc = Document(
        text="DQ200 accumulator fails",
        url="https://x.test/dsg2",
        site_or_channel="x.test",
        published_at="2021-05-03",
    )
    doc_id = ingest.ingest_document(conn, doc, "page", target_hint="dq381")
    row = conn.execute("SELECT published_at FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert row["published_at"] == "2021-05-03"


def test_ingest_document_defaults_published_at_blank(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    doc = Document(
        text="unrelated text with no date",
        url="https://x.test/dsg3",
        site_or_channel="x.test",
    )
    doc_id = ingest.ingest_document(conn, doc, "page", target_hint="dq381")
    row = conn.execute("SELECT published_at FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert row["published_at"] == ""


def test_backfill_cache_dir(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "part_dq381_transmission_candidates.json").write_text(
        json.dumps(
            [
                {
                    "claim": {
                        "title": "DQ200 hydraulic pressure failure",
                        "domain": "transmission",
                        "severity": "high",
                        "rationale": "r",
                        "inspection_advice": "i",
                        "quote": "q",
                        "engine_or_variant_hint": "DQ200",
                    },
                    "doc": {
                        "text": "full page text about DSG",
                        "url": "https://x.test/dsg",
                        "site_or_channel": "x.test",
                    },
                }
            ]
        )
    , encoding="utf-8")
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
    (claims / "renault_megane_4.yaml").write_text(
        yaml.dump(
            [
                {
                    "claim_key": "megane4_k9k_injectors",
                    "title": "K9K injector fouling",
                    "domain": "engine",
                    "severity": "medium",
                    "rationale": "r",
                    "inspection_advice": "i",
                    "status": "verified",
                    "sources": [
                        {
                            "source_url": "https://s.test/a",
                            "site_or_channel": "s.test",
                            "quote": "K9K injectors foul at high mileage",
                        }
                    ],
                }
            ]
        )
    , encoding="utf-8")
    docs, ev = ingest.backfill_claims_dir(conn, claims)
    assert (docs, ev) == (1, 1)
    # Verify stored row's field mapping
    row = conn.execute(
        "SELECT d.target_hint, d.source_type, d.raw_text FROM documents d"
    ).fetchone()
    assert row["target_hint"] == "renault_megane_4"
    assert row["source_type"] == "backfill_yaml"
    assert row["raw_text"] == "K9K injectors foul at high mileage"
    assert ingest.backfill_claims_dir(conn, claims) == (0, 0)  # idempotent


def test_backfill_skips_malformed_files(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    cache = tmp_path / "cache"
    cache.mkdir()
    # Corrupt JSON file
    (cache / "part_bad_engine_candidates.json").write_text("{not json", encoding="utf-8")
    # Valid file
    (cache / "part_dq381_transmission_candidates.json").write_text(
        json.dumps(
            [
                {
                    "claim": {
                        "title": "DQ200 hydraulic pressure failure",
                        "domain": "transmission",
                        "severity": "high",
                        "rationale": "r",
                        "inspection_advice": "i",
                        "quote": "q",
                        "engine_or_variant_hint": "DQ200",
                    },
                    "doc": {
                        "text": "full page text about DSG",
                        "url": "https://x.test/dsg",
                        "site_or_channel": "x.test",
                    },
                }
            ]
        )
    , encoding="utf-8")
    # Should skip malformed file and ingest valid file
    docs, ev = ingest.backfill_cache_dir(conn, cache)
    assert (docs, ev) == (1, 1)
    # Verify the valid file was ingested
    row = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    assert row == 1
