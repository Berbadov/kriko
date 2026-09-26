> TL;DR (archived 2026-09-25): Design (2026-07-05, draft) for the "garbage of near-duplicate
cards" problem: three layers — backend Jaccard title dedup in `resolver.py` (threshold 0.4,
strength/severity preserving), frontend domain grouping in `hover_lite.js`, build-time
cross-file warnings in `sync.py`. No LLM on serve path, API unchanged, fail-open everywhere.

---
date: 2026-07-05
topic: "Issue Card Deduplication and Grouping"
status: draft
---

## Problem Statement

Users see many cards saying the same thing — near-duplicate "garbage" instead of a scannable list.

**Two duplication sources:**
1. **Same-topic claims across sibling parts** — EA211 YAML has 6 timing-belt claims (design flaw, wear/chirp, cam-gear defect ×2, interval, longevity) reading as "lots of timing belt cards."
2. **Unioned claims from ambiguous matches** — multi-variant matches union claims; `dict[int, Claim]` dedup catches same-ids only.

**Gap:** all dedup runs offline (`knowledge/dedup.py`); serving (`resolver.py`) has none; frontend renders every `RiskItem` flat.

## Constraints

- No LLM on serve path (Jaccard/token-overlap only); preserve `confirmed`/`due`/`due_stated`/`reported`
- Zero new deps (reuse `knowledge/dedup.py`); `AnalyzeResponse` unchanged; frontend backward-compatible; dedup <10ms (serve path ~30ms)

## Approach

**Three layers:**

| Layer | Where | What | Effort |
|-------|-------|------|--------|
| 1 — Title dedup | `resolver.py` | Merge by Jaccard similarity | Small |
| 2 — Domain grouping | `hover_lite.js` + `risk_card.js` | Expandable domain sections | Medium |
| 3 — Cross-file warnings | `sync.py` | Build-time near-dup alerts | Small |

Layer 1 removes near-exact dupes; Layer 2 organises the rest ("1 timing-belt section", not 6 cards); Layer 3 stops regrowth.

## Architecture

### Layer 1: Backend title-similarity dedup

`resolve_claims() → [new] _deduplicate_results() → main.py → _claim_to_risk()`. Extract tokenizer + Jaccard from `knowledge/dedup.py` into a shared utility; group `ClaimResult`s by domain, merge Jaccard ≥ 0.4 clusters keeping: highest-severity title (ties: most sources), max severity, strongest strength, deduped rationale/advice, merged sources, max confidence. Edge cases: empty → `[]`; single → as-is; all-maintenance merges as maintenance; mixed confirmed/reported keeps strongest, documents both in rationale.

### Layer 2: Frontend domain grouping

Group `state.result.risks` by `domain` at render; expandable sections (domain name + count). Display names/icons per domain (engine/transmission/emissions/electrical/fuel/other); sticky heads; high/medium/low mini-counts; risk cards inside unchanged (`risk_card.js` untouched).

### Layer 3: Cross-file duplicate warnings

In `sync.py` post-load: pairwise Jaccard on same-domain titles across parts; `warning` with file paths + claim keys at ≥ 0.4. Informational only.

## Data Flow

`content.js` ad_metadata → `POST /analyze` → `match_variant()` → `resolve_claims()` → **[NEW] dedup** → `_claim_to_risk()` → `AnalyzeResponse` → `background.js` cache → `hover_lite.js` groups by domain → domain sections → cards.

## Example Scenario

Before: 14 flat cards (6 timing-belt, 3 wastegate, 2 water-pump, 2 carbon, 1 PCV). After: Engine (8 merged) / Transmission (2) / Emissions (2) / Electrical (1) — e.g. one "Timing belt replacement [high] — 5 merged sources".

## Error Handling Strategy

- Backend dedup throws ⇒ log + return original (duplicates > nothing)
- Frontend grouping throws ⇒ flat render fallback; empty/null titles ⇒ Jaccard 0.0
- Threshold prevents whole-list collapse into one group

## Testing Strategy

### Backend tests

Identical/similar/different titles; cross-domain non-merge; strength preservation; empty/single; `resolve_claims` integration.

### Frontend tests

Manual: sections, collapse/expand, counts, no empty sections.

## Open Questions

1. `merged_count` on `RiskItem`? Skip — revisit if users want "5 sources merged".
2. Backend owns dedup (semantic), frontend owns grouping (visual) — separation keeps API clean.
3. Threshold 0.4 inherited; adjust from production (false+ → 0.5, false− → 0.35).
4. Summary counts post-dedup (match what the user sees).

## Implementation Plan

### Phase 1: Extract tokenizer to shared module

Move `_title_tokens()` + `title_similar()` from `knowledge/dedup.py` to `backend/core/title_sim.py`; both importers use the shared location; offline dedup verified (import change only).

### Phase 2: Backend dedup in resolver.py

`_deduplicate_results()` at the end of `resolve_claims()`, fail-open; summary counts post-dedup risks.

### Phase 3: Frontend domain grouping in hover_lite.js

Domain-grouped `renderBody()` + CSS + toggles; backward-compatible flat fallback.

### Phase 4: Cross-file warning in sync.py

Duplicate-detection loop post-YAML-load; warnings carry file paths + claim keys.

### Phase 5: Testing

Backend dedup tests + manual frontend QA (panel, sections, counts).
