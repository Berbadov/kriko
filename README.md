<div align="center">

<img src="docs/assets/kriko-lockup.svg" alt="Kriko" width="320">

### Know what to check before you buy.

Kriko brings known product problems, their sources, and useful checks<br>
next to the listing you're reading.

[![version](https://img.shields.io/badge/version-1.1.7-1F4FFF?style=flat-square&labelColor=05070F)](https://github.com/Berbadov/kriko/releases/latest)
[![platform](https://img.shields.io/badge/platform-Windows_x64-1F4FFF?style=flat-square&labelColor=05070F)](https://github.com/Berbadov/kriko/releases/latest)

[Download for Windows](https://github.com/Berbadov/kriko/releases/latest) · [Get started](#get-started) · [Model benchmarks](#model-benchmarks) · [Help](#get-help)

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
| `kriko-1.1.7-x86_64.msi` | Installing Kriko with Start menu and desktop shortcuts. No administrator rights needed. |
| `kriko-1.1.7-win64-portable.zip` | Trying Kriko without an installer. Unzip it, keep both programs together, and open `kriko.exe`. |

The Windows app includes everything it needs to start, including its catalogs. You don't need to install Python, Node, or Rust.

> The build is unsigned, so Windows may show a SmartScreen warning. See the [Windows installation guide](docs/INSTALL_WINDOWS.md) for the install steps.

### 2. Add the browser extension

1. Open **Browser extension** in Kriko and use **Stage** to prepare its files (**Refresh** if already staged).
2. Use **Show folder** to find the extension folder.
3. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select that folder.
4. Pin Kriko in the browser toolbar. In the extension's **Options**, grant access to the sites you want to use.

The extension is loaded from disk; it isn't distributed through a browser store. Kriko must be running for it to answer.

> If a page has no panel, check **Sites** in Kriko. The site may need permission or an adapter that can read its listings.

### 3. Check a listing

Open a supported listing and open the Kriko panel. Read the known risks, expand a finding, and follow its source. A catalog supplies the knowledge for its product category; it can only answer for products it covers.

When the product isn't covered, try **Quick look** with a configured agent. You can inspect the sources and ask another question after the result arrives. Quick look stays in your history; creating a catalog requires an explicit build action.

### 4. Choose an agent when you want to research

Open **Agents** to select an installed agent and its model, then **Check connection**. For a local model, use **Local LLM** to choose a downloaded model. For a paid API, add its key in **Settings** and choose its model.

The beta desktop supports **Claude Code, Codex, Antigravity, Mistral, and Local agent**. Search the model picker to find a model quickly. Each CLI research call starts a fresh chat.

Your model choices come from the provider or runtime. You can adjust a research run before starting it, follow its log, answer an agent's question, and stop it from the live panel.

## Your data stays with you

Kriko saves catalogs, preferences, research, and history under `%USERPROFILE%\.kriko`. Updating or uninstalling the app preserves that folder.

Closing the window keeps Kriko running so the browser extension can answer. To stop it completely, choose **Quit** from its tray icon.

Installed lookups run on your computer. Online research sends its questions and reading context to the providers you select; a local model runs inference on your computer and still needs web search to gather new sources.

## Model benchmarks

**Release 1.1.0 baseline:** we measured three fixed research cases per requested model on the release computer. Version 1.1.2 fixes local evidence handling and CLI research; the older measurements below do not include those fixes. Results and account availability are recorded in [the benchmark report](docs/benchmarks/README.md), together with the exact model IDs and commands to repeat the runs.

| Model | Cases completed | Median time | Grounded findings |
|:---|:---:|:---:|:---:|
| **GLM 5.3** via Mistral<br><sub>`zai-glm-5-3`</sub> | ✅ 3 / 3 | 63.0 s | **17** |
| **Gemma** local agent<br><sub>`gemma3n:e2b`</sub> | ✅ 3 / 3 | 24.7 s | 0 <sup>1</sup> |
| **Haiku 5.5** | ⚠️ not completed <sup>2</sup> | n/a | n/a |
| **GPT 6 Luna** | ⚠️ not completed <sup>3</sup> | n/a | n/a |

<sup>1</sup> Gemma proposed candidates, but none passed the quote check, so none are counted.<br>
<sup>2</sup> 0 of 3 cases ran: model/budget error, and the retry account had no credits.<br>
<sup>3</sup> 0 of 3 cases ran: subscription inactive, and the retry account had no credits.

Measured on Windows 11 with an RTX 3060 Laptop GPU (6 GB). A grounded finding passed the quote check; it is not independent proof of a fault. Hosted cost was unavailable for GLM, so no dollar figure is claimed.

These are small samples of the complete research workflow, including search and reading. They describe this machine and these accounts; they don't establish a general model ranking. Failed requests are reported separately from successful answer times.

### CLI startup on this computer

Measured on 9 October 2026, three separate processes and three fresh chats per CLI:

| Agent | Model | Launch (`--help`) | First reply |
|:---|:---|---:|---:|
| **Claude Code** | Haiku | 0.38 s | **3.93 s** |
| **Codex** | GPT 6 Luna | 0.08 s | 4.36 s |
| **Antigravity** | Gemini 3.8 Flash (low) | 0.36 s | 7.74 s |
| **Mistral** | GLM 5.3 (high) | 0.59 s | 15.23 s |

<sub>Medians of three runs. "First reply" is a fresh one-word answer in a new chat.</sub>

All 12 replies completed. These are startup checks, not research scores: the reply times also include authentication, agent setup, network latency, and model generation. Keeping a terminal open cannot remove most of that wait. GLM varied from 12.55 to 35.23 seconds. Every reply used a new chat. [Raw measurements](docs/benchmarks/cli-startup-1.1.2.json) include the CLI-reported token totals; even a short answer includes the agent's initial instructions.

## Get help

- [Install on Windows and connect the extension](docs/INSTALL_WINDOWS.md)
- [Use Kriko and grow your catalogs](docs/USAGE.md)
- [Understand how matching and research work](docs/HOW_IT_WORKS.md)
- [Report a problem or request a feature](https://github.com/Berbadov/kriko/issues)

If the panel says Kriko isn't running, open the desktop app first. After an update, prepare the extension again in Kriko and reload it on the browser's extensions page.

## Build or contribute

The engine, command line, and browser dashboard can also run from source on macOS and Linux. The packaged desktop app is for Windows x64.

See the [desktop build guide](kriko-gpui/README.md) for the Windows installer recipe, [contributor guide](docs/DOCTRINE.md) for setup and checks, and [architecture guide](docs/ARCHITECTURE.md) for the code. To add a new product category, start with the [catalog contract](docs/PACK_CONTRACT.md).

## License

Kriko is open source under the [MIT License](LICENSE).
