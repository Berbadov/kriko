# Kriko — Done

Completed work, newest first. Entries move here from `backlog.md` with date + commit.
Seeded 2026-07-16 from git history; older history lives in `git log` and
`docs/pipeline_postmortem.md`.

---

## 2026-07 (branch `model-year-claim-windows`, pending merge — backlog B12)

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
