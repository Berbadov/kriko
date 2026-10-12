"""Local Quick Look keeps source evidence and reports output failures."""

import json

import pytest

from app import quicklook
from app.providers import local_agent, local_asker
from app.providers.local_inference import LocalInferenceError
from app.providers.local_pipeline import (
    EXTRACT_SCHEMA, GROUP_SCHEMA, IDENTITY_SCHEMA, LANGUAGE_CHECK_SCHEMA,
    LANGUAGE_SCHEMA, PAIR_SCHEMA, RENDER_SCHEMA, SOURCE_KIND_SCHEMA, VERIFY_SCHEMA,
)


_STAGES = ((EXTRACT_SCHEMA, "extract"), (VERIFY_SCHEMA, "verify"),
           (SOURCE_KIND_SCHEMA, "source"), (RENDER_SCHEMA, "render"),
           (LANGUAGE_SCHEMA, "language"), (LANGUAGE_CHECK_SCHEMA, "language_check"),
           (GROUP_SCHEMA, "group"), (PAIR_SCHEMA, "pair"), (IDENTITY_SCHEMA, "identity"))


def _stage(schema: dict) -> str:
    # Equal, not identical: a schema that came over HTTP is a decoded copy.
    for shape, name in _STAGES:
        if schema == shape:
            return name
    return "plan" if "queries" in schema.get("properties", {}) else "other"


class PipelineModel:
    """A stand-in for the local model that answers each Quick Look stage by
    the schema it is asked for.

    `findings` are what the model reads in the source sentences: each cites
    the first sentence that contains its `needle`, so a risk always points at
    a real passage. `queries` are the searches it plans. `broken` and
    `wrong_shape` name stages answered with no JSON, or with a reply of the
    wrong shape. Every call is recorded with the reply budget it was given.
    """

    max_tokens = 8192
    last_finish_reason = "stop"

    def __init__(self, findings=(), queries=("widget drive failures",), *,
                 broken=(), wrong_shape=(), window=12000, pack="", pack_identity=None):
        self.findings = list(findings)
        self.pack = pack
        self.pack_identity = dict(pack_identity or {})
        self.queries = list(queries)
        self.broken = set(broken)
        self.wrong_shape = set(wrong_shape)
        self.window = window
        self.calls: list[tuple[str, str, int]] = []

    def prompt_chars_allowed(self) -> int:
        return self.window

    def context_tokens(self) -> int:
        return 4096

    def stages(self) -> list[str]:
        return [stage for stage, _, _ in self.calls]

    def json(self, prompt, schema):
        stage = _stage(schema)
        self.calls.append((stage, prompt, self.max_tokens))
        if stage in self.broken:
            return "I found a drive failure but did not write JSON."
        if stage in self.wrong_shape:
            return json.dumps({"answer": "a drive failure"})
        return json.dumps(self._answer(stage, prompt), ensure_ascii=False)

    def __call__(self, prompt):
        return self.json(prompt, {})

    def _answer(self, stage: str, prompt: str):
        if stage == "identity":
            return {"canonical_name": "", "aliases": [], "variant": "", "identifiers": [],
                    "unknowns": [], "evidence": [], "brand": "", "item": "",
                    "item_terms": [], "fits": ""}
        if stage == "language":
            return {"language": "en"}
        if stage == "language_check":
            return {"matches": True}
        if stage == "plan":
            return {"queries": self.queries}
        if stage == "extract":
            sentences = json.loads(prompt.split("SOURCE SENTENCES:\n", 1)[1])
            risks = []
            for finding in self.findings:
                ids = [key for key, text in sentences.items()
                       if finding["needle"].casefold() in text.casefold()]
                if ids:
                    risks.append({"title": finding["title"], "why": finding["why"],
                                  "check": "", "severity": "high", "evidence": ids[:1]})
            return {"category": "", "pack": self.pack, "pack_identity": self.pack_identity,
                    "risks": risks, "specs": []}
        if stage == "verify":
            return {"evidence_kind": "problem", "support": "supported", "identity": "match"}
        if stage == "source":
            return {"kind": "problem"}
        if stage == "render":
            shown = json.loads(prompt[prompt.index('{"display_text"'):])["display_text"]
            return {"title": shown["title"], "why": shown["body"], "check": shown["advice"]}
        if stage == "group":
            return {"groups": []}
        if stage == "pair":
            return {"same_failure": False}
        return {}


def test_the_local_plane_searches_on_this_machine_whatever_the_setting_says():
    """Exa left the local plane: its search is OpenSERP on this machine, and a
    local scraper is asked one query at a time, never in a burst."""
    asker = local_asker(base_url="http://127.0.0.1:1", serving_name="test",
                        search_kind="exa")
    assert asker.search_provider == "openserp"
    assert asker.parallel_search is False


def test_small_runtime_receives_a_bounded_prompt_and_grounded_answer():
    url = "https://example.org/report"
    quote = "The Widget drive failed after one month."
    model = PipelineModel(findings=[{"title": "Drive failure",
                                     "why": "An owner reported a failed drive.",
                                     "needle": "drive failed after one month"}])
    asker = local_agent.LocalAsker(lambda _: '["Widget drive failures"]', model,
        lambda *_: [{"url": url}],
        lambda _: "Widget forum thread\n\n" + "Navigation\n\n" * 1500 + quote,
        model="test", search_provider="stub")
    reply = asker.ask(quicklook.brief("Widget", compact=True))
    result = quicklook.parse(reply, asker.sources)
    assert result["risks"][0]["sources"][0]["grounded"]
    # Every prompt fits the window the runtime reports, and every reply is
    # budgeted: a small model is not handed the 8k default.
    assert model.calls and all(len(prompt) <= model.window for _, prompt, _ in model.calls)
    assert all(budget <= local_agent.REPLY_MAX_TOKENS for _, _, budget in model.calls)


def test_the_local_answer_carries_the_packs_identity_only_for_a_listed_pack():
    url = "https://example.org/report"
    finding = [{"title": "Drive failure", "why": "An owner reported a failed drive.",
                "needle": "drive failed after one month"}]
    page = lambda _: "Widget owners report that the drive failed after one month, across many forum threads."  # noqa: E731
    packs = "* `widgets`, Widgets [identity product: brand, model]"
    for named, expected in (("widgets", {"brand": "Acme", "model": "W1"}), ("invented", {})):
        model = PipelineModel(findings=finding, pack=named,
                              pack_identity={"brand": "Acme", "model": "W1"})
        asker = local_agent.LocalAsker(lambda _: '["Widget drive failures"]', model,
                                       lambda *_: [{"url": url}], page,
                                       model="test", search_provider="stub")
        result = quicklook.parse(asker.ask(quicklook.brief("Widget", packs=packs, compact=True)),
                                 asker.sources)
        assert result["pack_identity"] == expected


def test_wrong_json_shape_is_not_a_card_and_is_not_repaired():
    url = "https://example.org/report"
    model = PipelineModel(wrong_shape=("extract",))
    asker = local_agent.LocalAsker(lambda _: '["Widget failures"]', model,
        lambda *_: [{"url": url}],
        lambda _: "Widget owners report that the drive failed after one month, across many forum threads.",
        model="test", search_provider="stub")
    # No card, and no second attempt that could invent one: the only page
    # was asked once, and the run says why nothing was evidenced.
    with pytest.raises(LocalInferenceError, match="Missing risks array"):
        asker.ask(quicklook.brief("Widget", compact=True))
    assert model.stages().count("extract") == 1


def test_empty_result_reports_the_actual_output_failure():
    invalid = "I found several issues but did not produce JSON."
    assert "unreadable" in quicklook.outcome(invalid, quicklook.parse(invalid))
    assert "cut off" in quicklook.outcome(invalid, quicklook.parse(invalid),
                                          finish_reason="length")
    empty = '{"risks": [], "specs": []}'
    assert "did not yield" in quicklook.outcome(empty, quicklook.parse(empty))


def test_unverified_claims_do_not_become_cards():
    reply = json.dumps({"risks": [{"title": "Failure", "url": "https://e.org",
                                   "quote": "an invented quote"}]})
    found = quicklook.parse(reply, {"https://e.org": "a different statement"})
    assert not found["risks"]
    assert "source checks" in quicklook.outcome(reply, found)


def test_specs_cannot_cite_an_address_that_was_never_read():
    reply = json.dumps({"specs": [{"name": "Weight", "value": "2 kg",
                                  "url": "https://misspelled.example/spec"}]})
    assert not quicklook.parse(reply, {"https://example.org/spec": "2 kg"})["specs"]


def test_planner_cannot_change_the_brand_and_model():
    product = "Şımart Katya Ü"
    queries = local_agent.plan.propose(quicklook.brief(product, compact=True),
        lambda _: '["another brand failures", "robot vacuum problems"]')
    assert all(product in query for query in queries)
