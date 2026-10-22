"""A second answer call in one turn must not blank the draft on screen.

The reader watched the reply appear, then the turn called the agent again — to
repair an offer, to revise a citation, to answer the evidence review — and that
call streamed its own draft from the beginning. The reader's text collapsed to
the first few words of a near-identical draft and animated in again word by
word: the same answer, twice. What is on screen now stays until the new draft
has said at least as much.
"""

import time

from app import chat, chatdata
from app.tests.test_chat_turn import Hooks, Script

OFFER = "I can help with that. Would you like me to get started?"
ANSWER = ("Induction charging moves power through a changing magnetic field, so a "
          "receiver coil picks up current without a plug.")


def _streaming(*calls: str):
    """An agent that streams each reply in fragments, as a real one does."""
    asked: list[str] = []

    def ask_stream(prompt: str, on_text) -> str:
        asked.append(prompt)
        text = calls[min(len(asked), len(calls)) - 1]
        for cut in (text[:30], text):
            on_text(cut)
            # Past the 0.25 s coalescing window, so both fragments are published.
            time.sleep(0.3)
        return text

    ask_stream.asked = asked  # type: ignore[attr-defined]
    return ask_stream


def test_a_repair_does_not_replace_the_offer_with_its_first_words():
    hooks = Hooks()
    ask_stream = _streaming(OFFER, ANSWER)
    out = chat.run_turn("Explain induction charging", ask=Script(),
                        ctx=chatdata.Context(), ask_stream=ask_stream, hooks=hooks)

    assert len(ask_stream.asked) == 2, "the offer was repaired"  # type: ignore[attr-defined]
    shown = [one["answer"] for one in hooks.partials]
    assert OFFER in shown, f"the reader saw the offer: {shown}"
    after = shown[shown.index(OFFER) + 1:]
    assert after, "the repair streamed its own answer"
    assert all(len(one) >= len(OFFER) for one in after), (
        f"a restart replaced the reader's text with a shorter draft: {after}")
    assert out["answer"] == ANSWER


def test_the_corrected_answer_is_what_the_turn_keeps():
    """Holding the screen must not cost the repair: the new text is the answer."""
    hooks = Hooks()
    ask_stream = _streaming(OFFER, ANSWER)
    out = chat.run_turn("Explain induction charging", ask=Script(),
                        ctx=chatdata.Context(), ask_stream=ask_stream, hooks=hooks)
    assert hooks.partials[-1]["answer"] == ANSWER
    assert out["agent_calls"] == 2
