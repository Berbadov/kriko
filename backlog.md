# Kriko — Backlog

Prioritized open work. Read `CLAUDE.md` (product, scalability, automation principles)
before picking anything up. When an item is finished, move it to `done.md` with the
date and commit hash.

- **P0** — actively hurting buyers or blocking everything else
- **P1** — the next round of high-leverage work
- **P2** — real, but can wait

Evidence for many items comes from production logs: `logs/analyses.jsonl`
(`python -m backend.tools.analyses --last 20`).

---

## Goals (2026-08)

**G1 — Quality over quantity.** A buyer sees at most ~8 risks, and they are the
*general chronics*: config-specific, high-consequence, multi-source-corroborated issues.
Today a DSG Golf gets 39–86 cards; nobody reads 39 cards.

**G2 — Cut pipeline cost per car by ~10×.** Classification spend must be budgeted,
cached, and reported. **(Landed 2026-07-22 — B1 closed.)**

**G3 — No silent coverage holes.** If a car is automatic, its gearbox chronics must show.
Ad-vs-catalog contradictions and empty part files must be *visible* (coverage_state,
coverage report), never a quiet zero.

**G4 — One trunk.** **(Done 2026-07-22 — all branches merged, worktrees pruned.)**

**G5 — Fully automated pipeline. Zero human-in-the-loop** *(new 2026-08-03)*.
Extraction and scraping run unattended; nothing in the data path — evidence, catalog
rows, gates, sources — may wait for human verification, spot-checks, or sign-off.
One-time *policy* decisions are allowed (market coverage, source licensing); per-car
and per-datum review is not. Where a value cannot be derived automatically, the system
**fails open** (no claim, no guess) and logs the gap; the log drives the next automated
pass, never a human TODO. This retires HUMAN DECISION #6/#7 (B17/B11) and all
"manual audit/spot-check" backlog steps.

**Cross-cutting rule — systemic only** *(2026-08-03; replaces the patch-and-mechanism
pairing)*. The catalog grows to thousands of models, so *no per-model fixes exist*.
Every fix ships as a mechanism that runs for all cars (coverage report, contradiction
surfacing, auto-remediation). Per-model manual steps (research runs, YAML audits,
spot-checks) are cancelled, not deferred — see B19, which absorbs B2/B3.

---

## P0

### B16 — Catalog swap: serve the ledger export instead of legacy part YAMLs `[G1][G2]`
The ledger export (knowledge/ledger_export/, 568 claims) is acceptance-ready per the
parity report; the serving-gate schema gap is closed. Remaining:
- [x] Export rewritten to the part-dict schema with serving-gate fields grounded at
      export. **Done 2026-08-02.** Regenerated 2026-08-03 from the ledger (19 parts,
      536 claims — the checked-in copy had gone stale; the fresh export covers
      dq200/dq250/dq381/ea211/ea888/k9k) and each file now carries
      `legacy_part_ids` (which legacy power-split files it supersedes —
      pipeline-derived, no hand list).
- [x] **Swap mechanism landed 2026-08-03** (`knowledge/ledger/swap.py`):
      `plan` derives the legacy→merged fitment remap mechanically
      (power-collapse rule via the export's `legacy_part_ids`), classifies every
      legacy file (superseded/retained), counts fitment edits; `apply` writes the
      export into `parts/<type>/`, deletes superseded power-split files,
      overwrites non-split ids in place, rewrites fitment axes (revertible, and
      default off the real catalog — runs on a copy unless `--in-place`);
      `check` is the **automated acceptance gate** (no human sign-off):
      (a) parity: every legacy claim absent from the export must be attributable
      to a named gate — "never extracted/ingested/no matching evidence" are
      LOST and fail; (b) serving: the 43-listing baseline replayed against the
      current catalog AND the post-swap catalog on fresh DBs — the swap's own
      delta, with a monotonicity rule (a listing that matches today must still
      match after the swap); (c) coverage: post-swap must not add findings.
      Tests: `knowledge/tests/test_ledger_swap.py`.
- [ ] **Live gate state (2026-08-03): FAIL, blocked on API funding — data
      catch-up is in the ledger.** The remediate loop ran twice (coverage gaps
      dw5/dw6 researched — 10/16 claims now exported from them; +50 pages
      ingested, including every source URL cited by parity-lost claims —
      `lost_source_urls`/`ingest_lost_sources` in `remediate.py`); parity
      re-classified sourceless legacy claims as unverifiable provenance (331
      claims with zero sources can't be reproduced by any pipeline and the
      ledger's ≥1-source bar would never serve them) — lost dropped 124 → 49
      (23 never-ingested pages + 26 no-matching-evidence, all now ingested).
      The second pass hit `Insufficient Balance` on the DeepSeek API —
      extraction/verdicts for the 50 new docs are pending and resumable.
      Re-run `python -m knowledge.ledger.run remediate --max-usd 2.0` once
      funded; when parity-lost hits 0, `python -m knowledge.ledger.swap check`
      decides the swap.
- [ ] After swap passes: replay serving baseline, retire judge.py gates /
      promote.py / purge_*.py / translate_claims.py, drop the B16 swap-in
      scaffolding.

### B11 — Emissions/SCR values: derive or fail open — no sign-off `[G3][G5]`
The mechanism landed 2026-08-02 (`Variant.emissions`/`aftertreatment` +
`_scr_compatible`/`_default_aftertreatment` in `backend/sync.py`, `write_variants.py`
support, `test_scr_gate.py`). The old HUMAN DECISION #7 sign-off is cancelled under G5:
- [x] Hand-typed Megane 4 values removed (2026-08-03) — all variants fail open
      again (no SCR grounding), which is strictly safer than the unverified
      `scr` value on `megane4_k9k_110_edc` for 2016–18 cars.
- [x] Year-split row support landed in `write_variants.py` (2026-08-03) —
      `emissions` may be a list of year-bounded segments; each segment emits its
      own variant row (`{id}__{emissions}` suffix), aftertreatment derived per
      segment, windows validated against the trim. Tests:
      `knowledge/tests/test_write_variants_emissions.py`.
- [x] Coverage report lists diesel variants with no emissions value
      (2026-08-03) — new `variant_no_emissions` finding kind
      (`backend/tools/coverage.py`); the gap is visible, never a quiet wrong
      value.
- [ ] Derive emissions values from sources via the ledger for Clio 5 + Golf 7 +
      Megane 4 (evidence path, then `write_variants.py` regen). Until then,
      fail-open stands and the coverage report shows exactly which variants
      lack data.

### B19 — Auto-remediation loop: coverage gaps fix themselves `[G3][G5]` *(absorbs B2/B3)*
The detection mechanisms exist: B7's coverage report (`zero_claim_part`,
`auto_variant_no_tx_part`, `backend/tools/coverage.py`) and B6's ad-vs-catalog
contradiction surfacing. The former B2/B3 manual steps are cancelled; this loop
replaces them:
- [x] **Driver landed 2026-08-03** — `python -m knowledge.ledger.run remediate`
      (`knowledge/ledger/remediate.py`): turns every part-level finding
      (zero_claim/missing part, auto-variant-without-tx-part) into an unattended
      acquire → extract → resolve → cluster → verdict → export pass. Budget-capped
      (`--max-usd`), resumable (existing stage guarantees), `--dry-run` prints the
      plan, empty plan = no spend. Every run appends `logs/remediation.jsonl`
      (findings, parts, rows gained, spend). Findings carry `part_id`/`axis`
      metadata for the loop (`coverage.Finding`); `orphan_part` and
      `variant_no_emissions` are deliberately not part-driven research.
      Tests: `knowledge/tests/test_ledger_remediate.py`, coverage metadata tests.
- [ ] First live instances the loop must fix: `dw5`/`dw6` (empty EDC
      transmission parts) + the other 7 empty Megane 4 parts — a scheduled
      remediate run with EXA/DeepSeek credentials resolves them; the B16 swap
      then makes the export the serving catalog and completes the loop.
- [ ] "Manual only in TR" notes in `volkswagen_golf_7.yaml` (esp. 1.6 TDI DSG) and
      Clio 5 diesel rows: no manual audit; contradiction + coverage signals drive any
      regen. (Transmission coverage is already enforced by B6/B7 checks.)

### B17 — Official recall feeds: DROPPED `[G3]` *(HUMAN DECISION #6 resolved 2026-08-03)*
All official sources are dropped — TR SGM, EU Safety Gate, and NHTSA. TR SGM was
already blocked by an anti-bot challenge; the decision now removes the whole class.
The 50 ingested EU Safety Gate rows stay in `ledger.db` as history, but:
- [ ] Retire `knowledge/ledger/feeds/` ingesters and their `run.py feeds` wiring
      (remove, or leave dormant — they must not run).
- [ ] Recall coverage ends here unless a non-official automated source is later
      onboarded (B18-adjacent); no human recall checking exists.

---

## P1

### B5 — Per-part claim budget: keep the chronics, archive the tail `[G1]`
896 claims across part files for 3 models (~300/model) is the volume problem at its
source. Rank claims within each part by consequence × independent-source count ×
specificity; keep the top ~15 servable, move the tail to a non-synced archive section.
Corroboration count *is* the "general chronic" signal. Respect the product principle
test in `CLAUDE.md` ("would the standard inspection catch this anyway?"). Fully
automated — ranking is a deterministic pipeline step, no review.

### B9 — Year-window near-miss policy: ADOPTED `[G3][G5]`
A 2024 Megane 1.3 TCe listing no_matched ("No renault megane petrol for 2024" —
`year_to: 2023`). Policy (no further decision): a listing outside the known window
still matches the variant, carries a "year outside known window" note in the
response, and logs a demand signal for the catalog. Windows may later be extended
from TR-market data — also automatically, via the demand miner (B10).

---

## P2

### B13 — Remaining design-flaw work (`docs/design_flaws.md`)
- Flaw 5: judge too weak → whack-a-mole patches. The ledger's verdict stage is now on
  `main` (B1, 2026-07-22) — closes for the pipeline; the *served* catalog inherits the
  fix at the B16 catalog swap.
- Flaw 6: pipeline keeps what sources mention, not what Kriko exists to show. The
  deterministic product-value gate is on `main`, dropping ~230 claims in the export;
  closes at B16 + B5.

### B14 — Documentation audit: docs must match the code
2026-07-16 pass fixed the worst drift. Remaining (all one-time doc work, allowed
under G5):
- [ ] Verify every INTERNALS.md mechanism section against current code — it predates
      the part-centric flow in places.
- [ ] USAGE.md §5/§7 still document the model-centric legacy mode prominently;
      restructure around the part-centric flow.
- [ ] Decide whether `docs/handover.md` earns a rewrite or deletion (B12 landed).

### B18 — Source adapter ToS decisions: wire recalls/specialists/forums into the pipeline `[G2]`
Three source adapters exist (`knowledge/sources/recalls.py`, `specialists.py`,
`forums.py`) with working `fetch()` methods, blocked on **HUMAN DECISION #5** —
the only remaining human decision, and the only allowed kind under G5: a one-time
licensing/policy gate, not per-car review. Once confirmed, wiring into
`knowledge/ledger/acquire.py` (with a `--sources` flag) is fully automated. Note:
with B17, the official recalls adapter is retired — specialists/forums remain.

---

## Human decisions — status under G5

| # | Topic | Status |
|---|-------|--------|
| 5 | Source ToS (B18) | **Open** — one-time policy, the only allowed kind under G5 |
| 6 | TR SGM recall feed | **Resolved 2026-08-03** — dropped with all official recall sources (B17) |
| 7 | B11 emissions sign-off | **Resolved 2026-08-03** — cancelled; derive or fail open (G5) |
