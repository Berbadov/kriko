"""The reader's report: asked which oil a Megane takes, the Kriko Agent asked which
Megane, was told "Facelift (2020)", and answered from memory with web tools off.

The reply names nothing to search and the turn before it left no sources, so it
routed as ordinary chat. An answer to the agent's own question, and a short
correction after a request the web answers, carry that request's route."""

from app import chat

ASKED = "Which engine oil and how often should I change it on my Renault Megane 4?"
QUESTION = {"ask": "Is your 2020 Megane 4 a pre-facelift or facelift model?",
            "options": ["Pre-facelift", "Facelift"]}


def _after_a_question():
    return [{"role": "reader", "text": ASKED},
            {"role": "agent", "text": "", "questions": [QUESTION]}]


def test_an_answer_to_the_agents_question_is_research_again():
    assert chat.route_message("Facelift (2020)", _after_a_question()) == "web"


def test_the_search_is_the_request_with_what_the_reader_added():
    query = chat._web_query("Facelift (2020)", _after_a_question())
    assert "engine oil" in query and "Facelift (2020)" in query


def test_a_short_correction_after_an_answer_stays_research():
    history = [{"role": "reader", "text": ASKED},
               {"role": "agent", "text": "Assumed 2020 and a 1.5 dCi.",
                "sources": ["web_search", "https://forum.example/megane-oil"]}]
    assert chat.route_message("its just 1.5 blue dCi diesel 2020", history) == "web"
    # ...including the answer to the question that correction led to.
    history += [{"role": "reader", "text": "its just 1.5 blue dCi diesel 2020"},
                {"role": "agent", "text": "", "questions": [QUESTION]}]
    assert chat.route_message("Facelift (2020)", history) == "web"


def test_thanks_and_a_new_topic_after_an_answer_stay_chat():
    history = [{"role": "reader", "text": ASKED},
               {"role": "agent", "text": "Use 5W-30.", "sources": []}]
    # An answer from memory left nothing to correct with a search.
    assert chat.route_message("thanks", history) == "chat"
    assert chat.route_message("Explain what a turbo does in one line", history) == "chat"


def test_a_lone_reply_with_nothing_before_it_is_not_research():
    assert chat.route_message("Facelift (2020)", []) == "chat"


def test_the_chat_brief_tells_the_agent_not_to_answer_a_reply_from_memory():
    assert "answering a question you asked" in chat.chat_brief("Facelift (2020)", _after_a_question())
