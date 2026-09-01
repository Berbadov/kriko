---
session: ses_0cc7
updated: 2026-07-05T18:26:16.566Z
---

# Session Summary

## Goal
Fix the duplicate "issue cards" problem in Kriko's Chrome extension panel so similar claims are merged (backend) and remaining cards are grouped by domain (frontend), eliminating the "garbage" of repeated same-thing cards.

## Constraints & Preferences
- No LLM on the serve path — dedup must be algorithmic (Jaccard title similarity, threshold 0.4)
- Must preserve strength ("confirmed" > "due" > "due_stated" > "reported") and severity through merges
- Zero new dependencies — reuse existing dedup approach from `knowledge/dedup.py`
- API contract (`AnalyzeResponse`) stays unchanged
- Frontend changes backward-compatible with old API responses
- Dedup must complete in <10ms (current serve path ~30ms)
- Fail-open for both backend and frontend — errors fall back to original flat list

## Progress
### Done
- [x] **Explored full codebase** — mapped data flow from YAML → DB → `/analyze` → extension UI. Identified two duplication sources: same-topic claims across sibling parts, and unioned claims from ambiguous variant matching.
- [x] **Designed three-layer approach** (design doc at `thoughts/shared/designs/2026-07-05-issue-card-dedup-design.md`): Layer 1 = backend title-similarity dedup, Layer 2 = frontend domain grouping, Layer 3 = build-time cross-file duplicate warnings.
- [x] **Created implementation plan** (at `thoughts/shared/plans/2026-07-05-issue-card-dedup-plan.md`): 6 phases with task breakdown and dependencies.
- [x] **Phase 1 — Shared title-sim module**: Created `backend/core/title_sim.py` with `title_tokens()` and `title_similar()` extracted from `knowledge/dedup.py`. Updated `knowledge/dedup.py` to import from the shared module (removed local `_title_tokens`, `title_similar`, `_STOPWORDS`, `re` import). Offline pipeline now uses same functions as the serving plane.
- [x] **Phase 2 — Backend dedup**: Added to `backend/core/resolver.py`:
  - `_SEVERITY_RANK` / `_STRENGTH_RANK` dictionaries for ordering
  - `_best_in_cluster(cluster)` — merges a cluster of similar ClaimResults, preserving highest severity, strongest strength, merging rationale/inspection_advice with dedup, taking max confidence
  - `_deduplicate_results(results)` — groups by domain, clusters by title similarity (Jaccard ≥ 0.4), merges each cluster via `_best_in_cluster()`. Fail-open: wraps in try/except, returns original list if exception.
  - `resolve_claims()` now calls `_deduplicate_results()` at the end of both exact and ambiguous match paths
- [x] **Phase 3 — Summary counts verified**: `_build_summary()` in `main.py` already counts from post-`resolve_claims()` risks, so no change needed.
- [x] **Phase 4 — Frontend domain grouping**: Modified `extension_ui/hover_lite/hover_lite.js`:
  - `renderRisksList()` groups `state.result.risks` by `domain` field
  - Each domain rendered as a collapsible `<div class="lite-domain-group">` with header button, icon from `domainIconSvg()`, count badge, severity dots, toggle (+/−)
  - Individual risk cards rendered inside `.lite-domain-body` with preserved global indices for `toggleOne(idx, card)` and stagger animation delays
  - Added `domainIconSvg` import from `__KrikoPanelIcons`
  - Added ~80 lines of CSS in `extension_ui/hover_lite/hover_lite.css` for domain groups (.lite-domain-group, .lite-domain-head, .lite-domain-body, .lite-domain-sev-dot, etc.)
- [x] **Phase 5 — Cross-file warnings**: Added `_warn_cross_file_duplicates()` to `backend/sync.py` — collects all claim titles by domain across part YAMLs, computes pairwise Jaccard across different part files, logs `log.warning()` for any pair ≥ 0.4 threshold. Called right after loading all parts in `sync_parts()`.
- [x] **Phase 6 — Tests**: Created `backend/tests/test_resolver_dedup.py` with:
  - 6 tests for `title_tokens` / `title_similar` (empty input, stopwords, punctuation, identical, different, threshold)
  - 6 tests for `_best_in_cluster` (single, strength preserved, severity preserved, title-from-best, confidence merged, rationale merged with dedup)
  - 7 tests for `_deduplicate_results` (empty, single, no-merge, similar-merge, cross-domain separate, three-similar-one-different, multiple-domains, different-titles)
  - 2 integration tests (dedup doesn't break existing tests, strength survives through to output)

### In Progress
- (none — all phases implemented)

### Blocked
- (none)

## Key Decisions
- **Backend dedup before frontend grouping**: Fix the root cause first (duplicate claims), then organize what's left visually. Separating concerns keeps API clean.
- **Jaccard threshold 0.4**: Matches existing offline pipeline threshold. Provides consistent behavior between build-time and serve-time dedup.
- **Fail-open on backend dedup**: If `_deduplicate_results` throws, log warning + return original list. Better to show duplicates than nothing.
- **Global index preservation in frontend**: Domain grouping preserves `state.result.risks` indices for `toggleOne`/`setAllOpen` — these functions work unchanged.
- **`_best_in_cluster` merge strategy**: Highest severity → strongest strength → first in sorted order is the "representative". Rationale/advice are smart-merged with dedup (overlap guard for rationale, exact dedup for advice).

## Next Steps
1. **Run `pytest`** to verify all backend tests pass (especially the new dedup tests + existing resolver tests)
2. **Run `pytest` with `-x` on `test_resolver_dedup.py`** to catch any dedup-specific failures
3. **Manual frontend verification**: Load extension on a listing with 10+ risks, verify domain sections render correctly, collapse/expand works, toggle animation still runs
4. **Run `python -m backend.sync`** to test cross-file duplicate warnings actually fire for existing YAML data
5. **Collect production feedback**: After deploy, monitor for false positives (different claims merged) or false negatives (duplicates not caught) — adjust threshold if needed
6. **Consider adding `merged_count` to `RiskItem`** as a follow-up if users want to see "5 sources merged" in card footer

## Critical Context
- The worst duplication source discovered: EA211 YAML has 6 separate timing-belt-related claims that would all merge under the new dedup — exact scenario the user is complaining about
- Existing `knowledge/dedup.py` used local `_title_tokens` with identical logic — extracted to shared `backend/core/title_sim.py`, both now import from same source
- `resolve_claims()` now dedup-s every path: exact single-variant, ambiguous multi-variant, and the no-variant edge case
- `_best_in_cluster` uses a token-overlap guard for rationale dedup (>60% overlap → skip) to avoid near-duplicate paragraphs in merged rationale
- `domainIconSvg()` function already existed in `icons.js` — just needed to be imported into `hover_lite.js`'s IIFE scope

## File Operations
### Read
- `/home/beraat/kriko/backend/api/main.py`
- `/home/beraat/kriko/backend/sync.py`
- `/home/beraat/kriko/backend/tests/conftest.py`
- `/home/beraat/kriko/backend/tests/test_resolver.py`
- `/home/beraat/kriko/extension_ui/hover_lite/hover_lite.css`
- `/home/beraat/kriko/extension_ui/hover_lite/hover_lite.js`
- `/home/beraat/kriko/extension_ui/hover_lite/icons.js`

### Modified
- `/home/beraat/kriko/backend/core/title_sim.py` (NEW — shared tokenizer + Jaccard)
- `/home/beraat/kriko/backend/core/resolver.py` (added `_deduplicate_results`, `_best_in_cluster`, dedup call in `resolve_claims`)
- `/home/beraat/kriko/backend/sync.py` (added `_warn_cross_file_duplicates`, call in `sync_parts`)
- `/home/beraat/kriko/backend/tests/test_resolver_dedup.py` (NEW — 21 tests)
- `/home/beraat/kriko/extension_ui/hover_lite/hover_lite.css` (added ~80 lines of domain group CSS)
- `/home/beraat/kriko/extension_ui/hover_lite/hover_lite.js` (domain grouping in `renderRisksList`, domainIconSvg import)
- `/home/beraat/kriko/knowledge/dedup.py` (switched imports to shared `backend.core.title_sim`, removed local tokenizer code)
- `/home/beraat/kriko/thoughts/shared/designs/2026-07-05-issue-card-dedup-design.md`
- `/home/beraat/kriko/thoughts/shared/plans/2026-07-05-issue-card-dedup-plan.md`
