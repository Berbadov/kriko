## The request

<!-- Backlog id, and the reader's words quoted. See docs/DOCTRINE.md §1. -->
B### — "…"

**Done when:** <copied from the backlog entry>

## What was observed

<!-- Not "tests pass". What you saw happen, on which screen, and where:
     here (Linux, stand-in CLIs) or on the reader's Windows machine.
     docs/DOCTRINE.md §2. -->

**Checked on:** here / Windows

<!-- A screenshot of the screen named in the entry's "Where",
     or the journey check's output. -->

## What it does not do yet

<!-- Stated, never left for the reader to find. "Nothing" is an answer. -->

## Review against the request

<!-- A second agent that did not write this, reading only the backlog entry,
     the proof above and the diff: does it do what was asked, where it was
     asked? Paste its verdict. docs/DOCTRINE.md §5. -->

---

### Principle checks

Kriko's principles live in `CLAUDE.md`. Tick what applies, delete what does
not; an unticked box is fine if you say why.

- [ ] **No hardcoded category data.** No new Python list of product names,
      variants or component codes. Anything category-specific is derived from
      the catalog's own data files. A small closed vocabulary is fine: the rule
      covers data that grows with coverage, not fixed engineering categories.
- [ ] **Systemic, not per-product.** A problem found in one product ships the
      mechanism that catches that class for every product, present and future. A
      patch for one product is not a fix.
- [ ] **No human in the data path.** No review, sign-off or spot-check step
      added to extraction or scraping. Where a value cannot be derived
      automatically, the system fails open: no claim, a gap in the coverage
      report, a logged signal for an automated pass.
- [ ] **Layering holds.** No new import from `src/kriko/` into `packs/`,
      `src/app/` or `src/app/pipeline/`; none from a pack's `pipeline/` into
      `src/app/`; none from `packs/` into `src/app/pipeline/`. A module that
      needs something from the layer above is in the wrong layer: move it.
      (`src/app/pipeline/tests/test_repo_invariants.py` enforces this.)
- [ ] **Claim selection clears the pack's bar.** If this touches what gets
      surfaced, the claim is specific to the configuration, predictable from
      what the listing already says, and not something a standard check already
      finds. The bar is the pack's own, in its `research/principle.md`.
- [ ] **No category or vendor in a document or in the UI.** Docs name no
      product type and no model or agent product; `ui/src` names no catalog
      vocabulary. Lists are read at runtime, never typed.

### Verification

<!-- Paste real output. "Tests pass" without the numbers is not evidence. -->

- [ ] `python -m pytest` — no arguments, so `pytest.ini` picks up every testpath
- [ ] `npm test`
- [ ] If this touches `packaging/`, `tauri/` or `src/app/sidecar.py`, the
      `desktop` workflow ran and all three runners are green.

```
paste test output here
```

### Before merge

- [ ] One request in this PR, and the branch is less than a day old (or rebased on `main`)
- [ ] Its journey check passes, or (until `tools/journeys/` exists, B191) the
      steps and the end result are walked by hand above (docs/DOCTRINE.md §4)

### Tracking

- [ ] `backlog.md` updated: the item leaves it, or its "Found" lines record
      what you measured. The commit message says what was observed, so no
      document has to carry a second status list.
