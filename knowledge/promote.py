"""Promotion engine — corroboration count → verified claims.

Scoring: each independent source that passes gate_support and gate_refute
contributes 1 point. Domain trust is not used — the LLM gates are the
sole quality filter now that source discovery is open to the general web.

  score ≥ 2 → VERIFY (auto) — two independent sources corroborate
  score ≥ 1 → HUMAN review  — single source, needs a second
  score  = 0 → HELD (no supporting source passed gates)

Overrides (always win):
  severity == "high" or gate_refute disagreed → HUMAN review, PROVIDED at
      least one source passed gate_support (score ≥ 1) — otherwise HELD.
      A "high severity, zero corroborating sources" claim must not reach a
      servable status with nothing backing it (backend/data/parts validator
      rejects an empty `sources:` list on verified/review claims); it stays
      HELD until a source actually supports it.
  gate_variant returned no match → HELD
  gate_generic flagged → REJECT

HUMAN DECISION #2: auto-promote thresholds and audit sample rate are
risk-appetite decisions that must be reviewed before production.
"""

import logging
import random
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from knowledge.dedup import merge_candidates, title_similar
from knowledge.extract import CandidateClaim
from knowledge.judge import gate_generic, gate_inspection_value, gate_refute, gate_support, gate_variant
from knowledge.sources.base import Document
from knowledge.stoplists import code_tokens, mentions_sibling_code

log = logging.getLogger(__name__)

# HUMAN DECISION #2: adjust these thresholds based on measured error rate.
SCORE_VERIFY  = 2       # auto-verify: ≥2 independent sources corroborate
SCORE_REVIEW  = 1       # human review: 1 source — needs a second to confirm
AUDIT_RATE    = 0.20    # 20% of auto-verified claims go to review queue


# Fuel signals in a claim's own fields (engine code / hint / title / quote).
# A diesel-specific claim (e.g. K9K injector fouling) must not be grounded to a
# petrol variant, or a buyer sees a wrong-fuel issue — the opposite of "signal
# the general idea about THIS car". We narrow grounding ONLY on a clear signal;
# fuel-agnostic claims (A/C, electrical) stay broad by design.
_DIESEL_RE = re.compile(r"\b(k9k|r9m|d[ck]i|diesel|dizel|adblue)\b", re.I)
_PETROL_RE = re.compile(r"\b(h5f|h5h|h4m|tce|petrol|benzin|gasoline)\b", re.I)

def _shares_code_token(evidence_tokens: set[str], variant_descs: list[str]) -> bool:
    """True if the evidence and any candidate variant description share an
    engine/transmission code token (e.g. EA211, DQ200, K9K), verbatim and
    case-insensitive.

    gate_variant (a small LLM judge, ministral-8b) has been observed to
    hallucinate a mismatch even when the exact code is present in both the
    evidence and the variant description — e.g. rejecting "EA211 1.4 TSI"
    evidence against a "...EA211 petrol 1395cc..." variant on an invented
    "non-TSI" distinction. A literal code match is unambiguous ground truth
    and should short-circuit the unreliable LLM call rather than defer to it.
    """
    return any(evidence_tokens & code_tokens(desc) for desc in variant_descs)


# ── Deterministic model-name bypass ─────────────────────────────────────────
# gate_variant's own prompt says "answer YES if the evidence names the car
# model/generation" (criterion #1) — but the LLM (ministral-8b) has been
# observed to `held` claims that do exactly that, for no clear reason (body-
# domain claims naming the model directly — see project memory, same class of
# unreliability already fixed for engine/transmission codes via
# _shares_code_token above). A literal "Megane 4" / "Megane IV" / "megane4" /
# "Megane Dört" mention is unambiguous ground truth; check it before spending
# an LLM call on a question that's really just substring matching.
_ROMAN_TO_INT = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
_INT_TO_ROMAN = {v: k for k, v in _ROMAN_TO_INT.items()}
_INT_TO_TR_WORD = {1: "bir", 2: "iki", 3: "üç", 4: "dört", 5: "beş", 6: "altı", 7: "yedi", 8: "sekiz", 9: "dokuz", 10: "on"}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _generation_number(generation: str) -> int | None:
    g = generation.strip().upper()
    if g in _ROMAN_TO_INT:
        return _ROMAN_TO_INT[g]
    if g.isdigit():
        return int(g)
    return None


def _model_mention_variants(model: str, generation: str) -> set[str]:
    """Every plausible way this model+generation is written in prose."""
    model_n = _strip_accents(model).lower()
    gen_forms = {generation.lower()}
    n = _generation_number(generation)
    if n is not None:
        gen_forms.add(str(n))
        if n in _INT_TO_ROMAN:
            gen_forms.add(_INT_TO_ROMAN[n].lower())
        if n in _INT_TO_TR_WORD:
            gen_forms.add(_INT_TO_TR_WORD[n])
    variants: set[str] = set()
    for g in gen_forms:
        g = _strip_accents(g)   # match text side, which is also accent-stripped
        variants.add(f"{model_n} {g}")
        variants.add(f"{model_n}-{g}")
        variants.add(f"{model_n}{g}")
    return variants


def _shares_model_mention(evidence: str, variant_descs: list[str]) -> bool:
    """True if the evidence literally names one of the candidate model+generations.

    variant_descs come from `_build_variant_descriptors`/`_load_all_variants_for_part`,
    always formatted "{Make} {Model} {Generation} {EngineCode} ...".
    """
    text = _strip_accents(evidence).lower()
    seen: set[tuple[str, str]] = set()
    for desc in variant_descs:
        parts = desc.split()
        if len(parts) < 3:
            continue
        model, generation = parts[1], parts[2]
        key = (model.lower(), generation.lower())
        if key in seen:
            continue
        seen.add(key)
        if any(v in text for v in _model_mention_variants(model, generation)):
            return True
    return False


# ── Cross-brand contamination guard ─────────────────────────────────────────
# The deterministic bypasses above check evidence that includes the FULL
# source page/transcript text (see the `evidence` assembly in
# _evaluate_claim), not just the specific claim's own span — a deliberate
# earlier fix so a code mentioned elsewhere in the article still grounds a
# claim whose clipped quote omits it. Cost: a source that compares several
# manufacturers' parts (e.g. "DCT transmission problems across brands") lets
# an off-topic claim ride in on an unrelated code mention anywhere in that
# same long page. Caught live: a Ford-badge "7DCT 300 Clutch Squeak" claim
# reached `review` status (servable) in dc4.yaml (a Renault EDC part file),
# and Hyundai/Chevrolet/Buick-specific claims sat in h4d_75.yaml.
#
# This checks only the CLAIM's own text (title/rationale/hint/quote — never
# the full source text, which is exactly what caused the contamination) for
# an explicit other-brand mention. A hit vetoes the deterministic bypass and
# forces the LLM gate_variant call instead, which sees the specific claim in
# context and should reasonably reject an obviously different manufacturer's
# part — same shape as the code-token/model-mention bypasses, but as a
# negative signal rather than a positive one.
#
# Group-platform siblings: badge-engineered/platform-sharing brands whose
# mention alongside a shared-part claim is legitimate evidence, not
# contamination. Dacia is Renault's own sibling brand (K9K, H4D, DC4, ...
# engines/gearboxes are shared verbatim). Audi/Skoda/Seat/Cupra share the
# same VW Group MQB-era engines and DSG gearboxes as Volkswagen (EA211,
# EA288, EA888, DQ200, DQ250, DQ381 all appear across the group) — caught
# live: a "DQ250 Hydraulic Issues (Audi A3 8P Chassis)" claim is genuine
# shared-part evidence for a Golf 7 DQ250, not contamination.
GROUP_SIBLINGS: dict[str, frozenset[str]] = {
    "renault": frozenset({"dacia"}),
    "volkswagen": frozenset({"audi", "skoda", "seat", "cupra"}),
}

OTHER_BRANDS: frozenset[str] = frozenset({
    "ford", "chevrolet", "chevy", "buick", "cadillac", "gmc", "chrysler",
    "dodge", "jeep", "ram", "toyota", "honda", "nissan", "mazda", "subaru",
    "mitsubishi", "lexus", "acura", "infiniti", "hyundai", "kia", "genesis",
    "bmw", "mercedes", "audi", "skoda", "seat", "peugeot", "citroen",
    "citroën", "fiat", "alfa romeo", "opel", "vauxhall", "volvo", "saab",
    "mini", "land rover", "jaguar", "tesla", "suzuki", "isuzu", "daihatsu",
    "ssangyong", "lada",
})


def _claim_own_text(claim: CandidateClaim) -> str:
    return " ".join(
        p for p in (claim.title, claim.rationale, claim.engine_or_variant_hint, claim.quote) if p
    )


def _mentions_other_brand(claim_text: str, own_makes: set[str]) -> bool:
    """True if the claim's own text names a car brand other than one of
    `own_makes` (the make(s) of the candidate variants for this part) or
    one of their GROUP_SIBLINGS."""
    allowed = set(own_makes)
    for make in own_makes:
        allowed |= GROUP_SIBLINGS.get(make, frozenset())
    text = claim_text.lower()
    for brand in OTHER_BRANDS:
        if brand in allowed:
            continue
        if re.search(rf"\b{re.escape(brand)}\b", text):
            return True
    return False


def _claim_fuel(claim: CandidateClaim) -> str | None:
    """Detect a claim's fuel from its own text. None = no/ambiguous signal."""
    text = " ".join(
        p for p in (claim.engine_or_variant_hint, claim.title, claim.quote) if p
    )
    is_diesel = bool(_DIESEL_RE.search(text))
    is_petrol = bool(_PETROL_RE.search(text))
    if is_diesel and not is_petrol:
        return "diesel"
    if is_petrol and not is_diesel:
        return "petrol"
    return None


def _fuel_grounded_variants(
    variant_ids: list[str],
    claim: CandidateClaim,
    variant_fuels: dict[str, str] | None,
) -> list[str]:
    """Narrow grounding to the claim's fuel when (and only when) it's signalled.

    No signal, or no fuel map → ground broadly (shared components, generic).
    A clear signal → only same-fuel variants; if the car has none of that fuel,
    the claim doesn't apply here and grounds to nothing (→ HELD).
    """
    fuel = _claim_fuel(claim)
    if not fuel or not variant_fuels:
        return variant_ids
    return [v for v in variant_ids if variant_fuels.get(v) == fuel]


class Disposition(str, Enum):
    VERIFY = "verified"
    REVIEW = "review"    # human must review before serving
    HELD   = "held"
    REJECT = "rejected"


@dataclass
class PromotionResult:
    claim: CandidateClaim
    disposition: Disposition
    score: float
    confidence: float
    promoted_by: str          # "auto" | "pending_human" | "rejected"
    grounded_variant_ids: list[str]
    grounded_sources: list[Document]
    reason: str


def promote(
    candidates: list[tuple[CandidateClaim, Document]],
    candidate_variants: list[tuple[str, str]],  # [(variant_id, description), ...]
    claim_key_prefix: str = "",
    variant_fuels: dict[str, str] | None = None,  # {variant_id: "diesel"|"petrol"}
    own_part_id: str | None = None,
) -> list[PromotionResult]:
    """Run gates + scoring on a batch of (claim, source) pairs.

    `variant_fuels` lets a fuel-specific claim ground only to same-fuel variants
    (see _fuel_grounded_variants). Omitting it preserves the old broad grounding.

    `own_part_id` is the part file this batch is being promoted into (e.g.
    "dq381") — used only by the sibling-code contamination guard (see
    _evaluate_claim). Omit it (per-model claims pipeline, which has no single
    part identity) to skip that guard.

    Returns one PromotionResult per merged claim group.
    """
    results = []
    groups = merge_candidates(candidates)

    for claim, sources in groups:
        result = _evaluate_claim(
            claim, sources, candidate_variants, claim_key_prefix, variant_fuels, own_part_id
        )
        results.append(result)

    return results


def _evaluate_claim(
    claim: CandidateClaim,
    sources: list[Document],
    candidate_variants: list[tuple[str, str]],
    claim_key_prefix: str,
    variant_fuels: dict[str, str] | None = None,
    own_part_id: str | None = None,
) -> PromotionResult:
    variant_ids   = [v for v, _ in candidate_variants]
    variant_descs = [d for _, d in candidate_variants]

    # ── Gate: generic? ───────────────────────────────────────────────────────
    try:
        generic_gate = gate_generic(claim.title, claim.rationale)
        if not generic_gate.passed:
            return PromotionResult(
                claim=claim, disposition=Disposition.REJECT, score=0.0,
                confidence=0.0, promoted_by="rejected",
                grounded_variant_ids=[], grounded_sources=[], reason=generic_gate.reason,
            )
    except Exception as exc:
        log.warning("gate_generic failed: %s", exc)

    # ── Gate: inspection value? ───────────────────────────────────────────────
    # Reject claims a standard pre-purchase mechanic inspection already covers
    # (fluid levels, brake wear, injector bench test, warning lights).
    try:
        inspection_gate = gate_inspection_value(claim.title, claim.rationale or "")
        if not inspection_gate.passed:
            return PromotionResult(
                claim=claim, disposition=Disposition.REJECT, score=0.0,
                confidence=0.0, promoted_by="rejected",
                grounded_variant_ids=[], grounded_sources=[],
                reason=f"inspection_value: {inspection_gate.reason}",
            )
    except Exception as exc:
        log.warning("gate_inspection_value failed: %s", exc)

    # ── Gate: variant grounding — judge the hint + source body, not the quote ─
    # The clipped quote usually omits the engine code; the code lives in the
    # extracted hint and the source article. Feeding the narrow quote wrongly
    # held genuine Megane-4 claims (K9K, 1.3 TCe). Include the source URL:
    # it often contains the model/engine name (e.g. "megane-4-edc-arizasi")
    # which is invisible in the stripped article text.
    evidence = "\n".join(
        part for part in (
            f"Source URL: {sources[0].url}" if sources else "",
            claim.engine_or_variant_hint,
            claim.quote,
            sources[0].text if sources else "",
        ) if part
    )
    # Cross-brand contamination guard: if the CLAIM ITSELF (not the wider
    # source text) names a different manufacturer, don't let it ride in on
    # the deterministic bypasses below — force the LLM call instead, which
    # sees the specific claim in context. See OTHER_BRANDS docstring.
    own_makes = {desc.split()[0].lower() for desc in variant_descs if desc.split()}
    claim_own_text = _claim_own_text(claim)
    contaminated = (
        _mentions_other_brand(claim_own_text, own_makes)
        or mentions_sibling_code(claim_own_text, own_part_id or "")
    )

    evidence_tokens = code_tokens(evidence)
    gate_passed = (
        not contaminated
        and bool(evidence_tokens)
        and _shares_code_token(evidence_tokens, variant_descs)
    )
    if not gate_passed and not contaminated:
        gate_passed = _shares_model_mention(evidence, variant_descs)
    if not gate_passed:
        try:
            vg = gate_variant(claim.title, evidence, variant_ids, variant_descs)
            gate_passed = vg.passed
        except Exception as exc:
            log.warning("gate_variant failed: %s", exc)

    # Gate says "relevant to this model"; now restrict to the claim's fuel so a
    # diesel-only issue never grounds to a petrol variant.
    grounded_variants = (
        _fuel_grounded_variants(variant_ids, claim, variant_fuels) if gate_passed else []
    )

    if not grounded_variants:
        if gate_passed:
            reason = f"claim fuel ({_claim_fuel(claim)}) not offered on this model"
        else:
            reason = "gate_variant: no variant grounded"
        return PromotionResult(
            claim=claim, disposition=Disposition.HELD, score=0.0,
            confidence=0.0, promoted_by="pending_human",
            grounded_variant_ids=[], grounded_sources=[],
            reason=reason,
        )

    # ── Score independent sources that pass gate_support ─────────────────────
    score = 0.0
    grounded_sources: list[Document] = []
    override_review = False

    for source in sources:
        try:
            support = gate_support(claim.title, claim.rationale, source.text)
            if not support.passed:
                continue
            refute = gate_refute(claim.title, claim.rationale, source.text)
            if not refute.passed:
                override_review = True
                continue
            score += 1
            grounded_sources.append(source)
        except Exception as exc:
            log.warning("gate_support/refute failed: %s", exc)

    # ── Apply promotion rules ─────────────────────────────────────────────────
    if (claim.severity == "high" or override_review) and score == 0:
        # Nothing passed gate_support — forcing this to REVIEW would write a
        # servable claim with an empty sources list (validator-invalid, and
        # leaves a human reviewer nothing to actually review). Stays HELD
        # until a source corroborates it.
        disposition = Disposition.HELD
        promoted_by = "pending_human"
    elif claim.severity == "high" or override_review:
        disposition = Disposition.REVIEW
        promoted_by = "pending_human"
    elif score >= SCORE_VERIFY:
        disposition = Disposition.VERIFY
        promoted_by = "auto"
        # 20% of auto-verified → review queue for error-rate measurement
        if random.random() < AUDIT_RATE:
            disposition = Disposition.REVIEW
            promoted_by = "auto_audit"
    elif score >= SCORE_REVIEW:
        disposition = Disposition.REVIEW
        promoted_by = "pending_human"
    else:
        disposition = Disposition.HELD
        promoted_by = "pending_human"

    confidence = min(0.9, max(0.6, score / 2)) if score > 0 else 0.0

    return PromotionResult(
        claim=claim, disposition=disposition, score=score, confidence=confidence,
        promoted_by=promoted_by, grounded_variant_ids=grounded_variants,
        grounded_sources=grounded_sources,
        reason=f"score={score:.2f}, sources={len(grounded_sources)}",
    )


# Dispositions that are persisted to the claims YAML. `rejected` is never
# written — but a human may *manually* set status: rejected on a claim to
# tombstone it (see below).
_PERSISTED = {
    Disposition.VERIFY: "verified",
    Disposition.REVIEW: "review",
    Disposition.HELD:   "held",
}


def write_promoted_claims(
    results: list[PromotionResult],
    make: str,
    model: str,
    claims_dir: Path,
) -> None:
    """Append verified / review / held claims to the YAML claims file.

    YAML is the source of truth; this is the only write path from the knowledge
    pipeline to the serving plane. Only status=verified is served
    (backend/core/resolver.py); review/held persist for human visibility and
    one-line manual promotion (edit status: review → verified).

    Idempotency — a re-run (especially with --skip-extraction) must not clobber
    human edits:
      • Skip-if-key-exists: an existing claim_key is never rewritten. This keeps
        a human review→verified promotion, and keeps a human tombstone (set
        status: rejected to permanently bury junk — it won't be re-added).
      • Cross-run near-duplicate guard: claim_key is title[:20]-based, so the
        same issue re-phrased across runs gets a new key. We also skip a
        candidate whose domain + title matches any existing claim (title-word
        Jaccard ≥ 0.4), regardless of that claim's status.

    Cross-run corroboration: a held claim whose key matches a new result with
    a better status (held → review or verified) is updated in-place so that
    re-running `--skip-extraction` after gate fixes actually promotes claims
    rather than silently skipping them.
    """
    _STATUS_RANK = {"held": 0, "review": 1, "verified": 2}

    path = claims_dir / f"{make.lower()}_{model.lower()}.yaml"
    existing: list[dict] = []
    if path.exists():
        existing = yaml.safe_load(path.read_text()) or []
    existing_keys = {r["claim_key"] for r in existing}
    existing_by_key: dict[str, dict] = {r["claim_key"]: r for r in existing}
    # (domain, title) of every claim already on disk plus those added this run —
    # used for the cross-run / same-run near-duplicate guard.
    seen_titles: list[tuple[str, str]] = [
        (e.get("domain", ""), e.get("title", "")) for e in existing
    ]

    def _is_dup(domain: str, title: str) -> bool:
        return any(
            d == domain and title_similar(t, title) for d, t in seen_titles
        )

    def _make_sources(r: PromotionResult) -> list[dict]:
        return [
            {
                "source_url": s.url,
                "source_domain": s.site_or_channel,
                "site_or_channel": s.site_or_channel,
                "quote": r.claim.quote,
                "independent": True,
            }
            for s in r.grounded_sources
        ]

    def _make_variants(r: PromotionResult, status: str) -> list[dict]:
        return [
            {"variant_id": v, "grounding_note": f"auto-{status}"}
            for v in r.grounded_variant_ids
        ]

    updated = 0
    new_claims = []
    for r in results:
        status = _PERSISTED.get(r.disposition)
        if status is None:                       # rejected — never written
            continue
        key = f"{make.lower()}_{model.lower()}_{r.claim.domain}_{r.claim.title[:20].lower().replace(' ', '_')}"

        if key in existing_keys:
            # Cross-run corroboration: promote a held claim if new result is better,
            # and always accumulate new sources even if status stays the same.
            existing_claim = existing_by_key.get(key)
            if existing_claim:
                old_status = existing_claim.get("status", "held")
                if old_status == "rejected":
                    continue
                old_rank = _STATUS_RANK.get(old_status, -1)
                new_rank = _STATUS_RANK.get(status, -1)
                changed = False
                # Promote status if new rank is strictly higher.
                if new_rank > old_rank:
                    existing_claim["status"] = status
                    existing_claim["promoted_by"] = r.promoted_by
                    existing_claim["confidence"] = round(r.confidence, 2)
                    if r.grounded_variant_ids:
                        existing_claim["variants"] = _make_variants(r, status)
                    changed = True
                # Always add new sources (accumulate, not replace) if new sources exist
                # and the existing claim has fewer or no sources.
                if r.grounded_sources:
                    existing_urls = {s.get("source_url") for s in (existing_claim.get("sources") or [])}
                    new_src_dicts = _make_sources(r)
                    added = [s for s in new_src_dicts if s.get("source_url") not in existing_urls]
                    if added:
                        existing_claim.setdefault("sources", [])
                        existing_claim["sources"].extend(added)
                        changed = True
                if changed:
                    updated += 1
            continue

        if _is_dup(r.claim.domain, r.claim.title):
            continue
        new_claims.append({
            "id": f"{key}_v1",
            "claim_key": key,
            "version": 1,
            "is_current": True,
            "title": r.claim.title,
            "domain": r.claim.domain,
            "severity": r.claim.severity,
            "confidence": round(r.confidence, 2),
            "rationale": r.claim.rationale,
            "inspection_advice": r.claim.inspection_advice,
            "status": status,
            "promoted_by": r.promoted_by,
            "variants": _make_variants(r, status),
            "sources": _make_sources(r),
        })
        # Guard against two same-run candidates colliding on key or title.
        existing_keys.add(key)
        seen_titles.append((r.claim.domain, r.claim.title))

    if new_claims or updated:
        all_claims = existing + new_claims
        claims_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(all_claims, allow_unicode=True, sort_keys=False))
        log.info("Wrote %d new + %d updated claims to %s", len(new_claims), updated, path)


def write_promoted_part_claims(
    results: list[PromotionResult],
    part_id: str,
    part_type: str,
    parts_dir: Path,
) -> None:
    """Write promoted claims into the part YAML (backend/data/parts/{type}/{part_id}.yaml).

    Part claims do NOT include a `variants` block — variant assignment is handled
    by fitment YAML + sync.py. The part YAML is the research artifact; sync.py
    materialises the claim→variant links.

    Same idempotency rules as write_promoted_claims (skip-if-key-exists,
    cross-run near-dup guard, cross-run corroboration).
    """
    _STATUS_RANK = {"held": 0, "review": 1, "verified": 2}
    _PERSISTED = {
        Disposition.VERIFY: "verified",
        Disposition.REVIEW: "review",
        Disposition.HELD:   "held",
    }

    type_dir = parts_dir / part_type
    type_dir.mkdir(parents=True, exist_ok=True)
    path = type_dir / f"{part_id}.yaml"

    # Load existing part YAML (preserve part metadata, just update claims list).
    existing_data: dict = {}
    if path.exists():
        existing_data = yaml.safe_load(path.read_text()) or {}

    existing_claims: list[dict] = existing_data.get("claims", []) or []
    existing_keys = {c.get("claim_key", "") for c in existing_claims}
    existing_by_key = {c["claim_key"]: c for c in existing_claims if "claim_key" in c}
    seen_titles: list[tuple[str, str]] = [
        (c.get("domain", ""), c.get("title", "")) for c in existing_claims
    ]

    def _is_dup(domain: str, title: str) -> bool:
        return any(d == domain and title_similar(t, title) for d, t in seen_titles)

    def _make_sources(r: PromotionResult) -> list[dict]:
        return [
            {
                "source_url": s.url,
                "source_domain": s.site_or_channel,
                "site_or_channel": s.site_or_channel,
                "quote": r.claim.quote,
                "independent": True,
            }
            for s in r.grounded_sources
        ]

    updated = 0
    new_claims: list[dict] = []
    for r in results:
        status = _PERSISTED.get(r.disposition)
        if status is None:
            continue
        key = f"{part_id}_{r.claim.domain}_{r.claim.title[:20].lower().replace(' ', '_')}"

        if key in existing_keys:
            existing_claim = existing_by_key.get(key)
            if existing_claim:
                old_status = existing_claim.get("status", "held")
                if old_status == "rejected":
                    continue
                old_rank = _STATUS_RANK.get(old_status, -1)
                new_rank = _STATUS_RANK.get(status, -1)
                changed = False
                if new_rank > old_rank:
                    existing_claim["status"] = status
                    existing_claim["promoted_by"] = r.promoted_by
                    existing_claim["confidence"] = round(r.confidence, 2)
                    changed = True
                if r.grounded_sources:
                    existing_urls = {s.get("source_url") for s in (existing_claim.get("sources") or [])}
                    added = [s for s in _make_sources(r) if s.get("source_url") not in existing_urls]
                    if added:
                        existing_claim.setdefault("sources", [])
                        existing_claim["sources"].extend(added)
                        changed = True
                if changed:
                    updated += 1
            continue

        if _is_dup(r.claim.domain, r.claim.title):
            continue

        # Part claims: no `variants` block (fitment handles it).
        new_claims.append({
            "claim_key": key,
            "title": r.claim.title,
            "kind": "known_issue",
            "domain": r.claim.domain,
            "severity": r.claim.severity,
            "confidence": round(r.confidence, 2),
            "status": status,
            "promoted_by": r.promoted_by,
            "rationale": r.claim.rationale,
            "inspection_advice": r.claim.inspection_advice,
            "sources": _make_sources(r),
        })
        existing_keys.add(key)
        seen_titles.append((r.claim.domain, r.claim.title))

    if new_claims or updated:
        existing_data["claims"] = existing_claims + new_claims
        path.write_text(yaml.dump(existing_data, allow_unicode=True, sort_keys=False))
        log.info(
            "Wrote %d new + %d updated part claims to %s", len(new_claims), updated, path
        )
