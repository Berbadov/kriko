# OpenResearch: reusable agent infrastructure for Kriko and other projects

Audit date: 14 October 2026. Reviewed with three GPT-6 Luna subagents and a root synthesis/review. The three tracks covered runtime speed, reliability, and research memory/tool efficiency.

OpenResearch source is pinned to [58eaa168380b95f2cca36907d8f627ae27280dd5](https://github.com/alphaXiv/OpenResearch/tree/58eaa168380b95f2cca36907d8f627ae27280dd5), version 0.2.18. Kriko base HEAD was `fe329b49e141c5330a82271d0457fc43d424592e`; comparisons include the existing working-tree edits. No application source or settings were changed. The external repository was cloned into a temporary directory. This is an implementation and test-source audit: we did not execute agents, benchmarks, or either project's test suite.

## Recommendation

Borrow specific infrastructure patterns. OpenResearch is a useful reference for protocol-based agent hosting, delivery-aware recovery, and reproducible execution. Kriko already has substantial evidence validation, job scheduling, checkpoints, cancellation, and discovery caching. Replacing those systems wholesale would add migration work without an established benefit.

The most useful near-term improvements are: close the Windows containment race; define a durable request/attempt contract before adding automatic retries; evaluate a Codex persistent transport with fresh threads; and enforce process-wide limits across concurrent jobs. Add immutable research-run provenance around Kriko's existing pack and evidence identities.

No numeric speedup is established by this audit. Persistent hosting mainly removes repeated process/config/protocol setup. It cannot remove model generation, all authentication work, or remote network latency.

## Repository architecture and scope

The open-source Rust application owns the CLI, local dashboard/API, SQLite state, coding-agent adapters, and execution backends. Its companion service owns accounts and managed compute provisioning; that separate service was outside this audit. See [repository guide](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/AGENTS.md).

The useful reading paths are:

| Area | OpenResearch implementation | Transfer to our projects |
|---|---|---|
| Agent contract | `src/local/harness/mod.rs`, provider adapters | Shared capabilities with provider-specific transports |
| Resident workers | `src/local/codex.rs`, `src/local/claude.rs` | Lower repeated-turn setup cost |
| Durable chat host | `src/local/chat/mod.rs`, `src/store.rs` | Request identity, delivery state, attempts, recovery |
| Compute | `src/compute.rs`, `src/jobs/*` | Reproducible input snapshots, backend lifecycle |
| Context/tools | `src/commands/logs.rs`, `src/local/agent_skills.rs` | Bounded reads, progressive instruction loading |
| Platform quality | `.github/workflows/ci.yml`, inline Rust tests | Real platform and failure-path checks |

These are runtime patterns relevant to other projects as well. The concrete adoption points below are based on the available Kriko workspace; no other private project was inspected.

## 1. Persistent protocol transport, with explicit context isolation

OpenResearch uses a long-lived Codex app-server child per chat session and persists the native thread ID. The host exchanges structured requests and receives events and approval requests over stdio. Replacement workers can resume native threads. Its Claude adapter holds a stream-JSON process open and sends successive messages through that resident process. See [Codex host](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/local/codex.rs#L1) and [Claude adapter](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/local/harness/claude.rs#L1).

Kriko's `HarnessResearcher` currently invokes a CLI per research call, with temporary run state and process-tree cleanup (`src/app/providers/harness.py:3040`, `3492`, `3534`). Its README explicitly promises a fresh chat per CLI research call.

Adopt an optional transport adapter that supports `start`, `create_context`, `run`, `interrupt`, and `close`. Start with one provider, preferably the structured app-server path, and keep the existing process-per-job fallback. Each independent product research job must create a fresh native thread. Reusing a provider process and reusing a conversation are separate decisions. A shared multi-thread worker would be our adaptation; OpenResearch itself normally retains one worker per chat.

Key worker identity should include executable/version, provider/account, model settings, working directory, permission policy, tool configuration, and isolated configuration home. A configuration change must replace or reconcile the worker. Route every event by request/thread/turn identity and reject late events belonging to an earlier run. Do not assume Claude's resident conversation can be reset safely between independent products; retain isolated processes where the protocol cannot enforce that boundary.

The existing startup benchmark reports median fresh one-word replies of 3.931 seconds for Claude, 4.355 for Codex, 7.743 for Antigravity, and 15.230 for Vibe, with three samples each (`docs/benchmarks/cli-startup-1.1.2.json`). These include setup, authentication, network, and generation. Separate `--help` timings do not isolate actual research startup. Measure cold process versus reused transport with a new context before deciding whether this complexity pays off.

## 2. Track delivery before deciding to retry

OpenResearch distinguishes `NotSent`, `Rejected`, `Accepted`, and `Unknown`. Not-sent/rejected requests can be retried; accepted/uncertain requests call for continuation or reconciliation. Its turn request hash covers messages, annotations, settings, and image identity. See [delivery states](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/local/chat/mod.rs#L2783) and [request hashing](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/local/chat/mod.rs#L6911).

Kriko already creates durable jobs, keeps partial results, interrupts orphaned rows on startup, and links one retry child to its parent (`src/app/web/jobs.py:360`, `368`; `src/app/web/state.py:2361`, `2447`). These are useful job-level safeguards. They do not by themselves establish whether an external provider accepted a particular request before a connection disappeared.

For the new transport, persist request ID, request hash, attempt ID, provider/native context ID, delivery state, and any output checkpoint before advancing. A repeated request ID with changed content should fail explicitly. After a crash, reconcile an accepted or uncertain request with the native context/provider handle before issuing a fresh request.

OpenResearch also caps host-owned retries at three and uses deterministic jitter and a 15-second retry budget ([retry implementation](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/local/harness/mod.rs#L174)). Copy the bounded policy shape, with cancellation and a visible retry status, rather than its exact constants. A disconnected paid model call or mutating action must not be replayed just because a timeout is considered transient. This pattern reduces duplicated work and spend; it is principally a robustness improvement.

## 3. Close the Windows process-containment race

Kriko already creates Windows Job Objects and kills process trees; POSIX children start in separate sessions. Preserve those mechanisms. However, its harness calls ordinary `Popen` at `src/app/providers/harness.py:3534` and assigns the child to the Job Object afterward at `3566`. A fast launcher can create descendants during that interval. This is a concrete launch-order gap, not evidence that all current cancellation fails.

OpenResearch's local compute launcher starts the child suspended, assigns it to the Job Object, records its handle/name, and only then resumes execution. Assignment failure kills and waits for the suspended child. See [Windows launcher](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/jobs/localbox/windows.rs#L33).

Adapt that ordering in the layer that owns Kriko's Windows subprocess launch. Verify actual descendants stop when the parent exits early, during cancellation, and during timeout. Test assignment failure and preserve hidden-window behavior. A mocked call to `taskkill` is insufficient proof. Keep in-process Python job cancellation cooperative, since forcibly stopping a handler during a store or pack write can corrupt work.

## 4. Bound concurrency across jobs and probe categories

OpenResearch limits simultaneous discovery children through a shared semaphore. The default is eight lanes, configurable, and permits survive blocked process creation. Queue time does not consume the individual probe's startup timeout. See [probe scheduling](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/local/harness/detect.rs#L18).

Kriko already deduplicates same-provider discovery and refreshes catalogs in the background. Its page reader uses pools of up to four workers (`src/app/providers/local_components/search.py:69`, `129`). OpenSERP search is deliberately sequential per Quick Look to avoid bursts/CAPTCHAs (`src/app/providers/local_agent.py:140`). Do not blindly raise those limits or fan out additional agents over the same queries.

The existing engine politeness scheduler is instantiated per researcher in `src/app/web/tasks.py:338`; its per-run source pacing is not a process-wide quota for every concurrent job or Quick Look. Its instance counters also should not simply be shared across threads without concurrency review. Multiple jobs can multiply outbound requests even while each obeys its own local policy.

Introduce shared, thread-safe host limits separately for CLI probes, owned agent processes, local inference/VRAM, and network source quotas. Acquire a provider/source permit at the actual request boundary. Keep rate limits and cooldowns shared across workers using the same account/source. Measure queue time separately from provider time so contention is visible rather than diagnosed as a slow model.

## 5. Warm workers need resource-aware eviction

OpenResearch checks physical RAM once and adjusts idle retention. Its default releases idle children after 15 minutes; machines at or below 8 GiB use two minutes and keep one idle child, with a 30-second grace against rapid churn. Active turns are protected. See [idle policy](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/local/agent_lifecycle.rs#L15).

This is useful only after resident workers exist. For our projects, measure worker RSS and local-model VRAM, then choose idle timeout and warm-worker limits suitable for the target machine. Preserve pending requests and native IDs before eviction. Avoid adopting an unlimited idle pool on a development laptop merely because its total RAM exceeds the upstream threshold.

## 6. Extend immutable research provenance

OpenResearch resolves a source commit, archives it, hashes the archive, and installs it under its content digest before executing. Backends consume a snapshot rather than whichever code happens to be in the agent's mutable worktree. See [source snapshot creation](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/compute.rs#L33).

Kriko already has pack content digests, revision snapshots, and evidence identities (`src/kriko/store/packstore.py:103`; `src/kriko/store/schema.sql:235`). Add a research-run manifest around these existing records: input/product identity, pack revision and principle digest, prompt/evaluator version, selected model and backend, settings, queries, source/evidence digests, coverage/rejection reasons, attempts, measured usage, and output digest. Keep input identity immutable while status and backend handles remain updateable. This makes reruns and failure comparisons useful without asking the model to remember everything.

There is an upstream caveat worth learning from: `src/store.rs:1106` assigns `commit_sha = excluded.commit_sha` on a conflicting run upsert. A later upsert can replace or clear the initial source revision. This behavior directly matches [issue #604](https://github.com/alphaXiv/OpenResearch/issues/604); it was verified in the pinned source. Content-addressed archives are valuable, but their existence alone does not guarantee immutable run metadata. Test immutability through late updates, null updates, and retry transitions.

## 7. Keep evidence binding in code

Kriko's local extraction is already a stronger fit for product findings than a generic research report: the model selects numbered evidence IDs and Python restores the original quote/URL, validates identity/support, and records coverage (`src/app/providers/local_pipeline.py:600`, `657`). Exact quote checks and abstention must remain intact when changing transport or concurrency.

OpenResearch's Git experiments and persisted logs complement this with execution provenance. For general coding/research projects, use source-span IDs for document claims and source snapshot/run IDs for measured claims. Distinguish a paper's reported measurement from an experiment our agent actually ran. A faster adapter that retains fewer verified findings is not an improvement.

## 8. Load instructions and large outputs on demand

OpenResearch separates native skill metadata, bodies, and lazily loaded reference resources ([skill catalog](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/local/agent_skills.rs#L29)). Its selected slash workflow expands server-side, while the stored transcript retains the compact command. Its log CLI reports the full file path, byte size, and a 500-character tail, prompting targeted search instead of loading the whole log ([log reader](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/commands/logs.rs#L7)).

Kriko already keeps its generated agent skill short, limits pack labels, and budgets source evidence against the inference context (`src/app/agentskill.py:101`; `src/app/providers/local_pipeline.py:600`). Keep those controls. Extend future long transcript/log tools with bounded summaries, offsets/cursors, and targeted search. Load category principles and detailed recipes for the selected task rather than inserting every workflow into every prompt. Record assembled prompt size and dropped evidence in the existing stage metrics.

## 9. Centralize local-versus-remote HTTP policy

OpenResearch creates HTTP clients through two constructors: loopback explicitly disables proxies, remote hosts honor proxy configuration. Clippy forbids direct client construction elsewhere. See [network policy](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/net.rs#L1) and [enforcement](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/clippy.toml).

Kriko's JSON helper and several local-runtime/search readers call `urllib.request.urlopen` directly (`src/app/providers/_http.py:57`, `local_inference.py:450`, `openserp.py:104`). There is no equivalent centralized explicit loopback rule in those paths. This is a portability hardening opportunity, not a reproduced proxy failure.

Route local inference/OpenSERP/sidecar requests through an explicit local client policy; keep internet requests compatible with the user's proxy/CA configuration. Separately benchmark whether reused HTTP connections help repeated calls. The upstream policy constructors by themselves are not evidence of a shared connection pool or a measured speed gain.

## 10. Preserve durable state; treat SSE as an optional delivery mechanism

OpenResearch atomically applies legal run transitions and preserves terminal outcomes ([status updates](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/store.rs#L1140)). Kriko already guards job start/finish transitions, retains partial results, and reconciles interrupted jobs. It does not need another generic job database.

For long-running jobs that outlive the host, OpenResearch offers durable cancellation intent, run locks, supervisor restart, rollback on failed supervisor launch, and persisted provider handles. Borrow this only when a Kriko backend gains detached execution; an ordinary HTTP research call does not need a full experiment supervisor.

Its run SSE endpoint includes a baseline, 500 ms status polling, byte-offset log chunks, and heartbeat comments, but lacks a durable Last-Event-ID replay contract and silently skips database read failures (`src/commands/serve.rs:187`). Kriko already has watched-row polling and durable pipeline events. If adding SSE, build it over those records with reconnect cursors and visible persistent errors; copying the upstream transport alone would not improve durability.

## 11. Capability gates and failure-focused quality checks

OpenResearch uses a conservative read-only command classifier: unknown/ambiguous shell commands remain gated, and compound stages must each pass classification ([plan gate](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/src/local/harness/plan_gate.rs#L163)). A capability must be supported by the detected provider/version before the host offers it. Preserve Kriko's tool restrictions and verify allowed operations at the actual protocol boundary when adding a new adapter. A UI toggle is not an execution sandbox.

Upstream CI runs formatting, Clippy, locked builds/tests, UI checks, and native Windows checks ([CI](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/.github/workflows/ci.yml)). These checks were inspected, not executed or independently certified. Kriko has a substantial local `tools/gate.sh` and a manually dispatched desktop build workflow; its current checkout lacks automatic PR tests. Its notes explain Actions-minute constraints. If capacity becomes available, prioritize automatic fast job/harness regression checks and real Windows containment tests. Keep native packaging observation for releases.

Two current upstream issue reports make useful adoption checks: [#647](https://github.com/alphaXiv/OpenResearch/issues/647) reports paid background calls despite a free-model selection; [#637](https://github.com/alphaXiv/OpenResearch/issues/637) reports outputs left in internal worktrees without clear links from the selected folder. These were not reproduced here. Explicitly bind any title/summary/helper call to the selected model and usage record, and give generated artifacts a discoverable final location. Avoid copying auxiliary model calls as an invisible part of worker warm-up.

## Adoption sequence and proof

| Step | Concrete result | Required evidence |
|---|---|---|
| 1 | Baseline the existing path | Cold launch, ready handshake, first event, completion, queue time, stage usage, failures; separate one-shot jobs from follow-ups |
| 2 | Harden Windows launch and request identity | Real fast-spawning descendants contained; repeat IDs deduplicate; changed content conflicts; cancellation retains partial work |
| 3 | Add one optional persistent protocol adapter | Fresh thread per independent job; explicit model/tool settings; old process path still available; crash and late-event tests |
| 4 | Add host-level limits and idle release | Concurrent jobs obey source/account quotas; probes don't starve runs; active workers never evicted; RAM/VRAM remains bounded |
| 5 | Extend research manifests and bounded readers | Input identity survives later updates; output/evidence IDs remain inspectable; reconnect/offset behavior verified |
| 6 | Expand only after paired evaluation | Lower latency at equal evidence quality, no extra unexplained spend, no context leakage, acceptable failure/cancel behavior |

For paired evaluation, alternate cold and warm cases using the same model/settings and fixed evidence fixtures. Measure first cold use separately from repeated use. Include at least two concurrent jobs, process death, provider rejection, uncertain delivery, delayed events, low memory, and cancel during a quiet request. Use existing precision/negative-coverage cases to check retention, unsupported claims, and abstention. Use distributions and failure counts rather than successful-run averages alone. Do not treat the existing three-sample one-word startup check as a research-quality comparison.

## What to defer

Remote GPU/Slurm/Kubernetes provisioning, LaTeX/Overleaf features, a full experiment-tree UI, and additional literature providers have little immediate bearing on product Quick Look latency. Independent chat spawning is useful, but it is not proof of a general task scheduler or that four agents beat one. Parallelize independent bounded work only after accounting for duplicated retrieval, model spend, merge overhead, and shared quotas.

Rewriting the Python engine in Rust is not supported by this comparison. Kriko's extraction budgets and verified evidence contracts are worth preserving while improving the interfaces around them.

The repository carries an [MIT license](https://github.com/alphaXiv/OpenResearch/blob/58eaa168380b95f2cca36907d8f627ae27280dd5/LICENSE). If copying implementation code, retain its copyright/license notice and record the source commit. This audit produced recommendations only; no upstream implementation was imported.
