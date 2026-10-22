"""A paraphrased quote is repaired by one bounded re-ask, never excused.

The small model finds the real fault, then re-words the sentence it just read.
`quicklook.parse` refuses the re-worded quote, correctly. The repair asks the
model once which numbered sentence of the page says what its claim says, and
copies that sentence's own characters in. Grounding is checked again afterwards
by the same gate, so nothing about it is weaker.
"""

import json

from app import quicklook
from app.providers import local_components
from app.providers.local_components import repair

URL = "https://a.test/thread"
PAGE = ("Widget MK2 owner forum. Several owners report that the hydraulic pump failed "
        "after a month of normal use. The tyres are covered by a separate warranty. "
        "Replacement pumps cost about forty euros.")


def _answer(*claims):
    return "```json\n" + json.dumps({"assumed": "", "category": "widgets", "pack": "",
                                     "specs": [], "risks": list(claims)}) + "\n```"


PARAPHRASE = {"title": "Pump failure", "why": "The hydraulic pump fails within a month.",
              "check": "", "severity": "high", "url": URL,
              "quote": "the hydraulic pump broke down after one month"}
CARRIED = {"title": "Tyre warranty", "why": "Tyres have their own warranty.", "check": "",
           "severity": "low", "url": URL,
           "quote": "The tyres are covered by a separate warranty."}


class Model:
    """A scripted small model; every prompt it is handed is kept."""

    max_tokens = 1024

    def __init__(self, answer, fixes=None, *, fail_repair=False):
        self.answer, self.fixes, self.fail_repair = answer, fixes, fail_repair
        self.prompts: list[str] = []

    def _reply(self, prompt):
        self.prompts.append(prompt)
        if "cite a quote that is not written on the page" in prompt:
            if self.fail_repair:
                raise RuntimeError("the runtime fell over")
            return json.dumps({"fixes": self.fixes or []})
        if "checking an answer against the pages" in prompt:
            return json.dumps({"unsupported": [], "note": "ok"})
        return self.answer

    def __call__(self, prompt):
        return self._reply(prompt)

    def json(self, prompt, schema):
        return self._reply(prompt)

    def repair_calls(self):
        return [one for one in self.prompts if "cite a quote that is not written" in one]


def _asker(model):
    asker = local_components.LocalAsker(
        model, model, None, None, model="small", search_provider="supplied",
        given_sources={URL: PAGE})
    asker.on_action = lambda line: None
    return asker


def _ask(model):
    asker = _asker(model)
    reply = asker.ask(quicklook.brief("Widget MK2", compact=True))
    return asker, reply, quicklook.parse(reply, asker.sources)


def test_a_model_that_names_no_sentence_leaves_the_paraphrase_refused_as_before():
    """The failure being fixed is that the model had the right sentence and
    re-worded it; a model that cannot say which sentence changes nothing."""
    asker, reply, shown = _ask(Model(_answer(PARAPHRASE), fixes=[]))
    assert shown["risks"] == [] and shown["dropped"] == 1
    assert asker.quote_repair["repaired"] == 0


def test_the_model_points_at_a_sentence_and_the_pages_own_words_become_the_quote():
    model = Model(_answer(PARAPHRASE), fixes=[{"claim": 1, "sentence": 1}])
    asker, reply, shown = _ask(model)
    assert [one["title"] for one in shown["risks"]] == ["Pump failure"]
    quote = shown["risks"][0]["sources"][0]["quote"]
    assert quote in PAGE and "hydraulic pump failed" in quote
    assert shown["risks"][0]["sources"][0]["grounded"] is True
    assert asker.quote_repair == {"asked": 1, "repaired": 1, "unrepairable": 0}


def test_whatever_the_model_writes_the_quote_is_the_pages_not_the_models():
    model = Model(_answer(PARAPHRASE), fixes=[{"claim": 1, "sentence": 1}])
    asker, reply, shown = _ask(model)
    assert "broke down" not in reply
    assert "broke down" not in shown["risks"][0]["sources"][0]["quote"]


def test_a_none_of_these_answer_leaves_the_claim_refused():
    asker, reply, shown = _ask(Model(_answer(PARAPHRASE), fixes=[{"claim": 1, "sentence": 0}]))
    assert shown["risks"] == [] and shown["dropped"] == 1


def test_a_choice_outside_the_offered_sentences_changes_nothing():
    asker, reply, shown = _ask(Model(_answer(PARAPHRASE), fixes=[{"claim": 1, "sentence": 99}]))
    assert shown["risks"] == []
    assert asker.quote_repair["repaired"] == 0


def test_a_repair_that_cannot_run_costs_the_answer_nothing():
    asker, reply, shown = _ask(Model(_answer(PARAPHRASE, CARRIED), fail_repair=True))
    assert [one["title"] for one in shown["risks"]] == ["Tyre warranty"]


def test_a_claim_no_sentence_resembles_is_not_offered_and_stays_refused():
    odd = {**PARAPHRASE, "title": "Gearbox noise", "why": "Clutch rattles loudly.",
           "quote": "clutch rattles loudly"}
    model = Model(_answer(odd), fixes=[{"claim": 1, "sentence": 1}])
    asker, reply, shown = _ask(model)
    assert model.repair_calls() == []
    assert shown["risks"] == []
    assert asker.quote_repair["unrepairable"] == 1


def test_all_carried_means_no_extra_call():
    model = Model(_answer(CARRIED))
    asker, reply, shown = _ask(model)
    assert model.repair_calls() == []
    assert [one["title"] for one in shown["risks"]] == ["Tyre warranty"]


def test_one_call_whatever_the_number_of_claims():
    many = [{**PARAPHRASE, "title": f"Pump failure {i}"} for i in range(5)]
    model = Model(_answer(*many), fixes=[{"claim": i, "sentence": 1} for i in range(1, 6)])
    asker, reply, shown = _ask(model)
    assert len(model.repair_calls()) == 1
    assert len(shown["risks"]) == 5


def test_a_made_up_link_is_pointed_at_the_read_page_its_claim_belongs_to():
    lost = {**PARAPHRASE, "url": "https://made-up.test/x"}
    model = Model(_answer(lost), fixes=[{"claim": 1, "sentence": 1}])
    asker, reply, shown = _ask(model)
    assert shown["risks"][0]["sources"][0]["url"] == URL


def test_the_gate_is_not_weakened_a_paraphrase_still_fails_grounding():
    assert quicklook.parse(_answer(PARAPHRASE), {URL: PAGE})["risks"] == []
    assert repair.not_carried(json.loads(_answer(PARAPHRASE)[8:-4]), {URL: PAGE})
