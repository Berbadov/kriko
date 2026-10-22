# Arrange the desktop app around Kriko Agent

This page proposes where the Kriko Agent lives, how a first question is asked and
answered, how its searches are shown, and what Settings holds. On it, an
**allowance** is the questions a shared password buys, and a **record** is the
searches run, the pages read, the kinds asked for and the cost.

Citations name a file and the symbol in it. Ten files carry uncommitted changes on
2026-10-23, so a line number would go stale. The pinned stack is named because
`docs/KRIKO_AGENT.md` names it and the code fixes it: one model plans and writes,
one provider runs Search and Fetch (`kriko_agent.py`, `MODEL`).

## 1. Where the Kriko Agent lives

**Today.** Chat is the landing screen and the only place a question is asked
(`kriko-ui/src/App.tsx`, the initial `screen` state, and `kriko-ui/README.md`).
The agent pick sits in the composer footer (`kriko-ui/src/ui/Composer.tsx`, the
`agent-pick` block). The Kriko Agent is a row under Settings, Agents, and the row
exists only when both keys are present (`apiagent.py`, `available`).

Three places already draw the work of a turn.

| Place | What it draws | Code |
|---|---|---|
| Timeline in the thread | one row per search, each page read, each failure | `kriko-ui/src/engine/live.ts`, `rowsFrom`, and `kriko-ui/src/activity/Timeline.tsx` |
| Sources column | each page with host, the engine's tier label, its standing, and whether it was read | `kriko-ui/src/ui/ChatRail.tsx`, and `src/app/evidence.py`, `tier_pages` |
| Logs panel | every job's steps with timing, tokens, cost, the redacted request and reply, and an export | `kriko-ui/src/ui/panels/Logs.tsx`, and `src/app/web/routers/logs.py` |

One gap matters most. A Kriko Agent turn gathers its evidence inside its own tool
loop, and that retrieval reaches the job log only. `kriko_agent.converse` calls
`on_step` for each retrieval, and `apiagent.ApiAgentResearcher._run` publishes
those lines and one summary line with the retrieval count, the billable count, the
cache hits and the cost. A chat turn on the ordinary route returns its answer with
`sources: []` and `activity: []` (`src/app/chat.py`, `run_turn`), so a reader sees
these searches in Logs and nowhere else.

**Change.**

1. Put the record on the answer, under the answer head: `5 searches · 9 pages
   read · $0.03`. The cost of the turn is drawn there already (`AnswerActions`).
   The reply also holds `queries`, `sources`, `retrieval_requests`,
   `billed_tool_calls` and `cache_hits` (`kriko_agent.converse`), and the chat
   result fields drop them (`src/app/web/routers/chat.py`, `USAGE_FIELDS`), so one
   result field carries the rest.
2. Draw each page the agent read, with its address and the engine's own tier
   label, in the Timeline that draws a web search today. The provider's
   `reply.sources` map is already the grounding text of the turn.

**A separate Kriko Agent screen is a bad idea.** A second composer splits one
thread in two, and every answer record is built per turn inside `app/chat.py`.

## 2. The first run, with no keys

**Today.** The window opens on Chat. The tour runs once on the first start
(`kriko-ui/src/tour/Tour.tsx`, `STEPS`). When no agent can run, a bar under the
top bar offers `Choose or install an agent` and `Add a provider key`
(`kriko-ui/src/App.tsx`, the `engine-notice` block). A turn with no agent refuses
with one sentence that names a different API agent and never the Kriko Agent
(`src/app/web/tasks.py`, `NO_AGENT`).

The empty state holds a sky, one question and recent checks
(`kriko-ui/src/screens/Chat.tsx`, the `hello` header and `recents`).
`docs/DESIGN.md:65-66` says the empty state shows "a row of prompt buttons". The
code has none, so a first-time reader has nothing to press and must invent a
question. There is no allowance and no account: the agent's own row says the keys
are the reader's own and that no shared credentials are included (`apiagent.py`,
`KRIKO_AGENT.model_hint`).

**Change.** The shortest path, in the reader's words:

| Step | Screen | What happens |
|---|---|---|
| 1 | Chat, empty | One card: `Kriko Agent is ready. 3 questions left today.` One button: `Ask a question`. |
| 2 | Composer | The reader types a product in their own words, for example `Bosch GBH 2-26 drill, what breaks`. |
| 3 | Thread | Four phases run. The answer arrives with its record line and its pages. |
| 4 | Allowance spent | The next press shows one card: `Your free questions ended. They return at 09:00.` Two buttons: `Ask again tomorrow` and `Use your own key`. |

Three rules for that card. Finish the turn that started, because a run stopped
mid-way was paid for and taken away. Say when it fails, and draw no number the
engine did not report (`docs/DOCTRINE.md:65-69`, `docs/DESIGN.md:227`).

**The friend with a password** uses the same screen. The only difference is one
field in Settings, Access (section 5). A reader without a password sees `Kriko
Agent needs keys` and a link to the Keys group.

**Two parts of this are not in the code.** A shared allowance needs a server that
holds the owner's keys and counts each person's questions. The relay is not that
server: it claims one owner and carries sealed blobs, watches and alerts
(`server/kriko_cloud/app.py`). `docs/DOCTRINE.md:184-185` pins the app as
standalone, so a metered service for strangers is a decision for the owner.

**Putting the owner's keys in the installer is a bad idea.** A shipped key cannot
be revoked, the owner pays for every stranger's question, and the app's own Keys
group promises the opposite: "A key stays on this computer"
(`kriko-ui/src/ui/panels/Settings.tsx`, the Keys note).

## 3. The agent picker

**Today.** One pill in the composer footer shows the agent mark and the label,
and opens a listbox with arrow keys and Escape (`Composer.tsx`, the `agent-pick`
block). The list is `/api/agent-availability`: installed CLIs, then API agents
with a key, then the local row (`src/app/web/routers/prefs.py`,
`agent_availability`). The order of choice is the pick, then the stored
`preferred_harness` (`src/app/prefs.py`, `HARNESS`), then the first row. The run
does not always use that pick: the engine resolves every run as the pick if it can
run, else the first installed CLI, with a note (`src/app/providers/__init__.py`,
`resolve_agent`). The answer head names the agent that answered
(`kriko-ui/src/engine/live.ts`, the succeeded branch).

**Already in this working tree, uncommitted.** The pick is kept as the stored
default (`kriko-ui/src/engine/Engine.tsx`, `chooseAgent`), and the roster no
longer clears a saved default when a reply omits one. That is the owner's report
that the selection changes on every reply.

**Change.**

| Row group | Rows | What a row shows |
|---|---|---|
| Kriko Agent | one | `Kriko Agent`, then one line in the reader's words: it searches the web itself, it spends the keys on this computer, and the cost of the last answer in this chat |
| On this computer | a coding agent CLI, a local model server | the label the engine found, and the model chosen in Settings, Agents |
| Other API agents | each agent with a key | the label and `billed per token` (`apiagent.py`, `ApiAgentResearcher.cost_basis`) |

1. Remove `Soon` from the label when the stack ships, and show no model control
   on that row. In a picker, `Soon` reads as "not now", and the stack is pinned
   on purpose (`providers/__init__.py`, `_api_agent`).
2. Say the fallback where the reader looks. `resolve_agent` builds the note
   already and it reaches the log only. The answer head is the place for it.
3. Keep the three mode chips where they are (`Composer.tsx`, `MODES`). They are
   buying modes for a web turn (`src/app/chat.py`, `web_turn`), not the source
   choice of section 4. Two chip rows with two meanings is a defect.

**What persists between messages, after this change:** the reader's default
agent, in the engine, and the agent of each answer, in the thread. The composer's
own state is not a record.

## 4. Search transparency

**Today.** Six kinds exist: forums, reviews, recalls, manufacturer pages, video,
news (`src/app/prefs.py`, `SOURCE_KINDS`). Settings shows them as chips and keeps
at least one on (`Settings.tsx`, `source-kinds`). A run turns them into one
sentence in the brief, `Go to these kinds of source first`
(`src/app/web/tasks.py`, `_source_kinds_line` and `_apply_source_options`). A
research job may override the stored choice, because its request carries
`source_kinds` (`src/app/web/routers/jobs.py`, `ResearchRequest`). A chat message
may not, because its request carries text, harness, backend and mode only
(`src/app/web/routers/chat.py`, `MessageRequest`).

The agent's tools take a search query and a result count, and nothing else
(`kriko_agent.py`, `TOOLS`). The kinds are an instruction to the model, never a
filter on the provider, so a reader who picks `forums` asks the model to start
there and the engine promises no forum page. Each page that was read comes back
with the engine's classification and standing (`src/app/evidence.py`,
`tier_pages`), and the sources column draws that label
(`kriko-ui/src/ui/ChatRail.tsx`).

**Change.**

1. One row above the composer, left of Send: `Where to look`, with the six kinds
   as chips, preselected from Settings. One press changes the next question.
2. Send the chips with the message. Add `source_kinds` to `MessageRequest` and
   pass it in the job params, beside the field the research request already has
   (`jobs.py`, `ResearchRequest.source_kinds`).
3. On the answer, under the record line: `Looked in: forums, maker pages`, with
   the same chips. The exact queries stay in the Timeline and the Logs panel,
   never as prose in the answer.
4. Under each chip, a count of pages of that kind, only when the engine can say
   it. The engine classifies each read page into its own tier label
   (`evidence.py`, `tier_pages`) and holds no mapping from that label to the six
   kinds. Until it does, do not invent the count.

**Two bad ideas here.** A filter that hides a page the agent already read makes
the record disagree with the evidence. A site list inside the screen breaks the
rule that the engine owns the classification (`docs/DESIGN.md:196-203`).

## 5. Settings

**Today.** One entry point: the drawer list, reached from the top bar
(`kriko-ui/src/ui/Drawer.tsx` and `kriko-ui/src/mock/data.ts`, `DRAWER`, where
the Settings row carries the gear icon). The panel holds Look, Chat, Information
sensitivity, Research, Search providers, Proxies, Keys, MCP clients, Usage caps,
Spent and About (`kriko-ui/src/ui/panels/Settings.tsx`). The Kriko Agent appears
twice: two sliders in Research (Thoroughness, Validation sensitivity) and a row
in Agents.

**Already in this working tree, uncommitted.** A Settings button with a gear sits
in the top bar at a readable size, the drawer icons grew, and closing the drawer
clears the remembered panel so the next open shows the list
(`kriko-ui/src/ui/TopBar.tsx`, `kriko-ui/src/App.tsx`,
`kriko-ui/src/styles/shell.css`). Those are two of the owner's three reports. The
third is section 6.

**Change.** Keep one entry point, and change two things.

| Order | Group | Contents |
|---|---|---|
| 1 | Kriko Agent | keys present, thoroughness, validation sensitivity, where to look |
| 2 | Access | your own keys, the shared password, questions left today |
| 3 | Look | theme, motion, reduce motion, tour |
| 4 | Chat | what it remembers, before it answers, product-only answers |
| 5 | Research | products at once, extra sources, languages, market, classification |
| 6 | Agents | the roster, each agent's model and effort, Connect |
| 7 | Usage | caps, spent in N days |
| 8 | Connections | search providers, proxies, MCP clients |
| 9 | About | engine version, updates, your data |

The shared password and its allowance live in Access, as one card: a state line
(`Sharing off`, or `Ready. 7 of 10 questions left today.`), one password field
with Save and Remove as the key field has (`Settings.tsx`, `KeyItem`), the
questions a day and the hour they return, and one `Stop sharing` action.

The count must come from the engine. The only ceiling on the screen today is the
local cap, and the panel says what it is: "A cap is a warning, not a stop"
(`Settings.tsx`, the Usage caps note, and `kriko-ui/src/engine/caps.ts`). A
password that spends the owner's keys needs a stop, and section 7 says the cost.

## 6. The reported reply that renders twice

The mechanism is visible in this working tree, and the fix is uncommitted in two
files. A turn makes more than one model call. A repair after an offer, the
citation revision and the evidence review each stream their own answer from the
beginning, and publishing that restart replaced the words already on screen
(`src/app/chat.py`, the stream hook above `hooks.partial(snapshot(answer))`). A
poll snapshot that carried no answer did the same on the next tick
(`kriko-ui/src/engine/live.ts`, the active-job branch). The tree now keeps the
longer draft and keeps the words already drawn.

The reproduction still comes first (`docs/DOCTRINE.md:39-44`): the job id, the
thread id and a screenshot of the doubled reply, then the test that fails before
the fix (`src/app/tests/test_a_restart_does_not_blank_the_answer_on_screen.py`).

## 7. What the runtime cannot support

| A screen I would design | Why the engine cannot support it today |
|---|---|
| A shared allowance with a password | No account, no per-person counter, no metered proxy. Keys are per installation (`src/app/keys.py`, `PROVIDERS`), the agent says no shared credentials are included (`apiagent.py`, `KRIKO_AGENT.model_hint`), and the relay claims one owner and serves blobs, watches and alerts (`server/kriko_cloud/app.py`, `claim`). |
| A per-kind count of pages read | The six kinds become one sentence to the model (`tasks.py`, `_source_kinds_line`), the tools take a query and a count (`kriko_agent.py`, `TOOLS`), and no mapping from the engine's tier label to the six kinds exists. |
| A steer inside one question | `MessageRequest` has no `source_kinds` and no `budget_usd` (`src/app/web/routers/chat.py`). `ResearchRequest` has both (`src/app/web/routers/jobs.py`). |
| The retrieval record on the answer | The counts are on the reply (`kriko_agent.converse`) and in one log line (`apiagent.ApiAgentResearcher._run`), and the turn returns `sources: []` and `activity: []` on the conversation route (`src/app/chat.py`, `run_turn`). The chat result fields drop them (`routers/chat.py`, `USAGE_FIELDS`). |
| A model choice on the Kriko Agent row | The stack is pinned (`providers/__init__.py`, `_api_agent`). |
| A stop when the allowance ends | `budget_usd` stops one run (`src/app/turnusage.py`, `TurnUsage.parameters`, and `apiagent.ApiAgentResearcher._calls_allowed`). The caps warn in this window only (`caps.ts`). No per-day stop exists. |

## 8. What to build first

| Order | Change | Size |
|---|---|---|
| 1 | The turn's record on the answer: searches, pages read, cost, and the pages themselves | one result field through the engine |
| 2 | The empty state's prompt buttons, as `docs/DESIGN.md:65-66` already describes | small, no engine change |
| 3 | The kind chips above the composer, with `source_kinds` on the chat message | one field through the engine |
| 4 | The picker groups, the fallback sentence on the answer head, and `Soon` removed | small |
| 5 | Settings in the new order, with Access | small |
| 6 | The allowance and its password | a new server surface, and a decision for the owner |
