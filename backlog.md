# Kriko — Backlog

Prioritized open work. Read `CLAUDE.md` (product + scalability principles) before picking
anything up. When an item is finished, move it to `done.md` with the date and commit hash.

- **P0** — actively hurting buyers or blocking everything else
- **P1** — the next round of high-leverage work
- **P2** — real, but can wait

Evidence for many items comes from production logs: `logs/analyses.jsonl`
(`python -m backend.tools.analyses --last 20`).

---

## Goals (2026-07)

**G1 — Quality over quantity.** A buyer sees at most ~8 risks, and they are the
*general chronics*: config-specific, high-consequence, multi-source-corroborated issues.
Today a DSG Golf gets 39–86 cards; nobody reads 39 cards.

**G2 — Cut pipeline cost per car by ~10×.** Classification spend must be budgeted,
cached, and reported. The evidence-ledger Stage 1 branch already implements most of this;
it needs its two blockers fixed and merging. **(Landed 2026-07-22 — B1 closed.)**

**G3 — No silent coverage holes.** If a car is automatic, its gearbox chronics must show.
Ad-vs-catalog contradictions and empty part files must be *visible* (coverage_state,
coverage report), never a quiet zero.

**G4 — One trunk.** `main` is behind two long-lived branches
(`model-year-claim-windows`, `evidence-ledger-stage1`). Consolidate so fixes stop
living in three places. **(Done 2026-07-22 — both branches merged, worktrees pruned,
merged branches deleted.)**

**Cross-cutting rule — patch the car, ship the mechanism** (see CLAUDE.md's
generalization principle): a per-model fix is only half done until the guard that
catches the same problem class on *every* car exists. The backlog pairs them
explicitly: B2/B3 (patches) ↔ B6/B7 (mechanisms). Don't close a patch item and
skip its mechanism.

---

## P0

### B1 — ~~Land evidence-ledger Stage 1~~ **DONE 2026-07-22** `[G2][G1]`
Landed to `main` (merge up to `80edf94`). Both blockers fixed on the branch:
export skip-and-report (`767dc82`), parity stable identity via shared source
URLs + domain agreement (`767dc82`), plus `parity --explain` acceptance report
(`84c2462`, artifact `thoughts/ledger_acceptance_parity_2026-07-22.txt`).
Acceptance numbers: 568 exported claims; 327 matched / 95 sibling-rerouted /
126 shipped-under-rewritten-titles; ~230 gate drops working as designed.
**Not done here (tracked below):** the servable catalog is still the legacy
part YAMLs — swapping in the export needs the export schema to carry the
gating fields (mileage/year windows/maintenance) and the fitment remap to
merged part identities. That is the Phase-3 catalog swap, paired with B5.
Legacy machinery retirement (judge gates, promote stack, purge_*.py) happens
with that swap, not before.

### B17 — EU Safety Gate + TR SGM recall feeds `[G3]`
NHTSA (US-only) covers VW; Renault sells nothing there. Two ingesters exist
(`knowledge/ledger/feeds/safety_gate.py`, `knowledge/ledger/feeds/recalls_tr.py`)
following the NHTSA pattern — structured documents + pre-structured evidence,
zero extraction LLM. Wired into `run.py feeds --feed` and the `all` pipeline.
Live validation done 2026-08-02:
- [x] **EU Safety Gate: VALIDATED + REWIRED.** The reverse-engineered JSON API
      (`/safety-gate/api/v2/alerts`) is dead (404). The official weekly-report
      XML (`safety-gate-alerts/api/download/weeklyReport/list/xml/en`) is the
      only public data source — feed rewritten to parse it (brand/product/
      danger/caseNumber/reference), brand-filtered per catalog make. Live run
      ingested 50 Renault alerts into `ledger.db`; idempotent (doc text-hash
      dedup + evidence title check).
- [x] **TR SGM: BLOCKED — HUMAN DECISION #6.** `sanayi.gov.tr/sgm/api/recalls`
      and the site itself answer non-browser clients with an anti-bot JS
      challenge (TSPD cookie) — a server-side HTTP client gets no JSON. The
      ingester is kept (idempotent, errors counted not fatal) but cannot
      ingest until a working route exists: headless-browser fetch, an official
      alternative TR recall source, or the wall lifting. Decide: pursue any of
      these or drop TR recall coverage (NHTSA + Safety Gate remain).
- [x] Run `python -m knowledge.ledger.run feeds --feed safety_gate` — Renault
      recalls verified in the ledger (50 docs/evidence rows). Full-model pass
      is resumable; VW/Clio runs were still fetching when the window closed.

### B16 — Catalog swap: serve the ledger export instead of legacy part YAMLs `[G1][G2]`
The ledger export (`knowledge/ledger_export/`, 568 claims) is acceptance-ready
per the parity report, but three gaps block replacing `backend/data/parts/`:
- [x] Export emits bare claim lists; sync expects part-dict YAML — **fixed 2026-08-02:**
      export rewritten to the part-dict schema (part_id/part_type/display_name/
      manufacturer/known_also_as/claims) with serving-gate fields grounded at export
      (deterministic grounders: applies_year_from/to, maintenance, min_mileage_km,
      requires_equipment). Verified live to `/tmp/opencode/ledger_export` (19 parts;
      skip-and-report for golf7_cool_cooling + duplicate k9k_engine_connecting_rod_bearing_f).
- [ ] Fitment remap to merged identities: export files are `k9k.yaml`,
      `h5h.yaml`, … but fitment rows point at `k9k_110`, `h5h_140`, …
      (the Flaw-2 merge — pairs with B5's per-part budget work).
- [ ] Thin merged files vs legacy: h5d 1 claim vs 69, h4d 1 vs 35, ea288 23 vs
      91 — mostly verdict-stage drops; needs a human spot-review pass before
      swap (start: `parity --explain` categories "unsupported" and
      "never extracted").
- [ ] Then: swap `backend/data/parts/` for the export, replay the serving
      baseline fixture (`backend/tests/fixtures/serving_baseline_2026-07-22.json`),
      retire judge.py gates / promote.py / purge_*.py / translate_claims.py.

### B2 — Research the empty gearbox parts: `dw5` (EDC7), `dw6` `[G3]`
`backend/data/parts/transmission/dw5.yaml` and `dw6.yaml` have `claims: []`, but every
automatic petrol Megane 4 variant (`megane4_h5h_115/140`, fitment `dw5`) and the
`megane4_r9m_130` (`dw6`) point at them. Production log: Megane 1.3 TCe EDC, exact match,
12 risks, **0 transmission risks** — while the sibling `dc4.yaml` holds 76 EDC claims that
correctly don't apply. Run the pipeline:
- [ ] `python -m knowledge.auto --part dw5 --part-type transmission`
- [ ] `python -m knowledge.auto --part dw6 --part-type transmission`
- [ ] Verify with `backend.tools.replay` against the logged Megane EDC analyses.

*Per-model patch — its recurrence mechanism is B7 (coverage report). Do both.*

### B3 — Catalog gaps: automatic rows that exist on the street but not in the YAML `[G3]`
Logged EDC 1.5 dCi Meganes (2018/2019/2020) "exact"-matched `megane4_k9k_110` — a variant
cataloged `transmission: manual`. The matcher's transmission narrowing is soft, so the ad
silently matched the manual row and *no gearbox part exists on that route at all*.
- [x] Add `megane4_k9k_110_edc` (1.5 dCi + EDC/DC4) variant + fitment rows via the
      catalog pipeline (no hand-written YAML). **Done 2026-08-02** — generated
      `renault_megane_4.yaml` row (dc4 + euro6d_temp/scr — value pending B11
      sign-off) + fitment row; matcher pins updated (`test_matcher.py`,
      `test_transmission_coverage_gap.py`) so EDC ads resolve to the EDC variant
      and `tx_mismatch` is false.
- [ ] Audit the "manual only in TR" notes in `volkswagen_golf_7.yaml`
      (esp. 1.6 TDI — DSG 1.6 TDIs are common on Sahibinden) and Clio 5 diesel rows.
- [ ] Re-check against `logs/analyses.jsonl` afterwards.

*Per-model patch — its recurrence mechanism is B6 (contradiction surfacing). Do both.*

---

## P1

### B15 — ~~Deploy-staleness guard: surface the running build~~ **DONE 2026-08-02** `[G1]`
B4's 39-risk DSG Golf turned out to be a stale deployed Docker image (predating the
risk-cap commit 3672eaa by ~23h), not a code bug — the cap binds in code (regression net
22c9117). Nothing tells an operator the deployed artifact is behind HEAD.
**Shipped:** `GIT_COMMIT`/`GIT_BUILD_TIME` stamped at image build (`deploy/Dockerfile`
ARGs → ENV, wired in `docker-compose.yml`; `scripts/run_local.sh` reads the checkout)
and surfaced via `/health` + every `/analyze` response (`build` field) + the extension
footer ("api · <commit>"). Unstamped builds report "unknown" — itself the tell.
Tests: `backend/tests/test_build_stamp.py`, `extension_ui/tests/hover_lite.test.js`.

### B5 — Per-part claim budget: keep the chronics, archive the tail `[G1]`
896 claims across part files for 3 models (~300/model) is the volume problem at its
source. Rank claims within each part by consequence × independent-source count ×
specificity; keep the top ~15 servable, move the tail to a non-synced archive section.
Corroboration count *is* the "general chronic" signal. Respect the product principle
test in `CLAUDE.md` ("would the standard inspection catch this anyway?").

### B12 — Branch consolidation `[G4]`
- [x] Merge `model-year-claim-windows` → `main` (2026-07-17, ff to 8acec0b; serving
      overhaul A/B/C/E, scraper fixes, model-year windows, Golf 1.2 TSI, backlog wave 1).
      `main` is local-only ahead of `origin/main` by 33 — not pushed.
- [x] Delete stale worktree branches after checking (2026-07-17): removed the five
      `.claude/worktrees/*` worktrees and deleted the merged branches
      `worktree-agent-*` (×4), `worktree-search-gate-fix`, `observability-analyses-log`.
      `model-year-claim-windows` kept (identical to main); `evidence-ledger-stage1` kept.
- [x] Land `evidence-ledger-stage1` (2026-07-22 — merged to main at `80edf94`
      instead of rebasing: main merged into the branch first, two blockers fixed
      there, then ff-merged back; merged local branches deleted).

---

## P2

### B8 — ~~Rank sources before spending extraction tokens~~ **DONE 2026-08-02** `[G2]`
`_select_capped` (`knowledge/auto.py:175`) kept sources in discovery order. Now scores by
domain reliability + title specificity (engine/gearbox code mentions) so the ≤25 extracted
sources are the ones most likely to describe chronics, not the first 25 Exa returned.
Also fixed DeepSeek structured-extraction mode (explicit `json_object` request in
`langextract_client.py`). Tests green.

### B9 — Year-window near-miss policy `[G3]`
A 2024 Megane 1.3 TCe listing no_matched ("No renault megane petrol for 2024" —
`year_to: 2023`). TR production/sales windows differ from EU. Decide: extend windows from
TR-market data, or match with a "year outside known window" note instead of nothing.

### B11 — AdBlue/SCR variant-scoping: mechanism landed, data pending sign-off `[G3]`
Design spec written (`docs/superpowers/specs/2026-07-10-variant-emissions-scr-gate-design.md`,
434f9ec). **Landed 2026-08-02:** `Variant.emissions`/`aftertreatment` columns (models.py +
schema.sql + ALTER notes), `_scr_compatible`/`_default_aftertreatment` in `backend/sync.py`
wired into per-variant claim grounding, generator support in `write_variants.py`
(emissions passthrough + aftertreatment derivation), tests (`test_scr_gate.py`, grounding
matrix). Megane 4 rows carry values (incl. new `megane4_k9k_110_edc` = euro6d_temp/scr).
**Still open — spec §2 data-accuracy checkpoint (HUMAN DECISION #7):** per-trim `emissions`
values are real engineering facts; the Megane 4 values were hand-typed without sign-off and
need spot-checking (e.g. the 110 EDC through 2018 was NOT AdBlue — Blue dCi/SCR only came
2018/19 at 115hp, so the EDC row's single scr value is wrong for 2016-2018 cars; a single
row can't express a mid-life emissions change — may need year-split rows). Clio 5 + Golf 7
have no values yet (propose from sources, then regen via `write_variants.py` — 1.6 TDI
stayed LNT, 2.0 TDI got AdBlue mid-life). Apply only after sign-off; wrong values would
broadcast AdBlue claims to non-AdBlue cars — strictly worse than the current no-data
fail-open.

### B14 — Documentation audit: docs must match the code
2026-07-16 pass fixed the worst drift (README rewritten; INTERNALS' qwen/OpenRouter →
ministral/Mistral, LLM dedup → deterministic Jaccard; historical banners on
handover/SCAFFOLD/build_plan; doc map in CLAUDE.md). Remaining:
- [ ] Verify every INTERNALS.md mechanism section against current code (promotion
      scoring, disposition rules, curated-source lifecycle) — it predates the
      part-centric flow in places.
- [ ] USAGE.md §5/§7 still document the model-centric legacy mode prominently;
      restructure around the part-centric flow.
- [ ] Decide whether `docs/handover.md` earns a rewrite or deletion once B12 lands.

### B13 — Remaining design-flaw work (`docs/design_flaws.md`)
- Flaw 5: judge too weak → whack-a-mole patches. The ledger's verdict stage is
  now on `main` (B1, 2026-07-22) — closes for the pipeline; the *served* catalog
  inherits the fix at the B16 catalog swap.
- Flaw 6: pipeline keeps what sources mention, not what Kriko exists to show.
  The deterministic product-value gate is on `main` and dropping ~230 claims in
  the export (see the B1 acceptance report); closes at B16 + B5.

### B18 — Source adapter ToS decisions: wire recalls/specialists/forums into the pipeline `[G2]`
Three source adapters exist (`knowledge/sources/recalls.py`, `specialists.py`,
`forums.py`) with working `fetch()` methods but are blocked on **HUMAN DECISION #5**:
confirm data licensing and Terms of Service for each source before enabling.
Once ToS is confirmed, wire them into `knowledge/ledger/acquire.py` as additional
discovery sources alongside Exa+YouTube (with a `--sources` flag to enable/disable).
