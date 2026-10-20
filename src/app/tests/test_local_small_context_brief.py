"""A small context gets a smaller brief, and the pack's bar is never the part cut.

On a 4k window the extraction prompt is policy plus evidence. A reader with
thirty packs installed saw the pack listing alone take the evidence's room,
and the page was lost with "task leaves no context". The listing is a lookup
table and the instructions have a compact form; the bar the pack declares is
the reader's taste and is carried verbatim or the run says it cannot.
"""

import json

import pytest

from app.providers import local_agent
from app.providers.local_identity import ProductIdentity
from app.providers.local_inference import LocalInferenceError
from app.providers.local_pipeline import QuickLookPipeline
from app.tests.test_local_quicklook_output import FourKPipelineModel

URL = "https://example.org/manual"
PAGE = "Widget MK2 owner report: the pump failed after one month."
BAR = ("## What is worth saying\n\nThe installed pack's own bar, verbatim:\n\n"
       "Surface a fault only when it is specific to this configuration.\n"
       "Do not surface what is true of every product in the category.\n")


def _listing(count: int) -> str:
    rows = "\n".join(f"* `pack-{i}`, Category number {i} with a long descriptive name "
                     f"[identity product: brand, model, year, variant]" for i in range(count))
    return ("## Where it belongs\n\nThese installed packs each hold one kind of product:\n\n"
            + rows + "\n\nIf this product is that kind, give the pack's id in `pack`.\n")


def _extract(task: str):
    model = FourKPipelineModel()
    asker = local_agent.LocalAsker(model, model, lambda *_: [], lambda _: "",
                                   model="test", search_provider="stub")
    pipeline = QuickLookPipeline(asker)
    pipeline.identity = ProductIdentity(canonical_name="Widget MK2", identifiers=("MK2",))
    asker.page_titles[URL] = "Widget MK2 service record"
    pipeline._extract(URL, PAGE, task, 1)
    prompt = next(text for stage, text, _ in model.calls if stage == "extract")
    return model, pipeline, prompt


def test_a_long_pack_listing_no_longer_takes_the_evidences_room():
    model, pipeline, prompt = _extract(BAR + _listing(60))
    assert len(prompt.encode("utf-8")) <= model.prompt_bytes_allowed(reply_tokens=768)
    assert "the pump failed after one month" in prompt
    budget = pipeline.coverage["context_budget"]["extract"]
    assert budget["brief_shortened"] is True


def test_the_bar_survives_whole_whatever_is_shortened():
    _, _, prompt = _extract(BAR + _listing(60))
    assert BAR.strip() in prompt


def test_a_task_that_fits_is_left_exactly_as_it_was():
    task = BAR + _listing(2)
    _, pipeline, prompt = _extract(task)
    assert task.strip() in prompt
    assert pipeline.coverage["context_budget"]["extract"]["brief_shortened"] is False


def test_the_bar_alone_too_big_is_refused_not_cut():
    huge = "## What is worth saying\n\n" + "Keep every claim tied to the bar. " * 400
    with pytest.raises(LocalInferenceError, match="no context for evidence"):
        _extract(huge)


def test_the_instructions_take_their_compact_form_only_when_the_window_needs_it():
    _, _, full = _extract(BAR + _listing(2))
    _, _, compact = _extract(BAR + _listing(60))
    assert "Describe only the scope stated" in full
    assert "Describe only the scope stated" not in compact
    # The rules that protect the grounding stay in the compact form.
    assert "never write or translate quotes or URLs" in compact
    assert json.loads(compact.split("PRODUCT IDENTITY:\n", 1)[1].split("\nTASK:", 1)[0])
