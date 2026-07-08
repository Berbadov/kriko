import pytest
from knowledge.ledger import db, resolve


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "l.db")


@pytest.fixture
def registry(monkeypatch):
    # Registry is normally derived from backend/data/parts/**; pin it here so
    # the test doesn't depend on which cars are currently onboarded.
    monkeypatch.setattr(resolve, "component_registry",
                        lambda: {"DQ200": "dq200", "DQ381": "dq381", "K9K": "k9k"})


def _evidence(conn, title, rationale="", hint=None, target_hint="dq381_transmission"):
    doc_id = db.insert_document(conn, url=f"https://x.test/{title[:8]}",
                                source_type="page", raw_text=title + rationale,
                                target_hint=target_hint)
    return db.insert_evidence(conn, doc_id=doc_id, claim={
        "title": title, "domain": "transmission", "severity": "high",
        "rationale": rationale, "inspection_advice": "", "quote": "",
        "engine_or_variant_hint": hint, "quote_grounded": False,
    }, span_start=None, span_end=None, extractor_version=2)


def _resolution(conn, ev_id):
    return conn.execute("SELECT * FROM resolutions WHERE evidence_id=?",
                        (ev_id,)).fetchone()


def test_sibling_reroute_own_text_beats_search_context(conn, registry):
    # The design_flaws.md Flaw 1 canary: DQ200 claim found while researching DQ381.
    ev = _evidence(conn, "DQ200 dry-clutch pressure failure",
                   "the DQ200 accumulator loses pressure", hint="DQ200")
    resolve.resolve_all(conn)
    r = _resolution(conn, ev)
    assert r["component_id"] == "dq200" and r["method"] == "alias"


def test_no_code_falls_back_to_hint(conn, registry):
    ev = _evidence(conn, "Mechatronic unit failure", "gearbox jerks when hot")
    resolve.resolve_all(conn)
    r = _resolution(conn, ev)
    assert r["component_id"] == "dq381" and r["method"] == "hint"


def test_multiple_codes_disambiguated_by_hint(conn, registry):
    ev = _evidence(conn, "DQ200 vs DQ381 clutch comparison",
                   "the DQ381 wet clutch avoids DQ200 issues")
    resolve.resolve_all(conn)
    assert _resolution(conn, ev)["component_id"] == "dq381"


def test_resolve_all_is_idempotent(conn, registry):
    _evidence(conn, "DQ200 dry-clutch pressure failure")
    resolve.resolve_all(conn)
    counts = resolve.resolve_all(conn)
    assert sum(counts.values()) == 0  # nothing left to resolve


def test_hint_resolves_bodyelec_part_by_id(conn, registry):
    # Body/electrical parts (megane4_elec) are keyed by model, carry no engine
    # code, and so never enter component_registry(). The hint fallback must
    # still recover the REAL part id from the ingest hint 'megane4_elec_...' —
    # not store the domain-suffixed string 'megane4_elec_electrical'.
    ev = _evidence(conn, "Intermittent BSI wake-up drains the battery",
                   "parasitic draw keeps the CAN bus awake overnight",
                   target_hint="megane4_elec_electrical")
    resolve.resolve_all(conn)
    r = _resolution(conn, ev)
    assert r["component_id"] == "megane4_elec" and r["method"] == "hint"


def test_foreign_manufacturer_code_detected(conn, registry):
    # design_flaws.md Flaw 1: a claim found under a VW hint (dq381 -> volkswagen)
    # whose own text actually discusses a Renault code (K9K, absent from the
    # pinned registry so it can't resolve as an alias). The foreign guard must
    # flag it rather than mis-file it under the VW hint.
    ev = _evidence(conn, "Injector fouling on the 1.5 dCi",
                   "the K9K unit coke-blocks its injectors")
    resolve.resolve_all(conn)
    r = _resolution(conn, ev)
    assert r["component_id"] == "foreign" and r["method"] == "foreign"


def test_component_registry_and_part_ids_derive_from_catalog():
    # The 'no hardcoded car data' deliverable, verified against the REAL catalog
    # (the other tests monkeypatch the registry away). Codes map to their
    # power-collapsed component; model-keyed body/electrical stubs appear only
    # among known part ids, never as codes.
    reg = resolve.component_registry()
    assert reg.get("K9K") == "k9k" and reg.get("DQ381") == "dq381"
    assert "MEGANE4_ELEC" not in reg  # model id is not an engine code
    ids = resolve.known_part_ids()
    assert {"k9k", "dq381", "megane4_elec"} <= ids
