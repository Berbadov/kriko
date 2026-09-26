# Implementing and testing doctrine

How work gets from "the reader asked for it" to "the reader has it" — every
session, human or agent. Until 2026-09-24 the norm was tests-green yet
ask-missed. Cause: no fixed **what was asked, what counts as done, who
checks.** Short rules; each enforceable one has a test.

## 1. A request is written down before any code

First act — a backlog entry:
```
### B### — <a short title, ideally the reader's own phrase>
**Asked:** "<reader's words, verbatim — never a paraphrase>" (date)
**Where:** <exact screen(s), e.g. "every research button: Knowledge → subject Research, Agents → Research top 5">
**Done when:** <reader-visible outcome, check-decidable>
**Not this:** <likeliest misreading>
**Owner:** <session/branch, or "free">
```

Quote, don't paraphrase ("Sliders" → "chips"). Read it back before starting.
No "Done when" = not understood: ask, never guess (B141+ enforced by
`test_every_new_backlog_item_says_when_it_is_done`).

## 2. "Done" is observable, and it is observed where the reader is

All four required: (1) **end result happened** — extension *checks in*;
claims *in the pack*. (2) **Seen on the "Where" screen** as is. (3) **On
`main`** — branch work doesn't exist for reader or next session. (4)
**Checked in the reader's environment** (Windows, their Chrome, real CLIs)
where it can differ — stubs are rehearsal; cloud sessions can't, so until the
Windows runner (B142) the reader/hand build does and the PR says "not yet
checked on Windows". "Shipped" is fifth: a double-clicked installer.

## 3. Reproduce first, then fix

Bug fails on purpose first (test, `tools/walk.sh`, symptom script) — no prior
failure = a guess. Three failed fixes in one place = wrong model (B109).
Outside-tool facts are read from the tool with a drift-failing test.

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

One reader task start-to-finish in `tools/journeys/` (B143) via
`tools/walk.sh`, stated like "Done when": extension install → checks in;
listing check → risks; one-subject research → pack gains claims; top-N agenda
run → `done` + summary; LLM/effort change → next command line; limits (B141)
→ respected, log-visible; pack install/disable/update → lookups reflect; site
register → extension reads.

No journey pass (on Windows per 2.4) = not done. **Until B143:** PR hand-walks
it (steps + observed result + screenshot).

## 5. Every PR carries its own proof

Merge requires: quoted request + id; "Done when" + observation; "Where"
screenshot (`.walk/`) or journey output; where checked; what it doesn't do
yet, stated. Then **an uninvolved second agent reviews** entry + proof + diff
only: *does this do what was asked, where asked?*

## 6. Several agents at once, without colliding

One area, one agent (Agents screen / research-harness / extension /
packs-knowledge / packaging-shell). Claim it (`**Owner:**`) first. Mergeable
within a day, one request per PR. PR to `main` same day, merged daily (reader
merges; day-old branches merge, rebase, or close; never build on unmerged
work). LF endings (`.gitattributes`).

## 7. When it does not work, say so

Partial = partial (missing + why). "It should work" isn't a status. A button
that can't work on the reader's setup says so on screen with the alternative.

## Checklist, before saying "done"

- [ ] Entry quotes reader, has **Done when**, seen first; failing check
  pre-existed (bugs); "Done when" seen on **Where** screen; Windows-checked
  or PR says so; journey passes (hand-walked until B143).
- [ ] `tools/gate.sh` green; `tools/walk.sh` clean on touched screens; PR has
  quote, observation, screenshot; second agent reviewed; merged to `main`;
  entry to `done.md` with commit.
