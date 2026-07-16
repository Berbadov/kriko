# Kriko — working notes for Claude

Kriko is a Chrome extension + FastAPI backend that surfaces reliability risks for used cars
on Sahibinden. See `docs/USAGE.md` (operation), `docs/INTERNALS.md` (architecture),
`docs/pipeline_postmortem.md` (knowledge-pipeline history).

## Task tracking

Open work lives in `backlog.md` (prioritized, with goals G1–G4 and evidence); finished
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
