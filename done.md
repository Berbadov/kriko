# Kriko — Done

Completed work, newest first. Entries move here from `backlog.md` with date + commit.
Seeded 2026-07-16 from git history; older history lives in `git log` and
`docs/pipeline_postmortem.md`.

---

## 2026-08-03 — Remediate loop live run + parity-lost self-closing (no commit yet)

- **First live remediate run** (coverage-driven, budget-capped): researched the 9
  zero-claim parts (dw5/dw6 now have 10/16 exported claims), 389 LLM calls for
  $0.17; backfilled the legacy cache (+234 docs, +1138 evidence rows); export
  regenerated (19 parts, dw5/dw6 covered).
- **Parity re-classification**: legacy claims with zero source URLs (~331 —
  mostly body/elec era claims) were counted as "never extracted"; they are
  unverifiable provenance — no URL means no evidence path, and the ledger's
  ≥1-grounded-source bar would never serve them. New category "no source URLs
  in legacy claim (unverifiable provenance)" in `parity.explain_only_old` —
  attributable, not lost. Gate lost count: 124 → 49.
- **Lost-source self-closing loop** (`remediate.lost_source_urls` /
  `ingest_lost_sources`): every parity-lost claim's cited URLs are fetched +
  ingested into the ledger (target_hint = claim's part stem) before the
  extract/cluster/verdict pass — the 49 remaining losses are now ingestible
  pages, not orphans. Tests added; suite 591.
- **Second live run**: ingested the 49 lost pages (+50 docs total), then hit
  **`Insufficient Balance` on the DeepSeek API** — extraction/verdicts pending,
  fully resumable. Once funded: `python -m knowledge.ledger.run remediate
  --max-usd 2.0` → `python -m knowledge.ledger.swap check`.

## 2026-08-03 — B16 swap mechanism + automated acceptance gate (no commit yet)

- **Export regenerated from the ledger** — the checked-in `ledger_export/` had gone
  stale (15 files, missing dq200/dq250/dq381/ea211/ea888/k9k, one bare-list
  artifact). Fresh run: 19 parts, 536 claims; `golf7_cool_cooling` correctly
  skip-and-reported (no catalog identity). Each part file now carries
  `legacy_part_ids` (which legacy power-split files it supersedes) —
  pipeline-derived via the power-collapse rule, no hand list.
- **`knowledge/ledger/swap.py`** — `plan` derives the legacy→merged fitment remap
  from the export, classifies every legacy file (superseded/retained), counts
  fitment edits; `apply` writes export files into `parts/<type>/`, deletes
  superseded power-split files, overwrites non-split ids in place (fixes a
  delete-pass bug that rglob'd away the fresh export files), rewrites fitment
  axes, defaults to a temp copy unless `--in-place`; `check` = the automated
  acceptance gate: parity loss (every absent legacy claim attributable to a
  named gate), serving monotonicity (baseline replayed against current AND
  post-swap catalogs on fresh DBs — 0 match-loss regressions allowed), coverage
  must not add findings. Tests: `test_ledger_swap.py`; suite 589.
- **Live gate state: FAIL, data-gated** — 119 lost claims (75 never extracted,
  23 never ingested, 21 no matching evidence) → B19 remediate loop targets;
  serving: 21/43 listings differ vs current serving, 0 regressions; coverage
  18→11. Swap lands when parity-lost hits 0.
- USAGE.md §4 Step 6 documents plan/check/apply.

## 2026-08-03 — B11 data safe + B19 auto-remediation loop landed (no commit yet)

- **B11 (data, fail-open)**: hand-typed `emissions`/`aftertreatment` removed from
  all 8 Megane 4 variant rows — the unverified `scr` value on
  `megane4_k9k_110_edc` (wrong for 2016–18) no longer serves. All variants fail
  open (no SCR grounding) until evidence-derived values exist.
- **B11 (mechanism)**: year-split `emissions` segments in `write_variants.py` —
  list of `{year_from, year_to, emissions}` per trim emits one variant row per
  era (`{id}__{emissions}` suffix), per-segment aftertreatment derivation,
  window validation. Tests: `test_write_variants_emissions.py`.
- **B11 (visibility)**: new `variant_no_emissions` coverage finding for diesel
  variants without an emissions value — the gap is reported, never a quiet
  wrong value. Tests added to `test_coverage_tool.py`.
- **B19 (driver)**: `python -m knowledge.ledger.run remediate`
  (`knowledge/ledger/remediate.py`) — coverage findings (zero_claim_part /
  missing_part / auto_variant_no_tx_part, now carrying `part_id`+`axis`
  metadata) drive an unattended acquire → extract → resolve → cluster → verdict
  → export pass. Budget-capped (`--max-usd`), resumable, `--dry-run` prints the
  plan, empty plan spends nothing. Every pass appends `logs/remediation.jsonl`.
  USAGE.md §4b documents scheduling. Tests: `test_ledger_remediate.py`.
- **G5 cleanup**: the draft-row onboarding step ("a human fills in real
  numbers") is retired — `draft_variant` coverage finding makes scaffolded
  rows fail open visibly; USAGE.md's "Promoting & rejecting claims (human
  step)" section replaced with a retired banner (statuses are verdict-stage
  owned). Docs updated to remove human-step language from onboarding.
- Full suite: 583 passed.

## 2026-08-03 — Priority reorganization: full automation + systemic-only (no commit — doc-only)

Two project rules changed in `CLAUDE.md` and the backlog, per the owner:

- **Automation principle (new)** — nothing in the data path waits for human
  verification, spot-checks, or sign-off; extraction and scraping run unattended.
  Where a value can't be derived automatically, fail open + log the gap. One-time
  policy decisions only (ToS, market coverage, source retirement).
- **Generalization principle (strengthened)** — per-model fixes do not exist:
  no per-model research runs, YAML audits, or spot-checks. Every fix is a mechanism
  that runs for all cars, or the feature is cancelled.
- **B17 dropped** — all official recall feeds retired (TR SGM, EU Safety Gate, NHTSA).
  HUMAN DECISION #6 resolved (drop). Ingested rows stay in `ledger.db` as history;
  feed ingesters + `run.py feeds` wiring to be removed/dormant.
- **B11 sign-off cancelled** — HUMAN DECISION #7 resolved: emissions values derive
  from evidence or fail open (no AdBlue claims when unknown); year-split rows where
  mid-life changes exist; hand-typed Megane 4 values must not serve as-is.
- **B19 created** — auto-remediation loop (coverage-report findings + B6
  contradiction signals auto-enqueue ledger acquire/extract + catalog regen).
  Absorbs former B2 (dw5/dw6) and B3 (EDC-auto gap, "manual only in TR" audits),
  whose manual steps are cancelled.
- **B16** — human spot-review sub-step replaced by an automated acceptance gate
  (parity --explain categories + coverage report + serving-baseline replay).
- **B9** — near-miss policy adopted: out-of-window listing still matches, with a
  "year outside known window" note + demand signal. No further decision.
- Remaining human decision: #5 only (B18 source ToS — one-time legal gate).

## 2026-08-02 — Serving-resolution fix + B15/B16/B17/B8 + B11 mechanism (wave 2)

- **Resolver fixed** — EDC Megane analyses stopped resolving transmission claims:
  `_resolve_part_claims` returned IDs instead of claim objects, and the missing
  `_fuel_compatible` import broke the fuel filter. Introduced `_servable_invariants`
  (source-requirement + high-severity-unreviewed gates) shared by both serving paths.
  Full suite 560 passed.
- **B3 (patch) + B6 (mechanism)**: added `megane4_k9k_110_edc` variant + fitment via the
  catalog pipeline; matcher/transmission-gap tests now pin EDC ads → EDC variant with
  `tx_mismatch false`. B6's coverage-gap test stays green via generic fixture variants.
- **B15 (done)**: deploy-staleness guard — `GIT_COMMIT`/`GIT_BUILD_TIME` stamped at image
  build (Dockerfile ARG/ENV, docker-compose, `scripts/run_local.sh`), surfaced via
  `/health`, `/analyze` (`build` field), and the extension footer. Recurrence guard for
  the B4 stale-image class. Tests: `test_build_stamp.py`, `hover_lite.test.js`.
- **B11 (mechanism landed; data at sign-off checkpoint, HUMAN DECISION #7)**: emissions/
  aftertreatment columns + `_scr_compatible`/`_default_aftertreatment` grounding gate in
  `backend/sync.py`; generator support in `write_variants.py`; `test_scr_gate.py`.
  Megane 4 values hand-typed pending spot-check (EDC row 110 ≠ Blue dCi 115 SCR years).
- **B17 (EU half done; TR blocked, HUMAN DECISION #6)**: Safety Gate feed rewritten to
  the official weekly-report XML after the reverse-engineered JSON API died (404);
  validated live — 50 Renault alerts ingested into `ledger.db`, idempotent.
  TR SGM blocked by an anti-bot JS challenge (TSPD); ingester kept, never fatal.
- **B16 (step 1 done)**: export rewritten to the part-dict schema with serving-gate
  fields grounded at export (year windows, mileage thresholds, maintenance);
  skip-and-report retained. Verified live to `/tmp/opencode/ledger_export` (19 parts).
- **B8 (done)**: `_select_capped` now ranks sources by domain reliability + title
  specificity; DeepSeek `json_object` extraction mode fixed.
- **B15/B17 feed run** left resumable in the background (text-hash dedup).

## 2026-07-22 — DB rebuild + evidence-ledger landing (B1/B12, G2/G4)

- **Serving DB rebuilt from YAML after accidental volume deletion** — no data loss
  by design (YAML is the source of truth; `logs/analyses.jsonl` and
  `knowledge/ledger.db` both survived). Rebuild surfaced a real deploy bug:
- **fix(deploy): add knowledge/consequence_tier.py to the image slice** (`56cb8af`) —
  fresh Docker builds crashed at startup (`sync.py` imports the consequence-tier
  module, but the Dockerfile's knowledge/ slice predated the serving overhaul).
  The recreate-from-scratch path had been silently broken since the overhaul
  landed (B15 class). Serving baseline fixture captured for future serving diffs
  (`backend/tests/fixtures/serving_baseline_2026-07-22.json`, 43 logged listings).
- **B1: evidence-ledger Stage 1 landed to main** (`80edf94`, G4: one trunk). Main
  merged into the branch (`bea0f5a`, one `.gitignore` conflict), then the two
  blockers fixed on-branch:
  - **Export skip-and-report** (`767dc82`) — one invalid cluster (DTC-in-title)
    no longer aborts the whole export; offenders are skipped, reported, retained.
  - **Parity stable identity** (`767dc82`) — match on shared source URLs + domain
    agreement instead of verdict-rewritten titles (`matched: 0` → 327 matched,
    95 sibling-reroute moves); cross-domain false matches from multi-claim pages
    guarded by the domain check.
  - **`parity --explain` acceptance report** (`84c2462`) — categorizes all 474
    only-in-existing claims (126 shipped under rewritten titles, ~230 gate drops
    working as designed, ~120 never ingested/extracted → tracked as B16's
    pre-swap review). Artifact: `thoughts/ledger_acceptance_parity_2026-07-22.txt`.
  - Servable catalog deliberately NOT swapped: legacy part YAMLs still serve until
    the export carries serving-gate fields and fitment is remapped (B16).
- **B12 completed** — `evidence-ledger-stage1` and `model-year-claim-windows`
  merged and deleted; `main` is the only trunk.

## 2026-07 (branch `model-year-claim-windows`, pending merge — backlog B12)

### Backlog wave 1 (2026-07-16/17, subagent-driven — merged into the branch)

- **Ad-vs-catalog transmission contradiction surfaced (B6)** (8990d99) — when the ad's
  gearbox matches no candidate variant's transmission and no same-engine alternative row
  exists, the resolver emits a degraded coverage note and logs a catalog-gap signal
  instead of falling back silently.
- **Coverage report + loud sync guard (B7)** (c8201f4) — `python -m backend.tools.coverage`
  maps variant → fitment parts → per-part claim counts and flags any non-`manual`
  transmission/engine code that resolves to a zero-claim part; `sync.py` prints the same
  warning. The "would it recur?" mechanism for the dw5 hole (B2).
- **Per-listing risk-cap regression net (B4)** (22c9117) — investigation proved the cap
  already binds in code; the 39-risk DSG Golf came from a stale deployed Docker image
  predating the cap commit (3672eaa), not a code bypass. Added unit-boundary + e2e
  `/analyze` regression tests pinning the cap. The remaining real fix (make a stale deploy
  visible) is new backlog **B15**.
- **`no_match` demand miner (B10)** (4a173cc → f2481c8 → 52aafa6, merged 19d62db) —
  `python -m backend.tools.demand` aggregates `no_match` `/analyze` log rows into a
  make/model onboarding-demand table, reason-classified (`not_onboarded` / `catalog_gap` /
  `missing_fields`), catalog-derived via `normalize.py` (no hardcoded car names). Review
  fix rounds: shared `observability.load_records` reader hardened against non-dict lines
  (also hardens `read_recent`/`read_by_id`), `missing_fields` derived from `ad_metadata`
  not matcher prose, fixture-catalog tests, majority-casing group labels, data-derived
  table widths.

- **Golf 7 1.2 TSI onboarded; fitment derived from variants** (a780f82) — no more
  hand-maintained fitment for new rows.
- **Scraper robustness pass** (0ada2d6, d697ee3, 6f64eb8) — fuel/year scraped reliably,
  make/model/fuel/year recovered from URL+title when the DOM fails, English-locale
  Sahibinden handled. Killed most of the `(None, 'Golf', None) → no_match` log rows.
- **Serving overhaul, phases A/B/C/E** (0463869, 3672eaa, b3c769b, c483cb5) —
  consequence-tier ranking signal, per-listing risk cap (MAX_RISKS_PER_LISTING=8;
  see backlog B4 for the exemption loophole), maintenance-kind reclassify script,
  specificity escape valve on the inspection-covered judge gate.
- **Model-year claim windows + mileage gates** (08f00a5, 123b2b7, 2960759) — claims
  carry `applies_year_from/to` and mileage thresholds, grounded deterministically;
  resolver hides out-of-window defects (fail-open on missing data).
- **Failure-onset vs service-interval confusion rejected** (59b22c2); **codes for
  never-onboarded components caught** (980e90f).
- **run_local.sh** (60c307d) — serve the API without Docker/Postgres.

## 2026-07 (branch `evidence-ledger-stage1`, unmerged — backlog B1)

- **Evidence-ledger Stage 1 pipeline** (24 commits, ~50c9ed1..434f9ec) — chunked cached
  extraction with budget enforcement, deterministic per-component evidence clustering,
  single batched verdict per cluster (migrated to DeepSeek, hash-cached, concurrent),
  resumable CLI with dry-run + cost report, validated YAML export, parity diff +
  gold-set verdict eval.
- **Deterministic product-value gate over the verdict model** (b9f0b0d) — eval_verdict
  11/11 gold, resolved the acceptance blocker.
- **Data-quality pass** (16dab04, b131d6d) — unreliable-source-domain blocklist,
  German-language evidence leak flagging.
- **AdBlue/SCR variant-scoping design spec** (434f9ec) — spec only; implementation is
  backlog B11.

## 2026-06 → 2026-07 (on `main`)

- **Part-centric "Lego" pipeline** — parts researched once (`backend/data/parts/**`),
  assembled per variant at sync via fitment YAML; catalog discovery scaffolds variants
  and fitment from Wikipedia.
- **Sync-time grounding guards** — transmission-code registry derived from the part
  catalog (no hardcoded code lists), fuel/drivetrain/powertrain compatibility checks
  stop cross-config contamination broadcasting (`backend/sync.py`).
- **Serve-time gates** — equipment gate, ad-stated-transmission gate (manual ad never
  sees DSG-mechanism claims), high-severity human-review gate, title-similarity dedup
  with strongest-signal merge (`backend/core/resolver.py`).
- **Observability** — `logs/analyses.jsonl` + `backend.tools.analyses` / `replay`
  (branch `observability-analyses-log`, merged content on current branch).
- **Docs** — `docs/INTERNALS.md`, `docs/USAGE.md`, `docs/design_flaws.md` (Flaws 1–4
  addressed; 5–6 tracked as backlog B13), `docs/pipeline_postmortem.md`.
