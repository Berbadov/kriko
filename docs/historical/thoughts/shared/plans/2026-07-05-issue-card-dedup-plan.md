> TL;DR (archived 2026-09-25): Implementation plan (2026-07-05) for issue-card dedup+grouping:
6 phases — shared `title_sim` module, resolver `_deduplicate_results`/`_merge_cluster`,
post-dedup summary (no change needed), `hover_lite` domain grouping + CSS, `sync.py`
cross-file warnings, backend tests + manual frontend QA. Dependencies: 1→2→3, 4∥3, 5 after 1, 6 last.

# Implementation Plan: Issue Card Dedup and Grouping

## Phase 1 — Shared title-similarity module (1 file, no deps)

**Task 1.1:** Create `backend/core/title_sim.py` — verbatim `_title_tokens()` + `title_similar()` from `knowledge/dedup.py` (+ `re`, logging; no sqlalchemy/dataclasses).
**Task 1.2:** `knowledge/dedup.py` imports from it; `same_claim()` unchanged.
**Test 1.3:** `tests/test_title_sim.py` — tokens (empty/single/stopwords); similarity (identical 1.0, disjoint 0.0, "Timing belt failure" vs "…replacement" ≥ 0.4); both-empty → False.

## Phase 2 — Backend dedup (1 file: resolver.py)

**Task 2.1:** Import `title_similar`.
**Task 2.2:** `_deduplicate_results(results)` — ≤1 item passthrough; group by domain; within-domain single-pass clustering on `title_similar(cluster[0], candidate)`; singletons pass, clusters merge. (Full function — see git history.)
**Task 2.3:** `_merge_cluster` — title from highest-severity (ties: most evidence), max severity, strongest strength (`confirmed`>`due`>`due_stated`>`reported`), deduped rationale/advice joins, max confidence, shared domain, representative `Claim`.
**Task 2.4:** Call at end of `resolve_claims()`; try/except fail-open (log + original list).

## Phase 3 — Update summary counts (1 file: main.py)

**Task 3.1:** Verify `_build_summary()` counts post-dedup `risks` (built from deduped `served` list) — expected: no change needed.

## Phase 4 — Frontend domain grouping (2 files: hover_lite.js, hover_lite.css)

**Task 4.1:** `renderRisksGrouped(risks)` — group by domain; per group a header (icon + label + count + severity dots + toggle) and body of `renderRiskCard` output; `wireDomainToggles()` flips `aria-expanded`/`data-open`/toggle glyph. Replaces the flat `innerHTML` mapping. (Full snippets — see git history.)
**Task 4.2:** CSS for `.lite-domain-groups/.lite-domain-group/.lite-domain-head/.lite-domain-body/.lite-domain-sev-dot` (flex rows, hover states, severity colours; full rules — see git history).

## Phase 5 — Cross-file duplicate warnings (1 file: sync.py)

**Task 5.1:** `warn_cross_file_duplicates(parts)` post-load, pre-sync: same-domain cross-file pairs with `title_similar` ⇒ `log.warning` with part/file/claim-key/titles. (Full function — see git history.)

## Phase 6 — Testing

**Task 6.1:** `backend/tests/test_resolver_dedup.py` — `_deduplicate_results` (empty/single/no-match/merge/multi-domain), `_merge_cluster` (strength/severity), 6 timing-belt claims → ~2 groups.
**Task 6.2:** Manual frontend pass (sections, toggles, counts, cards-in-sections).

## Dependencies

`Phase 1 → Phase 2 → Phase 3`, `Phase 4 ∥ Phase 3` (needs Phase 2's output shape only), `Phase 5` anytime after Phase 1, `Phase 6` after Phases 2 + 4.
