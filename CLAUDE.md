# Kriko — working notes for Claude

Kriko is a Chrome extension + FastAPI backend that surfaces reliability risks for used cars
on Sahibinden. See `docs/USAGE.md` (operation), `docs/INTERNALS.md` (architecture),
`docs/pipeline_postmortem.md` (knowledge-pipeline history).

## Task tracking

Open work lives in `backlog.md` (prioritized, with goals G1–G5 and evidence); finished
items move to `done.md` with date + commit. Check the backlog before starting work and
keep both files current — they are the single source of truth for project status.

## Product principle — what Kriko surfaces (READ THIS BEFORE TOUCHING CLAIM SELECTION)

Kriko's value is **the config- and mileage-specific known risks a buyer cannot cheaply get
from the standard pre-purchase inspection** — what to worry about for *this* specific car,
*before* they even book the expert. Everything we show should clear that bar.

**Surface a claim when it is:**
- **Specific to this variant/config** — engine code, gearbox type (e.g. dual-clutch/automated
  manual vs torque-converter), fuel, market. Not advice that applies to any car.
- **Predictable from the listing data** (mileage, year, transmission, fuel) *without*
  inspecting the car — a known weak point or failure pattern the odometer/age implies.
- **Maintenance-interval / "unless recently done"** — items due by a km or time interval (cam
  belt, major service, clutch/wear parts on high mileage). If the listing gives no evidence the
  work was done, **the omission itself is the signal** — flag it as "due unless the ad/seller
  proves otherwise".
- **High-consequence or expensive** — structural/known-weak-point failures and costly systems
  (emissions hardware, dual-clutch/mechatronics, turbo, timing components), not cosmetic or
  trivial.

**Do NOT surface (low value — drop or heavily downrank):**
- Generic dashboard-warning-light items ("ABS light", "ESP fault") or anything true of all cars.
- Anything the standard pre-purchase mechanic inspection already catches as routine — fluid
  levels/leaks, brake-pad wear, injector bench tests, compression. Buyers already pay an expert
  for these; repeating them is noise, not signal.

The test for any candidate claim: *"Would a buyer learn this from a normal pre-purchase
inspection anyway?"* If yes, it's low value. *"Is it specific to this car's
engine/gearbox/mileage and predictable from the ad?"* If yes, it's what we exist to show.

> Status: the extraction/gating pipeline currently keeps whatever sources mention (including
> generic warning-light items), so live output does **not** yet fully reflect this principle.
> Aligning it — mileage-gated claims, explicit maintenance-interval/"not mentioned in ad"
> claims, and an "inspection already covers this" filter — is open work. Honour this principle
> in any claim-selection change.

## Scalability principle — no hardcoded car data (READ THIS BEFORE ADDING A MAKE/MODEL/CODE LIST)

Kriko must generalize to thousands of cars, not the handful onboarded today. Hardcoding
specific makes, models, engine codes, or gearbox codes as Python constants is a
**scalability bug, not a shortcut** — every hardcoded list is a manual edit someone has
to remember to make for every new car, and history here shows that edit gets forgotten
(`SIBLING_CODE_FAMILIES` going stale was Flaw 1 in `docs/design_flaws.md`; `normalize.py`'s
`_MAKE_MAP`/`_MODEL_MAP` were the same failure mode).

**Before adding a fixed list of car-specific values, ask:** can this be *derived* from the
catalog (`backend/data/**/*.yaml`) instead of hand-enumerated? `catalog_code_manufacturers()`
in `knowledge/stoplists.py` is the reference pattern — it reads manufacturer-per-code
straight off the part YAMLs, so a new part is covered the moment its stub exists, with no
separate registration step to forget.

**Exception:** small, genuinely closed vocabularies (fuel types, transmission
technologies, a handful of spelling/abbreviation aliases) are fine as constants — this
rule is about data that grows with car *coverage*, not fixed engineering categories.

Onboarding a new car model must never require a manual Python dict/list edit in
`normalize.py` or `stoplists.py` — only new YAML data, ideally pipeline-generated rather
than hand-authored (see `docs/USAGE.md`'s onboarding steps).

## Generalization principle — systemic fixes only, no per-model patches

The catalog must scale to thousands of models, so **per-model fixes do not exist**:
no per-model research runs, no per-model YAML audits, no per-model spot-checks, no
one-off patches that only touch one car's row. Every fix ships as the *mechanism*
that catches the same class of problem for every current and future car. When a
problem shows up on one car, ask **"how would we catch this automatically for every
car, and how will it be fixed without a person?"** — and ship that, or cancel the
feature (see the automation principle).

The mechanism should be catalog-derived or log-derived (validation, coverage report,
telemetry, auto-remediation), never another hand-enumerated list and never a manual
step — see the scalability and automation principles below. When a per-model problem
is found, it is a *test case* for the mechanism, not a fix target. Tracked as backlog
B19 (auto-remediation loop); B2/B3's manual steps were cancelled there 2026-08-03.

## Automation principle — no human in the data path (READ THIS BEFORE ADDING A REVIEW/SIGN-OFF STEP)

Kriko runs unattended. Extraction and scraping never wait for human verification,
spot-checks, or sign-off — neither per datum nor per model. Where a value cannot be
derived automatically (from the ledger, the catalog pipeline, or a deterministic
rule), the system **fails open**: emit no claim, surface the gap in the coverage
report, and log a signal that feeds an automated pass. A manual step that "someone
should review" is a bug, not a process — the backlog's HUMAN DECISION #6/#7 were
retired this way 2026-08-03 (B17 dropped, B11 derives-or-fails-open).

One-time *policy* decisions are the only allowed human decisions — source
licensing/ToS (backlog B18, HUMAN DECISION #5), market coverage, source retirement —
never per-car or per-datum review. When a per-model problem appears, fix it with a
mechanism that runs for all models (generalization principle) or cancel the feature;
never add a human verification step to the pipeline.

## Layering principle — dependencies flow one way (READ THIS BEFORE ADDING AN IMPORT ACROSS PACKAGES)

Kriko is three layers. Each may import from the layers below it, never from the
layers above:

```
ops/        operator layer — hub, mcp, reports, auto, process, ledger_run,
            swap, remediate, panel. Drives and inspects everything below.
backend/    serving layer — sync ETL, api, resolver, db, matcher.
knowledge/  catalog layer — extraction, catalog, parts, sources, ledger.
            Imports nothing above it.
```

**A deferred import (one written inside a function body) that points *upward* is
the smell.** It means someone hit `ImportError: partially initialized module` and
pushed the import down to runtime rather than fixing the layering. Before
2026-08-21 there were 11 of them, all pointing from `knowledge/` into `backend/`,
because `backend/tools/` held operator tooling the pipeline needed. A deferred
import pointing *downward* is fine — that is a startup-cost decision.

Two greps must return nothing (tests excluded — an end-to-end test may span layers):

```bash
grep -rnE "^[[:space:]]*(from|import) (backend|ops)" --include='*.py' knowledge/ | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) ops"            --include='*.py' backend/   | grep -v /tests/
```

If a module needs something from the layer above, it is in the wrong layer — move
the module, don't add the import. New CLI drivers and anything that spans layers
belong in `ops/`. See `docs/INTERNALS.md` for the diagram and
`docs/superpowers/specs/2026-08-21-codebase-organisation-design.md` for the
reasoning.

## Documentation map

| Doc | What it's for | Status |
|-----|---------------|--------|
| `README.md` | Project overview, quickstart, supported cars | current |
| `CLAUDE.md` | Principles + working rules for Claude sessions | current |
| `CONTRIBUTING.md` | Branches, commits, test gates, what CI checks | current |
| `backlog.md` / `done.md` | Task tracking — single source of truth for status | current |
| `docs/USAGE.md` | Operating the stack + growing the knowledge base | current |
| `docs/INTERNALS.md` | Mechanism-level architecture reference | current (verify details against code) |
| `docs/design_flaws.md` | 2026-07-04 audit; Flaws 1–4 fixed, 5–6 → backlog B13 | reference |
| `docs/overhaul_plan.md`, `docs/claim_relevance_plan.md` | Claim-quality roadmap/specs | reference |
| `docs/pipeline_postmortem.md` | Early pipeline history | historical |
| `docs/historical/` | Pre-part-centric era (`handover.md`, `SCAFFOLD.md`) + superseded 2026-07 designs/plans (`thoughts/`) | historical — do not follow |
