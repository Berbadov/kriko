"""Extraction layer — turns raw source text into structured CandidateClaims.

Uses Mistral chat completions with json_object response format.
The model's only job is to identify concrete reliability issues and copy
the verbatim supporting quote. Accuracy is the gate's job, not this layer's.

This module runs OFFLINE only — never on the /analyze request path.
"""

import json
import os
import re
import time
from typing import Literal

from pydantic import BaseModel, Field

from knowledge.sources.base import Document

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
_MODEL = "ministral-8b-latest"

SYSTEM_PROMPT = """You are a car reliability analyst. Given a text excerpt from a
repair blog, forum thread, or mechanic video transcript, extract ONLY chronic,
model-specific, or part-specific engineering flaws, design defects, and exceptional
failure cases.

Strict Rules:
- DO NOT extract generic warnings (e.g. "if the turbocharger fails, it will cause loss of power"). Every turbocharger or engine component can fail; we only care about model-specific design defects.
- DO NOT extract standard wear-and-tear items (e.g., brake pads, tyres, routine battery replacement, standard oil/fluid changes).
- DO NOT extract generic maintenance advice (e.g. "regular oil changes are important").
- Extract ONLY concrete, chronic failures, recall issues, or common engineering faults (e.g., "thermostat housing cracking on H5H 1.3 TCe petrol engines", "clutch shudder on dry-clutch DC4 transmissions").
- Copy the supporting quote VERBATIM — do not paraphrase.
- If the text mentions an engine code or variant (e.g. "1.5 dCi", "K9K", "H5H"), include it in engine_or_variant_hint.
- Do NOT invent claims. If no concrete chronic reliability issue is present, return {"claims": []}.
- severity is your provisional assessment; the review gate may adjust it.

Return ONLY valid JSON in this exact format:
{
  "claims": [
    {
      "title": "Short title of the chronic/design defect",
      "domain": "engine|transmission|electrical|emissions|fuel system|brakes|suspension|general",
      "severity": "high|medium|low",
      "rationale": "Plain-language explanation of the chronic issue",
      "inspection_advice": "What a buyer should check at viewing to identify this defect",
      "quote": "VERBATIM span from the source text supporting this specific defect",
      "engine_or_variant_hint": "Engine code or variant if mentioned, or null"
    }
  ]
}"""


class CandidateClaim(BaseModel):
    title: str = Field(description="Short title of the reliability issue")
    domain: str = Field(description="Category: engine|transmission|electrical|emissions|fuel system|brakes|suspension|general")
    severity: Literal["high", "medium", "low"] = Field(description="Provisional: high|medium|low")
    rationale: str = Field(description="Plain-language explanation of the issue")
    inspection_advice: str = Field(description="What a buyer should check at viewing")
    quote: str = Field(description="VERBATIM span from the source text that supports this claim")
    engine_or_variant_hint: str | None = Field(
        default=None,
        description="Engine code or variant if mentioned (e.g. 'K9K', '1.5 dCi', 'H5H')"
    )


def _parse_json(text: str) -> dict:
    """Strip markdown code fences if present, then parse JSON.

    Falls back to salvaging whole claim objects from a response that was
    truncated mid-JSON (LLM hit max_tokens) — better a partial harvest than
    losing every claim from a long source. See pipeline_postmortem.
    """
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        salvaged = _salvage_claims(text)
        if salvaged:
            return {"claims": salvaged}
        raise


def _salvage_claims(text: str) -> list[dict]:
    """Recover complete claim objects from a truncated JSON response.

    Scans for top-level `{...}` objects inside the response (the claim dicts)
    using brace balancing that respects strings/escapes, and json-loads each
    fully-closed one. A trailing object cut off by max_tokens is simply skipped.
    """
    objs: list[dict] = []
    starts: list[int] = []   # stack of '{' positions, so nested claim dicts are seen
    in_str = False
    escaped = False
    for i, ch in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            starts.append(i)
        elif ch == "}":
            if not starts:
                continue
            chunk = text[starts.pop() : i + 1]
            try:
                obj = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            # claim objects carry a title; skip the outer wrapper and inner blobs
            if isinstance(obj, dict) and "title" in obj:
                objs.append(obj)
    return objs


def extract_claims(doc: Document) -> list[CandidateClaim]:
    """Extract candidate claims from a Document. Returns [] on any error."""
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY not set — cannot run extraction")

    from mistralai.client import Mistral
    client = Mistral(api_key=MISTRAL_API_KEY)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Source text:\n\n{doc.text[:6000]}\n\nExtract all reliability issues as structured data."},
    ]

    last_exc: Exception = RuntimeError("extraction failed after retries")
    for attempt in range(3):
        try:
            response = client.chat.complete(
                model=_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=8192,
            )
            raw = response.choices[0].message.content
            data = _parse_json(raw)
            claims_data = data if isinstance(data, list) else data.get("claims", [])
            claims: list[CandidateClaim] = []
            for c in claims_data:
                try:
                    claims.append(CandidateClaim(**c))
                except Exception as exc:
                    # one malformed/partial claim shouldn't sink the rest
                    print(f"  skipped malformed claim: {exc}")
            return claims
        except Exception as exc:
            last_exc = exc
            if "429" in str(exc) and attempt < 2:
                time.sleep(2 ** attempt * 5)  # 5s, 10s
                continue
            raise
    raise last_exc
