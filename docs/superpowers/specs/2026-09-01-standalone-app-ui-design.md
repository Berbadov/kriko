# The standalone app — UI rewrite and desktop packaging

**Date:** 2026-09-01
**Branch:** to be created from `feat/knowledge-engine-pivot`
**Baseline:** the knowledge-tree observability pass (Health tab landed, commit `f121dee`)
**Goal alignment:** G6 (product knowledge engine) and its *web-first minimal slice* delivery
constraint — "every operation must be operable and inspectable from the dashboard with a
visible result, error, and durable status."

## Problem

The dashboard is feature-complete and unusable. Every backend capability has a tab, and
none of them is a *workflow*:

- **Nothing persists.** `app.js` renders into `innerHTML` and forgets. Switching a tab or
  reloading destroys a lookup. There is no back button, no history, no way to reopen or
  link a result, no way to compare two cars.
- **No visible job state.** `grep -rn "job" src/` finds nothing. Research runs through
  `kriko/research/` driven by MCP or `app/pipeline/` scripts; a pack is *built* only by
  CLI. The browser can install a finished `.kpack` and nothing else, so the two operations
  that actually grow the knowledge base are terminal-only — directly contradicting the G6
  delivery constraint.
- **Results are not advice.** A claim renders as a flat card with a raw `relevance 0.270`.
  No grouping by system, no ordering that reads as urgency, no separation between "what is
  wrong" and "what to ask the seller", no way to mark one as checked. `advice` and `why`
  are in the API payload and shown nowhere.
- **Input is hostile.** Analyze demands a hand-typed JSON object. Ask demands you already
  know which identity keys the pack declares. No paste-a-URL path, no autocomplete against
  installed subjects, no validation before submit.

Underneath, the frontend is 443 lines of one file with fifteen HTML-string builders and no
router — so there is nowhere to hang the per-view state that every fix above needs.

## What is worth keeping

The current frontend is **pack-agnostic, and that is the load-bearing property.**
`changeAskPack()` builds its form from `/api/identity-keys/{pack}` and
`/api/packs/{pack}/vocabulary`; `analyze.py::_context_units` exists precisely so the UI
never learns that `usage_km` is kilometres. The G6 invariant reaches into the DOM. Any
rewrite preserves this or the engine's domain-freedom stops at the HTTP boundary.

## Non-goals

- **No auth, no multi-tenancy, no remote hosting.** Local-first; `127.0.0.1` stays a
  correctness property, not a default (`app.py` explains why).
- **No engine rewrite in Rust.** Tauri wraps a Python sidecar; `kriko/` is untouched by
  this work, and a diff to `src/kriko/` in this project is a sign something went wrong.
- **No new ranking, no new claim selection.** The product principle is not being
  relitigated here. This changes presentation and operability only.
- **No auto-update, no code signing, no app-store distribution** in this project.
  Installers are produced; distribution is a later policy decision.
- **No mobile layout.** Desktop and desktop-sized browser only.

## Architecture

```
ui/                             NEW — Svelte 5 + Vite + TypeScript source. Not in the wheel.
  src/lib/api.ts                typed client; one function per endpoint
  src/lib/types.ts              hand-written types mirroring the router payloads
  src/lib/mode.ts               buyer | author projection
  src/lib/stores/               history, jobs, mode — Svelte stores over the API
  src/routes/                   Ask, Result, Subjects, Packs, Jobs, Health, Coverage
src/app/web/static/             BUILD OUTPUT of `vite build`, committed to git
src/app/web/state.py            NEW — ~/.kriko/app.sqlite: history, saved lookups, jobs
src/app/web/jobs.py             NEW — single-worker job runner over app.sqlite
src/app/web/routers/jobs.py     NEW — create / list / detail / SSE stream
tauri/src-tauri/                NEW — Rust shell; spawns the PyInstaller sidecar
```

Dependencies still flow one way. `ui/` talks to `app/` over HTTP; `tauri/` talks to
`app/` over HTTP and a process handle; neither is importable, so the fan in CLAUDE.md is
unchanged and no new Python import crosses a layer.

### Decision 1 — `ui/` sits outside `src/`, build output is committed

The Python wheel ships only `src/app/web/static/`. `pip install kriko` must not require
Node, and `python -m app.web` on a clean checkout must serve a working UI, so the built
bundle is committed like a generated parser. `ui/node_modules` is gitignored; `ui/` is
excluded from the wheel via `pyproject.toml`. Today's `test_web.py` (which fetches `/`)
keeps passing unchanged, and a stale-bundle check in CI compares a fresh `vite build`
against the committed output.

### Decision 2 — UI state lives in a separate `~/.kriko/app.sqlite`

Lookup history and job rows are interface concerns owned by `app/`. Putting them in
`knowledge.sqlite` would add the first tables in `kriko/store/schema.sql` that nothing in
`kriko/` reads — a layering violation expressed as schema rather than as an import, and
the precedent that admits the next one. Practical consequences that settle it: uninstalling
a pack must not drop your history, and a history table must never show up in a `.kpack`
diff or a `content_digest`.

`state.py` owns its own tiny schema, WAL on, same `~/.kriko/` directory, created on first
use. `Settings` gains `app_state_path` alongside `store_path` so tests can point it at a
tmpdir — the same factory pattern that unblocked B28.

### Decision 3 — the mode switch is a projection, never a second API

`buyer` and `author` are two renderings of one `/api/lookup` response:

| Same claim, buyer sees | author sees |
|---|---|
| severity as a word and a colour, ordered by urgency | `relevance 0.2700`, `pack_id`, `disputed` |
| `advice` as "ask the seller / have this checked" | `why[]` reasons, resolution `flags` |
| sources as "3 sources agree" | per-source `domain · tier · stance · retrieved_at` |
| — | `unmapped_labels`, `method`, `coverage` verbatim |

No endpoint branches on mode; no backend code knows a mode exists. The setting persists in
`app.sqlite` and is reflected in the URL so a link carries it.

### Decision 4 — jobs are rows first, a stream second

`app.sqlite.jobs`: `job_id, kind, params_json, state, progress, message, log, result_json,
created_at, started_at, finished_at`. States: `queued → running → (succeeded | failed |
interrupted)`.

A `ThreadPoolExecutor(max_workers=1)` runs them; there is no broker and no second process.
Progress is written to the row, and `GET /api/jobs/{id}/stream` is SSE over the row with a
polling fallback so the UI degrades rather than hangs. At startup any row still `running`
is marked `interrupted` — a job cannot be silently lost, and an interrupted job is visible
as a state rather than as a spinner that never resolves.

Serial by design: research and pack builds are I/O- and cost-heavy, and two concurrent
builds writing the same pack directory is a bug we should not be able to express.

## Backend additions

| Endpoint | Purpose | Job? |
|---|---|---|
| `GET /api/lookup/{lookup_id}` | reopen / link a past result | no |
| `GET /api/history?limit=` | recent lookups from `app.sqlite` | no |
| `DELETE /api/history/{id}` | forget one | no |
| `POST /api/lookups/{id}/checked` | triage state per claim | no |
| `GET/POST /api/settings` | mode and other UI preferences | no |
| `POST /api/packs/build` | pack dir → `.kpack` → install | **yes** |
| `POST /api/research` | run a `Researcher` against a gap | **yes** |
| `GET /api/jobs`, `/api/jobs/{id}`, `/api/jobs/{id}/stream` | job state | — |
| `POST /api/jobs/{id}/cancel` | cooperative cancel | — |

`POST /api/lookup` starts recording to `app.sqlite` and returns a `lookup_id`. `/api/analyze`
does the same; the JSONL analysis log in `observability.py` is untouched, because it is the
parity corpus and not a UI store.

Research reuses the `Researcher` protocol in `kriko/research/base.py` and the existing
`AgentResearcher`; the job is a driver, and no new research logic is written here.

## Views

**Buyer mode — two screens.**

1. **Check** — one field that accepts a listing URL, with the guided identity form beneath
   it for when there is no URL. The URL path posts to `/api/analyze`; unrecognised hosts
   say which sites the installed packs *can* read, from `/api/adapters`, instead of a bare
   404.
2. **Report** — the risks, grouped by `domain`, ordered by severity then relevance. Each
   card leads with the risk, then "what to ask", then sources collapsed. A checkbox marks
   one handled and persists. The header states `coverage` and `method` in words, and an
   empty result says *why* it is empty — no match, versus matched with nothing known.

**Author mode adds** Subjects (searchable, detail + research brief), Health (as today),
Coverage (gaps, each with a "research this" button that starts a job), Packs (install,
build, enable, revisions, rollback), Jobs (queue, live log, outcomes), Activity.

**Both modes** get a real hash router, so every view is linkable and the back button works.

### `ui/` may not contain pack vocabulary

`test_core_is_domain_free.py` walks `kriko/`'s AST for car words. The same failure mode is
now reachable in TypeScript: one `if (key === "make")` in a form component and the engine's
domain-freedom is over in a place no Python test looks. A check in
`test_repo_invariants.py` greps `ui/src/` for pack vocabulary in code positions, so the
invariant is enforced in the language where it will actually be broken.

## Desktop packaging

The largest and riskiest phase, and the one with the least prior art in this repo.

- **Sidecar.** PyInstaller builds the engine + uvicorn into one binary per OS, declared as
  a Tauri `externalBin`. The Rust shell spawns it on an ephemeral port, passes the port in,
  and polls `/api/health` before showing the window.
- **Paths.** The sidecar must resolve `~/.kriko/` the same as the CLI does, so a pack
  installed in the app is visible to `python -m app.cli` and vice versa. One store, two
  front doors.
- **Lifecycle.** The shell kills the sidecar on window close and on its own crash; an
  orphaned uvicorn holding a WAL lock is the failure mode to test for explicitly.
- **Failure surface.** If the sidecar dies or never becomes healthy, the window shows the
  captured stderr, not a blank page.
- **CI.** Bundles build on macOS, Windows and Linux runners. Unsigned; signing is deferred.

## Testing

| Layer | Tool | What |
|---|---|---|
| new routers, state, job runner | pytest (existing) | states incl. `interrupted` and cancel; tmpdir `app_state_path` |
| projections, form building, api client | Vitest | buyer/author output from one fixture payload; dynamic fields from vocabulary |
| the two flows | Playwright, one spec | paste a URL → report; start a research job → watch it finish |
| invariants | pytest | layering greps, `ui/` vocabulary grep, stale-bundle check |
| sidecar | pytest + CI job | health-check handshake, port passing, no orphan on exit |

## Phases

Each lands on its own, and the app is usable at the end of every one.

| # | Phase | Ends with |
|---|---|---|
| 0 | `ui/` scaffold, typed client, feature parity with the 7 tabs | `app.js` deleted, tests green, no behaviour change |
| 1 | Router + `app.sqlite` + history, linkable results | reload and back button work |
| 2 | Buyer/author projections; the report screen | a result reads as advice |
| 3 | Input overhaul — URL paste, autocomplete, no raw JSON | the JSON textarea is gone |
| 4 | Jobs backend + Jobs view; research and build from the browser | nothing in the data path is terminal-only |
| 5 | Tauri shell + sidecar + installers | a double-clickable app on three OSes |

Phase 4 closes the G6 delivery constraint. Phase 5 is what makes it a standalone app; 0–4
are worth shipping even if 5 slips.

## Risks

- **PyInstaller + SQLite + WAL across three OSes** is where this bogs down. Mitigation:
  phase 5 last, and a CI smoke test that launches the bundle and hits `/api/health`.
- **The committed bundle goes stale.** Mitigation: CI rebuilds and diffs; a stale bundle
  fails the build rather than shipping a UI nobody can reproduce.
- **Two SQLite files confuse operators.** Mitigation: `/api/health` reports both paths (it
  already reports the store), and the Packs view names them.
- **Scope drift into ranking work.** The report screen will make weak claim selection
  obvious. That is the product principle's open work, not this project's — file it, do not
  fix it here.
