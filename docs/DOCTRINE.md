# Implementing and testing doctrine

How work gets from "the reader asked for it" to "the reader has it" — every
session, human or agent. Until 2026-09-24 the norm was tests-green yet
ask-missed. Cause: no fixed **what was asked, what counts as done, who
checks.** Short rules; each enforceable one has a test.

## 1. A request is written down before any code

First act, an entry in `backlog.md`:
```
### B### — <a short title, ideally the reader's own phrase>
**Asked:** "<the reader's words, verbatim, never a paraphrase>" (date)
**Where:** <exact screen(s), e.g. "every research button: Browse → subject Research, Run → Start">
**Done when:** <a reader-visible outcome, check-decidable>
**Not this:** <the likeliest misreading>
**Owner:** <session/branch, or "free">
```

Quote, don't paraphrase ("Sliders" becomes "chips"). Read it back before
starting. No "Done when" means not understood: ask, never guess. B141 onward is
enforced by `test_every_new_backlog_item_says_when_it_is_done`.

## 2. "Done" is observable, and it is observed where the reader is

All four required. (1) **The end result happened**: the extension checks in,
the claims are in the pack. (2) **It is seen, as is, on the "Where" screen.**
(3) **It is on `main`**: branch work does not exist for the reader or for the
next session, which is why an item written on a branch is still open. (4)
**It was checked in the reader's environment** (Windows, their browser, their
own CLIs) wherever that can differ. A stub is a rehearsal and a cloud session
cannot do it, so until the Windows runner exists (B142) the reader or a hand
build does, and the PR says plainly "not yet checked on Windows". "Shipped" is
fifth: a double-clicked installer.

## 3. Reproduce first, then fix

A bug fails on purpose first (a test, `tools/walk.sh`, a symptom script). No
prior failure is a guess. Three failed fixes in one place means the model of
the problem is wrong. A fact about an outside tool is read from that tool, with
a test that fails when the tool drifts.

## 4. Tests: which kind proves what

| Kind | Proves | Does **not** prove |
|---|---|---|
| Unit / component (pytest, vitest) | logic, world stubbed | world matches stub |
| Source-reading guard (`test_repo_invariants.py` et al.) | code rule holds | anything *works* |
| `tools/walk.sh` | screens load, buttons respond, no errors/hangs | the button's purpose |
| **Journey check** (below) | reader's end result happened | — the one that counts |
| Reader's Windows install | works where used | — |

Green suite is necessary, not sufficient. A never-failed test tests nothing:
break the code once per guard (#48). Stub the edge (network, CLI), not the
middle (collaborators).

### Journey checks

One reader task start to finish in `tools/journeys/`, run by `tools/walk.sh`,
stated the way a "Done when" is: load the extension and check in; check a
listing and read the risks; research one subject and see the catalog gain
claims; change a model or an effort and read the next command line; install,
disable and update a catalog and see checks follow; register a site and see the
extension read it.

No journey pass, checked on Windows as in §2, means not done. Until those
scripts exist (B191), the PR hand-walks the journey and shows the steps, the
observed result and a screenshot.

## 5. Every PR carries its own proof

Merge requires: the quoted request and its id; the "Done when" and what was
observed; a screenshot of the "Where" screen (`.walk/`) or the journey's output;
where it was checked; and what it still does not do, stated rather than left
for the reader to find. Then **an uninvolved second agent reviews** the entry,
the proof and the diff, and answers one question: *does this do what was asked,
where it was asked?*

## 6. Several agents at once, without colliding

One area, one agent (the Agents screen, the research harness, the extension,
knowledge and catalogs, packaging and the shell). Claim it (`**Owner:**`)
first. Mergeable within a day, one request per PR. The PR goes to `main` the
same day and is merged daily; the reader merges. A day-old branch merges,
rebases, or closes, and nobody builds on unmerged work. LF endings
(`.gitattributes`).

## 7. When it does not work, say so

Partial is partial: what is missing and why. "It should work" is not a status.
A button that cannot work on this reader's machine says so on screen, with the
alternative next to it.

## Checklist, before saying "done"

- [ ] The entry quotes the reader, has a **Done when**, and was read first; a
  failing check pre-existed (for a bug); the "Done when" is seen on the
  **Where** screen; it is checked on Windows or the PR says it is not; the
  journey passes, or is hand-walked until B191.
- [ ] `tools/gate.sh` is green and `tools/walk.sh` is clean on the screens this
  touches; the PR carries the quote, the observation and the screenshot; a
  second agent has reviewed it; it is on `main`; and the item has left
  `backlog.md`, with the commit saying what was observed.
