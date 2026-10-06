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

## 23. App background and browser toolbar connection *(2026-10-06)*

> "let's handle the background state of the app since it has to connect to the web extension. and handle the web extensions small icon on the browser please"

- **Where:** the Windows tray after closing the Kriko window, and the browser extension's toolbar icon.
- **Done when:** closing the window leaves the supervised engine reachable on the extension's fixed local port, the tray can reopen or quit it, and the toolbar icon shows whether that engine is reachable without hiding the per-page risk badge. Clicking the icon still opens the in-page panel when Chrome permits it.
- **Not this:** keeping an invisible process alive after Quit, or claiming the app is connected based only on a cached result.
- **Owner:** `codex/background-extension`.
