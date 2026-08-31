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

## What it looks like

A real lookup against the installed `cars` pack, for a 2015 Golf, diesel, DSG, 190,000 km:

```bash
$ python -m app.cli lookup make=volkswagen model=golf year=2015 fuel=diesel \
      transmission=automatic --ctx usage_km=190000 --limit 3

match: exact  (1 subject(s))  coverage: RISKS_FOUND

1. [high] CP4.1 pump failure contaminates EA288 fuel system
   Volkswagen EA288 TDI  ·  fuel system  ·  relevance 0.270

2. [high] Clutch temperature sensor G509 failure in DQ250
   Volkswagen DQ250 6-speed wet DSG  ·  transmission  ·  relevance 0.270

3. [high] DQ200/DQ250 DSG solenoid valve electrical short-circuiting
   Volkswagen DQ250 6-speed wet DSG  ·  transmission  ·  relevance 0.270
```

Add `-v` and each claim also shows its check ("scan for DTC P0087..."), its sources and
their trust tier, and — for a claim the listing doesn't confirm or rule out — the reason
it's shown anyway but ranked lower.

---

## Install and run

Requires Python 3.14+. No Docker, no Postgres — the store is a single SQLite file at
`~/.kriko/knowledge.sqlite`.

```bash
pip install -e ".[dev,pipeline]"            # editable install; pipeline extra is
                                             # only needed to research, never to serve;
                                             # dev extra is needed to run the tests below

python -m app.cli build packs/cars          # → dist/cars.kpack
python -m app.cli install dist/cars.kpack
python -m app.cli packs                     # what is installed, and its trust weight

python -m app.cli lookup make=volkswagen model=golf year=2015 fuel=diesel \
    transmission=automatic --ctx usage_km=190000 -v

python -m app.web                           # dashboard + /analyze on 127.0.0.1:8787
```

Identity is passed as bare `key=value` pairs, not `--make/--model` flags: the keys are
pack-declared data, so the CLI can only pass them through opaquely.

Then load the extension: Chrome → `chrome://extensions` → Developer mode → Load unpacked
→ select `extension/`.

Only *running the research pipeline* needs API keys (`MISTRAL_API_KEY`, `EXA_API_KEY` in a
repo-root `.env`) — never serving a lookup.

Run the tests with `python -m pytest` (no arguments — `testpaths` is set in `pytest.ini`).

---

## What a pack is

A pack is data plus a builder, never code that runs inside the engine: a catalog of
subjects (`packs/<name>/data/`), the vocabulary and source-trust tiers for its category,
that category's own bar for what's worth surfacing, and a `build.py` that turns YAML into
an installable `.kpack`. The engine imports none of it — packs are consumed through the
store at read time, so installing a second category is a data change, not an engine change.

Two packs ship today: `cars`, the mature one described above, and `drill`, a deliberately
tiny synthetic pack — a cordless drill with no engine, no fuel, no displacement — that
exists to prove the engine has no car-shaped assumptions baked in. The full contract a pack
must satisfy, and what it may optionally add, is in `docs/PACK_CONTRACT.md`.

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

## Where to go next

| Doc | For |
|-----|-----|
| `docs/ARCHITECTURE.md` | Reading the code — package layout, reading map |
| `CLAUDE.md` | The principles every change is judged against |
| `CONTRIBUTING.md` | Branches, commits, test gates, what CI checks |
| `backlog.md` / `done.md` | Open work and finished work — status, always current |
