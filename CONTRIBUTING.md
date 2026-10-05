# Contributing to Kriko

Principles (*what* Kriko does) live in [`CLAUDE.md`](CLAUDE.md) and are not repeated here. This file is mechanics: branches, commits, tests, gate.

## The loop

```bash
tools/setup.sh                 # working tree (idempotent — run whenever something feels wrong)
tools/gate.sh                  # everything the branch used to be checked for
python tools/bump.py X.Y.Z     # version, in all five places it lives
```

`setup.sh` pins what six failed discoveries taught: the interpreter floor from `pyproject.toml`, `requirements.lock` as the frozen closure, `-e .` so `app.version` reports the tree, the `pipeline` extra required for the *suite* (six modules will not import without it), separate `node_modules` for `ui/` and the root, and wiping stale `src/*.egg-info`. It never touches `~/.kriko` — the store, history and keys are not a dev environment.

`python tools/bump.py --show` checks four committed files plus installed-distribution metadata (what `/api/health` reports; a tree at 0.8.1 with a 0.8.0 editable install serves 0.8.0). It never commits or tags.

The MCP server (`.mcp.json`) runs `.venv/bin/python -m app.sidecar --mcp` relative to the repo root, so it works in any checkout `setup.sh` touched.

## Before you start

Read [`backlog.md`](backlog.md) then [`docs/DOCTRINE.md`](docs/DOCTRINE.md) — the status file, then how a request is written, what "done" means, which test proves what, and what a PR must carry. A finished item leaves the backlog, and its commit message is the record: say what was observed, not that tests pass.

Two things every document here obeys, because a decision that belongs to the reader's own machine must not be frozen into prose every other machine reads:

- **No category.** A document names no product type and no catalog, even where a
  real pack directory would have made a shorter example. An example in a
  document becomes a promise in the reader's head, and the principle it
  illustrates is the one the reader asked to see.
- **No vendor.** A document names no model, no agent product and no search provider. Roles instead: *a coding agent CLI*, *a local model server*, *a hosted search*. The names live in code, where the machine's own list is read at runtime.

## Branches and commits

Branch off `main`. Nothing reaches `main` without the author asking.

Conventional commits with scope, as history uses: `feat(hub):`, `fix(hub):` (name the cause), `refactor(ops):`, `docs:`, `chore(git):`, `perf(hub):` (measured, with numbers). The body is for `git log` in six months: the cause, not the symptom (*"the picker armed an unsucceedable onboarding run"* over *"fix picker bug"*), and what you chose not to do when the choice is not obvious.

## Tests

```bash
python -m pytest        # all tests — no arguments
npm test                # extension scraper + panel
```

Run `pytest` bare: `pytest.ini` pins `testpaths`, and naming directories skips `app/pipeline/tests` silently (576 of 761 tests once). The suite must pass with **no API keys and no `.env`**; a keyed test reaches the network and belongs behind a marker.

After moving a serving-path module, also run:

```bash
python -c "import app.web.app, kriko.lookup, kriko.store"
python -m pytest src/app/pipeline/tests/test_repo_invariants.py
```

Serving is the local FastAPI app on the SQLite pack store; the pipeline stays separate, so importing `app.web.app` must not load `app.pipeline` or the LLM stack.

## The window

The window is `kriko-gpui/` (Rust, GPUI). It reads the engine over HTTP like
the extension and the TUI; the engine serves data, never screens.

## Dead code

`grep` for a dotted path misses `from x import y` and falsely reports live modules as dead. Before deleting on "nothing imports this", check all import styles, entry points and doc mentions; the record of past findings is in `git log`.

## Architecture

Dependencies flow one way; import down, never up:

```
src/app/             CLI, web dashboard, MCP server, operator TUI
src/app/pipeline/    ledger and remediation orchestration
src/kriko/           store, ledger/extract, lookup, ranking, research
packs/               per-category data, builders, vocabulary, coverage, pack pipelines
extension/           thin browser client; no product or site interpretation
```

Needing something from above means **the module is in the wrong layer, so move it.** An upward deferred import (a function-body import hiding `partially initialized module`) is the smell; a downward one is just startup cost. `test_repo_invariants.py` enforces this.

## The gate

```bash
tools/gate.sh            # everything
tools/gate.sh py         # Python suite only
```

| Gate | Catches |
|---|---|
| `pytest` | full suite + the layering and testpaths invariants |
| `npm test` | scraper and extension-panel tests (jsdom) |

**It runs on your machine, as a deliberate retreat.** These were `ci.yml`'s
three jobs, moved verbatim into `tools/gate.sh` on 2026-09-13 when the
account's Actions minutes ran out: every run failed in under 15 seconds with
no logs, which is red ticks on untested commits, and a signal that is always
red teaches ignoring red. The obligation moved with them, so run it before you
push. Restoring the workflow is `git revert` then the billing change, in that
order.

No docker-build job, ever: Kriko is a standalone app, not a deployment
(`test_the_app_stays_standalone` fails on a Dockerfile, compose files, a
`deploy/` directory or a Postgres driver).

The `desktop` workflow (four installers, three runners plus
`packaging/smoke_sidecar.py`) is untrimmed but **hand-run only**
(`workflow_dispatch`; the tag and pull-request triggers were removed
2026-09-13 for the same minutes reason). Run it from the Actions tab
(`platforms: all` for the Linux and macOS legs) or build on a Windows host per
`tauri/README.md`, which is how every installer so far was made.

The gate runs with no secrets. Root `npm test` uses `npm install` (its lockfile
is gitignored); the `ui` gate uses `npm ci` (lockfile committed), because
floating dependencies would change asset hashes and fail the bundle check
spuriously.
