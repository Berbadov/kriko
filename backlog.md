# Kriko: the backlog

**Reset 2026-10-02.** The sheet is blank. The app is being rebuilt in GPUI
(https://gpui.rs/) and this file starts over with it. Everything before this
reset is in `git log`.

How items are written, per `docs/DOCTRINE.md`:

- Every item quotes the request, names the screen, and says what counts as
  done. No "Done when", no start.
- A finished item leaves this file. Its commit message carries the reasoning;
  `git log` is the record.

## 9. Queue mode: products are queued from the browser extension *(2026-10-04)*

> "queue is added by the web extension btw. let's do that for the end."

- **Where:** the extension's panel on a listing (Alt+K), and kriko-gpui's
  Compare, Research queue card.
- **Done when:** the panel has an Add to queue key that puts the listing's
  product in the app's research queue (kept in `app.sqlite`, survives a
  restart, a second press does not queue it twice) and says how many are
  queued; the engine serves the queue at `/api/queue`; and the Compare
  queue card says its products come from the extension and shows where each
  one was queued from.
- **Left:** the engine half and the panel key are done and tested; the
  Compare card still shows sample items until the app reads `/api/queue`
  (item 10).

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
