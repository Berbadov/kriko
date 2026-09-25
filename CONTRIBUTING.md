# Contributing to Kriko

Principles (*what* Kriko does) live in [`CLAUDE.md`](CLAUDE.md) and are not repeated here. This file is mechanics: branches, commits, tests, gate.

## The loop

```bash
tools/setup.sh                 # working tree (idempotent — run whenever something feels wrong)
tools/gate.sh                  # everything the branch used to be checked for
python tools/bump.py X.Y.Z     # version, in all five places it lives
```

`setup.sh` (new 2026-09-13) pins what six failed discoveries taught: Python 3.14, `requirements.lock` as the frozen closure, `-e .` so `app.version` reports the tree, the `pipeline` extra required for the *suite* (six modules won't import without it), separate `node_modules` for `ui/` and root, and wiping stale `src/*.egg-info`. It never touches `~/.kriko` — store, history and keys are not dev environment.

`python tools/bump.py --show` checks four committed files plus installed-distribution metadata (what `/api/health` reports — a tree at 0.8.1 with a 0.8.0 editable install serves 0.8.0). It never commits or tags.

The MCP server (`.mcp.json`) runs `.venv/bin/python -m app.sidecar --mcp` relative to the repo root, so it works in any checkout `setup.sh` touched.

## Before you start

Read [`backlog.md`](backlog.md) then [`docs/DOCTRINE.md`](docs/DOCTRINE.md) — status source of truth (`backlog.md`/`done.md`), then how requests are written, what "done" means, which test proves what, and PR proof. Move finished work across with date + commit hash.

## Branches and commits

Branch off `main` (`feat/agent-model-onboarding`, `observability-analyses-log`). Nothing reaches `main` without the author asking.

Conventional commits with scope, as history uses: `feat(hub):`, `fix(hub):` (name the cause), `refactor(ops):`, `docs:`, `chore(git):`, `perf(hub):` (measured, with numbers). Body for `git log` in six months: cause not symptom (*"picker armed an unsucceedable onboarding run"* > *"fix picker bug"*); note what you chose not to do when non-obvious.

## Tests

```bash
python -m pytest        # all tests — no arguments
npm test                # extension scraper + panel
npm --prefix ui test    # dashboard Svelte components
```

Run `pytest` bare: `pytest.ini` pins `testpaths`; naming directories skipped `app/pipeline/tests` silently (576 of 761 tests once). Suite must pass with **no API keys, no `.env`** — keyed tests reach the network and belong behind a marker.

After moving a serving-path module, also run:

```bash
python -c "import app.web.app, kriko.lookup, kriko.store"
python -m pytest src/app/pipeline/tests/test_repo_invariants.py
```

Serving is the local FastAPI app on the SQLite pack store; the pipeline stays separate, so importing `app.web.app` must not load `app.pipeline` or the LLM stack.

## The frontend

`ui/` is Svelte + Vite source; `src/app/web/static/` is committed build output (the wheel serves the UI with no Node toolchain — only true if output matches source). After touching `ui/src/`:

```bash
npm --prefix ui test
npm --prefix ui run build      # rewrites src/app/web/static/
git add ui src/app/web/static
```

`tools/gate.sh ui` rebuilds and fails on a dirty diff. `ui/package-lock.json` is committed (overriding the repo ignore) for reproducible asset hashes. `ui/src/` holds **no pack vocabulary** (`make`, `model`, `fuel`…) — forms come from `/api/identity-keys/{pack_id}` and `/api/packs/{pack_id}/vocabulary` at runtime (`test_ui_contains_no_pack_vocabulary`).

### Pressing every button: `tools/walk.sh`

Component tests stub fetch, so they miss slow screens and dead buttons. `walk.sh` starts the app on a throwaway home (never `~/.kriko`) with fresh first-party packs, opens every rail screen in headless Chromium, presses every button from a fresh load, and writes `.walk/walk.md` (load time, console errors, ≥400 requests; per button: errored / never settled / slow / changed nothing).

```bash
tools/walk.sh             # all screens, ~15 min
tools/walk.sh agents      # addresses containing "agents"
KRIKO_WALK_REAL_CLIS=1 tools/walk.sh agents   # real claude/agy/opencode
```

Defaults use instant stand-in CLIs on `PATH`; buttons named quit/uninstall/delete/remove/forget/reset/revoke/undo are listed, never pressed. Needs Playwright (`npm i -g playwright && npx playwright install chromium`); not a repo dep, not in the gate.

## Dead code

`grep` for a dotted path misses `from x import y` and falsely reports live modules as dead. Before deleting on "nothing imports this", re-run the query in `docs/superpowers/plans/2026-08-29-simplification-pass.md` Task 9 (all import styles, entry-point and doc-mention detection) — currently finds no dead modules.

## Architecture

Dependencies flow one way; import down, never up:

```
src/app/             CLI, web dashboard, MCP server, operator TUI
src/app/pipeline/    ledger and remediation orchestration
src/kriko/           store, ledger/extract, lookup, ranking, research
packs/               category data, builders, vocabulary, coverage, pack pipelines
extension/           thin browser client; no product/site interpretation
```

Needing something from above means **the module is in the wrong layer — move it.** Upward deferred imports (function-body imports hiding `partially initialized module`) are the smell; downward ones are just startup cost. `test_repo_invariants.py` enforces this.

## The gate

```bash
tools/gate.sh            # everything
tools/gate.sh py         # Python suite only
tools/gate.sh ui         # vitest + types + stale-bundle check
```

| Gate | Catches |
|---|---|
| `pytest` | full suite + layering and testpaths invariants |
| `npm test` | scraper and extension-panel tests (jsdom) |
| `npm --prefix ui test` | Svelte component tests |
| `svelte-check` | type errors at `--threshold error` |
| rebuild + `git diff` | committed bundle not matching `ui/src/` |

**It runs on your machine — a deliberate retreat.** These were `ci.yml`'s three jobs, moved verbatim into `tools/gate.sh` on 2026-09-13 when the account's Actions minutes ran out (every run failed in <15s, no logs, red ticks on untested commits — a signal always red teaches ignoring red). Obligation moved with them: run it before you push. Restore via `git revert` + billing change, in that order.

No docker-build job, ever: Kriko is a standalone app, not a deployment (`test_the_app_stays_standalone` fails on Dockerfile/compose/`deploy/`/Postgres driver).

The `desktop` workflow (four installers, three runners + `packaging/smoke_sidecar.py`) is untrimmed but **hand-run only** (`workflow_dispatch`; tag/PR triggers removed 2026-09-13 for the same minutes reason). Run from the Actions tab (`platforms: all` for Linux/macOS legs) or build on a Windows host per `tauri/README.md` — as every installer since 0.5.0 was made.

Gate runs with no secrets. Root `npm test` uses `npm install` (lockfile gitignored); the `ui` gate uses `npm ci` (lockfile committed — floating deps would change asset hashes and fail the bundle check spuriously).
