<div align="center">

<img src="docs/assets/kriko-lockup.svg" alt="Kriko" width="320">

### Know what to check before you buy.

Kriko brings known product problems, their sources, and useful checks<br>
next to the listing you're reading.

[![version](https://img.shields.io/badge/version-1.6.1-1F4FFF?style=flat-square&labelColor=05070F)](https://github.com/Berbadov/kriko/releases/latest)
[![platform](https://img.shields.io/badge/platform-Windows_x64_%2B_macOS_arm64%2FIntel-1F4FFF?style=flat-square&labelColor=05070F)](https://github.com/Berbadov/kriko/releases/latest)

[Downloads](https://github.com/Berbadov/kriko/releases/latest) · [Get started](#get-started) · [Model benchmarks](#model-benchmarks) · [Help](#get-help)

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
| `kriko-1.6.1-x86_64.msi` | Installing Kriko with Start menu and desktop shortcuts. No administrator rights needed. |
| `kriko-1.6.1-win64-portable.zip` | Trying Kriko without an installer. Unzip it, keep the programs together, and open `kriko.exe`. |

The Windows app includes everything it needs to start. It does not include catalogs: a new install starts with none. Open **Overview**, under **Knowledge**, in the app: it lists the catalogs this release publishes, each with an **Install** button, and keeps installed ones current every week. (`kriko install <file.kpack>` still works from a terminal.) You don't need to install Python, Node, or Rust.

#### macOS downloads

The packaging script names Apple Silicon and Intel builds separately. These are the exact filenames it produces; a file is downloadable only when that architecture's native build has been attached to the [release](https://github.com/Berbadov/kriko/releases/latest):

| Mac | Disk image | Portable app bundle |
|---|---|---|
| Apple Silicon | `kriko-1.6.1-macos-arm64.dmg` | `kriko-1.6.1-macos-arm64-portable.zip` |
| Intel | `kriko-1.6.1-macos-x86_64.dmg` | `kriko-1.6.1-macos-x86_64-portable.zip` |

Open the `.dmg` and drag **Kriko.app** to **Applications**. For the portable ZIP, extract it and move **Kriko.app** where you want it. Each archive contains a complete app for its named Mac architecture. The release packaging recipe builds each artifact on a matching Mac; this Linux checkout has not run or visually verified either native build.

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

## Your data stays with you

Kriko saves catalogs, preferences, research, and history under `%USERPROFILE%\.kriko` on Windows and `~/.kriko` on macOS. Updating or uninstalling the app preserves that folder.

The in-app updater currently downloads and runs only the Windows x86_64 MSI. It does not update the Windows portable ZIP or macOS app bundles. To update a Mac or portable install, download the newer archive from Releases and replace the old app or extracted files; your `~/.kriko` data stays in place.

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

## What's new

### 1.6.1

- Codex, Antigravity and Mistral Vibe Quick Looks no longer fail while counting model calls. Agent model choices omit duplicate entries.
- Local research reserves context for source evidence, keeps product metadata compact, and searches product documentation alongside issue discussions. Ollama execution reports the model's observed GPU or CPU use.
- A completed Quick Look with no supported issues remains a saved research result, with product facts, sources and coverage. It does not establish that the product is issue-free.
- Product and comparison follow-ups carry the saved product context and can search and read fresh web evidence. Saved results show their evidence in Run and History.

### 1.6.0

- The desktop has a new glass-inspired layout, clearer navigation and live job panel, with animations that pause when the window is inactive and obey **Reduce motion**.
- Home, Run, Local, and Browser extension now explain what to do while data loads and after success or failure. Retry actions report their state, and failed refreshes identify stale information instead of presenting it as current.
- Saved Quick Looks can be filed into installed catalogs using exact matching or a grounded assignment from a local model or Mistral, with web tools disabled. CLI-only agents currently abstain and leave the catalog choice to the reader because a verified tool-less mode is unavailable; this does not affect ordinary CLI research. Filing does not rewrite the saved research evidence.
- Local model requests negotiate supported structured-output formats while keeping Kriko's evidence checks in place. No Gemma 4 E2B quality evaluation was run on the 1.6.0 pipeline, whose evaluator digest is
  `e647d1c957e01a8972ddef64ed0834a17ceb622613e0e1d998c8aa2affec6055`.
  An older two-case Gemma 4 E2B fixture run at digest
  `e686996dd0dadaa54e653ae0065e089521c9c4425284f3394d265f08c9e57e98`
  recorded the expected findings and abstention, but its rows lack
  host/runtime metadata and it is not a 1.6.0 benchmark. A separate [live
  search observation](docs/benchmarks/2026-10-11-local-search-followup.md)
  used an earlier pipeline and retained no findings for one product; this is
  not evidence that the product has no faults. Neither result is a general
  model-quality claim. No fine-tuning was performed; details are in the
  [local-agent research note](docs/benchmarks/2026-10-12-local-agent-research.md).
- Agent and model discovery shows when provider choices are still loading, and research screens give clearer feedback as runs start and finish. Hosted response time still depends on the selected provider, model, account, and network; this release makes no latency guarantee.
- A native macOS packaging recipe now targets Apple Silicon (`arm64`) and Intel (`x86_64`) Macs and emits the filenames listed above. The screenshots in this checkout were captured on Linux; each release still needs a successful build and launch check on matching native hardware.

### 1.5.0

- The recommended local model, running on a CPU with no graphics card, now finds both documented problems in Kriko's test evidence instead of one, still reports nothing where nothing is documented, and ignores instructions planted in a page. It no longer throws away a correct finding that names the product word for word because it was unsure of its own answer.
- English answers from a local model skip a translation step that changed nothing: about a third fewer model calls per check.
- A local model server that asks for structured answers in a different format (such as llama-cpp-python's) still gets them, instead of the model being left to answer in free text.
- **Overview** (under **Knowledge**) lists the catalogs you can install, each with an **Install** button. A new install no longer needs a terminal to get its first catalog. Newer versions of installed catalogs stay in their own **Pack updates** card.
- Saved quick looks build your catalogs. **File quick looks** on **Overview** adds every saved quick look to its catalog: to the product already there, or as a new product when the quick look read enough to name it in the catalog's own terms (for example, make and model). No agent runs again and it costs nothing. Each quote is re-checked against its page before it is kept, and each catalog that changed is installed at a new version, as a `.kpack` file you can share. Quick looks that couldn't name their product that precisely are listed, so you can choose to research them.
- A catalog that a harvest or an update replaced can go back: **Back to <version>** on its row on **Overview** restores the version installed before.
- **Install from a file** on **Overview** installs a catalog someone shared with you, from its `.kpack` file. After a harvest, **Share as a file** saves the catalogs that changed, so you can send them.
- **Test** beside a saved key on **Settings** sends the provider one tiny request with it and says under the key whether it worked, how fast, or why not (for example, the provider refused the key).
- The browser panel no longer tells you a product it has just named is unrecognised: a recognised product with nothing known says so. The extension's options page hides **Allow the pending site** when no site is waiting.
- On Windows, if Kriko cannot open its window (no usable DirectX 11, as over some Remote Desktop sessions or in a virtual machine), it now says so in a message box with the reason, and stops its engine. Before, it vanished without a word and left the engine running.
- The app fits a small screen. The window opens inside the display it is on, and below 1100 px wide the sidebar folds to its icons unless you open it. At the 940 px minimum, **Sites**, **Agents** and **Compare** keep every column and button on the page, and **Run** opens with its search field ready.
- **Add to a pack** on a quick look is instant and free when the catalog already has that product. Before, it ran the whole research again.
- **Open in Kriko** and the other buttons in the extension's panel now open the screen they name: a saved check opens in **History**, already unfolded; a product opens in **Browse**; installing a catalog opens **Overview**. Before, they only brought the window to the front, on whatever screen was last open.
- Catalog names on **Overview** and links on **Agents** showed as "…" instead of their text; they now show in full. The sidebar's **Browse** count and **Activity** badge come from your install; before, they were fixed placeholder numbers. Empty screens say what is missing instead of "no match" when nothing was searched.
- When a listing names a model but not its exact variant, the panel says it fits several products and lists them, each opening in Kriko with what is known about it. Before, it called them "recognised" and said the catalogs knew nothing, though they knew a lot about each variant. A product opened in **Browse** lists everything that applies to it, including what is known about its parts (for a car: its engine and gearbox), each marked with the part it comes through. Car variants are named by displacement and power range too, so two of them no longer share a name.
- **Home** says whether no catalog is installed or every catalog is switched off, and takes you to **Overview** to fix either.
- When no catalog is installed and none can be fetched, Overview says to check the connection instead of leaving you at an empty screen.
- When several products fit a listing, a finding that fits none of them is no longer shown. For example, a hybrid-only fault no longer appears on a listing whose fitting variants are all petrol or diesel. A saved check of such a listing is named by the listing's own title. Opening one from the panel takes **History** to its page, already unfolded.
- The car catalog no longer puts findings about another generation on a model's body and electrics. Mégane 3 faults were showing on every Mégane 4, and Golf 8 faults on Golf 7 engines.
- A finding is shown only with the page and quote it came from. A few findings in the built-in catalogs had none and were shown anyway; they are now left out.
- Answers from the engine arrive about 40 ms sooner each. The extension and the app ask often, so lists and checks feel quicker: a status check went from 48 ms to 3 ms, and a catalog lookup from 60 ms to 15 ms.
- Updating with the installer also stops a running search helper (`OpenSERP.exe`), so it can no longer lock files and fail the upgrade.
- In a research log, the page reader is named only when it was actually used. Before, an ordinary page fetch could be reported as a page-reader read.
- The precision benchmark counts a correct finding as supported when it cites its sources in the current format. Before, it scored those findings as unsupported. Its score is what reaches you, and a separate column counts the candidates the local pipeline turned down.
- For contributors: `kriko build packs/<name>` works from a plain checkout for catalogs that ship their own builder (it needed `PYTHONPATH` before), and the car catalog's research pipeline no longer ranks every high-severity finding as unverified, which put the most expensive faults below cheap ones with the same evidence.
- For contributors: the check script `tools/gate.sh` passes again (it had 43 failing tests and 15 type errors), a new test checks that every engine address the extension, the app and the terminal console call actually exists, and `docs/PROTOCOL.md` describes how they talk to the engine.

<details>
<summary>Earlier releases</summary>

#### 1.4.1

- **Search this product** works on a product no installed catalog knows yet. It now starts the same research as **Research this product** in the panel, and the panel says so beneath the button, instead of asking the catalogs again and showing the same answer.
- Bold and inline code in catalog and agent text (claim titles, bodies and "What to ask" lines, quick look specs and assumptions, and an agent's questions) render as formatting instead of showing the asterisks and backticks.
- When the last running job ends, Kriko asks Ollama to unload the local model straight away. Before, the model stayed in video memory for five more minutes after a run (Ollama's default) and slowed the computer while Kriko sat in the background. Quitting Kriko unloads it too. Other model servers keep their own unload timer.
- A product check on a local model no longer stops with "The task leaves no room for evidence" when no installed catalog fits. The instructions are measured against the model's whole context window, and only the page text is held to the research budget. A 16k window now has room for three pages beside the catalog instructions.
- When the instructions really are too long for the window, the error gives both numbers: how long the instructions are and how much the window holds.
- A listing title's seller words are no longer the product. In "DEMİRAY OTODAN DEĞİŞENSİZ BAKIMLI COROLLA 1.8 HYBRID", the check searches for, names and files the product "COROLLA 1.8 HYBRID". The name is kept only when every word of it is in the title or the listing.
- Local models under 2B parameters are never run, whether picked or not. A 0.8B model wrote findings its pages did not say. Choosing one leaves the local plane not ready and says why. The model library no longer offers those sizes for download.
- The desktop app no longer uses a CPU core while nothing is happening. With its window open behind other windows, it used about one full core (10.4 CPU-seconds every 10 seconds). It now uses about 0.1. Minimized or closed to the tray, it stays near zero. The engine keeps serving the browser extension the whole time.
- Animations play only while the Kriko window is the one in front. Behind another window, minimized or in the tray, the window stays still; animations resume when you switch back.
- The **? n** needs-you tag in the title bar blinks three times when it appears, then stays lit. An agent waiting for your answer breathes three times, then rests. Spinners, meters and agent marks still move while a job runs.
- The page header's background no longer slowly pulses.

#### 1.4.0

- The installer no longer carries catalogs. A new install opens with none, and each catalog is installed separately.
- Browse, Agents, Settings and Overview fit the window at its default size and at its minimum size. Nothing is cut off, and no screen scrolls sideways.
- The Live panel starts closed on every launch. When you open it, it floats over the page on a glass panel, so the page layout does not change.
- Local research tells a part from the product it fits. For a listing such as an air filter for a specific engine, Kriko searches for the filter by its name in your search language and skips pages that only discuss the engine.
- A page no longer has to repeat the whole listing title. A part name matches wording variants, and the listing's trailing arrows and the dotless `ı` are handled.
- Pages that were read but were not about the product give an empty result with counts, not a "check OpenSERP and the connection" error. That error now appears only when nothing could be read, and names the cause.
- `gemma4:e2b` is the recommended local model: it is the default when you have not chosen one, what **Set up Ollama and the recommended model** downloads (allow about 8 GB), and it is marked *Recommended* in the model list.
- When a research run finishes without keeping any claim, the extension's panel says that no data was found showing an issue, and that this is not proof there is no issue. Before, it only said "Open the research job for findings."
- A run that left a brief to read keeps the previous wording, because the brief may hold the findings.
- On **Local**, a choice of device, GPU layers, context tokens, answer language or search language shows as picked at once, with a spinner beside its row until the engine confirms it. If the engine refuses the change, the previous choice comes back.
- **Refresh device** shows a spinner until the device information arrives.
- Changing a Local choice or refreshing the device no longer clears a server address or search address you have typed but not saved.
- Kriko checks for a newer version every time it starts. When one is published, the **Home** screen shows it at the top with **Install and restart**. Nothing installs until you press that button.
- If the check cannot reach GitHub, Home stays quiet and **About** says why. A failed check does not hide a newer version that an earlier check found.
- Follow-up questions about a saved check and about a quick look search the web for the answer. Answers are kept to a few sentences and list the pages they rely on as links.
- Answers appear as they are written: three dots while the agent starts, then the text typed out with a caret until it is complete. A local model streams its answer word by word. A coding-agent CLI returns its answer all at once, and the panel types that out the same way.
- Quick-look follow-ups no longer answer only from the quick look's own findings.
- The installer build writes its Rust output to one shared folder outside the project, instead of a copy of about 2 GB inside every checkout and worktree.

#### 1.3.3

- Includes the extension's **Search this product** action, queue button for unrecognized products, and escaped bold/inline-code answer formatting from 1.3.2.
- **Add site** checks for usable catalog identity information before starting an agent, with distinct messages for missing, disabled, or incomplete catalogs.
- Antigravity site and catalog authoring prompts direct the agent to its permitted web tools instead of shell commands that headless mode denies.

#### 1.3.2

- The extension's main action is now **Search this product**, with **Search again** for a refresh.
- **Add to queue** is available even when installed catalogs do not recognize the product.
- Agent answers render bold and inline code while escaping agent-supplied HTML.

#### 1.3.1

- Local research prioritizes exact-model issue forums and owner reports, filters ads and repair-service offers, and replaces irrelevant pages before using the page limit.
- Exact model codes and the selected search language are preserved. Response and search languages can be set independently.
- Bundled OpenSERP stays usable when some search engines are unavailable, and the desktop recovers its search process after it exits.
- Coverage and evidence rejection reasons are visible. An empty result does not establish that a product has no problems.
- The updater recognizes this as newer than 1.3.0. Release downloads include `SHA256SUMS.txt` for verified updates.

Kriko offers a newer version on the Home screen when it starts, or you can install the newer MSI over your current version. Your catalogs, settings, and history are preserved. Refresh the staged browser extension in Kriko and reload it in the browser after updating.

> The build is unsigned, so Windows may show a SmartScreen warning. See the [Windows installation guide](docs/INSTALL_WINDOWS.md) for the install steps.

</details>

## Get help

- [Install on Windows and connect the extension](docs/INSTALL_WINDOWS.md)
- [Use Kriko and grow your catalogs](docs/USAGE.md)
- [Understand how matching and research work](docs/HOW_IT_WORKS.md)
- [Report a problem or request a feature](https://github.com/Berbadov/kriko/issues)

If the panel says Kriko isn't running, open the desktop app first. After an update, prepare the extension again in Kriko and reload it on the browser's extensions page.

## Build or contribute

The engine, command line, and local API can also run from source on macOS and Linux. The desktop packaging scripts target Windows x64 and native macOS builds for Apple Silicon and Intel.

See the [desktop build guide](kriko-gpui/README.md) for the Windows installer recipe, [contributor guide](docs/DOCTRINE.md) for setup and checks, and [architecture guide](docs/ARCHITECTURE.md) for the code. To add a new product category, start with the [catalog contract](docs/PACK_CONTRACT.md).

Versions and reader-visible release notes move at release, not with every change set. Follow the [update protocol](docs/UPDATE_PROTOCOL.md); published versions and their assets are immutable.

## License

Kriko is open source under the [MIT License](LICENSE).
