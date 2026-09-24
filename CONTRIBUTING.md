# Contributing to Kriko

The principles that govern *what* Kriko does live in [`CLAUDE.md`](CLAUDE.md) and
are not repeated here. This file covers the mechanics: branches, commits, tests,
and the gate they run behind.

## The loop

Three commands. Everything else is detail.

```bash
tools/setup.sh           # get a working tree (idempotent — run it whenever something feels wrong)
tools/gate.sh            # everything the branch used to be checked for
python tools/bump.py X.Y.Z   # set the version, in all five places it lives
```

**`tools/setup.sh`** is the one that did not exist until 2026-09-13, and its
absence cost a fresh session six separate discoveries before `pytest` told the
truth: that the tree needs Python 3.14; that `requirements.lock` is the closure
the installer freezes and installing anything else makes the suite's central
claim false; that `-e .` is what makes `app.version` report the tree's version;
that the `pipeline` extra is optional for *serving* and not for the *suite*
(without it six modules will not import); that `ui/` and the repo root have
separate `node_modules`; and that `src/*.egg-info` goes stale and fails a
version test for a reason that is about your directory rather than your change.
None of that is interesting, so it lives in the script.

It never touches `~/.kriko`. Your store, history and keys are not development
environment, and a setup script that resets them is one people are afraid to run.

**`python tools/bump.py --show`** prints the version from all five places and
exits non-zero if they disagree — four committed files plus the *installed*
distribution's metadata, which is what `/api/health` actually reports. The fifth
is why a `sed` never finished the job: a tree at 0.8.1 with a 0.8.0 editable
install serves 0.8.0. It does not commit and does not tag; a tool that tags as a
side effect of an edit cuts releases by accident.

**The MCP server** (`.mcp.json`) runs `.venv/bin/python -m app.sidecar --mcp`,
relative to the repository root, so it works in any checkout `tools/setup.sh`
has been run in. It used to name one contributor's absolute home directory and
failed to connect everywhere else.

## Before you start

Read [`backlog.md`](backlog.md). It and [`done.md`](done.md) are the single source
of truth for project status — not issues, not this file.

Then read [`docs/DOCTRINE.md`](docs/DOCTRINE.md): how a request is written down,
what "done" means, which test proves what, and what a PR must carry as proof. Finished work moves from
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
reaching the network and belongs behind a marker — the gate runs with no secrets,
on purpose.

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

`tools/gate.sh ui` rebuilds and fails on a dirty diff, so a forgotten rebuild is
caught rather than shipped. `ui/package-lock.json` is committed (overriding the repo-wide ignore) because
that check needs the same dependency versions to produce the same asset hashes.

`ui/src/` must contain **no pack vocabulary** — no `make`, `model`, `fuel` and so on.
Every form field comes from `/api/identity-keys/{pack_id}` and
`/api/packs/{pack_id}/vocabulary` at runtime. `test_ui_contains_no_pack_vocabulary` in
`src/app/pipeline/tests/test_repo_invariants.py` enforces it: the engine's
domain-freedom has to survive the trip to the DOM, and TypeScript is where it is
easiest to break unnoticed.

### Pressing every button: `tools/walk.sh`

The component tests render one piece with a stubbed fetch, so they cannot see a
screen that takes six seconds or a button that does nothing. `tools/walk.sh`
can. It starts the app on a throwaway home (never `~/.kriko`) with the
first-party packs built fresh, opens every screen the rail lists in a headless
Chromium, presses every button on each (from a fresh load each time), and
writes `.walk/walk.md`: per screen the load time, console errors and failed or
`>= 400` requests; per button whether it errored, never settled, was slow
(`KRIKO_WALK_SLOW_MS`, default 1000) or changed nothing at all.

```bash
tools/walk.sh             # every screen, ~15 minutes
tools/walk.sh agents      # only addresses containing "agents"
KRIKO_WALK_REAL_CLIS=1 tools/walk.sh agents   # your own claude/agy/opencode
```

By default `tools/walk/bin` goes ahead of `PATH`: stand-in `claude`, `agy`,
`opencode`, `copilot` and `vibe` that answer instantly and spend nothing, and
whose `models` take two seconds like the real ones. Buttons named quit, uninstall, delete, remove,
forget, reset, revoke or undo are listed and never pressed. It needs Playwright
(`npm i -g playwright && npx playwright install chromium`); it is not a
dependency of the repo and not part of the gate.

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
src/app/             CLI, local web dashboard, MCP server, operator TUI
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

## The gate

```bash
tools/gate.sh            # everything, in one command
tools/gate.sh py         # just the Python suite
tools/gate.sh ui         # just vitest, types, and the stale-bundle check
```

| Gate | What it catches |
|---|---|
| `pytest` | the full suite, plus the layering and testpaths invariants |
| `npm test` | scraper and extension-panel tests under jsdom |
| `npm --prefix ui test` | Svelte component tests |
| `svelte-check` | type errors, at `--threshold error` |
| rebuild + `git diff` | a committed bundle that no longer matches `ui/src/` |

**It runs on your machine, and that is a deliberate retreat.** These were the
three jobs in `.github/workflows/ci.yml`, deleted on 2026-09-13. The checks did
not stop mattering — the 1.0.0 audit's finding was that four reported defects had
passed every automated gate, and the answer to that was more gates, not fewer.
What stopped working was the runner: with the account's Actions minutes gone,
every job since 2026-09-08 failed in under fifteen seconds without ever being
allocated one, produced no logs, and left a red tick on a commit nothing had
tested. A signal that is always red carries no information, and this one was
teaching people to ignore a red build.

So the jobs moved into `tools/gate.sh` verbatim rather than being dropped, and
the obligation moved with them: run it before you push. Restoring the workflow is
a `git revert` and a billing change, in that order.

There is no docker-build job, and there will not be one: Kriko is a standalone
app, not a deployment. `test_the_app_stays_standalone` fails if a Dockerfile, a
compose file, a `deploy/` directory, or a Postgres driver returns — so this
paragraph cannot go stale without the suite going red.

The `desktop` workflow still builds the actual shipping artifact (four
installers on three runners) and runs `packaging/smoke_sidecar.py` against the
frozen binary before bundling it. Every step of it stands; on 2026-09-13 its
*triggers* were narrowed to `workflow_dispatch` only, because it needs minutes
too and firing on tags and packaging PRs only painted a false red. Run it by
hand from the Actions tab (`platforms: all` for the Linux and macOS legs), or
follow `tauri/README.md` to build on a Windows host — which is how every
installer since 0.5.0 was made.

The gate runs with no secrets. `npm test` at the root uses `npm install` rather
than `npm ci`, because the root `package-lock.json` is gitignored. The `ui` gate
uses `npm ci`: its lockfile *is* committed, because the stale-bundle check
compares a fresh build against the committed one and a floating dependency
version would change an asset hash and fail for no reason.
