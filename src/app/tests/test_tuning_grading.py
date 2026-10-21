"""The grader is independent, blind to the answerer, and checked against the evidence."""

import json

import pytest

from app.tests import tuning_fakes as fakes
from app.tuning import agents as agent_mod
from app.tuning import evidence, failures, grade
from app.tuning.answer import Answer


def _graded(case, answer, verdict_reply, *, pages=None):
    agent = fakes.FakeGraderAgent(default=verdict_reply)
    found = evidence.collect(evidence.urls_in(answer.text), answer.read_urls, pages or fakes.fetch,
                             question=case["question"])
    links = evidence.links_summary(found)
    return grade.Grader(agent).grade(case, answer, found, links), agent


# ── who may grade ───────────────────────────────────────────────────────────

def test_the_grader_is_never_the_agent_that_answered():
    roster = [fakes.ANSWERER, fakes.GRADER]
    assert agent_mod.choose_grader(fakes.ANSWERER, roster).id == "claude-code"
    assert agent_mod.choose_grader(fakes.GRADER, roster).id == "codex"


def test_with_only_the_answerer_available_nothing_is_graded_by_itself():
    with pytest.raises(agent_mod.NoIndependentGrader, match="never lets an agent grade itself"):
        agent_mod.choose_grader(fakes.ANSWERER, [fakes.ANSWERER])


def test_naming_the_answerer_as_grader_is_refused():
    with pytest.raises(agent_mod.NoIndependentGrader, match="grade its own"):
        agent_mod.choose_grader(fakes.ANSWERER, [fakes.ANSWERER, fakes.GRADER], wanted="codex")


def test_two_ids_serving_one_model_do_not_count_as_two_agents():
    twin = agent_mod.AgentRef("codex-api", "Codex API", "api", "model-a")
    with pytest.raises(agent_mod.NoIndependentGrader):
        agent_mod.choose_grader(fakes.ANSWERER, [fakes.ANSWERER, twin])
    with pytest.raises(agent_mod.NoIndependentGrader, match="same model"):
        agent_mod.choose_grader(fakes.ANSWERER, [fakes.ANSWERER, twin], wanted="codex-api")


# ── what the grader is shown ────────────────────────────────────────────────

def test_the_grader_sees_the_answer_and_the_pages_and_nothing_about_the_answerer():
    answer = fakes.good_answer()
    answer.verification = {"status": "unverified"}
    _, agent = _graded(fakes.CASE, answer, fakes.verdict())
    prompt = agent.prompts[0]
    assert "stainless steel" in prompt and fakes.URL in prompt          # the answer and the page
    assert "REASONING-LINE" not in prompt and "step: searching" not in prompt   # its reasoning
    for identity in ("codex", "Codex", "model-a", "searchprov-x"):
        assert identity not in prompt, identity                          # who and how


def test_the_packet_names_no_agent_even_for_a_follow_up_with_history():
    case = {**fakes.CHAT, "history": [{"role": "reader", "text": "earlier question"},
                                      {"role": "agent", "text": "earlier answer"}]}
    packet = grade.packet(case, "an answer", [])
    assert [one["role"] for one in packet["earlier_conversation"]] == ["reader", "agent"]
    assert "codex" not in json.dumps(packet)


def test_the_grader_gets_scrubbed_question_history_and_page_text_but_citations_still_validate(monkeypatch):
    secret = "environment-secret-value-12345678"
    monkeypatch.setenv("SERVICE_API_KEY", secret)
    url = f"{fakes.URL}?api_key={secret}"
    case = {**fakes.CASE, "question": f"Does this work? {secret} {url}",
            "history": [{"role": "reader", "text": f"Earlier: {secret}"}]}
    answer = fakes.good_answer(text=f"Stainless steel, 8 bar [{url}].", read_urls=[url])
    pages = [{"url": url, "opens": True, "chars": 100,
              "text": f"The stainless steel pump housing is rated for 8 bar. {secret}",
              "in_answer": True, "read_by_answerer": True}]

    class EchoingGrader:
        ref = fakes.GRADER

        def __init__(self):
            self.prompt = ""

        def ask(self, prompt):
            self.prompt = prompt
            packet = json.loads(prompt.split(grade.GRADER_SYSTEM, 1)[1])
            safe_url = packet["evidence"][0]["url"]
            return json.dumps(fakes.verdict(
                facts=[{"id": "material", "status": "met", "url": safe_url,
                        "quote": "stainless steel pump housing", "reason": "shown"},
                       {"id": "rating", "status": "met", "url": safe_url,
                        "quote": "rated for 8 bar", "reason": "shown"}],
                claims=[{"text": "rated for 8 bar", "supported": "yes", "url": safe_url,
                         "quote": "rated for 8 bar"}]))

    agent = EchoingGrader()
    got = grade.Grader(agent).grade(case, answer, pages, evidence.links_summary(pages))
    assert secret not in agent.prompt
    assert "api_key=[redacted]" in agent.prompt
    assert got["accepted"] is True
    assert got["claims"][0]["url"] == url


# ── the grader's verdicts are checked, not trusted ──────────────────────────


def test_a_redacted_url_shared_by_distinct_pages_cannot_verify_a_citation():
    urls = [f"{fakes.URL}?api_key={value}" for value in ("first-secret", "second-secret")]
    pages = [{"url": url, "opens": True, "chars": 100,
              "text": "a stainless steel pump housing rated for 8 bar",
              "in_answer": True, "read_by_answerer": True} for url in urls]
    alias = f"{fakes.URL}?api_key=[redacted]"
    reply = fakes.verdict(
        facts=[{"id": name, "status": "met", "url": alias,
                "quote": "rated for 8 bar"} for name in ("material", "rating")],
        claims=[{"text": "rated for 8 bar", "supported": "yes", "url": alias,
                 "quote": "rated for 8 bar"}])
    agent = fakes.FakeGraderAgent(default=reply)
    got = grade.Grader(agent).grade(fakes.CASE, fakes.good_answer(), pages,
                                   evidence.links_summary(pages))
    assert got["accepted"] is False
    assert all(not fact["verified"] for fact in got["facts"])
    assert got["claims"][0]["supported"] == "unverified"

def test_a_sound_answer_is_accepted():
    graded, _ = _graded(fakes.CASE, fakes.good_answer(), fakes.verdict())
    assert graded["accepted"] is True and graded["fact_credit"] == 1.0
    assert graded["links"]["total"] == 1 and graded["links"]["open"] == 1


def test_a_fact_marked_met_with_no_quotation_the_page_carries_is_downgraded():
    reply = fakes.verdict(facts=[
        {"id": "material", "status": "met", "url": fakes.URL, "quote": "made of solid titanium", "reason": "x"},
        {"id": "rating", "status": "met", "url": fakes.URL, "quote": "rated for 8 bar", "reason": "x"}])
    graded, _ = _graded(fakes.CASE, fakes.good_answer(), reply)
    assert graded["facts"][0]["status"] == "partial" and graded["facts"][0]["verified"] is False
    assert graded["accepted"] is False                       # a critical fact is not fully correct
    assert any("downgraded to partial" in note for note in graded["normalisations"])


def test_a_claim_marked_supported_whose_quotation_is_not_on_its_page_is_unverified():
    reply = fakes.verdict(claims=[{"text": "Waterproof to 30 m", "supported": "yes",
                                   "url": fakes.URL, "quote": "waterproof to thirty metres"}])
    graded, _ = _graded(fakes.CASE, fakes.good_answer(), reply)
    assert graded["claims"][0]["supported"] == "unverified"
    assert graded["claims_supported"] == 0 and graded["accepted"] is False


def test_a_link_that_was_never_read_and_does_not_open_is_an_invented_link():
    answer = fakes.good_answer(text="Stainless steel, 8 bar [https://made-up.example/spec] "
                                    f"and [{fakes.URL}].")
    graded, _ = _graded(fakes.CASE, answer, fakes.verdict())
    assert graded["links"]["invented"] == ["https://made-up.example/spec"]
    assert graded["accepted"] is False
    assert "invented_link" in failures.classify_row("", answer.text, graded)


def test_a_link_that_was_read_but_will_not_reopen_is_not_called_invented():
    answer = fakes.good_answer(text=f"Stainless steel, 8 bar [{fakes.URL}].",
                               read_urls=[fakes.URL])
    graded, _ = _graded(fakes.CASE, answer, fakes.verdict(),
                        pages=lambda url: "" if url == fakes.URL else fakes.fetch(url))
    assert graded["links"]["broken"] == [fakes.URL] and graded["links"]["invented"] == []


def test_a_wrong_product_fails_even_when_every_fact_is_met():
    graded, _ = _graded(fakes.CASE, fakes.good_answer(),
                        fakes.verdict(identity={"matches": False, "reason": "the MK1"}))
    assert graded["accepted"] is False
    assert "wrong_identity" in failures.classify_row("", "x", graded)


def test_an_ignored_requirement_fails_and_is_classified():
    graded, _ = _graded(fakes.CASE, fakes.good_answer(),
                        fakes.verdict(requirements_ignored=["answer in Turkish"]))
    assert graded["accepted"] is False
    assert "ignored_requirement" in failures.classify_row("", "x", graded)


def test_missing_the_primary_source_the_case_requires_fails():
    answer = fakes.good_answer(text="Stainless steel, 8 bar [https://forum.example/thread].",
                               read_urls=["https://forum.example/thread"])
    graded, _ = _graded(fakes.CASE, answer, fakes.verdict())
    assert graded["primary"] == {"found": 0, "needed": 1} and graded["accepted"] is False


# ── asking instead of answering ─────────────────────────────────────────────

def test_a_clarifying_question_passes_where_one_is_expected():
    answer = fakes.good_answer(text="Which variant is it: the EVA or the cork one?", read_urls=[],
                               asked_question=True)
    reply = fakes.verdict(facts=[{"id": "ask", "status": "met", "url": "", "quote": "", "reason": "asks"}],
                          claims=[], asked_for_clarification=True)
    graded, _ = _graded(fakes.CLARIFY, answer, reply)
    assert graded["accepted"] is True


def test_answering_where_a_question_was_expected_fails_as_a_mismatch():
    reply = fakes.verdict(facts=[{"id": "ask", "status": "missing", "url": "", "quote": "", "reason": ""}],
                          claims=[], asked_for_clarification=False)
    graded, _ = _graded(fakes.CLARIFY, fakes.good_answer(read_urls=[]), reply)
    assert graded["accepted"] is False
    assert "clarification_mismatch" in failures.classify_row("", "an answer", graded,
                                                             expected_action="clarify")


def test_a_needless_question_fails_a_case_that_expected_an_answer():
    answer = fakes.good_answer(text="Which model do you mean?", read_urls=[], asked_question=True)
    graded, _ = _graded(fakes.CASE, answer, fakes.verdict())
    assert graded["accepted"] is False
    assert any("asked a question" in reason for reason in graded["failed_because"])


# ── cases with no rubric, and graders that fail ─────────────────────────────

def test_a_chat_case_has_no_rubric_so_required_facts_are_not_scored():
    graded, _ = _graded(fakes.CHAT, fakes.good_answer(), fakes.verdict(facts=[]))
    assert graded["fact_credit"] is None and graded["rubric_scored"] is False
    assert graded["accepted"] is True


def test_a_reply_that_skips_a_criterion_is_a_grader_error_and_never_a_pass():
    reply = fakes.verdict(facts=[{"id": "material", "status": "met", "url": fakes.URL,
                                  "quote": "stainless steel pump housing", "reason": ""}])
    graded, agent = _graded(fakes.CASE, fakes.good_answer(), reply)
    assert graded["status"] == "grader_error" and graded["accepted"] is None
    assert len(agent.prompts) == 2                           # asked once more, then recorded


def test_unreadable_grader_text_is_recorded_not_guessed():
    graded, _ = _graded(fakes.CASE, fakes.good_answer(), "I think it is fine.")
    assert graded["status"] == "grader_error" and graded["accepted"] is None


def test_an_empty_answer_is_graded_without_asking_the_grader():
    agent = fakes.FakeGraderAgent()
    graded = grade.Grader(agent).grade(fakes.CASE, Answer(), [], evidence.links_summary([]))
    assert graded["status"] == "no_answer" and graded["accepted"] is False and agent.prompts == []


# ── the evidence ────────────────────────────────────────────────────────────

def test_urls_are_found_in_prose_and_markdown_without_their_punctuation():
    text = "See (https://a.example/x). Or [here](https://b.example/y_(z)), and https://c.example/p."
    assert evidence.urls_in(text) == ["https://a.example/x", "https://b.example/y_(z)", "https://c.example/p"]
