# Agent runtime branch experiment

Branch: `codex/agent-runtime-1.6.2`, based on Kriko 1.6.2 commit
`399706f584274ebb35281aa7b0e9fdffb0061433`. This branch does not change the release version.

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
Select the installed Codex agent and your model through Agents. Its research
answer uses an app-server worker while each independent request starts a fresh
native thread. Search and page reading still happen through Kriko's existing
host readers, and findings still pass the existing evidence checks.

The mode is controllable without rebuilding:

- `KRIKO_CODEX_TRANSPORT=auto` is the default. It uses the persistent protocol
  when the installed CLI supports it. A capability/startup failure before
  prompt delivery can use the existing process path.
- `KRIKO_CODEX_TRANSPORT=persistent` requires the protocol and surfaces a
  startup failure instead of falling back.
- `KRIKO_CODEX_TRANSPORT=exec` uses the existing process path for comparison.

Persistent Codex runs rely on Kriko's host search and page reader because the
app-server receives no web tools. If every host search fails and the prompt
must ask Codex to search natively, `auto` selects the web-capable exec path
before sending that prompt; `persistent` reports the missing host search
instead of submitting a request the worker cannot fulfill.

The same choice is stored through `PUT /api/prefs` with
`{"codex_transport":"auto"}`, `"persistent"`, or `"exec"`. An explicitly set
environment variable wins. Other coding-agent CLIs continue using their existing
process adapters. No inference or background title request is made just to warm
a worker; it starts when requested work needs it.

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

The protocol currently supports the installed Codex app-server schema;
unsupported CLI installations keep the original adapter in auto mode. First
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

Repeat with the selected model explicitly named:

```text
python tools/bench_agent_transport.py --live --model <selected-model> --effort low --samples 3 --out <report.json>
```

`--live` is required because the script sends inference requests using the
selected CLI account. Raw measured usage and implementation hashes accompany
the timings. Source and fixtures were reviewed by Luna agents independently of
the components they implemented. Native macOS packaging and a new desktop
installer have not been exercised for this branch experiment.
