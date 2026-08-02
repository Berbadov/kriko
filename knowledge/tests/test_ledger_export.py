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


# ── Part-dict metadata (derived from the real served catalog) ───────────────


def test_component_part_meta_exact_match():
    meta = export.component_part_meta("dq381")
    assert meta["part_id"] == "dq381"
    assert meta["part_type"] == "transmission"
    assert meta["display_name"] and meta["manufacturer"]


def test_component_part_meta_power_collapsed():
    """k9k has no exact part file (k9k_85/90/100/110 do) — the merged header
    is derived from the power-split catalog parts, not hand-enumerated."""
    meta = export.component_part_meta("k9k")
    assert meta["part_id"] == "k9k"
    assert meta["part_type"] == "engine"
    assert meta["manufacturer"] == "renault"
    assert meta["code_family"]           # engine parts must declare one
    assert "hp" not in meta["display_name"]  # tune-specific suffix stripped


def test_component_part_meta_unknown_is_none():
    assert export.component_part_meta("n0p3_gearbox") is None


# ── Gate grounding units ────────────────────────────────────────────────────


def test_ground_applies_when_mileage():
    aw = export._ground_applies_when(
        "Clutch wear typically appears after 80,000 km.", "")
    assert aw == {"min_mileage_km": 80000}


def test_ground_applies_when_year_window_from_quotes():
    aw = export._ground_applies_when(
        "Mechatronic failures on early builds.",
        "Owners report the fault affects 2019 builds onward, fixed in 2022.")
    assert aw["applies_year_from"] == 2019
    assert aw["applies_year_to"] == 2022


def test_ground_applies_when_ungrounded_years_stay_open():
    # no direction cue near the year token → no window (fail-open)
    assert export._ground_applies_when("title", "As of 2022 it was popular.") == {}


def test_ground_applies_when_contradictory_window_drops_both():
    # lower-cued year AFTER the upper-cued one (cues > PROXIMITY apart, so no
    # bleed) → from > to is contradictory; both bounds drop (fail-open).
    aw = export._ground_applies_when(
        "title",
        "The fault affects 2020 model year builds onward according to many"
        " separate owner reports filed. Meanwhile the 2015 recall was fixed.")
    assert "applies_year_from" not in aw and "applies_year_to" not in aw


def test_validate_rejects_bad_gate_fields():
    errors = []
    export._validate({"title": "ok", "severity": "medium", "kind": "maintenance"},
                     errors, 1)
    assert any("maintenance" in e for e in errors)
    errors = []
    export._validate({"title": "ok", "severity": "medium", "kind": "known_issue",
                      "applies_when": {"applies_year_from": 2022,
                                       "applies_year_to": 2019}}, errors, 1)
    assert any("applies_year_from" in e for e in errors)


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


def test_export_writes_part_dict_shape(populated, tmp_path):
    _add_verdict(populated, _verdict())
    paths = export.export_all(populated, tmp_path / "out")
    doc = yaml.safe_load(paths[0].read_text())
    # part-dict shape sync.py expects (part_id == filename stem)
    assert paths[0].name == "dq381.yaml"
    assert doc["part_id"] == "dq381"
    assert doc["part_type"] == "transmission"
    assert doc["display_name"] and doc["manufacturer"]
    c = doc["claims"][0]
    assert c["status"] == "verified"            # two independent netlocs
    assert c["claim_key"].startswith("dq381_transmission_")
    assert c["id"] == c["claim_key"] + "_v1"
    assert c["is_current"] is True
    assert len(c["sources"]) == 2
    assert c["title"] == "DQ381 mechatronic solenoid wear"
    assert c["kind"] == "known_issue"           # served per-part claim field
    assert "applies_when" not in c              # nothing grounded → no gate
    # source_domain is derived from the URL netloc (www stripped)
    assert {s["source_domain"] for s in c["sources"]} == {"a.test", "b.test"}


def test_export_grounds_mileage_gate(populated, tmp_path):
    _add_verdict(populated, _verdict(
        rationale_en="Solenoid wear typically appears after 80,000 km."))
    paths = export.export_all(populated, tmp_path / "out")
    c = yaml.safe_load(paths[0].read_text())["claims"][0]
    assert c["applies_when"]["min_mileage_km"] == 80000
    assert c["kind"] == "known_issue"


def test_export_reclassifies_maintenance_claim(populated, tmp_path):
    _add_verdict(populated, _verdict(
        title_en="Neglected DSG fluid degradation causing judder",
        rationale_en="The DSG fluid must be changed every 40,000-60,000 km "
                     "to prevent failure."))
    paths = export.export_all(populated, tmp_path / "out")
    c = yaml.safe_load(paths[0].read_text())["claims"][0]
    assert c["kind"] == "maintenance"
    assert c["maintenance"]["interval_km"] == 40000      # biased low
    assert c["maintenance"]["evidence_keywords"]
    # the interval was consumed from the applies_when gate, not duplicated
    assert "min_mileage_km" not in c.get("applies_when", {})


def test_component_without_catalog_identity_held_back(populated, tmp_path, capsys):
    _add_cluster(populated, 2, "n0p3", ["https://c.test/1", "https://d.test/2"],
                 _verdict(attribution={"component_id": "n0p3", "confidence": "high",
                                       "reason": "r"},
                          title_en="N0P3 unit failure"))
    _add_verdict(populated, _verdict())
    paths = export.export_all(populated, tmp_path / "out")
    out = capsys.readouterr().out
    assert "no catalog part identity" in out
    assert [p.name for p in paths] == ["dq381.yaml"]  # the valid one still ships


def test_attribution_mismatch_not_exported(populated, tmp_path):
    _add_verdict(populated, _verdict(
        attribution={"component_id": "dq200", "confidence": "high", "reason": "r"}))
    paths = export.export_all(populated, tmp_path / "out")
    assert paths == []  # contamination caught, nothing written


def _add_cluster(conn, cluster_id, component, urls, verdict, quote=None):
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
            "quote": quote or f"quote c{cluster_id}-{i}",
            "engine_or_variant_hint": component,
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


def test_export_grounds_year_window_from_quotes(populated, tmp_path):
    _add_cluster(populated, 2, "dq200", ["https://c.test/1", "https://d.test/2"],
                 _verdict(attribution={"component_id": "dq200", "confidence": "high",
                                       "reason": "r"},
                          title_en="DQ200 mechatronic unit failure"),
                 quote="The fault affects 2019 builds onward and was fixed in 2022.")
    _add_verdict(populated, _verdict())
    paths = export.export_all(populated, tmp_path / "out")
    doc = yaml.safe_load((tmp_path / "out" / "dq200.yaml").read_text())
    c = doc["claims"][0]
    assert c["applies_when"]["applies_year_from"] == 2019
    assert c["applies_when"]["applies_year_to"] == 2022


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
    assert "skipped 1 invalid item(s)" in out
    assert "DTC code in title" in out
    # the valid dq200 cluster still exported despite the invalid dq381 one
    assert len(paths) == 1
    doc = yaml.safe_load(paths[0].read_text())
    assert [c["title"] for c in doc["claims"]] == ["DQ200 mechatronic unit failure"]


def test_all_invalid_clusters_export_nothing(populated, tmp_path, capsys):
    _add_verdict(populated, _verdict(title_en="P17BF P189C fault code litany"))
    paths = export.export_all(populated, tmp_path / "out")
    assert paths == []
    assert "skipped 1 invalid item(s)" in capsys.readouterr().out
