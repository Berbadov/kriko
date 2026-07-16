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
it needs its two blockers fixed and merging.

**G3 — No silent coverage holes.** If a car is automatic, its gearbox chronics must show.
Ad-vs-catalog contradictions and empty part files must be *visible* (coverage_state,
coverage report), never a quiet zero.

**G4 — One trunk.** `main` is behind two long-lived branches
(`model-year-claim-windows`, `evidence-ledger-stage1`). Consolidate so fixes stop
living in three places.

---

## P0

### B1 — Land evidence-ledger Stage 1 (branch `evidence-ledger-stage1`) `[G2][G1]`
24 commits, unmerged. Already carries: budget-enforced chunked extraction with caching,
one batched verdict per cluster (DeepSeek), cost report, deterministic product-value gate
(11/11 gold), unreliable-domain blocklist. This is the single biggest lever on
classification cost. Two known blockers:
- [ ] Export aborts all-or-nothing on cluster 547 (DTC-title claim) — make export
      skip-and-report instead of abort, or fix the offending cluster.
- [ ] Parity run reports `matched: 0` — matcher compares rewritten titles; needs a
      stable cluster/evidence identity to diff against the legacy claims.
- [ ] Acceptance run, then merge (after B12 so it lands on an up-to-date main).

### B2 — Research the empty gearbox parts: `dw5` (EDC7), `dw6` `[G3]`
`backend/data/parts/transmission/dw5.yaml` and `dw6.yaml` have `claims: []`, but every
automatic petrol Megane 4 variant (`megane4_h5h_115/140`, fitment `dw5`) and the
`megane4_r9m_130` (`dw6`) point at them. Production log: Megane 1.3 TCe EDC, exact match,
12 risks, **0 transmission risks** — while the sibling `dc4.yaml` holds 76 EDC claims that
correctly don't apply. Run the pipeline:
- [ ] `python -m knowledge.auto --part dw5 --part-type transmission`
- [ ] `python -m knowledge.auto --part dw6 --part-type transmission`
- [ ] Verify with `backend.tools.replay` against the logged Megane EDC analyses.

### B3 — Catalog gaps: automatic rows that exist on the street but not in the YAML `[G3]`
Logged EDC 1.5 dCi Meganes (2018/2019/2020) "exact"-matched `megane4_k9k_110` — a variant
cataloged `transmission: manual`. The matcher's transmission narrowing is soft, so the ad
silently matched the manual row and *no gearbox part exists on that route at all*.
- [ ] Add `megane4_k9k_110_edc` (1.5 dCi + EDC/DC4) variant + fitment rows via the
      catalog pipeline (no hand-written YAML).
- [ ] Audit the "manual only in TR" notes in `volkswagen_golf_7.yaml`
      (esp. 1.6 TDI — DSG 1.6 TDIs are common on Sahibinden) and Clio 5 diesel rows.
- [ ] Re-check against `logs/analyses.jsonl` afterwards.

---

## P1

### B4 — Make the per-listing risk cap actually bind `[G1]`
`MAX_RISKS_PER_LISTING = 8` (`backend/api/main.py:52`) exempts confirmed/due strengths —
a DSG Golf was served **39 risks on 2026-07-13** (86 pre-cap). Rank confirmed/due by
consequence tier too and cap the total; consider a "top N + M more (collapsed)" response
shape so nothing is hidden, just deprioritized.

### B5 — Per-part claim budget: keep the chronics, archive the tail `[G1]`
896 claims across part files for 3 models (~300/model) is the volume problem at its
source. Rank claims within each part by consequence × independent-source count ×
specificity; keep the top ~15 servable, move the tail to a non-synced archive section.
Corroboration count *is* the "general chronic" signal. Respect the product principle
test in `CLAUDE.md` ("would the standard inspection catch this anyway?").

### B6 — Surface ad-vs-catalog transmission contradictions `[G3]`
`_narrow_by_transmission` (`backend/core/matcher.py:157`) falls back silently when the
ad's transmission matches no candidate. The resolver gates *claim direction* already;
what's missing is honesty: when ad tx ≠ every matched variant's tx and no same-engine
alternative row exists, set a degraded coverage note ("gearbox coverage missing for this
config") and log it as a catalog-gap signal (feeds B3).

### B7 — Coverage report + sync-time guard against empty part references `[G3]`
The dw5 hole (B2) shipped without any warning. Add `python -m backend.tools.coverage`:
variant → fitment parts → claim counts per part, flagging any non-`manual`
transmission_code (or engine_family) that resolves to a part file with 0 claims.
`sync.py` should print the same warning. This is the "would it recur?" fix for B2.

### B12 — Branch consolidation `[G4]`
- [ ] Merge `model-year-claim-windows` → `main` (serving overhaul A/B/C/E, scraper
      fixes, model-year windows, Golf 1.2 TSI).
- [ ] Then rebase `evidence-ledger-stage1` onto main and land it (B1).
- [ ] Delete stale worktree branches (`worktree-search-gate-fix`?) after checking.

---

## P2

### B8 — Rank sources before spending extraction tokens `[G2]`
`_select_capped` (`knowledge/auto.py:175`) keeps sources in discovery order. Score by
domain reliability + title specificity (engine/gearbox code mentions) so the ≤25 extracted
sources are the ones most likely to describe chronics, not the first 25 Exa returned.

### B9 — Year-window near-miss policy `[G3]`
A 2024 Megane 1.3 TCe listing no_matched ("No renault megane petrol for 2024" —
`year_to: 2023`). TR production/sales windows differ from EU. Decide: extend windows from
TR-market data, or match with a "year outside known window" note instead of nothing.

### B10 — Mine `no_match` logs as the onboarding priority queue `[G3]`
The logs already show real demand: Audi Q2/A4 (S-Tronic), BMW 3 Series, VW CC 1.4 TSI DSG,
Citroën Berlingo, Clio 4. Small tool that aggregates no_match rows by make/model/count so
onboarding order follows actual usage, not guesswork.

### B11 — Implement the AdBlue/SCR variant-scoping spec `[G3]`
Design spec written (`docs/superpowers/specs/2026-07-10-variant-emissions-scr-gate-design.md`,
434f9ec), not implemented. Emissions-hardware claims need an SCR/no-SCR variant dimension.

### B13 — Remaining design-flaw work (`docs/design_flaws.md`)
- Flaw 5: judge too weak → whack-a-mole patches (the ledger's verdict stage, B1,
  is the structural answer; confirm and close after merge).
- Flaw 6: pipeline keeps what sources mention, not what Kriko exists to show
  (product-value gate on the ledger branch + B5 close most of this).
