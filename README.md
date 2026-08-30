# Kriko

A local-first, open **knowledge engine for manufactured products**. It answers one
question — *what is known to go wrong with this specific one?* — from knowledge **packs**
you install, and it runs entirely on your machine.

Pack #1 is `cars`: a Chrome extension that surfaces known reliability risks for a specific
used-car variant on Sahibinden.com, **before** the buyer books an expert inspection. Not a
generic checklist — signal specific to *this exact engine and gearbox*, predictable from
the listing data alone.

The engine knows nothing about cars. `packs/drill/` is a cordless drill with no engine, no
fuel and no displacement, wearing out in charge cycles instead of kilometres — it exists to
keep the car assumptions out of the core. Adding a product category is a data change.

---

## Design principles (read before contributing)

The rules that shape every decision live in `CLAUDE.md`; the short version:

1. **Product principle — high-value claims only.** Surface config- and usage-specific
   known risks the buyer can't cheaply get from a standard inspection. Each pack states
   its own bar in `packs/<name>/research/principle.md`; for cars, if the ekspertiz would
   catch it anyway (fluids, brake wear, warning lights), it's noise.
2. **Scalability principle — no hardcoded product data, no orphan patches.** Anything that
   grows with coverage must be *derived from the catalog YAMLs*, never hand-enumerated in
   Python. Every per-model fix must ship with the mechanism (validation, coverage report,
   telemetry) that catches the same class of problem for every future product.
3. **Layering — `kriko/` imports nothing.** The engine may not know what a car is. This is
   enforced mechanically, not by convention: `app/pipeline/tests/test_repo_invariants.py` and
   `kriko/tests/test_core_is_domain_free.py`.

Task tracking: open work in [`backlog.md`](backlog.md), finished work in [`done.md`](done.md).

---

## What it shows

- **Maintenance intervals due from usage** — timing belt at 90k km on K9K, DSG service on
  a high-mileage DQ250; flagged "due unless the ad proves otherwise"
- **Known-weak-point failures** — specific to this engine code and gearbox revision, gated
  by mileage/age/model-year windows where the evidence supports one
- **Honest uncertainty** — a condition the listing can't answer ("fails after 150k" with no
  odometer stated) is neither hidden nor asserted: it is shown, downranked, with the reason
- **Disagreement preserved** — two packs may contradict each other. Nothing is merged away;
  the rebuttal is shown and the claim ranks lower

A per-listing cap keeps the panel readable instead of encyclopedic.

---

## Architecture

```
Chrome extension  ─→  POST /analyze  ─→  app/web
                                            │
site adapter (pack-declared selectors)  ────┤   raw scrape → identity dict
                                            │
kriko.lookup:  match ─→ conditions ─→ rank ─┤   no LLM on the request path
                                            │
                            ranked claims ──┘   ← the installed packs, one SQLite store
```

Four packages. Dependencies form a fan, not a column:

- **`kriko/`** — the engine. Pack store (install/enable/uninstall), generic lookup,
  three-state condition evaluation, read-time ranking, the `Researcher` interface.
  Imports none of the others and contains no category vocabulary.
- **`packs/`** — one directory per product category: data, vocabulary, source trust tiers,
  its own product principle, a builder, a site adapter, and the coverage report for its own
  catalog shape. This is what a third party authors, and it is data plus a builder — never
  code that runs inside the engine.
- **`kriko/ledger/` and `kriko/extract/`** — generic evidence ledger and grounded
  extraction primitives; they turn sources into pack-owned claims without category logic.
- **`app/`** — the interfaces: CLI, local web dashboard, and MCP server.
- **`app/pipeline/`** — orchestration drivers (`ledger_run`, `remediate`, `panel`, `process`).
- **`packs/cars/pipeline/`** — cars-only acquisition, catalog, fitment, export, and research policy.

See the layering principle in `CLAUDE.md` for the four greps that enforce this.

### Slots are rows, not columns

The pivot rests on one schema change. A `variants` table assumes every subject has a make,
a model, an engine code and a displacement — already false for an EV, hopelessly false for
a drill. Everything is instead subject/attribute/value rows carrying a `pack_id`.

Two consequences worth knowing before reading the code: **identical facts from two packs do
not collapse into one row** (`pack_id` is in every primary key, so uninstalling one pack
cannot delete a fact another still asserts — dedup is a read-time `GROUP BY`), and **there
is no central authority** (contradicting claims coexist; ranking happens at read time).

### The "Lego" system

Research is done once per **part revision**, not per product model. A claim on
`packs/cars/data/parts/engine/ea211.yaml` applies to every variant of every model whose
fitment row says `engine_family: ea211` — onboarding a new EA211-engined car inherits the
research for free.

### File layout

```
kriko/
  store/       schema, content-addressed ids, pack install/uninstall
  lookup/      match, conditions (met/unmet/unknown), rank, query
  pack/        manifest + generic builder
  research/    Researcher protocol: agent ($0, via MCP) and API (Exa/Tavily + LLM)
  adapters.py  declarative site-adapter runner (selectors + a closed transform vocabulary)
packs/
  cars/
    data/variants/{make}_{model}.yaml   trim configs: cc, hp, fuel, tx, years
    data/fitment/{make}_{model}.yaml    variant_id → engine_family/tx_code/… (derived)
    data/parts/{type}/{code}.yaml       the claims themselves, per part revision
    vocabulary/  trust/  research/      terms, components, source tiers, principle
    adapters/sahibinden.json            the extension's DOM knowledge, as data
    build.py  coverage.py               YAML → .kpack; catalog-hole report
    pipeline/                            cars-only research/acquisition pipeline
  drill/                                synthetic second pack — the car-shape falsifier
kriko/
  ledger/      generic ledger DB, ingest, chunking, clustering, costs
  extract/     generic grounded extraction helpers
  store/       installed pack revisions and active-read projection
app/
  cli.py       kriko packs | install | uninstall | enable | build | lookup
  web/         local dashboard + /analyze (FastAPI, 127.0.0.1:8787)
  mcp_server.py  stdio MCP server — the $0 agent control plane
app/pipeline/           ledger_run.py remediate.py panel.py process.py
extension/  Chrome extension (content.js scraper + panel)
logs/analyses.jsonl   every /analyze request+response
```

---

## Setup

### Requirements

- Python 3.11+. No Docker, no Postgres — the store is a single SQLite file at
  `~/.kriko/knowledge.sqlite`.
- Only for *running the research pipeline*, never for serving:
  `MISTRAL_API_KEY` (extraction + judge gates), `EXA_API_KEY` (source discovery).
  Keys live in the repo-root `.env`. The `$0` agent research plane needs neither.

### Build and install a pack

```bash
python -m packs.cars.build                  # → dist/cars.kpack
python -m app.cli install dist/cars.kpack
python -m app.cli packs                    # what is installed, and its trust weight
```

Authoring a pack for a new category? `docs/PACK_CONTRACT.md` states the required
minimum and the optional parts, with `packs/drill/` as the copy-this-first example
and `packs/cars/` as what a mature pack grows into.

### Ask it something

```bash
python -m app.cli lookup make=volkswagen model=golf year=2015 fuel=diesel \
    transmission=automatic --ctx usage_km=190000 -v
```

Identity is passed as bare `key=value` pairs, not `--make/--model` flags: the keys are
pack-declared data, so the CLI can only pass them through opaquely. `-v` shows why each
claim ranked where it did, and its sources.

### Start the local app

```bash
python -m app.web            # dashboard + /analyze on http://127.0.0.1:8787
```

### Load the Chrome extension

Chrome → `chrome://extensions` → Developer mode → Load unpacked → select `extension/`

### Tests

```bash
python -m pytest      # all tests — testpaths in pytest.ini
npm test              # extension scraper (jsdom)
```

Run `pytest` with no arguments. Naming directories by hand is how the suite quietly shrank
once already: `pytest backend knowledge` collected 576 of 761 tests after `app/pipeline/` was added,
skipping every test in `app/pipeline/tests` without failing.

---

## Growing the knowledge base

```bash
# 1. Bootstrap a new model: variants scaffold + fitment derived from it
python -m packs.cars.pipeline.catalog.discover --make volkswagen --model golf_7 --write-variants
python -m packs.cars.pipeline.catalog.discover --make volkswagen --model golf_7 --write-fitment

# 2. Acquire sources for the part, then run the ledger pipeline
python -m app.pipeline.ledger_run acquire --part dq200 --part-type transmission
python -m app.pipeline.ledger_run all

# 3. Re-run gates only — zero token cost, uses cached candidates
python -m app.pipeline.process --part dq200 --part-type transmission --skip-extraction

# 4. See what is still missing, then rebuild and reinstall
python -m packs.cars.coverage
python -m packs.cars.build && python -m app.cli install dist/cars.kpack
```

There is no human approval step anywhere in that sequence, by design — see the automation
principle in `CLAUDE.md`. Where a value can't be derived, the pipeline fails open (emits no
claim) and the gap shows up in `coverage`. Full operational detail is in `docs/USAGE.md`.

---

## Supported cars (TR market)

| Make | Model | Generation | Engines | Gearboxes |
|------|-------|------------|---------|-----------|
| Renault | Mégane | IV (2016–2023) | K9K 1.5 dCi · R9M 1.6 dCi · H5F 1.2 TCe · H5H 1.3 TCe | manual · DC4 EDC · DW5/DW6 EDC* |
| Renault | Clio | V (2019–) | H4D 1.0 SCe · H5D 1.0 TCe · H5H 1.3 TCe · K9K 1.5 dCi | manual · DC4 EDC |
| Volkswagen | Golf | VII (2013–2020) | EA211 1.0/1.2/1.4 TSI · EA288 1.6/2.0 TDI · EA888 2.0 TSI (GTI/R) | manual · DQ200 · DQ250 · DQ381 DSG |

\* DW5/DW6 (7/6-speed wet EDC) part files exist but are **unresearched stubs**. Rather than
fixing those two by hand, the gap is owned by the auto-remediation loop (backlog B19) — see
the generalization principle for why per-model fixes don't exist here.

---

## Docs

| Doc | Contents |
|-----|----------|
| `backlog.md` / `done.md` | Task tracking — goals, open items, finished work |
| `CLAUDE.md` | Product, scalability, automation and layering principles; doc map |
| `CONTRIBUTING.md` | Branches, commits, test gates, what CI checks |
| `packs/<name>/README.md` | What that pack covers, and its own product principle |
| `docs/ARCHITECTURE.md` | Reading map — where to start, what each package owns |
| `docs/USAGE.md` | Full operational guide (stack, pipeline, claim lifecycle) |
| `docs/INTERNALS.md` | Mechanism-level architecture reference |
| `docs/PACK_CONTRACT.md` | What a pack must contain, and what it may |
| `docs/design_flaws.md` | The 2026-07-04 audit — root causes behind claim mismatches |

Everything under `docs/historical/` predates the part-centric system, or predates the pivot
that made Kriko category-free — `handover.md` and `SCAFFOLD.md` describe the old
model-centric flow, `thoughts/` holds superseded 2026-07 designs and plans, and
`overhaul_plan.md` / `claim_relevance_plan.md` / `pipeline_postmortem.md` are the pre-pivot
claim-quality roadmap and pipeline history. Historical context only; don't follow their
instructions.
