"""Configuration mistakes are observable before the UI's source filter."""

import json
from types import SimpleNamespace

import pytest

from app import bench, benchcases, precisionbench, precisioncases, protocols
from app.providers.local_agent import LocalAsker, evidence, identity, plan, triage
from app.web import state


def case(key="pc-revision"):
    return next(c for c in benchcases.case_rows(50) if c["id"] == key)


def sources(c):
    return {doc["url"]: doc["text"] for doc in c["documents"]}


def correct(c):
    return {"assumed": c["product"], "specs": c["expected_specs"], "risks": [
        {"title": " ".join(group[0] for group in entry["terms"]),
         "why": entry["quote"], "url": entry["url"], "quote": entry["quote"]}
        for entry in c["supported"]]}


def test_generated_suite_matches_the_shipped_snapshot():
    assert precisioncases.generate()["cases"] == json.loads(
        benchcases._FILE.with_name("benchprecision.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("c", benchcases.case_rows(50), ids=lambda c: c["id"])
def test_reference_answers_pass_every_dimension(c):
    result = precisionbench.judge(c, json.dumps(correct(c)), sources(c))
    assert result["pass"]


def test_a_real_quote_about_a_sibling_is_still_a_hallucination():
    c = case()
    result = correct(c)
    result["risks"].append({"title": "Fan seizure", "why": "This unit's fan seizes",
                            "url": c["documents"][0]["url"],
                            "quote": "AX-1040R1 (2020) has cooling fan seizure."})
    judged = precisionbench.judge(c, json.dumps(result), sources(c))
    assert judged["hallucination_rate"] == .5
    assert judged["unsupported_quotes"] == 0
    assert judged["errors"][0]["reason"] == "unsupported-configuration-or-claim"


def test_invented_quotes_and_wrong_specs_are_separate_failures():
    c = case()
    result = correct(c)
    result["risks"][0]["quote"] = "Every unit catches fire at startup."
    result["specs"] = [{**c["expected_specs"][0], "value": "8 GB"}]
    judged = precisionbench.judge(c, json.dumps(result), sources(c))
    assert judged["unsupported_quotes"] == 1
    assert judged["spec_errors"] == ["memory capacity: 8 gb"]
    assert not judged["pass"]


def test_an_unreadable_answer_is_not_correct_abstention():
    c = case("missing-fitment")
    judged = precisionbench.judge(c, "I have no answer", sources(c))
    assert not judged["valid_shape"]
    assert not judged["abstention_correct"]
    assert not judged["pass"]


def test_an_empty_answer_cannot_win_the_positive_cases():
    c = case()
    judged = precisionbench.judge(c, '{"risks": [], "specs": []}', sources(c))
    assert judged["recall"] == 0
    assert judged["hallucination_rate"] is None
    assert not judged["pass"]


def test_wrong_url_cannot_borrow_another_documents_quote():
    c = case()
    result = correct(c)
    result["risks"][0]["url"] = "https://wrong.example/doc"
    judged = precisionbench.judge(c, json.dumps(result), sources(c))
    assert judged["unsupported_quotes"] == 1


def test_codes_are_anchored_as_whole_identifiers():
    task = "# Quick look:\n\nNorthstar notebook AX-1040R2 2021\n"
    assert identity.contains("AX-1040R2 fails", "AX-1040R2")
    assert not identity.contains("AX-1040R20 fails", "AX-1040R2")
    proposed = plan.propose(task, lambda _: '["Northstar notebook failures"]')
    assert '"ax-1040r2"' in proposed[0]


def test_exact_sku_page_beats_a_verbose_sibling_page():
    pages = [("https://a.example", "Northstar AX-1040R1 failures " * 100),
             ("https://b.example", "AX-1040R2 charging connector fracture")]
    chosen = triage.choose(pages, task="Northstar AX-1040R2", queries=[],
                           budget=5000, at_most=1, page_cap=2000)
    assert chosen[0][0] == "https://b.example"


def test_explicit_exclusions_and_sibling_sentences_are_not_quote_options():
    task = "# Quick look:\n\nNorthstar AX-1040R2\n"
    options = evidence.quotes(
        "AX-1040R1 units have cooling fan seizure. The bulletin excludes AX-1040R2. "
        "AX-1040R2 units have connector fractures.", task)
    assert options == ["AX-1040R2 units have connector fractures."]


class Counted:
    def __init__(self, reply):
        self.reply = reply
        self.tokens_in = self.tokens_out = self.tokens_used = 0
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        self.tokens_in += 20
        self.tokens_out += 5
        self.tokens_used += 25
        return self.reply if len(self.prompts) % 2 else '{"unsupported": [], "note": "checked"}'


def test_local_supplied_evidence_skips_search_and_counts_answer_and_check():
    c = case()
    complete = Counted(json.dumps(correct(c)))
    asker = LocalAsker(complete, complete, None, None, model="small",
                       search_provider="supplied-corpus", given_sources=sources(c))
    asker.ask(precisionbench.brief(c))
    assert asker.tokens_used == 50, "shared sockets must not be counted twice"
    assert [row["stage"] for row in asker.metrics] == ["triage", "answer", "verify"]
    assert sum(row["tokens_used"] or 0 for row in asker.metrics) == 50
    assert asker.sources == sources(c)
    assert "AX-1040R2" in complete.prompts[0]


def test_fixed_case_records_raw_errors_even_if_the_parser_drops_them(tmp_path, monkeypatch):
    c = case()
    answer = correct(c)
    answer["risks"].append({"title": "Fire", "url": c["documents"][0]["url"],
                            "quote": "Invented quote from nowhere."})
    complete = Counted(json.dumps(answer))
    asker = LocalAsker(complete, complete, None, None, model="small",
                       search_provider="supplied-corpus", given_sources=sources(c))
    monkeypatch.setattr(bench, "_asker", lambda *a: asker)
    row = bench.run_case(SimpleNamespace(app_state_path=tmp_path / "app.sqlite"), c, plane="local")
    assert row["accepted"] == 1
    assert row["refused"] == 1
    assert row["gold"]["raw_produced"] == 2
    assert row["gold"]["hallucination_rate"] == .5
    assert row["tokens"] == 50
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        state.record_bench(conn, row)
        restored = state.bench_runs(conn)[0]
        assert restored["measurement"]["tokens_in"] == 40
        assert restored["measurement"]["stages"]
        readout = protocols.readout([restored], [])[0]
        assert readout["hallucination_rate"] == .5
        assert readout["tokens_mean"] == 50
        assert readout["recall"] == 1
    finally:
        conn.close()


def test_failed_cases_keep_usage_and_latency(tmp_path, monkeypatch):
    class Broken:
        model = "small"
        tokens_used = 70
        tokens_in = 50
        tokens_out = 20

        def ask(self, _):
            raise RuntimeError("cut off")

    monkeypatch.setattr(bench, "_asker", lambda *a: Broken())
    row = bench.run_case(SimpleNamespace(app_state_path=tmp_path / "app.sqlite"), case(), plane="local")
    assert row["tokens"] == 70
    assert row["ms"] is not None
    readout = protocols.readout([row], [])[0]
    assert readout["failed_runs"] == 1
    assert readout["tokens_total"] == 70
    assert readout["hallucination_rate"] is None


def test_unknown_prices_and_tokens_do_not_get_diluted_by_unmeasured_runs():
    rows = [{"model": "small", "accepted": 1, "tokens": 50, "usd": .1},
            {"model": "small", "accepted": 1, "tokens": 50, "usd": .1},
            {"model": "small", "accepted": 100, "tokens": None, "usd": None}]
    row = protocols.readout(rows, [])[0]
    assert row["usd_per_accepted_claim"] == .1
    assert row["tokens_per_accepted_claim"] == 50
    assert row["counted_runs"] == 2


def test_the_same_model_on_different_planes_is_not_averaged():
    rows = [{"model": "m", "plane": p, "ms": ms, "protocol": "standard"}
            for p, ms in (("local", 1000), ("api", 10))]
    assert len(protocols.readout(rows, [])) == 2


def test_partial_usage_is_kept_but_not_treated_as_a_complete_run():
    row = protocols.readout([{"model": "m", "tokens": 50,
        "gold": {"measurement": {"usage_complete": False}}}], [])[0]
    assert row["tokens_mean"] is None
    assert row["partial_usage_runs"] == 1
    assert row["counted_runs"] == 0


@pytest.mark.parametrize("key", ["car-year-outside", "missing-fitment", "no-evidence"])
def test_nonapplicable_corpus_has_no_risk_quote_choices(key):
    c = case(key)
    assert not evidence.quotes(c["documents"][0]["text"], precisionbench.brief(c))


def test_specification_values_are_not_risk_quote_choices():
    c = case()
    choices = evidence.quotes(c["documents"][0]["text"], precisionbench.brief(c),
                              spec_names=c["requested_specs"])
    assert choices == [c["supported"][0]["quote"]]


def test_hosted_completion_enforces_a_budget_before_the_request(monkeypatch):
    from app.providers.completion_asker import CompletionAsker
    complete = Counted('{"risks": [], "specs": []}')
    complete.model = "hosted"
    monkeypatch.setattr("app.modelcatalogue.price", lambda *a: .5)
    with pytest.raises(ValueError, match="exceeds"):
        CompletionAsker(complete, budget_usd=.1).ask("task")
    assert not complete.prompts


def test_model_ownership_includes_the_configured_local_server(monkeypatch):
    monkeypatch.setattr("app.providers.harness.available", lambda: [])
    monkeypatch.setattr("app.providers.harness.models_for_each", lambda *a: {})
    monkeypatch.setattr("app.localplane.resolve", lambda *a, **k: {"models": ["tiny:local"]})
    owners = bench.llm_owners()
    assert owners["tiny:local"] == {"local"}
    assert ("api", "tiny:local") not in bench.pairs(["local", "api"], ["tiny:local"], owners)
