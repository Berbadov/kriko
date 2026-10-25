# Kriko Agent

Kriko Agent is the app's fixed hosted research stack: Mercury 3 plans and
writes the answer; DeepSeek Search and Fetch supply web evidence. It appears
under **Settings → Agents** after both provider keys are available.

Set these keys in **Settings → Keys** or the ~/.kriko/env file:

    MERCURY_API_KEY=...
    DEEPSEEK_API_KEY=...

The key values stay in the application process. Mercury receives the research
brief and its supplied evidence; DeepSeek receives search queries and URLs from
its own search results. Kriko Agent is pinned to Mercury 3 so a saved
per-agent model preference cannot silently change the benchmarked stack.
The adapter sends Mercury 3's own envelope: temperature 0.5 (the model's
floor — 0.1 is a Mercury 2.5 value the provider refuses), a 131,072-token
output ceiling the model accepts, and the 1M-token context window. What a turn
asks for is less: 16,384 output tokens (`DEFAULT_MAX_TOKENS`), 32,768 where it
writes a whole catalog (`AUTHORING_MAX_TOKENS`). Mercury 3 reasons before it
answers and the reasoning counts against the same ceiling, so 8,192 cut off a
turn whose visible answer was two thousand tokens.

The agent requests page content with each DeepSeek search. It fetches a result
URL only when the inline text is missing or insufficient. Duplicate search and
fetch requests are coalesced during a research turn; independent tool calls run
with a four-request concurrency bound. Search and Fetch use 0.21-second
per-process pacing to stay below DeepSeek's documented 5-QPS per-account
limit. Failed and empty DeepSeek responses are not counted as billable calls.

Successful search results are cached in `~/.kriko/cache/kriko-agent.sqlite3`:
searches for 15 minutes and fetched pages for one hour, with at most 500 cache
entries. Cache hits appear in the run log and do not incur another DeepSeek
retrieval charge. The cache contains result text and URLs but no API keys; delete
that SQLite file to clear it.

Mercury 3's conversation context is capped at 96,000 serialized characters, and
the incoming brief is clipped to 32,000 characters if needed (the newest
24,000 characters of the chat travel with it). Tool output is
trimmed to fit while keeping source URLs and result metadata first. The full
retrieved text remains in the run's grounding data, up to 8,000 characters per
URL; the copy sent back to the model is 4,000 characters per result, which is
what keeps a five-result search from spending the whole turn's input budget.

Settings → Research has two Kriko Agent controls. **Thoroughness** sets the
search-call ceiling (3 at Low, 5 at the default midpoint, 8 at High) and the
result count per search (2, 4, and 5 respectively); a scope (below) can raise the
call ceiling for a complex product, to 12 at most. **Validation sensitivity**
requires quotes of 8–20 characters; at 80% and above it also requires an exact
case-sensitive quote from the returned source. Higher settings ask Mercury to
seek independent corroboration for consequential details.

Run token and cost reporting uses Mercury's reported input/output usage and
the model catalogue's Mercury 3 rates. DeepSeek is estimated at $0.00075 per
successful search or fetch request. If Mercury omits token usage, Kriko marks
the total unknown instead of reporting a partial amount as the full cost.

The APIs and their current request/billing rules are documented by
[Inception](https://docs.inceptionlabs.ai/) and the
[DeepSeek Search and Fetch guide](https://api-docs.deepseek.com/guides/search/).

## The protocol of one turn: what bounds it, and what it says

The reader's words: *"the kriko agent; it gets stuck on web search"*. A turn
used to have one bound — the model request — and none on retrieval, so a search
socket that dribbled held the job, and the reader's screen, for as long as the
socket did. Every bound now has a name, and hitting one ends the turn with a
sentence rather than silence.

| Bound | Value | What happens at it |
|---|---|---|
| Turn deadline | 120 s (`TIMEOUT_SECONDS`) | The next retrieval is refused; the turn ends with the deadline as its reason |
| Mercury request | `min(45 s, time left)` | The stream is cut; the reply carries the error |
| One DeepSeek call | `min(10 s, (time left − 1.5) / 3)` | That search or fetch reports "did not answer in time" and the turn continues with what it has |
| Tool rounds | 4 (`MAX_TOOL_ROUNDS`), 5 when a scope asked for more than 8 retrievals | "Mercury exceeded the web research round limit" |
| Tool calls | 12 at most (`MAX_TOOL_CALLS`); thoroughness (3/5/8) unless a scope sized it | "Mercury requested web access after its tool budget ended" |
| Response ceiling | 16,384 tokens, 32,768 when authoring | A cut-off answer is kept where it can be (below), refused where it cannot |
| Waiting on a tool | `time left + 1 s`, then the future is cancelled | "The search service did not answer in time" |
| Retrieval pool | 4 at once, 0.21 s pacing per lane | Queued, not dropped |

The pool is **not joined** on the way out (`_UnjoinedPool`): a worker abandoned
past the deadline is left to end on its own, which the retrieval timeouts make it
do. Joining it is what turned one slow socket into a stuck job.

**A turn says what it is doing.** `converse` reports one line per retrieval
through `on_step` — `searching: <query>`, `search (cached): <query>`,
`3 result(s): <query>`, `search failed: <query> (…)`, `free trial: 7 question(s)
left` — and `apiagent` publishes them on the job thread, so they appear in the
run's log as they happen instead of one frozen "searching the web" for a minute.

## Scope before search, and what a cut-off answer keeps

The reader's words: *"kriko agent aint performing well on quick searches … for
cars only brought 3 issues where that car had more than 3 and in many places"*,
and *"I think agent needs a thinking before going out on internet and search"*.

Three faults sat behind it, found by re-running a stored job on the reader's own
keys. The retrieval budget was the Settings dial for every product, so a
three-system car and a wristwatch each got five retrievals. A finding whose
quote was verbatim on a page the agent held was dropped because it cited an
address the search never returned. And an answer that reached the response
ceiling was thrown away whole, which is also how a catalog authoring job for the
same car failed with "reached the response token limit".

**Scope.** Before a quick look searches, or a question that asks for failures is
answered, one tool-less Mercury call (`ApiAgentResearcher.scope_for`, at most
20 s) names how complex the product is and which aspects need their own
evidence: the components and systems a fault could be in (`agentplan.Scope`:
`simple`, `moderate` or `complex`, at most 8 aspects, each with the query to
search it). The scope sizes three things and nothing else:

- the **retrieval pool**: the dial's ceiling plus 0, 2 or 4 for the complexity,
  never more than one retrieval per aspect plus one, never under 3 or over 12
  (`agentplan.scoped_calls`);
- the **finding cap**: 4, 6 or 10 sourced risks (`agentplan.risk_cap`), kept most
  serious first, where the unscoped brief keeps its old cap;
- a **checklist** in the system prompt: each aspect with its query, and the
  instruction to search the ones it has no evidence for before answering.

Each kept finding is tagged with the aspect it belongs to (the aspect's name or
its query both count), so the run's log says `scope: complex, 6 of 7 aspects
covered` and the job result carries the same record. **It fails open.** A scope
that times out, errors or cannot be read is `None`, the run says it could not
scope the subject, and everything behaves as the dial alone did. A product the
scope calls simple gets the dial's budget, not less.

**A cut-off answer.** At the response ceiling, a turn that has no pending tool
call keeps what was written (`reply.truncated`, `telemetry["truncated"]`) when
the caller asked for it: quick looks and the two catalog-authoring jobs do, since
`packauthor.read_payload` repairs cut-off JSON and a quick look's findings are
independent objects. A cut-off *tool call* is never kept, and any other caller
still gets the error. `read_payload` now reaches that repair for a catalog cut
off after complete claims, which it did not before: the complete claim objects
inside the cut-off outer object used to be mistaken for the whole answer.

**A mistyped address.** `quicklook.ground` checks a quote against the page it
cites. When the cited address is not one of the pages the search returned, the
quote (25 characters or more) is looked for on the pages held, and the finding is
kept on the page that carries it, preferring the nearest address. The words are
still found in a page's own text, so nothing ungrounded gets in; a cited address
that *is* a held page whose text lacks the quote stays refused.

## Which web search: the agent's own, or Kriko's

Settings → Agents gives every coding agent a third dial beside its model and its
effort: **Web search**.

| Choice | What happens | What it costs |
|---|---|---|
| The agent's own web search (**default**) | Kriko reads nothing; the CLI searches and opens pages with its own tools, and is told that no pages were prepared for it | Quotes are not checked against pages Kriko fetched, because it has none |
| Kriko's web search (experimental) | Kriko searches, reads the pages, and puts the text in the brief; every quote is checked against a page Kriko itself read | Kriko's search stack, which is the newer and less reliable of the two |

The default is the agent's own, for the reason the reader gave: Kriko's is the
experimental one. A stored choice is read where the model and the effort are
read (`providers.harness_researcher` → `prefs.search_for_harness`), so a call
site cannot forget it.

One exception is not the reader's to make: a CLI whose protocol has no web tools
(`TOOLLESS_PROTOCOLS`: codex, mistral-vibe) cannot search for itself unless the
transport is forced to a process with tools (`exec`). Left in `auto` it would
start a persistent, toolless session — the run that once tried WebSearch,
ToolSearch and `curl` a dozen times, was refused each time, and shipped a
catalogue with no claims. Kriko reads for it instead, and the run's note says
that the dial asked otherwise.

## Which kinds of source it goes to, and how that is visible

The reader's words: *"make sure that source selection type is determined by the
agent => from forums or magazine sites or news sites or official records etc.
all must be observable"*.

The `search` tool takes a third argument beside the query and the count: `kind`,
one of the app's closed vocabulary (`prefs.SOURCE_KINDS` — forums, reviews,
recalls, manufacturer, video, news). The system prompt tells the agent to decide
where to look before it searches, to put that kind's own word in the query
because a search that does not ask for a thread does not return one, and to go
to more than one kind for a consequential question. A kind the app does not know
is dropped rather than guessed at, and the line then says no kind.

Every search writes the same job-log line the in-house search writes
(`local_search_plan.searched_line`), so one run's source selection reads the
same whichever stack answered it:

    searching kind forums: widget pump seal failure
    searched kind forums: widget pump seal failure -> search returned 3 result(s) at forum.example, mag.example
    search failed for kind recalls: widget pump recall: DeepSeek Search returned nothing

A line beginning `searched` is classified as a search step (`app/web/steps.py`),
so a run's kinds can be filtered and read rather than guessed at. The in-house
search chooses its kinds the same way and logs the same shapes; see
`local_search_plan.choose_kinds` for how a question becomes a set of kinds.

## The plan before the spend, and the record after it

A turn used to spend the Settings dial the same way on every question, took any
page a search returned as evidence about the product, and kept every result for
fifteen minutes. `app/providers/agentplan.py` is the small deterministic layer
that replaces those three habits, with no model call and no category: it reads
the reader's own words (`converse(question=…)`, set by `chat_ask` from the
message) against the closed vocabularies the app already keeps.

- **Effort by uncertainty.** `make_plan` reads which kinds of source the question
  asks for (`local_search_plan.choose_kinds`). A question that asks only for a
  maker's figures or a review is a lookup and is worth `LOOKUP_CALLS` (4)
  retrievals; one that asks for owner reports or recalls, or for two kinds, is a
  hunt for failures and gets the dial's whole ceiling. A question that names no
  kind fails open to the dial untouched, and the plan never exceeds it. The run
  logs `plan: searching kinds: forums, recalls`.
- **Identity beside the evidence.** The question is reduced to the words that name
  the product — model codes and proper names, never a bare number — and every
  result and fetched page the model is shown carries `about_product`: whether the
  page's text has them (every model code, spaces and hyphens ignored; two thirds
  of the plain names). The system prompt tells the agent a page that is not about
  the product supports no claim about it. It is a signal, not a gate, and `null`
  when the question named nothing to check; it is computed for each question and
  never stored in the cache, because the cached row belongs to a query and the
  next question may be about another product.
- **Coverage, in-band.** When the question asked for a kind no search has gone to
  and retrievals remain, the last result of the round carries `coverage`
  (`still_asked`, with each kind's own word). Asking again after a finished draft
  would cost a model call and throw away words the reader watched stream in; a
  note beside the evidence is read before the agent decides to answer. A kind
  still unsearched at the end is reported as missing, never hidden.
- **Freshness by kind.** A search result is reused for as long as its kind stays
  true (`agentplan.FRESHNESS_SECONDS`): recalls five minutes, news ten, forums
  thirty, reviews and video an hour, the maker's documentation a day. A search
  that names no kind, or asks for none, keeps the fifteen-minute default.
- **The record.** `reply.record` says what the turn did, from what it actually
  retrieved: `searches`, `pages` (with readable text), `unreadable`, `cached`,
  `retrieved`, the `kinds` covered and the kinds `missing`, and — when a product
  was named — `on_product` and `off_product` pages. `ApiAgentResearcher` merges
  it across the turn's calls, `chat_ask` carries it with the usage fields so the
  saved message reads it back under `spend.record`, and the answer shows one
  quiet line: `3 searches · 5 pages read · forums, reviews · not searched: recalls`.
  The tooltip says how many pages had no readable text, how many were not about
  the product, and how many came from this computer's recent searches.

## What it may change in the app

The agent has three named actions, and no others. They arrive as tool calls, and
the turn carries back the same objects the screen draws (`reply.actions`,
`app/agentactions.py`); the answer's prose never creates one.

| Action | What it does | Press needed? |
|---|---|---|
| `remember` | Adds one lasting statement to the reader's profile — a must, an avoid, a preference, a distrust, or a line about how they use things — and saves it in **For you** | No: it is the low-risk action, and the reader can edit or remove it where it landed |
| `open` | Takes the reader to a screen they asked to see | Yes: navigating away mid-answer is the reader's move, not the answer's |
| `start_quick_look` | Starts one Quick Look on a product, saving its sourced risks in History | Yes: it spends the reader's credits, so the card's Start button is the consent |

A new spending or installing action comes back as `proposed` too, and its
screen runs it only on a press; a page's text cannot spend the reader's credits
or change an installed catalog. `start_quick_look` is run by
`POST /api/agent-actions`, which accepts no other action and starts the same
`quick_look` job the extension's button does.

The adapter passes the action executor only where it has app state
(`ApiAgentResearcher._app_action`). A test that has no app state still gets a
plain research turn.

## Buying questions: identify, research, then name a product

The reader's words: *"some agents are avoiding doing detailed work, identifying
parts doing research before showing some products"*. The buying brief
(`chat.BUYING_RULES`) now opens with an ordered pre-step rather than a
presentation rule: settle what the product is; name the parts or consumables
that matter and the code each carries, from the pages; find what owners,
repairers and records report failing on each candidate, and what the pages say
about fitment; only then compare candidates and name a seller. A list of
products without those steps is called an incomplete answer in as many words,
and the agent is told to say which parts it could not identify.

The same four steps are in `PRODUCT_ONLY_RULES`, in the Kriko Agent system
prompt (`kriko_agent.SYSTEM`) and in the API agents' contract note
(`apiagent.KRIKO_AGENT.contract_note`), so every plane is told once, at the door
it arrives through.
