# The architecture

Kriko is a local-first knowledge engine for manufactured products. One rule
explains the layout: **the engine knows no product category.** A new category is
data, in a folder under `packs/`. A new category is never a change to the
engine.

The rule is a test, not a habit. `src/kriko/tests/test_core_is_domain_free.py`
reads the engine and fails on a category word.

## Which package may import which?

Dependencies point down. They never point up or across.

| Package | Function |
|---|---|
| `kriko-gpui/` | The desktop app (Rust, GPUI). It supervises the sidecar and draws the interface. It holds no engine logic. |
| `src/app/` | The interfaces: the command line, the local HTTP API, the MCP server, and the operator console. |
| `src/app/pipeline/` | The drivers that run the evidence ledger of a category and repair its gaps. |
| `src/kriko/` | The engine: the store, the lookup, the ranking, and the gates. It imports none of the others. |
| `packs/` | One folder per category: the data, the vocabulary, the trust tiers, and the builder. |
| `packs/<name>/pipeline/` | The evidence ledger and the grounded extraction of one category. |
| `extension/` | It reads a listing page and draws the panel. |

Three rules keep the layout true:

1. `src/kriko/` must not import a package above it. This rule carries the
   design. An engine that knows one category ends the data-only category.
2. Kriko reads a catalog through the store. It never imports a catalog.
3. An upward import inside a function body is a defect. It hides the same
   mistake.
   `src/app/pipeline/tests/test_repo_invariants.py` enforces the rules.

## Where do I read for a question?

| Your question | Read first |
|---|---|
| A listing becomes a panel | `extension/content.js`, then `src/app/web/routers/analyze.py`, then `src/kriko/lookup/match.py` |
| A problem did or did not appear | `src/kriko/lookup/rank.py`, `src/kriko/lookup/conditions.py`, `src/kriko/gates.py` |
| What a catalog contains | `packs/drill/` (the smallest complete example), then `src/kriko/pack/manifest.py` |
| Build and install a catalog | `src/kriko/pack/build.py`, then `src/kriko/store/packstore.py` |
| Evidence and quotations | `packs/<name>/pipeline/ledger/`, then `src/kriko/ledger/`, then `src/app/pipeline/ledger_run.py` |
| A refusal | `src/app/mcp_server.py`, `src/kriko/gates.py`, and the vocabulary of the catalog |
| The engine supervisor | `kriko-gpui/src/engine.rs`, then `src/app/sidecar.py` |

Start with these files:

| Package | Read first |
|---|---|
| `kriko-gpui/` | `kriko-gpui/README.md`, then `kriko-gpui/src/engine.rs` |
| `src/app/` | `src/app/cli.py`, then `src/app/sidecar.py` |
| `src/app/pipeline/` | `src/app/pipeline/ledger_run.py` |
| `src/kriko/` | `src/kriko/store/packstore.py` |
| `packs/` | `packs/drill/` |
| `extension/` | `extension/content.js` |

## Which command starts what?

| Command | Function |
|---|---|
| `kriko` | The command line: install, build, list, and look up a catalog |
| `kriko tui` | The operator console |
| `kriko model-bench` | Measure models on a fixed corpus: tokens, fabrication, abstention. Writes a JSON, two CSVs and a report. See [MODEL_BENCHMARK.md](MODEL_BENCHMARK.md) |
| `python -m app.modelbench` | The same benchmark without the `kriko` command. `list`, `plan`, `run` |
| `python -m app.mcp_server` | The MCP server, for an agent that reads by itself |
| `python -m app.pipeline.ledger_run` | The ledger stages |
| `python -m app.pipeline.panel` | The spend, the coverage, and the recent runs |
| `python -m app.pipeline.process` | One product from end to end |
| `python -m app.web` | The local API on `http://127.0.0.1:8787`. The interactive API is at `/api/docs`. |
| `python -m packs.<name>.build` | The build of one catalog |
| `python -m packs.<name>.coverage` | The coverage report of one catalog |

The sidecar is the engine as a child process. It selects a free port and prints
`KRIKO_PORT <n>` as its first line. `kriko-gpui/` polls `/api/health` until the
engine answers.

Kriko uses two databases on purpose. The engine store is
`~/.kriko/knowledge.sqlite`, and the history and the settings are
`~/.kriko/app.sqlite`. The removal of a catalog must not remove your history,
and your history must not change the digest of a catalog.

## Run the tests

Set up a working tree once:

```bash
tools/setup.sh
```

Then run the gate before each push and each merge:

```bash
tools/gate.sh          # everything
tools/gate.sh py       # the Python suite only
tools/gate.sh node     # the JavaScript suite only
tools/gate.sh gpui     # the desktop app only
tools/gate.sh wheel    # the shipped wheel only
```

On Windows, use `.venv\Scripts\python.exe` in place of `.venv/bin/python`. The
gate holds these stages: the version strings, ruff, mypy three times, pytest,
the shipped wheel, the JavaScript suite, and the Rust check and tests of the
desktop app. `pytest.ini` fixes the test folders.

To run the Python suite alone:

```bash
.venv/bin/python -m pytest
```

## Build and install a catalog

```bash
kriko build packs/<name>     # a folder becomes a .kpack file
kriko packs                  # the installed catalogs
kriko install <file.kpack>   # add one
```

## Build the desktop app

The installer recipe, the macOS build, and the artifacts are in
[kriko-gpui/README.md](../kriko-gpui/README.md).
