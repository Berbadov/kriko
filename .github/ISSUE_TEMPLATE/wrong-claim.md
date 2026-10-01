---
name: Wrong or missing claim on a listing
about: Kriko showed a risk that does not apply, missed one that does, or showed noise
title: '[claim] '
labels: claim-quality
---

### The listing

- URL or listing id:
- The identity fields, exactly as the page stated them (the catalog decides
  which fields those are; see its `README.md`):
- Anything the page said that the listing's own context implies, such as age or
  usage:

### What Kriko showed

<!-- Paste the risk card text or the /api/analyze response. Recent check
     activity is on the Home and Activity screens and through
     `kriko operations`. -->

### What it should have shown

<!-- And why: a known failure pattern for this exact configuration, a service
     interval the listing never addresses, something the ad contradicts. -->

### Which bar does this fail?

The bar is the catalog's own, in its `research/principle.md`. Tick the ones
that apply, and say in one line which of its rules was broken.

- [ ] **Not specific to the configuration** — the claim is true of the whole
      category, not of this one
- [ ] **Not predictable from the listing** — it takes an inspection to know
- [ ] **A standard check already finds it** — the reader would learn this
      anyway
- [ ] **Missing** — a real, configuration-specific, predictable risk was not shown
- [ ] **Wrong subject** — a correct claim attached to the wrong product
