"""Promotion engine — corroboration count → verified claims.

Scoring: each independent source that passes gate_support and gate_refute
contributes 1 point. Domain trust is not used — the LLM gates are the
sole quality filter now that source discovery is open to the general web.

  score ≥ 2 → VERIFY (auto) — two independent sources corroborate
  score ≥ 1 → HUMAN review  — single source, needs a second
  score  = 0 → HELD (no supporting source passed gates)

Overrides (always win):
  severity == "high"  → HUMAN review regardless of score
  gate_variant returned no match → HELD
  gate_refute disagreed → HUMAN review
  gate_generic flagged → REJECT

HUMAN DECISION #2: auto-promote thresholds and audit sample rate are
risk-appetite decisions that must be reviewed before production.
"""

import logging
import random
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from knowledge.dedup import merge_candidates, title_similar
from knowledge.extract import CandidateClaim
from knowledge.judge import gate_generic, gate_inspection_value, gate_refute, gate_support, gate_variant
from knowledge.sources.base import Document

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
) -> list[PromotionResult]:
    """Run gates + scoring on a batch of (claim, source) pairs.

    `variant_fuels` lets a fuel-specific claim ground only to same-fuel variants
    (see _fuel_grounded_variants). Omitting it preserves the old broad grounding.

    Returns one PromotionResult per merged claim group.
    """
    results = []
    groups = merge_candidates(candidates)

    for claim, sources in groups:
        result = _evaluate_claim(
            claim, sources, candidate_variants, claim_key_prefix, variant_fuels
        )
        results.append(result)

    return results


def _evaluate_claim(
    claim: CandidateClaim,
    sources: list[Document],
    candidate_variants: list[tuple[str, str]],
    claim_key_prefix: str,
    variant_fuels: dict[str, str] | None = None,
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
    gate_passed = False
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
    if claim.severity == "high" or override_review:
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
