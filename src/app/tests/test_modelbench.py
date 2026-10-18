"""The model benchmark: what it measures, and the ways it must not lie.

Every test here is about a way the number could be wrong rather than about a
function's return value: a rate averaged instead of pooled, a failure dropped
from a denominator, an estimate folded into a measured mean, a brief that
differed between two candidates. Those are the failures that make a benchmark
worse than no benchmark, and each one has a test that would catch it.
"""

import json

import pytest

from app import benchcases
from app.modelbench import aggregate, candidates, corpus, metrics, report
from app.modelbench import runner as runner_mod
from app.modelbench import sweep
from app.modelbench.sockets import NoSocket, Reply
from app.web.jobs import Cancelled


def case(key="pc-revision"):
    return next(c for c in benchcases.case_rows(50) if c["id"] == key)


def sources(one):
    return {doc["url"]: doc["text"] for doc in one["documents"]}


def correct_reply(one) -> str:
    """What a model that read the case properly returns."""
    return json.dumps({
        "assumed": one["product"],
        "specs": [{"name": spec["name"], "value": spec["value"],
                   "url": spec["url"], "quote": spec["url"]}
                  for spec in one.get("expected_specs") or []],
        "risks": [{"title": " ".join(group[0] for group in entry["terms"]),
                   "why": entry["quote"], "url": entry["url"], "quote": entry["quote"]}
                  for entry in one["supported"]],
    })


class FakeSocket:
    """A transport that answers with whatever it was handed, and counts."""

    def __init__(self, text="{}", *, usage="reported", error=None):
        self.text = text
        self.usage = usage
        self.error = error

    def answer(self, prompt: str) -> Reply:
        if self.error:
            raise self.error
        return Reply(
            text=self.text,
            model="fake",
            tokens_in=100 if self.usage != "none" else None,
            tokens_out=20 if self.usage != "none" else None,
            tokens_total=120 if self.usage in ("reported", "reported_total") else None,
            usage=self.usage,
            brief_chars=len(prompt), reply_chars=len(self.text),
        )


# ── naming ────────────────────────────────────────────────────────────────

def test_every_candidate_kind_round_trips_through_its_own_id():
    for spec in ("local:qwen3.5:4b", "api:gpt-4o-mini",
                 "harness:mistral-vibe@glm-5-3", "harness:claude-code"):
        one = candidates.parse(spec)
        assert one.id == spec


def test_a_local_model_name_may_contain_colons():
    """`qwen3.5:4b` is one model, not a kind and a tag."""
    one = candidates.parse("local:qwen3.5:4b")
    assert one.kind == "local"
    assert one.model == "qwen3.5:4b"


def test_the_harness_model_splits_on_the_last_at_sign():
    one = candidates.parse("harness:mistral-vibe@glm-5-3")
    assert (one.harness, one.model) == ("mistral-vibe", "glm-5-3")


def test_an_unknown_kind_is_refused_with_the_vocabulary_that_would_work():
    with pytest.raises(candidates.UnknownCandidate) as caught:
        candidates.parse("plane:harness")
    assert "local" in str(caught.value) and "harness" in str(caught.value)


def test_a_kind_with_no_model_is_refused_rather_than_defaulted():
    with pytest.raises(candidates.UnknownCandidate):
        candidates.parse("local:")
    with pytest.raises(candidates.UnknownCandidate):
        candidates.parse("harness:")


def test_several_specs_parse_from_a_string_or_a_list_and_deduplicate():
    from_string = candidates.parse_many("local:a,local:b")
    from_list = candidates.parse_many(["local:a", "local:b"])
    assert [one.id for one in from_string] == [one.id for one in from_list] == ["local:a", "local:b"]
    assert len(candidates.parse_many("local:a,local:a")) == 1


def test_discovery_never_invents_a_candidate_it_cannot_reach(monkeypatch):
    from app.providers import harness as harness_mod

    monkeypatch.setattr(harness_mod, "available", lambda: [])
    monkeypatch.setattr(candidates, "local_candidates", lambda path=None: [])
    monkeypatch.setattr(candidates, "api_candidates", lambda: [])
    assert candidates.discover(None) == []


def test_a_cli_that_lists_models_yields_its_default_and_each_model(monkeypatch):
    from app.providers import harness as harness_mod

    class One:
        id = "some-cli"
        label = "Some CLI"

    monkeypatch.setattr(harness_mod, "available", lambda: [One()])
    monkeypatch.setattr(harness_mod, "models_for", lambda one, **kw: ["m-a", "m-b"])
    found = [one.id for one in candidates.harness_candidates(None)]
    assert found == ["harness:some-cli", "harness:some-cli@m-a", "harness:some-cli@m-b"]


# ── the brief ─────────────────────────────────────────────────────────────

def test_the_brief_is_deterministic():
    one = case()
    assert corpus.prompt(one) == corpus.prompt(one)
    assert corpus.prompt_fingerprint(one) == corpus.prompt_fingerprint(one)


def test_two_cases_have_two_briefs_and_one_case_has_one():
    a, b = case("pc-revision"), case("car-code-suffix")
    assert corpus.prompt_fingerprint(a) != corpus.prompt_fingerprint(b)
    assert corpus.prompt_fingerprint(a) == corpus.prompt_fingerprint(a)


def test_the_brief_carries_every_document_and_leaks_no_answer_key():
    one = case("pc-revision")
    text = corpus.prompt(one)
    for doc in one["documents"]:
        assert doc["text"] in text
        assert doc["url"] in text
    # The scoring vocabulary must never appear, or a model could answer the key
    # instead of the question. Checked as serialized keys and as the key's own
    # labels: the word "supported" legitimately appears inside "unsupported
    # items", so a substring test on it alone would be a false alarm.
    for forbidden in ("must_find", "must_not_find", "known_absent",
                      "expect_abstention", '"supported"'):
        assert forbidden not in text
    for entry in one["supported"]:
        assert entry["id"] not in text


def test_the_brief_is_the_same_whichever_candidate_is_reading_it():
    one = case()
    first = candidates.parse("local:qwen3.5:4b")
    second = candidates.parse("harness:mistral-vibe@glm-5-3")
    assert corpus.prompt(one) == corpus.prompt(one)
    assert first.id != second.id


def test_the_corpus_refuses_the_live_web_suite():
    with pytest.raises(ValueError) as caught:
        corpus.load("web")
    assert "legacy" in str(caught.value)


def test_the_shipped_corpus_has_no_defects():
    assert corpus.problems(corpus.load()) == []


# ── scoring ───────────────────────────────────────────────────────────────

def test_a_correct_answer_scores_everything_and_invents_nothing():
    one = case()
    score = metrics.verdict(one, correct_reply(one), sources(one))
    assert score["recall"] == 1.0
    assert score["fabricated"] == 0
    assert score["hallucination_rate"] == 0.0
    assert score["pass"] is True


def test_a_true_quote_about_a_sibling_model_is_a_hallucination():
    """The failure the corpus exists for: a real sentence, the wrong variant."""
    one = case("pc-revision")
    reply = json.loads(correct_reply(one))
    reply["risks"].append({
        "title": "Fan seizure",
        "why": "This unit's fan seizes",
        "url": one["documents"][0]["url"],
        "quote": "AX-1040R1 (2020) has cooling fan seizure.",
    })
    score = metrics.verdict(one, json.dumps(reply), sources(one))
    assert score["fabricated"] == 1
    assert score["produced"] == 2
    assert score["hallucination_rate"] == 0.5


def test_an_invented_quote_is_counted_as_an_unsupported_quote():
    one = case()
    reply = json.loads(correct_reply(one))
    reply["risks"][0]["quote"] = "A sentence that is nowhere in the document."
    score = metrics.verdict(one, json.dumps(reply), sources(one))
    assert score["unsupported_quotes"] == 1
    assert score["fabricated"] == 1


def test_an_abstention_case_is_scored_on_whether_it_abstained():
    one = case("car-year-outside")
    assert one["expect_abstention"] is True
    quiet = metrics.verdict(one, json.dumps({"risks": [], "specs": []}), sources(one))
    assert quiet["abstention_correct"] is True
    loud = metrics.verdict(
        one,
        json.dumps({"risks": [{"title": "Cooler seal", "why": "leaks",
                               "url": one["documents"][0]["url"],
                               "quote": "GX-07A cooler seal leakage affects build "
                                        "years 2018 through 2020 inclusive."}],
                    "specs": []}),
        sources(one),
    )
    assert loud["abstention_correct"] is False


def test_prose_instead_of_json_scores_as_producing_nothing_rather_than_crashing():
    one = case()
    score = metrics.verdict(one, "I could not find anything useful.", sources(one))
    assert score["pass"] is False
    assert score["produced"] == 0
    # Nothing was produced, so there is no hallucination *rate* — an invented
    # "0%" would say the prose answer was clean.
    assert score["hallucination_rate"] is None
    assert score["recall"] == 0.0


def test_a_rate_with_no_denominator_is_none_not_zero():
    assert metrics.rate(0, 0) is None
    assert metrics.rate(0, 2) == 0.0


# ── the runner ────────────────────────────────────────────────────────────

def test_a_run_records_both_halves_of_a_metered_exchange(monkeypatch):
    one = case()
    monkeypatch.setattr(runner_mod, "socket_for",
                        lambda *a, **k: FakeSocket(correct_reply(one), usage="reported"))
    row = runner_mod.run_case(candidates.parse("local:qwen3.5:4b"), one)
    assert row.failed is False
    assert (row.reply.tokens_in, row.reply.tokens_out, row.reply.tokens_total) == (100, 20, 120)
    assert row.reply.usage == "reported"
    assert row.score["recall"] == 1.0


def test_a_transport_that_cannot_be_reached_is_a_row_not_an_exception(monkeypatch):
    def refuse(*args, **kwargs):
        raise NoSocket("no local model server is ready")

    monkeypatch.setattr(runner_mod, "socket_for", refuse)
    row = runner_mod.run_case(candidates.parse("local:does-not-exist"), case())
    assert row.failed is True
    assert "no local model server" in row.error
    assert row.ms is not None
    assert row.score == {}


def test_a_run_that_failed_keeps_the_tokens_it_had_already_spent(monkeypatch):
    """A 40k-token timeout spent those tokens; dropping them makes it look free."""
    class Halfway:
        model = "fake"
        tokens_in = 40_000
        tokens_out = 0
        tokens_used = 40_000

    class Exploding(FakeSocket):
        def answer(self, prompt):
            self._socket = Halfway()
            raise TimeoutError("took too long")

    monkeypatch.setattr(runner_mod, "socket_for", lambda *a, **k: Exploding())
    row = runner_mod.run_case(candidates.parse("local:qwen3.5:4b"), case())
    assert row.failed is True
    assert row.reply.tokens_total == 40_000
    assert row.reply.usage == "reported"


def test_cancellation_is_not_swallowed_as_a_failure(monkeypatch):
    class Stopped(FakeSocket):
        def answer(self, prompt):
            raise Cancelled("reader pressed stop")

    monkeypatch.setattr(runner_mod, "socket_for", lambda *a, **k: Stopped())
    with pytest.raises(Cancelled):
        runner_mod.run_case(candidates.parse("local:qwen3.5:4b"), case())


# ── the aggregate ─────────────────────────────────────────────────────────

def _row(candidate_id="local:a", *, wanted=1, found=1, produced=1, fabricated=0,
         tokens=100, usage="reported", error="", abstention=None, case_id="c1",
         specs_wanted=0, specs_found=0, spec_errors=()):
    row = runner_mod.Measurement(
        candidate_id=candidate_id, candidate_label=candidate_id, kind="local",
        case_id=case_id, prompt_fingerprint="deadbeef",
    )
    row.ms = 1000
    row.error = error
    if error:
        row.reply = Reply()
        return row
    row.reply = Reply(
        tokens_in=tokens // 2 if usage == "reported" else None,
        tokens_out=tokens // 2 if usage == "reported" else None,
        tokens_total=tokens if usage in ("reported", "reported_total") else None,
        usage=usage,
    )
    row.score = {
        "wanted": wanted, "found": ["f"] * found, "missed": ["m"] * (wanted - found),
        "produced": produced, "fabricated": fabricated,
        "hallucination_rate": (fabricated / produced) if produced else None,
        "recall": (found / wanted) if wanted else None,
        "specs_wanted": specs_wanted, "spec_found": ["s"] * specs_found,
        "spec_missed": ["s"] * (specs_wanted - specs_found),
        "spec_errors": list(spec_errors),
        "specs_produced": specs_found + len(spec_errors),
        "unsupported_quotes": 0, "abstention_correct": abstention,
        "pass": fabricated == 0 and found == wanted,
        "valid_shape": True, "errors": [], "hallucinated": [],
    }
    return row


def test_rates_are_pooled_across_cases_rather_than_averaged():
    """A one-fact case must not outvote a three-fact one."""
    rows = [
        _row(wanted=1, found=1, case_id="small"),
        _row(wanted=3, found=0, case_id="big"),
    ]
    one = aggregate.by_candidate(rows)[0]
    assert one["recall"] == 0.25          # 1 of 4, pooled
    assert one["recall"] != 0.5           # which is what mean-of-rates would say


def test_a_failure_stays_in_the_denominator_and_is_not_scored():
    rows = [
        _row(wanted=2, found=2, case_id="a"),
        _row(wanted=2, found=2, case_id="b", error="NoSocket: server is down"),
    ]
    one = aggregate.by_candidate(rows)[0]
    assert one["runs"] == 2
    assert one["failed"] == 1
    assert one["failure_rate"] == 0.5
    assert one["graded"] == 1
    assert one["recall"] == 1.0           # pooled over what was actually scored
    assert one["failures"][0]["error"].startswith("NoSocket")


def test_an_estimate_never_enters_a_measured_token_mean():
    rows = [
        _row(tokens=100, usage="reported", case_id="a"),
        _row(tokens=9999, usage="estimated", case_id="b"),
    ]
    one = aggregate.by_candidate(rows)[0]
    assert one["tokens_total_mean"] == 100.0
    assert one["metered_runs"] == 1
    assert one["estimated_runs"] == 1


def test_a_candidate_that_metered_nothing_reports_no_tokens_rather_than_zero():
    one = aggregate.by_candidate([_row(tokens=0, usage="none")])[0]
    assert one["tokens_total_mean"] is None
    assert one["tokens_per_fact"] is None
    assert one["unmetered_runs"] == 1


def test_tokens_per_fact_is_absent_when_nothing_was_found():
    """The column that ranks efficiency must not reward finding nothing."""
    nothing = aggregate.by_candidate(
        [_row(wanted=2, found=0, produced=0, tokens=10)])[0]
    assert nothing["tokens_per_fact"] is None
    something = aggregate.by_candidate(
        [_row(wanted=2, found=2, produced=2, tokens=100)])[0]
    assert something["tokens_per_fact"] == 50.0


def test_abstention_is_counted_only_where_the_case_expected_it():
    rows = [
        _row(abstention=True, case_id="quiet"),
        _row(abstention=False, case_id="loud"),
        _row(abstention=None, case_id="no-opinion"),
    ]
    one = aggregate.by_candidate(rows)[0]
    assert one["abstentions_expected"] == 2
    assert one["abstention_accuracy"] == 0.5


def test_the_dimension_table_says_where_a_model_fails():
    rows = [
        _row(found=1, wanted=1, case_id="a"),
        _row(found=0, wanted=1, produced=1, fabricated=1, case_id="b"),
    ]
    rows[0].dimension = "revision"
    rows[1].dimension = "distractor-load"
    found = {one["dimension"]: one for one in aggregate.by_dimension(rows)}
    assert found["revision"]["recall"] == 1.0
    assert found["distractor-load"]["hallucination_rate"] == 1.0


def test_a_wrong_specification_is_counted_apart_from_a_missing_one():
    """Omitting a figure and stating the wrong one are different failures."""
    rows = [
        _row(specs_wanted=1, specs_found=1, case_id="right"),
        _row(specs_wanted=1, specs_found=0, spec_errors=["memory capacity: 8 GB"],
             case_id="wrong"),
    ]
    one = aggregate.by_candidate(rows)[0]
    assert one["specs_produced"] == 2
    assert one["specs_wrong"] == 1
    assert one["spec_error_rate"] == 0.5


def test_a_model_that_returns_no_specifications_has_no_wrong_spec_rate():
    """It must not read as careful for having said nothing."""
    one = aggregate.by_candidate(
        [_row(specs_wanted=2, specs_found=0, case_id="silent")])[0]
    assert one["spec_error_rate"] is None
    assert one["spec_recall"] == 0.0


def test_tokens_per_accepted_is_reported_beside_tokens_per_fact():
    rows = [_row(tokens=200, wanted=2, found=2, produced=2, case_id="a")]
    one = aggregate.by_candidate(rows)[0]
    assert one["accepted"] == 2
    assert one["tokens_per_fact"] == 100.0
    assert one["tokens_per_accepted"] == 100.0
    assert one["tokens_per_claim"] == 100.0


def test_tokens_per_claim_is_absent_when_the_model_claimed_nothing():
    """Cost per claim has no answer for a model that made no claims."""
    one = aggregate.by_candidate(
        [_row(tokens=500, wanted=1, found=0, produced=0, case_id="a")])[0]
    assert one["tokens_per_claim"] is None
    assert one["tokens_per_fact"] is None


# ── comparability ─────────────────────────────────────────────────────────

def test_fingerprints_are_compared_per_case_not_across_cases():
    rows = [
        _row(case_id="a"),
        _row(case_id="b"),
    ]
    rows[0].prompt_fingerprint = "aaaa"
    rows[1].prompt_fingerprint = "bbbb"
    assert aggregate.summary(rows)["fingerprints_agree"] is True


def test_two_different_briefs_for_one_case_are_caught():
    rows = [_row(case_id="a"), _row(case_id="a", candidate_id="local:b")]
    rows[0].prompt_fingerprint = "aaaa"
    rows[1].prompt_fingerprint = "bbbb"
    shape = aggregate.summary(rows)
    assert shape["fingerprints_agree"] is False
    assert shape["cases_with_split_briefs"] == ["a"]


# ── the report ────────────────────────────────────────────────────────────

def test_the_report_says_the_comparison_is_fair_when_the_briefs_agree():
    rows = [_row(case_id="a"), _row(case_id="a", candidate_id="local:b")]
    rows[0].prompt_fingerprint = rows[1].prompt_fingerprint = "aaaa"
    text = report.markdown(rows, aggregate.by_candidate(rows),
                           aggregate.by_dimension(rows), aggregate.by_case(rows),
                           title="t", when="now")
    assert "Comparability check passed" in text


def test_the_report_warns_when_a_candidate_was_never_metered():
    text = report.markdown([_row(usage="none")], aggregate.by_candidate([_row(usage="none")]),
                           [], [], title="t", when="now")
    assert "not counted" in text
    assert "| — |" in text or "—" in text


def test_the_csv_names_the_usage_kind_so_a_reader_can_weigh_the_number():
    text = report.case_csv(aggregate.by_case([_row(usage="reported_total")]))
    assert "reported_total" in text
    header, first = text.strip().splitlines()[:2]
    assert "tokens_total" in header
    assert first.count(",") >= 5


def test_every_emitted_shape_is_written(tmp_path):
    rows = [_row(case_id="a")]
    paths = report.write(tmp_path, rows, stem="probe", title="t", when="now")
    assert {"json", "candidates_csv", "cases_csv", "markdown"} <= set(paths)
    # And the five charts, which are part of the report rather than an extra.
    assert {name for name in paths if name.startswith("chart_")} == {
        "chart_tradeoff", "chart_quality", "chart_tokens", "chart_dimensions",
        "chart_fabrication"}
    for path in paths.values():
        assert (tmp_path / path.split("\\")[-1]).exists()
    document = json.loads((tmp_path / "probe.json").read_text(encoding="utf-8"))
    assert document["set"]["fingerprints_agree"] is True
    assert document["candidates"][0]["candidate"] == "local:a"


def test_a_rerender_derives_a_denominator_an_older_report_never_stored(tmp_path):
    """A saved report stays readable as the scorer grows a field."""
    rows = [_row(case_id="a", specs_wanted=1, specs_found=0,
                 spec_errors=["memory capacity: 8 GB"])]
    report.write(tmp_path, rows, stem="old", title="t", when="then")
    document = json.loads((tmp_path / "old.json").read_text(encoding="utf-8"))
    for one in document["runs"]:
        one["score"].pop("specs_produced", None)
    (tmp_path / "old.json").write_text(json.dumps(document), encoding="utf-8")
    report.rerender(tmp_path / "old.json")
    fresh = json.loads((tmp_path / "old.json").read_text(encoding="utf-8"))
    assert fresh["candidates"][0]["specs_produced"] == 1
    assert fresh["candidates"][0]["spec_error_rate"] == 1.0


def test_a_report_can_be_rebuilt_from_its_own_json_without_the_model(tmp_path):
    """A view should not cost a sweep to correct."""
    rows = [
        _row(case_id="a", candidate_id="local:a"),
        _row(case_id="a", candidate_id="local:b", fabricated=1, produced=1),
    ]
    report.write(tmp_path, rows, stem="first", title="t", when="then")
    paths = report.rerender(tmp_path / "first.json", stem="second", when="later")
    rebuilt = (tmp_path / "second.md").read_text(encoding="utf-8")
    assert "later" in rebuilt
    assert "local:a" in rebuilt and "local:b" in rebuilt
    document = json.loads((tmp_path / "second.json").read_text(encoding="utf-8"))
    assert {one["candidate"] for one in document["candidates"]} == {"local:a", "local:b"}
    assert {"json", "candidates_csv", "cases_csv", "markdown"} <= set(paths)


def test_a_rerender_recomputes_the_table_rather_than_reusing_a_stale_one(tmp_path):
    """A fix to a rate must reach a report that was already paid for."""
    rows = [_row(case_id="a")]
    report.write(tmp_path, rows, stem="stale", title="t", when="then")
    document = json.loads((tmp_path / "stale.json").read_text(encoding="utf-8"))
    # Simulate a report written by an older version: drop a column the current
    # writer always emits. Re-rendering must survive it.
    for one in document["candidates"]:
        one.pop("valid_shape_rate", None)
    (tmp_path / "stale.json").write_text(json.dumps(document), encoding="utf-8")
    report.rerender(tmp_path / "stale.json")
    fresh = json.loads((tmp_path / "stale.json").read_text(encoding="utf-8"))
    assert "valid_shape_rate" in fresh["candidates"][0]


# ── the sweep and its command line ────────────────────────────────────────

def test_the_sweep_runs_cases_outside_and_candidates_inside(monkeypatch):
    """A sweep stopped early must leave a comparable table, not one full column."""
    order = []

    def record(candidate, one, **kwargs):
        order.append((one["id"], candidate.id))
        return _row(candidate_id=candidate.id, case_id=one["id"])

    monkeypatch.setattr(sweep, "run_case", record)
    plan = sweep.Plan(
        candidates=[candidates.parse("local:a"), candidates.parse("local:b")],
        cases=[case("pc-revision"), case("car-code-suffix")],
        reps=1,
    )
    rows = sweep.run(plan)
    assert [name for name, _ in order] == [
        "pc-revision", "pc-revision", "car-code-suffix", "car-code-suffix"]
    assert len(rows) == 4


def test_a_sweep_with_no_candidate_is_refused_rather_than_empty():
    plan_of = sweep.Plan(candidates=[], cases=[case()], reps=1)
    assert plan_of.runs == 0


def test_the_plan_counts_every_axis(monkeypatch):
    monkeypatch.setattr(candidates, "discover", lambda *a, **k: [])
    plan_of = sweep.plan("local:a,local:b", cases=None, limit=3, reps=2)
    assert len(plan_of.candidates) == 2
    assert len(plan_of.cases) == 3
    assert plan_of.runs == 12


def test_planning_raises_when_the_corpus_itself_is_broken(monkeypatch):
    monkeypatch.setattr(corpus, "problems", lambda cases: ["c1: no documents"])
    with pytest.raises(ValueError) as caught:
        sweep.plan("local:a")
    assert "corpus is not usable" in str(caught.value)


def test_the_command_line_writes_a_report_from_a_fake_transport(tmp_path, monkeypatch):
    from app.modelbench import __main__ as cli

    one = case("pc-revision")
    monkeypatch.setattr(runner_mod, "socket_for",
                        lambda *a, **k: FakeSocket(correct_reply(one)))
    code = cli.main([
        "run", "--candidates", "local:qwen3.5:4b", "--cases", "1",
        "--out", str(tmp_path), "--stem", "probe", "--quiet",
    ])
    assert code == 0
    assert (tmp_path / "probe.md").exists()
    text = (tmp_path / "probe.md").read_text(encoding="utf-8")
    assert "local:qwen3.5:4b" in text


def test_the_command_line_refuses_a_spec_it_cannot_read(tmp_path, capsys):
    from app.modelbench import __main__ as cli

    code = cli.main(["run", "--candidates", "plane:harness", "--out", str(tmp_path)])
    assert code == 2
    assert "unknown candidate kind" in capsys.readouterr().err


def test_the_listing_prints_what_this_machine_can_reach(monkeypatch, capsys):
    from app.modelbench import __main__ as cli

    monkeypatch.setattr(candidates, "discover",
                        lambda *a, **k: [candidates.parse("local:qwen3.5:4b")])
    code = cli.main(["list", "--json"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "local:qwen3.5:4b"


def test_the_benchmark_is_reachable_from_the_kriko_command(monkeypatch, capsys):
    """`kriko model-bench` and `python -m app.modelbench` are one command."""
    from app import cli as kriko_cli

    monkeypatch.setattr(candidates, "discover",
                        lambda *a, **k: [candidates.parse("local:qwen3.5:4b")])
    code = kriko_cli.main(["model-bench", "list", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["id"] == "local:qwen3.5:4b"


# ── recording into the app's own history ──────────────────────────────────

def test_a_measurement_projects_onto_the_history_row_the_app_already_reads():
    from app.modelbench import record

    one = case("pc-revision")
    row = runner_mod.Measurement(
        candidate_id="local:qwen3.5:4b", candidate_label="l", kind="local",
        model="qwen3.5:4b", case_id=one["id"], dimension=one["dimension"],
        set_id=one["set_id"], set_version=one["set_version"], rep=2,
    )
    row.ms = 1234
    row.reply = Reply(tokens_in=100, tokens_out=20, tokens_total=120,
                      usage="reported", usd=0.001)
    row.score = metrics.verdict(one, correct_reply(one), sources(one))
    row.answer_key = corpus.answer_key(one)
    projected = record.legacy_row(row, one)
    assert projected["plane"] == "local"
    assert projected["model"] == "qwen3.5:4b"
    assert projected["protocol"] == record.PROTOCOL
    assert projected["tokens"] == 120
    assert projected["set_id"] == one["set_id"]
    assert projected["rep"] == 2
    assert projected["gold"]["recall"] == 1.0
    assert projected["gold"]["measurement"]["usage_complete"] is True
    # The empty protocol name would make `readout` claim a batch size that was
    # never used; the named one keeps it visibly its own configuration.
    from app import protocols

    assert record.PROTOCOL not in protocols.BY_NAME


def test_an_unmetered_run_is_recorded_as_uncounted_not_as_free():
    from app.modelbench import record

    one = case()
    row = runner_mod.Measurement(candidate_id="harness:x", kind="harness",
                                 model="x", case_id=one["id"])
    row.reply = Reply(usage="none")
    row.score = metrics.verdict(one, correct_reply(one), sources(one))
    projected = record.legacy_row(row, one)
    assert projected["tokens"] is None
    assert projected["gold"]["measurement"]["usage_complete"] is False


def test_recorded_runs_are_readable_by_the_app_history(tmp_path):
    from app.modelbench import record
    from app.web import state

    one = case("pc-revision")
    row = runner_mod.Measurement(
        candidate_id="local:qwen3.5:4b", candidate_label="l", kind="local",
        model="qwen3.5:4b", case_id=one["id"], dimension=one["dimension"],
        set_id=one["set_id"], set_version=one["set_version"],
    )
    row.ms = 900
    row.reply = Reply(tokens_in=10, tokens_out=5, tokens_total=15, usage="reported")
    row.score = metrics.verdict(one, correct_reply(one), sources(one))
    row.answer_key = corpus.answer_key(one)

    path = tmp_path / "app.sqlite"
    assert record.record(path, [row], {one["id"]: one}) == 1
    conn = state.connect(path)
    try:
        stored = state.bench_runs(conn)
        assert len(stored) == 1
        assert stored[0]["model"] == "qwen3.5:4b"
        assert stored[0]["tokens"] == 15
        assert stored[0]["gold"]["recall"] == 1.0
        assert state.bench_summary(conn)[0]["runs"] == 1
    finally:
        conn.close()


def test_recording_skips_a_row_whose_case_is_missing(tmp_path):
    from app.modelbench import record

    row = runner_mod.Measurement(candidate_id="local:a", kind="local",
                                 case_id="not-in-this-corpus")
    assert record.record(tmp_path / "app.sqlite", [row], {}) == 0


def test_the_app_readout_gets_the_same_denominator_as_the_report(tmp_path):
    """Two screens must not publish two hallucination rates for one fact.

    `protocols.readout` divides by `gold["raw_produced"]` and falls back to
    `findings` — which here means *facts expected*, not items claimed. A model
    that claims 27 things to find 10 would be scored 1/12 by the screen and
    17/27 by the report.
    """
    from app import protocols
    from app.modelbench import record
    from app.web import state

    one = case("pc-revision")
    row = runner_mod.Measurement(
        candidate_id="local:gemma4:e2b", candidate_label="l", kind="local",
        model="gemma4:e2b", case_id=one["id"], set_id=one["set_id"],
        set_version=one["set_version"],
    )
    reply = json.loads(correct_reply(one))
    reply["risks"].append({
        "title": "Fan seizure", "why": "invented",
        "url": one["documents"][0]["url"],
        "quote": "AX-1040R1 (2020) has cooling fan seizure.",
    })
    row.reply = Reply(tokens_in=10, tokens_out=5, tokens_total=15, usage="reported")
    row.score = metrics.verdict(one, json.dumps(reply), sources(one))
    row.answer_key = corpus.answer_key(one)

    path = tmp_path / "app.sqlite"
    record.record(path, [row], {one["id"]: one})
    conn = state.connect(path)
    try:
        readout = protocols.readout(state.bench_runs(conn), state.bench_summary(conn))
    finally:
        conn.close()
    mine = next(one_ for one_ in readout if one_["model"] == "gemma4:e2b")
    # 1 fabricated of 2 claimed — the report's number, not 1 of 1 expected.
    assert mine["hallucination_rate"] == rounded(row.score["hallucination_rate"])
    assert mine["hallucination_rate"] == 0.5


def rounded(value):
    return None if value is None else round(value, 3)
