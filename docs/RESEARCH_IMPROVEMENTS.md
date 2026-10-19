# Research and agent improvements

The app starts without launching agent model-discovery probes. Opening the
agent settings or explicitly refreshing their model lists performs discovery.
Resident agent processes start when work needs them; idle workers expire after
90 seconds (20 seconds on machines with at most 8 GiB of memory), with at most
one idle worker retained. Active work is not evicted. Shutdown closes the
terminal session as well as the resident pools.

## Chat and the research queue

Local model responses exclude separate reasoning fields and inline thinking
blocks. Search requests written as `SEARCH:` or supported JSON tool requests
are dispatched to the host's bounded search/read path and kept out of the
streamed answer. Grounded answers use fetched text; snippets remain leads.

The Run view displays queries, result URLs, read outcomes and operational
events. Page-attempt counts advance when a reader call starts, and page-read
counts require returned evidence. A deadline does not count cancelled pending
work as a page read. Search results, attempted pages and read pages are
different measures. Source links from older threads are labelled as listed
sources when no read record was saved. Activity and source records survive
reopening a thread; detailed log events are derived from its saved job.

The selected model gives a new conversation a short title and suggests up to
three related follow-up questions. Clicking a suggestion places it in the
composer so it can be edited before sending. Metadata is optional: the answer
is saved first, and an unavailable or malformed metadata response keeps the
first-question title and omits suggestions.

A finished queue batch removes completed rows from the active queue. Its
saved checks and completed history remain. Failed, paused, newly added or
requeued products remain available for the next run.

## Language, market and keys

Settings exposes response language, search language and market region.
Market context applies to chat, research, Quick Looks and follow-up briefs.
It prefers region-relevant evidence and requires the source to establish
regional applicability for fitment, recalls, regulations, prices and stock.
An output language choice does not translate the entire app interface.

For a compatible API service, save its key and endpoint in Settings, choose
the OpenAI-compatible API row in Agents, and select or enter its model ID.
Keys use the existing local key store and are not returned by the API. Web
tools on the compatible API agent use the selected Exa or Tavily provider;
ordinary conversation can work with just the completion key. Provider charges
remain the user's own account charges.

Jev is an optional TypeSafe classification provider, configured separately
from the conversation model. Its typed catalog decisions are constrained to
installed catalog candidates, with an explicit uncertain option and local
evidence validation. Its confidence is not proof that a product belongs in a
catalog or that parts are compatible. See [How Kriko works](HOW_IT_WORKS.md)
for classification audit details and setup.

## Compatibility, sellers and report length

Compatibility research requires exact variants and relevant constraints. PC
research distinguishes socket, chipset, BIOS, RAM generation, power and
clearance. Vehicle research distinguishes year, engine, transmission, market,
VIN restrictions and exact part numbers. Missing decisive evidence leaves
fitment unconfirmed. These are research rules, not a substitute for a
manufacturer fitment database or a physical inspection.

Seller checks consider independent owner or consumer forums and records,
match the seller's identity, and distinguish reports from verified findings.
A marketplace's reputation does not establish an individual seller's
credibility. Missing reviews do not establish fraud or safety.

The model selects report length based on complexity, consequences and available
evidence, while honoring explicit requests for brevity or detail. Existing
token and context bounds still apply.

The [compatibility benchmark](../benchmarks/COMPATIBILITY.md) provides five
fictional supplied-evidence cases, source-quote validation and mechanically
derived compatible, incompatible and unknown verdicts. It supports local and
API models. `python -m app.compatbench verify` checks fixtures and the grader
offline; it does not measure model quality. No live model benchmark or paid
provider request was run while implementing these changes.
