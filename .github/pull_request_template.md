## What changed

<!-- One or two sentences. The commit messages carry the detail. -->

## Why

<!-- The problem, not the solution. If this fixes a bug, what produced the bug? -->

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
- [ ] **Layering holds.** No new import from `knowledge/` into `backend/` or `app/pipeline/`,
      and none from `backend/` into `app/pipeline/`. If a module needs something from the
      layer above, it is in the wrong layer — move the module.
      (`app/pipeline/tests/test_repo_invariants.py` enforces this.)
- [ ] **Claim selection clears the bar.** If this touches what gets surfaced: the
      claim is config-specific, predictable from the listing, and not something a
      standard pre-purchase inspection already catches.

### Verification

<!-- Paste real output. "Tests pass" without the numbers is not evidence. -->

- [ ] `python -m pytest` — no arguments, so `pytest.ini` picks up every testpath
- [ ] `npm test`
- [ ] Touched `deploy/Dockerfile` or a module the serving path imports?
      `docker build -f deploy/Dockerfile .` — the suite checks that every needed
      `knowledge/` module is copied, but not that the image actually builds.

```
paste test output here
```

### Tracking

- [ ] `backlog.md` / `done.md` updated — they are the single source of truth for status
