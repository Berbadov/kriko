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

## Download

The desktop app carries its own Python. Nothing to install, nothing to run
alongside it — **no Docker, no Postgres, no service**. Grab the installer for
your platform from the [latest release](../../releases/latest):

| Platform | File |
|----------|------|
| Windows | `Kriko_<version>_x64-setup.exe` |
| macOS (Apple Silicon) | `Kriko_<version>_aarch64.dmg` |
| Debian / Ubuntu | `Kriko_<version>_amd64.deb` |
| Any Linux | `Kriko_<version>_amd64.AppImage` |

Builds are **unsigned**: macOS calls it an unidentified developer (right-click →
Open) and Windows SmartScreen warns on the installer (More info → Run anyway).
Signing needs an Apple developer account and an EV certificate — backlog B52.

Everything lives in `~/.kriko`: `knowledge.sqlite` holds the packs you install,
`app.sqlite` holds your own lookup history. They are separate files on purpose,
so uninstalling a pack cannot drop your history. Uninstalling the app leaves
both.

Every release is built by `.github/workflows/desktop.yml` on three runners, and
each frozen sidecar has to answer a real lookup and run a real job
(`packaging/smoke_sidecar.py`) before it is allowed into a bundle.

### Staying current — two clocks

Knowledge changes far more often than the app does, so the two update
separately and neither waits for the other.

**Packs.** *Packs → Check for updates*. Kriko reads `packs.json` from the
latest release, compares each installed pack's version and content digest
against what is offered, and downloads only what is genuinely newer — a
renumbered pack with identical knowledge is not an update, and a version
republished with *different* knowledge is refused outright, because a version
is an immutable identifier. The download is verified against the index's
`sha256` before it is allowed near the store, and installs through the same
path as `kriko install`. Point it elsewhere with `KRIKO_PACK_INDEX`.

**The app.** Kriko asks on startup when a newer release exists, then downloads,
installs and restarts. Updates are verified against a minisign key baked into
the app — separate from OS code signing, which is why it works on the unsigned
builds above. Releases built without the signing secret simply ship no
self-update; the installers are unaffected.

Both leave `~/.kriko` alone.

---

## Install and run from source

Requires Python 3.13+. Same two SQLite files as the app above — a pack installed
by the CLI is visible in the desktop app and the other way round.

```bash
tools/setup.sh                   # one command: the venv, the locked deps, the
                                 # extras, both npm trees, and a check that the
                                 # installed version matches the tree

kriko build packs/cars           # → dist/cars.kpack
kriko install dist/cars.kpack
kriko packs                      # what is installed, and its trust weight

kriko lookup make=volkswagen model=golf year=2015 fuel=diesel \
    transmission=automatic --ctx usage_km=190000 -v

kriko tui                        # the operator console: planes, agenda, jobs, ops, shell
kriko prefs                      # or: costs, sites, verify, drafts, operations
                                 # — everything the dashboard's Settings/Sites/
                                 # Verify/Knowledge screens do, from a terminal
python -m app.web                # dashboard + /analyze on 127.0.0.1:8787
                                 # its Health tab shows the weakest-sourced
                                 # claims, worst first
```

`kriko` is on PATH after the install above; from a checkout without one,
`python -m app.cli` is the same command.

The dashboard is not a read-only view: researching a subject and building a pack
both run from it as **jobs** with a live log, a durable result and a cancel
button, so nothing that grows the knowledge base is terminal-only. A job whose
server died comes back marked `interrupted` rather than spinning forever.

Identity is passed as bare `key=value` pairs, not `--make/--model` flags: the keys are
pack-declared data, so the CLI can only pass them through opaquely.

Then load the extension. In the app, **Check → Browser extension** stages a copy to
`~/.kriko/extension/`, opens the folder, and tells you when the extension actually
reaches the app. From a checkout you can skip that: Chrome → `chrome://extensions` →
Developer mode → Load unpacked → select `extension/`.

Only *running the research pipeline* needs API keys (`MISTRAL_API_KEY`, `EXA_API_KEY` in a
repo-root `.env`) — never serving a lookup.

Run `tools/gate.sh` before pushing — pytest, both JS suites, types, and a check
that the committed frontend bundle still matches its source. It is what
`.github/workflows/ci.yml` used to run, moved here on 2026-09-13 when it became
clear the workflow had never once been allocated a runner. `CONTRIBUTING.md`
has the reasoning and the rest of the development loop.

### As a desktop app

`tauri/` wraps the same server in a window: a Rust shell spawns a PyInstaller
sidecar, waits for `/api/health`, and shows the UI — the identical UI a browser
gets, from the identical `~/.kriko/` store, so a pack installed in the app is
visible to `python -m app.cli`. Building it needs a Rust toolchain and Node;
neither the wheel nor the test suite does. See `tauri/README.md`.

Installers are built by `.github/workflows/desktop.yml`, which is **hand-run
only** as of 2026-09-13 — it needs Actions minutes this account does not have,
and a trigger that can only ever report a false failure is worse than none. Run
it from the Actions tab (`platforms: all` for the Linux and macOS legs), or
build on a Windows host with `pwsh packaging/build_desktop.ps1`, which is how
every installer since 0.5.0 was made. Nothing in the recipe was trimmed; putting
the `push` and `pull_request` triggers back is all that restoring it takes.

Locally, `packaging/freeze.sh` builds and smoke-tests the sidecar alone, which
needs no Rust toolchain.

The frozen sidecar is also the operator console: `kriko-sidecar --tui` runs the
same TUI as `kriko tui`, with no Python, no Node and no webview involved. On
Windows the installer puts **Kriko Console** in the Start menu pointing at
exactly that, so it is one click — no terminal to find, no flag to remember.
That is deliberate: a console whose reason for existing is a window that would
not open should not itself require a working toolchain.

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

## Growing the knowledge base

Kriko's default research plane costs **$0**, and that is a design decision
rather than a limitation. A Claude Code, opencode, Codex or Cline subscription
already includes web search and a model that can read. Kriko does not buy either
again — it says precisely what to look for, what counts as worth keeping, and
what shape to return, and lets the harness that is already paid for do the
reading (`src/kriko/research/agent.py`).

Wire the MCP server once — **System → Connect an agent** writes it into Claude
Code, Claude Desktop, Cursor or VS Code, verifies the command actually starts,
and installs a research skill built from the installed packs' own principles
(`.mcp.json` is also checked in, for a source checkout). Then hand a subject to
the research agent:

```
use the kriko_research agent to onboard renault megane_4
```

It asks the server for the work list, researches the trim lineup and submits it,
researches each part into the evidence ledger, and runs a pipeline pass. Every
write goes through an MCP tool that is deterministic or import-only, so nothing
it does can spend a token of Kriko's own money. `.claude/agents/kriko_research.md`
is generated from the pack — the agent works for whatever categories are
installed, not for cars specifically.

**The server is the referee.** Every rule in the agent's prompt is also enforced
in code at the write path, because a rule that lives only in a prompt is a rule a
cheap model can break and be told "OK":

| Refused | Why |
|---------|-----|
| A quote not literally in the submitted document | `add_evidence` checks it. An agent cannot cite a source it did not read. |
| A figure the agent could not source | Written `draft: true`, skipped by the build, raised in the coverage report. A visible gap, never a plausible invention. |
| `transmission_code: "7-speed DSG"` | "DSG" names three gearboxes; a claim attributed to it would contaminate its siblings. Find the unit code (`dq381`). |
| Warning-light and inspection-routine claims | The pack's own product principle, enforced rather than requested. |

A rejection names what would fix the row, and the contract forbids retrying it
reworded — fix the substance or report the gap.

**MCP is one door, not the only one.** The same three operations are commands,
for any agent that can run a shell and for the days the MCP connection does
not come up:

```bash
python -m app.cli agenda --pack cars               # what to research next
python -m app.cli brief <subject_id> --pack cars   # what to look for, and the queries
python -m app.cli submit <subject_id> findings.json --pack cars   # or `-` for stdin
```

They call the functions the MCP tools call (`src/app/agentops.py`), so a claim
submitted here is checked by the same grounding rule and the same pack gate, and
the operations feed labels it "the command line".

**The other two planes.** A paid API researcher (`backend: "api"`, with a
`budget_usd`) exists for unattended runs and is never the default: a tool that
starts spending because a key happened to be in the environment is a tool people
stop trusting. And from the app itself, the **Coverage** screen has a *Research*
button on every gap and the **Jobs** screen has a build form — both run as jobs
with a live log, a durable result and a cancel button. Note that the $0 plane
inside the app produces a *brief* rather than findings: there is no harness in
the desktop process to do the reading, and quietly falling back to a paid path
would turn "free" into a surprise bill.

Then build and install what the research produced:

```bash
python -m app.cli build packs/cars      # → dist/cars.kpack
python -m app.cli install dist/cars.kpack
```

Full walkthrough — trim research, the manual CLI fallback, the deterministic
catalog repair pass (`catalog.doctor --fix`), and gate evaluation — is
`docs/USAGE.md` §4.

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

## To do — research, not release

Ideas worth a month and no promises. None of these is a release item. Each one
records what was actually measured on 2026-09-23, so nobody has to redo the
first afternoon.

**Small local models as extractors, then fine-tuned ones.** The goal is to build
packs at no cost and without spending a subscription's limits. The first step is
the benchmark (B126), because without it nobody can tell whether a model is
good. The accepted ledger is the obvious training set, but it holds unverified
claims that `accept_findings` weights at 0.6, so a model trained on it learns
the gate's taste, not the truth.
- *Measured:* six real evidence pages, the real extraction prompt, and the real
  acceptance path on a throwaway copy of the store, all on CPU through Ollama.
- `qwen3.5:4b` returned nothing until two changes: a 16k context
  (`PARAMETER num_ctx 16384`) and thinking turned off
  (`reasoning_effort: "none"`). After that it produced one grounded finding on
  each of the 3 pages it finished before the run was stopped.
- `granite4.2:3b` returned `[]` on all six pages with the same settings. With
  the default context, one of its five proposals passed; the rest were
  unquotable, a JSON object instead of a list, or a URL without its scheme.
- *What the engine needs before this can work:*
  - `app.providers.llm.completer` can pass neither `num_ctx` nor
    `reasoning_effort`, so a local model is misconfigured the moment it is
    plugged in.
  - `_read` accepts only a bare JSON array. Any other shape, such as an object,
    is silently dropped.
  - Per-model confidence has to come from the benchmark rather than from which
    door the claim came through.

**Laya / Jev as the principle filter: an optional add-on, installed
separately.** The alternative is the orthodox, lower-compute way (the pack's
deterministic `gate_terms`), and it stays the default. Readers choose.
- *Measured:* zero-shot, on 40 cars claims, scored against the pack's own gate
  vocabulary.

  | Checkpoint | AUC | Agreement | CPU per claim |
  |---|---|---|---|
  | english | 0.61 | 21/40 | 1.5 s |
  | multilingual | 0.53 | 21/40 | 1.3 s |
  | typed-decisions | 0.46 | 21/40 | 2.3 s |

  All three score at chance, which matches Laya's own description: a fast base
  to specialise, not a zero-shot judge. Making it useful means a labelled set
  per pack and a fine-tune per pack. That is the month.

**MCP is demoted, then deleted.** The command line now offers the same three
operations (`agenda`, `brief`, `submit`) through the same functions. The MCP
server becomes a thin wrapper, and it goes away once the operations feed shows
nothing coming in through it.

**Obscura as a fetcher: tested, not adopted.** On 20 real evidence URLs it
grounded the same 6 quotes as the built-in reader. It read 2 pages the reader
could not, and neither contained the quote. It timed out on 2 pages the reader
handled, and it was about 3× slower (median 5.6 s against 1.7 s). It fetches;
it does not search, so it does not replace Tavily or Exa. If a site ever needs
JavaScript rendering, the most it could be is a fallback behind a flag, pinned
to a version. The same test surfaced B140: half the cars quotes are stored
wrapped in quotation marks, so they cannot be re-proven against their page.

---

## Where to go next

| Doc | For |
|-----|-----|
| `docs/ARCHITECTURE.md` | Reading the code — package layout, reading map |
| `CLAUDE.md` | The principles every change is judged against |
| `CONTRIBUTING.md` | Branches, commits, test gates, what CI checks |
| `backlog.md` / `done.md` | Open work and finished work — status, always current |
| `docs/USAGE.md` | Operating it, and growing the knowledge base end to end |
| `docs/HOW_IT_WORKS.md` | Four diagrams: page-to-pack matching, the pack lifecycle, a run, the layering |
| `docs/STYLE.md` | How these docs are written. Rules, not taste |
| `docs/INSTALL_WINDOWS.md` | Installing on Windows, start to finish, including the extension's permission step |
| `docs/PACK_CONTRACT.md` | Authoring a pack for a new product category |
| `tauri/README.md` | The desktop shell — launch sequence, failure surface, local build |
