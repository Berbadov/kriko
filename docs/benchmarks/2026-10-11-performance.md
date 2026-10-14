# Performance, 2026-10-11

What was measured, what changed, and what it did. The reader-facing numbers
are the endpoint latencies: the extension asks `/api/lookup`, `/api/search`
and `/api/adapters` on every page it reads.

## Headline

| Request (keep-alive, 200 calls, p50 / p95) | Before | After |
|---|---|---|
| `GET /api/health` | 48.0 / 52.0 ms | 3.4 / 5.3 ms |
| `GET /api/adapters` | 48.0 / 52.1 ms | 5.6 / 8.7 ms |
| `POST /api/lookup` | 60.0 / 67.3 ms | 14.6 / 21.6 ms |
| `GET /api/search?q=clio` | 48.0 / 52.1 ms | 6.2 / 8.4 ms |

The engine's own lookup, in process and without HTTP: **6.4 ms → 2.2 ms** (p50),
10.7 ms → 2.5 ms (p95).

Most of the drop is one socket option (see change 1). The rest is in the
lookup and health code.

## Setup

- Packs: `packs/cars` (47 subjects, 699 claims) and `packs/drill`
  (6 subjects, 4 claims), built with `python -m app.cli build` and installed
  with `python -m app.cli --store STORE install`.
- Every sidecar ran with `HOME` set to a throwaway directory, on a copy of the
  store, with `KRIKO_NO_PACK_AUTOUPDATE=1`.
- The machine has 4 CPUs and was shared with other sessions. Load average
  was 1 to 3 during the final runs. Wall-clock startup noise was about ±50 ms
  from run to run.

Reproduce:

```bash
python tools/bench_endpoints.py --store STORE --requests 200
python tools/bench_startup.py --runs 3 --store STORE
python tools/bench_startup.py --runs 3 --store STORE --reuse-home
python tools/bench_startup.py --runs 3 --store STORE --repo PATH_TO_OTHER_CHECKOUT
```

## Startup

Import of the web app (`python -X importtime -c "import app.web.app"`):

| | Before | After |
|---|---|---|
| Root total, median (interleaved, 5 runs each) | 691 ms | 661 ms |
| Wall time, `python -c "import app.web.app"`, median (5 runs each) | 835 ms | 796 ms |

Within noise. An earlier, separate run before any change gave 654.5 ms
(median of 3). The import graph did not change, and the import is the same
set of modules. Top cumulative costs before the change (median of 3 runs):

| Module | ms |
|---|---|
| `fastapi` | 291.6 |
| `fastapi.routing` / `.params` | 281.6 / 203.7 |
| `fastapi.openapi.models` | 102.3 |
| `app.web.jobs` (pulls `app.prefs`, `app.providers`, `kriko.research`) | 44.2 |
| `app.prefs` | 42.7 |
| `app.providers` | 40.7 |
| `anyio` | 37.4 |
| `app.web.routers.agenda` | 31.7 |
| `pydantic` | 28.9 |
| `app.web.routers.extension` | 28.5 |

Most of the import is FastAPI route construction and pydantic model creation,
which happen when the routers are imported. The `app.prefs` and
`kriko.research` chain is imported by router modules that stay in the app, so
deferring it inside `jobs.py` saves nothing. Not changed.

Launch to first healthy answer (`tools/bench_startup.py`, median of 3):

| | Before (port / health) | After (port / health) |
|---|---|---|
| Cold home, every run | 730 / 1003 ms | 760 / 1052 ms |
| Warm home, after one discarded start | 729 / 922 ms | 745 / 939 ms |

Wall-clock startup did not move beyond noise. The change to the lifespan
(change 5) saves about 16 ms per start, which is inside that noise.

Where the time goes now, one start on a fresh home (timestamps from a scratch
script, not committed):

| Stage | ms (approx.) |
|---|---|
| Interpreter start and imports of `app.sidecar` | 550 to 615 |
| `uvicorn` import and port announced | 30 to 35 |
| Lifespan before serving | 60 to 70 (up to about 35 of it creates `app.sqlite`'s schema on a fresh home; about 3 ms on a steady start) |
| First `/api/health`, FastAPI building state for 155 routes | 100 to 130 |

The last row is not removed. FastAPI 0.138 builds route state lazily on the
first request and caches it, so moving it earlier does not shorten the time to
the first answer. Cutting it needs fewer routes, which is a design change.

## Changes

1. **Keep-alive responses waited about 43 ms (`src/app/sidecar.py`).**
   `reserve()` created the listening socket with `proto=0`. asyncio sets
   `TCP_NODELAY` on accepted sockets only when the listener's proto is
   `IPPROTO_TCP`. Without it, each response's headers and body went out as two
   writes, and Nagle held the body until the client's delayed ACK. Measured on
   one keep-alive socket: time to first byte 5 ms, time to full body 48 ms. A new
   connection per request took 3.5 ms. Fixed by passing `IPPROTO_TCP`.
   Effect: every endpoint, 40 to 45 ms less per request.

2. **YAML parsed on every lookup (`src/kriko/lookup/match.py`).**
   `load_terms` called `yaml.safe_load` on every term's `match_json` on every
   request: 64 parses per lookup, a third of its time under profile. The parse
   is now memoised by the text (`functools.lru_cache`, keyed by the text, so a
   reinstalled pack with different rules is a new key). Effect: part of the
   engine lookup drop from 6.4 to 2.2 ms.

3. **Title tokens rebuilt on every comparison (`src/kriko/text/title_sim.py`).**
   `cluster` compares each claim with each cluster head, and both titles were
   tokenised each time (18,200 tokenisations for 100 lookups). `similarity` now
   uses a memoised frozenset per title. `title_tokens` is unchanged. Effect:
   part of change 2's drop.

4. **Health read the package metadata on every call (`src/app/version.py`).**
   `app_version()` runs `importlib.metadata.version`, which scans every
   distribution on `sys.path`: 1.8 ms per call, most of a health answer. It is
   now cached for the life of the process, which is the version the process was
   started with. Effect: health 2.9 to 2.2 ms in the stepwise run.

5. **Startup rendered the agenda even when nothing would be written
   (`src/app/web/app.py`, `src/app/agentconfig.py`).**
   The lifespan rendered the agent skill with the agenda snapshot, which builds
   the lookup tree over every claim, and then found nothing to rewrite. The
   digest leaves the snapshot out, so staleness can be checked from the protocol
   alone. Startup now calls `skill_needs_refresh` first and renders the full
   body only when a wired copy is stale. Checked: the digest is identical with
   and without the agenda (a scratch script, not committed). Effect, in process:
   steady start lifespan 19.5 → 3.2 ms; first start 68 → 42 ms.

## Considered and not changed

| Candidate | Measured | Decision |
|---|---|---|
| Batch the per-claim conditions and evidence queries | 0.4 ms per lookup in total (38 claims) | Not worth the complexity |
| Pool the store and app-state connections per process | Opening a connection is about 0.7 ms, mostly the schema load a query needs anyway | Not worth the thread-ownership risk the store module documents |
| `PRAGMA synchronous = NORMAL` for history writes | Commit 0.37 ms less per lookup | Durability change for a small gain; declined |
| Defer `app.prefs`, `kriko.research` and `yaml` imports | Still imported by router modules | No saving on `import app.web.app` |
| Move the agent-skill refresh to a background thread | Would save the same work as change 5 | Racy with the skill tests, which read the file as the lifespan finishes |

## Verification

- **Engine answers.** A scratch script (not committed) runs every product
  subject in both packs, in two contexts, plus eight searches, against `HEAD`
  and against the changed tree. 64 lookups, 416 claims and 8 searches; the JSON is
  byte-identical.
- **Test suite.** `PYTHONPATH=src:. python -m pytest -q -p no:cacheprovider`
  before and after: the same 43 failing test IDs in both runs, none new, none
  fixed. These are the known failures owned by other areas.
- **Lint.** `ruff check` passes on every file touched.
- **Version and README.** Not bumped, as the author asked. The project's rule
  is that every change set bumps the version and updates `README.md`; that step
  is left to the reader.
