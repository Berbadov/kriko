"""LLM-as-judge gate — grounding checks only.

Each gate is a tiny, cheap LLM call returning yes/no + reason.
The judge ONLY asks grounded questions (text vs text). It never
judges truth-about-the-world.

This module runs OFFLINE only — never on the /analyze request path.
"""

import json
import os
import re
import time
from dataclasses import dataclass

from knowledge.stoplists import (
    AMBIGUOUS_INSPECTION_TERMS,
    GENERIC_MAINTENANCE_TERMS,
    INSPECTION_COVERED,
    WARNING_LIGHT_PATTERNS,
    has_specificity_signal,
)

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
_MODEL = "ministral-8b-latest"


@dataclass
class GateResult:
    passed: bool
    reason: str


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())


def _ask(prompt: str, retries: int = 3) -> tuple[bool, str]:
    """Send a yes/no question, return (answer: bool, reason: str)."""
    from mistralai.client import Mistral
    client = Mistral(api_key=MISTRAL_API_KEY)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a strict grounding checker. Answer only based on the text provided. "
                "Return ONLY valid JSON: {\"answer\": true|false, \"reason\": \"one sentence\"}"
            ),
        },
        {"role": "user", "content": prompt},
    ]

    last_exc: Exception = RuntimeError("gate failed after retries")
    for attempt in range(retries):
        try:
            response = client.chat.complete(
                model=_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=256,
            )
            raw = response.choices[0].message.content
            data = _parse_json(raw)
            answer = bool(data.get("answer", False))
            reason = str(data.get("reason", ""))
            return answer, reason
        except Exception as exc:
            last_exc = exc
            if "429" in str(exc) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_exc


def gate_support(claim_title: str, claim_rationale: str, source_text: str) -> GateResult:
    """Does this source text actually support this claim?

    Checks the claim (title + rationale) against the source document text, not
    against the extractor's own quote — the quote-vs-quote check was circular and
    fragile on trafilatura-stripped forum/blog HTML (see pipeline_postmortem #6).
    """
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY not set")
    prompt = (
        "Does the following source text support the stated reliability claim?\n\n"
        f"Claim: {claim_title}\nRationale: {claim_rationale}\n\n"
        # Window must be ≥ the extraction window (extract.py uses doc.text[:6000]),
        # else evidence the extractor saw past char 4000 is invisible here and the
        # claim is silently dropped — that was pipeline_postmortem bug #2.
        f"Source text:\n{source_text[:6000]}\n\n"
        "Important: the source text may be in Turkish or another language. "
        "Accept as supporting evidence if the same concept or failure mode is "
        "discussed in the source, even when phrased differently or in a different "
        "language. Answer yes if the source provides concrete evidence for this "
        "specific claim type."
    )
    answer, reason = _ask(prompt)
    return GateResult(passed=answer, reason=reason)


def gate_variant(
    claim_title: str,
    evidence: str,
    candidate_variant_ids: list[str],
    candidate_descriptions: list[str],
) -> GateResult:
    """Which of the candidate variants does this evidence actually justify?

    `evidence` is the extracted engine/variant hint plus the source body — NOT
    the clipped verbatim quote. The quote is a narrow span that usually omits the
    engine code, so judging it alone wrongly held genuine Megane-4 claims (e.g.
    K9K injector, 1.3 TCe turbo) whose code lives in the hint / article body.
    This is the same quote-artifact failure fixed in gate_support/gate_refute.

    It still discriminates on the auto.py discovery path: a source about a
    different car won't mention an engine code in the variant list, so it fails.

    Returns passed=True if at least one candidate is justified.
    """
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY not set")
    variants_text = "\n".join(
        f"- {vid}: {desc}"
        for vid, desc in zip(candidate_variant_ids, candidate_descriptions)
    )
    prompt = (
        "Does the following evidence relate to this specific car model "
        "or any of its engine/transmission variants listed below?\n\n"
        # Window ≥ extraction window (extract.py uses doc.text[:6000]).
        f"Evidence:\n{evidence[:6000]}\n\nClaim: {claim_title}\n\nVariants:\n{variants_text}\n\n"
        "Answer YES if ANY of these apply:\n"
        "1. The evidence text or source URL mentions the car model/generation name "
        "(e.g. 'Megane 4', 'Megane IV', 'megane-4', 'megane4') or a Turkish/French "
        "equivalent (e.g. 'Megane Dört', 'Mégane IV').\n"
        "2. The evidence mentions an engine code or transmission code that appears in the variant list "
        "(e.g. K9K, H5H, H5F, R9M, DC4, DW5, DW6, '1.5 dCi', '1.6 dCi', '1.3 TCe', '1.2 TCe', '1.6 dCi'), even without "
        "specifying exact power output or year.\n"
        "3. The evidence discusses a failure specific to a transmission type, engine type, or component listed "
        "(e.g. EDC, dual clutch, manual, turbo, DPF, EGR, thermostat, cooling, electrical) that matches the variants.\n\n"
        "Answer NO only if the evidence is generic advice applicable to any car, "
        "or is clearly about a different car model/part entirely (e.g. if the variants use Getrag EDC and the text is about VW DSG or Opel Easytronic)."
    )
    answer, reason = _ask(prompt)
    return GateResult(passed=answer, reason=reason)


def gate_generic(claim_title: str, claim_rationale: str) -> GateResult:
    """Filter only claims that are trivially obvious to any car buyer.

    Returns passed=True if the claim is worth showing (i.e. NOT trivial).
    Fast-reject warning-light claims before the LLM call.
    """
    # Fast pre-check runs before the API key guard — no LLM cost for obvious rejects.
    text = (claim_title + " " + claim_rationale).lower()
    for pat in WARNING_LIGHT_PATTERNS:
        if pat.search(text):
            return GateResult(passed=False, reason="generic dashboard warning light (fast-reject)")

    # ministral-8b has been caught answering "keep" on its own textbook trivial
    # example while its own stated reason said the opposite (see
    # GENERIC_MAINTENANCE_TERMS docstring) — don't trust the LLM on the
    # clear-cut cases. Escape valve: a specificity signal (engine code,
    # displacement+fuel-tech label, mileage figure) means this phrasing is
    # config-specific despite the generic-sounding words, so still ask the LLM.
    generic_hit = next((kw for kw in GENERIC_MAINTENANCE_TERMS if kw in text), None)
    if generic_hit is not None and not has_specificity_signal(text):
        return GateResult(passed=False, reason=f"'{generic_hit}' with no engine/mileage specificity (fast-reject)")

    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY not set")

    prompt = (
        "You are evaluating whether a reliability claim is worth showing to a "
        "first-time buyer of this specific car. The buyer is NOT a mechanic.\n\n"
        f"Claim: {claim_title}\nRationale: {claim_rationale}\n\n"
        "Answer yes (reject) ONLY if the claim is completely trivial — something "
        "every car buyer already knows regardless of model, like 'brakes wear over "
        "time' or 'oil needs changing'. "
        "Answer no (keep) if the claim describes a specific failure mode, a known "
        "weakness of this engine family, a diesel/petrol-specific issue, or anything "
        "a buyer would genuinely want to know before purchasing this car."
    )
    answer, reason = _ask(prompt)
    # gate passes if the claim is NOT trivial
    return GateResult(passed=not answer, reason=reason)


def gate_inspection_value(claim_title: str, claim_rationale: str) -> GateResult:
    """Reject claims a standard pre-purchase inspection routinely covers, or generic
    warning lights. Uses a curated stoplist first (zero cost), then the LLM for
    edge cases.

    Returns GateResult(passed=True) for high-value claims (keeper);
    passed=False to tombstone.
    """
    text = (claim_title + " " + claim_rationale).lower()

    # Fast stoplist pass — runs before the API key guard, truly zero cost.
    # Same specificity escape valve as the AMBIGUOUS_INSPECTION_TERMS branch
    # below: a stoplist term shares a word ("clutch wear") with config-specific
    # keepers (a DQ200 dual-clutch pattern at a known mileage). An engine/
    # transmission code, displacement+fuel-tech label, or mileage figure marks
    # the claim config-specific — keep it; only fast-reject when no such signal.
    inspection_hit = next((kw for kw in INSPECTION_COVERED if kw in text), None)
    if inspection_hit is not None:
        if has_specificity_signal(text):
            return GateResult(passed=True, reason=f"'{inspection_hit}' inspection-covered term but config/mileage-specific — kept")
        return GateResult(passed=False, reason="matches inspection-covered stoplist")

    # Ambiguous terms ("oil consumption", ...) cover both a routine inspection
    # check and well-documented, mileage-specific chronic defects (see
    # stoplists.has_specificity_signal). Reject only when no engine/mileage
    # signal accompanies the term; otherwise treat that signal as evidence
    # this is config-specific and keep it without spending an LLM call — the
    # LLM alone doesn't reliably separate these (see stoplists.py docstring).
    ambiguous_hit = next((kw for kw in AMBIGUOUS_INSPECTION_TERMS if kw in text), None)
    if ambiguous_hit is not None:
        if has_specificity_signal(text):
            return GateResult(passed=True, reason=f"'{ambiguous_hit}' with engine/mileage specificity — kept")
        return GateResult(passed=False, reason=f"generic '{ambiguous_hit}' mention, no engine/mileage specificity")

    for pat in WARNING_LIGHT_PATTERNS:
        if pat.search(text):
            return GateResult(passed=False, reason="generic dashboard warning light")

    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY not set")

    # LLM for nuanced edge cases that the stoplist doesn't cover.
    prompt = (
        "You are evaluating whether a used-car reliability claim has value for a buyer "
        "BEFORE they book a standard pre-purchase mechanic inspection (ekspertiz). "
        "The inspection routinely covers: all fluid levels and leaks, brake pad and "
        "disc wear, injector bench test, compression test, and notes all dashboard "
        "warning lights.\n\n"
        f"Claim title: {claim_title}\n"
        f"Rationale: {claim_rationale}\n\n"
        "Answer YES (reject this claim) if ANY of these apply:\n"
        "1. The claim would be caught as a matter of routine by a standard pre-purchase "
        "inspection (fluid levels, brake wear, compression, injector bench test).\n"
        "2. It is a generic dashboard warning light (ABS, ESP, check engine) that applies "
        "to any car regardless of model or variant.\n"
        "3. It is a TRIVIAL software annoyance or UI bug with no safety/reliability impact: "
        "audio glitches, radio presets not saved, volume spikes, sensor false triggers "
        "under unusual conditions (light rain, low-light), or cosmetic/comfort issues.\n"
        "4. It describes a vehicle PERFORMANCE characteristic (power, acceleration, fuel "
        "economy, power-to-weight), a standard COMFORT/NVH property (road noise, vibration, "
        "ride quality), or an EQUIPMENT GAP (missing spare tire, no navigation) — not a "
        "mechanical failure or reliability risk.\n"
        "5. It describes damage that requires an accident or external impact to occur "
        "(collision damage, stone chips, impact-related suspension failure) — i.e. it is "
        "NOT predictable from the car's mileage, age, engine, or gearbox type alone.\n"
        "6. It is a duplicate or subset of a well-known inspection check (clutch slip on "
        "manual gearboxes, ball joint play, track rod wear, exhaust leaks) that a standard "
        "pre-purchase test drive or under-car inspection always catches.\n\n"
        "Answer NO (keep this claim) if it describes a specific mechanical/electrical "
        "failure mode, a known weak point of this engine or gearbox family, a maintenance "
        "interval predictable from mileage/age, or any high-consequence risk a buyer "
        "cannot learn from the standard inspection."
    )
    answer, reason = _ask(prompt)
    # passes (is high-value) if the LLM says it is NOT inspection-covered/trivial
    return GateResult(passed=not answer, reason=reason)


def gate_refute(claim_title: str, claim_rationale: str, source_text: str) -> GateResult:
    """Try to refute this claim from the source text.

    Returns passed=True if the source text does NOT refute the claim.
    """
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY not set")
    prompt = (
        "Does the following source text contradict or refute the stated claim?\n\n"
        f"Claim: {claim_title}\nRationale: {claim_rationale}\n\n"
        f"Source text:\n{source_text[:6000]}\n\n"   # ≥ extraction window (extract.py doc.text[:6000])
        "Answer yes if the source text REFUTES or contradicts the claim."
    )
    answer, reason = _ask(prompt)
    # gate passes if NOT refuted
    return GateResult(passed=not answer, reason=reason)
