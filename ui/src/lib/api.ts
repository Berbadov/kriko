import type * as T from "./types";

export class ApiError extends Error {
    constructor(
        public status: number,
        body: string,
    ) {
        super(`${status}: ${body}`);
        this.name = "ApiError";
    }
}

async function request<R>(path: string, init?: RequestInit): Promise<R> {
    const response = await fetch(path, init);
    if (!response.ok) throw new ApiError(response.status, await response.text());
    return (await response.json()) as R;
}

const get = <R>(path: string) => request<R>(path);

const postJson = <R>(path: string, body: unknown) =>
    request<R>(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
    });

const seg = encodeURIComponent;

export const api = {
    status: () => get<T.Status>("/api/status"),
    activity: (limit = 20) =>
        get<{ items: T.ActivityItem[]; malformed: number }>(
            `/api/activity?limit=${limit}`,
        ),
    packs: () => get<T.Pack[]>("/api/packs"),
    kinds: () => get<T.Kind[]>("/api/kinds"),
    identityKeys: (packId: string) =>
        get<T.IdentityKey[]>(`/api/identity-keys/${seg(packId)}`),
    vocabulary: (packId: string) =>
        get<T.Vocabulary>(`/api/packs/${seg(packId)}/vocabulary`),
    gaps: (packId: string) => get<T.Gap[]>(`/api/packs/${seg(packId)}/gaps`),
    subjects: (q: string, limit = 60) =>
        get<T.Subject[]>(`/api/subjects?limit=${limit}&q=${encodeURIComponent(q)}`),
    weakest: (limit = 40) =>
        get<{ claims: T.ClaimHealth[] }>(`/api/health/weakest?limit=${limit}`),
    healthSubject: (subjectId: string) =>
        get<T.HealthTree>(`/api/health/subject/${seg(subjectId)}`),
    revisions: (packId: string) =>
        get<T.Revision[]>(`/api/packs/${seg(packId)}/revisions`),
    events: (packId: string) => get<T.PackEvent[]>(`/api/packs/${seg(packId)}/events`),
    lookup: (body: T.LookupRequest) => postJson<T.LookupResult>("/api/lookup", body),
    analyze: (body: T.AnalyzeRequest) => postJson<T.AnalyzeResult>("/api/analyze", body),
    history: (limit = 20) =>
        get<{ items: T.HistoryItem[] }>(`/api/history?limit=${limit}`),
    getLookup: (lookupId: string) => get<T.StoredLookup>(`/api/lookup/${seg(lookupId)}`),
    settings: () => get<Record<string, unknown>>("/api/settings"),
    putSettings: (values: Record<string, unknown>) =>
        postJson<Record<string, unknown>>("/api/settings", { values }),
    checked: (lookupId: string) =>
        get<{ checked: string[] }>(`/api/lookups/${seg(lookupId)}/checked`),
    setChecked: (lookupId: string, claimKey: string, checked: boolean) =>
        postJson<{ checked: string[] }>(`/api/lookups/${seg(lookupId)}/checked`, {
            claim_key: claimKey,
            checked,
        }),
    adapters: () => get<T.Adapter[]>("/api/adapters"),
    subject: (subjectId: string) => get<T.SubjectDetail>(`/api/subjects/${seg(subjectId)}`),
    brief: (subjectId: string) =>
        get<T.Brief>(`/api/subjects/${seg(subjectId)}/brief`),
    jobs: (limit = 30) => get<{ items: T.Job[] }>(`/api/jobs?limit=${limit}`),
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
    installPack: (file: File) =>
        request<{ pack: T.Pack; revision: T.Revision }>("/api/packs/install", {
            method: "POST",
            headers: { "X-Filename": file.name },
            body: file,
        }),
};
