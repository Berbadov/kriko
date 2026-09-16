"""B126 — ground truth as pack data, and the three case kinds.

`app/gold.py` is deliberately not an LLM judging another model's output: the
one thing this has to be is independent of the thing it measures. These tests
cover the loader (a case with no `subject_id` and no `subject_ids` is dropped
rather than crashing a benchmark run), `judge` for the `specific` kind that
already existed, and the two additions this session makes real: `judge_bulk`
(does quality degrade with volume?) and `judge_validation` (drift, not
correctness).
"""


from app import gold


class _Conn:
    """A stand-in for a store connection: `pack_asset` and the packs table,
    nothing else — the two things `gold.load`/`gold.all_cases` touch."""

    def __init__(self, assets: dict[str, str], packs: tuple[str, ...] = ("p",)):
        self.assets = assets
        self.packs = packs

    def execute(self, sql, args=()):
        assert "packs" in sql
        return self

    def fetchall(self):
        return [{"pack_id": one} for one in self.packs]


def _asset(text: str):
    def pack_asset(conn, pack_id, name):
        return text if pack_id in conn.packs else ""

    return pack_asset


def test_a_case_with_no_subject_at_all_is_dropped_not_crashed(monkeypatch):
    monkeypatch.setattr(
        "kriko.research.pack_asset",
        _asset("cases:\n  - id: broken\n    kind: specific\n"),
    )
    assert gold.load(_Conn({}), "p") == []


def test_a_malformed_gold_file_is_empty_not_an_exception(monkeypatch):
    monkeypatch.setattr("kriko.research.pack_asset", _asset("cases: [this is not: a list of dicts"))
    assert gold.load(_Conn({}), "p") == []


def test_a_bulk_case_is_loaded_from_subject_ids(monkeypatch):
    monkeypatch.setattr(
        "kriko.research.pack_asset",
        _asset(
            "cases:\n"
            "  - id: siblings\n"
            "    kind: bulk\n"
            "    subject_ids: [a, b, c]\n"
            "    must_find: [{claim: shared issue, domain: engine}]\n"
        ),
    )
    (case,) = gold.load(_Conn({}), "p")
    assert case["kind"] == "bulk"
    assert case["subject_ids"] == ("a", "b", "c")
    assert case["subject_id"] == "a"  # the anchor, for display and filtering


# ── judge (specific) — sanity that the existing behaviour still holds ───────

def test_judge_scores_recall_precision_and_hallucination():
    case = {
        "id": "c1", "subject_id": "s1",
        "must_find": [{"claim": "mechatronics fails", "domain": "transmission"}],
        "must_not_find": [{"claim": "check engine light", "why": "generic"}],
    }
    produced = [
        {"title": "DSG mechatronics unit fails", "domain": "transmission", "quote": ""},
        {"title": "check engine light comes on", "domain": "", "quote": ""},
    ]
    result = gold.judge(case, produced)
    assert result["recall"] == 1.0
    assert result["hallucinated"] == ["check engine light comes on"]
    assert result["hallucination_rate"] == 0.5


# ── judge_bulk — throughput and degradation-with-volume ─────────────────────

def _bulk_case(n: int) -> dict:
    return {
        "id": "siblings", "subject_ids": tuple(f"s{i}" for i in range(n)),
        "must_find": [{"claim": "shared issue", "domain": "engine"}],
    }


def test_bulk_aggregates_recall_across_measured_subjects():
    case = _bulk_case(4)
    judged = {
        f"s{i}": gold.judge(case, produced)
        for i, produced in enumerate([
            [{"title": "shared issue found", "domain": "engine"}],
            [{"title": "shared issue found", "domain": "engine"}],
            [],
            [],
        ])
    }
    result = gold.judge_bulk(case, judged)
    assert result["measured"] == 4
    assert result["requested"] == 4
    assert result["recall"] == 0.5


def test_bulk_reports_a_skipped_subject_as_unmeasured_not_zero():
    """A subject uninstalled mid-run is absent from `judged_by_subject`
    entirely — it must not be silently counted as a zero-recall measurement."""
    case = _bulk_case(3)
    judged = {
        "s0": gold.judge(case, [{"title": "shared issue found", "domain": "engine"}]),
        # s1 uninstalled mid-run: no entry at all.
        "s2": gold.judge(case, [{"title": "shared issue found", "domain": "engine"}]),
    }
    result = gold.judge_bulk(case, judged)
    assert result["measured"] == 2
    assert result["requested"] == 3
    assert result["recall"] == 1.0


def test_degradation_with_volume_is_detected():
    """The failure a single-case benchmark cannot see: quality holding up on
    subject one and collapsing by subject eight."""
    case = _bulk_case(8)
    good = gold.judge(case, [{"title": "shared issue found", "domain": "engine"}])
    bad = gold.judge(case, [])
    judged = {f"s{i}": (good if i < 4 else bad) for i in range(8)}
    result = gold.judge_bulk(case, judged)
    assert result["recall_first_half"] == 1.0
    assert result["recall_second_half"] == 0.0
    assert result["degrades"] is True


def test_steady_quality_is_not_reported_as_degrading():
    case = _bulk_case(6)
    good = gold.judge(case, [{"title": "shared issue found", "domain": "engine"}])
    judged = {f"s{i}": good for i in range(6)}
    result = gold.judge_bulk(case, judged)
    assert result["degrades"] is False


def test_too_few_subjects_to_split_says_nothing_rather_than_guessing():
    case = _bulk_case(1)
    judged = {"s0": gold.judge(case, [{"title": "shared issue found", "domain": "engine"}])}
    result = gold.judge_bulk(case, judged)
    assert result["degrades"] is None
    assert result["recall_first_half"] is None


def test_bulk_with_no_measured_subjects_at_all():
    """Every subject failed or was uninstalled: a zero denominator, not a
    zero score."""
    case = _bulk_case(3)
    result = gold.judge_bulk(case, {})
    assert result["measured"] == 0
    assert result["recall"] is None
    assert result["degrades"] is None


# ── judge_validation — drift, not correctness ────────────────────────────────

def _validation_case() -> dict:
    return {
        "id": "recheck", "subject_id": "s1",
        "must_find": [{"claim": "mechatronics fails", "domain": "transmission"}],
        "must_not_find": [{"claim": "battery fire", "why": "never credibly reported"}],
    }


def test_validation_confirms_what_is_still_quoted():
    rechecked = [
        {"claim_id": "c1", "title": "DSG mechatronics unit fails",
         "domain": "transmission", "verdict": "quoted"},
    ]
    result = gold.judge_validation(_validation_case(), rechecked)
    assert result["recall"] == 1.0
    assert result["drift_rate"] == 0.0


def test_validation_reports_drift_separately_from_hallucination():
    """A page being rewritten is not the plane's fault and must never score as
    a fabrication — it is a different bucket with a different remedy."""
    rechecked = [
        {"claim_id": "c1", "title": "DSG mechatronics unit fails",
         "domain": "transmission", "verdict": "missing"},
    ]
    result = gold.judge_validation(_validation_case(), rechecked)
    assert result["recall"] == 1.0  # still stored, still "found" in the store
    assert result["drifted"] == ["DSG mechatronics unit fails"]
    assert result["drift_rate"] == 1.0
    assert result["hallucination_rate"] == 0.0


def test_validation_catches_a_claim_that_should_never_have_been_accepted():
    rechecked = [
        {"claim_id": "c9", "title": "battery fire risk", "domain": "battery",
         "verdict": "quoted"},
    ]
    result = gold.judge_validation(_validation_case(), rechecked)
    assert result["hallucinated"] == ["battery fire risk"]
    assert result["hallucination_rate"] == 1.0


# ── wilson — the interval every rate above needs ─────────────────────────────

def test_wilson_is_none_for_a_zero_denominator():
    """The zero-denominator rule this whole module has to honour."""
    assert gold.wilson(0, 0) is None


def test_wilson_narrows_with_more_samples():
    narrow_lo, narrow_hi = gold.wilson(60, 100)
    wide_lo, wide_hi = gold.wilson(3, 5)
    assert (narrow_hi - narrow_lo) < (wide_hi - wide_lo)
