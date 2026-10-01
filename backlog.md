# Kriko: the backlog

Open work, and where the work stands. One file, no second status list, so
nothing here can quietly disagree with the tree.

**Reset 2026-10-01.** The 1.0 list written on 2026-09-29 ran B155 to B189.
B155 to B183 are on `main`. B181 and B184 to B188 are written but sit on two
branches that were never merged. B189, the release, is the only item with
nothing written at all. What came before the 2026-09-29 reset is in
`docs/historical/backlog-2026-09-29.md`, and everything before that is in
`git log`.

How to use this file:

- Read `docs/DOCTRINE.md` first. Every item quotes the request, names the
  screen, and says what counts as done.
- A finished item **leaves this file**. Its commit message says what changed,
  what was observed and why; `git log` is the record. There is no archive of
  finished work to fall behind, because there is no archive.
- One agent and one PR per item. Items in the same phase can run in parallel
  unless they touch the same screen.
- "Found" lines record what was measured, and on which day. Check a line
  number before relying on it.

## Rules for every item (the reader, 2026-09-29)

These apply to every screen and to the browser extension. B159 to B162 put
them in place and every later PR keeps them.

- **Typeface:** IBM Plex Mono everywhere.
- **Theme:** Panel only. There is no theme choice.
- **Emphasis:** italic marks anything different or important.
- **Controls:** buttons and every other control (select, input, tab, file
  button) look raised, like a button.
- **Headings:** every section heading carries a symbol.
- **Words:** no em dashes; no informal phrasing; at most one line under a
  heading, with anything longer behind an expander; a professional name for
  every feature.

The rules in `CLAUDE.md` still hold, and several items depend on them:

- `ui/` carries no vocabulary from any catalog. Category names, filters and
  specification fields come from API rows.
- `kriko/` stays free of any product category.
- Model and category lists are read from the tools installed on the machine
  or from the catalogs, never typed into the source.
- A bundle-budget raise is recorded with its reason, not avoided.

## Decisions only the reader can make

Each decision has a default, so no work waits on it. The reader confirmed
D1, D3, D4 and D5 on 2026-09-29; D2, D6 and D7 stood as defaults and are
recorded below with what happened to each.

| # | Question | Decision |
|---|---|---|
| D1 | What the UI calls a catalog, the authoring role, and "analyze" | **Decided (2026-09-29).** A pack is a "Catalog" on screen. "Analyze" is "Check". The authoring role disappears with the Buyer/Author switch (B165). Code, API and docs keep `pack`. Landed. |
| D2 | Provider marks are trademarks | **Default held.** Each vendor's own published mark, small and monochrome, for each provider the app already detects. Landed as `ui/src/lib/ProviderMark.svelte`. |
| D3 | The local plane needs a search service, and the obvious one has no Windows install story | **Decided (2026-09-29).** Use it when it answers; otherwise fall back to a keyless hosted search, so a local model alone is enough to run. Bundling waits on a licence check, which is B192. |
| D4 | Does "remove every package" include the two packs the installer seeds | **Decided (2026-09-29).** Yes on this machine, and they stay removed after a restart. The 1.0 installer still carries them for a new install. The reset itself is B188. |
| D5 | Removing the agenda, the build button and the schedule leaves nothing that starts a run over a whole category | **Decided (2026-09-29).** The category-wide run and the schedule loop go, with their endpoints. Research starts per product: on the Run screen, from Browse, or from the extension. Landed. |
| D6 | Where the benchmark's fixed test set lives | **Default held.** A versioned set shipped with the app. It is neither a catalog nor stored in the knowledge store. Written on `origin/vibe/kriko-overhaul-remaining`; landing it is B185. |
| D7 | "Agents on this machine" holds the only connect and skill buttons | **Default held.** The section goes. Each agent's row in Agents gains its connection state and one action. Landed. |

## Where the work stands (2026-10-01)

- `main` is **0.10.16**. The gate is local (`tools/gate.sh`); the installer
  workflow is hand-run only, because the account has no Actions minutes.
- The rail is four groups holding thirteen destinations: **Check** (Home, Run,
  History, Compare, Browser extension), **Knowledge** (Overview, Browse),
  **System** (Sites, Activity, Agents, Benchmark) and **This install**
  (Settings, About). `ui/src/lib/shell/nav.ts` also keeps fourteen retired
  addresses resolving to whatever absorbed them, so an old bookmark never lands
  on "no such view".
- Two agents wrote the last six items independently, on two branches, and
  neither is on `main`. They disagree on the same screens, so one has to be
  chosen rather than both merged. That is B190, and nothing else can be
  called done until it lands.
- `tools/journeys/` does not exist. The 1.0 release criterion is written
  against journeys that have never been written, which is B191.

## Phase 0: land what is already written

Nothing in this phase is new work. Each item is written, reviewed once, and
sitting on a branch. Per `docs/DOCTRINE.md` §2 an item is not done until it
is on `main`, so all six are open.

### B190: One branch wins, and the six items land
**Asked:** the standing rule, "let's do a stable version to do list" (2026-09-29); nothing new on 2026-10-01.
**Where:** `main`, and the six items below.
**Found (2026-10-01):**
- Two branches each implement B181 and B184, and `origin/vibe/kriko-overhaul-remaining` adds B185 to B188 on top.
- `b181/sites-settings`: `669705f`, `4821618`. It builds filters as `ui/src/lib/ListFilter.svelte` plus `ui/src/lib/filter.ts`, and site detail as `ui/src/lib/SiteDetail.svelte`, with `test_site_detail_and_amend.py`.
- `origin/vibe/kriko-overhaul-remaining`: `90df6fd`, one squashed commit, same six items. It has no filter component and a different site router, and it empties the reader-words baseline.
- Both sit on `3022cee`, which is `main` without the 0.10.16 version bump, so a merge is small. Merging *both* is not: `git merge-tree` reports eight content conflicts, and the two branches touch the same files with different designs rather than different lines of the same design.
- Neither branch bumped the version string, so both still say 0.10.15.

**Done when:**
- One implementation of B181 and B184 is on `main`, the other branch is closed with a note saying which won and why.
- B185, B186, B187 and B188 are on `main` from the surviving branch.
- The version is bumped past 0.10.16 by `tools/bump.py`, and the installer is built from that tree.
- `tools/gate.sh` is green on `main` after the merge, and a walk of the touched screens is clean.

**Not this:** merging both and reconciling by hand. Two answers to one request is a decision for the reader, not a merge conflict.
**Owner:** free. Blocks B189.

### B181: Sites shows what each site gives, and can be amended
**Asked:** "Sites: remove unnecessary descriptions", "Sites: show detailed info about what is being seen from the added sites", "Sites: allow amendments to that info" (2026-09-29)
**Where:** System, Sites.
**Found (2026-10-01):** both branches implement it; neither is on `main`. `src/app/sites.py` grows from 392 lines to 495 on one and 466 on the other, and `/api/sites` gains the rules each site reads, the labels it sees but does not map, its match patterns and its last sample page. A learned site's mapping is amended through a checked `PUT`; a shipped one is read-only, and an override for it is kept on this machine.
**Done when:** each site expands to the fields it reads, the labels it does not map, its match patterns and a sample page; a learned mapping can be changed there and is checked before it saves; a shipped site is marked read-only and its override stays on this machine.
**Not this:** editing a shipped adapter in place.
**Owner:** free. Lands with B190.

### B184: Filters on the System screens, and a new Settings
**Asked:** "Add more filters", "Redo Settings: it looks very ugly, remove unnecessary descriptions, polish it" (2026-09-29)
**Where:** the System screens that hold lists (Activity, Sites, submissions) and Settings.
**Found (2026-10-01):** on `main` only the Live lens has filters. Settings is three sections (Closing the window, Check a provider key, What is remembered), each with a paragraph, and the last one dumps every stored setting as raw key and JSON value. Both branches cut this; the two disagree on how the filter is built.
**Done when:** each System list has a search box and a state filter; Settings is a short set of sections with one-line labels; the dump of stored settings is gone or folded.
**Not this:** ever showing a key's value.
**Owner:** free. Lands with B190.

### B185: Benchmark, rebuilt
**Asked:** "Make it intuitive, currently info and options are spat out with no structure", "Use fixed tests, not the user's installed packs (packs are made with agents anyway)", "Copy the structure of current LLM benchmark systems", "Make models comparable" and six more (2026-09-29)
**Where:** System, Benchmark (`ui/src/routes/Bench.svelte`, `src/app/bench.py`).
**Found (2026-10-01):** ground truth is read from `research/gold.yaml` in the pack (`src/app/gold.py`), and no pack ships one, so the benchmark runs on whatever is installed and hallucination reads "not yet measured". The screen meanwhile says every row is "measured against ground truth this pack's author" supplied (`ui/src/routes/Bench.svelte:266`). About 30 model chips sit in one wall. `90df6fd` adds `src/app/benchcases.json` (184 lines) and `src/app/benchcases.py`, ranks per set, and gives every plane a one-line meaning.
**Done when:** the benchmark runs a fixed, versioned test set, identical on every machine; results read as a leaderboard, one sortable row per model, each expanding to per-case detail; graphs put models on shared axes; runs scored on different sets are never ranked together; each plane has a one-line meaning.
**Not this:** measuring the reader's own catalogs.
**Owner:** free. Lands with B190. Decision: D6.

### B186: The extension follows the same rules
**Asked:** "Remove excess wording and phrases like \"one click\"", "Keep only the extension connection, plus logs if the user asks", "Remove the long descriptions, keep only what is needed", "Apply the global design foundations from section 1" (2026-09-29)
**Where:** the Browser extension screen in the app, the in-page panel, and its options page.
**Found (2026-10-01):** the app screen is seven cards, one of them headed "One click", and the last lists the sites an installed catalog can read, which duplicates Sites. The panel uses system fonts first. The options page has five paragraphs for one field. There is no log view. `90df6fd` cuts all four.
**Done when:** the Browser extension screen shows its connection status with folded Log and Files sections; the panel and options page use the house type, colours, raised controls and section symbols, with no paragraph longer than a line.
**Not this:** a site's own vocabulary in `extension/`, which `test_the_extension_speaks_no_sites_own_language` forbids.
**Owner:** free. Lands with B190.

### B187: The sweep, where every word earns its place
**Asked:** "Remove every unprofessional phrase (\"what is this\", \"throw it away\", \"cover the gaps\", etc.)", "Cut wording everywhere, there are too many words", "Remove all em dashes" (2026-09-29)
**Where:** every screen, the extension, and the server messages that reach a screen.
**Found (2026-10-01):** on `main`, `tools/reader_words_baseline.json` still allows 118 em dashes and one informal phrase across 31 files, the worst being `ui/src/routes/Bench.svelte` at 18 and `ui/src/routes/Extension.svelte` at 13. `90df6fd` empties the baseline, which makes the guard absolute rather than a ratchet.
**Done when:** the ratchet baseline is empty; a walk of every screen and the extension finds no paragraph under a heading and no informal phrase, including in the messages the server sends.
**Not this:** raising the baseline. A count above it is a reword, never a new allowance.
**Owner:** free. Lands with B190.

### B188: A clean install, rebuilt by the new flow
**Asked:** "Remove every package so you can rebuild them" (2026-09-29)
**Where:** Settings (one reset action) and Browse.
**Found (2026-10-01):** on `main` no reset exists. The two seeded catalogs come back at the next start, because `app/bundledpacks.py` seeds any missing pack. Drafts persist under `~/.kriko/drafts` and block a new draft of the same name. `90df6fd` adds `src/app/cleaninstall.py` and a refusal to reseed.
**Done when:** after one confirmed reset, Browse shows no catalogs and no drafts and a restart brings nothing back; history is kept; the knowledge is rebuilt by checking products through the B168 to B170 flow.
**Not this:** deleting history or settings.
**Owner:** free. Lands with B190. Decision: D4.

## Phase 1: what 1.0 still needs

### B191: The journey checks the release criterion is written against
**Asked:** "okay let's do a stable version to do list" (2026-09-29); the 1.0 list's own criterion names a directory that does not exist.
**Where:** `tools/journeys/`, run by `tools/walk.sh`.
**Found (2026-10-01):** `tools/walk.sh` exists and presses every button on every screen. `tools/journeys/` does not exist at all. `docs/DOCTRINE.md` §4 names it as the one check that counts, and B189's release criterion is written against it.
**Done when:** `tools/journeys/` holds one script per reader task, each passing headlessly: load the extension and check in; check a listing and read the risks; research one subject and see the catalog gain claims; change a model or an effort and read the next command line; install, disable and update a catalog and see lookups follow; register a site and see the extension read it.
**Not this:** a journey that presses a button and asserts a row exists. Each one states the reader's end result, the way a "Done when" does.
**Owner:** free. Blocks B189.

### B192: Whether the local search service can be bundled
**Asked:** not a new request. D3 (2026-09-29) recorded the reason this is still
open: the local plane searches through a self-hosted service that "is not
installed here and has no Windows install story", so the decision was to fall
back to a keyless hosted search for now and to bundle the local one only if its
licence allows.
**Where:** `pyproject.toml`, `packaging/`, and the local plane's settings.
**Found (2026-10-01):** the local plane falls back to a keyless hosted search, so a local model alone can run. The local service itself is not bundled, and nothing in the tree records whether its licence permits redistribution. The answer decides whether a fresh install can search with no network at all.
**Done when:** the licence is read and the answer is written here with the date and where it was found; if it permits bundling, the service is an optional extra and a fresh install can search offline; if it does not, the hosted fallback is documented as the only path and this item closes.
**Not this:** a guess, and not a silent dependency on a service the reader did not install.
**Owner:** free. Decision: D3.

### B189: 1.0.0
**Asked:** "okay let's do a stable version to do list" (2026-09-29)
**Where:** the installer and every screen.
**Found (2026-10-01):** the temporary app-first section of `CLAUDE.md` ends when the reader confirms that a double-clicked install opens and runs a check. That has not happened for any version; every installer so far was built by hand and the reader confirmed behaviour from a screenshot.
**Done when:**
- A double-clicked 1.0.0 installer opens, and every journey in `tools/journeys/` passes on it.
- The reader runs a check from the extension and says it works.
- 1.0.0 is published as a release.
**Not this:** code signing, unless the reader asks. SmartScreen still warns on an unsigned installer.
**Owner:** free. After B190 and B191.

## Paused, and why

- **B142, the gate on the reader's own Windows machine.** Stays paused while the account has no Actions minutes, for the reason in the temporary section of `CLAUDE.md`. The installer recipe (`desktop.yml`) is untrimmed and hand-run; restoring the triggers is `git revert` plus a billing change, in that order.
