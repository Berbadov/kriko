> TL;DR (archived 2026-09-25): Design (2026-09-01) for the standalone app: dashboard is
feature-complete but unusable (no persistence, no job state, flat relevance cards, hostile
JSON input; 443-line `app.js` with no router). Rewrite as Svelte 5 + TS (`ui/` outside
`src/`, committed bundle), pack-agnosticism preserved, separate `app.sqlite` state, mode as
projection, single-worker jobs, Tauri sidecar packaging. Constraints: local-first
127.0.0.1, no engine diff, no ranking change, no auth/update/signing/mobile.

# The standalone app — UI rewrite and desktop packaging

**Date:** 2026-09-01 · **Branch:** from `feat/knowledge-engine-pivot` · **Baseline:** observability pass (Health tab, `f121dee`) · **Goal alignment:** G6 + *web-first minimal slice* ("every operation operable and inspectable from the dashboard with visible result, error, durable status")

## Problem

Feature-complete and unusable — every capability has a tab, none is a *workflow*:
- **Nothing persists.** `app.js` renders `innerHTML` and forgets: tab switch/reload kills lookups. No history, no links, no compare.
- **No visible job state.** Zero `job` in `src/`: research (`kriko/research/`, MCP, `app/pipeline/`) and pack builds are terminal-only — contradicting the G6 delivery constraint (browser installs finished `.kpack`s only).
- **Results aren't advice.** Flat cards with raw `relevance 0.270`; no system grouping, no urgency order, no wrong-vs-ask-seller split, no checked-marks. `advice`/`why` in payload, shown nowhere.
- **Hostile input.** Hand-typed JSON for Analyze; Ask needs pack identity keys upfront. No URL paste, no subject autocomplete, no pre-submit validation.

Underneath: 443 lines, fifteen HTML-string builders, no router — nowhere to hang per-view state.

## What is worth keeping

**Pack-agnosticism reaching the DOM** — the load-bearing property. `changeAskPack()` builds forms from `/api/identity-keys/{pack}` + `/api/packs/{pack}/vocabulary`; `_context_units` keeps the UI from learning `usage_km` is kilometres. Any rewrite preserves this or domain-freedom dies at the HTTP boundary.

## Non-goals

No auth/multi-tenancy/remote hosting (local-first; 127.0.0.1 is a correctness property) | no Rust engine rewrite (Tauri wraps a Python sidecar; `src/kriko/` diffs = something wrong) | no ranking/claim-selection change (presentation + operability only) | no auto-update/signing/store distribution (installers produced; distribution later) | no mobile layout.

## Architecture

`ui/` NEW (Svelte 5 + Vite + TS; `lib/{api.ts,types.ts,mode.ts,stores/}`, `routes/` Ask/Result/Subjects/Packs/Jobs/Health/Coverage) — **not** in the wheel. `src/app/web/static/` = committed `vite build` output. `state.py` NEW (`~/.kriko/app.sqlite`: history, saved lookups, jobs) + `jobs.py` NEW (single-worker runner) + `routers/jobs.py` (CRUD + SSE stream). `tauri/src-tauri/` NEW (Rust shell, PyInstaller sidecar). One-way deps unchanged: `ui/`→`app/` over HTTP; `tauri/`→`app/` over HTTP + process handle; nothing importable.

### Decision 1 — `ui/` sits outside `src/`, build output is committed

Wheel must not need Node; `python -m app.web` serves working UI on clean checkout ⇒ bundle committed like a generated parser (`node_modules` ignored, `ui/` excluded from wheel). Today's `test_web.py` (GET `/`) passes unchanged; CI stale-bundle check diffs fresh build vs committed.

### Decision 2 — UI state lives in a separate `~/.kriko/app.sqlite`

History/jobs are interface concerns; in `knowledge.sqlite` they'd be the first tables nothing in `kriko/` reads (layering violation as schema) and poison `.kpack` diffs/`content_digest`. Consequences that settle it: uninstalling a pack must not drop history; history must never appear in a digest. Own tiny schema, WAL, `Settings.app_state_path` (tmpdir in tests — the B28 factory pattern).

### Decision 3 — the mode switch is a projection, never a second API

Buyer/author render one `/api/lookup` response: words+colour+urgency vs `relevance 0.2700`+`pack_id`+`disputed`; "ask the seller" vs `why[]`+flags; "3 sources agree" vs per-source `domain·tier·stance·retrieved_at`; verbatim `unmapped_labels`/`method`/`coverage` for authors only. No endpoint knows mode; mode persists in `app.sqlite` + URL (links carry it).

### Decision 4 — jobs are rows first, a stream second

`jobs(job_id, kind, params_json, state, progress, message, log, result_json, created_at, started_at, finished_at)`; `queued → running → (succeeded|failed|interrupted)`. `ThreadPoolExecutor(max_workers=1)` — no broker/process; serial by design (concurrent builds on one pack dir = inexpressible bug). SSE over the row + polling fallback. Startup marks stale `running` ⇒ `interrupted` (visible state, never a hung spinner).

## Backend additions

`GET /api/lookup/{id}` (reopen/link), `GET/DELETE /api/history`, `POST /api/lookups/{id}/checked` (triage), `GET/POST /api/settings`, `POST /api/packs/build` (**job**), `POST /api/research` (**job**), `GET /api/jobs[/{id}[/stream]]`, `POST /api/jobs/{id}/cancel`. `POST /api/lookup` records to `app.sqlite`, returns `lookup_id` (`/api/analyze` same; JSONL analysis log untouched — parity corpus, not UI store). Research reuses `Researcher`/`AgentResearcher` (job is a driver; no new research logic).

## Views

**Buyer — two screens.** **Check**: URL field first (posts `/api/analyze`; unknown hosts answer with what installed packs *can* read from `/api/adapters`, not bare 404) + guided identity form beneath. **Report**: risks grouped by `domain`, severity-then-relevance; risk → "what to ask" → collapsed sources; persistent handled-checkboxes; header states `coverage`/`method` in words; empty results say *why* (no match vs matched-but-unknown). **Author adds** Subjects (search, detail, research brief), Health, Coverage (gaps + "research this" job buttons), Packs (install/build/enable/revisions/rollback), Jobs (queue, live log, outcomes), Activity. **Both**: hash router — every view linkable, back button works.

### `ui/` may not contain pack vocabulary

The TS analogue of the engine's failure mode (`if (key === "make")` in a form component ends domain-freedom where no Python test looks): `test_repo_invariants.py` greps `ui/src/` for pack vocabulary in code positions, so the invariant holds in the language where it would actually break.

## Desktop packaging

Largest, riskiest, least prior art. **Sidecar:** PyInstaller engine+uvicorn per OS as Tauri `externalBin`; shell spawns on ephemeral port, passes it in, polls `/api/health` pre-window. **Paths:** sidecar resolves `~/.kriko/` like the CLI (one store, two front doors). **Lifecycle:** shell kills sidecar on close/crash (test the orphaned-uvicorn-WAL-lock case explicitly). **Failure surface:** dead sidecar ⇒ captured stderr in-window, never blank. **CI:** macOS/Windows/Linux bundles, unsigned (signing deferred).

## Testing

pytest (routers/state/runner incl. `interrupted` + cancel, tmpdir state) | Vitest (projections, form-building, api client from one fixture) | Playwright one spec (URL→report; research job→completion) | pytest invariants (layering, `ui/` vocab grep, stale bundle) | sidecar (handshake, port passing, no orphan) + CI job.

## Phases

0. `ui/` scaffold + typed client, 7-tab parity → `app.js` deleted, green, no behaviour change. 1. Router + `app.sqlite` + history → reload/back work. 2. Projections + report → results read as advice. 3. URL paste/autocomplete/validation → JSON textarea gone. 4. Jobs backend + view → nothing terminal-only. 5. Tauri + sidecar + installers → double-clickable, 3 OSes. Phase 4 closes the G6 constraint; 0–4 ship even if 5 slips.

## Risks

PyInstaller+SQLite+WAL × 3 OSes (phase 5 last; CI bundle smoke test on `/api/health`) | stale committed bundle (CI rebuild-and-diff fails the build) | two-SQLite confusion (`/api/health` reports both paths; Packs view names them) | report exposes weak selection (correct — file it, B36-adjacent, don't fix here).
