# Changelog

Reader-visible changes for releases older than the three shown in the
[README](README.md#whats-new). Newest first. Published versions are immutable; a
correction is a newer version (see [the update protocol](docs/UPDATE_PROTOCOL.md)).

### 0.1.2

- **Chat answers are formatted.** An answer from an agent is markdown. A bold
  term is bold. A bullet list is a list. A table is a table. A link opens the
  page it names. Before this release the screen drew the characters: every
  asterisk, pipe and bracket reached the reader as itself.
- **You can select and copy an answer.** Drag over the words. Press Ctrl+C. The
  selection crosses a bullet and the paragraph under it, because the
  transcript holds one selection rather than one for each block.
- **One status line while an agent works.** The running turn showed a moving
  mark, a phase word and a second status line at the same time. The mark and
  one line remain.
- **A product card under an answer.** When a turn reads your catalogs, the
  answer now carries a card for each product it found. The card shows the name
  the catalog uses, the identity it is recorded under, and the number of
  recorded risks. **Open** reads the product in Browse. **Add to Compare** puts
  it beside the others and saves its check. **Read again** reads the product
  now, because an answer is a reading of the catalog at the moment it was
  written.
- **A calmer sidebar.** The rows have one rhythm. The fold control moved to the
  brand row, where it reads as this rail's control. A real edge separates the
  rail from the page; a hairline disappeared on a bright screen.
- **The model store is a list.** One full-width row for each model, with one
  primary action at the right edge. The name is the largest thing in the row.
  A size picker appears only on a model that is not installed and offers more
  than one size.
- **The local model lives with the agents.** **Agents** now shows a marketplace
  of every way to answer a question: the coding agents on this machine, the
  local model, and the paid APIs you hold a key for. Each row says what it is,
  where Kriko found it, and its state. It offers one action. The local model
  panel shows the model, the server and the number of models on the machine.
  **Local LLM** left the rail and keeps its own screen, which Agents opens.
- **The light theme is correct.** The hero band kept its dark image but its
  background followed the theme, so on the white ground it became a pale smear
  with light words on it. The band keeps its own colours in both themes. A new
  `EDGE` token separates two surfaces, where a hairline is only right for a
  rule inside one surface.
- **The browser extension is ready for the Web Store.** Version 0.4.2. Escape
  now closes the panel. One loading indicator replaces two spinners and a
  skeleton. The endless sky movement is one pass. A pack's tone value is
  escaped. The result cache is keyed by a digest, so the reader's own listing
  addresses are no longer written to disk as keys. The options page keeps a
  visible focus ring, and it no longer claims that nothing leaves the computer.
- **The agents are faster and they need less of the internet.** The plane
  decision took 1114 ms on a cold start and now takes 264 ms; the second and
  third question in one turn take 1.8 ms. One request on the loopback address
  took 17.19 ms and now takes 1.43 ms. A read of the installed catalogs used
  159 statements and now uses 6. Three of the four coding agents declare no
  page reader, so no internet server can attach to them. The rule that a paid
  API runs only after you pick it is unchanged.
- **A follow-up question carries less and knows more.** The brief for a saved
  check fell from 37,229 characters to 8,752. It still carries the product, how
  far it has been used, and every recorded risk with its page.
- **Kriko can work out how to read a new site.** When no installed catalog can
  read a page, the local model is asked to map the page's own labels. The
  result is checked before it is stored, and it is cached by the page's shape
  rather than by its address, so one inference serves every listing on that
  site. Nothing is recorded when no model is ready, and the reader can turn an
  inferred site off.
- Known limits: the desktop screens were compiled, unit-tested and observed in
  a window on Windows only. The agent speed figures come from one machine and
  exclude the model's own inference time. Nothing was checked on macOS. The
  browser extension is not yet published to the Web Store.

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

### 1.4.1

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

### 1.4.0

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

### 1.3.3

- Includes the extension's **Search this product** action, queue button for unrecognized products, and escaped bold/inline-code answer formatting from 1.3.2.
- **Add site** checks for usable catalog identity information before starting an agent, with distinct messages for missing, disabled, or incomplete catalogs.
- Antigravity site and catalog authoring prompts direct the agent to its permitted web tools instead of shell commands that headless mode denies.

### 1.3.2

- The extension's main action is now **Search this product**, with **Search again** for a refresh.
- **Add to queue** is available even when installed catalogs do not recognize the product.
- Agent answers render bold and inline code while escaping agent-supplied HTML.

### 1.3.1

- Local research prioritizes exact-model issue forums and owner reports, filters ads and repair-service offers, and replaces irrelevant pages before using the page limit.
- Exact model codes and the selected search language are preserved. Response and search languages can be set independently.
- Bundled OpenSERP stays usable when some search engines are unavailable, and the desktop recovers its search process after it exits.
- Coverage and evidence rejection reasons are visible. An empty result does not establish that a product has no problems.
- The updater recognizes this as newer than 1.3.0. Release downloads include `SHA256SUMS.txt` for verified updates.
