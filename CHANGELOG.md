# Changelog

Reader-visible changes for releases older than the three shown in the
[README](README.md#whats-new). Newest first. Published versions are immutable; a
correction is a newer version (see [the update protocol](docs/UPDATE_PROTOCOL.md)).

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
