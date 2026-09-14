# Kriko — Backlog

Prioritized open work. Read `CLAUDE.md` (product, scalability, automation principles)
before picking anything up. When an item is finished, move it to `done.md` with the
date and commit hash.

- **P0** — actively hurting buyers or blocking everything else
- **P1** — the next round of high-leverage work
- **P2** — real, but can wait

Evidence for many items comes from production logs: `logs/analyses.jsonl`
(`python -m ops.reports.analyses --last 20`).

---

## Goals (2026-08)

**G1 — Quality over quantity.** A buyer sees at most ~8 risks, and they are the
*general chronics*: config-specific, high-consequence, multi-source-corroborated issues.
Today a DSG Golf gets 39–86 cards; nobody reads 39 cards.

**G2 — Cut pipeline cost per car by ~10×.** Classification spend must be budgeted,
cached, and reported. **(Landed 2026-07-22 — B1 closed.)**

**G3 — No silent coverage holes.** If a car is automatic, its gearbox chronics must show.
Ad-vs-catalog contradictions and empty part files must be *visible* (coverage_state,
coverage report), never a quiet zero.

**G4 — One trunk.** **(Done 2026-07-22 — all branches merged, worktrees pruned.)**

**G5 — Fully automated pipeline. Zero human-in-the-loop** *(new 2026-08-03)*.
Extraction and scraping run unattended; nothing in the data path — evidence, catalog
rows, gates, sources — may wait for human verification, spot-checks, or sign-off.
One-time *policy* decisions are allowed (market coverage, source licensing); per-car
and per-datum review is not. Where a value cannot be derived automatically, the system
**fails open** (no claim, no guess) and logs the gap; the log drives the next automated
pass, never a human TODO. This retires HUMAN DECISION #6/#7 (B17/B11) and all
"manual audit/spot-check" backlog steps.

**Cross-cutting rule — systemic only** *(2026-08-03; replaces the patch-and-mechanism
pairing)*. The catalog grows to thousands of models, so *no per-model fixes exist*.
Every fix ships as a mechanism that runs for all cars (coverage report, contradiction
surfacing, auto-remediation). Per-model manual steps (research runs, YAML audits,
spot-checks) are cancelled, not deferred — see B19, which absorbs B2/B3.

---

## Goal G6 — Kriko becomes a product knowledge engine *(new 2026-08-26)*

Kriko stops being a car product and becomes an open-source, local-first knowledge
engine for any manufactured product. Cars become pack #1. Design and phases:
`~/.claude/plans/let-s-go-with-the-eager-torvalds.md` (to be moved into
`docs/superpowers/specs/` when Phase 1 lands).

The pivot rests on one change: **slots become rows, not columns.** `variants`
assumes every subject has a make, a model, an engine code and a displacement —
already false for an EV, hopelessly false for a cordless drill with no components.
Two contributors modelling a category differently must still produce mergeable
databases; columns cannot union, rows can.

Locked: subject/attribute/value rows in SQLite; `pack_id` on every row; no central
authority (contradicting claims coexist, ranking happens at read time); packs
authored as a directory and shipped as one `.kpack` file; Postgres and Docker
deleted; research pluggable between the $0 agent/MCP path and an Exa/Tavily+LLM
path; every install is both reader and author; language is a row attribute;
monorepo with `packs/` beside the engine.

### Current delivery constraint — web-first minimal slice
The next milestone is a usable local browser workflow, not another CLI-only path. Every
operation must be operable and inspectable from the dashboard with a visible result,
error, and durable status. The minimal slice covers: health and installed pack state;
pack build/install/revision/enable/disable/uninstall; generic product/listing analysis;
identity, coverage, flags, ranked claims, reasons, and sources; subject browsing;
coverage gaps; recent activity; and explicit empty/unknown results.

Research execution and the remaining pipeline separation stay behind browser-visible
job state rather than requiring a terminal, MCP client, or manual data-path step.

### B29 — Phase 1: the `kriko/` core `[G6]` **(LANDED 2026-08-26)**
`kriko/store/{schema.sql,ids.py,db.py,packstore.py}` + 28 tests. WAL on; two
databases, never merged. `test_kriko_core_never_imports_a_domain_layer` in
`ops/tests/test_repo_invariants.py` is the mechanical guarantee that adding a
category stays a data-only change.

Corrected while writing the tests: identical facts from two packs do **not**
collapse to one row. `pack_id` is in every primary key, so each pack keeps its
own row with the same content hash — otherwise uninstalling one pack would
delete a fact the other still asserts. Dedup is a read-time `GROUP BY` on the
agreeing hash, never a storage-time merge.

### B30 — Phase 2: pack format and the drill pack `[G6]` **(LANDED 2026-08-26)**
`kriko/pack/{manifest,build}.py` + `packs/drill/` + 24 tests. Authoring a pack is
data-only: YAML in, SQLite out, no Python. The builder validates strictly — a
claim pointing at a nonexistent subject, or an attribute using an undeclared
term, fails the build rather than shipping a row nobody would see.

The drill pack is deliberately **synthetic** (`synthetic = true`, every URL on
the reserved `example.invalid` domain, pinned by a test). It exists to falsify a
car-shaped format, not to inform: no engine/fuel/displacement, wear measured in
`charge_cycles`/`usage_hours`, and one product with zero relations. Rebuild it
from real sources once the researcher interface lands in Phase 5.

### B31 — Phase 3: generic lookup `[G6]` **(LANDED 2026-08-26)**
`kriko/lookup/{conditions,match,rank,query}.py` + 52 tests. Replaces
`matcher.py` (226) + `resolver.py` (650) with no car knowledge in either.
Read-time trust; `stance='refutes'` halves rank and shows the rebuttal.

The condition evaluator answers in **three** states, not two: `met`, `unmet`,
`unknown`. Unknown is where an engine starts lying — an unstated mileage makes a
"fails after 150k" claim neither true nor false, so it is served and downranked
with the reason attached, per the fail-open rule in G5.

`test_packs_that_disagree_on_identity_keys_still_both_answer` covers the design's
riskiest property (two authors, different identity keys, different hashes, must
still union). `test_core_is_domain_free.py` walks kriko/'s AST for car vocabulary
in executable positions and carries its own negative test.

### B32 — Phase 4: cars pack + parity `[G6]` **(LANDED 2026-08-26)**
`packs/cars/` — 699 claims, 26 variants, 21 parts, 89 relations, 676 conditions,
725 evidence rows. `parity_golden.jsonl` captured (98 rows) while both engines
still exist. Two gates green over 98 real listings: wherever the old engine
matched, the new one resolves the identical car; and all 2,121 old claim
instances are represented.

Three deliberate divergences, each asserted by a test rather than assumed:
status became rank (**closes B26**), year windows are soft (**B9**), and part
attribution is stricter — the old sync served DC4 gearbox faults to a diesel
Mégane out of the *h5f petrol engine's* part file, a car not fitted with that
engine. Five titles listed in `KNOWN_ATTRIBUTION_FIXES`; the list must shrink to
nothing when the catalog is refiled.

Found while measuring: compatibility gates must be suppressed for any attribute
the part is fitted *across* (a gearbox shared by petrol and diesel spans both
fuels, so a text signal naming a petrol engine describes the source, not the
part). Derived from fitment, never an exception list.

### B33 — Phases 5–6: interfaces, then delete the old path `[G6]`
CLI + web (finishing `ops/hub/web.py`, which lands B28) + MCP on the new core;
extension becomes a cars-pack site adapter. Then `backend/`, `knowledge/catalog/`,
`ops/swap.py`, `ops/process.py` go.

- [x] Phases 5a–5d **(landed 2026-08-26)** — CLI, MCP, the two research planes,
      the local dashboard, and the pack-declared site adapter.
- [x] **Phase 6a landed 2026-08-27** (`e5d7951`): `backend/` and `deploy/` deleted,
      `ops/{hub,mcp,reports,swap}` gone, the car catalog moved to
      `packs/cars/data/`, the coverage report moved to `packs/cars/coverage.py`
      and now derives servability from the pack manifest. Layering re-derived
      from a column to a fan and re-enforced in `test_repo_invariants.py`, with
      a ratchet that keeps `backend/` deleted. Suite 534 -> 535, 3m -> 18s.
- [x] **Phase 6 docs landed 2026-08-27** — `README.md` and `CLAUDE.md` rewritten
      for the pack architecture (every command in the README verified to run).
- [x] **Phase 6b landed 2026-08-29** (`f038df9`) — generic ledger/extraction primitives moved
      to `kriko/ledger/` and `kriko/extract/`; car catalog, sources, parts, fitment,
      acquisition, export, resolution, and research policy moved to
      `packs/cars/pipeline/`; `knowledge/` is deleted. Pack vocabulary and gate
      terms are data, not engine constants. `app/pipeline/` owns orchestration.
- [x] **Phase 6c landed 2026-08-27** — the Chrome extension is on the new
      protocol and the client keeps no site knowledge of its own.
      `content.js` reports the page's own label/value pairs and interprets
      nothing (697 -> 426 lines; `mapTurkishKeys`, `mapTechnicalDetails`,
      `parseMakeModelFromTitle` and its hardcoded make list are gone);
      `background.js` POSTs that to `/api/analyze` on 8787 and asks
      `/api/adapters` which sites are worth scraping at all; the panel renders
      the resolved identity rather than its own reading of the page. JS tests
      14 -> 36, with `background.js` covered for the first time. Verified end
      to end against the real cars pack: both captured fixtures resolve to a
      full identity with **zero unmapped labels** and 8 ranked claims.

      Five bugs the rewire found, each fixed as a mechanism:
      - **`packs/cars` could not be built.** Phase 6a moved
        `trust/source_tiers.yaml` in from `backend/` unchanged and the builder
        expected a different shape; nothing noticed, because every suite built
        its own fixture and the one pack that ships was never built in CI.
        `test_every_pack_in_the_repo_builds_and_is_not_empty` is the mechanism
        (it also catches the empty-build case, since a pack may ship its own
        `build.py`), and an unreadable trust file is now a build error rather
        than a pack that silently trusts nothing.
      - **A near-miss label answered for a rule.** "Yakıt Tüketimi" contains
        "yakıt", so consumption could be read as the fuel type. Labels now
        match exact-before-loose, and `ignore_labels` is a real blocklist
        rather than a reporting filter.
      - **Turkish "İ" broke every accented label.** It casefolds to "i" plus a
        combining dot, so `İlan No` never matched `ilan no` and the adapter
        carried hand-kept transliterations. Both ends now strip combining
        marks (letters, including "ı", are untouched).
      - **The title fallback needed a make list.** Replaced by `vocabulary`:
        an adapter rule says "find a known value of this attribute in the
        title" and `kriko/` resolves it from the packs' own `is_identity`
        rows — no list, in any language, and it works for a category nobody
        has written yet.
      - **The panel footer would have read "unknown" forever** (B15's
        deploy-staleness guard, pointed at a `build` field the new payload has
        no reason to carry). Re-pointed at what a reader now needs: which
        pack, at which version, answered.

      New adapter vocabulary, all closed and all interpreted server-side:
      `from` (a labelled rule's text fallback), `vocabulary`, `segment`.
      `/api/analyze` also returns `packs` and `context_units`; `/api/adapters`
      returns `labels`.

- [ ] **Phase 6c follow-up — the manifest is the last hardcoded site list.**
      `extension_ui/manifest.json` still names `*.sahibinden.com` in
      `content_scripts.matches` and `host_permissions`, so installing a pack
      for a second listing site does nothing until someone edits it. Every
      other layer is now adapter-driven. The fix is
      `chrome.scripting.registerContentScripts` over the adapters' `site`
      values, but MV3 cannot inject into a host it has no permission for, so
      it needs `optional_host_permissions` plus a user grant — a UX decision,
      not a mechanism gap, which is why it is filed rather than done.
- [x] Architecture and usage docs rewritten for the new `app/`, `kriko/`,
      `packs/`, and `extension/` layout; old interface references removed from
      active documentation. Older product-quality work is re-filed against the
      new core where still applicable.

**HUMAN DECISION #8 — resolved 2026-08-29.** Choose the long-term split: generic
ledger/extraction lives in `kriko/ledger/` and `kriko/extract/`; car-specific
acquisition, catalog, parts, fitment, export, and research policy live in
`packs/cars/pipeline/`. `app/pipeline/` is orchestration only. This leaves a
pack-supplied seam for future categories without making the core car-aware.

---

## P0

### B110 — `requires-python = ">=3.14"` cannot be satisfied today `[dev]`
Found 2026-09-13 while writing `tools/setup.sh`. There is currently no
interpreter on which a clean setup of this tree succeeds:

* **Python 3.13** — `uv pip install -e .` refuses: *"only kriko==0.8.0 is
  available and the current Python version (3.13.12) does not satisfy
  Python>=3.14"*.
* **Python 3.14.0rc2** (the only 3.14 uv can fetch) — installs cleanly and then
  `import fastapi` raises `AssertionError` inside `pydantic/_internal/
  _typing_extra.py`: the pinned `pydantic==2.13.4` cannot run on that
  pre-release's `typing._eval_type` signature.

`tools/setup.sh` now refuses loudly in both cases rather than reporting
"ready" on a tree that cannot import its own app — which is what its first
version did, and exactly the failure a setup script exists to prevent.

**The evidence worth weighing:** the full suite, both JS suites, svelte-check
and the stale-bundle check all pass on **3.13** (`tools/gate.sh`, green on this
branch). So the `>=3.14` floor is not load-bearing for anything the tests
cover; it is currently only blocking setup.

**Decision needed** (a policy call, not a mechanism): relax the floor to
`>=3.13`, or keep `>=3.14` and wait for a stable release. Keeping it is
defensible — `desktop.yml` pins `python-version: "3.14"` and the frozen sidecar
ships whatever it was built with — but while no stable 3.14 exists for a given
platform, a contributor there cannot set the tree up at all except by the kind
of hand-rolled workaround that produces an environment nobody else can
reproduce. Do not change it without deciding; a floor that moves by accident is
worse than either answer.


### B109 — Terminal: CLOSED 2026-09-13 by dropping the WebSocket (0.7.12)

**Resolved.** Six entries below chased a cause inside `terminal_ws`; the
seventh answer was that the handler was never the component at fault. The
socket's own evidence said so: the fifth entry's raw probe got `101` and real
PTY bytes out of the frozen binary on the reader's machine, and the sixth
entry's banner came back `1006` — the handshake never finished, at a layer
below anything this app controls. The terminal was also the only WebSocket in
the tree, next to a `/api/jobs/{id}/stream` that works in the same install.

So it is SSE + `POST` now (`docs/INTERNALS.md`, and the 2026-09-13 entry in
`done.md`), with a polling fallback under that and a relative URL that cannot
disagree about the port. The transcript lives on the session, so a failure is a
field one GET can read rather than a frame someone had to be connected for.

**What is left is verification, not cause-hunting**: 0.7.12 has to reach the
reader in an installer (app-first rule 4) and open a shell. If it does not, the
next fact to get is `GET /api/terminal/state` — which answers with the reason
whether or not anything is connected, and which the reader can reach from a
browser.

The six-entry history below is kept verbatim; it is the record of how a
component-level assumption survives six correct fixes.

#### Original entry — Terminal (B107): still shows "disconnected" on 0.7.5, cause unknown
Reported live 2026-09-11, right after the 0.7.5 hotfix (which fixed a confirmed,
verified bug — `winpty-agent.exe` missing from the frozen sidecar, see done.md).
The reader installed 0.7.5, and the terminal panel now shows an explicit
"disconnected" state (`ui/src/lib/shell/TerminalPanel.svelte`'s `ws.onclose`
path) rather than a bare black screen — progress, but the terminal still does
not work, and the *reason* is not yet known.

The reader's `app.log` after reproducing showed nothing at all about it — no
exception, no traceback, not even a log line from `app.web.routers.terminal` —
which turned out to be a second, real, independently-fixed bug: `app.sidecar`'s
`uvicorn.Config(...)` used the default `log_config`, which calls
`logging.config.dictConfig` and gives "uvicorn" its own stderr handler with
`propagate=False`. Any unhandled exception in *any* route (logged through the
child logger "uvicorn.error") stopped there and never reached the root logger
`app.logs.configure()` attached to `~/.kriko/logs/app.log` — visible on stderr
only, and nothing reads this app's stderr once the shell's window has opened.
Fixed by passing `log_config=None` (skips the `dictConfig` call; `log_level`
still applies independently) — verified with a real subprocess + real
exception in `test_an_unhandled_exception_in_a_route_reaches_the_app_log`
(`src/app/tests/test_sidecar.py`), which fails without the fix and passes with
it. This closes a real, systemic diagnostic gap (any route's crash was
invisible past the first few minutes, not just the terminal's) but it is a
visibility fix, not a fix for *why the terminal disconnects* — that is still
open.

Next step: ship the visibility fix, ask the reader to reproduce again and send
the new `app.log`, which should now actually name the exception. Leading
guesses not yet confirmed: `SESSION.start()` raising again for a different
reason than the agent gap (`winpty.PtyProcess.spawn` failing on the specific
shell resolved from `COMSPEC`), or an antivirus/SmartScreen action against the
newly-added, unsigned `winpty-agent.exe` on the reader's real (Program Files)
install path — plausible because the build machine's own smoke test spawns the
exe from a temp/build directory, not Program Files, and running unsigned for
the first time there is untested. Do not guess further without the log.

**Second gap found while chasing this one, closed 2026-09-11**: `app.log` was
never the *only* way to learn the reason — the terminal websocket handler ran
`SESSION.start()` with no `try`/`except`, so a crash there just dropped the
connection and the panel printed the same bare `[disconnected]` regardless of
cause. The reader watching the panel had no way to see the exception at all,
log fix or not. `terminal_ws` now catches the failure, still logs it via
`logger.exception` (so a report's `app.log` names it), and sends
`{"type": "error", "message": "..."}` on the socket itself before closing
(code 1011); `TerminalPanel.svelte` writes that message into the terminal in
red and skips the generic disconnect line when it saw one. Verified with
`test_a_session_start_failure_is_reported_on_the_socket`
(`src/app/tests/test_terminal_ws.py`, in-process, `SESSION.start` monkeypatched
to raise) and a matching vitest case in `TerminalPanel.test.ts`;
`test_an_unhandled_exception_in_a_route_reaches_the_app_log` updated to match
(the socket now closes cleanly with a reason frame instead of raising on
`recv`, and the log line to look for is the route's own `logger.exception`,
not uvicorn's "Exception in ASGI application"). This still does not name *why*
`SESSION.start()` fails on the reader's machine — but the reader no longer
needs to find `app.log` at all: the next report can just be a screenshot of
the terminal panel.

**Correction, 2026-09-11**: the "no Windows access" claim above was wrong —
this WSL2 host's `/mnt/c` *is* real Windows interop (`cmd.exe`/`powershell.exe`
run fine by full path; they were just absent from the WSL `$PATH`, which is
what the earlier `which` checks actually tested), and a real `claude.exe`
exists at `C:\Users\beraat\.local\bin\claude.exe`. See B108's correction
below — checked as part of that repro. Still true: no `pywinpty` in this
Linux `.venv`. Root cause of the original crash remains unconfirmed until a
build carrying this fix reaches the reader and they reproduce again.

**Third gap, found from the reader's own 0.7.7 report, closed 2026-09-12**:
0.7.7 shipped the start()-side fix above; the reader reproduced and still saw
only "disconnected", no red text. Root cause: `start()` can return with *no*
exception and the spawned process still be dead a moment later (an AV killing
a freshly-written `winpty-agent.exe`, a bad `COMSPEC`, the shell exiting on
its own) — `pump_output`'s read loop hit `EOFError`/`OSError` there and
silently `break`, which is the exact same bare "disconnected" one step later
in the same handler. Now reports an error frame there too, same shape, same
`logger.exception` call. Verified with
`test_a_read_failure_after_a_successful_start_is_also_reported`. This closes
the diagnostic-visibility half of B109 completely (every path out of
`terminal_ws` that isn't a clean shutdown now reports why) — root cause of
the reader's actual crash is still open pending their next reproduction on a
build with *this* fix.

**Fourth gap, found from the reader's own 0.7.8 report ("still says
[disconnected]"), closed 2026-09-12**: the third gap's fix shipped in 0.7.8
and the reader still saw the bare, dim "[disconnected]" line with no red
text at all — the tell that `sawError` never flipped on the client, meaning
no `{"type": "error"}` frame ever arrived, meaning the connection never even
reached the two fixes above. Root cause: `terminal_ws`'s two *pre-accept*
rejections (the extension-port check, the origin check) both called
`websocket.close(code=1008)` before `websocket.accept()` ever ran — and a
socket that was never accepted cannot carry a text frame at all, so
`onclose` fires with no `onmessage` first and the client falls straight to
its generic disconnect line. This is the same bare "[disconnected]" as the
first three gaps, just from a rejection instead of a crash, and it is the
one path the first three fixes structurally could not have touched (they
all live inside the `try` after `accept()`). Fixed by moving `accept()`
before both checks, logging the reason, and sending an error frame in the
same shape as the other three before closing. Verified with
`test_a_rejected_origin_is_reported_on_the_socket_before_closing`
(`src/app/tests/test_terminal_ws.py`); the existing
`test_the_socket_refuses_an_extension_origin` updated to match (it used to
assert the connection raised on handshake — it now asserts an error frame
instead). This is the last close path in `terminal_ws` that could still be
silent; if the reader's next build still shows bare "[disconnected]" the
failure is upstream of this handler entirely (the socket never reaching the
FastAPI app at all), which is a different, network-level question.

**Fifth entry, 2026-09-12 — the predicted "upstream of the handler" case
confirmed, and the frozen backend proven innocent**: 0.7.9 shipped the fourth
gap's fix and the reader still saw bare "[disconnected]", no text at all —
exactly the case the fourth gap's note predicted. Rather than patch a fifth
path inside `terminal_ws` (three "fix a path inside this handler" attempts
had now each failed to be the reader's actual cause — the
systematic-debugging trigger for "question whether this is even the right
component"), the frozen `kriko-sidecar.exe` from the 0.7.9 build tree was run
directly on the Windows host and probed with a raw socket handshake
(`GET /api/terminal/ws` + `Upgrade: websocket`, `Origin: tauri://localhost`)
— no browser, no webview, nothing this handler doesn't already control. The
server replied `101 Switching Protocols` and immediately streamed real PTY
output (`\x1b[?9001h\x1b[?1004h`, a real PowerShell prompt sequence). The
backend, the websocket upgrade, and `winpty` all work correctly in the exact
binary the reader is running — the failure is entirely in how the real
webview reaches this endpoint, not in anything `terminal_ws` or `TermSession`
does. This rules out every remaining hypothesis inside this file and moves
the search to `TerminalPanel.svelte`'s `connect()`/`wsUrl()` and how Tauri's
webview navigates to the sidecar's URL.

Shipped as a diagnostic rather than a guessed fix: `ws.onclose`'s
`CloseEvent.code` (1006 = "abnormal closure", the browser's own signal for
"never finished connecting", available with **no server-sent frame
required**) now goes into the disconnect banner every time, not only when a
server frame already explained it. This is the one piece of evidence that
distinguishes "the socket never opened" (code 1006) from every other case
already covered — verified with a new vitest case
(`ui/src/lib/shell/TerminalPanel.test.ts`) asserting the code appears in the
written banner. Next reproduction should return a code, which is the next
concrete lead rather than another guess.

**Sixth entry, 2026-09-12 — 1006 confirmed, and the next fact identified**: the
reader's 0.7.10 report came back exactly `1006` — abnormal closure, confirmed,
not the origin-reject path (that one closes `1008`, with a frame, gated behind
`sawError`). This is real signal: the socket never completes its opening
handshake at all, at a layer below anything `terminal_ws` controls, even
though the raw probe proved that same handler works when dialed directly.
1006 alone doesn't say *what URL* the failing socket dialed — `wsUrl()`
derives it from `location.host` at connect time, and if the real webview's
`location.host` disagrees with what the announced sidecar port actually is
(stale, wrong port, wrong scheme), the two would silently never meet. `ws.url`
is the browser's own resolved record of that, so it now goes into the banner
alongside the code — verified with an updated vitest case
(`ui/src/lib/shell/TerminalPanel.test.ts`) asserting the URL appears in the
written banner. The next reproduction's banner is the concrete next lead:
whatever host/port it names is where the real mismatch lives.

### B108 — Agents/Connect: `claude` runs fail, cause not yet confirmed

**2026-09-13 — one silent failure mode removed (0.7.12).** `available()` was
`shutil.which()` and nothing else, and the sidecar's `PATH` is whatever the
file manager handed the desktop shell *at login*. A reader who installs Claude
Code and comes back to Kriko without logging out has the binary on disk and no
harness plane, with no error anywhere, because nothing in the process knew a
CLI existed. `harness.locate()` now searches `PATH`, `$KRIKO_HARNESS_DIRS`, and
the directories these CLIs install into, `command_for` runs the resolved path,
and `/api/research-planes` reports which binary was found. This is a mechanism,
not a per-machine patch — but it is not a confirmed fix for the original
report either, and the leading explanation for *that* remains an expired CLI
login (see the 2026-09-11 repro below).

**2026-09-13 — the plane has instruments now.** `kriko tui` (`src/app/tui/`,
see `done.md`) puts the harness binary's resolved path on screen, and where
`locate()` looked when it found none. The commonest form of "agent operations
do nothing" is now a sentence the operator can read rather than a silence.

**Still open, and the thing to build next:** a harness run is still a *captured*
subprocess with a 600s (or 2400s) ceiling and no output until it ends, so its
remaining failure modes still reach the reader as "succeeded / 0 claim(s) kept"
or a raw traceback — the TUI can only tail what the job writes to its log row.
Now that `termpty.TermSession` is a general "process with a resumable
transcript", a harness run should be one too: streamed into the jobs tab and the
web panel alike, and *answerable* when the CLI asks for a login. That is the
step that turns the class from "diagnose by report" into "watch it happen", and
it reuses the mechanism 0.7.12 already shipped.

#### Original entry — `claude` still hits the stdin race B106 was meant to close
Reported live 2026-09-11, on 0.7.4: running a harness task through the `claude`
CLI (not opencode) failed with

    RuntimeError: Claude Code exited 1: Warning: no stdin data received in 3s,
    proceeding without it. ... Error: Input must be provided either through
    stdin or as a prompt argument when using --print

which is exactly the failure `_run`'s own docstring in `src/app/providers/harness.py`
describes fixing for B92/B106 — the prompt is written to a temp file and handed to
the subprocess as `stdin=`, not as an argument, specifically so no CLI flag or
quoting can eat it. It happened anyway, on the reader's own Windows machine, so
either the fix does not cover the `claude` executable's path (npm ships it as a
`.cmd` shim wrapping `node`; B106's fix, per its done.md entry, was demonstrated
against opencode) or the CLI's own stdin-readiness heuristic treats a real file
handle differently from a pipe on Windows specifically. `_hint()` has no entry
for this reason string, so the reader saw the raw exception with no next step.
Needs reproduction on Windows (this session had no `powershell.exe`/shell access
to the reader's machine to test `claude.cmd` invocation directly) before a fix —
guessing at subprocess plumbing without seeing it fail is how B92 shipped broken
the first time.

**Checked 2026-09-11, still needs a real repro**: this session's WSL2 host
exposes a real Windows filesystem at `/mnt/c`, so it was checked for a shim to
test against — no `claude`/`claude.cmd` anywhere on that machine (no
`@anthropic-ai/claude-code` under its npm global `node_modules`, nothing named
`claude.cmd` on the whole drive) and no `powershell.exe`/`cmd.exe` interop
available from this shell either, so there is still no way to run the real CLI
through Python's `subprocess` on Windows from here. Deliberately not
guess-patching `_run`'s subprocess call over unverified theories about `.cmd`
shims — the next thing this needs is the reader's own repro (does `claude -p`
with a piped/redirected stdin, run by hand in their own terminal, show the same
warning outside of Kriko entirely?), not another blind fix attempt.

**Correction and real repro, 2026-09-11 (same day)**: the paragraph above was
wrong on both counts. `cmd.exe`/`powershell.exe` interop from this WSL2 shell
does work by full path (`/mnt/c/Windows/System32/cmd.exe /c ...`) — the
earlier `which`/`where` checks failed only because Windows System32 isn't on
the WSL PATH, which says nothing about whether the binaries are reachable.
And a real, native `claude.exe` (not an npm `.cmd` shim) exists at
`C:\Users\beraat\.local\bin\claude.exe`, found via `where claude` run
through `cmd.exe`. Real Windows Python is also present
(`C:\Users\beraat\AppData\Local\Programs\Python\Python314\python.exe`).

With all three confirmed, `harness.py`'s exact `_run()` subprocess pattern
(prompt written to a temp file, opened and passed as `stdin=`, same
`subprocess.run(..., capture_output=True, text=True, timeout=..., env=os.environ.copy(), cwd=home)`
call) was reproduced directly against the real `claude.exe`, run through real
Windows Python, invoked through real `cmd.exe` — the same process family the
packaged sidecar itself would use. Result: **no stdin race, no "no stdin data
received" warning, at all.** The subprocess ran cleanly to completion and
returned `RETURNCODE 1` with a full valid JSON stream ending in
`{"type": "result", "is_error": true, "result": "Failed to authenticate: OAuth
session expired and could not be refreshed"}` — an expired CLI login, not a
stdin-plumbing bug, and a case `_hint()`/`HINTS` in `harness.py` already
handles correctly (the reader's second live traceback the same day showed
exactly this error text and hint).

This does not prove B108 is closed — an expired login was never ruled out as
the actual cause of the *original* report, and this repro used a directly
invoked `python.exe`, not a frozen PyInstaller sidecar, so a
packaging-specific stdin difference is still conceivable. But it is now the
leading explanation over a stdin race: no evidence of the race has been
produced on the real CLI, on the real OS, using the real subprocess pattern,
in two independent attempts. Next step if it recurs: get a repro where the
reader is confirmed logged in (`claude` runs with no auth error by hand) and
still sees the stdin warning through Kriko specifically — that isolates
packaging/frozen-binary stdin handling as the one remaining suspect.

### B16 — Catalog swap: serve the ledger export instead of legacy part YAMLs `[G1][G2]`
The ledger export (knowledge/ledger_export/, 568 claims) is acceptance-ready per the
parity report; the serving-gate schema gap is closed. Remaining:
- [x] Export rewritten to the part-dict schema with serving-gate fields grounded at
      export. **Done 2026-08-02.** Regenerated 2026-08-03 from the ledger (19 parts,
      536 claims — the checked-in copy had gone stale; the fresh export covers
      dq200/dq250/dq381/ea211/ea888/k9k) and each file now carries
      `legacy_part_ids` (which legacy power-split files it supersedes —
      pipeline-derived, no hand list).
- [x] **Swap mechanism landed 2026-08-03** (`ops/swap.py`):
      `plan` derives the legacy→merged fitment remap mechanically
      (power-collapse rule via the export's `legacy_part_ids`), classifies every
      legacy file (superseded/retained), counts fitment edits; `apply` writes the
      export into `parts/<type>/`, deletes superseded power-split files,
      overwrites non-split ids in place, rewrites fitment axes (revertible, and
      default off the real catalog — runs on a copy unless `--in-place`);
      `check` is the **automated acceptance gate** (no human sign-off):
      (a) parity: every legacy claim absent from the export must be attributable
      to a named gate — "never extracted/ingested/no matching evidence" are
      LOST and fail; (b) serving: the 43-listing baseline replayed against the
      current catalog AND the post-swap catalog on fresh DBs — the swap's own
      delta, with a monotonicity rule (a listing that matches today must still
      match after the swap); (c) coverage: post-swap must not add findings.
      Tests: `knowledge/tests/test_ledger_swap.py`.
- [x] **Swap LANDED 2026-08-03** — `apply --in-place` replaced
      `backend/data/parts/` with the export (25 legacy files superseded,
      dw5/dw6 retained-then-covered, fitment remapped k9k_110→k9k etc.).
      Acceptance gate **PASS** under the $0 gate policy: 0 lost claims
      (URL-less legacy claims = unverifiable provenance; pending/mixed
      clusters = adjudicated-or-in-the-ledger; YouTube URLs = retry-owned by
      the remediate loop), 0 match-loss serving regressions (43 listings
      replayed, current-vs-post-swap), coverage 18→9. Serving DB re-syncs on
      next deploy. Two swap-caught data bugs fixed: `code_family_extra`
      (sibling aliases, r9m/M9R) now preserved by `apply` from superseded
      legacy files, and `component_part_meta` copies it on power-merge; the
      resolver's `_best_in_cluster` no longer mutates persisted ORM claims
      (replay-determinism bug). Legacy judge.py/promote.py/purge_*/translate
      + their tests retired (14 files, 75 tests) — `ops.process`'s
      promote steps now raise with a pointer to the ledger path.
- [ ] **Post-swap maintenance**: re-run `swap check` after any re-export;
      `python -m ops.ledger_run remediate` keeps coverage + parity
      gaps closed (default $0/import-only mode).

### B11 — Emissions/SCR values: derive or fail open — no sign-off `[G3][G5]`
The mechanism landed 2026-08-02 (`Variant.emissions`/`aftertreatment` +
`_scr_compatible`/`_default_aftertreatment` in `backend/sync.py`, `write_variants.py`
support, `test_scr_gate.py`). The old HUMAN DECISION #7 sign-off is cancelled under G5:
- [x] Hand-typed Megane 4 values removed (2026-08-03) — all variants fail open
      again (no SCR grounding), which is strictly safer than the unverified
      `scr` value on `megane4_k9k_110_edc` for 2016–18 cars.
- [x] Year-split row support landed in `write_variants.py` (2026-08-03) —
      `emissions` may be a list of year-bounded segments; each segment emits its
      own variant row (`{id}__{emissions}` suffix), aftertreatment derived per
      segment, windows validated against the trim. Tests:
      `knowledge/tests/test_write_variants_emissions.py`.
- [x] Coverage report lists diesel variants with no emissions value
      (2026-08-03) — new `variant_no_emissions` finding kind
      (`ops/reports/coverage.py`); the gap is visible, never a quiet wrong
      value.
- [ ] Derive emissions values from sources via the ledger for Clio 5 + Golf 7 +
      Megane 4 (evidence path, then `write_variants.py` regen). Until then,
      fail-open stands and the coverage report shows exactly which variants
      lack data.

### B19 — Auto-remediation loop: coverage gaps fix themselves `[G3][G5]` *(absorbs B2/B3)*
The detection mechanisms exist: B7's coverage report (`zero_claim_part`,
`auto_variant_no_tx_part`, `ops/reports/coverage.py`) and B6's ad-vs-catalog
contradiction surfacing. The former B2/B3 manual steps are cancelled; this loop
replaces them:
- [x] **Driver landed 2026-08-03** — `python -m ops.ledger_run remediate`
      (`ops/remediate.py`): turns every part-level finding
      (zero_claim/missing part, auto-variant-without-tx-part) into an unattended
      acquire → extract → resolve → cluster → verdict → export pass. Budget-capped
      (`--max-usd`), resumable (existing stage guarantees), `--dry-run` prints the
      plan, empty plan = no spend. Every run appends `logs/remediation.jsonl`
      (findings, parts, rows gained, spend). Findings carry `part_id`/`axis`
      metadata for the loop (`coverage.Finding`); `orphan_part` and
      `variant_no_emissions` are deliberately not part-driven research.
      Tests: `knowledge/tests/test_ledger_remediate.py`, coverage metadata tests.
- [ ] First live instances the loop must fix: `dw5`/`dw6` (empty EDC
      transmission parts) + the other 7 empty Megane 4 parts — a scheduled
      remediate run with EXA/DeepSeek credentials resolves them; the B16 swap
      then makes the export the serving catalog and completes the loop.
- [ ] "Manual only in TR" notes in `volkswagen_golf_7.yaml` (esp. 1.6 TDI DSG) and
      Clio 5 diesel rows: no manual audit; contradiction + coverage signals drive any
      regen. (Transmission coverage is already enforced by B6/B7 checks.)

### B17 — Official recall feeds: DROPPED `[G3]` *(HUMAN DECISION #6 resolved 2026-08-03)*
All official sources are dropped — TR SGM, EU Safety Gate, and NHTSA. TR SGM was
already blocked by an anti-bot challenge; the decision now removes the whole class.
The 50 ingested EU Safety Gate rows stay in `ledger.db` as history, but:
- [ ] Retire `knowledge/ledger/feeds/` ingesters and their `run.py feeds` wiring
      (remove, or leave dormant — they must not run).
- [ ] Recall coverage ends here unless a non-official automated source is later
      onboarded (B18-adjacent); no human recall checking exists.

---

## P1

### B34 — Re-wire or drop the two orphaned gate capabilities from the deleted `gates.py` `[G2]`
This pass (`2a88372`) removed `packs/cars/pipeline/agent/gates.py` after re-wiring it —
`check_evidence`'s vocabulary became `packs/cars/vocabulary/gates.yaml` rows, its
thresholds became `limits` rows, and its rule shapes became
`kriko.gates.structural_reasons`. Two of the old module's three public functions,
plus one supporting mechanism, were **not** ported and now have no caller anywhere
(so nothing running today changed — this is a capability gap, not a live bug):
- `check_document(url, raw_text, target_hint, existing_for_target)` — rejected
  blocked/forum domains, rejected snippets-instead-of-article-text, and enforced a
  server-side per-part research budget.
- `duplicate_of(title, known_titles)` plus `DUPLICATE_THRESHOLD` — title-level dedupe
  against claims already on file for the same target.
- The advisory-warning mechanism (`WEAK_TIERS` + `resolve_tier` integration) that
  warned on weak source tiers and on a missing `inspection_advice`. `resolve_tier`
  itself still exists in `packs/cars/pipeline/sources/tiers.py` but now has no caller
  outside its own module.
- `title_has_dtc_code` (a raw diagnostic-trouble-code shape check on the title) —
  a fourth lost rule, omitted from this inventory until the final review of this
  pass caught it. It still lives in `packs/cars/pipeline/stoplists.py` with no
  caller in the current write path (see `docs/USAGE.md`'s "Removed, not currently
  enforced").

All three are fully recoverable — the deleted file existed at commit `367e62f`.
Decide: re-wire document-level gating and title dedupe into the current agent research
path (`app/mcp_server.py`'s `submit_findings`), or delete `resolve_tier` too if the
project decides document-level gating isn't worth the research path's complexity.

### B35 — Gate calibration: false-rejection rate when a claim carries no `component` anchor `[G2]`
`packs/cars/tests/test_gate_calibration.py` (not `packs/cars/pipeline/tests/...` — that
path was a mislabel) measures the write-path gate's false-rejection rate across every
claim in `packs/cars/data/parts/**/*.yaml`. Two numbers, remeasured 2026-08-30 after the
`noise`-scoping fix and the `has_anchor` threading through `gate_reason` (final review
of this pass, finding 1/2):
- **Anchored** (claim has a `component` field): **1.29%** (9/699) — asserted in the
  test, ceiling 5% in aggregate, plus a per-kind bound per rule (added by the same fix).
  Was 3.29% (23/699) before the fix — the drop is `noise` losing its false rejections of
  rationale text mentioning a warning light while describing a real chronic.
- **Unanchored** (no `component`): **21.46%** (150/699) — measured and reported by the
  test, deliberately *not* asserted (would make the suite depend on catalog content
  that is expected to keep changing). Was 23.03% (161/699) before the fix.

`app/mcp_server.py`'s `submit_findings` docstring was updated this pass to tell agents
to always send `component`, which is why the anchored number is the one that should
apply in practice going forward. The unanchored number is still worth tracking: it
says roughly a fifth of catalog-shaped claims carry no configuration anchor in their
own text, which reads as a statement about **catalog quality** as much as about the
gate. Revisit if the unanchored rate moves a lot, or if agents keep omitting
`component` despite the docstring. Not filed as a bug — no fix is proposed here.

### B36 — Product-principle question: does a bare mileage figure earn the specificity escape? `[G3]` **(HUMAN DECISION #9 — open)**
Under both the original write-path gate and the one restored by this pass (`2a88372`),
a bare mileage figure in a claim's title satisfies the "config-specific" escape that
waives the ekspertiz-routine (`covered`) rejection — so *"Brake pad wear at 60,000 km"*
surfaces while a bare *"Brake pad wear"* is dropped. `CLAUDE.md`'s product principle
explicitly names brake-pad wear as routine pre-purchase-inspection ground that Kriko
should not surface ("Anything the standard pre-purchase mechanic inspection already
catches as routine — fluid levels/leaks, **brake-pad wear**, injector bench tests,
compression"). Read literally, that principle says neither phrasing should surface —
a mileage figure alone doesn't make routine wear config-specific in the sense the
principle means (engine/gearbox/fuel/market variant), it just adds a number.

This is **pre-existing behaviour**, not introduced by the current pass — both the
original gate (before this pass) and the restored one preserve it identically. It is a
**taste decision for the project owner**, not a refactoring decision: does "mileage
present in the title" count as the kind of specificity the product principle asks for,
or does it need to be tightened so routine-wear items still get dropped even with a
mileage figure attached? Whichever way this is decided, the fix is a one-line change
to `kriko/gates.py`'s specificity check (or to `packs/cars/vocabulary/gates.yaml`'s
`covered` rows) plus a calibration-test update (B35) to confirm the rejection rate
doesn't regress.

### B26 — Settle the 696 `status: review` claims deterministically `[G1][G5]` **(CLOSED 2026-08-26 by B32 — status became rank, not a gate)**
The claim inspector (done.md B25) made the size of this visible: **696 of ~699
catalog claims sit at `status: review`**, i.e. the pipeline never settles a
claim and the serving tier is doing that judgement implicitly. The mechanism
now exists — `knowledge/agent/gates.py` gives a deterministic keep/drop verdict
with reasons, and the hub records where a human disagrees with it
(`ops/hub/claim_signals.jsonl`). Remaining:
- [ ] Run the gate over the catalog as a pipeline step that writes a settled
      status/`value_tier`, not a hub button (no human in the data path).
- [ ] Feed `claim_signals.jsonl` disagreements into the gate's calibration test
      (the 10/699 rejection rate is pinned; a signal that contradicts it is a
      failing case to add).
- [ ] Fold into B5's ranking: settle first, then budget the survivors.

### B27 — Golf 8's gearbox code is unresearched `[G3]` *(new 2026-08-19; test case, not a fix target)*
`golf8_ea211evo2_150_auto` carries `transmission_code: 7_speed_dsg`, which
names three different gearboxes. The doctor fails it open (`draft: true`, kept
out of serving) and reports it as `invalid_code` needing research. Per the
generalization principle this is a **test case for the remediation loop**
(B19), not a car to hand-fix: the loop must be able to take an `invalid_code`
finding and drive a research pass that resolves it.
- [ ] Teach `ops/remediate.py` to consume doctor findings
      (`invalid_code`, `draft_variant`) alongside coverage findings.

### B5 — Per-part claim budget: keep the chronics, archive the tail `[G1]`
896 claims across part files for 3 models (~300/model) is the volume problem at its
source. Rank claims within each part by consequence × independent-source count ×
specificity; keep the top ~15 servable, move the tail to a non-synced archive section.
Corroboration count *is* the "general chronic" signal. Respect the product principle
test in `CLAUDE.md` ("would the standard inspection catch this anyway?"). Fully
automated — ranking is a deterministic pipeline step, no review.

### B9 — Year-window near-miss policy: ADOPTED `[G3][G5]`
A 2024 Megane 1.3 TCe listing no_matched ("No renault megane petrol for 2024" —
`year_to: 2023`). Policy (no further decision): a listing outside the known window
still matches the variant, carries a "year outside known window" note in the
response, and logs a demand signal for the catalog. Windows may later be extended
from TR-market data — also automatically, via the demand miner (B10).

### B20 — kriko-hub: clickable pipeline dashboard `[G2][G5]`
**Landed 2026-08-04** (`ops/hub/`, USAGE §4d). **Web edition is the
live one**: `ops/hub/web.py` (fastapi+uvicorn, 127.0.0.1:8787) — six
browser tabs (Overview/Parts/Sources/Run/Ledger/Coverage) over the
test-pinned `metrics.py`, run buttons spawning `ops.ledger_run`
(`--max-usd` caps, streamed output, stop), 1s polling. The DearPyGui app
(`app.py`) is deprecated — GL rendering on WSLg was unusable (GLX missing,
scaling breakage, per-second rebuild stalls swallowing clicks); the web
version renders in the host browser instead. `run.py` gained
`verdict --import-only` for the $0 button.

### B21 — MCP server + kriko_research agent: subscription-LLM engine, $0 research `[G2][G5]`
**Landed 2026-08-04** (`ops/mcp/server.py`, USAGE §4e, opencode.json →
`mcp.kriko`, `.opencode/agents/kriko_research.md`). 13 stdio tools; the full
agent loop tested end-to-end: `add_document` (hash-idempotent) →
`add_evidence` (extractor_version=1, deduped) → `run_pipeline_pass`
(resolve/cluster/import-verdicts/export, logged `model=agent, usd=0`).
Import-verdict predicate generalized `{0}` → `⊆ {0,1}`; LLM-eligible clusters
still queue paid verdicts only for extractor-version-2 evidence.
`pip install mcp>=1.0,<2.0` (2.0 dropped FastMCP). **Closed by B23** (harness
wiring + model entry point); see `done.md`.

### B23 — Agent-driven model onboarding: no hand-edited trim table `[G2][G3][G5]`
**Landed 2026-08-16.** B21's agent could only start from a coverage finding that
already named a `part_id`, so a car with **no scaffold** was unreachable, and
scaffolding one meant a human editing `TR_MARKET_TRIMS` in
`knowledge/catalog/write_variants.py` — the exact hand-enumerated per-model list
the scalability rule forbids. Now the researcher agent supplies the lineup:

- `write_variants.run(trims=...)` injection; `TR_MARKET_TRIMS` demoted to the CLI
  fallback (row content verified byte-identical for every onboarded car).
- `validate_trims()` — deterministic structural checks only. An unsourced figure
  is **not** an error: the row is written `draft: true`, sync skips it, coverage
  raises `draft_variant`. Fail open, never guess.
- MCP `onboard_model()` (work list: scaffold state, draft rows, part codes tagged
  missing/zero_claim/has_claims) and `submit_trims()` (validate → write variants +
  fitment → record lineup sources as `spec` documents). 15 tools total.
- `add_evidence()` verifies the quote is actually present in the submitted
  document (casefold + whitespace-normalized) and **rejects** fabricated
  citations. Previously `quote_grounded` was `bool(quote)` — any string passed.
- Harnesses wired: `.mcp.json` (Claude Code) + `.claude/agents/kriko_research.md`
  alongside opencode's; Codex/Cline snippets in USAGE §4e. The server owns
  validation, so hosts are interchangeable and none can bypass the gates.
- Agent loop is now **one model per pass** (was one part).

- **Top-down picker** (2026-08-16): make → model → generation → run, no typing.
  Makes/models come from the demand queue (`ops.reports.demand` over
  `logs/analyses.jsonl`), `not_onboarded` first — traffic-derived, never a
  maintained list. Generation is researched in a phase-1 agent pass
  (`submit_generations` / `list_generations`, lineups in
  `knowledge/catalog/generations/`), which also resolves scraped display names
  (`vw_cc_1_4_tsi` → `passat_cc`) via `canonical_model` + aliases.

- **Task/harness/model picker + command preview** (2026-08-16): both agent task
  forms as buttons, harness and LLM model as dropdowns, and the exact argv shown
  before it runs (`POST /api/agent-preview` shares the run endpoints' argv
  builder, so preview and execution cannot drift). Model lists come from
  `opencode models`, never shipped here.
  **Found doing this:** the hub passes `.env` to the harness, so opencode
  reported 406 models — 380 of them pay-per-token providers unlocked by
  `DEEPSEEK_API_KEY`/`MISTRAL_API_KEY`/`OPENROUTER_API_KEY`. One dropdown pick
  would have silently spent API credits and broken the $0 premise. Now split
  into flat-rate vs `⚠ pay-per-token` optgroups with a preview warning; the
  split derives from the `*_API_KEY` names in `.env`.

- Hub **Models tab** (2026-08-16): onboarding control room — catalog rollup,
  per-model work list, draft rows with their missing figures, `POST /api/onboard`
  spawning opencode/Claude Code, and a live activity feed read off the *ledger*
  (harness-independent, shows per-row quote grounding). Shared `model_state`
  module backs both the MCP tool and the UI so they cannot drift.

- [x] First live run happened (VW Golf 8) and **failed quality**: the lineup
      came back as marketing trims, with a description in place of a gearbox
      code. Fixed as a mechanism, not a patch — see done.md B24 (identity
      module, catalog doctor, server-side product-principle gates, derived
      research brief). Re-run it through the gated path to confirm
      `SUM(usd) WHERE model='agent'` stays 0.
- [ ] Re-onboard already-catalogued cars through the agent path, then delete their
      `TR_MARKET_TRIMS` entries (the fallback keeps them working until then).

### B22 — MCP-driven extraction: budget-capped paid tools on the MCP server `[G2][G5]` *(deprioritized 2026-08-16)*
**Deprioritized by B23:** the point of the agent path is the $0 plane — a
subscription harness doing the research is what makes onboarding cheap, so adding
paid tools to the MCP surface works against it. Revisit only if subscription
throughput (rate limits, session ceilings) proves insufficient in practice. The
analysis below stands if that happens.

`ops/mcp/server.py` (B21) is the **$0 plane by construction**: every write tool is
deterministic or import-only, `add_evidence` writes `extractor_version=1` rows that skip
the paid extractor, and `run_pipeline_pass` / `run_remediate_import_only` never spend
tokens. The paid engine (chunked DeepSeek extraction, batched verdicts) is reachable only
from the CLI (`python -m ops.ledger_run extract|verdict|remediate --max-usd`) and
the hub Run buttons. There is **no plan for an MCP path to the paid stages** — this item
is that decision + mechanism. Two options:

- **Option A — one wrapper tool (recommended first step).** `kriko_remediate(max_usd,
  dry_run=False)` calls the B19 loop unchanged (coverage findings → acquire → extract →
  resolve → cluster → verdict → export; budget-capped, resumable, appends
  `logs/remediation.jsonl`). Thin surface, reuses the tested driver; an agent closes
  coverage gaps end-to-end at a capped cost. Limitation: coverage-driven — the agent
  cannot say "extract *these* documents".
- **Option B — stage tools.** `kriko_extract(max_usd)` + paid `kriko_verdict(max_usd)`
  (verdicts only needed for the `extractor_version=2` evidence the extractor creates —
  `extractor_version=1` rows already flow through deterministic import verdicts). Makes
  extraction doc-driven: the agent commissions the real grounded extractor on documents
  it found, instead of hand-writing evidence rows. Literal "MCP-driven extraction"; more
  surface and per-stage budget bookkeeping. Natural follow-up on A — both stages already
  exist as `run.py` commands.

Mechanism constraints (G5 automation + generalization): budget is a **mandatory** tool
parameter enforced server-side by the same `costs` charging the CLI uses (no unbudgeted
spend, ever); paid agent runs log to `runs` (`model=agent`) so the hub cost panel stays
honest; MCP tools call the same `run.py` entrypoints as the CLI — one code path, no
second pipeline. Applies to all parts; no per-model logic.

- [ ] Decide A vs B (recommendation: A first; B only if doc-driven extraction proves valuable).
- [ ] Wire the tool(s) to the existing `run.py` entrypoints with `--max-usd` enforced server-side.
- [ ] `kriko_research.md` contract: "never invoke paid stages" → "never exceed the passed budget".
- [ ] Hub cost panel shows agent-paid spend (runs already carry `model=agent`; verify `usd > 0` renders).
- [ ] Tests in `test_mcp_server.py`: budget-capped paid tool with a mocked LLM stage — cap honored, spend logged, dry-run free.

---

## P2

### B37 — Long-function readability residue: eight (now more) functions over 90 lines `[G5]`
Tasks 10–11 of the 2026-08-29 simplification pass split the two functions the spec
scoped (457 → 65 lines, 300 → 28 lines). The plan named eight more, all outside that
scope, with line counts measured when the plan was written: `validate_part()` (194),
`process.run()` (153), `process.run_part()` (152), `ledger_run.main()` (144),
`export_all()` (142), `submit_findings()` (128), `lookup()` (119), `build_report()`
(114).

Re-measured 2026-08-30 with the same AST walk (`ast.FunctionDef`/`AsyncFunctionDef`,
excluding `/tests/`), those eight are all still present — `submit_findings()` grew to
**155 lines** (a later fix in this same pass lengthened its docstring to document the
`component` anchor requirement, B35) — and the same walk with the plan's >80-line
threshold now also catches nine more that were not named in the plan (`build_report()`
above is the one already named — these are new to this list):
`packs/cars/build.py:_conditions_from()` (91),
`packs/cars/pipeline/parts/search_templates.py:templates_for_part()` (98),
`packs/cars/pipeline/catalog/discover.py:_match_specs_to_variants()` (91) and
`discover()` (93), `packs/cars/pipeline/catalog/write_variants.py:run()` (92),
`packs/cars/pipeline/catalog/doctor.py:repair()` (93),
`packs/cars/pipeline/ledger/parity.py:explain_only_old()` (100),
`app/web/routers/analyze.py:analyze()` (90), `kriko/store/packstore.py:install()` (91).

None of this is a correctness bug — it's readability. Splitting seventeen unrelated
functions with no behaviour test behind most of them is a different, larger piece of
work than the simplification pass funded, and doing it without tests first would be
trading a readability problem for a regression risk. If this is picked up, write
characterization tests per function before splitting (test-driven-development skill),
and do not attempt all seventeen in one pass — group by module/owner instead.

### B38 — Measure how much the offline ledger's low-value gate widened `[G2]`
`packs/cars/pipeline/ledger/extraction.py:_low_value_reason` (`extract_document`'s
`gate_reason` callback) now routes through the full `kriko.gates.gate_reason`, which
means the offline ledger's chunk-extraction path flags evidence under `covered` and
`ambiguous` too — two rule kinds the old `_deterministic_low_value_reason` this
replaced never applied there (it only ever caught `noise`-shaped warning-light
language at extraction time; `covered`/`ambiguous` were write-path-only checks before
this pass). Flagged evidence is excluded from clustering
(`kriko/ledger/cluster.py:41`), so a false-positive `covered`/`ambiguous` flag here
can never reach export — this is a silent widening of what evidence gets dropped
before a human or agent ever sees it, not a live bug, and nothing currently measures
its rate.

Found during the final review of the 2026-08-29 simplification pass (finding 4);
filed rather than fixed per that review's own instruction not to fix findings 4/8 in
the same wave. Next step: instrument or backfill a measurement of how often
`covered`/`ambiguous` (as opposed to `noise`) fire on this path across a ledger run,
then decide whether the widening is wanted — it may well be (evidence that reads as
routine-and-unspecific is plausibly not worth clustering either), but that is a
decision to make with the number in hand, not by default.

### B39 — The research brief still tells agents to call tools that don't exist `[G2]`
`kriko/research/agent.py:53` (`research_brief`'s generated prompt) still tells
research agents to call `add_document` then `add_evidence` — neither tool exists;
the real (and only) write path is `submit_findings`. It also lists only
`quote`/`title`/`domain`/`severity` as the fields to send, omitting `document_text`
(without which `submit_findings` refuses every finding — see the grounding check at
`app/mcp_server.py`) and `component` (the anchor field that waives the specificity/
generic/ambiguous escapes, per B34/finding 2 of the 2026-08-29 pass's final review).

Two other surfaces carrying the same contract were already corrected in that pass —
`submit_findings`' own docstring and `.claude/agents/kriko_research.md` — this third
one (the brief the engine itself generates and hands to an agent at the start of a
research session) was missed. An agent following this brief literally would call
tools that raise `AttributeError`/tool-not-found, then likely improvise a shape that
`submit_findings` refuses for missing `document_text`. Fix: rewrite the brief's
tool-call example to name `submit_findings` with its real field list
(`title`, `rationale`, `quote`, `document_text`, `source_url`, `component`, plus
`domain`/`severity`).

### B40 — `packs/cars/pipeline/ledger/export.py`'s `errors`/`path` may be read unbound `[G5]`
Same bug family as the `component_part_meta` fix in the 2026-08-31 decontamination
pass (`2f0d061`, filed in `done.md`): `errors` and `path` inside the `for comp, claims
in sorted(by_component.items()):` loop of the export function around lines 438-455
are only assigned inside the `for _attempt in range(2):` sub-loop, then read after it
at `if errors or not kept:`. `range(2)` always runs at least once in the reachable
path today, so this has not fired — but that is exactly the shape that hid the
`component_part_meta` bug for however long it went unguarded (a branch that happens
to always run, verified by nothing). Deliberately left alone rather than
guessed-and-fixed in this pass: the fix belongs with a test that actually forces the
sub-loop to be skippable (or proves it can't be), the same way `2f0d061` rebuilt
`test_component_part_meta_power_collapsed` to force its branch by construction
rather than by accident of current data.

### B41 — Coverage loss: `test_adapters.py` no longer covers "two mutually plausible
values, identical digit format" `[G5]`
Pre-pivot, `test_range_bounds_disambiguate_identical_digit_patterns` fed
`"1.461 Nm"` and `"148.000"` — two independently plausible readings (a real torque, a
real mileage) sharing one dot-grouped digit pattern, disambiguated only by which
field's declared range believed which. The 2026-08-31 decontamination pass (Task 7)
moved this fixture to `packs/drill/`'s vocabulary; drill's magnitude profile (torque
~1-200, charge cycles ~0-2000) has no pair of dot-grouped integers that are each
independently plausible for a *different* field — any value plausible for one is
implausible for the other. Round 2 (`11c8b6f`) replaced it with a real but weaker
demonstration: `"1.200"` fed to both fields, believed for `charge_cycles`, correctly
absent from `max_torque_nm` (an accept/reject split on one shared value, not two
independently-valid readings). If the engine's adapter-parsing test suite ever needs
this exact case back, it needs either a fixture category whose two fields' plausible
ranges genuinely overlap in one digit-grouped format, or a synthetic (non-pack)
SPEC built for the purpose rather than borrowed from an installed pack's real
vocabulary.

### B42 — `pip install .` (non-editable) is unverified `[G5]`
`pyproject.toml`, added in the 2026-08-31 decontamination-and-packaging pass, has no
`package-data` or `MANIFEST.in` entry. `src/kriko/store/schema.sql` and
`src/app/web/static/*` are non-`.py` files the serving path needs at runtime; without
an explicit data-files declaration, a built wheel would plausibly ship without them
while `pip install -e .`'s editable `.pth` (which points straight at the source tree)
would still find them and hide the gap. Every command this pass verified went through
the editable install only. Needs: build a real wheel (`python -m build`), install it
into a clean venv with no source checkout on the path, and run the server/build
commands against that install.

### B43 — The prose gate is a worklist, not a proof `[G5]`
`src/kriko/tests/test_core_is_domain_free.py`'s `_prose_offences` check (added
2026-08-31) is real and load-bearing, but its guarantee is narrower than it sounds:
green means "no un-allowlisted `PROSE_BANNED` word appears in a `kriko/` docstring or
comment," not "no category leakage." It cannot catch a leak phrased without any
banned word (an explanation that names a mechanism by *behaviour* specific to one
category rather than by vocabulary), and every `ALLOWED_PROSE` entry is a judgment
call about whether an example "genuinely clarifies," not a mechanically checked
property. Worth restating for whoever runs the next pass: a green gate narrows the
search, it does not end it. No action item — this is a documentation gap in what the
gate proves, not a bug in the gate.

### B28 — Split `ops/hub/web.py` into routers `[G5]` **(SUPERSEDED 2026-08-26 by B33 — `apps/web/` ships the router split on the new core; the blocker was import-time path constants, now a Settings value passed through an app factory)**
`web.py` is 831 lines and ~28 endpoints after the 2026-08-22 helper extraction
(1151 originally; `textfmt.py`/`agents.py`/`claimview.py` took the pure helpers).
Splitting the endpoints themselves is blocked on a test-coupling problem, not a
code problem:

Endpoints read `DATA_DIR`, `RUNS_LOG`, `CLAIM_SIGNAL_LOG` and `AGENT_RUN_LOG`
from module scope, and `ops/tests/test_hub_web.py` patches them with
`monkeypatch.setattr(web, "DATA_DIR", tmp_path)`. A function resolves globals
from the module it was **defined** in, so moving `/api/models` to a
`routes_catalog.py` detaches it from the patch — it would read the real
`backend/data/` instead of the fixture and still return 200. A test that passes
while testing nothing is worse than a red one.

Doing this properly means moving the config globals to an `ops/hub/config.py`
and repointing ~8 `monkeypatch` targets from `web` to that module — mechanically
simple, arguably better tests (patch config, not the app module), but it is a
test change, so it was held back from the behaviour-preserving pass.

Acceptance: route table (path + methods) diffed identical before/after — the
2026-08-22 pass used exactly this check and it caught a real over-capture.

### B13 — Remaining design-flaw work (`docs/design_flaws.md`)
- Flaw 5: judge too weak → whack-a-mole patches. The ledger's verdict stage is now on
  `main` (B1, 2026-07-22) — closes for the pipeline; the *served* catalog inherits the
  fix at the B16 catalog swap.
- Flaw 6: pipeline keeps what sources mention, not what Kriko exists to show. The
  deterministic product-value gate is on `main`, dropping ~230 claims in the export;
  closes at B16 + B5.

### B14 — Documentation audit: docs must match the code
2026-07-16 pass fixed the worst drift. Remaining (all one-time doc work, allowed
under G5):
- [ ] Verify every INTERNALS.md mechanism section against current code — it predates
      the part-centric flow in places.
- [ ] USAGE.md §5/§7 still document the model-centric legacy mode prominently;
      restructure around the part-centric flow.
- [ ] Decide whether `docs/historical/handover.md` earns a rewrite or deletion (B12 landed).

### B18 — Source adapter ToS decisions: wire recalls/specialists/forums into the pipeline `[G2]`
Three source adapters exist (`knowledge/sources/recalls.py`, `specialists.py`,
`forums.py`) with working `fetch()` methods, blocked on **HUMAN DECISION #5** —
the only remaining human decision, and the only allowed kind under G5: a one-time
licensing/policy gate, not per-car review. Once confirmed, wiring into
`knowledge/ledger/acquire.py` (with a `--sources` flag) is fully automated. Note:
with B17, the official recalls adapter is retired — specialists/forums remain.

### B44 — No LICENSE file `[G5]` **(HUMAN DECISION #10 — open)**
There is no `LICENSE` file anywhere in the repo, and no licence is named in
`README.md`, `CLAUDE.md`, or `pyproject.toml`. `README.md` calls Kriko "open," but
with no licence granted, default copyright applies — all rights reserved — which is
the opposite of what "open" implies to a reader on GitHub. Per the 2026-08-31 branch
review that caught this: an earlier ruling had promised to file this decision and did
not — filing it here for real. One-time policy decision, same
category as B18's source-ToS call: which licence (if any) to publish under, and
whether `pyproject.toml`'s classifiers/`license` field should be updated to match.
Not a mechanism gap — nothing to automate here.

### B45 — `sources.published_at` is written by nobody
The ledger has no publication-date extractor, so the tree reports it always empty.
Derive it from page metadata during ingest, or drop the column.

### B46 — `evidence.independent` is `1` on all 719 rows; nothing ever computes independence
Until it does, "independent sources" means "distinct sources", and the health view
says so. Deriving it (same domain, same syndicated text, same author) is the real fix.

### B47 — no producer emits `stance = 'refutes'`, so the sharpest signal in the health view has zero live hits
The verdict step already sees contradicting evidence within a cluster; it should
record the rebuttal rather than discarding it.

### B48 — feed observed weakness back into `relevance()`
Deliberately out of scope for the knowledge-tree observability pass (spec
non-goal), but a claim with one forum source ranking beside one with three
bulletins is a ranking question, not only a reporting one.

### B49 — `rank.py`'s `score_sources` and `tree.py` disagree about what "independent" means
`src/kriko/lookup/rank.py:score_sources` increments its `independent` counter once
per *evidence row*, with no deduplication by source URL. Two quotes extracted from
one page therefore count as two independent sources and earn the claim a
corroboration step on the serving path buyers actually see. `kriko/lookup/tree.py`
does dedupe (`len({e.url for e in supporting if e.url and e.independent})`), so the
health view and the ranking now disagree on the same claim. Fix `rank.py` to
dedupe by URL, and add a test asserting the two agree.

### B50 — URL-less sources count as zero sources in the health view
`tree.py`'s `supporting_sources`/`independent_sources` dedupe on `e.url` and
filter `if e.url`, so a source with no URL contributes to neither count. The
schema does not require one: `source_type` includes `manual|structured|dataset`,
`ids.source_id` falls back to hashing the quote text when there is no URL, and
`packs/cars/build.py` happily accepts a quote-only source. Three scanned
service bulletins with no URLs would report `independent_sources=0` and rank
as maximally uncorroborated even though three genuinely independent sources
back the claim. Nothing has caught this yet because nothing has to: 0 of the
193 live sources have an empty `url`. Fix by deduping on a source identity
that falls back to the quote hash (`ids.source_id`'s own logic) instead of
`url` directly.

### B51 — `lang` is hardcoded `"en"` in `tree.py`, unlike `/api/query`
`_nodes()` takes a `lang` parameter but neither `GET /api/health/weakest` /
`GET /api/health/subject/{id}` nor the `subject_health`/`weakest_claims` MCP
tools expose it — every caller gets `lang="en"`. The store holds 699 `en` and
699 `tr` `claim_text` rows, so a pack shipping only `tr` claims yields
`title=''` on every health row: blank table cells, and an evidence `<details>`
with an empty, unclickable summary. Add a `lang` parameter to both surfaces,
matching `/api/query`'s existing precedent, with a fallback to any available
language rather than an empty title when the requested one is missing.

### B52 — The standalone app: signing, and a window nobody has opened `[G6]`
Phases 0–5 landed and **all four installers now build** — see `done.md`
(2026-09-01). **0.5.1 was built by hand on 2026-09-09** —
`Kriko_0.5.1_x64-setup.exe`, 22.6 MB, from `packaging/build_desktop.ps1` on the
Windows host with no CI at all (there are no credits), carrying everything
0.5.0's runner-less tag never shipped. The bundled shell was launched and
stayed up, and the run found two defects in the script's own reporting (a
success report naming last release's file, and mojibake on codepage 1254) —
both fixed and gated, see `done.md`. So the Windows leg of “there is an
installer” is answered; the rest is what CI could never answer anyway:

- **v0.2.4 on Windows did not open at all, and now the shell's own start is
  checked.** The app panicked in `build().expect(..)` before it drew anything:
  `PluginInitialization("updater", "invalid type: null, expected struct
  Config")`. `configure_updater.py` removes `plugins.updater` from a build with
  no signing key — which is every release so far — while `main.rs` registered
  the plugin unconditionally, so the two halves were each correct and together
  fatal. The updater is now registered from `setup` via `AppHandle::plugin`,
  where the failure is a `Result` the shell shrugs at. The *mechanism*, since
  "the installers built" was never evidence that the app opens:
  `packaging/smoke_app.py` launches the bundled shell on the Linux and Windows
  runners and fails on a panic or an early exit.
- **A reader has now run the installer, and it failed.** v0.2.1 on Windows 11
  stopped with "Error opening file for writing: ...\kriko-sidecar.exe", and after
  *Ignore* the app did not open at all. Two causes, both fixed in v0.2.2: a
  leaked sidecar kept its own onefile image mapped (now: `--exit-with-parent`,
  a Windows tree kill, and an NSIS pre-install hook), and `start_engine`
  returned its error into a window that is created hidden, so "no sidecar"
  rendered nowhere (now: every failure path goes through `emit_failure`, which
  shows the window). **Still unconfirmed by a human: the success path** —
  window appears with "Starting Kriko…", the shell reads `KRIKO_PORT`,
  `/api/health` answers, `location.replace` swaps in the dashboard.
- **Nothing is signed.** macOS shows an unidentified-developer warning and
  Windows SmartScreen flags the NSIS installer. Signing needs an Apple
  developer account and an EV certificate — a policy/spend decision, not an
  engineering one (see the human-decisions table).
- **Distribution is wired end to end.** A `v*` tag builds every pack, publishes
  `packs.json` beside the four installers, and the app updates its packs from
  it (*Packs → Check for updates*). The app updates itself the same way, from
  `latest.json` — but self-update is **off until someone generates the minisign
  keypair** and sets `TAURI_SIGNING_PRIVATE_KEY` (secret) and
  `TAURI_SIGNING_PUBLIC_KEY` (variable); see `tauri/README.md`. Until then
  releases ship installers only, which is a deliberate no-op rather than a
  failure.
- **First run offers the index.** ~~The installer carries no pack, so a fresh
  launch answers nothing until the reader presses *Check for updates*.~~ Fixed
  2026-09-03: `Welcome.svelte` is gated on `packs === 0` and offers the index
  by name, installs through the same job path *Packs* uses, and takes a
  `.kpack` file when the index is unreachable. Deliberately *not* bundling
  `cars.kpack`, which would pin knowledge to the binary's release cadence.
  Still unconfirmed by a human on Windows.
- **The extension could not reach the installed app, and now can.** It
  hardcodes `http://127.0.0.1:8787` because a page cannot be told a random
  port, while the sidecar only ever bound an OS-chosen one. The sidecar now
  serves both sockets and `EXTENSION_PORT` is one constant with a guard test.
  Untested against a real Chrome profile and a real Sahibinden page.
- **An agent can now reach the installed app; nobody has driven one yet.**
  *Coverage → Research* still produces a *brief* on the free plane, by design —
  the gathering is done by a coding agent you already pay for. What was missing
  was an address, and that is fixed: the sidecar binary takes `--mcp` and serves
  the MCP stdio server on the same `~/.kriko`, and *Coverage → Connect an agent*
  hands over a per-machine `.mcp.json` block naming the store this window reads.
  Untested with a real harness against a real installer, and there is still no
  in-app *view* of what an agent submitted beyond the ordinary claim screens.
  *(2026-09-07: the skill an agent is handed is now derived from the store —
  identity keys, domains, holdings, gaps, a runnable example, and every reason
  a finding can be refused — so a driven agent no longer has to guess the
  vocabulary. Still nobody has driven one.)*
- **What is already mechanical**: the handshake string must match on both
  sides, no engine vocabulary may appear in Rust, the boot screen must be able
  to render a failure, every data file under `src/` must be declared package
  data, and no tracked path may be unnameable on Windows. All in the ordinary
  pytest suite, no toolchain needed.

### B53 — The desktop shell has no `Cargo.lock` — **Done 2026-09-08**
Moved to `done.md`. `tauri/src-tauri/Cargo.lock` is committed (501 packages),
`cargo metadata --locked` gates the release workflow before it builds, and
`src/app/tests/test_shell_is_locked.py` holds the invariant with no Rust
toolchain installed.

Also open from the phase-2 work: the report screen makes weak claim selection
obvious, which is the product principle's open work (B36), not this item's.

---

## The 0.6.0 reader report *(2026-09-10)* — **all five closed, 0.7.0; delivery closed in 0.7.1**

The reader installed 0.6.0 and reported: *"run nothing again… did nothing
again, am i doing simething wrong, package bulding still expects user raw input
to create which i said many times, its gotta be automated with agents man…
this section is still car fixated. bro please fix this completely and make
agent usage very easy and fast I beg… queries are still fucked up."*

- **B99** — the harness never received the prompt (`--allowedTools` is
  variadic and ate the brief). Closed: stdin. → `done.md`
- **B100** — Research defaulted to the plane that fetches nothing. Closed:
  `default_backend()` resolves to `harness`, and the screen marks it. → `done.md`
- **B101** — queries were display labels, not searches. Closed: the
  `search_name` alias tier, narrowest-first, capped. → `done.md`
- **B102** — pack authoring still asked for raw input. Closed:
  `app/packauthor.py`, one category field. → `done.md`
- **B103** — the claim bar did not say whose bar it was. Closed: the brief's
  heading names the pack. → `done.md`

Verified against the reader's own `claude`: three documents, five
config-specific claims on a Golf VII EA211 DQ200.

- **B104** — *and none of B101 could reach them.* Closed as 0.7.1: the
  installer carried no pack at all, so the reader's store kept cars 0.1.1 with
  zero `search_name` rows and a fix living in pack rows was undeliverable by
  any release. `app/bundledpacks.py` seeds at startup,
  `packaging/build_packs.py` builds every pack directory that has a
  `pack.toml`, and `smoke_sidecar.py` fails a build whose frozen binary
  installs nothing into a fresh store. → `done.md`

---

## The 0.7.1 pack-authoring failure *(2026-09-11)* — **closed, 0.7.2**

The reader pressed **Author a pack** on 0.7.1, typed `Gaming Monitors`, and got

```
RuntimeError: Claude Code exited 1: [{"type":"system","subtype":"init",
"cwd":"C:\\Users\\beraat","session_id":"01275c13-...","tools":["Task","Bash",
...],"mcp_servers":[{"name":"kriko","status":"failed"}],...
```

- **B105** — the failure said everything except why. Closed as 0.7.2, in four
  parts:
  1. **The detail was the front of the output.** `_run` reported
     `(stderr or stdout)[:2000]`, and on a CLI that prints its whole message
     stream the first 2000 characters are the tool list and the session id.
     `_why()` reads the CLI's own `subtype` and `errors` out of the result
     message and falls back to the *tail*.
  2. **The output shape was one Kriko never saw here.** The reader's build
     prints a JSON *array* of stream messages under `--output-format json`;
     this machine's prints the result object alone. `_envelope()` reads one
     object, an array, or one object per line.
  3. **"No `--mcp-config`" was not "no MCP servers".** Their own failed
     `kriko` server is in that banner, loaded from their global config because
     the spawn's working directory is their home — and the same door hands over
     their `CLAUDE.md`, hooks, skills and output style. The vector now asks for
     `--strict-mcp-config` and `--safe-mode`, feature-detected from the
     installed CLI's own `--help` so an older build keeps the plane.
  4. **Authoring had the research ceiling.** `TIMEOUT_SECONDS` is sized for
     three searches; a real `packauthor.brief` run against the real CLI goes
     past ten minutes, so a healthy run was being killed and reported as a
     hang. `AUTHOR_TIMEOUT_SECONDS`. → `done.md`

  A recognised failure also names the next action now (`HINTS`): a usage
  limit, a login, a billing stop and a lost CLI each read as something to do
  rather than as a stack trace.

---

## The 0.5.3 reader audit *(2026-09-10)* — **all seven closed, 0.6.0**

The reader installed 0.5.3, pressed Research, and reported: *"research does
nothing unfortunately. it says done but logs return nothing. plus the
researches making turkish-english queries, agent should decide the queries,
it's fixated on the car still. plus the pack building must be guided with
agents. I see no token info, no usage info etc."*

The headline finding is worth keeping here because it outlived the rows:
**nothing on that machine could run an agent.** Kriko had two research planes
— `agent`, which gathered nothing by design, and `api`, which spends money —
and `app/agentconfig.py` wrote MCP config *into* harnesses so a harness could
call Kriko, while nothing anywhere called a harness. Pressing Research could
only ever render a brief and stop, and the job then reported `succeeded / 0
claim(s) kept` for a run that structurally could not do anything. One missing
direction caused the reader's first, second and fifth complaints at once.

B92–B98 closed it. See `done.md` for the row-by-row account:

| Row | | Commit |
|-----|---|--------|
| B92 | No plane drives a harness | `e9f6eb9` |
| B93 | A run that gathers nothing must say what to do next | `e9f6eb9` |
| B94 | Queries half Turkish, nothing declares a language | `e9f6eb9` |
| B95 | The agent has no authority over its queries | `e9f6eb9` |
| B96 | An agent cannot author or grow a pack | `7de3699` |
| B97 | The plane everyone uses reports no usage | `ff807c6` |
| B98 | Nothing runs unattended | `2b4ed8e` |


## P0 — the 1.0.0 release audit *(2026-09-08)*

The full assessment, with the finding-by-finding reasoning, the seven-phase
plan and the six open questions, is the published artifact
`https://claude.ai/code/artifact/b4a4aa7d-18cc-4c2e-b22c-14549587e4c8`
("Kriko 1.0.0 Readiness").

**The headline finding, kept here because it outlives the rows.** Every
automated gate was green — pytest, vitest, node, svelte-check — and *all four
reported defects passed all of them*. Four defects, four missing categories of
gate. So each row that fixed behaviour also named the gate that was absent,
and a row without one was not treated as finished. Apply that to anything new
in this file.

**B54–B62, B65–B80 are done** and moved to `done.md` — two sections dated
2026-09-08, the second covering [PR #12](https://github.com/Berbadov/kriko/pull/12).
`B57` is done including `Cargo.lock` (that was `B53`, closed 2026-09-08 — a
user-local rustup and `cargo generate-lockfile` turned out to be the whole
"needs a Rust toolchain" blocker). `B44` (LICENSE) is its own row under P2.


### B83 — Closing the window killed the extension's engine — **Done 2026-09-09**
Moved to `done.md` (`85c0ced`). The window hides, a tray icon owns the process,
and `installer.nsh` became the primary way a running engine is stopped before
an install. **Still unverified on hardware**: no Rust toolchain here and no CI
credits, so the tray has never been seen. Needs a 0.5.2 hand build.

### B84 — The rail marker drifted and the shell showed document scrollbars — **Done 2026-09-09**
Moved to `done.md` (`2f9a995`). The measured marker is now pure CSS; `html` and
`body` are pinned. Both defects were invisible to jsdom, which is the general
lesson: a layout bug needs a stylesheet assertion, not a DOM test.

### B90 — The research brief named MCP tools that do not exist — **Done 2026-09-10**
Moved to `done.md`. The $0 plane's only output is the brief, and it told agents
to call `add_document` and `add_evidence` — gone since the MCP surface
consolidated on `submit_findings`, and confirmed absent from the reader's own
installed binary. `app/agentskill.py` was correct throughout; nothing compared
the two, so `test_agent_instructions_name_real_tools.py` now checks every
agent-facing document against the tools the server registers, deriving the
legitimate non-tool vocabulary rather than listing it. `kriko pack scaffold`
also never wrote `research/templates.yaml`, so every new pack rendered zero
searches; it does now, and the brief states the absence when a pack ships none.

**Follow-up:** rowed and closed as B91 below.

### B91 — The docs where B90's phantom names came from — **Done 2026-09-10**
Moved to `done.md`. `docs/USAGE.md` Step 4e documented a nineteen-tool
pipeline MCP server that no longer exists, and `docs/INTERNALS.md` documented
four `normalize_*` functions deleted with the pivot. Both rewritten from what
the tree exports. The mechanism is `test_docs_name_real_symbols.py`: a
backticked call in a current doc must resolve to a registered MCP tool or a
`def`/`function` in the tree, with `docs/historical/`, dated design specs and
blockquoted passages out of scope. Resolution against ~2,970 scraped symbols,
not a whitelist — a maintained list is the failure this closes.

### B89 — The desktop shell had not compiled since B83 — **Done 2026-09-10**
Moved to `done.md`. Three adjacent string literals with no `concat!` in
`main.rs` — a parse error that shipped in `a062b86` and that all twelve tray
guards passed, because each only asserts a string is present.
`test_the_shell_is_valid_rust.py` parses every `.rs` with bare `rustc`, which
needs no dependencies and no `webkit2gtk`, and skips rather than passes where
there is no toolchain. `Kriko_0.5.2_x64-setup.exe` then built, 22.8 MB, both
smoke steps green.

**Follow-up, unrowed:** `581e76d` bumped both version files to 0.5.2 and never
tagged. `desktop.yml` builds on tags, so nothing ever compiled the tree. A
version bump with no tag needs a gate.

### B88 — The extension spoke the site's language — **Done 2026-09-10**
Moved to `done.md` (`ed3bb15`). The Turkish damage-state words, part-name
regexes and alert thresholds moved out of `extension/` and into the adapter's
`local_panel` block, which the client already fetches. Two gates: no non-ASCII
*word* anywhere in `extension/` (a lone character is a fold and stays legal),
and the shipped alert keys must equal the keys the interpreter reads, derived
from its own source. The rewrite passed the old suite 12/12 first try, because
the old test only asserted `damage_info` was truthy.

### B85 — The install prompt kept asking readers who already installed — **Done 2026-09-09**
Moved to `done.md` (`69a1789`). `ever_connected` instead of the liveness badge,
and dismissal persisted per step id in `app.sqlite`.

### B87 — The one click opened a second copy of the app — **Done 2026-09-09**
Moved to `done.md`. The launched browser lands on a listing site read off the
adapter rows, so the hover panel is what the reader sees; the app screen stays
the fallback for an installation with no packs.

### B86 — Building knowledge with an agent is not a system yet — **Done 2026-09-09**
Moved to `done.md` (`0ab613d`, `b945408`). Two research planes side by side, a
key store, an unattended agenda run under one shared ceiling, provenance that
makes every run reversible, and a per-pack product-identity skill. Spec:
`docs/superpowers/specs/2026-09-09-knowledge-building-design.md`.

### B82 — The data pipeline still needs a person to aim it — **Done 2026-09-09**
Moved to `done.md`. `app/agenda.py` ranks what to research next by what this
installation was actually asked about, through three doors (`research_agenda`,
`GET /api/agenda`, the generated skill). Spec:
`docs/superpowers/specs/2026-09-09-research-agenda-design.md`.

### B81 — Only CI could build an installer — **Done 2026-09-09**
Moved to `done.md`. The v0.5.0 tag produced nothing: no runner was ever
assigned, and `desktop.yml` was the sole path to a bundle.
`packaging/build_desktop.ps1` runs that job on a Windows box, and
`src/app/tests/test_the_installer_can_be_built_by_hand.py` reads the workflow
to fail the script when the two drift. Then it was actually run, on the Windows
host WSL2 exposes at `/mnt/c`, and it was wrong three times — a codepage parse
error, an elided empty argument, and a PyInstaller orphan holding its own
`.exe` — none of which any runner-based gate could have seen. All three shipped
with a gate; `done.md` has the detail. Does not remove the *OS* from the
critical path — PyInstaller cannot cross-compile — only the runner.

What stays open here is the two rows nobody can write code for:

### B63 — The updater and `packs.json` URLs 404 for a running app
**Blocked on Q1.** The repository is private, so both point at endpoints a
reader's app cannot reach. Recommendation in the artifact: a releases-only
public mirror.

### B64 — Nothing is signed, so nothing can self-update
**Blocked on Q2.** minisign now (free, and the key must never be lost);
the ~$200–400/yr Windows authenticode certificate can wait.

---

## Human decisions — status under G5

| # | Topic | Status |
|---|-------|--------|
| 5 | Source ToS (B18) | **Open** — one-time policy, the only allowed kind under G5 |
| 6 | TR SGM recall feed | **Resolved 2026-08-03** — dropped with all official recall sources (B17) |
| 7 | B11 emissions sign-off | **Resolved 2026-08-03** — cancelled; derive or fail open (G5) |
| 8 | Split point for `knowledge/`'s deletion (B33 Phase 6b) | **Resolved 2026-08-29** — generic ledger/extract to `kriko/`, cars-specific pipeline to `packs/cars/pipeline/` |
| 9 | Does a bare mileage figure earn the specificity escape for routine-wear claims? (B36) | **Open** — product-principle taste call, not a mechanism gap |
| 10 | No LICENSE file, despite README calling Kriko "open" (B44) | **Open** — which licence (if any) to publish under |
