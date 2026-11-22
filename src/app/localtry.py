"""One short question to the local model, so a reader can see it answers.

The Local AI section has a "Try it" box. Pressing Send is the only thing that
reaches here: nothing asks on its own, and the model is on this computer, so it
costs nothing. The call goes through the same socket the research plane uses
(`providers.local_inference.OpenAICompatSocket`), with a short reply budget and
a short timeout, so a model that is slow or missing says so in a minute instead
of holding the screen for the five minutes a research run may take.

Refusals are `TryRefused`, with the HTTP status the door should answer and the
words to show. Nothing here picks a model by name: the plan (`localplane.resolve`)
names what the server holds.
"""

import time

from app import localplane
from app.providers.local_inference import LocalInferenceError, OpenAICompatSocket

#: The longest question accepted, in characters. A try is a hello, not a document.
MAX_PROMPT_CHARS = 2000
#: The reply budget, in tokens, and how long to wait for it, in seconds.
MAX_OUTPUT_TOKENS = 200
TIMEOUT_SECONDS = 60.0


class TryRefused(Exception):
    """The try could not run, and why, in words for the reader."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _plan(app_state_path, asked: str) -> tuple[dict, str]:
    plan = localplane.resolve(app_state_path, with_search=False)
    if not plan["url"]:
        raise TryRefused(409, plan["reason"] or "No local model server is running. Start Ollama, then try again.")
    if not plan["models"]:
        raise TryRefused(
            409, f"{plan['name'] or 'The server'} is running but holds no chat model. "
            f"Download one first ({localplane.RECOMMENDED_MODEL} is recommended).")
    if asked:
        if asked not in plan["models"]:
            raise TryRefused(
                409, f"{asked} is not loaded on {plan['name'] or 'the server'}. "
                f"It has: {', '.join(plan['models'])}.")
        return plan, asked
    if not plan["model"]:
        raise TryRefused(409, plan["reason"] or "No model is chosen. Pick one under Models on this computer.")
    return plan, plan["model"]


def ask(app_state_path, prompt: str, model: str = "") -> dict:
    """Send one bounded chat completion and report the answer and its speed."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise TryRefused(422, "Type something to ask the model.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise TryRefused(
            422, f"That is {len(prompt)} characters. Keep it under {MAX_PROMPT_CHARS}: "
            "this is a quick test, not a document.")
    plan, serving = _plan(app_state_path, (model or "").strip())
    socket = OpenAICompatSocket(
        plan["url"], serving, timeout=TIMEOUT_SECONDS, temperature=0.2,
        max_tokens=MAX_OUTPUT_TOKENS, reasoning_effort="none",
        runtime_options=plan.get("runtime_options"))
    began = time.monotonic()
    try:
        text = socket.complete(prompt)
    except LocalInferenceError as error:
        if error.code == "timeout":
            raise TryRefused(
                504, f"The model did not answer within {TIMEOUT_SECONDS:g} seconds. "
                "The first answer also loads the model, so try once more, or pick a smaller model.") from error
        if error.code == "truncated":
            raise TryRefused(502, f"{serving} ran out of room before it wrote anything. Try a shorter question.") from error
        raise TryRefused(502, str(error)) from error
    seconds = time.monotonic() - began
    out = socket.tokens_out
    return {
        "ok": True,
        "text": text.strip(),
        "model": serving,
        "seconds": round(seconds, 2),
        # Whatever the server counted, or nothing: a guessed count would be a
        # speed the reader repeats.
        "output_tokens": out,
        "tokens_per_second": round(out / seconds, 1) if out and seconds > 0 else None,
        "truncated": socket.last_finish_reason == "length",
    }
