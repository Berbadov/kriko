from app import chat
from app.research_policy import (
    COMPATIBILITY_GUIDANCE, SELLER_GUIDANCE, response_length_guidance,
)


def test_answer_length_scales_to_the_question_without_a_fixed_word_target():
    guidance = response_length_guidance("Should I replace the engine?")
    assert "complexity, stakes, and evidence" in guidance
    assert "no fixed word target" in guidance
    assert "100 words" not in guidance


def test_explicit_detail_and_brevity_requests_are_respected():
    assert "asked for detail" in response_length_guidance("Explain in detail")
    assert "asked for brevity" in response_length_guidance("Just the answer, briefly")


def test_compatibility_and_seller_questions_use_shared_grounding_rules():
    assert chat.route_message("Will this CPU fit the motherboard?") == "web"
    assert chat.route_message("Is this seller reliable?") == "web"
    assert chat.route_message("What does a motherboard do?") == "chat"
    compatibility = chat.web_answer_brief(
        "Will this CPU fit?", [], [], "no results")
    seller = chat.web_answer_brief("Is this seller reliable?", [], [], "no results")
    assert COMPATIBILITY_GUIDANCE in compatibility
    assert SELLER_GUIDANCE in seller
