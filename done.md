# Kriko — Done

Completed work, newest first. Entries move here from `backlog.md` with date + commit.
Seeded 2026-07-16 from git history; older history lives in `git log` and
`docs/historical/pipeline_postmortem.md`.

---

### 2026-09-11 — A real terminal, one keystroke away, as 0.7.4 (B107)

B106 fixed one CLI's stdin race; the class of problem underneath it is that a
harness sometimes needs a one-time *interactive* step — `claude login` after
an OAuth session expires, `opencode auth login`, an npm 2FA prompt — that no
API call can do on the app's behalf, and until now the only way to run one was
to leave the app for the OS's own terminal, find the right working directory,
and come back. That is exactly the friction Kriko exists to remove.

**The Console is gone.** It was a safe, API-only prompt that dispatched a
fixed command set through the same endpoints the UI already called — never a
real shell, on purpose, back when nothing the app did needed one. `login` is
the thing that needed one. `ui/src/routes/Console.svelte` and its command
table (`ui/src/lib/console/commands.ts`) are deleted; `Agents.svelte` (78
lines, two lenses) collapses to a 17-line delegate to `Connect.svelte` alone.

**A real, always-reachable terminal replaced it**, backed by an actual PTY —
`src/app/providers/termpty.py` spawns the reader's own shell
(`$SHELL`/`ComSpec`) and holds one session for the process's life, the same
"one shell per app session" choice `sidecar.py` already makes for the engine
itself. `POST /api/terminal/ws` (`src/app/web/routers/terminal.py`) is a
WebSocket, not a REST verb — a shell is a duplex byte stream, not a
request/response pair — framed as `{"type":"data"|"resize", ...}` JSON, and checked by a new
`origins.terminal_origin_is_allowed()` — the same loopback/shell-origin rule
`origins.py` already enforced elsewhere, minus the extension schemes that
rule allows: a shell is not something a browser extension gets to open. The
socket also rejects any connection whose server-side port is
`EXTENSION_PORT`, so the fixed port a browser extension is hardcoded to talk
to can never be the one serving a shell.

**The frontend is `@xterm/xterm` + `@xterm/addon-fit`**, mounted once by
`ui/src/lib/shell/TerminalPanel.svelte` on first open and never torn down —
closing the panel only sets `hidden`, the same lazy-mount-then-keep pattern
`Agents.svelte` used for the old Console, for the same reason: an unmounted
terminal is a cleared one. Open state lives in `lib/shell/terminal.ts`, a
plain `writable` shared between the rail's toggle button (`Sidebar.svelte`)
and the panel itself (`App.svelte`, mounted as a root-level sibling, not a
routed view) — closed by default, and reachable from anywhere with
`Ctrl+``/`Cmd+``` or the rail button, never by navigating.

**Mounted outside `.view` on purpose.** `App.svelte`'s `focusTheView()`
existed because a navigation `viewEl.focus()` once stole focus from the
Console's autofocused prompt (the bug `App.focus.test.ts` guards). The new
terminal cannot hit that bug structurally — it isn't a route the focus effect
ever runs against — which is why that test's Console-specific case is gone
and its fallback-focus case stays, still real infrastructure for the next
route that autofocuses something.

Gate: full `pytest -q` green (added `applies_here()` to `tools/relock.py` so
a platform-gated root like `pywinpty` reads as inapplicable rather than
unlocked, and documented `/api/terminal/ws` as the ninth door in
`docs/INTERNALS.md`); full `npm run test`/`npm run check` green, including a
new `TerminalPanel.test.ts` that polyfills the two things jsdom lacks for
`@xterm/xterm` to mount at all (`matchMedia`, `ResizeObserver`) and replaces
the network with a `FakeWebSocket`. The committed bundle grew past its
280 KB `.js` budget from `@xterm/xterm`'s DOM renderer; raised to 720 KB in
`test_bundle_budget.py` rather than silently widened.

---

### 2026-09-11 — The extension's own button, and a Windows stdin race, as 0.7.3 (B106)

The reader's report: pressing Research in the extension went straight to
"done" with nothing found, and their pasted job log showed the *real* harness
run failing underneath it — `Claude Code exited 1: Warning: no stdin data
received in 3s...`. Two independent bugs, both closed here.

**The extension asked the wrong question.** `tasks.default_backend()` already
preferred `harness` when a CLI was on PATH; `GET /api/extension/research-plane`
did not — it checked only the paid `api` plane's keys and otherwise always
answered `agent`, the plane that writes a brief and returns nothing by
design. `hover_lite.js` compounded it: even when the server did say
`harness`, `researchSubject()` hardcoded `"agent"` as the fallback for
anything that wasn't `"api"`. Both now pass the real answer through.

**Claude Code's own stdin, from a Windows spawn, lost the race.**
`HarnessResearcher._run()` wrote the prompt with `subprocess.run(...,
input=prompt)` — a pipe the child reads once it starts polling, and a
Windows named pipe's readiness timing is not POSIX's. The prompt now goes
into a temp file opened for read and handed to `subprocess.run(...,
stdin=stdin_read)`, which removes the race by removing the pipe.

**opencode is back as a harness, on a leash.** It was excluded from
`available()` because `opencode run` had no flag restricting which tools the
agent could use — the same allowlist requirement every other harness meets.
`opencode agent create --tools/--permissions` (present since 1.18) closes
that gap: `_ensure_opencode_agent()` now writes a restricted
`~/.opencode/agents/kriko-harness.md` profile (`bash: deny`, `edit: deny`,
`webfetch: allow`, `websearch: allow`) the first time opencode is chosen, and
`opencode run --agent kriko-harness` is bound to it. Codex stays out —
no tool-restriction mechanism found for it yet.

Gate: `pytest -q` full suite green; extension's `node --test` suite green.
The stdin fix is not yet confirmed against a real Windows failure — it
closes the only race the pasted log is consistent with, but the reader's own
machine is the actual gate.

---

### 2026-09-11 — A failure a reader can act on, and a spawn that is actually sandboxed (B105)

The reader pressed **Author a pack**, typed `Gaming Monitors`, and got two
thousand characters of the CLI's init banner: its tool list, its session id, its
model, and no reason. `RuntimeError: Claude Code exited 1: [{"type":"system",
"subtype":"init",...`. Four things were wrong and the first one is why the other
three took a release to find.

**The detail was the front of the output.** `_run` reported
`(done.stderr or done.stdout)[:2000]`, which is the right instinct for a CLI
that fails on stderr and exactly wrong for one that prints a message stream on
stdout: the reason a run stopped is always the *last* message. `_why()` now
reads the result message's own `subtype` and `errors` — `error_max_turns`,
`error_during_execution`, whatever the CLI called it — then its text, then
stderr, and only then falls back to the tail rather than the head.

**The shape was one this machine never prints.** Their build emits a JSON
*array* of stream messages under `--output-format json`; the one here emits the
result object alone. Both are that version's documented format, so `_envelope()`
reads either, plus the line-delimited form — and it is shared with the failure
path, so the two can no longer disagree about what the CLI said.

**"The spawned agent gets no MCP config" turned out not to mean "no MCP
servers".** Their banner says `"mcp_servers":[{"name":"kriko","status":
"failed"}]` — their own global configuration, loaded because B92 deliberately
put the working directory in their home. The same door hands over their
`CLAUDE.md`, their hooks, their skills and their output style, none of which
were written for a prompt whose entire contract is "print one JSON object and
nothing after it". The vector now asks for `--strict-mcp-config` (with no
`--mcp-config`, that is zero servers) and `--safe-mode`. Both are
**feature-detected** from the installed CLI's own `--help` and cached per
executable: the report came from `claude_code_version 2.1.261`, versions are
not ordered the way flag support is, and a reader on an older build must not
lose the plane over a flag it never heard of. `command_for()` is a named
function so the free gate that runs the real CLI judges the vector that
actually runs — the shape-only assertions are what let B92 ship a plane that
could not start.

**And authoring had been given one subject's research ceiling.** 600s is sized
for three searches and four pages. Authoring a pack is a category read from
scratch, four decisions made from what was read, and two or three subjects
researched before a single character is printed; measured against the real CLI
it runs past ten minutes. So `TIMEOUT_SECONDS` was killing healthy runs and
calling them hangs — the least debuggable failure this feature could have.
`AUTHOR_TIMEOUT_SECONDS`.

Last, a reason with no action attached is half an answer. `HINTS` is a closed
vocabulary of CLI failure classes — usage limit, not logged in, billing, out of
turns, cannot start — and a recognised one appends what to do: wait, log in,
switch plane, send the log. A class we do not recognise is reported in the
CLI's own words with no guess bolted on.

Nine tests in `test_the_harness_research_plane.py` and one in
`test_an_agent_authors_a_whole_pack.py`, including the reader's exact banner as
a fixture with an assertion that its session id never reaches an error message
again.

Verified against the real CLI with the reader's own input: `Gaming Monitors` ->
`display.gaming.monitors`, 280s, five subjects and seven claims, and a 266 KB
`.kpack` from `app.cli build`. Shipped as `Kriko_0.7.2_x64-setup.exe`, built on
the Windows host and copied to the Desktop.

**A note on how that installer was built**, because the build script itself
would not run to completion twice over: npm printed one deprecation warning
about a transitive package, and PowerShell -- capturing the native stderr into
its own pipeline because the invocation piped it to `Out-File` -- raised it as a
terminating `NativeCommandError` three lines into `=== Build the UI`.
`$ErrorActionPreference = 'Continue'` does not touch it; the error comes from
the pipeline, not the preference. Redirecting in `cmd` instead hands the child
an OS file handle and a warning stays a warning. The working invocation is now
an `.EXAMPLE` in `build_desktop.ps1` with the reason attached, since the failing
one looks more idiomatic and produces a log that silently omits every
`Write-Host` step marker as well.

---

### 2026-09-10 — The installer carries its own knowledge, as 0.7.1 (B104)

Found while checking that B101's queries fix had actually reached the reader.
It had not, and could not: their `~/.kriko/knowledge.sqlite` held
`org.kriko.cars 0.1.1` with 68 `attribution_safe` aliases and **zero**
`search_name` rows, because `packaging/kriko-sidecar.spec` carried the frontend,
the store's DDL and the browser extension — and no pack at all. The only two
ways a pack had ever reached a store were a file the reader found themselves and
an update index that answers 404 while this repository is private (B63). So a
defect whose fix lives in a pack's *rows* could not be delivered by any release,
and a fresh install opened onto an empty engine.

`src/app/bundledpacks.py`, three rules and nothing else: missing gets installed;
newer gets installed and older never does; a failure here is never why the app
will not start. A `.kpack` is a SQLite database, so each carried artifact's
identity is read out of its own `packs` row rather than from its file name —
trusting the name is how a renamed file installs as something it is not. Version
ordering is borrowed from `kriko/pack/updates.py` rather than written a second
time, and a store holding something *newer* is left alone: an app upgrade that
walked a hand-installed 0.9.0 back to the 0.2.0 it happened to carry would be
destroying the reader's own work to deliver ours.

`source_dir()` is deliberately narrower than `extension.source_dir()`, which
falls back to the checkout. This one writes into a store, and both reasons not
to do that from a checkout are real: a developer's `dist/` holds whatever they
last built — the first run of this module found a `drill.kpack` frozen before
`gate_terms` existed in the schema, which rule 3 logged and skipped — and the 28
tests that start a lifespan would each have a 2 MB cars pack installed into their
temp store by the act of starting the app. So it reads what the installer
unpacked, or what `KRIKO_BUNDLED_PACKS` names.

`packaging/build_packs.py` builds every pack directory that has a `pack.toml`,
*discovered* rather than listed, so a third first-party pack ships by existing —
the scalability principle applied to the build. Both build paths call it before
freezing (`build_desktop.ps1`, `desktop.yml`), the spec refuses to freeze with
no artifacts the way it already refuses with no frontend, and
`smoke_sidecar.py` now fails a build whose frozen binary installs no pack into
a store two seconds old. That check catches all three ways this can silently
regress: the datas entry, the build step, and the seeder itself.

Tests: `src/app/tests/test_the_installer_carries_knowledge.py`, 11 of them,
including that a hand-installed newer pack survives, that an uncomparable
version (`nightly`) is left alone, that a truncated artifact is skipped while
its neighbour installs, that a renamed file installs as what it says it is, and
that the store is not left holding a WAL lock — the lock that turns into
"Error opening file for writing: kriko-sidecar.exe" on the next Windows install.

### 2026-09-10 — The 0.6.0 reader report: five defects, shipped as 0.7.0 (B99–B103)

The reader installed 0.6.0, pressed Research on a Golf, and got seven queries
that found nothing, then a crash. Their words: *"run nothing again… did nothing
again, am i doing simething wrong, package bulding still expects user raw input
to create which i said many times, its gotta be automated with agents man…
this section is still car fixated. bro please fix this completely and make
agent usage very easy and fast I beg… queries are still fucked up."*

Five defects. Three were why nothing ran; two were the reader asking for the
feature to exist at all.

**B99 — the harness never received the prompt.** `claude --help` declares
`--allowedTools, --allowed-tools <tools...>`, *variadic*. A vector ending
`--allowedTools WebSearch,WebFetch <prompt>` handed the brief to the allowlist,
and the CLI's complaint was the reader's traceback: `Input must be provided
either through stdin or as a prompt argument when using --print`. The prompt
now goes over stdin, which removes the class rather than the instance. The gate
is free and deterministic: with an *empty* prompt, `claude -p` refuses before
any API call and its only complaint is that one — so "the only complaint was
the empty prompt" proves everything else in the vector is accepted, at zero
cost.

**B100 — Research defaulted to the plane that fetches nothing.** `backend` was
`agent` by omission, and `agent.gather()` returns `[]` by design: it writes a
brief for somebody else to run. On a machine with a coding-agent CLI installed
this rendered a brief and reported success. `tasks.default_backend()` now
resolves an unnamed plane to `harness` when a CLI is on PATH, and
`/api/research-planes` returns which plane that is so a screen can mark it.
`api` is still never chosen by omission — a button that quietly starts spending
is a button people stop pressing.

**B101 — queries were catalog spellings, not searches.** The queries the reader
watched find nothing were `Volkswagen Golf 1.5_TSI 150 hp common problems` — a
phrase nobody has typed. One string was doing two jobs: a *display label*
carries whatever tells two rows apart in a list, and that is not what a person
types into a search box. So `subject_aliases` gained a third tier,
`search_name`: a complete phrase somebody would type for exactly this subject.
It attributes nothing (that is `attribution_safe`) and it is a whole name rather
than a widening fragment (that is `search_only` — `LXT common problems` is a
worse search than the label it would replace). Collapsing those tiers was
design-flaw 3, and a first attempt at this fix collapsed two of them again;
`packs/drill`'s test caught it.

The taste ships as pack data (`packs/cars/build.py` decides what people type);
the mechanism is the engine's (prefer `search_name`, fall back to the label,
narrowest first, cap at `MAX_QUERY_NAMES`). Verified against the reader's own
`claude`: `Volkswagen Golf EA211 common problems` → three real documents → five
config-specific claims, including the DQ200 mechatronic pressure loss and the
EA211 water-pump housing. `packs/cars` is 0.1.2 because the tier is in the
artifact, not only in the code.

**B102 — a pack an agent writes, from a category in plain words.** The reader
said "its gotta be automated with agents man" more than once, and the screen
still asked for a directory, a pack id, a name and an identity table before it
would write anything. Three of those four are decisions somebody who has read
the category takes well and somebody who has not cannot take at all — and the
identity table is the sharp one: too few keys and unrelated rows collide into
one subject, too many and one thing splits across subjects that never see each
other's claims, and *neither failure raises*. `app/packauthor.py` is one field
and one press: the agent decides taste, Kriko decides shape, the reader decides
installation. Nothing about the agent's reach widened — it prints one JSON
object, gets no `--mcp-config`, and `app/packdraft.py` writes the files, so a
draft is data only and installs nothing until the reader presses Install.

**B103 — the claim bar now says whose bar it is.** The four bullets the reader
called "still car fixated" are `packs/cars/research/principle.md`, quoted
verbatim, and that is the design: what counts as worth surfacing is a property
of the category, so it ships as pack data (`packs/drill/` states a different
bar, and `pack/scaffold.py`'s placeholder is generic — a new pack inherits
nothing car-shaped). Nothing was wrong with the layering. What was wrong was a
heading that named no owner, leaving the engine as the only candidate to blame.
The brief now says `## What makes a claim worth keeping — the
\`org.kriko.cars\` pack's bar`, and says in a sentence that it is the pack's
and the pack's to change.

**And a guard, because a test billed the developer.**
`test_a_real_agenda_run_ends_up_in_the_run_list` resolved to `harness` by
omission and spent fifteen seconds driving the reader's real `claude` against
their subscription — and passed on CI, where no CLI is installed. That
asymmetry needed a mechanism: `no_test_starts_a_real_coding_agent` in
`src/app/tests/conftest.py` refuses any spawn whose executable is one of
`harness.KNOWN`, and shuts the door on *which* process rather than on the call,
because a harness test should still exercise the spawn against a fake CLI.

---

### 2026-09-10 — The 0.5.3 reader audit, closed end to end (B92–B98)

Seven rows, four commits, shipped as 0.6.0. The reader had installed 0.5.3,
pressed Research and got *"research does nothing… it says done but logs return
nothing. plus the researches making turkish-english queries, agent should
decide the queries… plus the pack building must be guided with agents. I see no
token info, no usage info etc."* Every complaint was accurate and four of the
five had the same cause.

**B92 — no plane drove a harness** (`e9f6eb9`). The headline finding. Kriko had
two research planes: `agent`, whose `gather()` and `extract()` returned `[]` by
design, and `api`, which spends money. `app/agentconfig.py` wrote MCP config
*into* coding-agent harnesses so a harness could call Kriko — and nothing
anywhere called a harness. So Research could only render a brief and stop,
while the job reported `succeeded / 0 claim(s) kept` for a run that
structurally could not do anything. `app/providers/harness.py` is the missing
direction: it finds a coding-agent CLI on PATH and drives it. The security
constraint is that `--allowedTools` is an explicit allowlist — the research
harness never gets Bash, Edit or Write — and the spawned agent gets no
`--mcp-config` at all.

**B93 — a run that gathers nothing now says what to do next** (`e9f6eb9`). The
old sentence stopped at the diagnosis. It now has a second half: the reader can
have Kriko start the agent, or hand the brief over themselves.

**B94 — queries were half Turkish and nothing declared a language**
(`e9f6eb9`). The cars pack shipped seed queries in two languages with no
`languages` declaration anywhere, which is how a search returns nothing. A pack
that ships `research/templates.yaml` must now declare `languages`; a `lang` the
manifest does not name is a contract failure, and so is a non-ASCII *word* in a
single-language pack — the same rule the client is held to, one layer in.

**B95 — the agent had no authority over its queries** (`e9f6eb9`). The brief
handed down a script. It now groups rendered queries by language and says they
are seeds to adapt. What the agent actually ran is stored per run
(`queries_json`), so the record is what happened rather than what was
suggested.

**B96 — an agent could not author or grow a pack** (`7de3699`). "The pack
building must be guided with agents" was the reader's third complaint and the
answer is a set of tools that write a draft under `~/.kriko/drafts/<slug>/`.
Test-enforced: a pack an agent writes is **data only** — no Python, no path
escaping the draft directory, nothing installed without the reader's press, and
no agent tool that can delete a draft.

**B97 — the plane everyone uses reported no usage** (`ff807c6`). Tokens now
travel the whole way: provider socket → `complete.tokens_used` on the callable
→ `ApiResearcher`/`HarnessResearcher` → `_Provenance.tokens()` →
`research_runs.tokens_used` → `/api/usage` → `Usage.svelte`. And
`analyses.jsonl`, the record of every lookup this installation has ever
answered, finally has a reader (`observability.summarise`).

Two rules hold the panel up. **NULL is not zero** — a plane that cannot count
writes NULL and the screen says "not counted", because "$0.00" is the figure a
reader would quote back and it would be wrong in the direction that flatters
us. **Every total carries its denominator** — `metered_runs of runs` sits
beside the spend, so a small total over many runs cannot read as a cheap
installation. Two currencies, not one: the harness plane knows its tokens and
spends none of Kriko's money, the api plane knows its dollars and may never see
a token, so `close_research_run` COALESCEs each column separately and a caller
who knows one cannot erase the other.

**B98 — nothing ran unattended** (`2b4ed8e`). Sequenced last on purpose: "a
scheduler driving a no-op is worse than no scheduler, because it would fill the
runs table with successful nothing." `app/web/schedule.py` is a pure `decide()`
plus a thread that sleeps and calls it, so every rule is an assertion rather
than a wait. It is off until the reader turns it on; it refuses the `agent`
plane by name (unattended, its brief is never read), refuses `harness` with no
CLI and `api` with no keys *with the sentence saying what is missing*, skips
while work is in flight, and waives its startup grace only for a reader
pressing "check now". Next-due comes from the stored timestamp, so a machine
off for a week runs once rather than seven times. Every tick records what it
decided, refusals included — on a quiet day that sentence is the feature's only
output.

Two defects found on the way, both the class B96 hit: `Usage.svelte` threw on
`.research.planes.length` and `Schedule.svelte` on `.last.reason` when a field
was absent, which is exactly what an older engine's payload looks like. They
surfaced as unhandled rejections in *passing* route tests — worth reading
vitest's "Errors" line, not just its "Tests" line.

---

### 2026-09-10 — The docs the phantom names came from (B91)

Branch `docs-name-real-symbols`. B90 fixed the brief; this fixes where the
brief was written from. `docs/USAGE.md` Step 4e held a second written copy of
the MCP surface — nineteen tools, `ledger_status`, `submit_trims`,
`add_document`, `add_evidence`, `run_pipeline_pass` and the rest, none of them
defined anywhere in the tree. `AgentResearcher.brief` had been written against
that list, so the cost of the stale paragraph landed on a reader pressing
Research, not on whoever wrote the sentence.

Step 4e now names the single source for each thing it describes rather than
restating it: `render.MCP_TOOLS` for the granted tools,
`research_brief(subject_id, pack_id)` and `submit_findings(subject_id,
pack_id, findings)` with their real signatures, §2b for the wiring, and the
retired nineteen kept in a blockquote as history. `docs/INTERNALS.md`'s
"Variant matcher" section was the same defect one layer down — it documented
`normalize_fuel`, `normalize_make`, `normalize_model` and
`normalize_transmission`, four functions that could not come back, since
`kriko/` may not hold a car-shaped anything. Rewritten around what
`lookup/match.py` actually exports: `load_terms`, `alias_map`,
`value_alias_map`, `normalize_identity`, `resolve`, `expand`, and
`Resolution`'s four fields.

The mechanism is `src/app/tests/test_docs_name_real_symbols.py`. A backticked
*call* in a current doc must resolve to something that exists — a registered
MCP tool, or any `def`/`function`/`const` in the tracked tree. The vocabulary
is scraped (~2,970 symbols), never listed, because a hand-kept list is the
exact failure being closed and enumerating one would reproduce it a layer out.
That distinction is what makes the gate usable: `create_app()` and
`declared_columns()` are real and docs are right to name them, while
`finish_model()` is not anything. Out of scope by rule: `docs/historical/`
(being stale is its content), `docs/superpowers/specs/` (dated records — a
spec describes the tree on the day it was written), and blockquoted lines,
which is how this repo already marks a superseded passage. Mutation-verified
both directions: `finish_model()` on a plain line fails, the same text quoted
passes. Five real offenders on first run, all genuine, all fixed.

### 2026-09-10 — The research brief pointed agents at tools that do not exist (B90)

Branch `agents-are-actually-reachable`. The reader installed 0.5.2, it opened,
and the report was: *"research buttons do nothing, no connection with the
agents and no agents guidline for brand new packages. furthermore, agents seem
to not integrated."* Three separate defects, all confirmed against a copy of
their own store, and one of them is the answer to the other two.

**The brief named `add_document` and `add_evidence`.** Neither has existed for
months. `app/mcp_server.py` registers thirteen tools and the one that files a
finding is `submit_findings` — confirmed by asking the reader's *installed*
binary directly: `kriko-sidecar.exe --mcp` completes a real handshake and lists
all thirteen, and those two are not among them. This matters more than a
wrong name because of what the $0 plane is: `AgentResearcher.gather()` returns
nothing on purpose, so the **brief is the plane's entire output** and every
tool name in it is a call an agent will actually attempt. An agent handed it
followed it and failed. The brief now names `submit_findings`, gives the real
six required fields, and shows the call filled in with the subject's own id.

**Where the names came from, which is the more useful finding.**
`docs/USAGE.md`'s Step 4e documents a pipeline MCP server under `packs/cars/`
with nineteen tools, `add_document` and `add_evidence` among them. That server
is gone — not one of the nineteen exists anywhere in the tree. The brief was
written against a stale second copy of a tool list. The inventory is now marked
as pre-pivot and gone rather than left readable as current; rewriting the rest
of Step 4e is an unrowed follow-up.

**`app/agentskill.py` had it right the whole time**, and that is why nothing
caught it. Two documents instruct agents, they disagreed, and nothing compared
them — to each other or to the server. `test_agent_instructions_name_real_tools.py`
is that comparison: it reads the tools the server actually registers and fails
if any agent-facing document names one it does not. Five documents are in
scope — the brief, the generated skill, `app/agenda.py`'s row actions,
`ui/src/lib/agenda.ts`, and every pack's own `research/skill.md` and agent
prose, globbed so a second category is held to the first's rule.

The hard part is telling a tool name from a field name; both are snake_case in
backticks and the documents are full of both. Nothing is enumerated. The
legitimate non-tool words are derived — the fields `accept_findings` actually
reads off its own source, every tool's parameter names off their signatures,
`agenda.KINDS`, and the alias tiers `plan_task` sorts into. A new field needs
no edit here; a retired tool cannot hide behind one. Host prefixes pass by
rule, not by list: `mcp__kriko__submit_findings` ends in a real tool's name.

It reads **only the text that reaches an agent** — for a Python module its
string literals and not its docstrings, via `ast`. That distinction is load
bearing in this very repo: the retired names are now discussed three times in
a docstring one function above the brief they were removed from, and a coarser
check would have to choose between failing on its own history and not reading
the brief at all. Mutation-verified both ways: RED with `add_evidence` back in
a literal, GREEN with it only in prose.

**And the scaffold never wrote `research/templates.yaml`.** `plan_task` renders
a brief's searches from that file, so every pack authored through
`kriko pack scaffold` rendered **zero** queries — a brief that says what to
keep and never says what to look for. That is "Research does nothing" as a
literal description, and it is the "no guidline for brand new packages" half of
the report. The scaffold now writes one, derived from the identity keys the
author just declared rather than from a category it cannot know, and the brief
states the absence instead of omitting the section when a pack still ships
none. Verified end to end: scaffold a `bikes` pack, build it, install it, ask
for a brief — five queries and a `submit_findings` call carrying the real
subject id. `docs/PACK_CONTRACT.md` now documents all three `research/` files
by name, which of them is required in effect, and that `kriko/pack/build.py`
is the list that decides what ships.

**What was not broken:** the wiring. `/api/agent-config` advertises the frozen
binary with `--mcp`, `mcp` is deliberately in the PyInstaller spec's hidden
imports, `packaging/smoke_sidecar.py` smoke-tests the handshake, and the
installed binary answered thirteen tools when asked. "No connection with the
agents" was an unwired install plus a brief no agent could act on, not a broken
address.

---

### 2026-09-10 — The shell had not compiled since B83 (B89)

Branch `shell-parses-as-rust`. The reader asked why the installer needed their
machine. It did not — `done.md` already recorded that this box reaches the
Windows host through `/mnt/c` plus binfmt interop, and I repeated a stale
handover line instead of the repo's own record. `powershell.exe` is simply not
on `$PATH` here, which reads as "no interop" if you stop at `which`.

**So the build ran, and it failed.** `tauri/src-tauri/src/main.rs:110` held
three adjacent string literals with no `concat!` and no commas. Rust does not
join adjacent literals the way C does, so that is a parse error — three rustc
errors from one cause. It shipped in `a062b86` (B83), survived the
`release: 0.5.2` commit, and was found by the first `cargo` that ever read it,
nine minutes in, after PyInstaller had already frozen a sidecar. Nothing
reached a reader: `v0.5.2` was never tagged and no installer was ever built
from it.

**The twelve tray tests passed on it, and that is the finding.** Every guard
over `tauri/` reads `main.rs` as text and asserts that some string is present
— and code that does not compile still contains its strings. Confirmed by
restoring the shipped file: the new gate RED, `test_the_shell_runs_in_the_tray.py`
GREEN.

**The premise was written in their own docstring.** "There is no Rust toolchain
on any machine that touches this tree" — taken as settled rather than
re-checked, and false: there is a `rustc` in this WSL and a full toolchain on
the host. Twelve careful tests were written *around* an assumption instead of
testing it. Corrected there, in CLAUDE.md's shell section, and in the doc
map's `tauri/README.md` row.

**The mechanism.** `test_the_shell_is_valid_rust.py` parses every `.rs` with
`rustc` alone. A real `cargo check` wants the crate's dependencies and, on
Linux, `webkit2gtk`, which is absent — it would fail on system libraries and
say nothing about the code. Parsing needs neither, because rustc reports
syntax errors *before* it resolves an `extern crate`: a parse error is an
`error:` with **no** code, an unresolved name is an `error[E0432]`, and that
discrimination is the whole gate. Edition read off `Cargo.toml` rather than
written down. It skips where there is no `rustc` and never passes silently.
0.12s, and it would have caught this on the commit that introduced it.

It does not see type errors and does not claim to; `desktop.yml`'s Windows leg
and `packaging/build_desktop.ps1` remain the only things that compile the crate
for real.

**Then the installer built.** `Kriko_0.5.2_x64-setup.exe`, 22.8 MB, every stage
green including both smoke steps — the frozen sidecar answers and the bundled
shell opens. Unsigned (B64).

Still open: `581e76d` bumped both version files to 0.5.2 and never tagged, so
`desktop.yml` — which builds on tags — never ran on the tree that could not
compile. A version bump with no tag is the process gap that kept this alive for
two releases' worth of commits.

Gate: `.venv/bin/python -m pytest -q` green; the new gate mutation-verified
against the exact code that shipped.

---

### 2026-09-10 — The client stops speaking the site's language (B88)

Branch `local-panel` (`ed3bb15`). `extension/hover_lite/hover_lite.js` held
hardcoded Turkish part-name regexes and alert thresholds; `extension/content.js`
held the damage-state words and the equipment categories. I had flagged it twice
without fixing it. It is `_MAKE_MAP` one language further out, in the one part of
the tree no Python AST gate can read — and no test scanned `extension/` for
vocabulary at all.

**The words come off the pack now.** `packs/cars/adapters/sahibinden.json`
declares a `local_panel` block: block/item selectors, the site's own words for
each damage state, the English titles/tones/hints the panel prints, the
equipment categories, a `measures` entry with its own currency table, and 11
alert rules with their thresholds. `kriko.adapters.local_panel()` returns it
**opaque** — validating its shape in the engine would mean writing that shape
down in the engine, which is the same mistake as writing the words down in the
browser — and `GET /api/adapters` carries it to the client, `{}` for an adapter
that declares none.

**It stays data because a pack shipping code would be a page-wide grant.** No
`RegExp` is built from a pack-supplied pattern, only from declared *terms* with
metacharacters escaped (`$` is both a declared currency key and an operator).
Two format rules earn their keep: array order is precedence, because
"lokal boyalı" contains "boyalı" and the narrower state must be declared first;
and `unless: [<rule-id>]` is an else-branch written as data, which bought the
one bit of control flow the alerts needed without giving the format boolean
expressions.

**The presentation rides in `listing.panel`** — the half of the scrape that
`background.js` documents as never going on the wire. So the pack's titles and
thresholds reach the renderer without reaching the engine, which has no rule
for any of this and should not acquire one.

**The rewrite passed the pre-existing suite 12/12 after one plumbing fix**, and
that is the finding. The old test asserted only that `damage_info` was *truthy*
— which the hardcoded version, the declarative version, and a version reading
nothing at all all satisfy. `extension/tests/local_panel.test.js` is 15 tests
that assert values, reading the *shipped* adapter rather than a copy, because a
test carrying its own copy of the rules cannot notice the shipped ones going
stale.

**Two gates, so the next one fails the suite.**
`test_the_extension_speaks_no_sites_own_language` strips comments and lone
delimited non-ASCII characters (a character fold — both `foldTerm`s need one)
and flags any remaining non-ASCII *letter*: a character is a fold, a word is
vocabulary. It is what found the last hardcoded Turkish word, `"Donanım"` as a
fallback bucket label at `hover_lite.js:142`, which no test had caught.
`test_the_shipped_panel_declares_what_the_interpreter_reads` derives the
honoured key set from the interpreter's source via `rule\.(\w+)` and asserts
set equality both ways — a hand-listed set survived mutation testing, this one
does not. Its docstring says plainly what it cannot see (a present-but-dead
branch) and where that is caught instead.

Also fixed here: `docs/INTERNALS.md`'s request-path steps 1, 2 and 6 still
described `extractSahibindenMetadata()` and `mapTurkishKeys()`, neither of
which has existed since Phase 6c. A doc that says the Turkish map belongs in
the client is worse than no doc. Steps 3–5b of that section remain pre-pivot
and are still wrong; out of scope here.

---

### 2026-09-09 — Building knowledge, as a system rather than a possibility (B86)

Branch `knowledge-building` (`0ab613d`, `b945408`). The reader looked at 0.5.1
and said they still could not tell how they would build knowledge with their
agents — with the agenda, the research plane, the acceptance path and the MCP
tools all already shipped. So this is two things at once: the second plane the
system was missing, and the screens that admit any of it exists.

**Two planes, one acceptance path.** `kriko/research/` had the abstraction and
one implementation. `ApiResearcher` is now real: three injected callables
(search, fetch, complete) supplied by `src/app/providers/` over stdlib
`urllib`, because `exa-py` and `openai` live in the `pipeline` extra and the
frozen desktop binary carries neither — three JSON requests should not become
two core dependencies for every reader who never sets a key. Whatever either
plane finds goes through the same grounding check (`quote not in
document.text` → dropped) and the same `app/findings.py`, tagged with the
plane. A pack's claims must not depend on which door they came in.

**The budget is a hard stop.** All accounting stays in `_charge`, held by two
gates: a behaviour test that overshoots a 15¢ ceiling and asserts the *second*
query never ran, and an AST gate requiring every `except BudgetExceeded` in
`src/app/` to reach a `raise`, `break` or `return`. `_budget` also floors a
paid run nobody budgeted, because `_charge` reads zero as unlimited — the
"unattended run with no ceiling" trap, closed on the api plane only so the
agent plane keeps its honest zero.

**Keys are a file, not a keychain.** `~/.kriko/env` at mode 0600, loaded into
`os.environ` at sidecar startup so precedence falls out for free.
`GET|PUT /api/keys` is write-only by construction: `keys.require` is the only
function that returns a key and never leaves the process, and a test drives
six requests through the router asserting the fixture appears in no response
body. Two declared providers only, so a localhost-reachable endpoint cannot
become an arbitrary way to set `PATH` for the next launch.

**Provenance in `app.sqlite`, never the engine store.** `research_runs` and
`research_run_claims` record plane, completion API, search provider, budget,
spend and which claims a run wrote. In the engine schema they would make a
pack's `content_digest` depend on who grew it, and pack-update refusal is
built on two installations computing the same digest for the same version.
Claim counts are subqueries rather than a stored total that undo would
falsify.

**The unattended run is inline, on purpose.** `app/web/jobs.py` has a single
worker, so a job that submits jobs waits behind itself forever — a queue that
never drains and rows spinning, which reads as slowness rather than as a bug.
`agenda_run` calls the research path directly, shares one ceiling across rows
(ten rows at $0.40 each is a $4.00 run wearing a $0.40 label), de-duplicates
by subject, and counts `unknown_subject` rows out loud rather than dropping
them silently.

**Undo landed before the loop that needs it.** `retract_claim` removes a claim
and its evidence and leaves `sources` alone, because a source row is shared
between claims and a dangling `source_id` is worse than an unreferenced row.
Already-absent is reported, not failed.

**Each pack now ships `research/skill.md`** — its own method for identifying a
subject before searching for it. The reader's point: products are not just
names, they have attributes, and which ones pin a product down is a property
of the category. So it is pack data, composed into the generated agent skill.

**The screens.** Agents → Wiring shows both planes under the agenda they work
down, the paid one inert-but-explained without keys. Settings → Research keys
is write-only because no endpoint returns a key, and prints what each provider
receives beside the box asking for it. Activity → Runs lists what wrote which
claims and offers *Undo this run* only while there is something to undo.

Four defects the tests found, all of the same kind — a rule stated correctly
in a comment and contradicted three lines away:

* `open_research_run` inserted `spent_usd` as `0.0`, so the agent plane's
  deliberate NULL — "nobody counted", as distinct from "cost nothing" — never
  survived, and `close`'s COALESCE preserved the false zero.
* The budget-stop source gate matched with a regex whose body-end lookahead
  read the *next* `except` clause, so `agenda_run`'s neighbouring
  `except Cancelled: raise` satisfied it and a `continue` mutation passed
  green. Rewritten over `ast.ExceptHandler`.
* The adapters' "keep no running total" gate could be broken by the word
  "budget" in a comment, so it now reads AST-stripped source: prose should
  neither satisfy a rule about behaviour nor break one.
* All three new components flattened an exception into state, which B79's gate
  exists to catch; and the runs list printed a `model` name, which
  `test_ui_contains_no_pack_vocabulary` bans because `model` is a car identity
  key. The collision is real rather than incidental — a car has a model, so
  does a completion API — so the column keeps its name and the wire says
  `llm`.

### 2026-09-09 — The engine outlives the window, and the three defects a reader could see (B83, B84, B85)

Branch `agents-and-tray`. Three things the reader reported from a screenshot of
0.5.1 running, and the one that was architectural came with an approval gate
before any code.

**B83 — the engine keeps serving after the window closes** (`85c0ced`). Closing
the window killed the sidecar, so the browser extension was dead in the one
situation it exists for: the reader is on a listing page, not in the app. The X
button now hides and a tray icon owns the process. This inverts an invariant
CLAUDE.md documents and four tests enforced, so the trade is held together by
twelve gates in `test_the_shell_runs_in_the_tray.py`, all mutation-verified:
the tray is built in `setup` with `?` (a shell that cannot show one refuses to
start rather than trapping the reader), it has a Quit, Quit calls `kill_engine`
*before* `app.exit`, `RunEvent::Exit` still kills, and `installer.nsh` stops
`Kriko.exe` before `kriko-sidecar.exe` in both hooks. That last file used to be
a fallback for a rare leak; now that a reader can leave Kriko in the tray for
days it is the normal path. **Unverified on hardware** — no Rust toolchain
touches this tree and `desktop.yml` has no credits, so nobody has seen the tray
yet; that needs a 0.5.2 hand build on the Windows host.

**B84 — the rail marker and the stray scrollbars** (`2f9a995`). The yellow
active-tab bar was a JS-measured element that re-measured on navigation only,
and its three real drift sources are not navigations: `font-display: swap`
means first paint measures fallback metrics, the `max-height: 820px` breakpoint
changes row height, and `.rail-nav` scrolls independently of routing. jsdom
sees none of it, which is how 391 tests passed while the bug shipped. The
mechanism is deleted in favour of `.nav-link.active::before`, laid out by the
browser's ordinary pass. The white blocks under the gray line were
*document*-level scrollbars: `.shell` clips its own overflow but nothing told
`html`/`body` they could not scroll, which a WebView2 that cannot parse `dvh`
or a DPI rounding difference is enough to expose.

**B85 — "Add the extension" stops asking readers who already did** (`69a1789`).
The bar keyed off `connected`, a liveness badge that goes stale after a few
quiet hours; "was this ever set up" is a different question and the router now
answers it with `ever_connected`. "Not now" also lived in component state, so
dismissal was forgotten on every launch — it is a row in `app.sqlite` now,
keyed by step id so declining one suggestion does not silence a later one.

**B87 — the one click opens a listing, not a copy of the app.** The reader:
"open with extension just opens the app interface in the web browser, exact
copy of the standalone app. I originally meant the hovering web extension."
Exactly right — `POST /api/extension/launch` handed the new browser this app's
own `/#/extension` page as its landing URL, chosen so the check-in
confirmation would be the first thing they saw. On that page the extension is
invisible by construction: it matches listing sites, and that is not one. It
now lands on a site an installed pack can read, taken off the adapter rows so
the app names no site itself, and the confirmation stays where the reader
already is — the status card on the Extension screen polls. With no pack
installed there is no such site and the app screen remains the fallback,
which is the one case the old behaviour was right for.

The fourth item the reader raised — that they still cannot see how to build
knowledge with their agents — is a design, not a fix: `81c145a`,
`docs/superpowers/specs/2026-09-09-knowledge-building-design.md`, unimplemented
and awaiting their review.

---

### 2026-09-09 — An installer built with no runner, and two defects in the build's own reporting (B52)

Branch `b52-installer-report`. `Kriko_0.5.1_x64-setup.exe` (22.6 MB) exists,
built by `packaging/build_desktop.ps1 -Version 0.5.1` on the Windows host with
no CI at all — the v0.5.0 tag's jobs died in three seconds with no runner
assigned, which is what a spending cap looks like from the inside, so B81's
hand-run path is now the path rather than the fallback. The bundled shell's
smoke passed: it stayed up 25s and did not panic. 0.5.1 was cut rather than
building unstamped, because an unstamped build inherits `0.5.0` and would put a
second file with that name, containing different code, beside the stale one.

Running it for real found two defects in the script that no test could have
found from the outside, and each ships the gate that was missing:

**The Done step listed installers it did not build.** `Get-ChildItem` over the
bundle directory reports whatever is on disk, so a `tauri build` that produced
nothing at all would still print a success report naming the previous release's
`.exe`. It now records `$started` before the freeze and lists only files newer
than that, throws when the set is empty, and — when `-Version` was given —
throws unless a file from *this* run carries the stamp, which is the only
end-to-end proof that a requested version reached the bundle's filename.
`test_the_script_reports_only_what_this_run_produced` and
`test_the_script_proves_a_requested_stamp_arrived` assert the ordering and the
filter in the script's source; stashing the fix fails exactly those two.

**Printed text was garbling on the console the script actually runs on.** The
verification build's own output read `engine spawned: not seen ù the webview
may not have run`: Windows console codepage 1254, an em-dash, and mojibake in
the one line a reader would consult. B81's first defect was the same encoding
in `.ps1` *source*; this is one layer down, in the Python the script calls.
Four em-dashes in `configure_updater.py`, `smoke_app.py` and `smoke_sidecar.py`
became `--`, and `test_a_packaging_script_prints_ascii_only` walks each
packaging script's AST for `print` calls and fails on a non-ASCII literal
argument. Only *printed* text is checked — Python reads its own source as UTF-8
regardless of the console's codepage, so comments and docstrings are free.

B52 stays open: nothing is signed, self-update waits on a minisign keypair, and
the success path is still unconfirmed by a human — the installer is on disk at
`C:\Users\beraat\kriko-build\tauri\src-tauri\target\release\bundle\nsis\`
waiting for someone to double-click it. That confirmation is what ends the
app-first phase, and it is not something a test can do.

---

### 2026-09-09 — The agent is told what to research next (B82)

Branch `b82-research-agenda`, spec
`docs/superpowers/specs/2026-09-09-research-agenda-design.md`. The last row of
the reader's 0.5.0 list, and the one that was not a UI change: an agent
arriving at the MCP door was told what it *accepts* and nothing about what this
installation actually needs. `coverage_gaps` answered a version of that already
— alphabetically, which is to say it answered "what is missing" and never "what
is missing that anyone has asked for".

`src/app/agenda.py` computes a ranked agenda on read, from four signals kept
separate: demand out of `analyses.jsonl` (the designated demand corpus, which
survives clearing history, and whose *position* is exact recency in an
append-only file — the record carries no timestamp, so the window is the newest
500 records rather than a date range), subjects with no claims, claims with one
source, and `fact_checks` whose quote has gone missing. No score: the row kind
and the demand count are shown separately, same principle as `ClaimHealth`.

**`NOT_MATCHED` is the strongest signal we had and the only one nothing could
see.** A reader bringing us a product the catalog cannot name is invisible to
every gap list, because a gap list can only name subjects that exist. It ships
as an `unknown_subject` row with no `subject_id` at all — so `submit_findings`
cannot be aimed at a neighbour — and both the MCP docstring and the copyable
prompt say in as many words that it is not a task for an agent.

Three doors on one computation: the `research_agenda` MCP tool (its docstring
opens "**Call this first.**"), `GET /api/agenda`, and the generated skill,
which now leads its loop with `research_agenda` and says that if the skill's
snapshot and the tool disagree, the tool is right. The Agents screen shows the
same rows above "What the agent is told", each copyable as a prompt for a
harness that is not wired to MCP at all.

Gates: the ordering gate from the spec (`["s-zeta", "s-audi"]` — a subject
asked about twice outranks an alphabetically-earlier gap nobody asked about,
the test that fails against `coverage_gaps`); a total sort order so two runs
agree; MCP and HTTP proved to be one computation; an unreadable log is a note
rather than an exception, and an unreadable `app.sqlite` costs only the stale
rows; no row carries the listing the reader was looking at; and the `KIND_WORD`
/ `KIND_TONE` maps in `ui/src/lib/agenda.ts` are regex-read from
`test_agenda.py` so a fifth kind cannot reach a screen as a bare token. 19
Python tests, 10 UI tests.

---

### 2026-09-09 — The 0.5.0 usability pass: shell, rail, one-click install, fact check

Branch `ui-0.5.0-shell-and-agents`, four commits. All from one reading of the
app by the reader: a browser scrollbar down the right edge of a desktop window,
a yellow marker sitting next to the wrong rail entry, fifteen rail entries, an
extension you install by following six numbered steps, and no way to ask
whether a cited page still says what the pack quotes.

**The window stops being a web page** (`c2121d3`). The rail was already told
not to scroll the document; the *view* was not, so a long report grew the body
and Chromium drew its own scrollbar over the shell's chrome. The marker lagged
because it animated from the entry that was active *before* navigation.

**Fifteen rail entries become twelve** (`94b8651`). Five System entries were one
question asked at three depths — the Subjects/Coverage/Health mistake again.
Runs, the knowledge pipeline and what researchers sent became three lenses of
**Activity**; Console and Connect became two of **Agents**. Every retired
route still resolves through `ALIASES`, because `#/coverage` is a link the
extension and this app's own older hints hand out.

**One click opens a browser with Kriko loaded** (`363b768`). No browser lets an
application install an extension into a browser that is already running, so
the honest version is starting a fresh Chromium with `--load-extension` and its
own profile. `POST /api/extension/launch` stages *and* opens in one request,
because one press must not be able to half-succeed — and `launched` never
means "installed": the extension's own call to `/api/adapters` remains the only
proof, both shortfalls answer 200 with prose, and the manual steps stay on
screen.

**One press asks whether the cited page still says it** (`2d2ee08`).
`app/factcheck.py` fetches a claim's cited page and looks for the pack's own
quote: `quoted / missing / unreadable / unreachable`. Deterministic, so there
is no judgement for anyone to review; `missing` is inert — it ranks nothing,
hides nothing, and says the page changed rather than that the claim is false;
and the verdict lives in `app.sqlite`, so one reader's dead link cannot move a
`content_digest` or travel to the next install. The matching is loose where
`findings.py` is strict, because re-reading shipped evidence is not the same
question as accepting new evidence. In the report as a per-claim badge with a
sequential, three-sources-a-claim sweep; in the panel as a per-card button that
sends only `(pack_id, claim_id)` — a door that took a quote from the caller
would be a fetch oracle for any page that can script the extension.

**The gates each one was missing**, per the 1.0.0 audit's rule: `.view`'s
overflow and the marker's source-of-truth are asserted in the shell tests; the
rail's ALIASES have a test that every retired name still resolves; the launch
route is tested for "never claims success"; and the verdict vocabulary has a
drift test in `src/app/tests/test_factcheck.py` that reads the wording maps out
of `risk_card.js` and `report.ts` and fails if either forgets a verdict —
a panel rendering an unknown verdict as reassurance would be the worst
available default. 377 UI tests, 108 extension tests, full pytest green.

---

### 2026-09-09 — B81: the installer stops needing GitHub's permission

`main`. The v0.5.0 tag produced nothing. Every job in both workflows exited in
three seconds with `runner_name: ""` and `steps: 0` — GitHub never assigned a
runner, which is what a spending cap looks like from the inside. The tag is
pushed, the suite is green, and there is no installer, because the only thing
in the repository that could build one was `.github/workflows/desktop.yml`.

That is the app-first phase's rule 4 failing on a technicality: *ship to the
reader, not to the branch*. A fix that is not in an installer they can
double-click is not a fix yet — and it turns out neither is a release.

**`packaging/build_desktop.ps1`** runs the workflow's windows leg on a Windows
box, in one command: install from `requirements.lock`, build the UI, freeze the
sidecar, smoke the handshake, place it as `kriko-sidecar-<triple>.exe`,
generate icons, configure the updater, `tauri build`, launch the bundled shell.
Nothing was invented for it. PyInstaller cannot cross-compile, so a Windows
sidecar has to be frozen on Windows regardless — the steps were never
Actions-specific, they were just written down somewhere only Actions could
read. `packaging/freeze.sh` covered the first half already and its header said
so ("the Tauri bundle ... is still only built in desktop.yml"); that sentence
is now a pointer rather than a dead end.

**The gate, because two copies of a build drift.** A step added to CI and not
to the script means a hand-built installer is quietly not the one a tag
produces, and nobody finds out until a reader opens it — precisely the shape
of failure the audit was about. `src/app/tests/test_the_installer_can_be_built_by_hand.py`
reads the `bundle` job out of `desktop.yml`, extracts the artifacts it *names*
(`requirements.lock`, `kriko-sidecar.spec`, `smoke_sidecar.py`,
`configure_updater.py`, `smoke_app.py`), the npm surfaces it builds
(`ui` and `tauri`, install and script) and the `tauri` subcommands it runs, and
asserts the script names every one. Derived, not enumerated: a new
`packaging/whatever.py` step fails this the day it lands. Plus the two order
invariants a subset check cannot see — freeze before place before bundle
(Tauri embeds whatever is in `binaries/` at bundle time, so the wrong order
ships the *previous* run's sidecar, green and silent), and sidecar smoke before
bundle before app smoke. Steps guarded to the linux/macos legs are skipped by
reading their `if:`, never by an allow-list of windows steps — an allow-list
would drop a new step, which is the drift being checked for.

**Then it was run, and it was wrong three times.** The script was written,
gated, reviewed and merged without ever executing — and it did not survive
first contact. This box is WSL2, so the Windows host *is* reachable from here
(`/mnt/c` plus binfmt interop), which turned "produce an installer from this
machine" from impossible into four builds. Each defect got the gate that was
absent, and each gate was confirmed to fail on the code that shipped it:

1. **The script would not parse.** Six cascading errors, at lines that were all
   wrong. Windows PowerShell 5.1 decodes a BOM-less `.ps1` with the system ANSI
   codepage, not UTF-8; this machine is codepage 1254, so one em-dash in a
   comment became three bytes, one of them a quote — and the failure surfaced
   in the *next* string literal. `.ps1` files are now ASCII-only, checked over
   `git ls-files '*.ps1'` (a worktree glob reaches `.venv/`, which nobody here
   can fix). A BOM would also work and is invisible in a diff, so the next
   person writes the same bug; ASCII is visible.
2. **`--version ""` reached argparse as a bare `--version`,** exit 2, nine
   minutes into build 2. PowerShell *drops* an empty-string argument on its way
   to a native command; `pwsh` 7.3+ has `$PSNativeCommandArgumentPassing` and
   5.1 has nothing. Fixed by expressing "empty" as *absence of the flag*, which
   both shells agree on — the argument list is built as an array and `--version`
   is appended only when there is one. `-Repo` is derived from
   `git remote get-url origin` for the same reason CI passes it: a fork's build
   should point at the fork's releases. The gate rejects any empty-string
   argument to a native command, skipping Verb-Noun cmdlets (where the elision
   does not apply) by PowerShell's own naming convention rather than a name list.
3. **`[WinError 5] Access is denied`** overwriting `dist/kriko-sidecar.exe` on
   build 3. `smoke_sidecar.py` ended the sidecar with a bare `terminate()`, and
   PyInstaller onefile re-execs — the pid you spawn is a bootloader whose
   *child* holds the `.exe` mapped. The orphan then owns the file the next build
   must write. `tauri/` has tree-killed since v0.2.x and `smoke_app.py` does
   too; `smoke_sidecar.py` was the third caller and the one that got it wrong.
   New `end()` helper does `taskkill /T /F /PID` — by pid tree, never by image
   name, because `/IM kriko-sidecar.exe` would also kill an installed Kriko the
   person at the keyboard is using. Gated over every `packaging/*.py` that
   calls `Popen`.

**Why no gate caught any of these.** A GitHub runner is destroyed after the
job, so an orphan holding a file has nothing left to break; and a UTF-8-clean
bash shell hides both PowerShell defects entirely. All three need the build to
run twice on one machine that a person also uses — which is the entire premise
of B81, and was the one configuration CI structurally cannot be.

Gate: pytest 1027 passed / 6 skipped locally; CI unavailable (quota). The
installer itself is the other gate, and it is the one that matters.

---

### 2026-09-08 — the 1.0.0 audit, part two: the subsystem, the sites, and the long tail

`release/1.0.0-readiness`, commits `53f0ac0`, `9e4a376`, `39a7c50`, `56af236`,
`414ae74`, `e5ef22f`, `42dbab8`, `bc7ae01`, `23ecfb5`, `f2a310a`, `6070657`
— [PR #12](https://github.com/Berbadov/kriko/pull/12). The rest of the audit's
rows: B57's Python half, the pipeline event spine and its view, runtime site
registration, and the independent findings B70–B80. Same rule as part one —
every behavioural fix ships with the gate that was absent.

**B67/B68 — the knowledge pipeline had no event spine.** The reader's Console
showed a job log and nothing about what the pipeline was *doing*: no stage, no
counts, no live view of what was discovered or extracted. Shipped as
`app/web/pipeline.py` — `pipeline_runs` / `pipeline_stages` /
`pipeline_events` in `app.sqlite` (interface state, never the engine's
schema), an `Emitter` the *interface* owns so `kriko/` emits nothing and
learns nothing about the transport, and SSE at `/api/pipeline/stream`. Stages
are Discovery / Extraction / Ingestion / Ledgering. Rows land before the
stream, so a run killed by a restart is still readable — and is marked
`interrupted` at startup rather than left spinning. `NULL` tokens are not `0`:
the agent plane meters nothing and says so, and `skipped` is not `done` with
zero. The Pipeline route is the view over it: per-stage progress, token counts
as they accrue, the knowledge entries landing and the sources they came from.
Progress counts *settled stages* and is never interpolated from item counts —
nothing knows how many findings a source will yield, and a bar that moves
backwards is worse than a coarse one. The feed scrolls in its own `role="log"`
region, focusable, because a region a keyboard cannot reach is a region it
cannot read.

**B69 — adding a listing site was a manual manifest edit.** The server learned
about a site the moment its adapter file existed; the extension learned about
it when somebody edited `manifest.json` — a scalability-principle violation
sitting in the one file nobody thinks of as data. `syncSites()` in
`background.js` reads `/api/adapters`, turns each `site` into exactly one match
pattern, and reconciles `chrome.scripting`'s registrations towards it.
*Detection* is the app's answer, never a hostname list in the worker;
*synchronisation* reads back `getRegisteredContentScripts()` and converges,
because an MV3 worker's memory does not survive it; *conflicts* are impossible
by construction, ids being derived (`kriko-site-<host>`); *recovery* is a
30-minute alarm plus startup and install, and a failed sync keeps every
existing registration rather than tearing the panel down because the app is
closed. The host permission stays a user gesture in the options page — Chrome
requires it and is right to; that is consent for reading a third party's
pages, not a human in the data path. A pack's `site` is validated as a bare
hostname, so an adapter cannot ask for `https://*/*`. B65's invariant is
relaxed rather than dropped: a site must be covered by the static manifest
**or** by `optional_host_permissions`, still derived from the pack tree, and
still failing when it is covered by neither.

**B70 — a site redesign was invisible.** `unmapped_labels` was computed on
every lookup and dropped. It is the only signal a site gives when it renames a
field: nothing errors, the lookup succeeds, resolves less precisely and returns
fewer claims — so a broken adapter reads as a thin pack. Now a table in
`app.sqlite`, one row per (adapter, label) with a `seen` count. Accumulate
rather than append: a row per sighting would grow with reading volume while
answering a question about *distinct* labels. Dismissal is a `DELETE`, not a
flag, so a label that recurs comes back — the honest answer to "I dismissed
this and it is still happening". It lives in `app.sqlite`, not the store: a
pack's adapter is content, what a reader's browsing revealed about a site is
not, and it must never move a `content_digest`. **The gate that was missing
came with it:** `src/app/tests/conftest.py` fails any test that opens the
reader's own `~/.kriko/app.sqlite`. `test_web.py`'s fixture had been doing
exactly that for 54 tests, which is how a new test first read `seen: 11`.

**B72/B79 — error copy named exceptions, not next steps.** "Could not load this
view: ConnectionError" is accurate and useless: the reader of a local app has
no terminal, no log viewer and nobody to page, so whatever the screen says is
the entire remedy available to them. The remedy is derived from the **HTTP
status**, in one module (`ui/src/lib/failure.ts`), never from the view — a
per-view table would be twenty places to keep in step and the twenty-first
view would ship with none. Statuses are a closed vocabulary that does not grow
with the product, which is exactly the exception the scalability rule carves
out. Four things every failure carries: what happened in the reader's terms,
the next action, whether trying again could plausibly work (a retry offered on
a 404 is a button with no path to working), and the exception itself, folded
away underneath rather than dropped.

B79 is the sixteen views B72 did not reach, and the gate that stops the
seventeenth. Every one did the same thing one line *earlier* than the bug B72's
gate was looking for: `error = String(cause)` into a `$state("")`. By the time
the markup runs there is no status left, so no remedy can be derived however
good the component downstream is — and a gate that reads only markup cannot
see it. Twenty-two sites across eleven files, in nine spellings of the same
variable. Three shapes came out of it, and they are the pattern for anything
new: a **view** renders `Failure`; a **row** is too small for that block and
renders `remedyFor(x).headline`, the sentence still derived and only the frame
smaller; the **Console** renders `remedyFor(x).technical`, because it is the
one surface whose reader *asked for* the exception. Two findings fell out of
the pass — `Check` was keeping a validation sentence this app wrote ("paste a
link first") and an exception from the engine in the same string, so the
reader's own typo and a dead engine rendered identically (two variables now);
and `remedyFor(x).technical` turned out to be exactly the
`(cause as Error).message ?? String(cause)` that four files had each written by
hand, so "the exception as text" has one definition and the new gate needs no
exemptions.

**B73 — the extension and the app never handshook.** Two headers, both riding
on requests that were already happening: `X-Kriko-Extension` out,
`X-Kriko-Minimum-Extension` back. No poll, no endpoint, no third clock to keep
wound. One number in one place, `extension.MINIMUM_VERSION`, bumped only when
a wire change genuinely breaks an older client — not a compatibility matrix,
because three clocks (knowledge weekly, the binary rarely, the extension
again) would make a matrix wrong within a release. Three states, not two:
`unknown` (nothing has called) is separate from `too_old`, because telling a
reader who never installed the extension that theirs is out of date is worse
than saying nothing. **The missing gate came out of it.** Adding
`extension_seen.version` revealed that `CREATE TABLE IF NOT EXISTS` does
nothing for a new *column*: the stamp moves, `PRAGMA user_version` is
rewritten, and the column is silently absent on every existing reader's file
until the first query names it. Every prior change to this schema had been a
new table, which is why it survived. `state.add_missing_columns` reconciles
what SCHEMA declares against `PRAGMA table_info` — parsed off the declaration,
never a migration list to remember.

**B74 — nothing verified the keyboard walk.** The audit row's claim was too
strong: the rail is real anchors, the skip control was already first in the tab
order, focus already moved into the view on navigation. What was true is that
every keyboard test in the suite covered one route with its own hand-written
hash, so three failures were invisible — a rail entry `App.svelte` does not
handle (a link that is focusable, announced, and leads to "No such view"), a
screen with no `NAV` entry (reachable only by typing a URL, which in a desktop
app with no address bar means not reachable), and focus escaping a modal. **The
third was a live defect and is fixed:** the palette declared
`aria-modal="true"` and did not keep it, so Tab off the last option walked into
the rail behind the scrim. It wraps at the two ends now, reading its stops off
the dialog at the moment of the press because the list is filtered as the
reader types. `ui/src/App.keyboard.test.ts` walks every destination in `NAV`,
one case per screen rather than a loop, because "which screens are missing" is
the useful answer. **One thing this cost, worth writing down:** the first
version was green with a route deleted from the if-chain. `waitFor` retries
until an assertion *passes*, so a negative assertion inside it passes on the
empty first frame and never sees the screen it is judging. Wait for a positive
signal, then assert negatives synchronously.

**B75 — a content script pulled a font from Google.** On every listing the
reader opened, from the one component running where that is observable: it told
a third party which cars they were looking at, and it failed offline, which is
the state the product is designed for. Fonts are system-first now, and the gate
is derived from `app.extension.SHIPPED` — no remote host in anything shipped,
by any of the three spellings of the mistake.

**B77 — nothing checked that an onboarding link goes anywhere.** The path was
already real; what it had no check on was whether the somewhere it points at
*exists*. A dead link in onboarding is the worst dead link in the product: it
is the reader's first minute, they have no model of the app yet to tell them
the app is wrong rather than they are, and what they get is "No such view" —
from where they sit, indistinguishable from a broken install.
`ui/src/lib/links.test.ts` walks the source for every destination anyone writes
down and asks whether `App.svelte` would render it, in all three spellings: a
literal `#/name`, a `toHash`/`hashWith` call, and a route name handed to
`NextStep`. The renderable set is read off `nav.ts` and off `App.svelte`'s own
if-chain, including the parametric views with no rail entry, which would
otherwise have needed the exemption list the file exists to avoid. And the one
real defect on that screen: `Welcome` was still printing `e.message`, so the
first sentence Kriko ever said to someone could be a `TypeError`.

**B80 — 197 KB in one chunk, which nobody had decided.**
`src/app/tests/test_bundle_budget.py` makes it a decision. The decision
recorded there is that there is *no* code splitting and that this is right:
splitting trades one download for several, which pays on a website, where the
second chunk crosses a network and most visitors never reach the screen it
holds. This bundle is read off local disk by a window the shell only shows
after `/api/health` answers, and every reader has every route. So size is not
something to optimise here, it is something to watch — and the failure guarded
against is not a slow app, it is a dependency arriving that nobody weighed.
Budgets are generous by about a third and deliberately **not** a ratchet: a
ratchet that tightens every build turns unrelated commits red and teaches
people to raise the number without reading it. Raising it is fine; raising it
knowingly is the point.

**B78 — the docs did not match the code.** Ten of the twelve tables in
`app.sqlite` were named in no document, and six API surfaces — history, marks,
subjects, pipeline, submissions, extension — had no endpoint written down
anywhere. Fixed in `docs/INTERNALS.md`, with `routers/focus.py` (the fix for
"Open in App opens a browser tab") finally introduced in the Desktop Shell
plane. **The mechanism, because a docs audit performed by a person is the
manual step G5 forbids:** `test_docs_match_the_code.py` asks questions *of the
code* and looks for the answers in the prose — every table in
`state.declared_columns()`, every API surface walked off the live route table,
the two-database split, the handshake headers, every path CLAUDE.md's
documentation map cites. Nothing is listed in the test, so a thirteenth table
goes red the day it lands. **Two things this cost.** The first version asked
whether the string `"focus"` appeared in the docs, and it did — in every
sentence about where focus lands after navigation — so the gate passed while
the surface named `focus` was undocumented; a router whose name is also an
English word is exactly the one a name check misses, and the check is by
endpoint *path* now. The second: FastAPI keeps one `_IncludedRouter` per
`include_router` call rather than flattening endpoints into `app.routes`, so
the obvious one-level loop found nothing at all — caught only because the test
asserts it found more than ten surfaces before judging them.

**B57 — the fourth dependency surface.** Three were already closed: all three
`package-lock.json` files are committed and `desktop.yml` uses `npm ci`. The
one still floating was the Python closure — `pip install -e "."` resolves
whatever PyPI holds the minute the job runs, and that job is the only one that
produces the binary a reader double-clicks. The evidence is not hypothetical:
v0.2.1 opened and v0.2.4, built four hours later from an identical tree,
panicked on a config both shipped. `requirements.lock` pins the runtime
closure, walked from `pyproject.toml`'s five roots by `tools/relock.py`.
Runtime *only* — pinning the pipeline and dev extras would make every
research-tool bump a change to the artifact a reader downloads. Installed with
`-r` rather than `--no-deps`, because two members are Windows-only (colorama
via click, pywin32 via mcp) and cannot be pinned from a Linux resolve. **The
gate runs in both directions**, because a pin nobody runs against is a guess
with a version number on it: every runtime root reaches the lock, *and* every
pin matches what the suite just passed against, so the lock cannot go stale
while the suite stays green. Regeneration stays a deliberate act —
`tools/relock.py` prints the file and the test only ever compares.

**B71 — closed without a change.** The audit row was written from a screenshot
and duplicated work already on `main` (`cb27d13`, `d362769`, 2026-09-05).
Recorded rather than deleted, because "the audit found a gap that was not
there" is the useful fact: a screenshot is evidence of what a screen looks
like, not of what the code does. Same for F11's retry affordance — the
endpoint, the API method and the button all existed.

Still open, and none of it is code: **B63/B64** are two decisions only the
reader can make (the repository is private, so the updater and `packs.json`
URLs 404 for a running app — recommendation, a releases-only public mirror;
and nothing is signed — recommendation, minisign now, defer the
~$200–400/yr authenticode certificate). **B44** is the missing LICENSE.
**B53** (`Cargo.lock`) needs a Rust toolchain. And the app-first phase still
ends where it always did: a reader double-clicking an installer.

**B53 — and the fifth surface, which needed a toolchain.** The last of the
five: `tauri/src-tauri/Cargo.lock` was not in the repository, and every crate
in `Cargo.toml` is a bare major (`tauri-plugin-updater = "2"`), so each CI run
resolved whatever crates.io held that minute. This is the surface v0.2.4
actually failed on — the plugin's tolerance for a missing `plugins.updater`
changed underneath a byte-identical tree, and the installer built green and
panicked before its first window. The row said "needs a Rust toolchain", which
was true and was also the whole reason it kept not happening; rustup is a
user-local install and `cargo generate-lockfile` only resolves, so it took
minutes rather than a build environment. 501 packages, all from crates.io.

**Cargo folds every target into the one lock**, which is the fact that makes a
Linux resolve the right one: the file pins the Windows and macOS graphs too (73
`windows*`/`objc2`/`core-foundation` entries), so no Windows box is needed to
regenerate it. That is also the failure mode worth a gate, because if those
families ever vanish the lock was produced some other way and pins nothing for
the two platforms readers download.

**The gate, in two halves, and neither needs Rust.** `cargo metadata --locked`
runs in `desktop.yml` before the bundle step — cargo *uses* a committed lock
without being asked, but it will also quietly rewrite one that has fallen
behind the manifest, and then the tagged release is not the graph anybody
reviewed. And `src/app/tests/test_shell_is_locked.py` asks four things of the
tree on every machine: every declared crate is locked at the declared major
(one case per crate, so the failure names it), the foreign-target families are
present, nothing resolves to a `git` or `path` source, and the workflow's
`--locked` check comes *before* the build rather than after it, which is the
ordering the whole thing turns on. Verified red by bumping one crate's major.

**And two things the branch's own CI found within the hour**, both of them
the new gates catching the commit that introduced them. `test_shell_is_locked`
and the `--locked` step went green locally and red on the Windows runner,
because a step's default shell is the *runner's* — PowerShell there — and
`> /dev/null` in PowerShell names `C:\dev\null`, whose parent does not exist.
Two runners green, one red, on a line with nothing to do with either;
`shell: bash` is the fix and `test_no_posix_only_step_runs_unshelled_on_a_windows_runner`
is the gate, because the convention already existed on five steps and nothing
noticed a sixth skipping it.

The other was B57's drift check firing on `ci.yml`, which is the check working
rather than failing: CI installed `-e ".[dev,pipeline]"` and resolved fastapi
0.141.1 while the installer freezes 0.138.1, so the suite's central claim — it
passed against the closure the artifact ships — was false in the one place that
matters. `ci.yml` installs `-r requirements.lock` now, and the workflow half of
the gate is per workflow and derived from the directory, since what actually
went wrong was a *second* workflow installing Python with nobody remembering
the rule covered it. What that deliberately gives up: nothing on a pull request
notices a new upstream release breaking us. That belongs on a schedule — a PR
that fails because a third party published something is a PR nobody can fix.

Gates at the cut: pytest 1013; vitest 43 files / 341 tests; node 103;
svelte-check 0 errors; `tools/relock.py` reproduces `requirements.lock`
byte-for-byte.

---

### 2026-09-08 — the 1.0.0 audit: four defects, four missing gates

`release/1.0.0-readiness`, commits `1f3978e`, `ae70e39`, `3343126`. Four
defects were reported. Every automated gate was green at the time — pytest,
vitest, node, svelte-check — and all four passed all of them. That is the
finding: not four bugs, four missing *categories* of gate. So every fix
shipped with the check that was absent, which is the generalization principle
applied to the test suite rather than to the catalog.

**B55 — nothing was written down.** `log_analysis_jsonl` reported its failures
through `log.warning` into a root logger with no handler, so two months of
`PermissionError` on every append produced output nowhere at all. The call
site looks correct, and that is what let it survive review. `src/app/logs.py`
now holds two rules: a diagnostic lands beside the store and never in the
source tree (`source_root()` prefers the checkout, which is right for *data*
and wrong for a file the reader must be able to send us), and a path we cannot
write is reported rather than swallowed. `probe()` returns the reason and
deliberately *opens* the file rather than calling `os.access`, because a mode
check gets exactly the interesting cases wrong — another user's directory, a
read-only mount, Program Files. Both the path in use and the rejection reason
reach `/api/health` and the About screen. The gate: `test_logging.py` asserts
on the *reporting*, because a test that only proved the log gets written when
the directory is writable would have passed throughout the whole two months.

**B58 — the Console could not be typed in.** Route changes moved focus to the
view container, stealing it from the prompt the route exists to offer.
`[autofocus]` is now read as a declaration: a route that autofocuses a control
is taken at its word, the container is the fallback. Beats a hardcoded
route-name list, and beats racing `document.activeElement`. Proven red against
the old code, with two counter-assertions that pass both ways so the fix
cannot license breaking the document routes.

**B59/B60 — "Open in App" claimed a window it could not see.** The link was
replaced by a posted route months ago; what remained was a *claim*. The
response said `raised: true` on any 2xx, and a 2xx only means the route was
recorded — whether a window came to the front depends on whether anything is
reading the sidecar's stdout, which this process genuinely cannot observe and
the shell can simply declare. `--supervised` on the spawn, `KRIKO_SUPERVISED`
in the environment, `Settings.shell_attached`, `delivery: "raised" |
"no_shell"` on the response; `raised` kept as an alias because the extension
ships on its own clock. The line is printed either way, because a branch there
would leave only the supervised path ever exercised. On the extension side a
422 — this extension building a route the app cannot navigate to — was caught
by the same `except` as ECONNREFUSED and opened a tab at the same bad route,
hiding a defect in our own code behind a fallback meant for a missing app.
Three of the five new node tests are red against the old worker; the two that
pass are the two that should pass both ways.

**B61/B62/B76 — the rail scrolled as a document.** `grid-template-rows: auto
minmax(0, 1fr) auto` is the entire fix: a track's automatic minimum is its
content, so plain `1fr` refuses to shrink and pushes the overflow back out to
the parent. The rail clips, only `.rail-nav` scrolls, and its scroll shadows
auto-hide through four backgrounds with `background-attachment: local, local,
scroll, scroll` — two caps that scroll with the content, two shadows fixed to
the frame, no script and no ResizeObserver. Alongside it: inline SVG icons for
all 16 routes (inline rather than a font, because the app must render with no
network and a webfont is a box on first paint on the element people navigate
with), and one measured marker that slides rather than fourteen borders that
blink. The other seven `overflow` sites were audited and only the rail was
wrong. `chrome.test.ts` holds the shape against the stylesheet as text, since
layout is precisely what jsdom does not do and a browser harness for one CSS
property is not the trade.

**B56 — the port answered anyone.** Grouped with B59 because it touches the
same request path and should not be opened twice. Binding 127.0.0.1 protects
the port from the network and not from the browser: 8787 is a constant
published in this repository and hardcoded in the extension, and every page
the reader visits runs script that can reach it. `Origin` stops a cross-site
GET — most damage is already out of reach, since a JSON body is preflighted
and we send no CORS headers, but a simple GET still executes, and `GET
/api/focus` is consume-once, so a page could burn a nudge it cannot even read.
`Host` stops DNS rebinding, where the attacker's own domain resolves to
127.0.0.1 and is therefore genuinely same-origin. The Host rule is "a dot
means a public DNS name, so it must be one of ours", which is why there is no
test-only exemption: a rule with a hole cut in it for the suite is a rule the
suite stops testing.

**B65/B66 — the last two gates, and CI back on the branch.**
`test_extension_sites.py` derives from the pack tree that every adapter's site
is one the extension actually injects on, and that the panel's stylesheet
reaches it. That seam is silent when it breaks: the pack installs,
`/api/adapters` lists the site, and the reader opens a listing to no panel,
which is indistinguishable from "nothing known about this car". Derived rather
than listed, because a list would be the third place to forget. And
`smoke_sidecar.py` now asks whether a diagnostic can be written *in the frozen
binary* — where `_MEIPASS` vanishes and an installed app runs from Program
Files, neither of which a source checkout reproduces. `ci.yml` runs on
push/pull_request again with svelte-check added; the app-first phase's other
half stands, since it ends when the reader opens an installer rather than when
a workflow goes green.

Still open and blocking the critical path: B63 and B64 are two decisions only
the reader can make — the repository is private, so the updater and
`packs.json` URLs 404 for a running app (recommendation: a releases-only
public mirror), and nothing is signed (recommendation: minisign now, defer the
authenticode certificate). B67–B80 are the pipeline subsystem, the runtime
site registration, onboarding and the long tail.

Gates at the cut: pytest green; vitest 39 files / 276 tests (from 263);
svelte-check 279 files / 0 errors; node 73 tests (from 68);
`smoke_sidecar.py` run end to end.

---

### 2026-09-08 — a pack's name is content, and the digest now says so

`fix/digest-covers-the-manifest`. The generated agent skill still described the
cars pack as "Cars (TR market)" long after `pack.toml` was corrected to "Used
cars". `agentskill.py` was not at fault — it reads the installed store, which
is the right source — and neither was the build, which produced the corrected
name deterministically. The gap was in `ids.content_digest`, which hashed
sorted row ids and nothing else, so the pack's own manifest was outside the
value that identifies "this version of what Kriko knows".

The evidence: v0.3.0 and v0.3.3 published the same pack id at version `0.1.0`
with the byte-identical digest `d34e72d5db23e32b…` and two different names.
`updates.decide` compares version then digest, so it answered `UP_TO_DATE`, and
**no metadata-only correction could ever reach an installed store** — not a
name, not a licence, and not the identity keys that decide which of a pack's
rows merge with another author's.

`content_digest(row_ids, manifest)` now hashes the declared manifest alongside
the rows, canonicalised so key order does not move it. `manifest` is required
rather than optional on purpose: a pack may bring its own builder, and an
argument a builder can omit is one a builder will omit, invisibly, until the
next metadata fix fails to travel. Omitting it is a TypeError at build time.

Because the digest's definition moved, every pack's digest moved, so both packs
go to `0.1.1` — a republished version is refused loudly by `packstore.install`,
which is the correct noise when metadata changes without a bump.

Guards: `test_content_digest_covers_what_the_pack_declares_itself_to_be`,
`test_content_digest_will_not_be_computed_without_a_manifest`,
`test_manifest_ordering_does_not_move_the_digest`,
`test_digest_changes_when_only_the_manifest_changes`.

### 2026-09-07 — the twenty-eight, in five phases (this commit)
A read of the whole app produced twenty-eight findings. None were bugs: every
one was a place where the product could do something and had not been given
the surface to do it, or where it knew something and told nobody. Worked as
five phases, one commit each — `3284315` (buyer), `2bf60d2` (author and
agent), `a55ac7a` (extension), and this one (shell, and closing the trust
surfaces).

**The buyer's half** stopped at "here is a verdict, here are cards, here is a
print button". It now has the thing a buyer actually accumulates on a viewing:
a note per claim (`claim_notes`, its own table beside `claim_checks`), a
question sheet with a rail entry of its own — with no id it resolves to the
newest saved answer, which is what it should do on inspection day — progress
across `handled`, a compare that takes more than two, and an export that is
not paper.

**The author and agent half** was missing its consequences. Marks fed nothing;
refusals were invisible; a failed job could only be re-run by retyping it;
`/api/settings` had no screen; and authoring a pack — the thing the platform
exists for — was the one task with no door in the app. All five have one now,
and the marks half **closes B54**: `state.mark_signals` splits `wrong` (a
knowledge problem, feeding the research job the app already runs) from
`not_applicable` (a matching problem), and attributes the latter to the door
the subject came through. Derived, not curated: no review queue, nothing
waiting on a person.

**The extension** got a keyboard shortcut behind the same function as the
toolbar button, an options page for the one setting `apiBase()` has always
read from a key nothing could write, and two ways back into the app. Both
destination screens accept an id as a path segment, because `/api/focus`
refuses a query string on purpose.

**The shell** was doing none of navigation's non-visual half. A hash router
replaces one document's contents: no load event, so a screen reader is told
nothing, and focus stays wherever it was — in the rail, groups above the thing
that just appeared. There is a live region now (outside the keyed subtree: one
replaced in the same paint as its text announces nothing), focus moves to the
view on navigation and *not* on first render, and a skip control sits first in
the tab order — a button rather than `<a href="#main">`, because the app is
hash-routed and the standard accessible pattern would have navigated to "No
such view". Plus a palette on ⌘K/Ctrl+K and `?`, built from the same route
table the rail renders, and the only place in the app that says out loud that
a keyboard shortcut exists.

**The trust surfaces** were the three findings that turned out to be one:
`disputed` was folded inside a provenance `<details>` inside author mode — two
folds away from the reader whose decision it changes; `relevance`, `trust` and
`detection` were raw numbers with no scale; and nothing anywhere said why a
claim was *not* in a report. The badge is out of both folds, `rankingNote`
says the numbers in words before printing them, and `absenceNote` states the
one thing this project must never leave implied: silence is what the packs do
not hold, not a risk that has been ruled out.

Two pieces of housekeeping the pass turned up, both mechanisms rather than
edits. `--scrim` had to be added to *every* theme including the extension's,
which has no dialog, because `tokens.test.ts` holds each theme to the union of
aliases — half a theme paints elements with nothing. And
`ui/src/lib/NextStep.test.ts` sat beside `nextStep.test.ts`: two real test
files on this machine, one file on the Windows box this project is shipping
to, where a clone keeps whichever git wrote last and the other test silently
stops existing. Renamed to the convention the repo already used
(`NextStep.svelte.test.ts`), and `test_no_two_tracked_files_differ_only_in_
case` walks `git ls-files` so the next collision does not survive a review.

Gates at each phase: pytest rc=0, vitest 263 across 37 files, extension 68,
svelte-check 0 errors, bundle rebuilt and committed.

### 2026-09-07 — the reader's eight, and the loop back from the panel
A reader listed eight things wrong with the app. The interesting ones were not
bugs: they were places where the product could see but not be told anything.

- **The generated agent skill said "Cars (TR market)"** and little else. Traced
  to one literal in `packs/cars/pack.toml` — correct, in that the engine holds
  no category words — but the deeper fault was that the skill was *thin*: it
  named the loop and nothing an agent needed to run it, so an agent invented
  plausible identity keys. `src/app/agentskill.py` now derives all of it from
  the store: identity keys per subject kind (off `attributes.is_identity`, not
  the manifest), the pack's own domains and predicates, its holdings, its gap
  count, a runnable `research_brief(...)` example against a real claim-less
  subject, and every reason `app/findings.py` can refuse a finding. A second
  category gets its version for free; `test_the_skill_generator_types_no_
  category_words` walks the generator's source to keep it that way.
- **"See in app" opened a browser tab.** A page cannot raise a native window,
  so the route travels instead: the extension POSTs it to `/api/focus`, the
  engine prints `KRIKO_FOCUS <route>` on stdout, `tauri/` raises the window
  without ever parsing the route, and the SPA polls `/api/focus` and navigates.
  The tab survives as the fallback for a terminal-run server. The route is
  validated by a closed regex — it is the one untrusted input in the path.
- **Marking knowledge from the panel.** Every risk card asks "was this any
  use?"; the verdict goes to `claim_marks` in **`app.sqlite`**, never the
  engine store, so a reader's opinion cannot move a pack's `content_digest`
  and uninstalling a pack cannot erase it. `wrong` and `not_applicable` stay
  distinct because they name different halves of the system — bad knowledge
  versus bad matching — and that is the one thing no automated pass could
  infer from the claim row afterwards. The title is stored on the mark so the
  report still reads after the claim's pack is gone.
- **Researching a gap from the panel.** `/api/analyze` was returning claims
  with no identity at all, which is why the panel could describe a claim but
  never point at one. It now carries `claim_id`/`subject_id` per claim and a
  top-level `subjects` with each one's claim count; a subject that resolved
  with zero claims renders as a named, one-click-fillable gap rather than an
  empty state.
- **A succeeded job reported "done".** `jobs.py` overwrote the handler's own
  last word, which is how Research came to look like a dead button: it ran,
  wrote a full brief, and reported one uninformative syllable. It keeps the
  handler's message now, and `Brief.svelte` shows the artifact rather than the
  state — plus the sentence that Kriko searched nothing, on purpose, because
  that is the reader's actual question at that moment.
- **Knowledge was three screens.** Subjects, Coverage and Health were not three
  places, they were three questions about one list. One screen, four lenses
  ("what is here / missing / thin / what readers said"), nothing expanded
  until asked; the retired routes resolve to the lens that absorbed them, and
  keep the author gate they had.
- **A switched-off pack no longer reads as a missing one** on Connect, the
  screen where an empty generated skill was most misleading.
- Pack vocabulary that had crept into `ui/src/` is gone: the console spells its
  usage hint from `/api/identity-keys` rather than naming a category's fields.

Tests: 830 pytest, 195 vitest, 49 extension — all green.

---

### 2026-09-05 — the four bugs 0.3.1 shipped with (this commit)
A reader opened v0.3.1 and got 500s on most views, `[PYI-24700:ERROR] Could
not create temporary directory!` under "Does it actually run?", no way to build
a pack, and a lemon where the K should be. Four reports, three causes, all of
them things the test suite agreed with.

- **Every store-backed view 500s.** `sqlite3.ProgrammingError: SQLite objects
  created in a thread can only be used in that same thread`. FastAPI splits a
  sync generator dependency across the AnyIO worker pool — `__enter__` and the
  endpoint body are separate `run_in_threadpool` calls — so a connection is
  routinely used off the thread that made it. With one idle worker they
  coincide, which is why a sequential sweep of all 21 endpoints was green and
  the UI's `Promise.all` was not. `check_same_thread=False` plus per-request
  ownership; `sqlite3.threadsafety == 3` is what makes that sound.
- **…and then `database is locked`.** Surfaced by the new concurrency test on
  its first run: `connect()` ran `executescript(schema.sql)` and
  `PRAGMA journal_mode = WAL` on *every* connection, so every read was a writer
  taking an exclusive lock. Now: `busy_timeout`, a read before the WAL switch,
  and the schema applied only when `PRAGMA user_version` disagrees with a
  fingerprint of the schema text (`kriko.store.db.schema_stamp`) — fingerprint
  rather than a number because a hand-bumped constant is the step that gets
  forgotten, and `app.sqlite`'s schema has already grown once.
- **Verify killed the binary it was verifying.** `handshake()` launched the
  advertised command with `{"PATH": ...}` and nothing else. A PyInstaller
  onefile binary unpacks itself through `TEMP`/`TMP` before parsing an
  argument, so on Windows it died with PYI-24700 and the app reported it as the
  reader's configuration being wrong. `packaging/smoke_sidecar.py` had always
  used `os.environ | {...}` and was green on the same build — the divergence
  between the diagnostic and the product is what let it ship.
- **Nothing could be built or logged.** `Settings.packs_dir`,
  `Settings.analysis_log_path` and `pack_build`'s output were relative paths,
  which resolve against a working directory an installed app does not own —
  `C:\Program Files\Kriko` on Windows. Now anchored to the source checkout
  when there is one and `~/.kriko` when there is not, with
  `test_writable_paths.py` failing any future default that is relative.
- **A 500 now says what it was.** A local app has one reader, no terminal and
  no log viewer; "Could not load this view: 500" is not a bug report. The
  handler returns the exception type, the path and the last few frames, and
  `ui/src/lib/api.ts` carries them onto the screen.
- **The mark is the extension's K**, in the rail, the favicon and the taskbar
  tile, derived by `packaging/render_icon.py` and held to the extension's own
  toolbar icon by a role-per-cell comparison — the lemon was left over from a
  product this never was.
- **Buttons look pressable.** A lit top edge, a shadowed bottom one, a 1px sink
  on `:active`, one primary per view — the tokens live in every theme, so
  `tokens.test.ts` still holds.

### 2026-09-05 — an extension the app can actually install
Until now the extension shipped in the repository and nowhere else: a reader
with an installer had no way to get it, and the docs answered with `git clone`.

**Check → Browser extension** does the four things a native app is permitted to
do here — no browser lets an application install an extension, deliberately, and
`chrome://extensions` cannot even be opened from a command line, so the last
three steps stay the reader's.

- **Stage** — `POST /api/extension/stage` writes a loadable copy to
  `~/.kriko/extension/`. Beside the store, not inside the install directory: a
  browser holds an unpacked extension *by path*, and an install directory is
  replaced wholesale by the next installer, so staging there would silently
  uninstall the extension on every app update. Replace-never-merge, because a
  stale file the browser still loads is worse than a missing one.
- **Reveal** — opens the folder, best-effort, and returns the path either way.
  A box with no file manager is not worth a red banner when the path is already
  on screen and copyable.
- **Guide** — the load steps, with `chrome://extensions` and friends as
  copy buttons, because a browser will not open its own settings page on an
  app's say-so.
- **Verify**, which is the half that matters. There is no registration
  handshake and there should not be one; instead a middleware records
  `Origin: chrome-extension://<id>`, a header only a browser can stamp, sent as
  a side effect of the extension doing its actual work. So the page is a status,
  not instructions: it turns green on its own, and it cannot be green while the
  install is broken. One row per browser profile, since each install has its own
  id.

Two failures it now names that were previously invisible: a staged copy older
than the one the app carries (*Add again*, then Reload), and **port 8787 held by
something else** — the extension has no other address, so that install works
perfectly and reaches nothing, and the reader's instinct, reinstalling the
extension, never helps. The sidecar is the only thing that knows whether it won
that bind, so it now says so through `KRIKO_EXTENSION_BOUND`.

The extension rides inside the sidecar (`packaging/kriko-sidecar.spec` datas →
`app/extension_src`), and `smoke_sidecar.py` fails the build if it is missing —
the same class of silent packaging fault as the frontend, on the one page a
reader opens *because* they need help. `test_the_shipped_list_matches_what_the_
manifest_actually_references` reads `manifest.json` and checks nothing it names
was left behind, so adding a content script cannot ship a folder Chrome refuses
to load. NextStep gained `install-extension`, ranked above connecting an agent:
the extension is what the reader came for, the agent is maintenance.

### v0.3.1 — the palette and the extension, in an installer — 2026-09-05 (this commit)
A patch with two reasons: 0.3.0's installer opens looking like 0.2.6, and it has
no way to hand over the browser extension. The theme correction landed an hour after that tag was cut, and a fix nobody
can double-click is not a fix yet.

**The self-updater does not carry this one, and cannot.** 0.3.0 was built with
`TAURI_SIGNING_PUBLIC_KEY` unset, so `configure_updater.py` took the updater
plugin back out — those binaries have no update client compiled in and no
endpoint to ask. There is nothing to fix in 0.3.1 that would change that; the
missing half is in the already-shipped app. 0.3.1 is a manual download, and if
the signing key is set before its build runs it becomes the first release that
*can* update, with 0.3.2 the first update anyone receives. Ordinary for a
first-updater release, and worth writing down so the next session does not
read the empty `latest.json` as a bug.

### 2026-09-05 — the app opens wearing the extension's face (`2e45c31`)
S2 shipped a theme ported from `extension/colors_and_type.css` — a stylesheet
nothing loads. The extension has no HTML outside its test fixtures;
`manifest.json` injects `hover_lite/hover_lite.css` into a shadow root, and that
file is near-black `#0a0b0d` with a gold `#e8c04b` accent in IBM Plex, not cream
and lemon in Sora. The port was faithful to a dead file, and the default theme
was never switched, so 0.3.0 opens looking exactly like 0.2.6. The reader
noticed before any test did.

- `themes/panel.css` — ported from the live sheet, reusing slate's alias names
  so no component changed. It takes bare `:root` (slate gives it up), because
  whichever sheet holds that is what paints the first frame before JS runs — a
  blue flash then a fade to near-black is worse than either theme alone.
- `DEFAULT_THEME = "panel"`. A theme nobody selects is a preference, not an
  identity.
- IBM Plex Sans + Mono self-hosted, latin **and** latin-ext: the market is TR/EU
  and `ş ğ ı İ ö ü ç` live in latin-ext, so a latin-only subset would fall back
  to a system face mid-word.
- `test_the_app_wears_the_extension_palette` is the mechanism half — it reads
  ground and accent straight off `hover_lite.css` and fails when either window
  is restyled without the other. The one-off fix would have gone stale the same
  way the first one did.

Not in the 0.3.0 installer; the tag was already cut.

### v0.3.0 — the app you can actually set up — 2026-09-05 (this commit)
The five changes below, in an installer. A minor rather than a patch because
three of them are capabilities the app did not have: it can update itself, it
can wire an agent to its own store, and the extension and the app now know they
are the same product. The engine did not move — `kriko/` is untouched across all
five, which is G6 doing its job: every one of these is an interface change.

The release gate is unchanged and is still the only one that counts: does the
installer open on Windows, and does a check return claims. `desktop.yml` builds
it from this tag.

### 2026-09-05 — the usability pass, five specs (`ce79771`, `9516785`, `a14e664`, `3adc2cc`, this commit)
Five changes the app needed before anyone but its author could run it, taken one
at a time.

**S1 — self-update and a version surface.** The updater was configured but
unreachable; About now names the app version, offers the update, and lists each
pack's installed and offered version. Two clocks, neither waiting on the other.

**S2 — the theme is a file.** The extension's palette became `ui/src/styles/`
tokens plus one theme sheet per look, with `tokens.test.ts` failing the suite on
a colour literal in any other sheet. The extension's mark is the app icon.

**S3 — the extension and the app know about each other.** `/api/analyze` records
which door a run came in by (`origin`, a `Literal`, so an unknown one is a 422
rather than a row); the panel links to the stored result in the app; a refused
connection now says "Kriko is not running" instead of arriving as the same red
banner a 500 does — `fetch` rejects rather than resolves there, so the two are
only separable at the call site.

**S4 — connect an agent in one click.** `app/agentconfig.py` finds the four
harnesses on this machine, reports each as connected/stale/absent/unreadable
(*stale* is the load-bearing one: wired, but pointing at a different
`knowledge.sqlite`, which passes "is kriko in the config?" while being worse than
absent), and merges one key atomically. `app/agentskill.py` renders the research
protocol from the packs installed *right now*, so the protocol versions with the
knowledge rather than the binary. `POST /api/agent-verify` runs the advertised
command and completes an MCP handshake. Deliberately *not* the in-app terminal
that was asked for: this process listens on a port a browser extension also
talks to, and a run-what-the-caller-names route there is remote code execution.

**S5 — motion and guidance.** `ui/src/styles/motion.css` holds every animation
in the app, with `tokens.test.ts` failing on a raw duration or curve anywhere
else — the colour rule one axis over. Reduced motion now lands each animation on
its *end* state; the blanket `animation-duration: 1ms !important` it replaced
froze a skeleton mid-pulse. `lib/nextStep.ts` is a pure function from store state
to the one thing this installation is missing, in dependency order, silent when
there is nothing to say and with no "seen it" flag anywhere — the same reasoning
as `firstRun`.

**Found while doing it:** vitest defaults to `css: false`, which resolves every
CSS module to an empty string *by extension*, `?raw` included. `tokens.test.ts`
had been reading eight empty strings and passing every rule vacuously since it
was written. `css: true` in `vite.config.ts` fixed it and immediately surfaced
two real violations. The names-only guard did not catch it because
`import.meta.glob` yields its keys either way; it now asserts content too.

### v0.2.6 — the app that reads like an app — 2026-09-03 (81f0cb8)
The design pass below, in an installer. Nothing in the engine moved: the whole
diff is `ui/` plus its committed bundle, so this is the first build where the
gate is entirely "does it open, and does it read right" — the two questions
v0.2.4 and v0.2.5 were spent on separately.

### 2026-09-03 — the app design pass (`docs/superpowers/specs/2026-09-03-app-design-and-ia.md`)
Seven flat tabs became a grouped rail over one route table; the report leads with
a derived verdict and prints; the describe-it form stages what it asks for; first
run offers the pack index; two checks compare side by side. One design-token
sheet with a guard test that fails on a colour literal anywhere else — which is
the mechanism, not the cleanup: `#e5e5e5` in `.history` is the class of bug it
now catches. No Python diff, no new endpoint, no layer crossed.

### v0.2.5 — the app that panicked before it had a window — 2026-09-01 (053fa51)
v0.2.4 installed on Windows 11 and then did nothing at all when opened. Not a
blank window: no window, and no dialog — the panic went to a stderr a
double-click does not have.

    panicked at src\main.rs:303:10: failed to start Kriko:
    PluginInitialization("updater", "Error deserializing 'plugins.updater'
    within your Tauri configuration: invalid type: null, expected struct Config")

Two halves that were each individually right. `packaging/configure_updater.py`
removes `plugins.updater` from any build without a signing key — every fork,
every local build, and every release cut so far, since the minisign keypair was
never generated. `main.rs` registered `tauri_plugin_updater` on the *builder*,
where a plugin is initialized before `build()` returns and its failure lands in
`.expect("failed to start Kriko")`. Two guard tests existed on either side of
the gap (`test_the_committed_config_ships_no_updater` asserted the config has no
updater) and neither could see the other.

The plugin moves into `setup`, registered through `AppHandle::plugin`, whose
`Result` decides whether the update is offered at all — the same shrug
`offer_update` already gave a missing endpoint. Rule 2 of `main.rs`: a shell
that cannot check for updates still has to open.

**The mechanism**, because "the installers built" was never evidence that the app
starts — v0.2.4 was green on all three runners: `packaging/smoke_app.py` launches
the bundled shell, holds it 25s, and fails on a panic or an early exit. Wired
into `desktop.yml` after the bundler on Linux (under xvfb) and Windows; it
deliberately asserts nothing about *windows*, since a headless webview is a
flakier question than the one that broke, and macOS is skipped because a Tauri
binary run outside its `.app` is a different question there. Verified green on
both runners before the tag. Guarded in `test_desktop_update.py` so the step
cannot be quietly dropped for speed.

Also here: `.github/workflows/ci.yml` drops to `workflow_dispatch` while the app
is the loop (see CLAUDE.md's temporary section — the gate moves to the local
suite, it does not disappear), and B53 files the missing
`tauri/src-tauri/Cargo.lock`: `tauri-plugin-updater = "2"` floats, which is why
v0.2.1 opened and v0.2.4, four hours later, did not, on identical config.

### v0.2.4 released — mcp freezes without its cli extra — 2026-09-01 (6b63c3c, 20a4ffa)
v0.2.3's bundles failed identically on all three runners at the freeze step:
`collect_submodules("mcp")` walks the package by *importing* each submodule, and
`mcp.cli` raises "typer is required" when the `[cli]` extra is absent — which it
is in the sidecar's frozen environment. The exclusion now lives in
`packaging/freeze_imports.py` (`MCP_EXCLUDED_PREFIXES`, applied via
`collect_submodules`'s pre-import `filter=`), not in the spec, so
`src/app/tests/test_freeze_imports.py` can pin it — including a guard that the
spec never grows a second collection of its own. A widening now fails in pytest
instead of ten minutes into a release build; the smoke test's `--mcp` handshake
catches a submodule that went missing in the job that produced the binary.

**v0.2.4 is on GitHub Releases** with all four bundles (x64 setup.exe, amd64 .deb,
amd64 .AppImage, aarch64 .dmg) plus `packs.json`, `cars.kpack`, `drill.kpack` —
one download now carries the installer fixes *and* the agent path. Still unsigned
(no minisign key), so self-update stays inert.

### The install that failed, and the extension that could not find the app — 2026-09-01 (this commit)
A reader ran the v0.2.1 Windows installer and got "Error opening file for
writing: ...\kriko-sidecar.exe"; *Ignore* then produced an app that did not open.
Three distinct bugs behind one dialog, all fixed as mechanisms:

- **The orphan.** `src/app/sidecar.py` promised in its own docstring to die with
  its parent and did not. `--exit-with-parent` watches stdin, whose write end
  lives in the shell, so a crash — the case no `kill_engine` handler can cover —
  is an EOF. `kill_engine` additionally kills the *tree* on Windows, because
  PyInstaller onefile re-execs and the child is what holds the image.
  `installer.nsh` kills it in `NSIS_HOOK_PREINSTALL` for machines where one
  already leaked, and `offer_update` now kills before installing rather than
  after — on Windows the update *is* an NSIS run over the running sidecar's own
  file, unattended.
- **The invisible failure.** `start_engine` returned `Err` for a missing binary,
  and the boot page rendered it into a window that is created hidden. Every
  failure path now goes through `emit_failure`, which shows the window. A
  guard test asserts it, because "the app does not open" is the one outcome
  `main.rs`'s rule 2 forbids and the only one with no evidence.
- **The unreachable extension.** `extension/background.js` hardcodes
  `127.0.0.1:8787` because a page cannot be told a random port, while the
  desktop sidecar only ever bound an OS-chosen one. `uvicorn.Server.run` takes a
  list of sockets, so the sidecar serves both: the announced port for the shell,
  `EXTENSION_PORT` for the extension, skipped with a stderr line if taken. The
  number is one constant and a repo invariant compares it to the extension's.

And the other half of the same gap: **an agent had no address for an installed
app.** The research protocol was fully written down — the MCP tool set, and
`app/findings.py` refusing a quote it cannot find in the document — but
`.mcp.json` pointed at a source checkout, so a reader who *installed* Kriko had
a Research button producing briefs nothing could act on. `--exit-with-parent`'s
sibling `--mcp` runs the MCP stdio server out of the same binary against the
same store, and `/api/agent-config` generates the config block per machine
(frozen → the app's own path; a checkout → `sys.executable`, deliberately
*unresolved*, because `.venv/bin/python` resolves to a base interpreter with no
`fastapi` on its path — caught by running the advertised command in a test
rather than checking its shape). *Coverage → Connect an agent* shows it, and the
card above the gap list now says the free plane writes a brief rather than
gathering, because a button that returns instructions reads as broken otherwise.

Four new guards in the ordinary pytest suite (no Rust toolchain): the
`--exit-with-parent` flag must be spelled on both sides, `start_engine` must
reach `emit_failure`, the NSIS hook must kill the binary Tauri actually ships
with `/T`, and the extension's port must equal the server's constant. Plus two
real-subprocess tests: closing stdin ends the sidecar, and a taken extension
port is not fatal. 739 tests pass (one deselected: a root-owned `backend/` left by an old
Docker container, not this work).

### Two clocks: packs update themselves, and so does the app — 2026-09-01 (`1bf7af9` + this commit)
The store had carried `origin_url`, `version` and `content_digest` on every pack
row since the schema was written and nothing read them. Now `kriko/pack/
updates.py` decides (index parsing, version+digest comparison, the same
republished-version refusal `packstore.install` enforces — moved early enough
that it costs a comparison rather than a download), `app/packsource.py` fetches
and verifies, and `app/web/tasks.py:pack_update` installs through the ordinary
acceptance path. Checking is a request, updating is a job, both on the Packs
screen. CI builds every pack and publishes `packs.json` with tag-pinned asset
URLs. The app's own update rides Tauri's updater, whose minisign key is
independent of OS code signing — applied at build time so a tree without the
secret still produces installers.


## 2026-09-01 — Four installers, and the three bugs CI had to find first

`4bec392`, `165cff3`, `264551d`, `e27404d`. B52's build verification.

The desktop workflow ran for the first time (as PR #3 — `workflow_dispatch` is
unavailable until the workflow reaches the default branch). It failed three
times, and every failure was real:

- **The catalog was scanned in directory order.** `Path.glob` returns whatever
  the filesystem hands back, so `_find_make_model_for_part("k9k")` — a part
  fitted to both `clio_5` and `megane_4` — answered differently on CI than
  here, from identical data. That made every generated search query
  machine-dependent. All 11 unsorted scans under `src/` and `packs/` are sorted
  now, with `test_the_catalog_is_never_scanned_in_directory_order` walking the
  AST for the next one (`# any-order: <why>` to opt out).
- **Six files could not be checked out on Windows or macOS.** An unrelated GUI
  program wrote `imgui.ini` layouts into the repo root under non-UTF-8 names and
  a `git add -A` committed them. Both runners died in *checkout*.
  `test_every_tracked_path_is_checkoutable_on_windows_and_macos` applies
  Windows' rules to every tracked path.
- **`uvicorn.run(fd=…)` is POSIX-only.** Windows printed `KRIKO_PORT 58378` and
  never served it — precisely the failure reserve-then-announce exists to
  prevent. `uvicorn.Server(config).run(sockets=[sock])` passes the socket
  object, which needs no re-creation anywhere.

**Result**: `Kriko_0.1.0_amd64.deb`, `Kriko_0.1.0_amd64.AppImage`,
`Kriko_0.1.0_aarch64.dmg`, `Kriko_0.1.0_x64-setup.exe`. The sidecar extracted
from the shipped `.deb` passes the full smoke — handshake, health, frontend, a
real lookup, and a research job — so the artifact contains a working engine and
not just a binary that links. Unsigned, and no human has opened the window yet:
both are B52.

---

## 2026-09-01 — The frozen sidecar, proven (and a wheel bug it found)

This commit. B52 verification work.

- **`packaging/freeze.sh`** builds the sidecar with PyInstaller and immediately
  smokes the binary, so the class of failure that only exists in a build — a
  missing hidden import, an undeclared data file — has a local reproduction and
  a name. No Rust toolchain needed; it stops short of the Tauri bundle.
- **`packaging/smoke_sidecar.py` now goes past liveness**: a real
  `/api/lookup`, a `POST /api/research` that must return a job id, and that
  job reaching `done` in state `failed` *without* `ModuleNotFoundError` in its
  log. It runs the binary in a temp directory with `KRIKO_STORE` /
  `KRIKO_APP_STATE` redirected — a lookup that passes only because the
  developer has the cars pack installed proves nothing.
- **The bug it found on the first run**: `kriko/store/schema.sql` is read from
  disk at every `connect()`, and `pyproject.toml` declared only
  `app.web/static`. The frozen binary answered `/api/health` and 500'd on the
  first query with `FileNotFoundError`; **a non-editable `pip install` was
  broken the same way** and no test could see it. Fixed in `pyproject.toml`,
  in the spec's `datas`, and generalised: 
  `test_every_data_file_under_src_is_declared_as_package_data` walks `src/`
  for non-`.py` files and fails on any that `package-data` does not cover.
- **A frozen build has no `packs/`**, so `tasks.pack_build` now turns
  `ModuleNotFoundError` on `packs.<name>.build` into a message that says to
  build the pack from a checkout and install the `.kpack`, instead of a
  traceback.

---

## 2026-09-01 — The standalone app, phases 2–5: advice, jobs, and a desktop shell

`127ec40`, `54c2ecf`, and this commit. Spec:
`docs/superpowers/specs/2026-09-01-standalone-app-ui-design.md` (B52).

- **Phase 2 — a result reads as advice** (`127ec40`). One `/api/lookup`
  response, two renderings, and the split lives entirely in the frontend
  (`ui/src/lib/mode.ts`, `report.ts`, `Report.svelte`): no request carries a
  mode and no endpoint branches on one, so the engine cannot grow a second
  answer shape to keep in sync. The buyer report inverts the engine's
  `(-relevance, severity, title)` order to consequence-first, groups by the
  pack's own `domain` strings without enumerating any of them, and turns
  `advice` into "what to ask". Triage checkmarks live in `app.sqlite` and are
  deleted with their lookup.
- **Phase 3 — the JSON textarea is gone** (`127ec40`). `Check.svelte` takes a
  pasted URL; an unreadable host answers with which sites the packs *can* read,
  from `/api/adapters`. The guided form is built from
  `/api/identity-keys/{pack}` and the pack vocabulary at runtime, names what is
  still missing rather than failing on submit, and autocompletes off installed
  subjects.
- **Phase 4 — nothing in the data path is terminal-only** (`54c2ecf`). This is
  the commit that closes G6's delivery constraint. A `jobs` table in
  `app.sqlite`, a single-worker runner (`app/web/jobs.py`), the two handlers in
  `app/web/tasks.py`, `POST /api/research`, `POST /api/packs/build`, SSE over a
  poll of the row with a polling fallback in the client, and cooperative
  cancel. Rows first, thread second: a process that dies leaves `interrupted`
  jobs, not rows that claim forever to be running. `submit_findings`'s
  grounding and gate logic moved to `app/findings.py` so a browser-started job
  and the MCP plane share one acceptance path — provenance must not depend on
  which door a claim came in.
- **Phase 5 — the desktop shell.** `src/app/sidecar.py` binds an OS-chosen port
  and prints `KRIKO_PORT <n>`: the child picks the port because a parent that
  finds a free one has already lost it by the time the child binds.
  `tauri/src-tauri/` spawns it, polls `/api/health`, shows a hidden window only
  when healthy, renders the captured stderr when not, and kills the child on
  close *and* on exit — an orphaned uvicorn holds the WAL lock and breaks the
  next launch. `packaging/kriko-sidecar.spec` freezes it;
  `.github/workflows/desktop.yml` bundles unsigned installers on three
  runners.
- **Verified here, and not.** 690 pytest, 55 vitest, svelte-check clean; the
  sidecar handshake and orphan-free exit are real subprocess tests, and
  `packaging/smoke_sidecar.py` passes against a live server. **The installers
  were never built** — there is no Rust toolchain on this machine. That is
  what is left of B52.
- **Counts**: 690 pytest (from 668), 55 vitest (from 32), 36 node.

---

## 2026-09-01 — The standalone app, phases 0–1: a Svelte frontend that remembers

Thirteen tasks, `c4b3b8b`..`1170e13`. Spec:
`docs/superpowers/specs/2026-09-01-standalone-app-ui-design.md`; plan:
`docs/superpowers/plans/2026-09-01-standalone-app-ui-phase-0-1.md`.
The 443-line `app.js` control plane is gone. `ui/` is a Svelte 5 + Vite +
TypeScript app built into the committed bundle at `src/app/web/static/`, and a
lookup now has a URL that survives a reload.

- **Phase 0 — parity** (`c4b3b8b`..`05c5ba3`): all seven views ported behind a
  hash router, so the back button and a linkable view work for the first time.
  A typed client (`ui/src/lib/api.ts`) replaces fifteen `innerHTML` string
  builders; loading, error and empty are three visible states rather than a
  blank div. Ask still builds its form from `/api/identity-keys` and the pack
  vocabulary — asserted by a test now, not just by convention.
- **The invariants are mechanisms, not rules** (`f563edc`): a grep fails when
  pack vocabulary appears in `ui/src/`, and a CI job rebuilds and diffs the
  committed bundle so a stale one cannot ship. Both were verified by injecting
  the violation they exist to catch. `ui/package-lock.json` is committed so the
  diff is reproducible.
- **Phase 1 — persistence**: `src/app/web/state.py` over `~/.kriko/app.sqlite`,
  deliberately *not* the engine's `knowledge.sqlite` — uninstalling a pack must
  not drop your history, and a history row must not affect a `content_digest`.
  `/api/lookup` and `/api/analyze` return a `lookup_id`; `/api/lookup/{id}`
  reopens it; `/api/history` lists and `DELETE /api/history/{id}` forgets. The
  JSONL analysis log is untouched — it is the parity corpus, not the UI's
  memory.
- **Counts**: 668 pytest (up from 655), 32 vitest, 36 node.

---

## 2026-08-31 — Knowledge-tree observability: reading the evidence back out

Six tasks, `9903083`..`bd72788`. Spec: `.superpowers/sdd/2026-08-31-knowledge-tree-observability/`.
Kriko can now answer "how well supported is this claim" as well as "what is
missing" — `weakest_claims()`/`subject_tree()` in `src/kriko/lookup/tree.py`
report four signals (contradiction, corroboration, best-source trust,
staleness) separately, ordered lexicographically, never collapsed into a
score.

- **Task 1 — `kriko/lookup/tree.py`** (`11b21c7`, `e2544fe`): `weakest_claims()`
  and `subject_tree()`, `ClaimHealth.concern` as the public sort key, reusing
  `rank.py`'s `tier_lookup`/`trust_lookup`/`tier_of` rather than re-resolving
  trust. Claims with no evidence are excluded from `weakest_claims()` (that's
  the coverage report's question) but stay visible in `subject_tree()`. An
  absent `retrieved_at` sorts last, not first.
- **Task 2 — producers write `retrieved_at`** (`d1935bf`, `2fce7bf`): the
  ledger exporter from `documents.fetched_at`, `packs/cars/build.py` from the
  source dict, `src/app/mcp_server.py` from the submission time. Nothing was
  backfilled — the 193 legacy sources stay blank and render as "unknown".
- **Task 3 — `GET /api/health/weakest` and `GET /api/health/subject/{id}`**
  (`39dded3`): `src/app/web/routers/health.py`, read-only, serialising through
  `tree.py`'s `health_json`/`tree_json`. Renamed the web app's inline
  liveness closure `health()` → `liveness()` so it stops shadowing the
  imported router module.
- **Task 4 — MCP tools** (`ecfa9ea`): `subject_health(subject_id, pack_id="")`
  and `weakest_claims(pack_id="", limit=20)` in `src/app/mcp_server.py`, after
  `coverage_gaps`.
- **Task 5 — dashboard Health tab** (`bd72788`): `src/app/web/static/`.
- **Task 6 — this doc/backlog pass**: `docs/ARCHITECTURE.md`,
  `docs/INTERNALS.md`, `README.md` updated; backlog items **B45**–**B49**
  filed (published_at never written, independent always 1, no producer emits
  refutes, health signal not yet fed into ranking, and `rank.py`/`tree.py`
  disagreeing on what "independent" means). 650 tests passing.

---

## 2026-08-31 — Decontamination and packaging: seven tasks, then a review pass fixed what it found

Seven tasks, `ac685a1`..`122b54e`, plus a follow-up review round
(`9832643`..`7c3a687`) and this pass's own fix wave (see below). Kriko becomes
`pip install`-able and the engine's own prose and tests stop leaking cars.

- **Task 1 — `src/` layout and `pyproject.toml`** (`ac685a1`): `kriko/` and
  `app/` moved under `src/`; `packs/` and `extension/` did not move.
  `pyproject.toml` makes an editable install (`pip install -e ".[dev,pipeline]"`)
  the supported way to set up the repo. `cadd33b` made the layering-guard scan
  roots self-checking (they no longer silently pass if a path stops existing).
- **Task 2 — the docs map** (`641b4b2`): pre-pivot planning documents moved to
  `docs/historical/`; `CLAUDE.md`'s documentation map states current vs.
  historical for every doc.
- **Task 3 — README rewritten** (`11cb189`): for someone who has never seen
  the project; every command in it verified to run.
- **Task 4 — the domain-free gate learns to read prose** (`09fddfa`,
  `844f670`): `test_core_is_domain_free.py` gained `_prose_offences`, scanning
  docstrings and comments (not just executable positions) against a narrower
  `PROSE_BANNED` list, with an `ALLOWED_PROSE` allowlist for deliberate
  category examples. It failed immediately, as designed — see Task 5.
- **Task 5 — the engine's prose decontaminated** (`343a591`): the offences
  Task 4 found, fixed — generic mechanisms restated without pointing at
  `packs.cars.pipeline.*` by module path.
- **Task 6 — the archaeology removed, repo-wide** (`122b54e`): ~66 "the old
  pipeline"/pre-pivot narrative references deleted from active documentation.
- **Task 7 — the engine's own tests stop proving generality with cars**
  (`91c82c8`, `ac4f98a`, `11c8b6f`): `src/kriko/tests/` fixtures moved from
  car vocabulary to `packs/drill/`'s (brand, model line, battery platform,
  charge cycles) — the deliberate car-shape falsifier, no engine/fuel/
  displacement. Two review rounds followed: round 1 fixed a fixture swap that
  had silently stayed within the cars category (Toyota/Corolla, same keys,
  same site) and rescaled car-magnitude numbers that had only been relabelled
  (a torque field carrying Mégane's displacement_cc, a "charge_cycles" field
  carrying model years); round 2 fixed an invented pack term
  (`chuck_type` — the pack declares `chuck_size_mm`) and reconstructed
  `test_range_bounds_disambiguate_identical_digit_patterns`, whose fixture no
  longer demonstrated its own name after the rescale.
  **Known coverage loss, accepted, not fixed:** the original test disambiguated
  two *different*, independently-plausible readings sharing one digit-grouped
  format (`"1.461 Nm"` a plausible torque, `"148.000"` a plausible mileage,
  same dot-grouping, decided only by which field the label put it in). Drill's
  magnitude profile (torque ~1–200, charge cycles ~0–2000) has no such pair —
  any dot-grouped integer plausible for one field is implausible for the
  other — so round 2's replacement demonstrates accept/reject on one shared
  value instead: `"1.200"` fed to both fields, believed as `charge_cycles`
  and correctly absent from `max_torque_nm`. That is a real demonstration of
  "range bounds decide," but the "two mutually plausible values, identical
  format" case is no longer covered by any test. Filed as **B41** (below).
- **Review-round fix (this pass) — the Critical and four Important findings**
  from the branch review: `DEFAULT_STORE` renamed from
  `packs.cars.pipeline.sqlite` (a leftover of a mangled rename) back to
  `knowledge.sqlite`, with a non-destructive one-time stderr warning when
  another `*.sqlite` file sits at the default location — never auto-selects
  or migrates either file; the gate gained plural stemming (`cars`,
  `vehicles`, `gearboxes`, `models` now match their singular BANNED entries)
  and the 7 offences that found were fixed or allowlisted; every doc except
  the README was swept for pre-`src/` paths, with every `docs/ARCHITECTURE.md`
  anchor re-verified against the actual function (three had drifted
  independently of the move); CI and CONTRIBUTING.md's claim of a
  Dockerfile-invariant test that does not exist was corrected; this `done.md`
  entry and backlog items B40–B44 (below) were added.
- Along the way: `2f0d061` fixed a real pre-existing bug Task 7's rewritten
  test found by actually exercising its branch —
  `component_part_meta`'s power-collapse `meta = {...}` sat one indent level
  too deep, inside the ambiguous-identity branch after its `return None`, so
  every reference to `meta` in the reachable power-collapse path raised
  `UnboundLocalError`. The old test's premise (`k9k` has no exact part file)
  had gone stale once a real `k9k.yaml` was added, so it always took the
  earlier exact-match return and never reached the buggy code — green suite,
  unguarded branch, for however long that had been true. Fixed and reapplied
  to confirm: broken code reds the rewritten test, the fix greens it. A
  sibling of the same bug shape is filed as **B40** rather than
  guessed-and-fixed (below).

## 2026-08-30 — Simplification and readability pass: 14 tasks, gates.py rewired then deleted

Fourteen tasks, `aa61266`..`63d2466` (docs) plus this entry. The plan's own
baseline number was wrong at the start — `pytest.ini` already sets `-q`, so a bare
`pytest -q` passes it twice and pytest drops the "N passed" summary line, so
nobody had actually read the count before writing 610 into the spec; caught by
the Task 1 implementer (`6dbf196`) and corrected to the real baseline, 594. Ends
this task at **601 passed**, with `.venv/bin/python -m pytest -o addopts="" -q`
as the invocation that actually prints the count.

- **Task 1 — the `title_sim` fork deleted** (`34424bb`): a pack-local copy of
  engine title-similarity logic, removed in favour of calling the engine
  directly. The warm-up task, and the pattern every later collapse in this pass
  follows: a pack may import the engine, so a pack-local reimplementation of
  engine logic is never justified.
- **Task 2 — the chunking fork collapsed** (`e05508b`): `packs/cars/pipeline/ledger/chunking.py`
  duplicated the engine's chunker and lexicon, adding only cars'
  `code_tokens()` detector. Chunking itself moved to `kriko/ledger/chunking.py`;
  the pack now injects its own signal policy rather than owning a copy of the loop.
- **Task 3 — the ingest fork collapsed** (`637b3f6`, `9fb8171`): `packs/cars/pipeline/ledger/ingest.py`
  (172 lines) differed from the engine's `kriko/ledger/ingest.py` (168 lines)
  in exactly three ways — a `Document` type hint, source-trust policy, and a
  cache-dir mapper. One ingest now lives in the engine with cars' source policy
  and claim mapper injected (`backfill_cache_dir` takes an injected mapper).
- **Task 4 — the extraction fork collapsed** (`8f75136`, `0343f27`): the
  largest of the five forks. `packs/cars/pipeline/ledger/extraction.py` (122
  lines) reimplemented the engine's chunk loop, cache check, budget charge and
  evidence insert. One extraction loop now lives in `kriko/ledger/extraction.py`;
  cars supplies langextract as the extractor, the code-token chunk gate, and its
  low-value-claim rules. The extraction-policy splat and dead re-exports it left
  behind were dropped in the same task.
- **Task 5 — cars' low-value rules became pack rows** (`e85f11b`, `f260d34`):
  `packs/cars/vocabulary/gates.yaml` already declared cars' gate vocabulary as
  rows and `kriko/gates.py` already evaluated it, but the extraction path still
  read Python frozensets instead of the pack's own rows. Fixed, plus a real bug
  found in the process: `_vocabulary()` did not fail open on a mis-shaped
  `gates.yaml` (would raise instead of degrading).
- **Task 6 — the engine learns the structural gate rules** (`367e62f`):
  `packs/cars/pipeline/agent/gates.py` held rules that are not vocabulary and so
  could not become rows — a title-length limit, a rationale-length minimum, and
  the config-specificity anchor rule. `kriko.gates.structural_reasons` now
  expresses these three as rule shapes the engine evaluates; the pack keeps
  only the numbers (its `limits` rows). The orphan's other two rules — a
  DTC-code shape check and a minimum-evidence threshold — were not ported; see
  `docs/USAGE.md`'s "Removed, not currently enforced" and backlog B34.
- **Task 7 — the gate wired into the agent write path, behaviour changed on
  purpose** (`2a88372`, `2ea068b`, `40daf3f`, `73ec95f`, `ac4579a`):
  `app/mcp_server.py:submit_findings` previously checked only that the quote
  appears in the document — the 243-line `check_evidence` gate ran nowhere in
  the live agent path. Now it does. Restoring it broke the `covered`/`generic`
  specificity escapes (a claim naming a real config detail was being rejected as
  generic); fixed by adding an `exempt` vocabulary category, then narrowing
  `exempt` to waive only `covered` (matching the original scope, not the wider
  one a first pass gave it — the `docs/USAGE.md` sentence describing this was
  still wrong until Task 14 fixed it, below). The
  gate-calibration guard was rebuilt and immediately found a real regression.
  `submit_findings`'s docstring was updated to tell agents to send `component`
  so the specificity check has something to anchor on (grew the function to 155
  lines — filed as backlog B37). Two of the deleted `gates.py`'s three public
  functions were not ported — filed as backlog B34 (see below) rather than
  silently dropped.
- **Task 8 — the pack contract written and tested** (`8b1238b`): `packs/drill/`
  is five YAML files, `packs/cars/` is 12,900 lines, and nothing stated which
  parts are required of either — a third-party pack author had two examples
  that disagreed. A contract doc plus a test now state what every pack must ship.
- **Task 9 — dead-code deletion found nothing to delete** (`2746830`): the task
  assumed `packs/cars/pipeline/catalog/model_state.py` was unreferenced, from a
  grep for the dotted import path. That grep cannot match
  `from packs.cars.pipeline.catalog import model_state`, the form its eleven
  tests actually use. Re-run correctly (all import forms, no test-directory
  filter, entry-point and doc-mention detection), the repo has zero dead
  modules. Recorded so the wrong grep is not repeated (see `CONTRIBUTING.md`'s
  new "Checking for dead code" section and the plan doc's Task 9 write-up).
- **Task 10 — `packs/cars/build.py`'s `build()` split** (`1d3b450`): 457 lines
  became a sequence of named stages, longest 65 lines.
- **Task 11 — `kriko/pack/build.py`'s `build()` split** (`d72cfa4`): 300 lines
  became a sequence of named stages, longest 28 lines. This one mattered more
  per line — it is the engine's, so every pack author reads it.
- **Task 12 — the flat drawer grouped** (`1d16149`): `packs/cars/pipeline/` held
  14 loose modules beside 6 tidy subpackages; regrouped so the directory listing
  says what is what.
- **Task 13 — a reading map written** (`886d309`, `63d2466`): a page making the
  tree investigable without reading it all first; one bug in the extension
  request path found and fixed while writing it.
- **Task 14 — this entry.** Repo tidy: `deploy/` (stray untracked `.env` +
  pytest cache, never git-tracked) deleted; `docs/INTERNALS.md`'s "Knowledge
  Plane: Pipeline" section rewritten end to end — it still described the
  pre-ledger `extract.py`/`dedup.py`/`judge.py`/`promote.py` design, all four
  either moved or replaced by the ledger's `acquire.py` -> `resolve.py` ->
  `verdict.py` -> `export.py` -> `parity.py` stages well before this pass; every
  `knowledge/`-prefixed path in it repointed to `packs/cars/pipeline/`.
  `docs/USAGE.md`'s low-value-rows bullet fixed — it read as though the recall
  exemption also waived the warning-light rejection, but `exempt` only waives
  `covered` (Task 7 confirmed this in code; the sentence just described it
  wrong). Six items this pass surfaced but did not fix are filed as B34-B37 and
  Human Decisions #8-#9 in `backlog.md`.

## 2026-08-27 — Phase 6a of the pivot: backend/ deleted, catalog into the pack

Commits `e5d7951` (code) and this one (docs + one engine bug). Suite 534 -> 536,
and 3 minutes -> 16 seconds now that nothing starts Postgres.

- **`backend/` and `deploy/` deleted** — sync ETL, SQLAlchemy models, the
  650-line resolver, matcher, normalize, recover, equipment, the FastAPI api,
  the Dockerfile and compose stack. Every one has a successor from Phases 1-5.
  `ops/{hub,mcp,reports,swap.py}` went with them.
- **The car catalog moved** to `packs/cars/data/`, and every reader was
  repointed rather than left to guess.
- **`ops/reports/coverage.py` -> `packs/cars/coverage.py`.** Its one engine
  dependency went away with it: it imported `SERVABLE_STATUSES` from the deleted
  resolver, and now derives servability from the pack manifest's
  `[status_confidence]` table — the same authority `build.py` uses, so the
  report and the builder can no longer disagree about what "servable" means.
- **Layering re-derived**, not renamed: the column (`ops -> backend ->
  knowledge`) became a fan (`apps -> kriko <- packs -> knowledge`, with `ops`
  driving). Four invariants enforced in `test_repo_invariants.py`, plus a
  ratchet asserting `backend/` stays deleted — a package deletion is easy to
  undo by accident.
- **`README.md` and `CLAUDE.md` rewritten** for the pack architecture. Every
  command in the README was executed before being documented, which is how the
  next two items were found.

Two bugs the smoke test found, neither of which any unit test could have:

- **`python -m apps.web` did not exist.** `app.py`'s own docstring and the
  README both document the package form; only `python -m apps.web.app` worked.
  Added `apps/web/__main__.py`.
- **A contradicting identity attribute was silently dropped once the candidate
  set was down to one** (`kriko/lookup/match.py`). Narrowing was skipped at
  `len(candidates) <= 1` as an optimisation — but narrowing is also how a
  contradiction is *detected*, so the skip made the most confident-looking case
  the only silent one. Live effect: a Sahibinden ad for a 1.6 TDI Golf 7 saying
  "Otomatik" resolved `exact` onto the sole manual variant, returned **zero**
  gearbox claims, and raised no flag — the quiet zero G3 exists to prevent. Now
  flagged `soft_narrow_fallback:transmission`. The fix can only add flags, never
  change which subjects match, which the 98-row parity golden confirms.

  The missing 1.6 TDI DSG catalog row is deliberately **not** patched: per the
  generalization principle a per-model fix does not exist, and the gap is now
  visible to B19's loop instead.


## 2026-08-26 — Phase 0 of the knowledge-engine pivot: demolition

First commit of goal **G6** (see `backlog.md`). Baseline established at 768 passing,
then 12 files and ~1,500 LOC removed; suite 768 -> 741 (27 tests deleted with their
modules) and 52s faster.

- **`ops/auto.py` (635) deleted.** The legacy curated-YAML pipeline. The ledger flow
  (`acquire -> ingest -> extract -> resolve -> cluster -> verdict -> export`) is the
  one pipeline now. Its only importer was `ops/tests/test_auto_cap.py`.
- **`knowledge/discover.py` (532) deleted.** A Textual TUI for approving YouTube
  sources by hand — a human in the data path, which G5 forbids. Its only importer was
  `ops/auto.py:272`; the two went together.
- **`knowledge/ledger/feeds/` deleted** (nhtsa, safety_gate, recalls_tr, `__init__`)
  plus three tests, plus the `feeds` stage unwired from `ops/ledger_run.py` — its
  argparse flags (`--feed`, `--make`, `--model`, used by nothing else), the
  `_cmd_feeds` body, the dispatch entry, and its slot in the `all` sequence.
  B17 had already dropped the whole recall-feed effort.
- **`add_car.sh` and `scripts/run_local.sh` deleted** — superseded onboarding and
  serving wrappers.
- **`knowledge/gold/gold.yaml` restored.** It was deleted in the working tree but
  still live-referenced by `langextract_client.py:36` and `eval_verdict.py:16`; three
  tests were failing on it. It is car-specific few-shot data and moves to
  `packs/cars/research/few_shot.yaml` in Phase 4.

Checked rather than assumed: deleting `auto.py` does **not** lose part-stub creation.
`_ensure_part_stub` was only its caller — `generate_part_scaffold` stays in
`knowledge/parts/search_templates.py`, `export.py:409` fails open and holds claims
back when a stub is missing, and `ops/remediate.py`'s `missing_part` finding acts on
it. That is B19's loop, which was supposed to own this anyway.

Deferred out of Phase 0, with reasons: **`deploy/` stays** until
`test_repo_invariants.py:124` is retargeted — it reads `deploy/Dockerfile` to enforce
that the serving image never pulls in `mistralai`/`langextract`/`exa-py`, an invariant
that matters *more* once `kriko/pipeline/` and `kriko/lookup/` are siblings.
**Postgres stripping stays** because `backend/` is the parity reference until the old
path is deleted. **`logs/` stays** — `analyses.jsonl` is the source of the parity
corpus Phase 4 depends on.

Docs updated rather than left dangling: `README.md` and `docs/USAGE.md` now show
`ops.ledger_run acquire` + `ops.ledger_run all`; the 23-line YouTube-TUI section is
gone from `USAGE.md` with headings renumbered; `docs/INTERNALS.md` marks the
curated-YAML path legacy and names the live flow.

---

## 2026-08-22 — Refactor pass: delete the archaeology, derive the hand-lists

Seven commits (`dfe2469`..`0caaa64`). ~1,100 lines removed, suite 765 -> 768
(14 obsolete tests deleted, 17 added). Every phase verified with the full suite
before the next started.

- **854 LOC of spent code deleted** (`dfe2469`). Six one-shot migrations whose
  transform already ran on the checked-in YAML (`migrate_v3`, three `backfill_*`,
  `add_part_code`, `strip_fitment_field`) and three zero-reference source modules
  (`sources/forums.py`, `recalls.py`, `specialists.py`). Kept deliberately:
  `doctor.py`, `repair_missing_stub_scaffold.py`, `ops/swap.py`,
  `ledger/parity.py` — standing tools, not spent migrations. `swap check` is a
  documented acceptance gate.
- **`reclassify_maintenance.py` -> `knowledge/maintenance.py`** (`c2b4695`),
  341 -> 259 LOC. Its name and location both misdescribed it: a domain rule, not
  a catalog migration. Stripping the human-sign-off CLI (a path G5 forbids) also
  orphaned `argparse`, `pathlib`, `yaml`, `REPO_ROOT`, `PARTS_DIR` and
  `SERVABLE` — the module now takes a dict and returns a dict.
- **Duplication consolidated where it was real** (`bc4aa6a`). `catalog_models()`
  and `VARIANTS_DIR` (byte-identical across three feeds), `_model_part_hint`
  (identical in two of three), and `PSEUDO_PART_CODES` (four definitions -> one
  in `catalog/registry.py`). **Five other "duplicates" were left alone** and the
  reason recorded at the shared definition: `_now_iso` emits different formats,
  `_http_get` differs by `follow_redirects`, `_doc_text` is three different feed
  schemas, and nhtsa's `_model_part_hint` uses a different algorithm. The grep
  found name collisions, not copies.
- **Onboarding data left Python** (`c647b8e`). `_WIKIPEDIA_ARTICLE_TITLES` (15
  models) and `_ENGINE_ALIASES` moved to
  `knowledge/catalog/wikipedia_articles.yaml`. These genuinely cannot be
  catalog-derived — `discover.py` runs *before* a model has a catalog row and
  exists to create one — so the fix is data, not derivation. The YAML header
  says so, to stop the next reader "fixing" it.
- **`ops/hub/web.py` 1151 -> 831** (`de6202a`), into `textfmt.py`, `agents.py`,
  `claimview.py`. **The planned six-router split is not possible**: endpoints
  read `DATA_DIR`/`RUNS_LOG`/`CLAIM_SIGNAL_LOG`/`AGENT_RUN_LOG` from module
  scope and `test_hub_web.py` patches them via `monkeypatch.setattr(web, ...)`.
  A function resolves globals from the module it was *defined* in, so moving an
  endpoint detaches it from the patch — `/api/models` would read the real
  catalog instead of `tmp_path` and still return 200. Only helpers reading no
  patched global moved; `web.py` re-imports them so every call site and patch
  still resolves. Verified by diffing the 28-route table before and after.

**Two latent bugs surfaced by the dedup pass and fixed separately:**

- **`_default_aftertreatment` drift** (`bf8590c`). Two copies: `backend/sync.py`
  returned `"none"` for a euro4/euro5 diesel, `write_variants.py` returned
  `None`. The dangerous part was *which* was tested — `test_scr_gate.py` covers
  sync's version, but grep shows sync **never calls it**; `write_variants.py:477`
  was the sole production caller, running the untested, divergent copy. A euro5
  diesel was written with no aftertreatment, `_scr_compatible` fails open on
  falsy, and an AdBlue/SCR claim could surface on a car with no SCR hardware.
  Now one implementation in `knowledge/catalog/emissions.py` (knowledge layer,
  because `backend/` may import it but not the reverse), plus a Dockerfile COPY
  line the invariant test demanded.
- **`_SHARED_CODES` stale** (`0caaa64`). Listed clio_5 and golf_7; megane_4 had
  its part files and variant codes but no entry, so regenerating it would have
  dropped `electrical_code`/`body_code` from every row. Now derived from
  `backend/data/parts/{electrical,body}/`, the same pattern
  `catalog_code_manufacturers()` uses.

Both bugs are the failure mode `docs/design_flaws.md` Flaw 1 records for
`SIBLING_CODE_FAMILIES`: a hand-maintained list that drifted. Both fixes make
the *class* impossible — one asserts function identity, the other asserts
`_SHARED_CODES` never returns.

---

## 2026-08-21 — CI, contributor protocol, structural invariants

No `.github/` existed: nothing verified a branch before merge.

- **The documented test command was wrong.** `python -m pytest backend knowledge`
  in the README collected **576 of 761** tests once `ops/` existed — every
  `ops/tests` file skipped, silently, without failing. Root cause: no pytest
  config at all, so collection depended on which directories you named.
  `pytest.ini` now pins `testpaths`; the README says to run `pytest` bare.
- **The layering rule became a test, not a CI script.** Duplicating the greps
  into CI would let them drift from `CLAUDE.md`.
  `ops/tests/test_repo_invariants.py` fails if `knowledge/` imports from
  `backend/` or `ops/`, if `backend/` imports from `ops/`, or if a package with
  tests is missing from `testpaths`. Each was verified to **fail on an injected
  violation** — a guard that cannot fail is not a guard.
- **CI** (`.github/workflows/ci.yml`): the suite with no secrets (verified: all
  761 pass in a stripped environment), the node tests, and a `docker build` that
  imports the serving app inside the image — covering the breakage class the
  suite structurally cannot see.
- **Templates**: PR template checks the CLAUDE.md principles; the claim-quality
  issue template asks which value bar the claim failed.
- **`CONTRIBUTING.md`**: branches, the commit convention already in the history,
  the test gates, the layering rule.
- Stale references refreshed: README architecture + file layout predated `ops/`;
  `knowledge/requirements.txt` still cited `judge.py` (deleted) and the old
  `knowledge/hub`, `knowledge/mcp` paths.

765 pytest (761 + 4 invariants), 23 node.

**CI is two jobs, ~3 min/push.** The docker-build job was dropped after the fact:
the repo is private so Actions minutes are billed, and the build was 3-5 of ~10
minutes per push. Its value is preserved statically —
`test_dockerfile_copies_every_knowledge_module_the_serving_path_imports` computes
the transitive closure of `knowledge/` imports reachable from `backend/` (12 files
today) and asserts `deploy/Dockerfile` copies each. Verified by deleting the
`title_sim.py` COPY, which is the near-miss that happened for real during the
refactor. It does not replace a build — a broken `pip install` or bad base image
still needs one.

**Open, not fixed here:** `package-lock.json` is gitignored, so CI uses
`npm install` rather than `npm ci` — no reproducible install. And `README.md`'s
onboarding step still says "human fills in per-market hp/years", which contradicts
the automation principle in `CLAUDE.md`.

---

## 2026-08-21 — Codebase organisation: five phases, backend/knowledge cycle broken

Spec: `docs/superpowers/specs/2026-08-21-codebase-organisation-design.md`.
Baseline before: 760 passed / 1 failed, 52 dirty files, 463 tracked files.
After: 761 passed / 0 failed, clean tree, 310 tracked files.

- **Phase 1 — dirty tree committed** in six coherent commits: source tiers,
  component registry, part YAML v3, serving payload v2, hover_lite v2 rendering,
  hub picker. The pre-existing test failure was a harness bug, not a product
  bug: `test_hub_web.py` regex-scans `hub.js` for `$('#id')` selectors without
  stripping comments, so a comment *documenting* a past selector bug read as a
  live lookup. Now strips `//` and `/* */` first.
- **Phase 2 — git hygiene.** `knowledge/ledger.db` was gitignored *and* tracked;
  gitignore never untracks, so the 6.9 MB binary re-diffed on every commit and
  rode along in three. Untracked with the hub run log and `sahibinden_example/`
  (152 files, 7.8 MB, referenced by nothing). Tracked files 463 → 309.
- **Phase 3 — seven dead modules deleted** (`knowledge/` 21 → 13). All leaves:
  zero importers, every apparent reference a self-reference in its own docstring.
  Five were already on the 2026-07-07 ledger plan's delete list, which was only
  half executed. Two were per-model patches the generalization principle
  forbids — `fix_sibling_contamination.py` imports the very
  `stoplists.mentions_sibling_code` that now prevents what it was written to mop.
- **Phase 4 — `docs/historical/`** for the two "do not follow" docs plus
  `thoughts/`. `pipeline_postmortem.md` deliberately stayed: three live files
  cite it as a standing convention. `CLAUDE.md` and `README.md` both listed
  `kriko_build_plan.md`, which exists nowhere — dangling reference dropped.
- **Phase 5 — the dependency cycle.** `backend/` and `knowledge/` imported each
  other; 12 of 18 cross-boundary imports sat inside function bodies as
  `ImportError` workarounds. Root cause: `backend/tools/` held operator analysis
  tooling — nothing in `backend/api`, `core`, `db` or `sync.py` imports it, while
  the hub, ledger, MCP server and pipeline imported `backend.tools.coverage` from
  six places. New `ops/` layer (layer 3) now holds `reports/`, `hub/`, `mcp/`,
  `auto`, `process`, `ledger_run`, `swap`, `remediate`, `panel`; `title_sim`
  moved down into `knowledge/`. **`knowledge/` now imports nothing above it and
  `backend/` nothing from `ops/`** — enforced by two greps in `CLAUDE.md`'s new
  layering principle and documented in `INTERNALS.md` ("Two Planes" → "Three
  Layers"; it also still named `judge.py`/`promote.py`, long gone).

CLI paths changed with the module moves — `python -m backend.tools.coverage` →
`ops.reports.coverage`, `knowledge.auto` → `ops.auto`, `knowledge.ledger.run` →
`ops.ledger_run` — along with `.mcp.json`, `opencode.json`, `package.json`'s test
glob, and the command strings `ops/hub/web.py` spawns and validates.

Verified at every step: 761 pytest + 23 node tests, `docker build`, and
`import backend.core.resolver, backend.sync, backend.api.main` inside the built
image — the last catching a `COPY` the test suite structurally cannot see.


## 2026-08-19 — B24: agent methodology overhaul — rules move to the write path

The first live agent onboarding (VW Golf 8) wrote four **marketing trims**
(Impression/Life/Style/R-Line) describing two powertrains, with `7-speed DSG`
as a part code and `generation: null`. `submit_trims` returned success; the
breakage surfaced hours later in `backend/tests/test_catalog.py` — a test the
agent never runs. Root cause, generalized: **every rule that lives only in a
test or a prompt is a rule the agent can break and be told "OK".**

- **`knowledge/catalog/identity.py`** — one definition of what makes two cars
  different: `find_overlaps` (imported by `backend/tests/test_catalog.py`, so
  CI and the write gate cannot disagree), `collapse_duplicates`, the code
  vocabulary (`code_errors` refuses descriptions like `7_speed_dsg` and
  sibling-shared families like `dsg`), and `canonical_variant_id`.
- **`knowledge/catalog/doctor.py`** — the same rules applied to the catalog
  already on disk, for every car, unattended: normalize codes, rename
  trim-shaped ids, merge duplicate powertrains, prune orphan fitment rows, fail
  open (`draft: true`) on an unresolvable code. **Preserves the B16 fitment
  remap** rather than re-projecting fitment from variant fields (which would
  have silently pointed `megane4_h5f_100` back at a part file the swap merged
  away — caught by a test). Idempotent; CI gate on the live catalog.
- **`knowledge/agent/gates.py`** — the CLAUDE.md product principle enforced at
  `add_evidence`/`add_document` instead of requested in a prompt: warning-light
  items, ekspertiz-routine items, DTC litanies, filler rationales, blocked
  forum/spec-farm sources, the 5-document per-part budget, and rephrasings of a
  chronic already on file (dq200 carries ~30 rows of the same two failures —
  the B5 volume problem at its source). Reuses `stoplists.py`, with its
  specificity escape valve, so the agent path and the LLM path judge value
  alike. Calibrated against the live catalog: 10 of 699 claims rejected, each
  one a row the product principle says should not exist — pinned as a test.
- **`research_brief(part_id)`** — the agent's plan, derived from
  `components.yaml` + `source_tiers.yaml` + what is already on file + remaining
  budget. "Do web research" was the weakest instruction in the contract.
- **`finish_model(make, model, notes)`** — pipeline pass plus a recorded
  outcome in `logs/agent_runs.jsonl`, so a run's result outlives its session.
- **One contract, generated harness files** — `knowledge/agent/kriko_research.md`
  is the body; `knowledge.agent.render` writes `.claude/` and `.opencode/`
  copies; `test_agent_contract.py` fails on drift and on a granted tool the
  server does not expose.
- **Golf 8 fixed by the mechanism, not by hand**: `doctor --fix` merged it to
  two powertrain rows, renamed the ids, and left one honest finding —
  `7_speed_dsg` needs research.

Commit `e5c00de`. 754 tests (was 698 + 1 failing).

## 2026-08-19 — B25: kriko-hub — claim inspector, catalog doctor, real HTML page

- **The review queue is gone.** Approve rewrote `status: review` →
  `verified` inside a part YAML: a human decision in the data path, which G5
  rules out, and unusable at scale anyway — the live queue holds **696**
  claims, which nobody was ever going to hand-approve. It becomes a **claim
  inspector**: each claim carries the deterministic gate's verdict *with its
  reasons* (the same `knowledge/agent/gates.py` the MCP write path runs), and
  agree/disagree records a labelled example in `claim_signals.jsonl`. A rule
  that collects disagreement is a rule to fix in `gates.py` — where the fix
  applies to every car.
- **Catalog doctor over HTTP** — `/api/doctor` (findings split auto-fixable vs
  needs-research) and `/api/doctor/repair` ($0 deterministic pass), surfaced on
  the Coverage tab. `/api/agent-runs` shows what agent passes achieved.
- **The page is a real `static/index.html`**, not a Python string that once
  took the whole dashboard out via a stray escape (49aa90c). Two consistency
  tests: every element `hub.js` reaches for exists, and every tab it switches
  between has both a nav button and a page div — the second found a live
  drift on the first run.
- **Repo hygiene**: nine `imgui.ini` files committed under garbage names
  (`Constant with a value of 2`, `\240b\235\017`) by the deprecated
  DearPyGui hub, plus `ops/hub/app.py` itself and its `dearpygui`
  requirement, retired. The web hub has been the live one since 2026-08-04.

Commit `89ba247`. 759 tests.

---

## 2026-08-16 — B23: agent-driven model onboarding (closes B21, deprioritizes B22)

Onboarding a car no longer requires a human to hand-type a Python dict. B21's
agent could only start from a coverage finding that already named a `part_id`,
so a car with no scaffold was unreachable — and building that scaffold meant
editing `TR_MARKET_TRIMS` in `knowledge/catalog/write_variants.py`, the exact
hand-enumerated per-model list the scalability rule forbids. The researcher
agent now supplies the trim lineup from the web instead.

- **`write_variants.run(trims=...)`** — injection point; `TR_MARKET_TRIMS`
  demoted to CLI fallback. Row content verified identical for every already
  onboarded car (only pre-existing `notes` drift on `volkswagen_golf_7`).
- **`validate_trims()`** — deterministic structural checks (fuel/transmission/
  emissions vocabularies, year and power ordering, identity keys, duplicate ids).
  An **unsourced figure is not an error**: the row is written `draft: true`,
  `backend/sync.py` skips it, the coverage report raises `draft_variant`. Fail
  open rather than guess — a guessed figure is a silent wrong answer to a buyer.
- **MCP `onboard_model()` + `submit_trims()`** — the model entry point and
  scaffold write (variants + fitment, with the lineup's source pages recorded as
  `spec` documents). 13 → 15 tools.
- **Grounded quotes** — `add_evidence()` rejects any quote not literally present
  in the submitted document (casefold + whitespace-normalized). Previously
  `quote_grounded` was `bool(quote)`, so a fabricated citation was
  indistinguishable from a real one downstream.
- **Harness-agnostic wiring** — `.mcp.json` + `.claude/agents/kriko_research.md`
  (Claude Code) beside the opencode pair; Codex/Cline snippets in USAGE §4e.
  Validation lives in the server, so hosts are interchangeable and none can
  bypass the gates.
- **Agent loop** — one *model* per pass (was one part).
- 580 tests pass; 33 new (`test_write_variants_agent_trims.py`, MCP tool tests).

## 2026-08-04 — B20 + B21: kriko-hub desktop dashboard + MCP control layer

- **B20 — `ops/hub/`** (DearPyGui, deps: `dearpygui`): six clickable
  windows — Overview (spend bar-plot, cost-to-finish, log tails), Model &
  Make (parts → claims/variants/findings), Sources (documents → raw text),
  Extraction (run buttons spawning `ops.ledger_run` with `--max-usd`
  caps, streaming output), Ledger browser (generic read-only SQLite
  explorer), Scaffold (coverage findings). ~1s read-only DB poll; GUI-free
  `metrics.py` pinned by tests; `run.py` gained `verdict --import-only`.
- **B21 — `ops/mcp/server.py`** (stdio MCP, `mcp>=1.0,<2.0` — 2.0
  dropped FastMCP): 13 tools, read + $0 write. `add_document`
  (hash-idempotent) → `add_evidence` (extractor_version=1, (doc_id,title)
  deduped) → `run_pipeline_pass` (resolve/cluster/import-verdicts/export,
  logged `model=agent, usd=0`). Import-verdict predicate generalized
  `{0}` → `⊆ {0,1}` so agent evidence never queues a paid verdict
  (extractor-version-2 evidence still does). Wired in `opencode.json`
  (`mcp.kriko`, type local, `.venv/bin/python`), agent loop in
  `.opencode/agents/kriko_research.md` (coverage → part → research with
  native web tools → write ≤5 docs → pipeline pass → verify).
- **Effect**: new-model onboarding drops from ~$0.17–0.20 to **$0.00** via
  the agent; DeepSeek API demoted to optional accelerator. Suite 536 tests.

---

## 2026-08-03 — B16 catalog swap LANDED ($0 gate policy; no commit yet)

- **Acceptance gate PASSES** under the $0 policy: 0 lost claims (sourceless
  legacy claims = unverifiable provenance; in-ledger/pending = adjudicated;
  YouTube URLs = retry-owned by the remediate loop), 0 match-loss serving
  regressions on the 43-listing replay (current-vs-post-swap), coverage
  findings 18→9.
- **Swap applied in-place**: backend/data/parts/ now serves the ledger export
  (699 claims, 21 parts incl. dw5/dw6 with 17 claims each — the empty-gearbox
  gap closed); 25 legacy files superseded (power-split deleted, non-split
  overwritten), fitment remapped k9k_110→k9k etc. Serving DB re-syncs on
  deploy.
- **Two swap-caught bugs fixed**: (a) `code_family_extra` sibling aliases
  (r9m/M9R) were lost in the power merge — `component_part_meta` copies them
  and `apply` preserves them from superseded legacy files; (b) resolver
  `_best_in_cluster` mutated persisted ORM claims (first analysis rewrote the
  DB row → replay nondeterminism) — merged views now built on transient
  copies.
- **Legacy gate stack retired**: judge.py, promote.py, purge_*.py ×4,
  translate_claims.py, eval_judge.py, review_tool.py + 7 test files (75
  tests) deleted; `ops.process` promote steps raise with a pointer to
  `ledger.run remediate`. The sibling-code guard survives in the sync
  validator + verdict prompt. Suite: 519 passed.
- **Cost accounting (whole wave)**: $0.62 total LLM spend (2.66M tokens) for
  the 3-model catalog; steady-state is $0 (remediate defaults to import-only,
  `--max-usd 0`); new parts cost ~$0.17 one-time when explicitly funded.

## 2026-08-03 — Remediate loop live run + parity-lost self-closing (no commit yet)

- **First live remediate run** (coverage-driven, budget-capped): researched the 9
  zero-claim parts (dw5/dw6 now have 10/16 exported claims), 389 LLM calls for
  $0.17; backfilled the legacy cache (+234 docs, +1138 evidence rows); export
  regenerated (19 parts, dw5/dw6 covered).
- **Parity re-classification**: legacy claims with zero source URLs (~331 —
  mostly body/elec era claims) were counted as "never extracted"; they are
  unverifiable provenance — no URL means no evidence path, and the ledger's
  ≥1-grounded-source bar would never serve them. New category "no source URLs
  in legacy claim (unverifiable provenance)" in `parity.explain_only_old` —
  attributable, not lost. Gate lost count: 124 → 49.
- **Lost-source self-closing loop** (`remediate.lost_source_urls` /
  `ingest_lost_sources`): every parity-lost claim's cited URLs are fetched +
  ingested into the ledger (target_hint = claim's part stem) before the
  extract/cluster/verdict pass — the 49 remaining losses are now ingestible
  pages, not orphans. Tests added; suite 591.
- **Second live run**: ingested the 49 lost pages (+50 docs total), then hit
  **`Insufficient Balance` on the DeepSeek API** — extraction/verdicts pending,
  fully resumable. Once funded: `python -m ops.ledger_run remediate
  --max-usd 2.0` → `python -m ops.swap check`.

## 2026-08-03 — B16 swap mechanism + automated acceptance gate (no commit yet)

- **Export regenerated from the ledger** — the checked-in `ledger_export/` had gone
  stale (15 files, missing dq200/dq250/dq381/ea211/ea888/k9k, one bare-list
  artifact). Fresh run: 19 parts, 536 claims; `golf7_cool_cooling` correctly
  skip-and-reported (no catalog identity). Each part file now carries
  `legacy_part_ids` (which legacy power-split files it supersedes) —
  pipeline-derived via the power-collapse rule, no hand list.
- **`ops/swap.py`** — `plan` derives the legacy→merged fitment remap
  from the export, classifies every legacy file (superseded/retained), counts
  fitment edits; `apply` writes export files into `parts/<type>/`, deletes
  superseded power-split files, overwrites non-split ids in place (fixes a
  delete-pass bug that rglob'd away the fresh export files), rewrites fitment
  axes, defaults to a temp copy unless `--in-place`; `check` = the automated
  acceptance gate: parity loss (every absent legacy claim attributable to a
  named gate), serving monotonicity (baseline replayed against current AND
  post-swap catalogs on fresh DBs — 0 match-loss regressions allowed), coverage
  must not add findings. Tests: `test_ledger_swap.py`; suite 589.
- **Live gate state: FAIL, data-gated** — 119 lost claims (75 never extracted,
  23 never ingested, 21 no matching evidence) → B19 remediate loop targets;
  serving: 21/43 listings differ vs current serving, 0 regressions; coverage
  18→11. Swap lands when parity-lost hits 0.
- USAGE.md §4 Step 6 documents plan/check/apply.

## 2026-08-03 — B11 data safe + B19 auto-remediation loop landed (no commit yet)

- **B11 (data, fail-open)**: hand-typed `emissions`/`aftertreatment` removed from
  all 8 Megane 4 variant rows — the unverified `scr` value on
  `megane4_k9k_110_edc` (wrong for 2016–18) no longer serves. All variants fail
  open (no SCR grounding) until evidence-derived values exist.
- **B11 (mechanism)**: year-split `emissions` segments in `write_variants.py` —
  list of `{year_from, year_to, emissions}` per trim emits one variant row per
  era (`{id}__{emissions}` suffix), per-segment aftertreatment derivation,
  window validation. Tests: `test_write_variants_emissions.py`.
- **B11 (visibility)**: new `variant_no_emissions` coverage finding for diesel
  variants without an emissions value — the gap is reported, never a quiet
  wrong value. Tests added to `test_coverage_tool.py`.
- **B19 (driver)**: `python -m ops.ledger_run remediate`
  (`ops/remediate.py`) — coverage findings (zero_claim_part /
  missing_part / auto_variant_no_tx_part, now carrying `part_id`+`axis`
  metadata) drive an unattended acquire → extract → resolve → cluster → verdict
  → export pass. Budget-capped (`--max-usd`), resumable, `--dry-run` prints the
  plan, empty plan spends nothing. Every pass appends `logs/remediation.jsonl`.
  USAGE.md §4b documents scheduling. Tests: `test_ledger_remediate.py`.
- **G5 cleanup**: the draft-row onboarding step ("a human fills in real
  numbers") is retired — `draft_variant` coverage finding makes scaffolded
  rows fail open visibly; USAGE.md's "Promoting & rejecting claims (human
  step)" section replaced with a retired banner (statuses are verdict-stage
  owned). Docs updated to remove human-step language from onboarding.
- Full suite: 583 passed.

## 2026-08-03 — Priority reorganization: full automation + systemic-only (no commit — doc-only)

Two project rules changed in `CLAUDE.md` and the backlog, per the owner:

- **Automation principle (new)** — nothing in the data path waits for human
  verification, spot-checks, or sign-off; extraction and scraping run unattended.
  Where a value can't be derived automatically, fail open + log the gap. One-time
  policy decisions only (ToS, market coverage, source retirement).
- **Generalization principle (strengthened)** — per-model fixes do not exist:
  no per-model research runs, YAML audits, or spot-checks. Every fix is a mechanism
  that runs for all cars, or the feature is cancelled.
- **B17 dropped** — all official recall feeds retired (TR SGM, EU Safety Gate, NHTSA).
  HUMAN DECISION #6 resolved (drop). Ingested rows stay in `ledger.db` as history;
  feed ingesters + `run.py feeds` wiring to be removed/dormant.
- **B11 sign-off cancelled** — HUMAN DECISION #7 resolved: emissions values derive
  from evidence or fail open (no AdBlue claims when unknown); year-split rows where
  mid-life changes exist; hand-typed Megane 4 values must not serve as-is.
- **B19 created** — auto-remediation loop (coverage-report findings + B6
  contradiction signals auto-enqueue ledger acquire/extract + catalog regen).
  Absorbs former B2 (dw5/dw6) and B3 (EDC-auto gap, "manual only in TR" audits),
  whose manual steps are cancelled.
- **B16** — human spot-review sub-step replaced by an automated acceptance gate
  (parity --explain categories + coverage report + serving-baseline replay).
- **B9** — near-miss policy adopted: out-of-window listing still matches, with a
  "year outside known window" note + demand signal. No further decision.
- Remaining human decision: #5 only (B18 source ToS — one-time legal gate).

## 2026-08-02 — Serving-resolution fix + B15/B16/B17/B8 + B11 mechanism (wave 2)

- **Resolver fixed** — EDC Megane analyses stopped resolving transmission claims:
  `_resolve_part_claims` returned IDs instead of claim objects, and the missing
  `_fuel_compatible` import broke the fuel filter. Introduced `_servable_invariants`
  (source-requirement + high-severity-unreviewed gates) shared by both serving paths.
  Full suite 560 passed.
- **B3 (patch) + B6 (mechanism)**: added `megane4_k9k_110_edc` variant + fitment via the
  catalog pipeline; matcher/transmission-gap tests now pin EDC ads → EDC variant with
  `tx_mismatch false`. B6's coverage-gap test stays green via generic fixture variants.
- **B15 (done)**: deploy-staleness guard — `GIT_COMMIT`/`GIT_BUILD_TIME` stamped at image
  build (Dockerfile ARG/ENV, docker-compose, `scripts/run_local.sh`), surfaced via
  `/health`, `/analyze` (`build` field), and the extension footer. Recurrence guard for
  the B4 stale-image class. Tests: `test_build_stamp.py`, `hover_lite.test.js`.
- **B11 (mechanism landed; data at sign-off checkpoint, HUMAN DECISION #7)**: emissions/
  aftertreatment columns + `_scr_compatible`/`_default_aftertreatment` grounding gate in
  `backend/sync.py`; generator support in `write_variants.py`; `test_scr_gate.py`.
  Megane 4 values hand-typed pending spot-check (EDC row 110 ≠ Blue dCi 115 SCR years).
- **B17 (EU half done; TR blocked, HUMAN DECISION #6)**: Safety Gate feed rewritten to
  the official weekly-report XML after the reverse-engineered JSON API died (404);
  validated live — 50 Renault alerts ingested into `ledger.db`, idempotent.
  TR SGM blocked by an anti-bot JS challenge (TSPD); ingester kept, never fatal.
- **B16 (step 1 done)**: export rewritten to the part-dict schema with serving-gate
  fields grounded at export (year windows, mileage thresholds, maintenance);
  skip-and-report retained. Verified live to `/tmp/opencode/ledger_export` (19 parts).
- **B8 (done)**: `_select_capped` now ranks sources by domain reliability + title
  specificity; DeepSeek `json_object` extraction mode fixed.
- **B15/B17 feed run** left resumable in the background (text-hash dedup).

## 2026-07-22 — DB rebuild + evidence-ledger landing (B1/B12, G2/G4)

- **Serving DB rebuilt from YAML after accidental volume deletion** — no data loss
  by design (YAML is the source of truth; `logs/analyses.jsonl` and
  `knowledge/ledger.db` both survived). Rebuild surfaced a real deploy bug:
- **fix(deploy): add knowledge/consequence_tier.py to the image slice** (`56cb8af`) —
  fresh Docker builds crashed at startup (`sync.py` imports the consequence-tier
  module, but the Dockerfile's knowledge/ slice predated the serving overhaul).
  The recreate-from-scratch path had been silently broken since the overhaul
  landed (B15 class). Serving baseline fixture captured for future serving diffs
  (`backend/tests/fixtures/serving_baseline_2026-07-22.json`, 43 logged listings).
- **B1: evidence-ledger Stage 1 landed to main** (`80edf94`, G4: one trunk). Main
  merged into the branch (`bea0f5a`, one `.gitignore` conflict), then the two
  blockers fixed on-branch:
  - **Export skip-and-report** (`767dc82`) — one invalid cluster (DTC-in-title)
    no longer aborts the whole export; offenders are skipped, reported, retained.
  - **Parity stable identity** (`767dc82`) — match on shared source URLs + domain
    agreement instead of verdict-rewritten titles (`matched: 0` → 327 matched,
    95 sibling-reroute moves); cross-domain false matches from multi-claim pages
    guarded by the domain check.
  - **`parity --explain` acceptance report** (`84c2462`) — categorizes all 474
    only-in-existing claims (126 shipped under rewritten titles, ~230 gate drops
    working as designed, ~120 never ingested/extracted → tracked as B16's
    pre-swap review). Artifact: `docs/historical/thoughts/ledger_acceptance_parity_2026-07-22.txt`.
  - Servable catalog deliberately NOT swapped: legacy part YAMLs still serve until
    the export carries serving-gate fields and fitment is remapped (B16).
- **B12 completed** — `evidence-ledger-stage1` and `model-year-claim-windows`
  merged and deleted; `main` is the only trunk.

## 2026-07 (branch `model-year-claim-windows`, pending merge — backlog B12)

### Backlog wave 1 (2026-07-16/17, subagent-driven — merged into the branch)

- **Ad-vs-catalog transmission contradiction surfaced (B6)** (8990d99) — when the ad's
  gearbox matches no candidate variant's transmission and no same-engine alternative row
  exists, the resolver emits a degraded coverage note and logs a catalog-gap signal
  instead of falling back silently.
- **Coverage report + loud sync guard (B7)** (c8201f4) — `python -m ops.reports.coverage`
  maps variant → fitment parts → per-part claim counts and flags any non-`manual`
  transmission/engine code that resolves to a zero-claim part; `sync.py` prints the same
  warning. The "would it recur?" mechanism for the dw5 hole (B2).
- **Per-listing risk-cap regression net (B4)** (22c9117) — investigation proved the cap
  already binds in code; the 39-risk DSG Golf came from a stale deployed Docker image
  predating the cap commit (3672eaa), not a code bypass. Added unit-boundary + e2e
  `/analyze` regression tests pinning the cap. The remaining real fix (make a stale deploy
  visible) is new backlog **B15**.
- **`no_match` demand miner (B10)** (4a173cc → f2481c8 → 52aafa6, merged 19d62db) —
  `python -m ops.reports.demand` aggregates `no_match` `/analyze` log rows into a
  make/model onboarding-demand table, reason-classified (`not_onboarded` / `catalog_gap` /
  `missing_fields`), catalog-derived via `normalize.py` (no hardcoded car names). Review
  fix rounds: shared `observability.load_records` reader hardened against non-dict lines
  (also hardens `read_recent`/`read_by_id`), `missing_fields` derived from `ad_metadata`
  not matcher prose, fixture-catalog tests, majority-casing group labels, data-derived
  table widths.

- **Golf 7 1.2 TSI onboarded; fitment derived from variants** (a780f82) — no more
  hand-maintained fitment for new rows.
- **Scraper robustness pass** (0ada2d6, d697ee3, 6f64eb8) — fuel/year scraped reliably,
  make/model/fuel/year recovered from URL+title when the DOM fails, English-locale
  Sahibinden handled. Killed most of the `(None, 'Golf', None) → no_match` log rows.
- **Serving overhaul, phases A/B/C/E** (0463869, 3672eaa, b3c769b, c483cb5) —
  consequence-tier ranking signal, per-listing risk cap (MAX_RISKS_PER_LISTING=8;
  see backlog B4 for the exemption loophole), maintenance-kind reclassify script,
  specificity escape valve on the inspection-covered judge gate.
- **Model-year claim windows + mileage gates** (08f00a5, 123b2b7, 2960759) — claims
  carry `applies_year_from/to` and mileage thresholds, grounded deterministically;
  resolver hides out-of-window defects (fail-open on missing data).
- **Failure-onset vs service-interval confusion rejected** (59b22c2); **codes for
  never-onboarded components caught** (980e90f).
- **run_local.sh** (60c307d) — serve the API without Docker/Postgres.

## 2026-07 (branch `evidence-ledger-stage1`, unmerged — backlog B1)

- **Evidence-ledger Stage 1 pipeline** (24 commits, ~50c9ed1..434f9ec) — chunked cached
  extraction with budget enforcement, deterministic per-component evidence clustering,
  single batched verdict per cluster (migrated to DeepSeek, hash-cached, concurrent),
  resumable CLI with dry-run + cost report, validated YAML export, parity diff +
  gold-set verdict eval.
- **Deterministic product-value gate over the verdict model** (b9f0b0d) — eval_verdict
  11/11 gold, resolved the acceptance blocker.
- **Data-quality pass** (16dab04, b131d6d) — unreliable-source-domain blocklist,
  German-language evidence leak flagging.
- **AdBlue/SCR variant-scoping design spec** (434f9ec) — spec only; implementation is
  backlog B11.

## 2026-06 → 2026-07 (on `main`)

- **Part-centric "Lego" pipeline** — parts researched once (`backend/data/parts/**`),
  assembled per variant at sync via fitment YAML; catalog discovery scaffolds variants
  and fitment from Wikipedia.
- **Sync-time grounding guards** — transmission-code registry derived from the part
  catalog (no hardcoded code lists), fuel/drivetrain/powertrain compatibility checks
  stop cross-config contamination broadcasting (`backend/sync.py`).
- **Serve-time gates** — equipment gate, ad-stated-transmission gate (manual ad never
  sees DSG-mechanism claims), high-severity human-review gate, title-similarity dedup
  with strongest-signal merge (`backend/core/resolver.py`).
- **Observability** — `logs/analyses.jsonl` + `ops.reports.analyses` / `replay`
  (branch `observability-analyses-log`, merged content on current branch).
- **Docs** — `docs/INTERNALS.md`, `docs/USAGE.md`, `docs/design_flaws.md` (Flaws 1–4
  addressed; 5–6 tracked as backlog B13), `docs/historical/pipeline_postmortem.md`.


