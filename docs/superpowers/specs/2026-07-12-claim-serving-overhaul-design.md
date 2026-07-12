# Claim-serving overhaul — design spec

**Date:** 2026-07-12 · **Branch:** `model-year-claim-windows` · **Status:** approved, ready to plan

## Problem

Kriko surfaces ~100+ claims for a single listing. The user's requirement is "few
data for one specific model/engine/transmission/year combination." Investigation
(four measurements, 2026-07-12) established the bloat is **not** junk and **not** a
consequence-ranking problem — it is a **flat-ranking + no-cap + empty-context-gate**
problem in the serving pipeline.

Serving today is `select → context-gate (fail-open) → cluster/dedup →
sort(strength, severity)` in `backend/core/resolver.py` + `backend/api/main.py:74-77`.
Both sort keys are dead in practice:

- **severity** is 47% `high` / 4% `low` (LLM-provisional, inflated) — no spread.
- **strength** has three tiers (`confirmed` > `due`/`due_stated` > `reported`) but
  `due`/`due_stated` are **always empty**: they come from `_resolve_maintenance_strength`
  and there are **zero `maintenance`-kind claims** (all 906 are `known_issue`). So
  506 of 527 servable claims sort identically as `(reported, high|medium)`.
- There is **no cap** — every servable, gated claim is returned.

### Problem inventory

| # | Problem | Consequence |
|---|---|---|
| A | Flat ranking (severity inflated; `due`/`due_stated` empty) | 506/527 sort identically |
| B | No per-listing cap | Everything shows even with a good sort |
| C | Context gates ~89% unpopulated (age/year/fuel ≈ 0%; mileage now ~11%) | High-mileage cars get no reduction |
| D | Zero `maintenance`-kind claims | Highest-value category absent; strength signal dead |
| E | Value-gate false positives (`gate_inspection_value` inspection-covered path lacks specificity escape valve) | Real keepers (DQ200 clutch) wrongly held |
| F | Deterministic grounding reaches ~11% | Other 90% needs suggester→verify→sign-off loop (absent) |

## Target architecture

One per-listing pipeline, unchanged in shape, fixed at each stage:

```
select → context-gate (fail-open) → cluster/dedup → RANK (real signal) → CAP → present
```

Guiding invariants (carry from the existing guards):
- **Fail-open on missing data** — never hide a risk for absent listing data.
- **Deterministic where possible; LLM only as a suggester behind a deterministic
  verifier + human sign-off.** (Guards: `ground_year_window`, `ground_mileage_threshold`.)
- **No hardcoded car data** — closed engineering vocabularies (fuel, subsystem
  categories, cue words) are the allowed exception; nothing that grows with car coverage.

## Phases

### Phase A — Real ranking signal (deterministic spine)
Replace the flat `(strength, severity)` sort with a deterministic **priority key**:
`(strength_rank, consequence_tier_rank, context_specificity_rank, corroboration)`.
- New `knowledge/consequence_tier.py`: pure `consequence_tier(title, rationale) → "high"|"medium"|"low"`.
  HIGH on expensive-subsystem vocab (timing, dual-clutch/mechatronic, DPF/SCR, turbo,
  injection, EGR, engine internals) — **multilingual** (fix `mekatronik`≠`mechatronic`);
  LOW only on unambiguous comfort/cosmetic/performance terms **and** no high-system term
  (ambiguity guard: `software` on a radio claim is low, on an ECU/EDC claim is high);
  else MEDIUM. Bias to never demote a real mechanical failure (asymmetric, like the
  year/mileage guards). Rehabilitated as a *cross-car* ranking input (it fails only as a
  *within-engine* discriminator).
- `context_specificity_rank`: a claim the listing *specifically triggered* (a context
  gate it just passed — mileage/age/year present and satisfied) outranks an ungated
  generic claim.
- Serving change: `backend/api/main.py` sort key + `resolver` expose the inputs. TDD.

### Phase B — Cap
After ranking, cap to top-N per listing with per-domain balance (avoid all-engine).
Never cap below `confirmed`/`due`/`due_stated` items (those always survive). Config
constant `MAX_RISKS_PER_LISTING` (+ per-domain soft cap). TDD in `test_context_gating`
/ a new serving test. Guarantees "few" for **all** cars incl. high-mileage.

### Phase C — Maintenance-kind (lights up the dead strength tiers)
Reclassify interval-shaped `known_issue` claims (timing belt/chain service, DSG fluid,
major service, clutch wear) to `kind: maintenance` with a `maintenance` interval block,
so `_resolve_maintenance_strength` produces `due`/`due_stated`. Deterministic candidate
detection (interval vocab + the mileage already grounded in Phase-mileage work) → a
backfill script with dry-run + sign-off (no hand-YAML). Turns "timing belt" into "DUE
at ~90k unless the ad proves otherwise." Highest product value; fixes ranking at source.

### Phase D — Broaden gate coverage
- Extend deterministic grounders to `min_age_years` and year windows where the claim
  text states them (same guard pattern).
- Build the **LLM-suggester → deterministic-verify → sign-off loop** for the ~90% that
  don't state their thresholds: LLM proposes a gate with a cited quote; the existing
  `ground_*` verifiers confirm the quote actually contains the figure; a human approves
  the proposal table before write. Reuses `backfill_claim_mileage`/`backfill_claim_window`
  as the write path. This is the only phase touching the distrusted LLM — contained by
  verify + sign-off.

### Phase E — Value-gate hardening
Add the specificity escape valve to `gate_inspection_value`'s inspection-covered
stoplist path (mirror `gate_generic`: a config/mileage signal keeps an otherwise
inspection-sounding claim), unburying keepers like the DQ200 clutch. Re-run the gates
over the corpus to hold what should be held. TDD in `test_judge_inspection` /
`test_specificity_checks`.

## Sequencing & risk

1. **A** (ranking) → 2. **B** (cap) — the spine; deterministic; delivers "few" for all cars.
3. **C** (maintenance-kind) — deterministic backfill; biggest product-value lift.
4. **E** (gate hardening) — small, deterministic, independent.
5. **D** (coverage + suggester) — largest; the only LLM-in-loop part; last.

A→B are sequential (B needs A's rank). C, E are independent of the serving code and of
each other (candidates for subagents). D is independent but large. All phases TDD, each
committed separately. Serving-plane edits (A, B) done in-session to avoid conflicting
edits to `resolver.py`/`main.py`.

## Verification
- Per-phase unit tests (TDD, fail-first).
- End-to-end via `run_analysis`: a low-mileage and a high-mileage sample listing both
  return ≤ `MAX_RISKS_PER_LISTING`, ordered by the new priority key, with a maintenance
  item shown as "due" where applicable.
- Full `knowledge/` + `backend/` suites green; corpus validates; `context.model_year`
  etc. visible in the JSONL trace.
- Migration: any new nullable columns need the commented `ALTER TABLE` lines applied to
  live Postgres before sync (fresh-volume caveat).

## Explicitly out of scope
Recall importer (KBA license unconfirmed — see `reference_recall_data_sources`); the
evidence-ledger's two open acceptance blockers (separate branch); listing granularity
finer than model-year (unreachable — `content.js` scrapes year only).
