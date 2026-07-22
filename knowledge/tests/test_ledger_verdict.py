import json
import pytest
from knowledge.ledger import costs, db, verdict


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "l.db")
    doc_id = db.insert_document(c, url="https://x.test/a", source_type="page",
                                raw_text="text", target_hint="dq381")
    ev_id = db.insert_evidence(c, doc_id=doc_id, claim={
        "title": "DQ381 mechatronic failure", "domain": "transmission",
        "severity": "high", "rationale": "solenoid wear",
        "inspection_advice": "scan", "quote": "q",
        "engine_or_variant_hint": "DQ381", "quote_grounded": True,
    }, span_start=None, span_end=None, extractor_version=2)
    c.execute("INSERT INTO resolutions VALUES (?,?,?,?)", (ev_id, "dq381", "alias", 1))
    c.execute("INSERT INTO clusters (component_id, domain, cluster_version)"
              " VALUES ('dq381','transmission',1)")
    c.execute("INSERT INTO cluster_members VALUES (1, ?)", (ev_id,))
    c.commit()
    return c


VALID = {
    "attribution": {"component_id": "dq381", "confidence": "high", "reason": "r"},
    "supported": True, "refuted_by": [],
    "product_value": "high", "severity": "high",
    "title_en": "DQ381 mechatronic failure", "title_tr": "DQ381 mekatronik arızası",
    "rationale_en": "re", "rationale_tr": "rt",
    "inspection_advice_en": "ie", "inspection_advice_tr": "it",
}


def test_gate_product_value_downgrades_dtc_litany_evidence():
    high = {"supported": True, "product_value": "high"}
    # Clean, config-specific evidence title — the model's "high" stands.
    assert verdict.gate_product_value(
        ["Chronic injector fouling (K9K 1.5 dCi)"], high) == "high"
    # Evidence that leads with raw fault codes is the low-value "DTC litany" form,
    # even though the model launders the codes out of its rewritten title_en.
    assert verdict.gate_product_value(
        ["Mechatronics adaptation not completed (P1781/18189)"], high) == "low"
    assert verdict.gate_product_value(
        ["Frequent Recurring OBD-II Fault Codes (P0130, P0136) for O2 sensors"],
        high) == "low"
    # Downgrade-only: a model verdict below "high" is never raised.
    assert verdict.gate_product_value(
        ["Mechatronics adaptation not completed (P1781/18189)"],
        {"product_value": "low"}) == "low"


def test_build_prompt_adds_recall_guidance_only_for_structured():
    base = {"component_id": "golf7_body", "domain": "body",
            "sibling_codes": []}
    testimony = dict(base, evidence=[{
        "title": "t", "rationale": "r", "inspection_advice": "i",
        "severity": "high", "quote": "q", "component_hint": "",
        "url": "https://x.test", "site_or_channel": "s",
        "source_type": "page", "target_hint": "golf7_body"}])
    structured = dict(base, evidence=[dict(testimony["evidence"][0],
                                           source_type="structured")])
    assert "RECALL RECORDS" not in verdict.build_prompt(testimony)
    p = verdict.build_prompt(structured)
    assert "RECALL RECORDS" in p
    assert "OFFICIAL safety recall" in p
    # mixed clusters (testimony + recall corroboration) also get the guidance
    mixed = dict(base, evidence=[testimony["evidence"][0],
                                 dict(testimony["evidence"][0],
                                      source_type="structured")])
    assert "RECALL RECORDS" in verdict.build_prompt(mixed)


def test_parse_verdict_validates_keys():
    assert verdict.parse_verdict(json.dumps(VALID))["supported"] is True
    assert verdict.parse_verdict(f"```json\n{json.dumps(VALID)}\n```")  # fenced ok
    with pytest.raises(ValueError):
        verdict.parse_verdict(json.dumps({"supported": True}))  # missing keys
    with pytest.raises(ValueError):
        verdict.parse_verdict("not json")


def test_input_hash_stable_and_content_sensitive(conn):
    p = verdict.cluster_payload(conn, 1)
    assert verdict.input_hash(p) == verdict.input_hash(verdict.cluster_payload(conn, 1))
    p2 = dict(p, component_id="other")
    assert verdict.input_hash(p) != verdict.input_hash(p2)


class _FakeUsage:
    def __init__(self, prompt_tokens=1000, completion_tokens=200):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeMsg:
    """Mirrors the OpenAI-SDK-shaped chat.completions.create() response that
    both Mistral and DeepSeek's OpenAI-compatible endpoints return."""
    def __init__(self, text, prompt_tokens=1000, completion_tokens=200):
        message = type("M", (), {"content": text})()
        self.choices = [type("C", (), {"message": message})()]
        self.usage = _FakeUsage(prompt_tokens, completion_tokens)


def test_run_verdicts_sync_stores_and_caches(conn, monkeypatch):
    calls = []
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    calls.append(kw)
                    return _FakeMsg(json.dumps(VALID))
    monkeypatch.setattr(verdict, "_client", lambda: FakeClient())
    b = costs.Budget()
    assert verdict.run_verdicts(conn, b) == 1
    assert len(calls) == 1
    assert b.total_usd > 0
    # cache: same payload hash → zero calls on rerun
    assert verdict.run_verdicts(conn, b) == 0
    assert len(calls) == 1


def test_precheck_blocks_unaffordable_run(conn, monkeypatch):
    monkeypatch.setattr(verdict, "_client",
                        lambda: (_ for _ in ()).throw(AssertionError("must not connect")))
    with pytest.raises(costs.BudgetExceeded):
        verdict.run_verdicts(conn, costs.Budget(max_usd=0.0000001))


def test_unparseable_verdict_still_charges_budget(conn, monkeypatch):
    # The API bills for the tokens regardless of whether the JSON parses; the
    # budget must reflect that spend so an unparseable reply can't slip a run
    # past --max-usd. No verdict row is stored, and the run reports 0 saved.
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _FakeMsg("this is not json")
    monkeypatch.setattr(verdict, "_client", lambda: FakeClient())
    b = costs.Budget()
    assert verdict.run_verdicts(conn, b) == 0
    assert b.total_usd > 0  # charged despite the parse failure
    assert conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == 0
