## The request

<!-- Backlog id, and the reader's words quoted. See docs/DOCTRINE.md §1. -->
B### — "…"

**Done when:** <copied from the backlog entry>

## What was observed

<!-- Not "tests pass". What you saw happen, on which screen, and where:
     here (Linux, stand-in CLIs) or on the reader's Windows machine.
     docs/DOCTRINE.md §2. -->

**Checked on:** here / Windows

<!-- A screenshot of the screen named in the entry's "Where"
     (tools/walk.sh writes them to .walk/), or the journey check's output. -->

## What it does not do yet

<!-- Stated, never left for the reader to find. "Nothing" is an answer. -->

## Review against the request

<!-- A second agent that did not write this, reading only the backlog entry,
     the proof above and the diff: does it do what was asked, where it was
     asked? Paste its verdict. docs/DOCTRINE.md §5. -->

---

### Principle checks

Kriko's principles live in `CLAUDE.md`. Tick what applies, delete what doesn't —
an unticked box is fine if you say why.

- [ ] **No hardcoded car data.** No new Python dict/list of makes, models, engine
      codes or gearbox codes. Anything car-specific is derived from the catalog
      YAMLs. (Small closed vocabularies — fuel types, transmission technologies —
      are fine.)
- [ ] **Systemic, not per-model.** If this fixes a problem found on one car, it
      ships the mechanism that catches the same class for every car. A per-model
      patch is not a fix.
- [ ] **No human in the data path.** No review, sign-off or spot-check step added
      to extraction or scraping. Where a value can't be derived automatically, the
      system fails open: no claim, a gap in the coverage report, a logged signal.
- [ ] **Layering holds.** No new import from `src/kriko/` into `packs/`, `src/app/`, or
      `src/app/pipeline/`; none from `packs/cars/pipeline/` into `src/app/`; none from
      `packs/` into `src/app/pipeline/`. If a module needs something from the layer
      above, it is in the wrong layer — move the module.
      (`src/app/pipeline/tests/test_repo_invariants.py` enforces this.)
- [ ] **Claim selection clears the bar.** If this touches what gets surfaced: the
      claim is config-specific, predictable from the listing, and not something a
      standard pre-purchase inspection already catches.

### Verification

<!-- Paste real output. "Tests pass" without the numbers is not evidence. -->

- [ ] `python -m pytest` — no arguments, so `pytest.ini` picks up every testpath
- [ ] `npm test`
- [ ] If this touches `packaging/`, `tauri/`, or `src/app/sidecar.py`, the
      `desktop` workflow ran and all three runners are green.

```
paste test output here
```

### Before merge

- [ ] One request in this PR, and the branch is less than a day old (or rebased on `main`)
- [ ] `tools/walk.sh` shows no errors on the screens this touches
- [ ] Its journey check exists and passes (docs/DOCTRINE.md §4)

### Tracking

- [ ] `backlog.md` / `done.md` updated — they are the single source of truth for status
