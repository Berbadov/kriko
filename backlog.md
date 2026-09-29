# Kriko: backlog for the first stable version (1.0)

This backlog was reset on 2026-09-29 at the reader's request: "make your own list please. reset the backlog." The list from before the reset is kept unchanged in `docs/historical/backlog-2026-09-29.md`, because code comments and `done.md` cite its B-numbers. Numbering continues from there, so B155 is the first item here.

How to use this file:

- Read `docs/DOCTRINE.md` first. Every item quotes the reader, names the screen, and says what counts as done.
- Finished items move to `done.md` with the date and commit, as before.
- One agent and one PR per item. Items in the same phase can run in parallel unless they touch the same screen.
- Phase 0 (broken today) and Phase 3 (engine) can start at once. Phase 1 (foundations) lands before any Phase 4 screen is restyled, because every screen depends on it.
- "Found" lines record what the survey of 2026-09-29 read in the code and on the installed 0.10.15. Check a line number before relying on it.

## Rules for every item (the reader, 2026-09-29)

These rules come from the reader's overhaul list. They apply to every screen and to the extension. B159 to B162 put them in place, and every later PR keeps them.

- **Typeface:** IBM Plex Mono everywhere.
- **Theme:** Panel only. There is no theme choice.
- **Emphasis:** italic marks anything different or important.
- **Controls:** buttons and every other control (select, input, tab, file button) look raised, like a button.
- **Headings:** every section heading carries a symbol.
- **Words:**
  - no em dashes;
  - no informal phrases ("what is this", "throw it away", "cover the gaps", "one click");
  - at most one line under a heading, with anything longer behind an expander;
  - professional names for features (D1).

The rules in `CLAUDE.md` still hold, and several items depend on them:

- `ui/` carries no pack vocabulary. Categories, filters and spec fields come from API rows.
- `kriko/` stays domain-free.
- Model and category lists are read from the CLI or the packs, never typed.
- A bundle-budget raise is recorded with its reason, not avoided.

## Decisions only the reader can make

Each decision has a default, so no work waits on it. An item that depends on one names it.

| # | Question | Default until the reader says otherwise |
|---|---|---|
| D1 | What the UI calls a pack, the author role, and "analyze" | A pack is a "Catalog" on screen. The author role disappears with the Buyer/Author switch (B165). "Analyze" becomes "Check". Code, API and docs keep `pack`. |
| D2 | Provider marks (Anthropic, Google, OpenAI and others) are trademarks | Each vendor's own published mark, small and monochrome, for each provider the app already detects. |
| D3 | The local plane searches through OpenSERP, which is not installed here and has no Windows install story | Use OpenSERP when it answers. Otherwise fall back to Exa's free, keyless hosted search, so a local model alone is enough to run. Bundling OpenSERP waits on a license check. |
| D4 | Does "remove every package" include the cars and drill packs that the installer seeds? | Yes on this machine, and they stay removed after a restart. The 1.0 installer still carries them for new installs. |
| D5 | Removing "What to research next", "Build knowledge" and "On a schedule" leaves nothing that starts a top-N run | The top-N run and the schedule loop go, with their endpoints. Research starts per product: on the Run screen, from Browse, or from the extension. |
| D6 | Where the benchmark's fixed test set lives | A versioned set shipped with the app. It is neither a pack nor stored in the knowledge store. The 2026-09-15 benchmark design is amended to match. |
| D7 | "Harnesses on this machine" holds the only Connect and skill buttons | The section goes. Each agent's row in "Your agents" gains its connection state and one action. |

## Phase 0: broken today

### B155: Claude Code reads the pages that sites refuse it
**Asked:** "do we know why claude code web search stopped working suddenly?", then "you reckon no solution to this?" (2026-09-29)
**Where:** every Claude Code research run: extension "Research this product", Browse subject Research, and the Run screen.
**Found:**
- Sites behind Cloudflare's AI-bot blocking answer Claude Code's fetcher (`Claude-User`) with a 403. The result was the same on 2.1.283 and 2.1.284, and seven sites refused in the job logs.
- Exa's free hosted MCP (`https://mcp.exa.ai/mcp`, tool `web_fetch_exa`, no key) read all four refused pages in a probe.
- Kriko launches Claude Code with `--strict-mcp-config` and `--allowedTools WebSearch,WebFetch` (`src/app/providers/harness.py`).

**Scope:**
- Every CLI that takes a per-run MCP config gets the same page reader.
- A refused page does not count toward the quick look's page opens.

**Done when:** a Claude Code quick look on a product whose top sources refuse `Claude-User` returns sourced risks, and its log shows the refused page read through the page reader rather than fetched a second time.
**Not this:**
- spoofing a browser user agent (ruled out in B154);
- changing the reader's global Claude Code config.

**Owner:** free

### B156: Sites stops hanging on "Reading the adapters"
**Asked:** "Sites: fix it getting stuck on \"reading the adapters\"" (2026-09-29)
**Where:** System, Sites.
**Found:** reproduced on the installed 0.10.15.
- `/api/sites` answers 200 in 0.03 s. The screen then throws `each_key_duplicate`, because its each key `site.site + site.source` repeats: four packs ship a `hepsiburada.com` adapter and three ship a `sahibinden.com` one.
- `ui/src/lib/Async.svelte` has no error boundary, so the loading text never leaves.
- `Sites.svelte` has no test.

**Done when:**
- Sites on the installed build lists every readable site and "Asked for" within a second, with no console error.
- A render error on any screen that uses `Async` shows an error, never an endless loading line.

**Not this:** the Sites redesign (B181).
**Owner:** free

### B157: "Update the skill" clears when pressed and stays clear
**Asked:** "Fix the Claude Code bug that keeps showing the \"update the skill\" button" (2026-09-29)
**Where:** Agents, Claude Code's row.
**Found:**
- The startup refresh (`src/app/web/app.py:168`) renders the skill without the "What to research next" block and stamps that digest.
- The status check (`skill_status` in `src/app/agentconfig.py`) and the button both render with `_agenda_rows(...)`.
- The two never match, and the agenda's counts change with every analysis. So the file reads as stale again after each restart or check.
- The test passes only because its store has an empty agenda.

**Done when:** after the button is pressed, the app restarted, and a new check run, Claude Code's row still reads up to date with no button.
**Not this:** the skill's content (B178).
**Owner:** free

### B158: The model pickers list only models
**Asked:** "Model selection: run a script to fetch the model list first, then let the user choose (models update daily)" (2026-09-29)
**Where:** Benchmark's LLM chips, the Agents LLM pick, the Run screen's LLM pick.
**Found:**
- Antigravity's list starts with `Fetching`. That is a header line of `agy models`, which `_from_models_command` (`src/app/providers/harness.py`) accepts as a model id.
- Vibe and Copilot return empty lists with no explanation.

**Done when:**
- Every LLM list matches what its CLI prints as models today, with no header or status lines.
- A CLI that lists no models says so, rather than showing an empty pick.

**Not this:** the picker's new look and the fetch when the screen opens (B175).
**Owner:** free

## Phase 1: foundations (first; every screen depends on these)

### B159: Plex Mono, only the Panel theme, italics and section symbols
**Asked:** "Switch the whole app to IBM Plex Mono", "Use italic text to mark anything different or important", "Remove all theme selections, keep only the Panel theme", "Use symbols for sections" (2026-09-29)
**Where:** every screen, the Appearance section of Settings, and the rail group titles.
**Found:**
- Plex Mono ships at weight 400 upright only (`ui/public/fonts/`), so bold and italic would be faked.
- Body text is Plex Sans, via `--font-sans` in `ui/src/styles/themes/panel.css`.
- Slate and Lemonade live in `ui/src/lib/theme.ts`, `main.ts` and `ui/index.html`, along with three fonts that only they use.
- Rail titles are plain text (`ui/src/lib/shell/NavGroup.svelte`).

**Done when:**
- Every screen renders in Plex Mono with real bold and italic faces.
- Settings has no theme choice.
- Emphasis is italic.
- Each rail group and section heading shows a symbol.

**Not this:**
- restyling individual controls (B160);
- the extension (B186 applies the same rules there).

**Owner:** free

### B160: One raised control kit for buttons, selects, search and file
**Asked:** "Make all buttons and selections 3D, button-like", "Restyle every <select> (they look ugly everywhere)", "Restyle the <search> text and box", "Restyle the \"Choose File\" box (unstylised)" (2026-09-29)
**Where:**
- every control on every screen;
- the search box is Browse's (`#k-search`);
- the file inputs are on Packs and Welcome.

**Found:**
- Buttons are already raised (`ui/src/styles/components.css:143-260`).
- Inputs, selects, radio cards and the file input are flat, and selects draw the native chevron (`components.css:309`).
- There are 19 selects across 14 files.

**Done when:**
- Every select, input, tab, radio card and file button on every screen has the same raised face and press as a button.
- Selects show one custom arrow.
- No native "Choose File / No file chosen" is visible anywhere.

**Not this:** replacing `<select>` with a custom listbox. Keyboard behaviour and the `combobox` role the tests use stay.
**Owner:** free

### B161: A crisp logo, and no "Open coverage" banner
**Asked:** "Fix the pixelated Kriko logo in the top left", "Remove the \"Open coverage\" indicator (annoying)" (2026-09-29)
**Where:** the mark at the top left of the rail, and the banner above every screen.
**Found:**
- The rail draws the 16x16 `ui/public/mark.svg` at 28 px, a 1.75 scale, with `image-rendering: pixelated`.
- `extension/assets/logo-mark-large.svg` is the 64x64 drawing that the installer icon uses.
- The banner is `NextStep`, mounted once in `App.svelte`, which shows the first unmet step. Today that step is "16 subjects with nothing known".

**Done when:**
- The mark is sharp at 100% and at high-DPI scaling.
- No screen shows a next-step banner.

**Not this:** removing the coverage counts on Overview and Browse.
**Owner:** free

### B162: The word rules become a check
**Asked:** "Remove every unprofessional phrase (\"what is this\", \"throw it away\", \"cover the gaps\", etc.)", "Cut wording everywhere, there are too many words", "Remove all em dashes" (2026-09-29)
**Where:** the gate (`tools/gate.sh`), over every string a reader sees in `ui/src` and `extension/`.
**Found:**
- About 132 em dashes in visible `.svelte` text across 35 files: Bench 18, Extension 12, Knowledge 9, Settings 7.
- 16 more in `ui/src/**/*.ts`, and about 22 in `extension/`.
- "Cover the gaps" and "Throw it away" are in `Knowledge.svelte`.

**Done when:**
- The gate fails on a new em dash or a listed phrase in reader-visible text.
- It reports the remaining count, which can only go down. B187 takes it to zero.

**Not this:**
- code comments and docs, which no reader sees;
- cutting the text itself, which each screen's item and B187 do.

**Owner:** free

## Phase 2: fewer screens, a clearer rail

### B163: New check and Question sheet are gone
**Asked:** "Remove \"New Check\" completely (the browser extension covers it)", "Remove \"Question Sheet\" completely" (2026-09-29)
**Where:** the rail's Check group, the default route, and the "Question sheet" link on a result.
**Found:**
- `routes/Check.svelte` is the default route (`router.ts:9`) and the brand link. It also brings `Describe.svelte`, which only it uses.
- `routes/Questions.svelte` is linked from `lib/Report.svelte:190`.
- `POST /api/analyze` stays, because the extension calls it. `#/result/<id>` also stays, because the extension opens it.

**Done when:**
- The rail has no New check and no Question sheet.
- The app opens on Home (B174).
- "Open in Kriko" from the extension still opens that product's result.

**Not this:** removing the result screen or the extension's "Ask the seller".
**Owner:** free

### B164: Agents shows the agents and nothing else
**Asked:** "Remove the \"Harnesses on this machine\" section completely", "Remove \"What to research next\" completely", "Remove \"Build knowledge\" completely", "Remove \"On a schedule\" completely", "Remove \"What the agent is told\" (unprofessional)" (2026-09-29)
**Where:** Agents. The sections are in `routes/Connect.svelte`: harnesses, `Agenda`, `Planes`, `Schedule`, and the skill text.
**Found:**
- "Harnesses on this machine" holds the only Connect, Rewrite and "Update the skill" buttons.
- "Build knowledge" holds the only top-N run buttons.
- The schedule loop still starts at boot if it was ever enabled (`src/app/web/app.py:186`). Once the card is gone, nothing could turn it off.

**Done when:**
- Agents shows only "Your agents" and "Does it actually run".
- Each agent row can still connect and refresh its skill (D7).
- No top-N or schedule control remains, and a schedule that was enabled before no longer runs (D5).

**Not this:** removing per-product research, or the agent pick that every run uses.
**Owner:** free. Decisions: D5, D7.

### B165: One mode, with no Buyer/Author switch
**Asked:** "Remove the Buyer/Author distinction, keep only Author" (2026-09-29)
**Where:** the rail switch, "What an answer shows" in Settings, and every author-only screen and control.
**Found:**
- The mode exists only in the UI (`ui/src/lib/mode.ts`). The server never branches on it.
- It gates Knowledge and System (`authorOnly` in `nav.ts`), "Start a new pack", and provenance on claim cards.
- It threads `?mode=` through about 15 links, and 12 vitest files mention buyer.

**Done when:**
- Every screen and control an author saw is visible to everyone.
- There is no switch, no Settings radio, and no `?mode=` in any link.

**Not this:** keeping the word "Author" in the UI (D1).
**Owner:** free

### B166: No Updates block, no "What readers said"
**Asked:** "Remove the \"Updates\" block", "Remove \"What readers said\" from Browse" (2026-09-29)
**Where:** Packs (`routes/Packs.svelte:251-330`), and the Browse lens tab (`routes/Knowledge.svelte:590`).
**Found:** UNVERIFIED whether a pack update installs without a click. If it does not, this item adds that, because the block is the only manual path.
**Done when:**
- Packs, or its section in Browse after B167, shows no Updates block.
- Browse shows three lenses.
- An available pack update still installs without the block.

**Not this:**
- stopping pack updates;
- the extension's claim marks. The extension still posts them, and they keep feeding research signals.

**Owner:** free

### B167: The rail folds, and Packs moves into Browse
**Asked:** "Make the KNOWLEDGE section a tab that can be closed or opened", "Make the SYSTEM section a tab that can be closed or opened", "Merge Packs into Browse as a section at the top of the context screen", "Keep Overview as its own separate screen after the merge" (2026-09-29)
**Where:** the rail, Browse, and Overview.
**Found:**
- Group titles are a `<p>` with no collapse state (`NavGroup.svelte:24`).
- `routes/Packs.svelte` is 436 lines, and nine links point to `#/packs`.

**Done when:**
- Clicking KNOWLEDGE or SYSTEM folds and unfolds its rows, and the choice survives a restart. The group holding the open screen stays open.
- Browse opens with the installed packs at the top, and `#/packs` lands there.
- Overview is still its own screen.

**Not this:** the Browse redesign (B180).
**Owner:** free

## Phase 3: engine

### B168: A product check lands in the knowledge store
**Asked:** "Singular product searches must be addable to the DB" (2026-09-29)
**Where:** extension "Research this product" on an unknown product, and Browse search.
**Found:**
- A quick look's sourced risks live only in `app.sqlite` `jobs.result_json` (`src/app/web/tasks.py`, `quick_look`).
- A Dyson V15 quick look found 5 sourced risks, yet `/api/search?q=Dyson V15` returns nothing.
- Agent-drafted packs hold 0 evidence rows, and their claims are unsourced.

**Done when:**
- After one quick look on an unknown product, Browse finds that product and shows its risks with their sources.
- A second quick look adds to it rather than starting over.

**Not this:**
- keeping unsourced claims;
- a review step before the claims land (the automation rule is to fail open).

**Owner:** free

### B169: Products join a category pack rather than minting one each
**Asked:** "Singular product searches must not create a new pack each time", "Revise the engine flow for the above" (2026-09-29)
**Where:** the extension door (`POST /api/extension/research-plane`) and `pack_author` (`src/app/web/tasks.py`, `src/app/packauthor.py`).
**Found:**
- `product_only: true` forces one pack per product, and the agent picks the id with no collision check. There are eight such packs today, most holding one subject. `scyrox.v8` was named from a Turkish listing title.
- A sibling product ("Scyrox V6", "iPhone 16") mints another pack.
- Checking the same product again fails with "drafts\samsung-headphones already holds a pack.toml" (`scaffold.py:261`).

**Done when:**
- Checking "Scyrox V6" after "Scyrox V8" leaves the pack count unchanged, and Browse lists both under one pack.
- Checking the same product twice succeeds.

**Not this:** a typed list of categories. Per `CLAUDE.md`, the category comes from pack data and the listing.
**Owner:** free

### B170: A category pack grows as a real package
**Asked:** "Singular product searches must be turned into packages" (2026-09-29)
**Where:** Packs (in Browse after B167), `packstore.install`, and `kriko/pack/build.py`.
**Found:**
- `packstore.install` refuses a changed digest at the same version, and nothing bumps versions. So an amended `0.1.0` cannot be reinstalled.
- Cars and drill have no draft folder, so they cannot be amended.

**Done when:**
- After a product joins a pack, Packs shows that pack's version and digest advanced.
- The `.kpack` it exports installs on another machine with the new product in it.

**Not this:** editing the source of the first-party packs in `packs/` from the app.
**Owner:** free

### B171: The local machine plane, finished
**Asked:** "Local agent: finish the work it needs, then implement it" (2026-09-29). Earlier the same day: "wheres the local agent".
**Where:** the local plane (`kriko/research/local.py`, `src/app/providers/`), its card, and Settings.
**Found:**
- **Wrong address:** the card probes only `127.0.0.1:8080`. This machine runs Ollama on 11434 with no model pulled, and has LM Studio installed but not running.
- **Wrong path and model:** the completer posts to `<base>/chat/completions`, which Ollama and LM Studio serve under `/v1`. The model defaults to `local`, which both reject.
- **Silent failure:** a failed request returns `{}`, and the run ends as "0 claims kept".
- **No settings:** there is no setting for the address or the model.
- **No search service:** OpenSERP is not installed and has no install story (D3).
- **Not usable from most doors:** the plane has no `ask`, so neither the extension's quick look nor pack author can use it, and the scheduler refuses it.

**Done when:**
- With Ollama or LM Studio running a downloaded model, the plane shows ready and its model list is the server's own.
- A quick look from the extension then returns sourced risks with no agent CLI and no key.
- When a server is down or has no model, the reader sees which one and what to do.

**Not this:** downloading a model on the reader's behalf.
**Owner:** free. Decision: D3.

### B172: The local plane goes first
**Asked:** "Add our new local machine and make it the prioritised one" (2026-09-29)
**Where:** every door that picks a plane: the extension, the Run screen and Browse Research (`default_backend` in `src/app/web/tasks.py`).
**Done when:**
- With the local plane ready, a run started without naming a plane uses it, the Run screen lists it first, and the run's log says so.
- With it not ready, runs fall back to the next plane and say why.

**Not this:** removing the other planes.
**Owner:** free. Depends on B171.

### B173: Product details for Compare
**Asked:** "Support detailed product info fetching for Compare (more detail is fine, see Compare)" (2026-09-29)
**Where:** the quick look and pack author briefs, subject attributes (`GET /api/subjects/{id}`), and Compare.
**Found:**
- Compare reads only claims (`ui/src/lib/compare.ts`).
- Specs already fit as subject attributes: the iPhone 15 pack has chipset, battery, display and IP rating. But the brief never asks for them, and the quick look returns none.

**Done when:** a product checked from the extension shows its specifications on its subject, taken from its pack's own attributes and each with a source, and Compare can line them up.
**Not this:** spec field names typed in `ui/`. They come from the pack.
**Owner:** free

## Phase 4: screens (after Phase 1)

### B174: Home, with Activity as the welcome page
**Asked:** "Make it the welcoming home page", "Add graphs", "Polish it (currently looks horrible)", "Rename unprofessional function names: pack, author, analyze, etc. Use symbols and professional names", "Replace \"What the pipeline did\", \"What researches send\" and similar with professional wording", "Remove unnecessary wording" (2026-09-29)
**Where:** Activity (`routes/Activity.svelte`), which becomes the default route.
**Found:**
- Four lens tabs: Live, Runs, "What the pipeline did", "What researchers sent".
- No graphs and no chart library. `BenchChart.svelte` is hand-drawn SVG.
- The data exists at `/api/operations`, `/api/jobs` and `/api/usage`.
- The JS budget has about 900 bytes of headroom.

**Done when:** the app opens on Home, which shows graphs of checks, knowledge gained and research spend over time, under professionally named sections with no paragraph under any title.
**Not this:** Runs, which becomes the Run screen (B175).
**Owner:** free. Decision: D1.

### B175: The Run screen: start a run
**Asked:** "Remove unnecessary descriptions", "Restyle the <select>s", "Show symbols or images of the LLM providers and APIs", "Model selection: run a script to fetch the model list first, then let the user choose (models update daily)", "Source count: replace the number input with an intuitive slider" (2026-09-29)
**Where:** the Run screen. Today that is Activity, Runs ("Start a new pack", with Agent, LLM, Effort and Stop after), and it becomes its own rail entry.
**Found:**
- Model lists are already read from each CLI (`models_for`, cached for 600 s).
- The source count is four preset chips plus a hidden number input (`lib/Scale.svelte`, with a maximum of 50 typed into the component).

**Done when:** the Run screen starts a run from one compact form:
- provider marks on agents and models;
- the model list refreshed from the CLI when the screen opens;
- a sources slider showing the count and the estimate;
- no paragraph under any control.

**Not this:**
- a typed model list;
- the live panel (B176).

**Owner:** free. Decision: D2.

### B176: The Run screen: watch a run live
**Asked:** "Put live agents in the black rectangle area whenever one is running", "Add more animations, more detail, more interaction choices", "Make it intuitive to see what the agent is doing and detecting (new info, etc.)", "Make agent output instant (streaming)" (2026-09-29)
**Where:** the dark panel under the Run screen's form. That is my reading of "the black rectangle"; the reader corrects it if it is wrong.
**Found:**
- CLI output is read line by line (`harness.py`, `_lines`) and pushed over SSE every 0.5 s (`routers/jobs.py`).
- Claude Code's `stream-json` gives whole messages only, and partial `stream_event` frames are dropped.
- A live card shows one tail line unless Log is pressed.

**Done when:**
- While a run is live, the dark panel shows each running agent, what it is doing, and each new source and finding as it arrives, within about a second of the CLI printing it, without Log being pressed.
- The reader can stop or answer the run from that panel.

**Not this:** a raw terminal dump.
**Owner:** free

### B177: Agents, one row per agent
**Asked:** "Remove the many unnecessary descriptions", "Update wording and symbols/images for the agents", "Restyle the <select> inputs", "Improve the \"does it actually run\" check and add logs available if the user asks", "Improve MCP guidelines without using text" (2026-09-29)
**Where:** Agents.
**Found:**
- Verify runs the MCP handshake (spawn, initialize, tools/list) and shows a block of detail only when it fails.
- Connecting another harness is a paragraph plus pasted JSON.

**Done when:**
- Each agent is one row: mark, state, model, effort and one action.
- Verify shows each step's result, with a "Show log" on request.
- Connecting a harness is shown as steps with state icons, not prose.

**Not this:** a Verify that runs any command the page names. The fixed command stays, as a guard against command injection.
**Owner:** free. Depends on B164. Decision: D2.

### B178: A short skill, tied to no one product, harness or model
**Asked:** "Improve skill.md and the 5 step functions", "Make skills.md model, harness and product agnostic (important)", "Shorten skills.md, it is bloated, make it efficient" (2026-09-29)
**Where:** the generated skill (`src/app/agentskill.py`), which is served at `/api/agent-skill` and written to each harness.
**Found:**
- It is 4,944 words: about 3,300 from the installed packs' own sections and 1,900 generic.
- The generic part names screens, the browser extension, a repo path, a dated history note and a car example.
- "These five fields are not optional" heads a table of seven.
- It names no models.
- `test_the_skill_names_the_operations_the_app_shows_back` requires screen names, so it changes with this item.

**Done when:**
- The skill is under 1,500 words whatever packs are installed.
- It names no screen, product, harness or model.
- Each of the five steps names one input and one output.
- A pack's own bar reaches the agent through `research_brief`.

**Not this:** removing the pack's bar from what the agent sees.
**Owner:** free

### B179: Overview shows what needs attention, each item linked
**Asked:** "Overview: rework it, it currently spits info that connects to nothing and lacks the crucial information. Show the crucial info and link it to where it belongs" (2026-09-29)
**Where:** Knowledge, Overview.
**Found:**
- Four stat tiles with no links.
- A "Labels no adapter reads" table whose site column is plain text.
- A pack-updates row that reads "Could not check for pack updates".

**Done when:**
- Every number and row on Overview opens the screen and filter that holds it.
- The top of the screen lists what needs attention now: products with nothing known, a failing update check, switched-off packs, and unread site labels.

**Owner:** free

### B180: Browse puts the search first, then filters
**Asked:** "Browse: stop spitting new packages and stacking them, so the search section is reachable immediately", "Browse: remove unnecessary descriptions and text", "Browse: add more filters, with expandable descriptions" (2026-09-29). The third sentence was cut off in the reader's list, and the reader completes it.
**Where:** Knowledge, Browse.
**Found:**
- The search box sits about 1,480 px down, under a stat strip and eight pack cards: six drafts marked "is installed" and two switched-off packs.
- The only filters are text search and one pack select.

**Done when:**
- On opening Browse, the search box and the first result row are visible without scrolling.
- Pack and draft notices fold into one expandable line.
- Filters by pack, kind, evidence and severity sit beside the search, each with an expandable description.

**Not this:** filter names typed in `ui/`. They come from API rows.
**Owner:** free. Depends on B167.

### B181: Sites shows what each site gives, and can be amended
**Asked:** "Sites: remove unnecessary descriptions", "Sites: show detailed info about what is being seen from the added sites", "Sites: allow amendments to that info" (2026-09-29)
**Where:** System, Sites.
**Found:**
- `/api/sites` returns only site, id, pack, match, source and activation. `/api/adapters` adds the labels and the panel block.
- A pack's adapters are read-only pack data. Learned ones live in `app.sqlite` `local_adapters`.
- No edit endpoint exists.

**Done when:**
- Each site expands to show the fields it reads, the labels it sees but does not map, its match patterns and its last sample page.
- A learned site's mapping can be changed there, and it is checked before it is saved.
- A pack's site is marked read-only, and an override for it is kept on this machine.

**Not this:** editing a pack's shipped adapter.
**Owner:** free. Depends on B156.

### B182: History, grouped by category and polished
**Asked:** "History: categorise the products", "History: make it more polished, better look" (2026-09-29)
**Where:** Check, History, and the short recent list beside a result.
**Found:**
- History is a flat list of links, 20 at a time, with repeats: three identical MacBook rows.
- `/api/history` carries no category, although each stored lookup records its packs.

**Done when:**
- History groups checks under their category, taken from the pack, with counts.
- Repeat checks of one product fold into one row.
- It reads as designed cards rather than a column of links.

**Owner:** free

### B183: Compare, with saved drafts side by side
**Asked:** "Compare: make it easier to use", "Compare: work like draft papers, each draft saved and helping the user choose", "Compare: put info side by side where possible", "Compare: fetch product info in detail, revealed gradually so it never bothers or overwhelms the user" (2026-09-29)
**Where:** Check, Compare.
**Found:**
- Two to four selects over the last 50 checks, and one table of risk titles.
- The choice lives only in the URL.

**Done when:**
- A comparison is saved as a named draft that can be reopened and edited.
- Products sit side by side, with specs and risks row by row.
- Details open on demand, one section at a time.

**Not this:** keeping drafts in the knowledge store. They are app state, in `app.sqlite`.
**Owner:** free. Depends on B173.

### B184: Filters on System screens, and a new Settings
**Asked:** "Add more filters", "Redo Settings: it looks very ugly, remove unnecessary descriptions, polish it" (2026-09-29)
**Where:**
- the System screens that hold lists: Packs (in Browse), Sites, the run history, and research submissions;
- Settings.

**Found:**
- Only the Live lens in Activity has filters: a door select and "running only".
- Settings has eight sections, each with a paragraph, including a raw dump of every stored setting.

**Done when:**
- Each System list has a search box and a state filter.
- Settings is a short set of sections with one-line labels: keys, provider tests, local machine (B171), and window.
- The dump of stored settings is gone or folded.

**Not this:** ever showing a key's value.
**Owner:** free

### B185: Benchmark, rebuilt
**Asked:** "Make it intuitive, currently info and options are spat out with no structure", "Add more selects, more options, more animations", "Remove unnecessary descriptions", "Explain the planes (they exist but explain nothing)", "Use fixed tests, not the user's installed packs (packs are made with agents anyway)", "Replace informal wording with professional wording", "Make the results section expandable for detail if the user wants it", "Copy the structure of current LLM benchmark systems", "Support results with graphs", "Make models comparable" (2026-09-29)
**Where:** System, Benchmark (`routes/Bench.svelte`, `src/app/bench.py`).
**Found:**
- No pack ships `research/gold.yaml`, so the benchmark runs on the first installed subjects and hallucination reads "not yet measured".
- The screen meanwhile says it measures "against ground truth this pack's author supplied".
- About 30 LLM chips sit in one wall, and the plane chips carry no explanation.

**Done when:**
- The benchmark runs a fixed, versioned test set, identical on every machine.
- Results read as a leaderboard: one sortable row per model, each expanding to per-case detail.
- Graphs put models on shared axes.
- Runs scored on different sets are never ranked together.
- Each plane has a one-line meaning.

**Not this:** measuring the reader's own packs.
**Owner:** free. Decision: D6.

### B186: The extension follows the same rules
**Asked:** "Remove excess wording and phrases like \"one click\"", "Keep only the extension connection, plus logs if the user asks", "Remove the long descriptions, keep only what is needed", "Apply the global design foundations from section 1" (2026-09-29)
**Where:** the Browser extension screen in the app, plus the extension's in-page panel and its options page.
**Found:**
- The app screen has seven cards, one headed "One click", and a site list that duplicates Sites.
- The panel (`extension/hover_lite/`) uses system fonts first.
- The options page has five paragraphs for one field.
- There is no log view.

**Done when:**
- The Browser extension screen shows its connection status, with folded "Log" and "Files" sections.
- The panel and options page use Plex Mono, the Panel colours, raised controls and section symbols, with no paragraph longer than a line.

**Not this:** site vocabulary in `extension/`, which `test_the_extension_speaks_no_sites_own_language` forbids.
**Owner:** free. After B159 and B160.

## Phase 5: sweep, clean install, release

### B187: The sweep, where every word earns its place
**Asked:** "Remove every unprofessional phrase (\"what is this\", \"throw it away\", \"cover the gaps\", etc.)", "Cut wording everywhere, there are too many words", "Remove all em dashes" (2026-09-29)
**Where:** every screen, the extension, and the server messages that reach a screen.
**Done when:**
- The check from B162 reports zero.
- A walk of every screen finds no paragraph under a heading and no informal phrase.

**Owner:** free. After the rest of Phase 4.

### B188: A clean install, rebuilt by the new flow
**Asked:** "Remove every package so you can rebuild them" (2026-09-29)
**Where:** Settings (one reset action) and Browse.
**Found:**
- No reset exists.
- Cars and drill come back at the next start after an uninstall, because `app/bundledpacks.py` seeds any missing pack.
- Drafts persist in `~/.kriko/drafts` and block a new draft of the same name.
- History rows keep referring to packs.

**Done when:**
- After one confirmed reset, Browse shows no packs and no drafts, and a restart brings nothing back (D4).
- History is kept.
- The packs are rebuilt by checking products through the B168 to B170 flow.

**Not this:** deleting history or settings.
**Owner:** free. After Phase 3. Decision: D4.

### B189: 1.0.0
**Asked:** "okay let's do a stable version to do list" (2026-09-29)
**Where:** the installer and every screen.
**Found:** the temporary app-first phase in `CLAUDE.md` ends "when the reader confirms a double-clicked install opens and runs an analysis".
**Done when:**
- A double-clicked 1.0.0 installer opens, and every journey in `tools/journeys/` passes on it.
- The reader runs a check from the extension and says it works.
- 1.0.0 is published as a GitHub release.

**Not this:** code signing, unless the reader asks. SmartScreen still warns on an unsigned installer.
**Owner:** free

## Carried from the old backlog

The rest of the old list is not part of 1.0. It stays readable in the archive.

- B113 (extension and app, one system) is absorbed into B186.
- B143 (journey checks) is absorbed into B189.
- B142 (CI on the reader's Windows machine) stays paused with CI, as described in the temporary section of `CLAUDE.md`.
