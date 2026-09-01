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
python -m pytest        # all tests — no arguments
npm test                # extension scraper + panel
npm --prefix ui test    # the dashboard's Svelte components
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

## The frontend

`ui/` is the Svelte + Vite source; `src/app/web/static/` is its **committed build
output**. The wheel ships the bundle, so `pip install kriko` serves a working UI with no
Node toolchain — which is only true if the committed output matches the source.

After changing anything under `ui/src/`:

```bash
npm --prefix ui test
npm --prefix ui run build      # rewrites src/app/web/static/
git add ui src/app/web/static
```

CI rebuilds and fails on a dirty diff, so a forgotten rebuild is caught rather than
shipped. `ui/package-lock.json` is committed (overriding the repo-wide ignore) because
that check needs the same dependency versions to produce the same asset hashes.

`ui/src/` must contain **no pack vocabulary** — no `make`, `model`, `fuel` and so on.
Every form field comes from `/api/identity-keys/{pack_id}` and
`/api/packs/{pack_id}/vocabulary` at runtime. `test_ui_contains_no_pack_vocabulary` in
`src/app/pipeline/tests/test_repo_invariants.py` enforces it: the engine's
domain-freedom has to survive the trip to the DOM, and TypeScript is where it is
easiest to break unnoticed.

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
| `ui` | Svelte component tests, and a rebuild that fails if the committed bundle is stale |

There is no docker-build job, and there will not be one: Kriko is a standalone
app, not a deployment. `test_the_app_stays_standalone` fails if a Dockerfile, a
compose file, a `deploy/` directory, or a Postgres driver returns — so this
paragraph cannot go stale without the suite going red. The `desktop` workflow
builds the actual shipping artifact (four installers on three runners) and runs
`packaging/smoke_sidecar.py` against the frozen binary before bundling it.

CI runs with no secrets. The `extension` job uses `npm install` rather than `npm ci`,
because the root `package-lock.json` is gitignored. The `ui` job uses `npm ci`: its
lockfile *is* committed, because the stale-bundle check compares a fresh build against
the committed one and a floating dependency version would change an asset hash and fail
the build for no reason.
