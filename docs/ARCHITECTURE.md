# Architecture, a reading map

Find the file that answers your question. Kriko is a local-first knowledge
engine for manufactured products: it answers *what is known to go wrong with
this specific one* from installed catalogs. One invariant explains the layout:
**`kriko/` knows no category.** A new category is a data change (a directory
under `packs/`), never an engine change. The invariant is a test, not a
convention: `src/kriko/tests/test_core_is_domain_free.py` walks `kriko/`'s AST
and fails on category-shaped vocabulary.

## Which package may import which?

Dependencies point down and in, never up or sideways. Where this and the
layering principle in `CLAUDE.md` disagree, `CLAUDE.md` wins.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
flowchart TD
    GPUI["kriko-gpui/<br/>desktop app, supervises the sidecar"] --> UI
    UI["ui/<br/>frontend, HTTP only"] --> APP
    APP["app/<br/>CLI, web, MCP, TUI"] --> K
    PACKS["packs/<br/>one dir per category"] --> K
    APP --> PL["app/pipeline/<br/>ledger drivers"]
    PL --> PP["packs/#lt;name#gt;/pipeline/<br/>evidence ledger"]
    K["kriko/<br/>engine, imports none of the others"]
    K -. "any import upward is the red line" .-> BAD["forbidden"]

    classDef brand  fill:#1F4FFF,stroke:#86A3FF,color:#F2F5FF
    classDef plain  fill:#090E1B,stroke:#3A4156,color:#C9D1EA
    classDef danger fill:#FF6B5E,stroke:#05070F,color:#05070F
    class K brand
    class GPUI,UI,APP,PACKS,PL,PP plain
    class BAD danger
```

## What does each package own, and where do I start?

| Package | Owns | Read first |
|---|---|---|
| `kriko-gpui/` | The desktop app (Rust, GPUI): supervises the sidecar, draws the interface over HTTP, no engine logic | `kriko-gpui/README.md`, then `kriko-gpui/src/engine.rs` |
| `ui/` | Svelte source; `npm --prefix ui run build` writes `src/app/web/static/` | `ui/src/lib/shell/nav.ts`, the one route table the rail, the palette and the router all read |
| `src/app/` | Interfaces: CLI, FastAPI dashboard, MCP server, operator TUI; the frozen sidecar entry | `src/app/cli.py`, `src/app/sidecar.py` |
| `src/app/pipeline/` | Drivers that orchestrate a category's ledger and remediate its gaps | `src/app/pipeline/ledger_run.py` |
| `src/kriko/` | Engine: pack store, generic lookup and ranking, gates, research interface | `src/kriko/store/packstore.py` |
| `packs/` | One directory per category: data, vocabulary, trust tiers, builder | `packs/drill/README.md`, the smallest complete example |
| `packs/<name>/pipeline/` | Evidence ledger and grounded extraction for one category | that pack's `pipeline/ledger/acquire.py` |
| `extension/` | Reads a listing page; a background worker calls the web API and renders the risk cards | `extension/content.js` |

### `ui/`, the frontend

Svelte 5 and Vite, built into `src/app/web/static/`. A hash-routed shell over
the route table in `lib/shell/nav.ts`, which also holds the alias words so a
retired screen's address still opens whatever absorbed it. `styles/` holds the
tokens and the one theme (`themes/panel.css`); `lib/` the typed API client
plus pure derivation (`report.ts`, `verdict.ts`, `compare.ts`, `health.ts`,
`fields.ts`, `homeSeries.ts`); `routes/` one component per destination. Only
the report surface is editorial (68ch, a print sheet).

## Chasing a question? Read these

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
flowchart LR
    Q1["A listing becomes a card"] --> F1["extension/content.js<br/>routers/analyze.py<br/>lookup/match.py"]
    Q2["A claim did or did not show"] --> F2["lookup/rank.py<br/>lookup/conditions.py<br/>gates.py"]
    Q3["What a catalog contains"] --> F3["PACK_CONTRACT.md<br/>packs/drill/<br/>pack/manifest.py"]
    Q4["Build and install"] --> F4["pack/build.py<br/>store/packstore.py"]
    Q5["Evidence"] --> F5["pipeline/ledger/acquire.py<br/>ledger/db.py<br/>app/pipeline/ledger_run.py"]
    Q6["Refusals"] --> F6["app/mcp_server.py<br/>gates.py<br/>the pack's vocabulary"]

    classDef brand  fill:#1F4FFF,stroke:#86A3FF,color:#F2F5FF
    classDef plain  fill:#090E1B,stroke:#3A4156,color:#C9D1EA
    classDef ice    fill:#BFE4FF,stroke:#1F4FFF,color:#05070F
    class Q1,Q2,Q3,Q4,Q5,Q6 ice
    class F1,F2,F3,F4,F5,F6 plain
```

The paths in the diagram are shortened; the full ones follow.

**A listing becomes a card.** `extension/content.js` scrapes and messages the
background worker, which `POST`s to `/api/analyze`
(`src/app/web/routers/analyze.py`). That turns the scrape into a `Query`
through `kriko.adapters.adapt()`, resolves subjects in
`src/kriko/lookup/match.py`, and reads ranked claims from
`src/kriko/lookup/__init__.py`.

**Why a claim did or did not show.** `src/kriko/lookup/rank.py`
(`relevance()`, `explain()`), `src/kriko/lookup/conditions.py` (`evaluate()`),
`src/kriko/gates.py` (`structural_reasons()`, `is_specific()`), and
`lookup/tree.py` for the support read, which carries no score. A claim ranked
low goes to `tree.py`, then to `src/app/web/routers/health.py`.

**What a catalog contains.** `docs/PACK_CONTRACT.md`, then `packs/drill/`,
then `src/kriko/pack/manifest.py` (`load()`).

**Build and install.** `src/kriko/pack/build.py` (`build()` and its `_emit_*`
stages) turns a directory into a `.kpack`; `src/kriko/store/packstore.py`
(`install()`, `activate()`) puts it in the store. A pack with its own legacy
data shapes may carry a parallel builder, which is a migration rather than the
general path.

**Evidence.** A category's `pipeline/ledger/acquire.py` fetches, and
`ingest.py` is a thin adapter over the engine's `src/kriko/ledger/db.py`.
`extraction.py` and `chunking.py` hold the shared grounded-extraction
machinery, and `src/app/pipeline/ledger_run.py` drives the stages.

**Refusals.** `src/app/mcp_server.py` (`submit_findings()`, which grounds
every quote first), `src/kriko/gates.py` (`gate_reason()`,
`structural_reasons()`), and the pack's own routine vocabulary, which is data
rather than Python.

## Which command starts what?

| Command | What it does |
|---|---|
| `kriko` (`python -m app.cli`) | CLI: catalog install, build, list, lookup |
| `kriko tui` / `kriko-sidecar --tui` | Operator console (see `docs/INTERNALS.md`) |
| `python -m app.mcp_server` | MCP server, for an agent that does its own reading |
| `python -m app.pipeline.ledger_run` | Ledger stages: acquire, extract, cluster, verdict, remediate, report |
| `python -m app.pipeline.panel` | Ledger review and inspection panel |
| `python -m app.pipeline.process` | End-to-end onboarding driver for one product |
| `python -m app.web` | FastAPI dashboard on `http://127.0.0.1:8787` |
| `python -m packs.<name>.build` | Builds one catalog (also `kriko build packs/<name>`) |
| `python -m packs.<name>.coverage` | That catalog's coverage report |
| `packs/<name>/pipeline/catalog/*.py` | Catalog discovery, health, variant and stub generation |
| `packs/<name>/pipeline/fitment/`, `parts/` | Validate a pack's own fitment and part data |
| `packs/<name>/pipeline/ledger/{eval_verdict,parity}.py`, `sources/curated.py`, `scaffold.py`, `agent/render.py` | One-off ledger, scaffold and render tools; each has `--help` |

## How do I run things?

- Repo venv, not bare `python`: `.venv/bin/python` on POSIX,
  `.venv\Scripts\python.exe` on Windows.
- Full suite, no arguments: `python -m pytest` (`pytest.ini` pins
  `testpaths`; see `docs/DOCTRINE.md`).
- A catalog: `kriko build packs/<name>`, then `kriko packs`. The full
  walkthrough is `docs/USAGE.md`.
