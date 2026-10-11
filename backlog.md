# Kriko: the backlog

**Reset 2026-10-02.** The sheet is blank. The app is being rebuilt in GPUI
(https://gpui.rs/) and this file starts over with it. Everything before this
reset is in `git log`.

How items are written, per `docs/DOCTRINE.md`:

- Every item quotes the request, names the screen, and says what counts as
  done. No "Done when", no start.
- A finished item leaves this file. Its commit message carries the reasoning;
  `git log` is the record.


### B201 — Local agent pipeline and language settings
**Asked:** "Bro make the ultimate local agent pipeline with product identification, languiage settings, and the things ive said. you can use Luna 6s as subagents" (2026-10-11)
**Where:** Local machine settings; listing Quick Look cards and research job log.
**Done when:** Local research identifies the exact listed product, obeys the selected response language, searches independent sources without free Exa, preserves source quotes, rejects unsupported evidence, and reports pages read separately from sources per finding. Small installed models are compared using identical evidence and settings.
**Not this:** A changed source counter or a promise that a tiny model always tells the truth.
**Owner:** current session / main; root pipeline, Luna language settings and identification.

### B202 — Retire the obsolete Svelte/Tauri desktop app
**Asked:** "WAIT we are stoppped using the svelte one bro. we use gpui with web extension remove that old app" (2026-10-11)
**Where:** Desktop packaging and the Python HTTP service that the GPUI app and browser extension use.
**Done when:** The old Svelte/Tauri app, static bundle, and its build/release gates are removed; the Python API remains usable by GPUI and the extension without requiring frontend files.
**Not this:** Removing the browser extension, its resources, Python engine/API, or GPUI app.
**Owner:** current session / main.

### B203 — Local research searches issue discussions and survives partial search degradation
**Asked:** "did a search with qwen3.5:4b no results are shown"; "lemme say that real quick: agents are going to the product pages instead of issue forums and sites" (2026-10-11)
**Where:** Local Quick Look, research job log, and Local machine readiness.
**Done when:** Searches prioritize exact-model owner problem discussions and repair reports rather than catalog/specification pages or advertisements; irrelevant pages are replaced within the page budget; rejection reasons remain visible; one failed OpenSERP engine does not block working engines. The corrected native installer reaches the reader.
**Owner:** current session; root retrieval/identity/health, Luna search result filtering, native supervision, and empty output display.
