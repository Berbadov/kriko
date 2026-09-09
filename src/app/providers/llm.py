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


def completer(api_key: str = "", base_url: str = "", model: str = ""):
    """`complete(prompt) -> the model's reply as a string`.

    An empty string on any failure, because `extract` already treats a reply it
    cannot parse as "this document supports no claim" — a provider outage
    should cost a document, not a run.
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
            },
            {"authorization": f"Bearer {key}"},
        )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = (message or {}).get("content") if isinstance(message, dict) else ""
        return _unfence(str(content or ""))

    return complete


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
