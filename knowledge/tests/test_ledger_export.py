import json
import pytest
import yaml
from knowledge.ledger import db, export


def _verdict(**over):
    v = {"attribution": {"component_id": "dq381", "confidence": "high", "reason": "r"},
         "supported": True, "refuted_by": [], "product_value": "high",
         "severity": "medium", "title_en": "DQ381 mechatronic solenoid wear",
         "title_tr": "t", "rationale_en": "re", "rationale_tr": "rt",
         "inspection_advice_en": "ie", "inspection_advice_tr": "it"}
    v.update(over)
    return v


def test_disposition_rules():
    assert export.disposition(_verdict(), 2, False) == "verified"
    assert export.disposition(_verdict(), 1, False) == "review"
    assert export.disposition(_verdict(), 1, True) == "verified"   # structured corroboration
    assert export.disposition(_verdict(severity="high"), 3, False) == "review"  # human gate
    assert export.disposition(_verdict(supported=False), 3, False) is None
    assert export.disposition(_verdict(product_value="generic"), 3, False) is None
    assert export.disposition(
        _verdict(attribution={"component_id": "foreign", "confidence": "high",
                              "reason": "r"}), 3, False) is None


@pytest.fixture
def populated(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    for i, url in enumerate(["https://a.test/1", "https://b.test/2"]):
        doc_id = db.insert_document(conn, url=url, source_type="page",
                                    raw_text=f"text {i}", target_hint="dq381")
        ev_id = db.insert_evidence(conn, doc_id=doc_id, claim={
            "title": "DQ381 mechatronic solenoid wear", "domain": "transmission",
            "severity": "medium", "rationale": "r", "inspection_advice": "i",
            "quote": f"quote {i}", "engine_or_variant_hint": "DQ381",
            "quote_grounded": True}, span_start=None, span_end=None,
            extractor_version=2)
        conn.execute("INSERT INTO resolutions VALUES (?,?,?,?)",
                     (ev_id, "dq381", "alias", 1))
    conn.execute("INSERT INTO clusters (component_id, domain, cluster_version)"
                 " VALUES ('dq381','transmission',1)")
    conn.execute("INSERT INTO cluster_members VALUES (1,1)")
    conn.execute("INSERT INTO cluster_members VALUES (1,2)")
    conn.commit()
    return conn


def _add_verdict(conn, v):
    # Verdicts are content-addressed: store under cluster 1's real input_hash so
    # export_all — which looks the verdict up by recomputing that hash — finds it.
    from knowledge.ledger.verdict import cluster_payload, input_hash
    h = input_hash(cluster_payload(conn, 1))
    conn.execute("INSERT INTO verdicts VALUES (?,'m',?,10,10,0.0,'now')",
                 (h, json.dumps(v)))
    conn.commit()


def test_export_writes_existing_claim_schema(populated, tmp_path):
    _add_verdict(populated, _verdict())
    paths = export.export_all(populated, tmp_path / "out")
    claims = yaml.safe_load(paths[0].read_text())
    c = claims[0]
    assert c["status"] == "verified"            # two independent netlocs
    assert c["claim_key"].startswith("dq381_transmission_")
    assert c["id"] == c["claim_key"] + "_v1"
    assert c["is_current"] is True
    assert len(c["sources"]) == 2
    assert c["title"] == "DQ381 mechatronic solenoid wear"
    assert c["kind"] == "known_issue"           # served per-part claim field
    # source_domain is derived from the URL netloc (www stripped)
    assert {s["source_domain"] for s in c["sources"]} == {"a.test", "b.test"}


def test_attribution_mismatch_not_exported(populated, tmp_path):
    _add_verdict(populated, _verdict(
        attribution={"component_id": "dq200", "confidence": "high", "reason": "r"}))
    paths = export.export_all(populated, tmp_path / "out")
    assert paths == []  # contamination caught, nothing written


def _add_cluster(conn, cluster_id, component, urls, verdict):
    """Add a second (third, …) cluster with its own docs/evidence/verdict so
    mixed valid+invalid exports can be tested."""
    from knowledge.ledger.verdict import cluster_payload, input_hash
    ev_ids = []
    for i, url in enumerate(urls):
        doc_id = db.insert_document(conn, url=url, source_type="page",
                                    raw_text=f"text c{cluster_id}-{i}",
                                    target_hint=component)
        ev_id = db.insert_evidence(conn, doc_id=doc_id, claim={
            "title": verdict["title_en"], "domain": "transmission",
            "severity": "medium", "rationale": "r", "inspection_advice": "i",
            "quote": f"quote c{cluster_id}-{i}", "engine_or_variant_hint": component,
            "quote_grounded": True}, span_start=None, span_end=None,
            extractor_version=2)
        ev_ids.append(ev_id)
        conn.execute("INSERT INTO resolutions VALUES (?,?,?,?)",
                     (ev_id, component, "alias", 1))
    conn.execute("INSERT INTO clusters (component_id, domain, cluster_version)"
                 " VALUES (?,?,1)", (component, "transmission"))
    cid = conn.execute("SELECT max(id) FROM clusters").fetchone()[0]
    for ev_id in ev_ids:
        conn.execute("INSERT INTO cluster_members VALUES (?,?)", (cid, ev_id))
    conn.commit()
    h = input_hash(cluster_payload(conn, cid))
    conn.execute("INSERT INTO verdicts VALUES (?,'m',?,10,10,0.0,'now')",
                 (h, json.dumps(verdict)))
    conn.commit()
    return cid


def test_invalid_cluster_is_skipped_not_fatal(populated, tmp_path, capsys):
    """Backlog B1 blocker 1: one DTC-titled cluster must not abort the export —
    it is skipped and reported; every other valid cluster still ships."""
    _add_verdict(populated, _verdict(title_en="P17BF P189C fault code litany"))
    _add_cluster(populated, 2, "dq200",
                 ["https://c.test/1", "https://d.test/2"],
                 _verdict(attribution={"component_id": "dq200", "confidence": "high",
                                       "reason": "r"},
                          title_en="DQ200 mechatronic unit failure"))
    paths = export.export_all(populated, tmp_path / "out")
    out = capsys.readouterr().out
    assert "skipped 1 invalid cluster(s)" in out
    assert "DTC code in title" in out
    # the valid dq200 cluster still exported despite the invalid dq381 one
    assert len(paths) == 1
    claims = yaml.safe_load(paths[0].read_text())
    assert [c["title"] for c in claims] == ["DQ200 mechatronic unit failure"]


def test_all_invalid_clusters_export_nothing(populated, tmp_path, capsys):
    _add_verdict(populated, _verdict(title_en="P17BF P189C fault code litany"))
    paths = export.export_all(populated, tmp_path / "out")
    assert paths == []
    assert "skipped 1 invalid cluster(s)" in capsys.readouterr().out
