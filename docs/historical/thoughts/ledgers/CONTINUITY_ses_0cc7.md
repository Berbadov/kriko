> TL;DR (archived 2026-09-25): Session ledger (2026-07-05) for the issue-card dedup/grouping
work: three-layer fix (backend Jaccard dedup, frontend domain grouping, build-time warnings)
designed and implemented across 6 phases (shared `title_sim`, resolver dedup, summary counts,
`hover_lite` grouping, `sync.py` warnings, 21 tests). All done; next = pytest, manual UI check,
production threshold feedback.

---
session: ses_0cc7
updated: 2026-07-05T18:26:16.566Z
---

# Session Summary

## Goal
Fix duplicate "issue cards" in the extension panel: merge similar claims (backend) + group by domain (frontend).

## Constraints & Preferences
- No LLM on serve path — algorithmic dedup (Jaccard titles, 0.4); <10ms (serve path ~30ms)
- Preserve strength (`confirmed`>`due`>`due_stated`>`reported`) and severity through merges
- Zero new deps (reuse `knowledge/dedup.py`); `AnalyzeResponse` unchanged; frontend backward-compatible; fail-open both layers

## Progress
### Done
- [x] **Explored codebase** — YAML → DB → `/analyze` → UI mapped. Duplication sources: same-topic claims across sibling parts (EA211: 6 timing-belt claims) + unioned claims from ambiguous variant matches.
- [x] **Designed three layers** (`thoughts/shared/designs/2026-07-05-issue-card-dedup-design.md`): backend title dedup / frontend domain grouping / build-time cross-file warnings.
- [x] **Planned** (`thoughts/shared/plans/2026-07-05-issue-card-dedup-plan.md`): 6 phases.
- [x] **Phase 1 — shared module** `backend/core/title_sim.py` (`title_tokens`, `title_similar` from `knowledge/dedup.py`); `dedup.py` re-imports it.
- [x] **Phase 2 — backend dedup** in `resolver.py`: `_SEVERITY_RANK`/`_STRENGTH_RANK`, `_best_in_cluster` (max severity/strength/confidence, merged rationale/advice, merged sources), `_deduplicate_results` (group by domain, cluster Jaccard ≥ 0.4, fail-open try/except); called on exact + ambiguous paths.
- [x] **Phase 3 — summary** already counts post-`resolve_claims` risks; no change.
- [x] **Phase 4 — frontend grouping** in `hover_lite.js` (`renderRisksList` groups by `domain`; collapsible headers with icon/count/severity dots; global indices preserved for `toggleOne`); ~80 lines CSS; `domainIconSvg` import.
- [x] **Phase 5 — cross-file warnings** `_warn_cross_file_duplicates()` in `sync.py` (pairwise Jaccard ≥ 0.4 across part files → `log.warning`), called in `sync_parts()`.
- [x] **Phase 6 — tests** `test_resolver_dedup.py`: 6 tokenizer + 6 merge + 7 dedup + 2 integration tests.

### In Progress
- (none — all phases implemented)

### Blocked
- (none)

## Key Decisions
- Backend dedup (root cause) before frontend grouping (presentation); API stays clean.
- Jaccard 0.4 = offline threshold (adjust from production feedback: false positives → 0.5, negatives → 0.35).
- Fail-open everywhere (duplicates > nothing); global index preservation keeps card toggles working.
- Merge representative = highest severity → strongest strength; rationale merged with 60%-overlap guard.

## Next Steps
1. `pytest` (esp. `test_resolver_dedup.py -x`) 2. Manual frontend check (10+ risks, collapse/expand, animation) 3. `python -m backend.sync` (warnings fire?) 4. Production feedback on threshold 5. Possible follow-up: `merged_count` on `RiskItem`.

## Critical Context
- EA211's 6 timing-belt claims = the exact reported scenario. `domainIconSvg()` already existed (import only). Rationale-overlap guard avoids near-dup paragraphs.

## File Operations
### Read
- `backend/api/main.py`, `backend/sync.py`, `backend/tests/{conftest,test_resolver}.py`, `extension_ui/hover_lite/{hover_lite.css,hover_lite.js,icons.js}`
### Modified
- NEW `backend/core/title_sim.py`, NEW `backend/tests/test_resolver_dedup.py` (21 tests)
- `backend/core/resolver.py`, `backend/sync.py`, `hover_lite.{js,css}`, `knowledge/dedup.py`, the two design/plan docs
