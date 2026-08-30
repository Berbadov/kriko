"""langextract_client.py — grounded, few-shot claim extraction via langextract.

packs.cars.pipeline.extract's old approach asked ministral-8b for raw JSON and trusted
its self-reported `quote` field verbatim — nothing verified the quote was
actually present in the source text until gate_support's separate LLM call
caught it later (or didn't). langextract instead asks for a span-grounded
extraction: each claim's supporting quote is aligned to an exact character
interval in the source text, so a fabricated/paraphrased quote is visible
immediately (alignment_status != MATCH_EXACT, or no char_interval at all)
instead of riding through as plain text.

deepseek-v4-flash via DeepSeek's OpenAI-compatible chat endpoint, routed
through langextract's OpenAILanguageModel provider with an explicit
factory.ModelConfig. The explicit provider= kwarg makes create_model() call
router.resolve_provider() directly instead of router.resolve(model_id) — this
matters because "deepseek-v4-flash" matches langextract's built-in Ollama
routing pattern (r'^deepseek', see langextract.providers.patterns) and would
be misrouted to a local Ollama server if provider= were ever omitted here.

This module runs OFFLINE only — never on the /analyze request path.
"""

import os
import time
from functools import lru_cache
from pathlib import Path

import yaml
from langextract import factory
from langextract.core import data

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
_MODEL = "deepseek-v4-flash"
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

GOLD_PATH = Path(__file__).parent / "gold" / "gold.yaml"

PROMPT_DESCRIPTION = """You are a car reliability analyst. Given a text excerpt from a
repair blog, forum thread, or mechanic video transcript, extract ONLY chronic,
model-specific, or part-specific engineering flaws, design defects, and exceptional
failure cases, as "claim" extractions.

Strict Rules:
- DO NOT extract generic warnings (e.g. "if the turbocharger fails, it will cause loss of power"). Every turbocharger or engine component can fail; we only care about model-specific design defects.
- DO NOT extract standard wear-and-tear items (e.g., brake pads, tyres, routine battery replacement, standard oil/fluid changes).
- DO NOT extract generic maintenance advice (e.g. "regular oil changes are important").
- Extract ONLY concrete, chronic failures, recall issues, or common engineering faults (e.g., "thermostat housing cracking on H5H 1.3 TCe petrol engines", "clutch shudder on dry-clutch DC4 transmissions").
- The extraction text must be a VERBATIM span copied directly from the source, in its
  ORIGINAL language — do not paraphrase or translate it.
- The source text may be in Turkish, German, French, or any other language. Regardless of
  source language, the title/rationale/inspection_advice attributes MUST be written in
  natural English — buyers reading these are not assumed to read the source language.
- If the text mentions an engine code or variant (e.g. "1.5 dCi", "K9K", "H5H"), include it in the engine_or_variant_hint attribute.
- Do NOT invent claims. If no concrete chronic reliability issue is present, extract nothing.
- severity is your provisional assessment; the review gate may adjust it.

Title rules (buyers read this first — it must be a short, general, human phrase,
never a diagnostic-code litany or a repeated paragraph):
- title is a BRIEF phrase (aim for under 12 words) naming the GENERAL failure and
  the engine/transmission code it affects, e.g. "Chronic injector fouling (K9K 1.5 dCi)",
  "DQ200 dry-clutch adaptation loss after battery disconnect", "Thermostat housing
  cracking (H5H 1.3 TCe)".
- NEVER put a raw diagnostic trouble code (P0300, P17BF, DTC numbers, VAG fault
  numbers, ...) in the title — describe the failure in plain words instead
  ("random multi-cylinder misfire", not "P0300"). Codes belong in
  inspection_advice, where a buyer's mechanic can use them to verify.
- NEVER restate the rationale inside the title. The title is a label, the
  rationale is the explanation — they must not be the same text twice.
- Still keep the engine/variant code anchor — "injector problems" alone is
  useless (as generic as "brakes wear"); "injector fouling (K9K 1.5 dCi)" is
  the target: brief AND specific to this engine/transmission, not brief
  INSTEAD OF specific.

Each claim extraction's attributes must include: title, domain
(engine|transmission|electrical|emissions|fuel system|brakes|suspension|cooling|body|general
— pick exactly ONE, never combine), severity (high|medium|low), rationale,
inspection_advice, and engine_or_variant_hint (or omit it if not mentioned)."""


def _model_config() -> factory.ModelConfig:
    return factory.ModelConfig(
        model_id=_MODEL,
        provider="OpenAILanguageModel",
        provider_kwargs={
            "api_key": DEEPSEEK_API_KEY,
            "base_url": _DEEPSEEK_BASE_URL,
            # DeepSeek's OpenAI-compatible endpoint only supports json_object;
            # langextract's example-derived schema makes it send json_schema
            # instead and the API 400s ("This response_format type is
            # unavailable now"). Constructor kwargs land in the provider's
            # _extra_kwargs and override the schema's response_format at
            # infer time.
            "response_format": {"type": "json_object"},
        },
    )


@lru_cache(maxsize=1)
def few_shot_examples() -> tuple[data.ExampleData, ...]:
    """Few-shot examples built from packs/cars/pipeline/gold/gold.yaml's `verdict: correct`
    entries — reuses the existing hand-judged gold set instead of writing new
    examples from scratch.

    Only correct entries: langextract's prompt-alignment validator doesn't
    support a zero-extraction example (a real document can yield zero
    extractions fine; an example cannot — the aligner crashes on an empty
    extraction list). "This is generic, skip it" is taught through
    PROMPT_DESCRIPTION's instructions instead.
    Cached — rebuild by calling few_shot_examples.cache_clear() if gold.yaml
    changes within a process lifetime (tests do this).
    """
    entries = yaml.safe_load(GOLD_PATH.read_text()) or []
    examples = []
    for entry in entries:
        if entry.get("verdict") != "correct":
            continue
        quote = (entry.get("quote") or "").strip()
        if not quote:
            continue
        attributes = {
            "title": entry["title"],
            "domain": entry["domain"],
            "severity": entry["severity"],
            "rationale": entry["rationale"],
        }
        if entry.get("inspection_advice"):
            attributes["inspection_advice"] = entry["inspection_advice"]
        if entry.get("engine_or_variant_hint"):
            attributes["engine_or_variant_hint"] = entry["engine_or_variant_hint"]
        examples.append(
            data.ExampleData(
                text=quote,
                extractions=[
                    data.Extraction(
                        extraction_class="claim",
                        extraction_text=quote,
                        attributes=attributes,
                    )
                ],
            )
        )
    return tuple(examples)


def extract_grounded(text: str) -> list[dict]:
    """Run grounded extraction over `text`. Returns raw dicts with
    CandidateClaim's fields plus `quote_grounded` (bool) — whether langextract
    could align the extracted quote to an exact span in `text`, versus a
    fuzzy/absent match, which is new information the old raw-JSON approach
    never had (it trusted the model's self-reported quote unconditionally).

    packs.cars.pipeline.extract.extract_claims() converts these into CandidateClaim
    instances — this function returns plain dicts so it has no dependency on
    that module's Pydantic model (avoids a circular import).
    """
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set — cannot run extraction")

    import langextract as lx
    from langextract.core.data import AlignmentStatus

    # langextract has no built-in retry; keep the same 3-attempt/backoff-on-429
    # shape the old raw-Mistral-SDK extractor had.
    last_exc: Exception = RuntimeError("extraction failed after retries")
    result = None
    for attempt in range(3):
        try:
            result = lx.extract(
                text_or_documents=text,
                prompt_description=PROMPT_DESCRIPTION,
                examples=list(few_shot_examples()),
                config=_model_config(),
                fence_output=False,
            )
            break
        except Exception as exc:
            last_exc = exc
            if "429" in str(exc) and attempt < 2:
                time.sleep(2 ** attempt * 5)  # 5s, 10s
                continue
            raise
    if result is None:
        raise last_exc
    docs = result if isinstance(result, list) else [result]

    claims: list[dict] = []
    for doc in docs:
        for e in doc.extractions:
            if e.extraction_class != "claim":
                continue
            attrs = e.attributes or {}
            claims.append({
                "title": attrs.get("title", ""),
                "domain": attrs.get("domain", "general"),
                "severity": attrs.get("severity", "medium"),
                "rationale": attrs.get("rationale", ""),
                "inspection_advice": attrs.get("inspection_advice", ""),
                "quote": e.extraction_text,
                "engine_or_variant_hint": attrs.get("engine_or_variant_hint") or None,
                "quote_grounded": e.alignment_status == AlignmentStatus.MATCH_EXACT,
            })
    return claims
