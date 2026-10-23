"""A "Keep exploring" button puts its words in the reader's box, so it has to be
something the reader would say to the agent. The reader pressed one that asked
*them* whether they needed help comparing warranties."""

import json

from app import chatmeta


def _followups(*questions: str) -> list[str]:
    return chatmeta.parse(json.dumps({"followups": list(questions)}))["followups"]


def test_a_question_that_asks_the_reader_something_is_not_offered():
    assert _followups(
        "Did you find a new listing with 16GB on Hepsiburada?",
        "Should we search for refurbished options?",
        "Do you need help comparing warranty terms across sellers?",
        "Is your car a pre-facelift model?",
    ) == []


def test_requests_and_questions_about_the_product_are_kept():
    kept = ["Compare warranty terms across sellers", "What does the warranty exclude?",
            "Can you compare both on service cost?"]
    assert _followups(*kept) == kept


def test_the_brief_asks_for_the_readers_voice():
    seen = []
    chatmeta.generate(lambda prompt: seen.append(prompt) or "{}", "q", "a", first_turn=False)
    assert "READER's voice" in seen[0]
