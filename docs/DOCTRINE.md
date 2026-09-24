# Implementing and testing doctrine

How work gets from "the reader asked for it" to "the reader has it". Every
session, human or agent, follows this. It exists because, until 2026-09-24,
the usual outcome of a request was code that passed its tests and still did not
do what was asked: a button that opens a browser with no extension in it, a
limiter that became three chips inside a collapsed section, an agent run that
works in the log and fails at the end, and a feature finished on a branch
nobody merged.

The failure was never that the code was careless. It was that three questions
had no fixed answer: **what was asked, what counts as done, and who checks.**
This file answers them. Each rule is short on purpose, and each one that can be
enforced by a test is.

---

## 1. A request is written down before any code

The first act on any request is a backlog entry, in this shape:

```
### B### — <a short title, ideally the reader's own phrase>
**Asked:** "<the reader's words, verbatim — never a paraphrase>" (date)
**Where:** <the exact screen(s) and place, e.g. "every research button:
  Knowledge → a subject's Research, Agents → Research the top 5">
**Done when:** <what the reader can see or do, stated so a check can decide it>
**Not this:** <the misreading this is most likely to suffer>
**Owner:** <session / branch holding it, or "free">
```

- **Quote, do not paraphrase.** "Sliders" became "chips" because the word
  was dropped between the request and the code.
- **Read it back.** The agent shows the entry to the reader before starting.
  One line of correction here costs seconds; a wrong feature costs a day.
- **If "Done when" cannot be written, the request is not understood yet.** Ask.
  Never start from a guess about what the reader meant.
- `test_every_new_backlog_item_says_when_it_is_done` fails the suite on an item
  (B141 onward) with no `**Done when:**` line.

## 2. "Done" is observable, and it is observed where the reader is

An item is **done** only when all four hold:

1. **The end result happened**, not just "something changed". The extension is
   done when the extension *checks in* with the app, not when a window opens.
   Research is done when accepted claims *appear in the pack*, not when the job
   log scrolls.
2. **It was seen on the screen named in "Where"**, visible without expanding,
   scrolling past or knowing it is there.
3. **It is on `main`.** Work on a branch does not exist for the reader, or for
   the next session, which starts from `main`.
4. **It was checked in the reader's environment** (Windows, their Chrome, their
   real CLIs) whenever the change touches something that differs there:
   packaging, the shell, the extension, a harness, a file path, an encoding.
   Linux Chromium and stand-in CLIs are a rehearsal, not the performance.
   A cloud session cannot do this check. Until the Windows runner (B142)
   exists, it falls to the reader or the hand build, and the PR says "not yet
   checked on Windows" rather than implying it was.

"Shipped" is a fifth step: in an installer the reader has double-clicked
(`CLAUDE.md`, app-first rule 4).

## 3. Reproduce first, then fix

- **A bug is first made to fail on purpose**: a test, a `tools/walk.sh` run, or
  a script that shows the reader's symptom. The fix is then shown turning that
  same check green. A fix with no failing check before it is a guess.
- **Three failed fixes in the same place means the model is wrong, not the
  code.** Stop patching and find the fact you do not know (B109 took six
  releases of patches before anyone questioned the component).
- **Facts about outside tools are asked, never remembered.** Model names, flags,
  help text, API shapes and browser behaviour change without notice. Read them
  from the tool (`--help`, `models`, a real call), and add a test that fails
  when the code and the tool disagree. A list typed from memory is a bug that
  has not fired yet.

## 4. Tests: which kind proves what

| Kind | Proves | Does **not** prove |
|---|---|---|
| Unit / component (pytest, vitest) | the logic, with the world stubbed | that the world behaves like the stub |
| Source-reading guard (`test_repo_invariants.py` and friends) | a rule about the code holds | that anything *works* |
| `tools/walk.sh` | every screen loads, every button responds, nothing errors or hangs | that the button achieved its purpose |
| **Journey check** (below) | the end result a reader wants actually happened | — this is the one that counts |
| The reader's Windows install | it works where it is used | — |

- **A green suite is necessary, not sufficient.** Never report a feature as
  working on the strength of unit tests alone.
- **A test that has never failed has not been shown to test anything.** When
  adding a guard, break the code once and watch it go red (#48: `npm test` ran
  zero tests with exit 0 for weeks).
- **Stub at the edge, not in the middle.** Stub the network and the CLI, not
  the component under test's own collaborators.

### Journey checks

A journey is one thing a reader does from start to finish, with its end result
asserted. Each lives in `tools/journeys/` (B143), runs against the real app
through `tools/walk.sh`'s harness, and states its end result the way a "Done
when" line does. The first list:

1. Install the extension → the extension checks in (`/api/extension` sighting).
2. Check a listing → risks are shown for it.
3. Research one subject with an agent → the pack gains accepted claims.
4. Research the top N from the agenda → the run ends `done` with its summary.
5. Change an agent's LLM / effort → the next run's command line carries it.
6. Set the research limits (B141) → the run respects them, visible in its log.
7. Install, disable, update a pack → lookups reflect it.
8. Register a site → the extension reads it.

A feature is not done until its journey exists and passes, on Windows where
rule 2.4 applies. **Until `tools/journeys/` exists (B143):** the PR walks the
journey by hand instead: the steps taken, and the end result observed at the
last step, with a screenshot of it. That walkthrough is the proof.

## 5. Every PR carries its own proof

The PR template asks for, and a PR is not merged without:

- **The request, quoted**, with its backlog id.
- **The "Done when" line, and what was observed**, not "tests pass".
- **A screenshot of the screen named in "Where"** (`tools/walk.sh` writes them
  to `.walk/`), or the journey's output.
- **Where it was checked**: here, or the reader's Windows machine.
- **What it does not do yet**, stated, never left for the reader to find.

Then **a second agent that did not write the code reviews it against the
request**, reading only the backlog entry, the proof and the diff, and answers
one question: *does this do what was asked, where it was asked?* The author is
the worst judge of that, because it knows what it meant.

## 6. Several agents at once, without colliding

- **One area, one agent.** Areas: the Agents screen, research/harness, the
  extension, packs/knowledge, packaging/shell. Two agents never hold the same
  area: that is how `Pick.svelte` and `HarnessLlm.svelte` were both written.
- **Claim it in the backlog** (`**Owner:**`) before starting, so the next
  session sees it is taken.
- **Small enough to merge within a day.** One request per PR. "20 of 23 items"
  in one PR hides the wrong one behind the nineteen right ones.
- **A PR to `main` the same day, merged daily.** The reader merges, as
  `CONTRIBUTING.md` says: nothing reaches `main` without the author asking. So
  an agent opens its PR the day it starts and says it is ready; a branch older
  than a day is merged, rebased on `main`, or closed. Nothing is started on top
  of unmerged work.
- **Line endings are LF.** A Windows editor that writes CRLF turns a one-line
  change into a whole-file conflict. `.gitattributes` makes git store LF.

## 7. When it does not work, say so

- A partial result is reported as partial, with what is missing and why.
- "It should work" is not a status. "It worked here, not yet checked on
  Windows" is.
- A button that cannot do its job on the reader's setup must say that on
  screen, and offer what does work, never open a window and let them discover it.

---

## Checklist, before saying "done"

- [ ] The backlog entry exists, quotes the reader, and has **Done when**.
- [ ] The reader saw the entry before the work started.
- [ ] A failing check existed before the fix (for a bug).
- [ ] The "Done when" result was observed, on the screen named in **Where**.
- [ ] Checked on Windows if it touches anything that differs there, or the PR
      says it was not.
- [ ] Its journey check passes, or (until B143) the PR walks it by hand.
- [ ] `tools/gate.sh` green; `tools/walk.sh` shows no errors on the touched screens.
- [ ] The PR carries the quote, the observation and a screenshot.
- [ ] A second agent reviewed it against the request.
- [ ] Merged to `main`; the backlog entry moved to `done.md` with the commit.
