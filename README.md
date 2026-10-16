<div align="center">

<img src="docs/assets/kriko-lockup.svg" alt="Kriko" width="320">

### Know what to check before you buy.

Kriko brings known product problems, their sources, and useful checks<br>
next to the listing you're reading.

[![version](https://img.shields.io/badge/version-2.0.0-1F4FFF?style=flat-square&labelColor=05070F)](https://github.com/Berbadov/kriko/releases/latest)
[![platform](https://img.shields.io/badge/platform-Windows_x64_%2B_macOS_arm64%2FIntel-1F4FFF?style=flat-square&labelColor=05070F)](https://github.com/Berbadov/kriko/releases/latest)

[Downloads](https://github.com/Berbadov/kriko/releases/latest) · [Get started](#get-started) · [What's new](#whats-new) · [Benchmarks](#model-benchmarks) · [Help](#get-help)

</div>

## Meet Kriko

A listing tells you what a product offers. Kriko helps you find out what can go wrong with that specific product, where the information came from, and what to check before deciding.

- **Read beside a listing.** The browser extension shows relevant risks and their evidence while you browse.
- **Follow the sources.** Open the supporting pages and read the quotes behind a finding.
- **Research something new.** Quick look asks your chosen agent to search and read. Ask follow-up questions without leaving the panel.
- **Compare your options.** Keep products together and compare what is known about each.
- **Keep your knowledge.** Save useful research as a catalog when you choose to. Catalogs and your history stay on your computer.

Looking up an installed catalog works offline and needs no API key. Research uses the internet and the agent or model you choose: an installed coding agent, a local model, or a paid API. Paid providers bill through your own account.

## Get started

### 1. Download and open Kriko

Choose a file from the [latest release](https://github.com/Berbadov/kriko/releases/latest):

| Download | Best for |
|---|---|
| `kriko-2.0.0-x86_64.msi` | Installing Kriko with Start menu and desktop shortcuts. No administrator rights needed. |
| `kriko-2.0.0-win64-portable.zip` | Trying Kriko without an installer. Unzip it, keep the programs together, and open `kriko.exe`. |

The Windows app includes everything it needs to start. It does not include catalogs: a new install starts with none. Open **Overview**, under **Knowledge**, in the app: it lists the catalogs this release publishes, each with an **Install** button, and keeps installed ones current every week. (`kriko install <file.kpack>` still works from a terminal.) You don't need to install Python, Node, or Rust.

#### macOS downloads

Apple Silicon and Intel Macs have separate builds. A file is downloadable only when that architecture's native build is attached to the [release](https://github.com/Berbadov/kriko/releases/latest):

| Mac | Disk image | Portable app bundle |
|---|---|---|
| Apple Silicon | `kriko-2.0.0-macos-arm64.dmg` | `kriko-2.0.0-macos-arm64-portable.zip` |
| Intel | `kriko-2.0.0-macos-x86_64.dmg` | `kriko-2.0.0-macos-x86_64-portable.zip` |

Open the `.dmg` and drag **Kriko.app** to **Applications**. For the portable ZIP, extract it and move **Kriko.app** where you want it. Each archive is a complete app for its named architecture, built on a matching Mac.

These macOS builds are unsigned unless the release explicitly says otherwise. On first launch, macOS may warn that it cannot verify the developer. In Finder, Control-click **Kriko.app**, choose **Open**, then confirm. If macOS still blocks it, use **System Settings → Privacy & Security → Open Anyway** for Kriko.

### 2. Add the browser extension

1. Open **Browser extension** in Kriko and use **Stage** to prepare its files (**Refresh** if already staged).
2. Use **Show folder** to find the extension folder.
3. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select that folder.
4. Pin Kriko in the browser toolbar. In the extension's **Options**, grant access to the sites you want to use.

The extension is loaded from disk; it isn't distributed through a browser store. Kriko must be running for it to answer.

> If a page has no panel, check **Sites** in Kriko. The site may need permission or an adapter that can read its listings.

### 3. Check a listing

Open a supported listing and open the Kriko panel. Read the known risks, expand a finding, and follow its source. A catalog supplies the knowledge for its product category; it can only answer for products it covers. A new install has no catalog until you install one, so the panel has nothing to check against yet.

When the product isn't covered, try **Quick look** with a configured agent. You can inspect the sources and ask another question after the result arrives. Quick look stays in your history. A catalog grows when you press **File quick looks** on **Overview**, or when you build one yourself.

### 4. Choose an agent when you want to research

Open **Agents** to select an installed agent and its model, then **Check connection**. For a local model, use **Local LLM** to choose a downloaded model. For a paid API, add its key in **Settings** and choose its model.

The beta desktop supports **Claude Code, Codex, Antigravity, Mistral, and Local agent**. Search the model picker to find a model quickly. Each CLI research call starts a fresh chat.

Your model choices come from the provider or runtime. You can adjust a research run before starting it, follow its log, answer an agent's question, and stop it from the live panel.

## Updates and your data

Kriko saves catalogs, preferences, research, and history under `%USERPROFILE%\.kriko` on Windows and `~/.kriko` on macOS. Updating or uninstalling the app preserves that folder.

**Updating.** Kriko checks for a newer version each time it starts and offers it on the **Home** screen. Nothing installs until you press **Install and restart**. The in-app updater downloads and runs only the Windows x86_64 MSI; it does not update the Windows portable ZIP or macOS app bundles. To update those, download the newer archive from Releases and replace the old app or extracted files. After any update, refresh the staged browser extension in Kriko and reload it in the browser.

> The build is unsigned, so Windows may show a SmartScreen warning. See the [Windows installation guide](docs/INSTALL_WINDOWS.md) for the install steps.

**Running in the background.** Closing the window keeps Kriko running so the browser extension can answer. To stop it completely, choose **Quit** from its tray icon.

**What leaves your computer.** Installed lookups run on your computer. Online research sends its questions and reading context to the providers you select; a local model runs inference on your computer and still needs web search to gather new sources.

## What's new

### 1.8.0

- **Chat can research products with every supported agent.** Product searches use bounded, parallel web gathering and keep sources beside the answer. Tool-capable agents can use their web tools. Ordinary conversation and saved-record questions avoid unnecessary research.
- **A calmer Chat workspace.** The conversation and composer come first. Real research phases replace the artificial percentage bar, and streaming answers no longer trigger repeated animations. Stop, Retry, Copy and source links stay close to the conversation.
- **Buyer decisions respect the evidence.** Catalog shortlists honor conditions and supporting citations, distinguish unknown requirements from matches, and no longer prefer a product simply because fewer serious problems were recorded for it.
- **Navigation opens what you chose.** Home opens the selected saved check or comparison. Run ignores obsolete search replies and can start a separate, unsent discovery conversation when a product is missing locally.
- **Research spends less time waiting.** Independent search engines answer concurrently, each engine receives one query at a time, and spare pages can replace stalled reads. Claude Code also receives pages gathered by Kriko. Cancellation and Quick Look gathering budgets remain enforced; bot-check pages are discarded.
- **First-run setup is guided.** A five-step tour introduces catalogs, agents, the extension and a first check. Settings can replay it. The Windows installer offers **Open Kriko** on its final screen; silent installs launch nothing.

### 1.7.0

- **Chat answers ordinary questions directly and finds products on the web.** Answers stream as they arrive, keep clickable sources, and support Stop, Retry and Copy. Each conversation keeps its own draft and running answer. The composer wraps across lines; Shift+Enter adds a new line.
- **Compare fits four products together.** The comparison comes first, the research queue can collapse, and failed or stopped items explain what happened and offer a retry. Follow-up answers resume after leaving the screen.
- **Concurrent runs stay independent.** Queue entries are claimed atomically, switching conversations cannot attach an answer to another thread, and cancellation checks no longer hold the shared agent-slot lock.
- **Quick Look starts showing useful work sooner.** Search and reading overlap, completed pages appear progressively, and initial gathering has a 15-second budget. Slow fallback readers stop when cancelled or out of time. Deep research retains its longer gathering path.
- Four live Chat checks completed in 6.2–11.4 seconds with the saved low-effort model setting, including two simultaneous conversations and two web requests. These are small samples, not a completion guarantee; model speed and source availability still matter. See the [measurement report](docs/benchmarks/interactive-workflows.md).

### 1.6.4

- **Codex works again on long answers.** Kriko stopped a Codex turn after 256 streamed events, so any structured answer of a few hundred tokens failed; in the author's own history 14 of 16 accepted turns died that way. The event limit, a reader queue limit and a line-size limit are gone or raised, a failed attempt now records why it failed, and a timed-out version probe is no longer remembered as "Codex has no persistent mode". Claude Code and Mistral Vibe get the same relief for long streamed answers. Codex also shows its first streamed answer text sooner in Chat and in the Run card, and a request that needs web tools goes to the process path before it is sent instead of failing after delivery.
- **Concurrent research runs concurrently.** The number of agent processes was capped at two by the resource profile whatever **Settings → Runs** said. The setting now raises that cap, for Codex too, and quick looks follow it. Jobs waiting for a slot say so. On the quiet resource profile the setting now wins over the profile. Unknown products that need a new catalog still take turns, because catalog drafts share one claim.
- **A new catalog is built from pages Kriko reads.** Codex, Antigravity and Mistral Vibe cannot search in persistent mode, so authoring a catalog used to send them to browse with no tools and ended in an installed catalog with no claims. They are now handed the pages, like a Quick Look, and a catalog with no claims says so and goes back to "needs an agent" instead of counting as filed.
- **Queue and Compare.** The engine resolves a queued listing to a product (the seller's title rarely matches a catalog word for word, so known products were researched again and "passed over"), a finished research job saves a check so the product appears in Compare, queue states only move in valid steps, and an interrupted run returns to waiting after a restart. A skipped row now says why.
- **Chat is shorter and built around the question.** One header and hint, a conversation with the input at its foot and the agent picker beside it, and product answers as compact rows. About a fifth of the words it had.
- **The Local agent can be picked in Chat and Compare**, and when it is found but not ready, both screens say why instead of hiding it. A Compare follow-up with the Local agent and no search service answers from the saved checks, without web search, and says so.
- **Browse** lines up: the filter card no longer overlaps the controls, every table row has the same height, long names truncate, and the grid and paging row follow the list.
- **Claude Code runs show what reuse did**, for example "reused worker · started in 0.1 s · 9,800 of 10,400 input tokens cached", in the Quick Look card and the job log. Reusing a worker saves about 1.4 s a request; most of a run is the model's own turns and page fetches. Tool search is off for Claude Code runs, which removes a first step that Sonnet sometimes spent on it.
- Known limits: the Windows desktop screens above were compiled and tested but not yet observed in a window for this release, and nothing was checked on macOS. Mistral Vibe authoring and the Claude Code changes were exercised against fakes, not a paid run. A catalog already installed with no claims is not rechecked; add the product to it again.

### 1.6.3

- **Chat** (Check group): pick an agent and hold a threaded conversation. The agent is told only the names and one-line descriptions of what the app has gathered, and reads a source only when it asks; each ask shows as a step, then the answer with its sources. "I need X, with constraints a, b, c" becomes a ranked shortlist that says, per candidate, what is met, unknown or contradicted. Keys and settings cannot be reached from chat. Numeric limits are word-matched, so "under 2 kg" is met by "2 kg" whatever the direction.
- Agent progress moves steadily: bars ease and creep instead of freezing and leaping, and every running agent shows what it is doing in words, its stage, a ticking clock and a short trail of recent actions. Reduce motion keeps them still.
- The desktop is denser: smaller cards, rows, gaps and totals, related cards side by side where they fit, and shorter page headings. More fits on each screen, including at the 940 px minimum.
- **Compare → Start queue** researches several products at once, as many as Settings → Runs allows (default 1). Runs on the same catalog still take turns.
- **Persistent agents.** Claude Code and Mistral Vibe now keep one worker alive across requests, as Codex already did, so a request skips process start-up. Every request still gets a fresh conversation: Claude Code is reset with `/clear` and Vibe opens a new ACP session. Workers get no tools beyond what the process path granted, are released when idle or when another agent needs the slot, and a request that may have been delivered is never sent twice. Antigravity has no persistent mode, so it keeps starting a process. `Settings → agent_transport` (or `KRIKO_AGENT_TRANSPORT`) accepts `auto` (default), `persistent` or `exec`; the older `codex_transport` and `KRIKO_CODEX_TRANSPORT` names still work. A run the reader can answer mid-run keeps its own process. Details: [docs/AGENT_RUNTIME.md](docs/AGENT_RUNTIME.md).
- Research requests are recorded durably (inputs, attempts, delivery state, results and usage), a lost response no longer submits the same research twice, and a run's manifest, log tail and event stream can be inspected through the API.
- Quick Looks obey the settings in the app (effort per agent, number and kinds of sources, search and output language) and answer in the listing's language. `kriko agent-bench` runs the real Quick Look path against a fixed fake web and reports how often each agent is right and how consistent it is; it spends your subscription only with `--yes`.
- Codex, Antigravity and Mistral Vibe search for the product itself, not for the catalog's `{make} {model}` templates.
- Busy local-model discovery no longer fails the app's screens. It reports that discovery is busy and can be checked again, rather than saying a server is down before it was probed.
- `tools/gate.sh` runs the Python tests in parallel and its stages concurrently: about 3 minutes instead of 13.
- Known limits: the Chat screen and the parallel queue were compiled and unit-tested but not driven in a real window; nothing here was checked on macOS. Resident Claude Code workers pick up a new login only after they idle out or Kriko restarts. Vibe's persistent worker was checked up to a prompt against the real `vibe-acp` (no Mistral key here); Claude Code was checked end to end.

### 1.6.2

- Codex, Antigravity and Mistral Vibe Quick Looks now show each search and each page read as it happens. Before, the run sat on a blank screen for up to two minutes while Kriko searched, which looked like a hang.
- Search asks Google, DuckDuckGo and Bing. The old list included Ecosia, which blocks the search helper, so every query waited for an engine that could not answer and often returned one page or none. In our checks, queries that took 17 s or more and found 0 to 1 results now take about 7 s and find 17 to 22. A real run on a fresh product found 29 pages where the same kind of run found 2.
- An engine the search helper reports as failed is skipped for ten minutes and then tried again, so a block that appears later does not slow every search. Google's click-through links, which carry no readable address, are no longer offered as results.
- After two searches in a row fail, Kriko skips the third instead of waiting out its timeout. If every search fails, Kriko says so, and the agent searches the web with its own tools, opening only a few pages. Its quotes are still checked against the pages, and any claim without a source is dropped.
- **Local** says what to do when a model runs on the processor of a computer that has a graphics card: Ollama looks for the card only when it starts, so quit it from the tray and open it again.
- Known limits: a first search after Kriko starts still takes 35 to 75 seconds while the search browser opens, and the search engines can block it again at any time. A run with no pages read is not evidence that a product has no problems.
- For contributors: `tools/bump.py` also updates the macOS download filenames in this README, which it left at the old version before.

Earlier releases are in the [changelog](CHANGELOG.md).

## Model benchmarks

The measurements below come from the 1.1.0 baseline: three fixed research cases per model, on one Windows 11 computer with an RTX 3060 Laptop GPU (6 GB). They are small samples of the whole research workflow, including search and reading, and describe that machine and those accounts. They are not a general model ranking.

| Model | Cases completed | Grounded findings |
|:---|:---:|:---:|
| **GLM 5.3** via Mistral | 3 / 3 | **17** |
| **Gemma** local agent | 3 / 3 | 0 |
| **Haiku 5.5** | not completed | n/a |
| **GPT 6 Luna** | not completed | n/a |

A grounded finding passed the quote check; it is not independent proof of a fault. Median times, why two models did not complete, the CLI startup measurements, exact model IDs and the commands to repeat every run are in [the benchmark report](docs/benchmarks/README.md).

## Get help

- [Install on Windows and connect the extension](docs/INSTALL_WINDOWS.md)
- [Use Kriko and grow your catalogs](docs/USAGE.md)
- [Understand how matching and research work](docs/HOW_IT_WORKS.md)
- [Report a problem or request a feature](https://github.com/Berbadov/kriko/issues)

If the panel says Kriko isn't running, open the desktop app first. After an update, prepare the extension again in Kriko and reload it on the browser's extensions page.

## Build or contribute

The engine, command line, and local API can also run from source on macOS and Linux. The desktop packaging scripts target Windows x64 and native macOS builds for Apple Silicon and Intel.

See the [desktop build guide](kriko-gpui/README.md) for the Windows installer recipe, [contributor guide](docs/DOCTRINE.md) for setup and checks, and [architecture guide](docs/ARCHITECTURE.md) for the code. To add a new product category, start with the [catalog contract](docs/PACK_CONTRACT.md).

The 1.6.2 [agent runtime branch experiment](docs/AGENT_RUNTIME.md) adds reusable Codex workers with fresh contexts, durable request and attempt records, shared resource limits, and retry protection. Its guide covers transport selection, inspection, validation, and measured startup timings.

Versions and reader-visible release notes move at release, not with every change set. Follow the [update protocol](docs/UPDATE_PROTOCOL.md); published versions and their assets are immutable.

## License

Kriko is open source under the [MIT License](LICENSE).
