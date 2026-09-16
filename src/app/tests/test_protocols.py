"""B123 — how an operation spends a model, chosen from measurements.

*"We need algorithms to pick the best api protocol/technique … qwen3.5 27b
performs well under 80k tokens at this batch size but opus 4.6 can handle Z —
which signals a ratio."*

The failure is two-sided and the middle is narrow. Too little batching re-sends
the brief, the principle and the vocabulary for every document and pays for the
same paragraph over and over. Too much piles context until the model stops
quoting and starts composing — which Kriko catches at the grounding gate, so
the batch is *refused* and the tokens are spent anyway.

Three properties are gated here: the shape lives in the engine and the choosing
does not (layering), a protocol is never promoted on one lucky run, and batching
cannot smuggle an ungrounded quote through by attributing it to whichever page
is handy.
"""

import pytest

from app import protocols
from kriko.research import STANDARD, ApiResearcher, ResearchTask, Spend


def _summary(*, runs: int = 100, acceptance: float = 0.6, **over) -> dict:
    """A bench-summary row, with `accepted`/`refused` counts derived from
    `acceptance` at a fixed sample size — 100 by default, large enough that a
    Wilson interval is narrow and two rates 30+ points apart do not overlap,
    which is what most of these tests are checking."""
    accepted = round(acceptance * runs)
    base = {
        "plane": "api", "model": "qwen", "protocol": "wide", "runs": runs,
        "failures": 0, "accepted": accepted, "refused": runs - accepted,
        "acceptance": acceptance,
    }
    return {**base, **over}


def test_nothing_measured_means_the_behaviour_that_existed_before():
    """A mechanism for going faster must never make a fresh install slower or
    wronger than it was."""
    assert protocols.choose([], "qwen") is STANDARD
    assert protocols.choose([_summary(model="other")], "qwen") is STANDARD


def test_one_lucky_run_never_promotes_a_protocol():
    """Two is not statistics; it is the difference between "it worked once" and
    "it worked", and the alternative is how a benchmark starts lying."""
    assert protocols.choose([_summary(runs=1, acceptance=1.0)], "qwen") is STANDARD


def test_a_protocol_that_mostly_fails_is_not_a_cheap_protocol():
    """A plane that cannot finish is not a fast one. Half the runs failing
    disqualifies the setting however well the survivors scored."""
    assert protocols.choose(
        [_summary(runs=4, failures=3, acceptance=0.9)], "qwen"
    ) is STANDARD


def test_the_measured_winner_is_chosen():
    chosen = protocols.choose(
        [
            _summary(protocol="wide", acceptance=0.62),
            _summary(protocol="standard", acceptance=0.60),
            _summary(protocol="narrow", acceptance=0.30),
        ],
        "qwen",
    )
    assert chosen.name == "wide"


def test_a_candidate_measured_against_nothing_is_not_a_winner():
    """Without a measured default to compare against, a single mediocre run of
    one protocol would promote it — "it is the only one we have" is how a
    benchmark comes to recommend the only thing anybody bothered to run."""
    assert protocols.choose([_summary(protocol="wide", acceptance=0.2)], "qwen") is (
        STANDARD
    )


def test_a_near_tie_goes_to_the_cheaper_one():
    """When two settings keep the same proportion, the one making fewer calls
    is strictly better — and the margin rule has already decided the
    difference is not real."""
    chosen = protocols.choose(
        [
            _summary(protocol="wide", acceptance=0.60),
            _summary(protocol="standard", acceptance=0.62),
        ],
        "qwen",
    )
    assert chosen.name == "wide"
    assert chosen.batch_size > STANDARD.batch_size


def test_a_real_difference_is_not_a_tie():
    chosen = protocols.choose(
        [
            _summary(protocol="wide", acceptance=0.30),
            _summary(protocol="standard", acceptance=0.62),
        ],
        "qwen",
    )
    assert chosen.name == "standard"


def test_the_ratio_is_keyed_by_model_not_by_plane():
    """"the API plane keeps 40%" averages two different models into one
    meaningless number."""
    summary = [
        _summary(model="qwen", protocol="standard", acceptance=0.62),
        _summary(model="qwen", protocol="wide", acceptance=0.20),
        _summary(model="opus", protocol="standard", acceptance=0.55),
        _summary(model="opus", protocol="wide", acceptance=0.80),
    ]
    assert protocols.choose(summary, "qwen").name == "standard"
    assert protocols.choose(summary, "opus").name == "wide"


def test_an_unreadable_benchmark_is_never_why_a_run_does_not_start(tmp_path):
    assert protocols.spend_for(tmp_path / "nope" / "app.sqlite", "qwen") is STANDARD


# ── B126 §5/§9: Wilson intervals replace MIN_MARGIN ──────────────────────────

def test_wilson_intervals_let_a_narrow_sample_say_not_yet_measured():
    """The whole reason for the interval: a 60% acceptance from 5 findings and
    a 60% from 200 must not print — or decide — identically."""
    chosen = protocols.choose(
        [
            _summary(protocol="wide", runs=5, acceptance=0.8),
            _summary(protocol="standard", runs=5, acceptance=0.6),
        ],
        "qwen",
    )
    # Five samples each: the Wilson intervals overlap heavily, so the
    # difference is not real and the cheaper protocol (bigger batch) wins —
    # exactly the "not yet measured" honesty a flat margin could not express,
    # because a flat 5% margin would have called 0.8 vs 0.6 a real win.
    assert chosen.name == "wide"


def test_a_provably_separated_interval_is_not_treated_as_a_tie():
    """Two hundred samples each, with no overlap: this is not noise."""
    chosen = protocols.choose(
        [
            _summary(protocol="wide", runs=200, acceptance=0.30),
            _summary(protocol="standard", runs=200, acceptance=0.62),
        ],
        "qwen",
    )
    assert chosen.name == "standard"


def test_zero_kept_findings_is_not_a_measurement():
    """A protocol whose runs all returned nothing has a zero denominator, not
    a zero rate — and a zero denominator must never be silently treated as a
    zero score."""
    chosen = protocols.choose(
        [
            _summary(protocol="wide", runs=4, accepted=0, refused=0, acceptance=0),
            _summary(protocol="standard", runs=4, accepted=0, refused=0, acceptance=0),
        ],
        "qwen",
    )
    assert chosen is STANDARD


# ── B126 §7: the preamble is a real, named, swept axis ──────────────────────

def test_the_preamble_variants_are_in_the_catalogue():
    """Not a field nobody reads: at least two genuinely different preambles
    must actually appear as protocols the sweep can choose between."""
    preambles = {one.preamble for one in protocols.CATALOGUE}
    assert "terse" in preambles
    assert len(preambles) >= 3
    assert all(one.name in protocols.BY_NAME for one in protocols.CATALOGUE)


def test_the_terse_preamble_is_the_known_good_default():
    assert STANDARD.preamble == "terse"
    assert STANDARD.preamble_text == ""


# ── B126 §7: the sweep's output, per model ──────────────────────────────────

def test_readout_reports_not_yet_measured_rather_than_a_fabricated_number():
    """A model with fewer than MIN_RUNS still gets a row — with `spend` the
    known-good default and a note saying why, never a guess dressed as one."""
    raw = [
        {"model": "qwen", "protocol": "wide", "accepted": 1, "usd": 0.01},
    ]
    rows = protocols.readout(raw, [])
    assert len(rows) == 1
    row = rows[0]
    assert row["protocol"] == STANDARD.name
    assert row["usd_per_accepted_claim"] is None
    assert "not yet measured" in row["note"] or "fewer than" in row["note"]


def test_readout_reports_cost_only_from_two_or_more_priced_runs():
    summary = [_summary(protocol="standard", runs=100, acceptance=0.6)]
    raw = [
        {"model": "qwen", "protocol": "standard", "accepted": 3, "usd": 0.02, "gold": {}},
    ]
    single = protocols.readout(raw, summary)[0]
    assert single["usd_per_accepted_claim"] is None

    raw_two = raw + [
        {"model": "qwen", "protocol": "standard", "accepted": 2, "usd": 0.02, "gold": {}},
    ]
    priced = protocols.readout(raw_two, summary)[0]
    assert priced["usd_per_accepted_claim"] == pytest.approx(0.008, abs=0.0001)


def test_readout_carries_the_hallucination_rate_and_its_interval():
    summary = [_summary(protocol="standard", runs=100, acceptance=0.6)]
    raw = [
        {"model": "qwen", "protocol": "standard", "accepted": 10,
         "gold": {"hallucinated": ["a fabricated claim"]}},
    ]
    row = protocols.readout(raw, summary)[0]
    assert row["hallucination_rate"] == pytest.approx(0.1)
    assert row["hallucination_interval"] is not None


def test_the_engine_defines_the_shape_and_never_the_choice():
    """`kriko/` may not import the interface, and choosing means reading this
    installation's own rows. So the engine owns `Spend` and takes one; the
    picker lives in `app/`."""
    import inspect

    import kriko.research.base as base

    source = inspect.getsource(base)
    assert "class Spend" in source
    assert "bench_runs" not in source
    assert "from app" not in source


# ── the batch, where the money actually changes ──────────────────────────────

PAGE_A = "The mechatronics unit fails on this gearbox at around 120,000 km."
PAGE_B = "Owners report the timing chain tensioner is a known weak point here."


def _task() -> ResearchTask:
    return ResearchTask(
        subject_id="s1", subject_label="Thing", subject_kind="product",
        pack_id="probe", queries=("{label} problems",), domains=("engine",),
        max_documents=4,
    )


class _Model:
    """A completion socket that counts its calls and answers from a script."""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


def _plane(reply: str, spend: Spend) -> tuple[ApiResearcher, _Model]:
    model = _Model(reply)
    plane = ApiResearcher(
        lambda query, limit: [
            {"url": "https://a.test/1", "title": "A", "site": "a.test"},
            {"url": "https://b.test/2", "title": "B", "site": "b.test"},
        ],
        lambda url: PAGE_A if "a.test" in url else PAGE_B,
        model,
        spend=spend,
    )
    return plane, model


def test_a_batch_reads_two_documents_in_one_call():
    """The whole point: the brief is sent once instead of twice."""
    reply = (
        '[{"source_url": "https://a.test/1", "title": "Mechatronics", '
        '"quote": "The mechatronics unit fails on this gearbox at around 120,000 km."},'
        ' {"source_url": "https://b.test/2", "title": "Tensioner", '
        '"quote": "the timing chain tensioner is a known weak point here"}]'
    )
    plane, model = _plane(reply, Spend(name="wide", context_chars=8000, batch_size=4))
    task = _task()
    documents = plane.gather(task)
    found = [finding for one in documents for finding in plane.extract(task, one)]
    assert len(model.prompts) == 1, "a batch that still calls per document is not one"
    assert {one.title for one in found} == {"Mechatronics", "Tensioner"}
    assert {one.source_url for one in found} == {
        "https://a.test/1", "https://b.test/2"
    }


def test_one_document_per_call_is_still_one_call_per_document():
    """`STANDARD` must behave exactly as the plane did before protocols."""
    reply = (
        '[{"title": "Mechatronics", "quote": "The mechatronics unit fails on '
        'this gearbox at around 120,000 km."}]'
    )
    plane, model = _plane(reply, STANDARD)
    task = _task()
    documents = plane.gather(task)
    for one in documents:
        plane.extract(task, one)
    assert len(model.prompts) == len(documents) == 2


def test_a_batch_cannot_file_a_quote_against_the_wrong_page():
    """The attribution slip a batch makes possible, and the reason the
    grounding check is made against the text of the url the model *named*."""
    reply = (
        '[{"source_url": "https://b.test/2", "title": "Misfiled", '
        '"quote": "The mechatronics unit fails on this gearbox at around 120,000 km."}]'
    )
    plane, _ = _plane(reply, Spend(name="wide", context_chars=8000, batch_size=4))
    task = _task()
    documents = plane.gather(task)
    found = [finding for one in documents for finding in plane.extract(task, one)]
    assert found == []


def test_the_context_limit_is_the_protocols_and_not_a_literal():
    page = "z" * 40000
    model = _Model("[]")
    plane = ApiResearcher(
        lambda query, limit: [{"url": "https://a.test/1", "title": "A", "site": "a"}],
        lambda url: page,
        model,
        spend=Spend(name="narrow", context_chars=6000, batch_size=1),
    )
    task = _task()
    documents = plane.gather(task)
    plane.extract(task, documents[0])
    assert model.prompts[0].count("z") == 6000
