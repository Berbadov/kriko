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
python -m pytest      # all 761 — no arguments
npm test              # extension scraper + hub console
```

**Run `pytest` with no arguments.** `pytest.ini` pins `testpaths`; naming
directories by hand is how the suite quietly shrank to 576 of 761 tests when
`ops/` was added, skipping every test in `ops/tests` without failing.

The suite must pass with **no API keys and no `.env`**. A test that needs a key is
reaching the network and belongs behind a marker — CI runs with no secrets, on
purpose.

If you touched `deploy/Dockerfile`, or moved a module the serving path imports,
also run:

```bash
docker build -f deploy/Dockerfile -t kriko-check .
docker run --rm kriko-check python -c "import backend.api.main, backend.core.resolver, backend.sync"
```

That Dockerfile copies a deliberate stdlib-only slice of `knowledge/` to keep the
LLM dependencies off the serving image, so a module move can produce an image that
builds clean and dies at request time. Tests run against the full source tree and
cannot see it. CI does this build for you; running it locally saves a round trip.

## Architecture: three layers

Dependencies flow one way. Each layer may import from the layers below it, never
from the layers above:

```
ops/        hub, mcp, reports, auto, process, ledger_run, swap, remediate, panel
backend/    sync ETL, api, resolver, db, matcher
knowledge/  extraction, catalog, parts, sources, ledger — imports nothing above it
```

If a module needs something from the layer above, **the module is in the wrong
layer — move it, don't add the import.** New CLI drivers and anything spanning
layers belong in `ops/`.

A deferred import (one written inside a function body) that points *upward* is the
smell: it means someone hit `ImportError: partially initialized module` and pushed
the import to runtime instead of fixing the layering. Pointing *downward* it is
just a startup-cost decision, and fine.

`ops/tests/test_repo_invariants.py` enforces this, so a violation fails the suite
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
computes the transitive closure of `knowledge/` imports reachable from `backend/`
and asserts `deploy/Dockerfile` copies each one. That runs in milliseconds as part
of the normal suite.

It cannot catch everything a real build would — a broken `pip install`, a bad base
image, a missing data file — so still build locally when you change the Dockerfile.

CI runs with no secrets. `npm install` rather than `npm ci`, because
`package-lock.json` is gitignored — commit the lockfile if you want reproducible
installs, and switch that one line.
