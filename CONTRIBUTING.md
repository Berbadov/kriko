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
python -m pytest app/pipeline/tests/test_repo_invariants.py
```

The serving path is the local FastAPI app backed by the SQLite pack store. The
pipeline remains separate from serving, so importing `app.web.app` must not load
`app.pipeline` or the LLM extraction stack.

## Architecture: engine, packs, and interfaces

Dependencies flow one way. Each layer may import from the layers below it, never
from the layers above:

```
app/             CLI, local web dashboard, MCP server
app/pipeline/    ledger and remediation orchestration
kriko/           generic store, ledger/extract, lookup, ranking, research
packs/           category data, builders, vocabulary, coverage and pack pipelines
extension/       thin browser client; no product/site interpretation
```

If a module needs something from the layer above, **the module is in the wrong
layer — move it, don't add the import.** Interfaces belong in `app/`, pipeline
drivers in `app/pipeline/`, generic engine code in `kriko/`, and category data in
`packs/<category>/`.

A deferred import (one written inside a function body) that points *upward* is the
smell: it means someone hit `ImportError: partially initialized module` and pushed
the import to runtime instead of fixing the layering. Pointing *downward* it is
just a startup-cost decision, and fine.

`app/pipeline/tests/test_repo_invariants.py` enforces this, so a violation fails the suite
rather than waiting to be noticed in review.

## What CI checks

[`.github/workflows/ci.yml`](.github/workflows/ci.yml), on every PR:

| Job | What it catches |
|---|---|
| `python` | the full suite, plus the layering, testpaths and Dockerfile invariants |
| `extension` | scraper and hub-console tests under jsdom |

There is no docker-build job. The repo is private, so Actions minutes are billed,
and an image build was 3-5 of the ~10 minutes per push. What it guarded is checked
statically instead: `test_dockerfile_copies_every_knowledge_module_the_serving_path_imports`
checks the package boundaries and test-path coverage. Those checks run in
milliseconds as part of the normal suite.

It cannot catch everything a real build would — a broken `pip install`, a bad base
image, a missing data file — so still build locally when you change the Dockerfile.

CI runs with no secrets. `npm install` rather than `npm ci`, because
`package-lock.json` is gitignored — commit the lockfile if you want reproducible
installs, and switch that one line.
