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


class _FakeMsg:
    class _U:
        input_tokens, output_tokens = 1000, 200
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]
        self.usage = self._U()


def test_run_verdicts_sync_stores_and_caches(conn, monkeypatch):
    calls = []
    class FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                calls.append(kw)
                return _FakeMsg(json.dumps(VALID))
    monkeypatch.setattr(verdict, "_client", lambda: FakeClient())
    b = costs.Budget()
    assert verdict.run_verdicts(conn, b, use_batch=False) == 1
    assert len(calls) == 1
    assert b.total_usd > 0
    # cache: same payload hash → zero calls on rerun
    assert verdict.run_verdicts(conn, b, use_batch=False) == 0
    assert len(calls) == 1


def test_batch_precheck_blocks_unaffordable_submit(conn, monkeypatch):
    monkeypatch.setattr(verdict, "_client",
                        lambda: (_ for _ in ()).throw(AssertionError("must not connect")))
    with pytest.raises(costs.BudgetExceeded):
        verdict.run_verdicts(conn, costs.Budget(max_usd=0.0000001), use_batch=False)
