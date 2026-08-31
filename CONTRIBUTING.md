# Contributing to Kriko

The principles that govern *what* Kriko does live in [`CLAUDE.md`](CLAUDE.md) and
are not repeated here. This file covers the mechanics: branches, commits, tests,
and what CI checks.

## Before you start

Read [`backlog.md`](backlog.md). It and [`done.md`](done.md) are the single source
of truth for project status — not issues, not this file. Finished work moves from
one to the other with a date and a commit hash.

## Branches

Branch off `main`. Names describe the work, not the ticket:

```
feat/agent-model-onboarding
observability-analyses-log
worktree-search-gate-fix
```

Nothing is pushed or merged to `main` without the author asking for it.

## Commits

Conventional commits with a scope, as the history already uses:

```
feat(hub):      a new capability
fix(hub):       a defect, with the cause named
refactor(ops):  structure changes, behaviour identical
docs:           documentation only
chore(git):     tooling, ignores, deps
perf(hub):      measured speedups — say what got faster and by how much
```

Write the body for someone reading `git log` in six months with no memory of the
session. Name the cause, not just the symptom: *"the picker armed an onboarding
run that could not succeed"* beats *"fix picker bug"*. Explain what you decided
not to do when it isn't obvious.

## Tests

```bash
python -m pytest      # all tests — no arguments
npm test              # extension scraper + panel
```

**Run `pytest` with no arguments.** `pytest.ini` pins `testpaths`; naming
directories by hand is how the suite quietly shrank to 576 of 761 tests when
`app/pipeline/` was added, skipping every test in `app/pipeline/tests` without failing.

The suite must pass with **no API keys and no `.env`**. A test that needs a key is
reaching the network and belongs behind a marker — CI runs with no secrets, on
purpose.

If you move a module used by the serving path, also run the import and pack checks:

```bash
python -c "import app.web.app, kriko.lookup, kriko.store"
python -m pytest src/app/pipeline/tests/test_repo_invariants.py
```

The serving path is the local FastAPI app backed by the SQLite pack store. The
pipeline remains separate from serving, so importing `app.web.app` must not load
`app.pipeline` or the LLM extraction stack.

## Checking for dead code

A grep for a dotted module path (`packs.cars.pipeline.catalog.model_state`)
misses `from packs.cars.pipeline.catalog import model_state` — the import form
most test files actually use — and will falsely report a module as dead. This
cost a wasted task: see `docs/superpowers/plans/2026-08-29-simplification-pass.md`,
Task 9, for the working query (all import styles, no test-directory filter,
plus entry-point and doc-mention detection) and its finding that the repo
currently has no dead modules. Re-run that query rather than a plain grep
before deleting anything on the strength of "nothing imports this."

## Architecture: engine, packs, and interfaces

Dependencies flow one way. Each layer may import from the layers below it, never
from the layers above:

```
src/app/             CLI, local web dashboard, MCP server
src/app/pipeline/    ledger and remediation orchestration
src/kriko/           generic store, ledger/extract, lookup, ranking, research
packs/                category data, builders, vocabulary, coverage and pack pipelines
extension/            thin browser client; no product/site interpretation
```

If a module needs something from the layer above, **the module is in the wrong
layer — move it, don't add the import.** Interfaces belong in `src/app/`, pipeline
drivers in `src/app/pipeline/`, generic engine code in `src/kriko/`, and category
data in `packs/<category>/`.

A deferred import (one written inside a function body) that points *upward* is the
smell: it means someone hit `ImportError: partially initialized module` and pushed
the import to runtime instead of fixing the layering. Pointing *downward* it is
just a startup-cost decision, and fine.

`src/app/pipeline/tests/test_repo_invariants.py` enforces this, so a violation fails
the suite rather than waiting to be noticed in review.

## What CI checks

[`.github/workflows/ci.yml`](.github/workflows/ci.yml), on every PR:

| Job | What it catches |
|---|---|
| `python` | the full suite, plus the layering and testpaths invariants |
| `extension` | scraper and hub-console tests under jsdom |

There is no docker-build job — there is currently no Dockerfile or `deploy/`
directory in the repo at all, so there is nothing for a build job to build.
Package boundaries and test-path coverage are still checked statically, in
milliseconds, by `src/app/pipeline/tests/test_repo_invariants.py` as part of
the normal suite. If a Dockerfile comes back, add a real build step (or an
equivalent static check) alongside it — don't let this paragraph go stale
again.

CI runs with no secrets. `npm install` rather than `npm ci`, because
`package-lock.json` is gitignored — commit the lockfile if you want reproducible
installs, and switch that one line.
