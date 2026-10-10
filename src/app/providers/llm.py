"""A completion, over OpenAI's wire format.

One adapter, several providers. OpenAI's `/v1/chat/completions` is the format
everyone implements, so a configurable base URL turns this single file into an
OpenAI, DeepSeek, OpenRouter or local-llama adapter with no second code path —
which is exactly what `packs/cars/pipeline/ledger/verdict.py` already does to
reach DeepSeek through the OpenAI client.

The prompt this receives is built by `ApiResearcher.extract`, including its
grounding instruction. Nothing about the research protocol is decided here: the
adapter's whole job is prompt in, text out.
"""

import os

from app.keys import require
from app.providers._http import post_json

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def model_name(model: str = "") -> str:
    """Which model this installation will use — for the provenance row.

    Exported because "researched by an LLM" is not a provenance record and
    `gpt-4o-mini` is one, and the caller that writes the row must be able to
    ask before the run rather than guess after it.
    """
    return model or _env("LLM_MODEL", DEFAULT_MODEL)


def completer(api_key: str = "", base_url: str = "", model: str = "",
              max_tokens: int | None = None):
    """`complete(prompt) -> the model's reply as a string`.

    An empty string on any failure, because `extract` already treats a reply it
    cannot parse as "this document supports no claim" — a provider outage
    should cost a document, not a run.

    It also carries the running token total as an attribute on itself
    (`complete.tokens_used`), which `ApiResearcher.tokens_used` reads and the
    provenance row records. This is the only place in the stack that sees a
    response envelope, so it is the only place that *can* count; the attribute
    opens at None rather than 0 so a provider that reports no `usage` block
    ends up recorded as "cannot count" instead of as a free run.
    """
    key = api_key or require("openai")
    endpoint = (base_url or _env("LLM_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    endpoint += "/chat/completions"
    name = model_name(model)

    def complete(prompt: str) -> str:
        body = post_json(
            endpoint,
            {
                "model": name,
                "messages": [{"role": "user", "content": prompt}],
                # Extraction is a transcription task with a JSON contract, not
                # a creative one: the quote must come back byte-identical or
                # the grounding check refuses the finding.
                "temperature": 0.0,
                **({"max_tokens": max_tokens} if max_tokens is not None else {}),
            },
            {"authorization": f"Bearer {key}"},
        )
        # Before the early returns below: a reply we could not parse still
        # cost tokens, and a total that only counts the usable answers would
        # make a run of unparseable replies look free.
        usage = body.get("usage")
        if not isinstance(usage, dict) or not (
                isinstance(usage.get("total_tokens"), int) and not isinstance(usage.get("total_tokens"), bool)
                or all(isinstance(usage.get(k), int) and not isinstance(usage.get(k), bool)
                       for k in ("prompt_tokens", "completion_tokens"))):
            complete.usage_complete = False
        if isinstance(usage, dict):
            # Both halves, not just the total. They were there all along —
            # `prompt_tokens` and `completion_tokens` are in every
            # OpenAI-shaped response — and only the total was kept, which is
            # the one number that *cannot* be priced: input and output cost
            # different amounts, so a meter handed a total is a meter
            # guessing. See `app/modelcatalogue.py`.
            _add(complete, "tokens_in", usage.get("prompt_tokens"))
            _add(complete, "tokens_out", usage.get("completion_tokens"))
            total = usage.get("total_tokens")
            if isinstance(total, int) and not isinstance(total, bool):
                complete.tokens_used = (complete.tokens_used or 0) + total
            elif complete.tokens_in is not None or complete.tokens_out is not None:
                # A provider that reports the halves and no total still gets
                # counted, rather than reading as a free run.
                complete.tokens_used = (complete.tokens_in or 0) + (
                    complete.tokens_out or 0)

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        complete.last_finish_reason = str(choices[0].get("finish_reason") or "") if isinstance(choices[0], dict) else ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = (message or {}).get("content") if isinstance(message, dict) else ""
        return _unfence(str(content or ""))

    #: None, not 0 — see the docstring. Set after the definition because the
    #: closure increments it by name.
    complete.tokens_used = None
    complete.usage_complete = True
    complete.last_finish_reason = ""
    #: The two halves, kept apart so a cost can be computed from them at all.
    complete.tokens_in = None
    complete.tokens_out = None
    complete.model = name
    return complete


def _add(fn, field: str, value) -> None:
    if isinstance(value, int) and not isinstance(value, bool):
        setattr(fn, field, (getattr(fn, field) or 0) + value)


def _unfence(text: str) -> str:
    """Strip a ```json fence, which every model adds despite being told not to.

    `extract` calls `json.loads` on this and returns no findings when it fails.
    A fence is therefore the difference between a document's findings and
    silence, and it is not worth losing them to a formatting habit.
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
