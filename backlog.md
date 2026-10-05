# Kriko: the backlog

**Reset 2026-10-02.** The sheet is blank. The app is being rebuilt in GPUI
(https://gpui.rs/) and this file starts over with it. Everything before this
reset is in `git log`.

How items are written, per `docs/DOCTRINE.md`:

- Every item quotes the request, names the screen, and says what counts as
  done. No "Done when", no start.
- A finished item leaves this file. Its commit message carries the reasoning;
  `git log` is the record.

## 10. 1.0.0: kriko-gpui is the app *(2026-10-04)*

> "Let's make the real app. push the work we've done first and then we are
> making the version 1.0.0 with the kriko-gpui; make sure that everything
> works like a efficient diesel machine"

- **Where:** a double-clicked Windows install of Kriko 1.0.0, and every tab
  of the window it opens.
- **Done when:** the installer puts the GPUI app and the engine on the
  machine (no webview, no Tauri); opening it starts the engine and the
  window shows the engine's own data on every screen (no sample constants);
  Run starts a real check and shows its stages; History, Browse, Compare and
  the research queue read the engine; closing the window keeps the engine
  serving the extension until Quit; a failed engine start shows its stderr
  instead of a blank window; the version reads 1.0.0 everywhere; and
  `tools/gate.sh` passes.
- **Left:** the reader's own run. Observed 2026-10-05 on the built MSI
  (`dist/kriko-1.0.0-x86_64.msi`): a silent per-user install, the desktop
  shortcut opens the app with no terminal beside it, the app starts its own
  frozen sidecar (health 1.0.0 in 2 s), every tab shows the engine's data,
  closing hides the window while the engine keeps serving, a second launch
  raises the first, and uninstalling a running Kriko stops it and removes
  the folder, the shortcuts and the HKCU key, keeping `~/.kriko`. Not
  observed by an agent on purpose: Run starting a real check, which spends
  the reader's agent. Done when the reader double-clicks the install and
  runs one.

## 11. The local agent: the app's flagship, scaffolded for a small model *(2026-10-04)*

> "I'd like to work on the local agent guy, making it the selling features
> of the app. though it will be open source we aint selling anything. I'd
> like to enrichen our structure and the add many components possible to make
> sure that it works yet being a small model."

- **Where:** the Local LLM tab of the kriko-gpui app, and a local run of the
  quick look on the local plane (Ollama).
- **Done when:** the local agent is a set of named components, not one
  190-line script — query planning with a JSON repair loop (a reply that
  fails as JSON is asked again, bounded, before anything is searched),
  context-aware page triage (the pages chosen for the prompt are sized to
  the model's own context, ranked, and the count the model saw is the
  count its quotes are checked against), a second search round that learns
  from the first, and a self-verify pass whose verdict is kept with the
  answer — and the Local LLM tab shows a real run's stages, the pages it
  read, its spend and the verify verdict from the engine, no sample
  constants; a small model that breaks JSON once still completes the run;
  and `tools/gate.sh` passes.

## 12. Compare with a small local model *(2026-10-05)*

> "I'm trying to make the seeling point of the app with the compare screen. app is opensource though. trying 4b and lower param models are the target but ui must include higher param models for high vram users. every process should work seamlessly with high accuracy with efficient token usage on scraping and crawling."

- **Where:** Compare follow-up questions and Local LLM model setup in the GPUI app.
- **Done when:** Compare offers the ready local model beside connected agents; a local question answers from the saved checks without a web search, fits a bounded relevant table into a small model's context, distinguishes recorded facts from unknowns, and the Local LLM screen keeps larger available models selectable alongside small ones. Tests prove the local question makes no search call and preserves each compared product.
- **Not this:** inventing facts or hiding larger installed models to promote small ones.
- **Owner:** agent-compare-operations worktree.
- **Left:** the code and automated checks are in the worktree; the installed GPUI screen still needs a visual walk, and the branch needs integration with the local agent refactor in the main checkout before this item can leave the backlog.

## 13. Make local operations easy to reach and inspect *(2026-10-05)*

> "work on the ui integration more, make everything accessible easily and observable"

- **Where:** Compare follow-up questions and the Local LLM tab in the GPUI app.
- **Done when:** a reader can get from local model setup to Compare and Run in one press; the Local LLM tab lists recent local jobs with a path to each run; Run exposes a local quick look's cited pages, token use, and self-check verdict when recorded; Compare shows which model answered, what saved material it read, live progress, token usage when reported, and the outcome after reopening the draft; missing usage is shown honestly. A failed question remains inspectable after reopening. The display reads durable job data, and GPUI tests pass.
- **Owner:** agent-compare-operations worktree.
- **Left:** code and focused checks are in the worktree; the installed GPUI screen still needs a visual walk, and the branch must be integrated with the main checkout's uncommitted local-agent refactor.
