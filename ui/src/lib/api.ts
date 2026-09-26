import type * as T from "./types";

export class ApiError extends Error {
    /** The server's own last stack frames, when it sent any. */
    public trace: string[] = [];

    constructor(
        public status: number,
        body: string,
    ) {
        super(`${status}: ${body}`);
        this.name = "ApiError";
    }
}

/**
 * The readable half of a failed response.
 *
 * FastAPI puts a handled error's reason in `detail`, and `app/web/app.py`'s
 * unhandled-error handler puts an exception's type and message there too. What
 * the reader used to see instead was the whole JSON body, or — before that
 * handler existed — the literal words "Internal Server Error", which named
 * nothing. A local app has one reader and no log viewer: whatever this returns
 * is the entire diagnosis available to them.
 */
function explain(body: string): { message: string; trace: string[] } {
    try {
        const parsed = JSON.parse(body) as {
            detail?: unknown;
            trace?: unknown;
        };
        const detail = parsed.detail;
        const trace = Array.isArray(parsed.trace)
            ? parsed.trace.map(String)
            : [];
        if (typeof detail === "string" && detail) return { message: detail, trace };
        // A 422 from pydantic sends `detail` as a list of {loc, msg, type} —
        // one per field that failed. Read as "field: reason" it names exactly
        // what to change; read as JSON.stringify it is `[{"loc":["body",...`,
        // which named nothing more than the generic "422" already did.
        if (Array.isArray(detail) && detail.length) {
            const readable = detail
                .map((one) => {
                    if (
                        one && typeof one === "object" && "msg" in one
                        && typeof (one as { msg: unknown }).msg === "string"
                    ) {
                        const loc = (one as { loc?: unknown }).loc;
                        const field = Array.isArray(loc) ? String(loc.at(-1)) : "";
                        const msg = (one as { msg: string }).msg;
                        return field ? `${field}: ${msg}` : msg;
                    }
                    return JSON.stringify(one);
                })
                .join("; ");
            return { message: readable, trace };
        }
        if (detail !== undefined) return { message: JSON.stringify(detail), trace };
        return { message: body, trace };
    } catch {
        return { message: body, trace: [] };
    }
}

async function request<R>(path: string, init?: RequestInit): Promise<R> {
    const response = await fetch(path, init);
    if (!response.ok) {
        const { message, trace } = explain(await response.text());
        const error = new ApiError(response.status, message);
        error.trace = trace;
        throw error;
    }
    return (await response.json()) as R;
}

const get = <R>(path: string) => request<R>(path);

const postJson = <R>(path: string, body: unknown) =>
    request<R>(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
    });

const putJson = <R>(path: string, body: unknown) =>
    request<R>(path, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
    });

const del = <R>(path: string) => request<R>(path, { method: "DELETE" });

const seg = encodeURIComponent;

export const api = {
    health: () => get<T.Health>("/api/health"),
    status: () => get<T.Status>("/api/status"),
    activity: (limit = 20) =>
        get<{ items: T.ActivityItem[]; malformed: number }>(
            `/api/activity?limit=${limit}`,
        ),
    packs: () => get<T.Pack[]>("/api/packs"),
    kinds: () => get<T.Kind[]>("/api/kinds"),
    agentConfig: () => get<T.AgentConfig>("/api/agent-config"),
    agentTargets: () => get<T.AgentTargets>("/api/agent-targets"),
    agentSkill: () => get<T.AgentSkill>("/api/agent-skill"),
    // What to research next. A GET with no job behind it — see routers/agenda.py.
    agenda: () => get<T.Agenda>("/api/agenda"),
    verifyAgent: () => postJson<T.AgentVerify>("/api/agent-verify", {}),
    connectAgent: (targetId: string) =>
        postJson<T.AgentTarget>(`/api/agent-targets/${seg(targetId)}/connect`, {}),
    extension: () => get<T.ExtensionStatus>("/api/extension"),
    stageExtension: () => postJson<T.ExtensionStaged>("/api/extension/stage", {}),
    revealExtension: () => postJson<T.ExtensionRevealed>("/api/extension/reveal", {}),
    // Stages *and* opens a browser, in one request, because one press by the
    // reader must not be able to half-succeed. See the router's docstring.
    launchExtension: () => postJson<T.ExtensionLaunched>("/api/extension/launch", {}),
    identityKeys: (packId: string) =>
        get<T.IdentityKey[]>(`/api/identity-keys/${seg(packId)}`),
    vocabulary: (packId: string) =>
        get<T.Vocabulary>(`/api/packs/${seg(packId)}/vocabulary`),
    gaps: (packId: string) => get<T.Gap[]>(`/api/packs/${seg(packId)}/gaps`),
    /** Labels a page carried that no installed adapter reads.
     *
     * A coverage gap in the *reading*, where `gaps` above is a gap in the
     * knowledge. High `seen` plus a recent `last_at` on a site that used to
     * work is a site that renamed a field — which otherwise arrives as claims
     * quietly going missing. */
    unmappedLabels: (limit = 100) =>
        get<{ labels: T.UnmappedLabel[] }>(`/api/adapters/unmapped?limit=${limit}`),
    forgetLabel: (adapterId: string, label: string) =>
        del<{ forgotten: boolean }>(
            `/api/adapters/unmapped/${seg(adapterId)}/${seg(label)}`,
        ),
    marks: (verdict = "") =>
        get<T.Marks>(`/api/marks${verdict ? `?verdict=${seg(verdict)}` : ""}`),
    /** What the marks add up to — the two queues, not the raw list. */
    markSignals: (limit = 50) => get<T.MarkSignals>(`/api/marks/signals?limit=${limit}`),
    unmark: (packId: string, claimId: string) =>
        del<{ removed: boolean }>(`/api/marks/${seg(packId)}/${seg(claimId)}`),
    subjects: (q: string, limit = 60) =>
        get<T.Subject[]>(`/api/subjects?limit=${limit}&q=${encodeURIComponent(q)}`),
    weakest: (limit = 40) =>
        get<{ claims: T.ClaimHealth[] }>(`/api/health/weakest?limit=${limit}`),
    healthSubject: (subjectId: string) =>
        get<T.HealthTree>(`/api/health/subject/${seg(subjectId)}`),
    revisions: (packId: string) =>
        get<T.Revision[]>(`/api/packs/${seg(packId)}/revisions`),
    events: (packId: string) => get<T.PackEvent[]>(`/api/packs/${seg(packId)}/events`),
    /** Write a new pack's skeleton to disk. Installs nothing — building is a job. */
    scaffoldPack: (body: T.NewPack) =>
        postJson<{ root: string; files: string[] }>("/api/packs/scaffold", body),
    /** Have the reader's own coding agent write a whole pack from a category.
     *
     * One argument, because the rest — the id, the name, the identity table,
     * the bar, the searches — is category knowledge, and an agent that has
     * read the category decides it better than a reader who has not. A job
     * rather than a request: it spawns an agent that searches for minutes, and
     * the reply is worth outliving the page. Installs nothing.
     */
    authorPack: (category: string, harness = "") =>
        postJson<{ job_id: string; kind: string }>(
            "/api/packs/author",
            harness ? { category, harness } : { category },
        ),
    // Packs an agent drafted. It writes files and installs nothing, so the
    // install below is the only way one of these reaches the store.
    packDrafts: () => get<{ items: T.PackDraft[] }>("/api/packs/drafts"),
    /** What a draft holds and what of its own line-up it does not cover. */
    packDraft: (slug: string) =>
        get<T.DraftState>(`/api/packs/drafts/${seg(slug)}`),
    /** Ask an agent for what this draft is missing. Adds; never rewrites. */
    amendPackDraft: (slug: string, note: string, harness = "") =>
        postJson<{ job_id: string; kind: string }>(
            `/api/packs/drafts/${seg(slug)}/amend`,
            harness ? { note, harness } : { note },
        ),
    /** Re-read the sources behind everything on this screen. A job: forty
     *  claims at three fetches each is minutes, not a press. */
    verify: (body: { pack_id?: string; subject_id?: string; limit?: number }) =>
        postJson<{ job_id: string; kind: string }>("/api/verify", body),
    installPackDraft: (slug: string) =>
        postJson<{ slug: string; pack_id: string }>(
            `/api/packs/drafts/${seg(slug)}/install`,
            {},
        ),
    discardPackDraft: (slug: string) =>
        del<{ slug: string }>(`/api/packs/drafts/${seg(slug)}`),
    lookup: (body: T.LookupRequest) => postJson<T.LookupResult>("/api/lookup", body),
    analyze: (body: T.AnalyzeRequest) => postJson<T.AnalyzeResult>("/api/analyze", body),
    history: (limit = 20) =>
        get<{ items: T.HistoryItem[] }>(`/api/history?limit=${limit}`),
    getLookup: (lookupId: string) => get<T.StoredLookup>(`/api/lookup/${seg(lookupId)}`),
    settings: () => get<Record<string, unknown>>("/api/settings"),
    putSettings: (values: Record<string, unknown>) =>
        postJson<Record<string, unknown>>("/api/settings", { values }),
    /** Every re-check this app has done, in one request: a report shows
     * forty claims, and forty requests to say "not checked yet" is not a
     * feature. */
    factChecks: () => get<T.FactChecks>("/api/factcheck"),
    /** Re-read the pages behind one claim. The quote is never sent — the
     * server checks the one the installed pack shipped. */
    checkFacts: (packId: string, claimId: string) =>
        postJson<T.FactCheck>("/api/factcheck", {
            pack_id: packId,
            claim_id: claimId,
        }),
    /** Per-evidence grounded/ungrounded/not_kept for one claim, offline — no
     *  network and no re-fetch, unlike `checkFacts` above. */
    grounding: (packId: string, claimId: string) =>
        get<T.Grounding>(
            `/api/factcheck/grounding?pack_id=${seg(packId)}&claim_id=${seg(claimId)}`,
        ),
    /** The retained page text behind one piece of evidence. 404 when this
     *  install never kept a copy of that source. */
    document: (sourceId: string) =>
        get<T.RetainedDocument>(`/api/factcheck/document?source_id=${seg(sourceId)}`),
    /** Both halves of the reader's own marks on one stored answer. */
    triage: (lookupId: string) =>
        get<T.Triage>(`/api/lookups/${seg(lookupId)}/triage`),
    setNote: (lookupId: string, claimKey: string, note: string) =>
        postJson<{ notes: Record<string, string> }>(
            `/api/lookups/${seg(lookupId)}/notes`,
            { claim_key: claimKey, note },
        ),
    /** The operations feed. `after` is an id: 0 means "the newest page",
     *  anything else means "everything since". See `lib/operations.ts`.
     *
     *  `watch` is the ids the caller still believes are open. Without it the
     *  feed only ever hears an operation *begin*: a row is written twice, and
     *  the second write is an update to a row whose id is already behind the
     *  cursor, so every line on screen said "running" until a reload. */
    operations: (limit = 50, after = 0, watch: number[] = []) =>
        get<T.Operations>(
            `/api/operations?limit=${limit}&after_id=${after}` +
                (watch.length ? `&watch=${watch.join(",")}` : ""),
        ),
    submissions: (limit = 30) =>
        get<T.Submissions>(`/api/submissions?limit=${limit}`),
    /* Run it again — optionally carrying answers to what it asked last time.
     *
     * Answers ride on the *retry* rather than on a reply endpoint because
     * there is no paused run to reply to: the identification pass never
     * blocked (see `app/disambiguate.py`). Posting `{}` is still the plain
     * "run it again", which is what every existing caller does. */
    retryJob: (jobId: string, answers: Record<string, string> = {}) =>
        postJson<{ job_id: string; kind: string }>(
            `/api/jobs/${seg(jobId)}/retry`,
            { answers },
        ),
    checked: (lookupId: string) =>
        get<{ checked: string[] }>(`/api/lookups/${seg(lookupId)}/checked`),
    setChecked: (lookupId: string, claimKey: string, checked: boolean) =>
        postJson<{ checked: string[] }>(`/api/lookups/${seg(lookupId)}/checked`, {
            claim_key: claimKey,
            checked,
        }),
    adapters: () => get<T.Adapter[]>("/api/adapters"),
    /** Rewrite one harness's skill from the packs installed right now. */
    refreshAgentSkill: (targetId: string) =>
        postJson<{ target: string; skill: string | null }>(
            `/api/agent-targets/${seg(targetId)}/skill`,
            {},
        ),
    /** Which sites can be read here, and which were asked for. */
    sites: () => get<T.Sites>("/api/sites"),
    registerSite: (host: string, url = "", harness = "") =>
        postJson<{ job_id: string; host: string }>(
            `/api/sites/${seg(host)}/register`,
            harness ? { url, harness } : { url },
        ),
    forgetSite: (host: string) =>
        del<{ host: string; forgotten: boolean }>(`/api/sites/${seg(host)}`),
    /** What the reader chose: which agent, which LLM, which search. */
    /** `fresh` re-asks every CLI for its LLM list instead of the cached one. */
    prefs: (fresh = false) => get<T.Prefs>(fresh ? "/api/prefs?fresh=true" : "/api/prefs"),
    savePrefs: (values: Partial<Record<string, string>>) =>
        putJson<T.Prefs>("/api/prefs", values),
    /** What it has cost, and what the next run is likely to. */
    costs: () => get<T.Costs>("/api/costs"),
    /** Every position on the depth dial, with this installation's estimate.
     *
     *  Fetched rather than restated. `app/scale.py` owns the numbers, and the
     *  one place that had copied them — the benchmark screen's own preset
     *  list — is the hand-maintained correspondence this repository keeps
     *  catching going stale (`SIBLING_CODE_FAMILIES`, `_MAKE_MAP`, the site's
     *  own words in `extension/`). A dial whose label and whose number can
     *  disagree is a dial that eventually lies about what it will spend. */
    scales: () => get<T.Scales>("/api/scales"),
    /** A route another process asked this window to show, consumed once. */
    focus: () => get<{ route: string | null }>("/api/focus"),
    subject: (subjectId: string) => get<T.SubjectDetail>(`/api/subjects/${seg(subjectId)}`),
    brief: (subjectId: string) =>
        get<T.Brief>(`/api/subjects/${seg(subjectId)}/brief`),
    jobs: (limit = 30) => get<{ items: T.Job[] }>(`/api/jobs?limit=${limit}`),
    /** Runs of the knowledge pipeline, newest first, plus the stage names —
     *  which come from the server because the stage vocabulary is the
     *  server's, and a second copy here is a second place to forget. */
    pipelineRuns: (limit = 30) =>
        get<{ runs: T.PipelineRun[]; stages: { stage: string; label: string }[] }>(
            `/api/pipeline/runs?limit=${limit}`,
        ),
    pipelineRun: (runId: string, after = 0) =>
        get<T.PipelineFrame>(`/api/pipeline/runs/${seg(runId)}?after=${after}`),
    job: (jobId: string) => get<T.Job>(`/api/jobs/${seg(jobId)}`),
    research: (body: T.ResearchRequest) =>
        postJson<{ job_id: string; kind: string }>("/api/research", body),
    /** Which planes exist and what each costs. Server-side vocabulary — see
     *  the router's docstring for why it is not restated here. */
    /** The planes, plus which one an unnamed run resolves to on this machine.
     *
     * `default` is resolved server-side at request time rather than assumed
     * here: whether a coding-agent CLI is installed is a fact about the
     * machine, and a frontend that guessed it would eventually mark the wrong
     * card. */
    researchPlanes: (selection: T.RunSelection = {}) =>
        get<{ planes: T.ResearchPlane[]; default?: string }>(
            `/api/research-planes${Object.keys(selection).length ? `?${new URLSearchParams(selection)}` : ""}`,
        ),
    /** Walk the agenda unattended. One job for the whole run: `agenda_run`
     *  calls the research path inline, because the job runner has a single
     *  worker and a job that submits jobs deadlocks. */
    runAgenda: (body: T.AgendaRunRequest) =>
        postJson<{ job_id: string; kind: string }>("/api/agenda/run", body),
    /** The sums. Two halves — what writing claims in cost, and how much
     *  reading them back out this installation has actually done. */
    usage: () => get<T.Usage>("/api/usage"),
    /** The unattended loop: what it is set to, and what it last decided. */
    schedule: () => get<T.Schedule>("/api/schedule"),
    /** A partial save. Every field is optional on the wire so that saving the
     *  one control the reader touched cannot reset the other five. */
    saveSchedule: (body: T.ScheduleRequest) => putJson<T.Schedule>("/api/schedule", body),
    /** One tick, now. The answer is the sentence the loop would have recorded
     *  — refusals included, which are the ones worth reading. */
    checkSchedule: () => postJson<T.ScheduleCheck>("/api/schedule/check", {}),
    researchRuns: (limit = 50) =>
        get<{ runs: T.ResearchRun[] }>(`/api/research-runs?limit=${limit}`),
    researchRun: (runId: string) =>
        get<T.ResearchRunDetail>(`/api/research-runs/${seg(runId)}`),
    /** Take a run's claims back out. A job, because it writes once per claim. */
    undoResearchRun: (runId: string) =>
        del<{ job_id: string; kind: string }>(`/api/research-runs/${seg(runId)}`),
    /** What is stored, masked. This never returns a key — `app/keys.py`'s
     *  `require` is the only function that reads one and it is in-process. */
    keys: () => get<T.ApiKeys>("/api/keys"),
    putKeys: (values: Record<string, string>) =>
        request<T.ApiKeys>("/api/keys", {
            method: "PUT",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ values }),
        }),
    forgetKey: (providerId: string) =>
        del<T.ApiKeys>(`/api/keys/${seg(providerId)}`),
    buildPack: (root: string, install = true) =>
        postJson<{ job_id: string; kind: string }>("/api/packs/build", { root, install }),
    cancelJob: (jobId: string) =>
        request<{ job_id: string; state: string }>(`/api/jobs/${seg(jobId)}/cancel`, {
            method: "POST",
        }),
    /** Say something to a job that is still running.
     *
     * `delivered` is false when the run ended while the reader was typing —
     * not a failure, and not something to show as one, but not something to
     * report as landed either. */
    sayToJob: (jobId: string, text: string) =>
        request<{ job_id: string; delivered: boolean }>(`/api/jobs/${seg(jobId)}/say`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ text }),
        }),
    forget: (lookupId: string) =>
        request<{ deleted: boolean }>(`/api/history/${seg(lookupId)}`, {
            method: "DELETE",
        }),
    setEnabled: (packId: string, enabled: boolean) =>
        request<unknown>(`/api/packs/${seg(packId)}/enabled?enabled=${enabled}`, {
            method: "POST",
        }),
    activate: (packId: string, revision: string) =>
        request<unknown>(
            `/api/packs/${seg(packId)}/activate?revision=${encodeURIComponent(revision)}`,
            { method: "POST" },
        ),
    packUpdates: () => get<T.PackUpdates>("/api/packs/updates"),
    updatePacks: (packId?: string) =>
        postJson<{ job_id: string; kind: string }>("/api/packs/update", {
            pack_id: packId ?? null,
        }),
    installPack: (file: File) =>
        request<{ pack: T.Pack; revision: T.Revision }>("/api/packs/install", {
            method: "POST",
            headers: { "X-Filename": file.name },
            body: file,
        }),
    bench: () => get<T.Bench>("/api/bench"),
    estimateBench: (body: T.BenchRequest) => postJson<T.BenchEstimate>("/api/bench/estimate", body),
    benchConfigs: () => get<{ configs: Record<string, T.BenchRequest> }>("/api/bench/configs"),
    saveBenchConfig: (name: string, config: T.BenchRequest) =>
        putJson<{ configs: Record<string, T.BenchRequest> }>("/api/bench/configs", { name, config }),
    forgetBenchConfig: (name: string) =>
        del<{ configs: Record<string, T.BenchRequest> }>(`/api/bench/configs/${seg(name)}`),
    startBench: (body: T.BenchRequest = {}) =>
        postJson<{ job_id: string; kind: string }>("/api/bench", body),
    testKey: (providerId: string) =>
        postJson<T.ProviderTest>("/api/keys/test", { provider: providerId }),
};
