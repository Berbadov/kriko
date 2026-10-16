# Interactive workflows, 2026-10-15

The requested target was “10 to 30 seconds with progressive and interactive
output,” consistent concurrent runs, a usable Compare screen, and Chat that
can find products online and hold an ordinary conversation.

## Changes

Ordinary Chat and web discovery use one answer call. Catalogue questions still
use bounded record selection. Chat shows streamed prose, linked sources,
separate conversation jobs and drafts, Stop, Retry, Copy, explicit agent choices,
and a wrapped composer with Shift+Enter for a new line. Research details can be
opened separately from the answer.

Compare keeps four products together, matching the saved-draft limit. Its
research queue is collapsed below the comparison, with a bounded expanded
list, separate failure states and retry actions. Follow-up jobs are recorded
before the API returns, so switching drafts can reconnect to their progress.
Queue claims use one conditional database update to prevent duplicate research
from two clients.

The shared run limiter no longer calls database-backed cancellation checks
under its global lock. Quick Look overlaps page reads with search and limits
initial gathering to 15 seconds, reports timed-out coverage as partial, and
retains exact quote validation. This is a gathering budget, not a promise that
the model finishes in 15 seconds.

## Observed measurements

On the Windows development machine, two real Chat jobs were posted to separate
threads concurrently through the production HTTP API. Each used Codex with
`gpt-6-luna`, the existing saved `low` effort setting, and a fresh conversation.
The databases were isolated copies. No reader preference was changed.

| Question | First answer visible | Finished | Model calls |
|---|---:|---:|---:|
| Explain a robot vacuum's lidar in two short sentences | 5.71 s | 6.24 s | 1 |
| Explain how HEPA filters work in two short sentences | 9.37 s | 9.90 s | 1 |
| Find air purifier reviews and summarize two products with source links | 10.59 s | 11.41 s | 1 |
| Find a quiet air purifier for a small bedroom with manufacturer specifications and sources | 8.41 s | 9.45 s | 1 |

The first two succeeded while the other job was active. The web turn fetched
an RTINGS review page, named two products, and linked that page. It also stated
that the supplied excerpt did not establish their individual performance.
The fourth turn returned a product and two fetched source links, while explicitly
saying manufacturer specifications were unavailable in those excerpts.
These are four observations, not a percentile benchmark or a guarantee for
deeper research.

The free local search helper answered its health check. Three searches through
its default combined-engine mode each timed out at about 8 seconds without
returning hits. Individual engine probes for `air purifier reviews` returned
8 results from DuckDuckGo in 2.90 s, 5 from Bing in 4.82 s, and 8 from Google in
5.78 s. Google returned opaque click-through URLs that the app correctly
rejected. The final bounded path asks dedicated engine endpoints serially,
starting with DuckDuckGo, and moves on when a response has no usable links.
That adapter returned eight usable review links in 2.92 s. A complete web-source
read returned two fetched pages in 5.78 s. Search hits are leads; those counts
do not establish verified findings. Earlier live web attempts with verbose
queries and the old combined path produced no supported answer; query cleanup
and the engine fallback were added before the successful final measurement.

## Validation boundaries

Regression coverage includes independent conversation completion, preserving
message paragraphs, local token accumulation, web routing, public page and
redirect checks, queue claims, saved follow-up jobs, limiter contention, quick
gathering deadlines, progress before slow requests finish, and cancellation.
The complete `tools/gate.sh` passed with eight Python workers: 2,999 Python
tests passed, 18 skipped, 269 JavaScript tests passed, and 123 Rust tests passed.
Version agreement, Ruff, all three mypy stages, native Windows compilation and
the installed-wheel smoke check passed. Total gate time was 4 minutes 4 seconds.

The installed Windows Chat and Compare screens were inspected to reproduce the
usability problems. The changed desktop compiles, but its preview launch was
rejected by automatic policy review with “blocked by policy.” The changed
screens have not been visually verified in a new window. macOS packaging and
UI were not checked. Full deep research and every external provider were not
benchmarked; their completion time depends on model and source availability.
