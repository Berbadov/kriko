---
name: Wrong or missing claim on a listing
about: Kriko showed a risk that doesn't apply, missed one that does, or showed noise
title: '[claim] '
labels: claim-quality
---

### Listing

- URL or listing ID:
- Make / model / generation:
- Engine + gearbox as the ad states them:
- Mileage and year:

### What Kriko showed

<!-- Paste the risk card text, or the /analyze response. `python -m ops.reports.analyses
     --last 20` lists recent requests; `python -m ops.reports.replay <analysis-id>`
     re-runs one through the current code and diffs it. -->

### What it should have shown

<!-- And why — a known failure pattern for this engine/gearbox at this mileage,
     a maintenance interval the ad doesn't address, etc. -->

### Which bar does this fail?

- [ ] **Not config-specific** — the claim is true of any car, not this variant
- [ ] **Not predictable from the ad** — needs the car inspected to know
- [ ] **Inspection already covers it** — a normal pre-purchase check finds this anyway
      (fluid levels, brake pads, compression, injector bench tests)
- [ ] **Missing** — a real, config-specific, mileage-predictable risk wasn't shown
- [ ] **Wrong variant** — correct claim, attached to the wrong engine/gearbox
