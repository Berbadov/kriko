"""Product-match risks use the lookup gate and expose record coverage."""

import textwrap

import pytest

from app import chatdata
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect


@pytest.fixture
def ctx(tmp_path):
    root = tmp_path / "gated-products"
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "pack.toml").write_text(textwrap.dedent("""
        [pack]
        id = "gated-products"
        name = "Gated products"
        version = "0.1.0"
        [identity]
        product = ["brand", "model"]
        component = ["component"]
    """), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(textwrap.dedent("""
        - {term_id: product, role: subject_kind}
        - {term_id: component, role: attribute, datatype: text, match: {required: true}}
        - {term_id: brand, role: attribute, datatype: text, match: {required: true}}
        - {term_id: model, role: attribute, datatype: text, match: {required: true}}
        - {term_id: usage_km, role: attribute, datatype: number, unit: km}
        - {term_id: engine, role: domain}
    """), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(textwrap.dedent("""
        - kind: component
          label: Shared engine
          identity: {component: shared-engine}
        - kind: product
          label: Alpha Device
          identity: {brand: acme, model: alpha}
          attributes: {usage_km: 10000}
          relations:
            - {predicate: part_of, object: {kind: component, identity: {component: shared-engine}}}
        - kind: product
          label: Beta Device
          identity: {brand: acme, model: beta}
        - kind: product
          label: Gamma Device
          identity: {brand: acme, model: gamma}
          relations:
            - {predicate: part_of, object: {kind: component, identity: {component: shared-engine}}}
    """), encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(textwrap.dedent("""
        - subject: {kind: product, identity: {brand: acme, model: alpha}}
          kind: known_issue
          domain: engine
          severity: high
          text: {en: {title: High mileage engine failure, body: engine failure after extended use, advice: inspect}}
          conditions:
            - {key: usage_km, op: gte, value: 120000, on_missing: closed, weight: 0.5}
          evidence:
            - {url: "https://maker.example.test/alpha", quote: Engine failure over 120000 km.}
        - subject: {kind: component, identity: {component: shared-engine}}
          kind: known_issue
          domain: engine
          severity: high
          text: {en: {title: High cycle bearing failure, body: bearing failure after extended use, advice: inspect}}
          conditions:
            - {key: usage_km, op: gte, value: 120000, on_missing: open, weight: 0.5}
          evidence:
            - {url: "https://maker.example.test/bearing", quote: Bearing failure over 120000 km.}
    """), encoding="utf-8")

    store = connect(tmp_path / "knowledge.sqlite")
    packstore.install(store, build.build(root, tmp_path / "gated-products.kpack"))
    try:
        yield chatdata.Context(store=store)
    finally:
        store.close()


def _row(ctx, query, **args):
    out = chatdata.run("product_match", ctx, {"query": query, **args})
    return next(row for row in out["rows"] if query.split()[0].casefold() in row["label"].casefold())


def test_closed_direct_and_relation_claims_do_not_apply_below_the_gate(ctx):
    alpha = _row(ctx, "alpha", must=["high mileage engine failure"])

    assert alpha["must"][0]["status"] == "unknown"
    assert alpha["risk_coverage"] == {
        "catalogue": 2, "applicable": 0, "conditional": 0,
        "sourced": 2, "unsourced": 0, "refuting": 0,
    }


def test_open_unknown_relation_claim_is_conditional_and_not_a_contradiction(ctx):
    gamma = _row(ctx, "gamma", must=["high cycle bearing failure"])

    assert gamma["must"][0]["status"] == "unknown"
    assert gamma["risk_coverage"]["catalogue"] == 1
    assert gamma["risk_coverage"]["applicable"] == 1
    assert gamma["risk_coverage"]["conditional"] == 1


def test_reader_context_overrides_catalogue_attribute_for_claim_gates(ctx):
    gamma = _row(ctx, "gamma", context={"usage_km": 130000},
                 must=["high cycle bearing failure"])

    assert gamma["must"][0]["status"] == "contradicted"
    assert gamma["risk_coverage"]["conditional"] == 0
    assert gamma["risk_coverage"]["applicable"] == 1


def test_unconstrained_match_does_not_rank_fewer_known_risks_as_safer(ctx):
    out = chatdata.run("product_match", ctx, {"query": "device"})

    assert [row["label"] for row in out["rows"]] == [
        "Alpha Device", "Beta Device", "Gamma Device"]
    rows = {row["label"]: row for row in out["rows"]}
    assert rows["Beta Device"]["risk_coverage"]["catalogue"] == 0
    assert rows["Alpha Device"]["risk_coverage"]["catalogue"] == 2
    assert rows["Alpha Device"]["risk_coverage"]["sourced"] == 2


def test_unsourced_high_risk_cannot_settle_a_must():
    risk = {"severity": "high", "text": "red paint causes a failure",
            "title": "Red paint failure", "source": "",
            "applicability": "applicable"}
    result = chatdata._judge("red paint", [], [risk])

    assert result["status"] == "unknown"
    assert result["evidence"] == ""


def test_matching_measurement_is_not_overridden_by_incidental_risk_words():
    fact = {"text": "voltage_v 18 V", "key": "voltage_v", "value": "18",
            "unit": "V", "identity": False, "source": "https://spec.example.test"}
    risk = {"severity": "high", "text": "18V battery overheats under load",
            "title": "18V battery overheats", "source": "https://risk.example.test",
            "applicability": "applicable"}

    result = chatdata._judge("18V", [fact], [risk])

    assert result["status"] == "met"
    assert result["evidence"] == "voltage_v 18 V"


def test_refuting_only_citation_is_not_presented_as_risk_support(ctx):
    claim_id = ctx.store.execute(
        "SELECT c.claim_id FROM claims c JOIN claim_text t USING (claim_id, pack_id)"
        " WHERE c.pack_id = 'gated-products' AND t.title = 'High mileage engine failure'"
    ).fetchone()["claim_id"]
    ctx.store.execute("UPDATE evidence SET stance = 'refutes' WHERE claim_id = ?", (claim_id,))
    subject_id = ctx.store.execute(
        "SELECT subject_id FROM subjects WHERE pack_id = 'gated-products'"
        " AND label = 'Alpha Device'").fetchone()["subject_id"]

    risks = chatdata._risks(ctx.store, subject_id, "gated-products")
    risk = next(one for one in risks if one["claim_id"] == claim_id)
    judged = chatdata._judge("high mileage engine failure", [], [risk])

    assert risk["source"] == ""
    assert risk["sources"][0]["stance"] == "refutes"
    assert judged["status"] == "unknown"
    assert chatdata._risk_coverage(risks)["refuting"] == 1


@pytest.mark.parametrize(("phrase", "key", "value"), [
    ("waterproof", "waterproof", "not waterproof"),
    ("wireless", "wireless", "false"),
])
def test_negated_or_false_fact_cannot_prove_a_positive_constraint(phrase, key, value):
    fact = {"text": f"{key} {value}", "key": key, "value": value,
            "unit": "", "identity": False, "source": ""}

    assert chatdata._judge(phrase, [fact], [])["status"] == "unknown"
