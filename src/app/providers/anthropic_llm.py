"""A completion, over Anthropic's own wire format.

`llm.py` is one adapter for everything that speaks OpenAI's
`/v1/chat/completions` — OpenAI, DeepSeek, OpenRouter, a local server — which
is most things. Anthropic is not one of them: the request shape, the response
shape and the auth header all differ, and there is no compatibility endpoint to
point `LLM_BASE_URL` at. So it gets its own file rather than a branch inside
that one, and the two stay readable.

**Same contract, exactly.** `complete(prompt) -> text`, an empty string on any
failure, and a running token total on the function object. `ApiResearcher` must
not be able to tell which provider it was handed — a claim's provenance may
record *which model* wrote it, but nothing about the research protocol may
depend on whose API it went to.

The one real difference is worth stating: Anthropic reports input and output
tokens separately, and this keeps them apart. `llm.py` can only report a total,
because OpenAI's `usage` gives it one — and a total cannot be priced, since
input and output cost different amounts. A cost meter fed a total is a cost
meter guessing.
"""

import os

from app.keys import require
from app.providers._http import post_json

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"

#: The version header the Messages API requires. Not a beta flag and not
#: optional: a request without it is refused, which would read here as "the
#: provider is down" rather than "we forgot a header".
API_VERSION = "2023-06-01"

#: Enough for the JSON array of findings a document supports. Extraction is
#: bounded work — a page yields a handful of claims, not a chapter — and a
#: ceiling this size costs nothing when it is not reached.
MAX_TOKENS = 8192


def completer(api_key: str = "", base_url: str = "", model: str = ""):
    """`complete(prompt) -> the model's reply as a string`.

    Empty on any failure, because `extract` already reads a reply it cannot
    parse as "this document supports no claim": a provider outage should cost a
    document, not a run.
    """
    key = api_key or require("anthropic")
    endpoint = (base_url or _env("ANTHROPIC_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    endpoint += "/messages"
    name = model or _env("ANTHROPIC_MODEL", "")
    if not name:
        raise ValueError(
            "no Anthropic model chosen. Pick one on Settings, or set "
            "ANTHROPIC_MODEL — this adapter will not guess, because the guess "
            "would be what every run silently cost you."
        )

    def complete(prompt: str) -> str:
        body = post_json(
            endpoint,
            {
                "model": name,
                "max_tokens": MAX_TOKENS,
                # Extraction is transcription against a JSON contract, not a
                # creative task: the quote must come back byte-identical or the
                # grounding check refuses the finding. Same reasoning, and the
                # same value, as the OpenAI adapter.
                "temperature": 0.0,
                "messages": [{"role": "user", "content": prompt}],
            },
            {"x-api-key": key, "anthropic-version": API_VERSION},
        )
        # Counted before the early returns: a reply we could not parse still
        # cost tokens, and a total that only counted the usable answers would
        # make a run of unparseable replies look free.
        usage = body.get("usage")
        if isinstance(usage, dict):
            _add(complete, "tokens_in", usage.get("input_tokens"))
            _add(complete, "tokens_out", usage.get("output_tokens"))
            if isinstance(complete.tokens_in, int) or isinstance(
                    complete.tokens_out, int):
                complete.tokens_used = (complete.tokens_in or 0) + (
                    complete.tokens_out or 0)

        content = body.get("content")
        if not isinstance(content, list):
            return ""
        # Concatenate the text blocks and ignore the rest. A response may carry
        # blocks that are not text; reading `content[0]` would work until the
        # first time it did not.
        text = "".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        return _unfence(text)

    #: None, not 0 — "nobody counted" and "it was free" are different facts,
    #: and only one of them should ever reach a cost report.
    complete.tokens_used = None
    complete.tokens_in = None
    complete.tokens_out = None
    complete.model = name
    return complete


def _add(fn, field: str, value) -> None:
    if isinstance(value, int) and not isinstance(value, bool):
        setattr(fn, field, (getattr(fn, field) or 0) + value)


def _unfence(text: str) -> str:
    """Strip a ```json fence, which models add despite being told not to.

    Same habit, same cost, same fix as the OpenAI adapter: `extract` calls
    `json.loads` on this, so a fence is the difference between a document's
    findings and silence.
    """
    body = text.strip()
    if not body.startswith("```"):
        return body
    body = body.split("\n", 1)[-1] if "\n" in body else ""
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -len("```")]
    return body.strip()


def _env(name: str, fallback: str) -> str:
    return os.environ.get(name) or fallback
