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
    verifyAgent: () => postJson<T.AgentVerify>("/api/agent-verify", {}),
    connectAgent: (targetId: string) =>
        postJson<T.AgentTarget>(`/api/agent-targets/${seg(targetId)}/connect`, {}),
    extension: () => get<T.ExtensionStatus>("/api/extension"),
    stageExtension: () => postJson<T.ExtensionStaged>("/api/extension/stage", {}),
    revealExtension: () => postJson<T.ExtensionRevealed>("/api/extension/reveal", {}),
    identityKeys: (packId: string) =>
        get<T.IdentityKey[]>(`/api/identity-keys/${seg(packId)}`),
    vocabulary: (packId: string) =>
        get<T.Vocabulary>(`/api/packs/${seg(packId)}/vocabulary`),
    gaps: (packId: string) => get<T.Gap[]>(`/api/packs/${seg(packId)}/gaps`),
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
    lookup: (body: T.LookupRequest) => postJson<T.LookupResult>("/api/lookup", body),
    analyze: (body: T.AnalyzeRequest) => postJson<T.AnalyzeResult>("/api/analyze", body),
    history: (limit = 20) =>
        get<{ items: T.HistoryItem[] }>(`/api/history?limit=${limit}`),
    getLookup: (lookupId: string) => get<T.StoredLookup>(`/api/lookup/${seg(lookupId)}`),
    settings: () => get<Record<string, unknown>>("/api/settings"),
    putSettings: (values: Record<string, unknown>) =>
        postJson<Record<string, unknown>>("/api/settings", { values }),
    /** Both halves of the reader's own marks on one stored answer. */
    triage: (lookupId: string) =>
        get<T.Triage>(`/api/lookups/${seg(lookupId)}/triage`),
    setNote: (lookupId: string, claimKey: string, note: string) =>
        postJson<{ notes: Record<string, string> }>(
            `/api/lookups/${seg(lookupId)}/notes`,
            { claim_key: claimKey, note },
        ),
    submissions: (limit = 30) =>
        get<T.Submissions>(`/api/submissions?limit=${limit}`),
    retryJob: (jobId: string) =>
        postJson<{ job_id: string; kind: string }>(
            `/api/jobs/${seg(jobId)}/retry`,
            {},
        ),
    checked: (lookupId: string) =>
        get<{ checked: string[] }>(`/api/lookups/${seg(lookupId)}/checked`),
    setChecked: (lookupId: string, claimKey: string, checked: boolean) =>
        postJson<{ checked: string[] }>(`/api/lookups/${seg(lookupId)}/checked`, {
            claim_key: claimKey,
            checked,
        }),
    adapters: () => get<T.Adapter[]>("/api/adapters"),
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
    buildPack: (root: string, install = true) =>
        postJson<{ job_id: string; kind: string }>("/api/packs/build", { root, install }),
    cancelJob: (jobId: string) =>
        request<{ job_id: string; state: string }>(`/api/jobs/${seg(jobId)}/cancel`, {
            method: "POST",
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
};
