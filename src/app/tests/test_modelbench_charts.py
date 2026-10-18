"""The charts: that they render, that they cannot lie, and that they cannot drift.

A graph is the one part of this report that carries a finding with no words
beside it, so it gets the same treatment as the numbers: every way a picture
could misstate the data has a test.

Three of these are regressions from the first version of `charts.py`, which was
looked at before it was trusted:

* the log axis snapped outward to whole decades and drew 100 → 100,000 for data
  spanning 862 → 8,081, which left 60% of the picture empty and both interesting
  models in one corner;
* the axis ticks were derived from the data (`2,020 · 4,041 · 6,061 · 8,081`),
  which is a scale nobody can read without dividing;
* a document where five bars four pixels tall sat five pixels apart, so five
  metrics per model merged into one block.

Every one of those was invisible in the code and obvious on the page.
"""

import json
import re
import xml.etree.ElementTree as ET

import pytest

from app.modelbench import charts, report
from app.tests.test_modelbench import _row

CANDIDATES = ("local:qwen3.5:4b", "local:qwen3.5:0.8b", "harness:mistral-vibe@glm-5-3")


def document(*, measured=True, rate=True):
    """A small document in the shape `report.build` produces."""
    rows = []
    for index, name in enumerate(CANDIDATES):
        for case_id in ("c1", "c2"):
            rows.append(_row(
                candidate_id=name, case_id=case_id,
                found=1, wanted=1, produced=2 if index else 1,
                fabricated=index, tokens=100 * (index + 1),
                usage="reported" if measured else "none",
                specs_wanted=1, specs_found=1 - (index % 2),
                spec_errors=("x: y",) if index == 1 else (),
            ))
            if not rate:
                rows[-1].score["produced"] = 0
                rows[-1].score["hallucination_rate"] = None
    return report.build(rows, title="t", when="now")


def svg_of(name, doc=None):
    return charts.render(doc or document())[name]


# ── they render ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(charts.ALL))
def test_every_chart_renders_as_well_formed_xml(name):
    markup = svg_of(name)
    root = ET.fromstring(markup)
    assert root.tag.endswith("svg")
    assert root.get("viewBox")
    # A picture with no accessible name is a finding half the readers cannot
    # get at, so the title is part of the contract rather than a nicety.
    assert root.get("role") == "img"
    assert "chart-title" in markup


@pytest.mark.parametrize("name", sorted(charts.ALL))
def test_a_chart_is_deterministic(name):
    """Two renders of one document must be byte-identical: they are diffed."""
    assert svg_of(name) == svg_of(name)


def text_of(markup: str) -> list[str]:
    """Every string a reader can actually see in the picture.

    The checks below are about *text*, so they read text nodes. Sweeping the
    whole document for `{` and `}` flags the stylesheet, which is not a
    placeholder leaking into a chart — it is the theme.
    """
    root = ET.fromstring(markup)
    return [node.text or "" for node in root.iter() if node.tag.endswith("text")]


@pytest.mark.parametrize("name", sorted(charts.ALL))
def test_no_placeholder_leaks_into_a_picture(name):
    for text in text_of(svg_of(name)):
        for bad in ("None", "nan", "NaN", "{", "}", "undefined"):
            assert bad not in text, f"{bad!r} reached a label in the {name} chart"


def test_no_label_is_empty():
    """A label with no text is a mark a reader cannot account for."""
    for name in charts.ALL:
        assert all(text.strip() for text in text_of(svg_of(name))), name


def test_a_model_name_cannot_break_the_document():
    """A candidate id is data, and data can contain markup."""
    doc = document()
    doc["candidates"][0]["candidate"] = 'local:<script>&"x"'
    markup = charts.render(doc)["quality"]
    ET.fromstring(markup)
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup


def test_a_document_with_nothing_metered_still_draws_a_picture():
    """An unmeasured sweep is a report to print, not a crash."""
    doc = document(measured=False)
    for name in ("tradeoff", "tokens"):
        markup = charts.render(doc)[name]
        ET.fromstring(markup)
    assert "No candidate produced" in charts.render(doc)["tradeoff"]


# ── they cannot lie ───────────────────────────────────────────────────────

def test_a_model_with_no_fabrication_rate_is_named_and_not_silently_dropped():
    """A model missing from the decision chart must be explained, not absent.

    `gemma3n:e2b` claimed nothing, so it has no fabrication rate to plot. Left
    out with no note, its absence reads as an oversight in its favour.
    """
    rows = [
        _row(candidate_id="local:good", case_id="c1", produced=2, fabricated=0),
        _row(candidate_id="local:silent", case_id="c1", produced=0, fabricated=0),
    ]
    doc = report.build(rows, title="t", when="now")
    markup = charts.render(doc)["tradeoff"]
    assert charts.short_name("local:silent") in markup
    assert "no fabrication" in markup
    # One bubble, drawn as a filled circle and an outlined one. Two would mean
    # the unplottable model had been drawn anyway, at a height it never earned.
    root = ET.fromstring(markup)
    circles = [node for node in root.iter() if node.tag.endswith("circle")]
    assert len(circles) == 2


def test_a_dash_is_used_where_there_is_no_denominator_never_a_zero():
    """No wrong specs and nothing returned are different facts."""
    rows = [_row(candidate_id="local:silent", case_id="c1", specs_wanted=2,
                 specs_found=0, spec_errors=())]
    rows[0].score["produced"] = 0
    rows[0].score["hallucination_rate"] = None
    doc = report.build(rows, title="t", when="now")
    assert "—" in charts.render(doc)["quality"]


def test_the_log_axis_is_scaled_to_its_data():
    """The regression: data spanning 862 → 8,081 got an axis of 100 → 100,000."""
    low, high = charts.nice_log_bounds(861.8, 8081.1)
    assert low == 500.0, "the axis must not start two whole decades below the data"
    assert high == 10_000.0
    assert low < 861.8 < high and low < 8081.1 < high


def test_axis_steps_are_round_numbers():
    """The regression: ticks derived from the data read as 2,020 · 4,041 · 6,061.

    2,500 counts as round — it is one of the four steps this axis is allowed to
    use (1, 2, 2.5 or 5 times a decade). What must never happen is a tick at
    4,041, which is an artefact of the largest value rather than a scale.
    """
    step = charts.nice_step(8081.1)
    assert is_round_step(step)
    ticks = [n * step for n in range(int(8081.1 // step) + 2)]
    # The ticks are the *step* repeated, so they are whole numbers. The old
    # version divided the largest value by four and produced 2,020 · 4,041 ·
    # 6,061 · 8,081, which is the data rather than a scale.
    assert all(float(value).is_integer() for value in ticks)
    assert 4041.0 not in ticks and 2020.0 not in ticks
    assert max(ticks) >= 8081.1


def is_round_step(value: float) -> bool:
    """`1`, `2`, `2.5` or `5` times a power of ten — the ladder the axis uses."""
    for decade in range(-3, 9):
        for multiple in (1.0, 2.0, 2.5, 5.0):
            if abs(value - multiple * 10.0 ** decade) < 1e-9:
                return True
    return False


# ── they cannot drift from the report ─────────────────────────────────────

def test_the_report_embeds_every_chart_it_writes(tmp_path):
    """A broken image link is the one failure a reader always notices.

    The Markdown names the files; `write` creates them. This is the test that
    those two agree, because nothing else checks them together.
    """
    rows = [_row(case_id="c1"), _row(case_id="c2", candidate_id="local:b")]
    paths = report.write(tmp_path, rows, stem="probe", title="t", when="now")
    text = (tmp_path / "probe.md").read_text(encoding="utf-8")
    links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    assert links, "the report embedded no charts at all"
    for link in links:
        assert (tmp_path / link).exists(), f"{link} is linked but was never written"
    for name in charts.ALL:
        assert f"chart_{name}" in paths


def test_a_rerender_rebuilds_the_charts_too(tmp_path):
    """A corrected rate must not leave a stale picture standing beside it."""
    rows = [_row(case_id="c1")]
    report.write(tmp_path, rows, stem="first", title="t", when="then")
    (tmp_path / "first-tradeoff.svg").unlink()
    report.rerender(tmp_path / "first.json")
    assert (tmp_path / "first-tradeoff.svg").exists()
    text = (tmp_path / "first.md").read_text(encoding="utf-8")
    assert "first-tradeoff.svg" in text


def test_the_pictures_carry_the_same_verdict_as_the_table(tmp_path):
    """Spot-check the one number a reader takes from the hero chart.

    The bubble area is expected facts found and the dot is the fabrication rate.
    If a chart ever recomputed either, this is where it would show.
    """
    rows = [_row(candidate_id="local:a", case_id="c1", produced=4, fabricated=2)]
    doc = report.build(rows, title="t", when="now")
    candidate = doc["candidates"][0]
    assert candidate["hallucination_rate"] == 0.5
    markup = charts.render(doc)["tradeoff"]
    assert "50%" in markup
    assert charts.short_name("local:a") in markup


# ── small pieces ──────────────────────────────────────────────────────────

def test_short_name_keeps_the_kind_and_drops_the_routing():
    assert charts.short_name("local:qwen3.5:4b") == "qwen3.5:4b"
    assert charts.short_name("harness:mistral-vibe@glm-5-3") == "glm-5-3 (CLI)"
    assert charts.short_name("api:gpt-4o-mini") == "gpt-4o-mini"


def test_prose_wraps_on_spaces_and_labels_wrap_on_hyphens():
    prose = charts.wrap_text("one two three four five six", 12)
    assert prose == ["one two", "three four", "five six"]
    label = charts.wrap("sold-product-vs-host", 11)
    assert len(label) > 1
    assert all(len(line) <= 12 for line in label)


def test_the_axis_bounds_are_the_same_function_for_one_value():
    low, high = charts.nice_log_bounds(1000.0, 1000.0)
    assert low < 1000.0 < high
    assert is_round_step(low) and is_round_step(high)


def test_the_document_json_holds_everything_a_chart_reads():
    """The charts are rebuilt from the saved JSON, so it must carry their input."""
    doc = document()
    encoded = json.loads(json.dumps(doc))
    for name in charts.ALL:
        ET.fromstring(charts.render(encoded)[name])
