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

## 12. Agents faster, and no tokens spent on a site's code *(2026-10-05)*

> "Aight id like to work on the speed and the efficiency of the agents in the
> app. Currently they work very well but they are kinda slow. Like annoyingly.
> Plus I dont want them to spend too much tokens on gibberish of the code in
> the sites. These goes for the local agent too."

- **Where:** every research and quick-look run, on each plane: a coding-agent
  CLI (harness), the API agent, and the local agent (Ollama), as the run's log
  and its spend line show them.
- **Done when:** a spawned Claude Code run loads only its search and fetch
  tools (measured: 29 327 input tokens of fixed context before, 5 719 after,
  on 2.1.289); the page text Kriko itself reads for a model (the plain
  fetch, the hosted readers, the browser rung) carries no menus, comments,
  markup or link and image addresses, so a listing site's first window is
  its content rather than its navigation (a CLI's own fetch tool is the
  CLI's, and out of reach); the window shown to a
  model is the part of the page about the subject, not its first N
  characters; the local agent searches in parallel and stops waiting for a
  page that has not answered within a deadline; and `tools/gate.sh` passes.
- **Not this:** a smaller model, fewer pages, or a lower quality bar. Same
  work, less waste.
- **Owner:** `claude/agent-speed-token-efficiency-frw1ev`.

## 13. Extension follow-up questions, stable knowledge cards and queue help *(2026-10-05)*

**Asked:** "Web extension i believe needs some work. The new knowledge instantly appears but we lack the follow up questions there and new knowledge cards gets blinks. For the new users queue up feature must have a \"?\" Icon or some sort to show what it is and how to use it. Let's start with this."

- **Where:** the browser extension's listing panel: research follow-up questions,
  knowledge cards updated while open, and Add to queue.
- **Done when:** research follow-up questions appear and can be answered in the
  panel; incoming knowledge keeps existing cards, expansion and reading position
  stable without replaying entrance animations; a keyboard-accessible question
  mark beside Add to queue explains what is saved and how to research it in
  Kriko's Compare screen. Regression checks and a browser preview demonstrate
  these behaviors. Windows/browser install verification and merge remain open.
- **Not this:** questions available only after leaving the extension, or queue
  help that starts a research job itself.
- **Owner:** this session / `fix/extension-followups-stable-cards`.
- **Observed on the branch:** the Chromium preview answered two follow-ups
  through the real saved-job API (a stand-in only at the model boundary),
  supplied the earlier exchange to the second question, and restored both
  answers on reload. New cards kept the existing card, expansion and focus,
  moved its reading position by under one pixel, and started no entrance
  animation. Queue help opened with the keyboard. Proof is in
  `.walk/extension/journey.json` and the screenshots beside it. The extension
  suite, full Python suite, lint, types and dashboard gate passed; the Python
  suite used a writable temporary log fallback for this cloud workspace.
- **Left:** native Windows browser/installed app verification; keep this
  item open until observed there.

## 14. Show who is asking and which agent is answering *(2026-10-05)*

**Asked:** "Oh no wait it was the prompt and answer. I didnt notice since there was no indicator that which agent was running and which is prompt and the answer."

- **Where:** follow-up exchanges in the extension's listing panel.
- **Done when:** each question is labelled You and each reply has a separate
  Answer label; the running reply names the agent chosen by the backend and
  shows its status; the identity stays beside the saved answer after reload.
  Regression tests and the Chromium preview demonstrate this.
- **Not this:** removing answer content because it was mistaken for helper text.
- **Owner:** this session / `fix/extension-followups-stable-cards`.
- **Observed on the branch:** the Chromium preview showed separate question
  and answer blocks, the backend's local model identity while Answering,
  then Answered with the same identity after reload. The model alone was a
  preview stand-in; job storage and polling used the real API. Screenshots:
  `.walk/extension/follow-up-running.png` and `follow-up.png`. All 227
  extension tests, all 2408 Python tests (21 skipped), Python lint and app
  types passed. The Python suite used the cloud workspace's writable log
  fallback as in item 13.
- **Left:** native Windows browser/installed app verification; keep this
  item open until observed there.

## 15. One polished working indicator in the live panel *(2026-10-05)*

**Asked:** "Very nice. Could you also fix the animation on the live panel, on the right side of the app. There is too much \"working\" status icon. There was 2 of them keep one and Polish it. Make it suitable for the general theme the stage lights."

- **Where:** the native app's right-hand Live actions panel, Working now rows.
- **Done when:** each row has one animated phase indicator in the app's LED
  style; the duplicate ripple is gone; the agent mark and progress meter are
  steady; fixed stage lights fade smoothly without bouncing or flashing;
  phase labels remain readable and Reduce motion keeps the lights still.
- **Not this:** changing research progress or replacing agent identities.
- **Owner:** this session / `fix/extension-followups-stable-cards`.
- **Observed on the branch:** the native GPUI crate passed `cargo check`.
  The browser motion preview kept the lights' positions fixed while their
  brightness changed, and froze them with Reduce motion. It is a recreation
  using the native theme and mark data, not a native window capture; proof is
  in `.walk/live-panel/preview-check.json`, `stage-lights.png` and the native
  build log beside them. The shared phase-light component supplies the same
  quieter motion in the app's other phase labels.
- **Left:** native Windows browser/installed app verification; keep this
  item open until observed there.

## 16. More visible stage lights and recognizable agent icons *(2026-10-05)*

**Asked:** "Okay way clear. Are you the goat himself? I just like to see a more stage lady thing onto the left of the reading writing thinking. And can you work on the antigravity and the claude? Reflect their icons more maybe?"

- **Where:** the native live panel's phase labels and agent marks.
- **Clarified:** item 17 replaces the earlier spotlight-shaped selection
  with the app's LED dot-matrix style.
- **Done when:** an animated LED activity glyph sits to the left of
  Reading/Writing/Thinking, keeping one activity indicator and reduced motion;
  Claude and Antigravity marks more closely follow their published shapes
  and colours, remaining recognizable at the live panel's small size.
- **Not this:** bringing back duplicate activity animations.
- **Owner:** this session / `fix/extension-followups-stable-cards`.
- **Observed on the branch:** the final dot patterns and their native
  renderer are recorded under item 18; no smooth-logo substitution remains.
- **Left:** native Windows browser/installed app verification; keep this
  item open until observed there.

## 17. Phase indicators in the existing LED dot-matrix style *(2026-10-05)*

**Asked:** "No not like that xd. Like we have ! And ✅️❌️ as spotlight you know dots, some lights are some of they do animations etc. Like that not like that xd"

- **Where:** the indicators to the left of Reading/Writing/Thinking in
  the native live panel.
- **Done when:** the literal spotlight is replaced with a recessed 5×5 LED
  glyph using the same lit and unlit dots as the app's !, check and cross;
  reading scans, writing lights in sequence and thinking shimmers; one
  indicator per working row remains, and Reduce motion holds the glyph still.
- **Not this:** a drawing of a physical lamp.
- **Owner:** this session / `fix/extension-followups-stable-cards`.
- **Observed on the branch:** the native crate passed `cargo check --offline`.
  The browser recreation loaded the agent artwork, fitted the 300px dock,
  showed animated lit/unlit cells at fixed positions, and froze them when
  motion was reduced. Proof: `.walk/live-panel/phase-matrix.png`,
  `matrix-preview-check.json` and `matrix-native-check.log`. This uses the
  existing native matrix renderer and phase motions; the browser preview
  is a recreation, not a native window capture.
- **Left:** native Windows browser/installed app verification; keep this
  item open until observed there.

## 18. Keep the agent logos in the LED matrix design *(2026-10-05)*

**Asked:** "Oh wait I just saw. The calide and antigravity shouls follow that the led matrix design too, I just wanted to represent them more"

- **Where:** the native app's Claude and Antigravity marks, including the
  live panel beside its LED phase indicators.
- **Done when:** both marks use the existing LED renderer, with recognizable
  dot patterns based on their published shapes and brand colours; there are
  no embedded smooth-logo substitutions. The final preview demonstrates
  both marks beside the single phase indicator, and the requested PR is
  opened and merged after checks and review.
- **Not this:** smooth SVG logos beside otherwise pixelated indicators.
- **Owner:** this session / `fix/extension-followups-stable-cards`.
- **Observed on the branch:** both marks render as 11×11 LED matrices
  sampled from the published silhouettes. The final browser recreation
  shows both at the live panel's actual width, one animated phase glyph per
  row, and reduced motion; `cargo check --offline` passed. Proof:
  `.walk/live-panel/led-marks-final.png` and `led-final-preview-check.json`.
- **Left:** native Windows browser/installed app verification; keep this
  item open until observed there.

**Final branch verification (items 13–18):** rebased onto the current main;
`tools/gate.sh` passed (2435 Python tests, 227 extension tests, dashboard
tests/types, wheel smoke check, lint and types). Native GPUI `cargo check`
passed. Legacy Tauri cargo checks were skipped by the gate because its
offline dependencies are not cached. The Python runner used a writable
temporary log fallback. Screenshots and observations are committed in
`docs/previews/extension-live-panel/` for PR review. The reader authorized
opening and merging the PR; Windows visual/install checks remain open.

## 19. Svelte is gone: the GPUI app is the only window *(2026-10-05)*

> "Bro demolish that svelte. Like, literally nuke it. Not the web extension
> though. We moved to guide completely works better and somewhat easier to
> read."

- **Where:** the repository tree, `tools/gate.sh`, and the engine's own
  address in a browser (`http://127.0.0.1:<port>/`).
- **Done when:** `ui/`, `kriko-svelte/` and the committed bundle under
  `src/app/web/static/` are deleted, with every test, gate step, packaging
  line and document that existed only for them; the engine still serves every
  `/api/...` route the GPUI app, the TUI and the extension read; the
  extension's own files, palette and tests are untouched and pass; and
  `tools/gate.sh` passes with no `ui` leg.
- **Not this:** removing the browser extension or any `/api` route.
- **Owner:** `claude/agent-speed-token-efficiency-frw1ev`.
- **Observed on the branch:** `ui/`, `kriko-svelte/`, the bundle and
  `tools/walk.sh` are gone; `/` answers a one-line notice; `tools/gate.sh`
  passed (2418 Python tests, 227 extension tests, wheel smoke) with no `ui`
  leg. The extension's files changed only in two palette comments.

## 20. A benchmark no model can answer from memory *(2026-10-05)*

> "For the extension I think we need a better process a product that any
> agent do no know. With made up websites, complex one medium complex and a
> simple one. Then a real one, a very complex good like a car with many
> different components, a middle complexity one and a simple one. Each good
> have tricky similar goods. Agents gotta differentiate between 2010 k5k and
> 2020 k5k and 2020 k5k with adblue. The non existing good important since it
> might be a leverage for the local small agent. Beating the training data
> with our algorithms against giant sota models."

- **Where:** kriko-gpui's Benchmark tab, and the engine's benchmark job.
- **Done when:** the fixed set has two halves. *Invented:* three products
  that exist nowhere (complex, medium, simple), each with look-alike siblings
  that differ by year or one fitted part, listed on three made-up listing
  sites (complex, medium, simple layout) and discussed on made-up source
  pages, all served from a local fixture so no search engine and no training
  set has ever seen them. *Real:* three real products (a car with many
  components, a medium one, a simple one), each with look-alike siblings,
  listed on the same made-up sites and researched on the open web. Ground
  truth is per variant, and a fault that belongs to a sibling but not to the
  asked variant scores as *wrong variant*, apart from recall and
  hallucination. Every plane runs the same set, and the Benchmark tab shows
  recall, hallucination and wrong-variant rate per plane and model from the
  engine's own rows, invented and real side by side.
- **Not this:** sample constants on the tab, or cases drawn from the
  reader's installed packs.
