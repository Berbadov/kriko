> TL;DR (archived 2026-09-25): Design (2026-07-12, approved) fixing "~100+ claims per
listing": bloat is flat-ranking + no-cap + empty context gates (506/527 sort identically;
`due` tiers always empty — zero `maintenance` claims of 906). Fix: deterministic priority rank
(strength, consequence tier, context specificity, corroboration) → cap (never below
confirmed/due) → maintenance-kind backfill → gate coverage + suggester loop → value-gate fix.

# Claim-serving overhaul — design spec

**Date:** 2026-07-12 · **Branch:** `model-year-claim-windows` · **Status:** approved, ready to plan

## Problem

~100+ claims per listing; requirement is "few data for one model/engine/transmission/year". Measured 2026-07-12 (four measurements): **not junk, not consequence-ranking — flat-ranking + no-cap + empty-context-gate** in `resolver.py` + `main.py:74-77`. Both sort keys dead: **severity** 47% high / 4% low (inflated, no spread); **strength** tiers exist but `due`/`due_stated` are **always empty** (zero `maintenance`-kind of 906 claims) ⇒ 506/527 servable sort identically as `(reported, high|medium)`. **No cap** — everything gated is returned.

### Problem inventory

| # | Problem | Consequence |
|---|---|---|
| A | Flat ranking (inflated severity; dead `due` tiers) | 506/527 sort identically |
| B | No per-listing cap | Good sort still shows everything |
| C | Context gates ~89% unpopulated (age/year/fuel ≈ 0%; mileage ~11%) | No high-mileage reduction |
| D | Zero `maintenance`-kind claims | Best category absent; strength signal dead |
| E | `gate_inspection_value` lacks specificity escape | Keepers (DQ200 clutch) wrongly held |
| F | Deterministic grounding ~11% | 90% needs suggester→verify→sign-off loop (absent) |

## Target architecture

Same shape, fixed stages: `select → context-gate (fail-open) → cluster/dedup → RANK (real signal) → CAP → present`. Invariants carried over: **fail-open on missing data**; **deterministic where possible, LLM only as suggester behind deterministic verifier + human sign-off**; **no hardcoded car data** (closed engineering vocabularies excepted).

## Phases

### Phase A — Real ranking signal (deterministic spine)

Replace `(strength, severity)` with `(strength_rank, consequence_tier_rank, context_specificity_rank, corroboration)`. New `knowledge/consequence_tier.py` (pure, asymmetric — never demote real mechanical failure): HIGH on expensive-subsystem vocab (timing, dual-clutch/mechatronic, DPF/SCR, turbo, injection, EGR, internals), **multilingual** (`mekatronik`=`mechatronic`); LOW only on unambiguous comfort/cosmetic terms **and** no high-system term (`software`+radio = low, +ECU/EDC = high); else MEDIUM. Cross-car ranking input only (fails as within-engine discriminator). `context_specificity_rank`: listing-triggered (passed gate with data present) outranks ungated generic. Serving: `main.py` sort key + resolver inputs. TDD.

### Phase B — Cap

Top-N per listing + per-domain soft balance (never all-engine); never cap below `confirmed`/`due`/`due_stated`. Constant `MAX_RISKS_PER_LISTING`. TDD. Guarantees "few" incl. high-mileage.

### Phase C — Maintenance-kind (lights up the dead strength tiers)

Reclassify interval-shaped `known_issue` (belt/chain service, DSG fluid, major service, clutch wear) → `kind: maintenance` + interval block, so `_resolve_maintenance_strength` yields `due`/`due_stated`. Deterministic candidate detection (interval vocab + grounded mileage) → backfill script with dry-run + sign-off (no hand-YAML). "Timing belt" becomes "DUE at ~90k unless the ad proves otherwise." Biggest product-value lift.

### Phase D — Broaden gate coverage

Deterministic grounders for `min_age_years` + year windows (same guard pattern); **LLM-suggester → deterministic-verify → sign-off loop** for the ~90% unstated: LLM proposes gate + cited quote, `ground_*` verifiers confirm the figure is quoted, human approves the table, `backfill_claim_mileage`/`backfill_claim_window` write. Only LLM-in-loop phase — contained by verify + sign-off.

### Phase E — Value-gate hardening

Specificity escape valve on the inspection-covered stoplist path (mirror `gate_generic`): config/mileage signal keeps inspection-sounding claims; re-run corpus to hold what should hold. TDD (`test_judge_inspection`, `test_specificity_checks`).

## Sequencing & risk

**A → B** (spine; B needs A's rank) → **C** (deterministic backfill; biggest lift) → **E** (small, independent) → **D** (largest; only LLM part; last). C, E independent of serving code and each other (subagent candidates); D independent but large. All TDD, separate commits. A/B serving edits in-session (avoid `resolver.py`/`main.py` conflicts).

## Verification

Per-phase TDD fail-first; `run_analysis` e2e (low- + high-mileage samples ≤ cap, new priority order, maintenance "due" shown); full suites green; corpus validates; `context.model_year` visible in JSONL trace. New nullable columns need commented `ALTER TABLE` applied to live Postgres pre-sync.

## Explicitly out of scope

Recall importer (KBA license unconfirmed); evidence-ledger acceptance blockers (separate branch); sub-model-year granularity (`content.js` scrapes year only).
