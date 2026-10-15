# Agent runtime

Began as the `codex/agent-runtime-1.6.2` experiment on Kriko 1.6.2 commit
`399706f584274ebb35281aa7b0e9fdffb0061433`; it ships in 1.7.0, where the persistent
protocol was extended from Codex to Claude Code and Mistral Vibe.

The [pinned OpenResearch audit](research/openresearch-agent-audit-2026-10-14.md)
records the source and adoption rationale. This is a Kriko adaptation; no
upstream implementation code was imported.

User request: "you know what, there is no harm of testing this in a branch.
implement each please Persistent protocol seems very important. hire Luna6s
again. 1.6.2 is getting released 1.6.2 is your base."

Done when: a branch based on 1.6.2 runs independent research through reusable
workers, retains verifiable request/attempt records, contains descendants,
respects shared resource limits, and preserves evidence validation; behavior
and failure checks pass and measured results are available for review.

## Run the experiment

Launch the sidecar from this checkout using the normal development commands.
Select an installed agent and your model through Agents. Its research
answer uses a resident worker (see the table below) while each independent
request starts a fresh conversation. Search and page reading still happen through Kriko's existing
host readers, and findings still pass the existing evidence checks.

The mode is controllable without rebuilding, and applies to every agent:

- `KRIKO_AGENT_TRANSPORT=auto` is the default. It uses the persistent protocol
  when the agent has one and the installed CLI supports it. A capability or
  startup failure before prompt delivery uses the existing process path.
- `KRIKO_AGENT_TRANSPORT=persistent` requires the protocol and surfaces a
  startup failure instead of falling back. For an agent with no persistent
  protocol (Antigravity) it reports that, naming the agent.
- `KRIKO_AGENT_TRANSPORT=exec` uses the existing process path for comparison.

`KRIKO_CODEX_TRANSPORT` and the `codex_transport` setting are the names this had
while only Codex had a worker; both are still read, the new name first.

The same choice is stored through `PUT /api/prefs` with
`{"agent_transport":"auto"}`, `"persistent"`, or `"exec"`. An explicitly set
environment variable wins. No inference or background title request is made
just to warm a worker; it starts when requested work needs it.

## One persistent protocol per agent

| Agent | Persistent protocol | How a request stays independent | Tools |
|---|---|---|---|
| Codex | `codex app-server` (`providers/codex_transport.py`) | A new thread and turn per request | None: shell, web and multi-agent disabled; pages come from Kriko's host reader |
| Claude Code | `claude -p --input-format stream-json --output-format stream-json` (`providers/resident.py`, `ClaudeWire`) | The worker is sent `/clear` before each reused request; the CLI answers `conversation_reset` and a new session id | The same `--allowedTools` allowlist, page-reader grant and budget flags as the process path |
| Mistral Vibe | `vibe-acp`, an Agent Client Protocol server (`AcpWire`) | A new ACP session per request, closed afterwards where the agent supports it | None: every permission request is refused with the agent's own reject option; pages come from the host reader |
| Antigravity | none: `agy` has a print mode only | n/a | n/a |

Claude Code and Vibe share one pool (`ResidentTransport`): a worker is reused
only when its complete profile matches (launch vector, executable stamp, folders,
a hash of the environment, model, effort); a request waits for a free slot under
the same host-wide child limit as every other adapter; an interrupted worker
that does not confirm it stopped within two seconds is killed; idle workers are
released after 15 minutes (2 minutes on a machine with 8 GB or less), and any
other adapter that needs a slot releases them first. Failures before the prompt
is written (the executable, the handshake, the `/clear`) are `TransportUnavailable`,
which `auto` answers with a fresh process. After the prompt is written, a crash,
timeout or lost worker is `DeliveryUncertain` and is never replayed. The ledger
records the same delivery states for every agent.

What this does not do:

- A run the reader can answer mid-run (Claude Code's conversational mode) needs
  its own process's stdin and keeps using it, in every mode.
- A resident Claude Code worker reads its login when it starts, so a new login
  takes effect after it idles out or Kriko restarts. Codex's worker is replaced
  when its account file changes; Claude Code keeps its account in places Kriko
  does not read.
- Claude Code and Vibe run in an empty folder that lives as long as the worker;
  as on the process path, Claude Code uses the reader's own home and login.
- Vibe's worker has no web tools. If every host search fails, `auto` runs that
  one request through a process, which does; `persistent` reports it instead.
- A `.cmd` launcher (Windows npm installs) needs a shell and falls back to a
  process.

## Implemented behavior

| Improvement | Behavior and primary implementation |
|---|---|
| Persistent protocol | Resident NDJSON worker, fresh thread/turn per request, explicit model/effort, bounded events, absolute deadline and stage timings: `providers/codex_transport.py` |
| Context isolation | Owned configuration home and empty work folder; worker identity includes executable, intended account, model, permissions and configuration. Native cache refresh does not invalidate identity: `providers/codex_profile.py` |
| Durable recovery | Immutable input manifest, atomic request/job reservation, attempt delivery states, result digests, usage and crash-window reconciliation: `agentledger.py`, `web/jobs.py` |
| Implementation identity | Submission snapshots include package version, pack revision, principle digest, and prompt/evaluator source digest. Source availability is explicit, including installations without readable source files. |
| Windows containment | Start suspended, assign the Job Object, then resume; stop descendants even if the launcher exits: `processcontrol.py` |
| Shared limits | Host-wide child/probe/inference/outbound limits, per-source limits and paced search, cancellable waits, eligible-source fairness: `agentresources.py`, `providers/network.py` |
| Resource-aware retention | Idle-worker eviction adjusted for physical RAM; active workers are protected. Switching to a process adapter releases idle protocol workers so they cannot monopolize child slots. |
| Bounded inspection | Manifest index, limited log tail/search/cursors, and persisted SSE event IDs with reconnect support: `web/routers/agent_runtime.py` |
| Request deduplication | Research, Quick Look follow-up and filing requests accept `client_request_id`. The extension retains the exact request and ID through lost responses/restarts; confirmed receipts clear the intent. |
| Local network/cancellation | Loopback traffic bypasses proxies; remote traffic retains normal proxy/CA behavior. Local streamed and structured completions check cancellation on the SQLite-owning thread and interrupt silent response reads. |

Protocol requests grant no dynamic tools or user MCP servers and disable shell,
web search and multi-agent tools. Native read-only sandboxing is explicit.
Denied command/file/MCP activity, mismatched events and ambiguous delivery do
not silently launch another model request. Assistant commentary is kept out of
the final structured answer. Usage is recorded from the provider, including
nested app-server token reports; unavailable cost remains unavailable.

Cancellation interrupts the exact thread/turn. An unsettled worker is
quarantined and terminated. A request marked accepted or delivery-unknown is
not automatically replayed after a crash. Startup closes stranded manifests
as interrupted and records the recovery classification. This branch preserves
records and avoids duplicate work; it does not automatically resume a native
conversation after the application has restarted. Explicit Retry remains a new
auditable job.

## Limits

`KRIKO_RESOURCE_PROFILE` accepts `quiet`, `balanced` (default), or `fast`.
Advanced bounds are `KRIKO_MAX_AGENT_CHILDREN`, `KRIKO_MAX_PROBES`,
`KRIKO_MAX_OUTBOUND`, `KRIKO_MAX_PER_SOURCE`, and
`KRIKO_MAX_LOCAL_INFERENCE`. Values are clamped; raising concurrency does not
override a provider's rate limits. Independent agent hosts in different
operating-system processes do not share this process-local limiter.

Each protocol is checked against the installed CLI (`app-server --help` for
Codex, `--input-format` for Claude Code, a `vibe-acp` beside `vibe`);
installations without it keep the process adapter in auto mode. First
use still pays for process creation, authentication, a fresh context and model
generation. A resident process does not promise an instant response.

## Inspect a run

For a durable job ID, the API provides:

- `GET /api/jobs/{id}/manifest`: input identity, immutable policy/pack snapshot,
  result digest, coverage, usage, and up to 50 attempts. It excludes assembled
  inputs, final-answer copies, filesystem settings and raw provider errors.
- `GET /api/jobs/{id}/log?tail=true&limit=6000`: a bounded log tail.
  Character cursors and a literal `q` search allow targeted follow-up reads.
- `GET /api/jobs/{id}/events`: baseline followed by persisted event IDs;
  `Last-Event-ID` resumes after an observed event. A state-read failure emits
  an error event; terminal runs close the stream.

The existing job/history endpoints and product evidence contracts remain the
interfaces used by the desktop and extension.

## Validation and measurements

The Windows gate passed: Ruff, mypy for engine/app/packs, **2,739 Python tests
passed with 18 skipped**, the wheel import/CLI smoke, **269 Node tests**, and
native Windows `cargo check` plus **84 Rust tests**. The final provenance change
also passed the focused checks and the clean installed-wheel smoke below.

The behavioral tests cover process reuse and fresh contexts, native cache
refresh, differing profiles, worker saturation, phase filtering, silent-turn
cancellation, deadlines, denied capabilities, immutable provenance, concurrent
request/attempt identity, late callbacks, restart/crash windows, bounded readers,
proxy handling, local inference interruption, and Windows descendants.

The real installed CLI returned `SET` for a codeword in one request and `NONE`
when the next independent request asked whether a codeword had previously been
provided in its conversation. The context IDs differed and the second request
reused the worker. Both attempts recorded accepted/succeeded and their token
counts. A Windows database-handle cleanup issue found during this smoke was
fixed and separately verified by immediate database rename and temporary-folder
cleanup without garbage collection.

An isolated installed-wheel smoke imported the new runtime modules, confirmed
that its prompt/evaluator digest matched the checkout, and repeated the Windows
ledger rename/cleanup check. The final 26-test focused run covered manifests,
request identity, inspection endpoints, and the research transport integration.

The [paired benchmark](benchmarks/2026-10-14-persistent-transport.json) used two
cold and two warm one-word requests with the same selected model/settings and a
fresh thread each time. All completed; warm rows report actual worker reuse and
zero process/handshake startup. Median end-to-end time was **3.69 seconds cold**
and **3.37 seconds warm**. Warm-up was **9.61 seconds** and is reported separately.
This is a small startup smoke, not a research-quality evaluation or a general
latency guarantee. Provider caching and generation varied, and measured input
token totals differed. It does not compare this adapter against legacy exec.

The retained [pre-fix trace](benchmarks/2026-10-14-persistent-transport-pre-fix.json)
shows why checking the reply alone was inadequate: native model-cache writes
invalidated worker identity, so nominal warm calls were actually respawns.
That defect is fixed and covered by a behavioral regression test.

Claude Code was also checked against the real CLI at 2.1.299 through the
harness: two requests ran on one process (3.9 s cold, 2.3 s warm), and the second,
asked for a codeword the first had been given, answered `NONE` after the
`/clear`. `vibe-acp` 2.26.1 accepted the handshake and session and reached the
provider with a prompt; no Mistral key was available, so a completed Vibe
answer was not observed.

Repeat with the selected model explicitly named:

```text
python tools/bench_agent_transport.py --live --model <selected-model> --effort low --samples 3 --out <report.json>
```

`--live` is required because the script sends inference requests using the
selected CLI account. Raw measured usage and implementation hashes accompany
the timings. Source and fixtures were reviewed by Luna agents independently of
the components they implemented. Native macOS packaging and a new desktop
installer have not been exercised for this branch experiment.
