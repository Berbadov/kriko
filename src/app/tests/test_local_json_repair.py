"""A small model that wraps or breaks its JSON still completes the stage.

Constrained decoding is requested whenever the runtime takes it
(`OpenAICompatSocket`), and a runtime that refuses it reports `unconstrained`.
On those runtimes a small model fences its object, writes a sentence around it,
or answers in prose once. The stage reads around the wrapping, and re-asks once
when there is nothing to read, instead of losing the page.
"""

import json

import pytest

from app import quicklook
from app.providers import local_agent
from app.providers.local_inference import LocalInferenceError
from app.providers.local_pipeline import EXTRACT_SCHEMA
from app.tests.test_local_quicklook_output import PipelineModel

URL = "https://example.org/report"
PAGE = "Widget owners report that the drive failed after one month, across many forum threads."
FINDING = [{"title": "Drive failure", "why": "An owner reported a failed drive.",
            "needle": "drive failed after one month"}]


class Wrapped(PipelineModel):
    """The runtime does not constrain output, so every object arrives wrapped."""

    structured_output = {"mode": "unconstrained", "reason": "response_format_refused"}

    def json(self, prompt, schema):
        reply = super().json(prompt, schema)
        return "Here is the JSON you asked for:\n```json\n" + reply + "\n```\nHope that helps!"


class ProseFirst(PipelineModel):
    """The first extraction reply is prose; asked again, the model holds the shape."""

    def __init__(self, *args, spoiled=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.spoiled = spoiled
        self.seen: list[str] = []

    def json(self, prompt, schema):
        if schema == EXTRACT_SCHEMA:
            self.seen.append(prompt)
        if schema == EXTRACT_SCHEMA and self.spoiled > 0:
            self.spoiled -= 1
            self.calls.append(("extract", prompt, self.max_tokens))
            return "I found a drive failure but did not write JSON."
        return super().json(prompt, schema)


def _run(model):
    asker = local_agent.LocalAsker(
        lambda _: '["Widget failures"]', model, lambda *_: [{"url": URL}], lambda _: PAGE,
        model="test", search_provider="stub", given_sources={URL: PAGE})
    reply = asker.ask(quicklook.brief("Widget", compact=True))
    return asker, quicklook.parse(reply, asker.sources)


def test_a_fenced_object_with_prose_around_it_is_read_not_lost():
    asker, shown = _run(Wrapped(findings=FINDING))
    assert [one["title"] for one in shown["risks"]] == ["Drive failure"]
    assert asker.coverage["json_repair"]["read_tolerantly"] >= 1
    assert asker.coverage["json_repair"]["asked_again"] == 0


def test_a_prose_reply_is_asked_again_once_and_the_page_is_not_lost():
    model = ProseFirst(findings=FINDING)
    asker, shown = _run(model)
    assert [one["title"] for one in shown["risks"]] == ["Drive failure"]
    assert model.stages().count("extract") == 2
    assert asker.coverage["json_repair"] == {
        "read_tolerantly": 0, "asked_again": 1, "recovered": 1}
    assert "not valid JSON" in model.seen[1] and "did not write JSON" in model.seen[1]


def test_a_model_that_cannot_hold_the_shape_costs_one_extra_call_not_a_loop():
    model = PipelineModel(broken=("extract",))
    asker = local_agent.LocalAsker(
        lambda _: '["Widget failures"]', model, lambda *_: [{"url": URL}], lambda _: PAGE,
        model="test", search_provider="stub", given_sources={URL: PAGE})
    with pytest.raises(LocalInferenceError, match="No evidence pass completed"):
        asker.ask(quicklook.brief("Widget", compact=True))
    assert model.stages().count("extract") == 2
    assert asker.coverage["json_repair"]["recovered"] == 0


def test_once_a_reask_has_failed_the_run_stops_asking():
    """A model that failed the re-ask will fail the next: say so once, spend once."""
    model = PipelineModel(broken=("extract", "verify", "source"))
    pages = {f"https://example.org/{i}": PAGE.replace("Widget", f"Widget MK{i}") for i in range(3)}
    asker = local_agent.LocalAsker(
        lambda _: '["Widget failures"]', model, lambda *_: [], lambda _: "",
        model="test", search_provider="stub", given_sources=pages)
    with pytest.raises(LocalInferenceError):
        asker.ask(quicklook.brief("Widget", compact=True))
    assert asker.coverage["json_repair"]["asked_again"] == 1


def test_a_reply_of_the_wrong_shape_is_still_not_repaired():
    """Valid JSON of the wrong shape is a different failure: no second attempt."""
    model = PipelineModel(wrong_shape=("extract",))
    asker = local_agent.LocalAsker(
        lambda _: '["Widget failures"]', model, lambda *_: [{"url": URL}], lambda _: PAGE,
        model="test", search_provider="stub")
    with pytest.raises(LocalInferenceError, match="Missing risks array"):
        asker.ask(quicklook.brief("Widget", compact=True))
    assert model.stages().count("extract") == 1


def test_valid_json_is_never_reread_or_asked_again():
    model = PipelineModel(findings=FINDING)
    asker, shown = _run(model)
    assert shown["risks"]
    assert asker.coverage["json_repair"] == {"read_tolerantly": 0, "asked_again": 0, "recovered": 0}
    assert json.dumps(asker.coverage)  # the repair counts ride the coverage report
