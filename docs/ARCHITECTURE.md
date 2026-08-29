# Architecture — a reading map

Kriko is a local-first, open knowledge engine for manufactured products: it
answers "what is known to go wrong with *this specific one*" from installed
knowledge **packs** (`cars` is pack #1). The one invariant that explains the
whole layout: **`kriko/` knows no category.** It has no `make`, no
`engine_code`, no `fuel` — only a generic pack store, lookup, ranking, and
research interface. That is what makes adding a product category a data
change (a new `packs/<name>/` directory) rather than an engine change. See
`kriko/tests/test_core_is_domain_free.py`, which enforces it by walking
`kriko/`'s AST.

## The fan

Dependencies point down and in, never up or sideways (copied from
`CLAUDE.md`'s layering principle — if this drifts from that copy, `CLAUDE.md`
is the source of truth):

```
app/       interfaces — cli, web dashboard, mcp server.
   |
   v
kriko/      the engine — pack store, generic lookup, ranking, research
   ^        interface. Imports NONE of the others. Knows no category.
   |
packs/      one directory per product category: data, vocabulary, trust
   |        tiers, builder, and that category's own coverage report.
   |        This is the thing a third party authors.
   v
packs/cars/pipeline/  evidence ledger + grounded extraction — turns sources into
            claims a pack can ship.

app/pipeline/        pipeline drivers — ledger_run, remediate, panel, process.
            May import packs/cars/pipeline/ and packs/. Nothing imports app/pipeline/.
```

## Package → what it owns → read this first

| Package | Owns | File to read first |
|---|---|---|
| `app/` | Interfaces: CLI, FastAPI web dashboard, MCP server for research agents | `app/cli.py` |
| `app/pipeline/` | Pipeline drivers that orchestrate the ledger and packs/cars pipeline | `app/pipeline/ledger_run.py` |
| `kriko/` | The engine: pack store, generic lookup/ranking, gate vocabulary, research interface — no category knowledge | `kriko/store/packstore.py` |
| `packs/` | One directory per product category — data, vocabulary, trust tiers, builder | `packs/drill/README.md` (smallest complete example) |
| `packs/cars/pipeline/` | Evidence ledger + grounded extraction that turns scraped sources into claims for the cars pack | `packs/cars/pipeline/ledger/ingest.py` |
| `extension/` | Chrome extension: scrapes a listing page, calls the web API, renders the risk card | `extension/content.js` |

## Chasing X? read these

**How a listing becomes risk cards** (end-to-end request path):
1. `extension/content.js` — scrapes the page, calls `POST /api/analyze`.
2. `app/web/routers/analyze.py:88` (`analyze()`) — turns the scrape into a
   `Query` via `kriko.adapters.adapt()`, then calls `kriko.lookup.lookup()`.
3. `kriko/adapters.py` — pack-supplied label/parse rules turn raw scraped
   text into typed identity/context fields (no JS from a pack is ever run).
4. `kriko/lookup/__init__.py:94` (`lookup()`) — matches the subject, scores
   and ranks its claims, returns a `LookupResult`.

**Why a claim did or did not show:**
- `kriko/lookup/rank.py:139` (`relevance()`) and `:164` (`explain()`) — the
  scoring/explanation math.
- `kriko/lookup/conditions.py:103` (`evaluate()`) — whether the claim's
  mileage/year/config conditions match this subject.
- `kriko/gates.py:89` (`structural_reasons()`) and `:135` (`is_specific()`) —
  whether the claim clears the product-principle bar at all.

**What a pack contains:**
- `docs/PACK_CONTRACT.md` — the contract, in prose.
- `packs/drill/` — the smallest pack that satisfies it end to end.
- `kriko/pack/manifest.py:37` (`load()`) — what a pack's manifest file
  (`packs/drill/pack.toml` for the reference example) must declare.

**How a pack is built and installed:**
- `kriko/pack/build.py:481` (`build()`) — compiles a pack directory
  (vocabulary + data + trust + gates) into one SQLite file; a short sequence
  of `_emit_*` stages.
- `kriko/store/packstore.py:176` (`install()`) and `:377` (`activate()`) —
  loads a built pack file into the store as a new revision.
- `packs/cars/build.py:871` (`build()`) — the cars pack's own build, which
  layers catalog/gearbox-code derivation on top of the same `_emit_*` shape
  before calling into `kriko/pack/build.py`.

**Where evidence comes from:**
- `packs/cars/pipeline/ledger/ingest.py` — pulls and stores raw source pages.
- `kriko/ledger/extraction.py` and `kriko/ledger/chunking.py` — the
  category-agnostic grounded-extraction machinery packs/cars/pipeline reuses
  rather than forking.
- `app/pipeline/ledger_run.py` — the CLI driver that runs ingest → extract →
  cluster → verdict end to end (`acquire`, `remediate`, `all`, `extract`,
  `report` subcommands).

**What Kriko refuses to store:**
- `app/mcp_server.py:261` (`submit_findings()`) — the one place external
  findings enter the store; grounds every quote against its source text
  before a claim is even considered.
- `kriko/gates.py` — `gate_reason()` and `structural_reasons()`, the generic
  gate engine that refuses routine/generic/unanchored findings.
- `packs/cars/vocabulary/gates.yaml` — the cars pack's own gate vocabulary
  (what counts as "routine" or "generic" for a car) that `kriko/gates.py`
  evaluates. A different pack ships its own gate vocabulary file at the same
  relative location instead.

## Entry points

Every `python -m` target in the tree:

| Command | What it does |
|---|---|
| `python -m app.cli` | CLI — pack install/build/list, lookup queries |
| `python -m app.mcp_server` | MCP server for research agents (`submit_findings`, `lookup`, …) |
| `python -m app.pipeline.ledger_run` | Ledger pipeline: acquire, extract, cluster, verdict, remediate, report |
| `python -m app.pipeline.panel` | Ledger review/inspection panel |
| `python -m app.pipeline.process` | End-to-end onboarding driver for one part/model |
| `python -m app.web` | FastAPI web dashboard (`http://127.0.0.1:8787`) |
| `python -m packs.cars.build` | Builds the cars pack (also reachable via `app.cli build packs/cars`) |
| `python -m packs.cars.coverage` | Cars pack coverage report |
| several `packs/cars/pipeline/{catalog,fitment,ledger,parts,sources}/*.py` scripts | One-off catalog/fitment/ledger maintenance tools — run each with `--help` |

## How to run things

- Use the repo venv, not a bare `python`: `.venv/bin/python`.
- Run the whole test suite with no arguments: `.venv/bin/python -m pytest`
  (`pytest.ini` pins `testpaths`; see `CONTRIBUTING.md`).
- Build and install the cars pack: `python -m app.cli build packs/cars`
  then `python -m app.cli packs` to confirm it's installed (see
  `docs/USAGE.md` for the full onboarding walkthrough).
