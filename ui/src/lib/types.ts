export type Status = {
    ok: boolean;
    packs: number;
    enabled_packs: number;
    counts: Record<string, number>;
};

export type ActivityItem = {
    timestamp?: string;
    created_at?: string;
    url?: string;
    method?: string;
    coverage?: string;
    claim_titles?: string[];
};

export type Pack = {
    pack_id: string;
    name: string;
    version: string;
    enabled: boolean | number;
    subjects: number;
    claims: number;
    evidence: number;
    digest: string;
};

export type Kind = { kind: string; pack_id: string };
export type IdentityKey = { key: string };
export type Term = { term_id: string; unit: string };
export type Vocabulary = { context_key?: Term[] } & Record<string, Term[] | undefined>;

export type Source = {
    url?: string;
    domain: string;
    quote: string;
    stance: string;
    tier: string;
};

export type Claim = {
    title: string;
    body: string;
    advice?: string;
    severity: string;
    domain?: string;
    subject: string;
    relevance: number;
    disputed?: boolean;
    pack_id: string;
    why?: string[];
    sources?: Source[];
};

export type LookupResult = {
    method: string;
    coverage?: string;
    flags?: string[];
    claims: Claim[];
    lookup_id?: string;
};

export type AnalyzeResult = LookupResult & {
    adapter: string;
    packs: { pack_id: string; version: string }[];
    context_units: Record<string, string>;
    identity: Record<string, unknown>;
    context: Record<string, unknown>;
    unmapped_labels: string[];
};

export type Subject = {
    subject_id?: string;
    label: string;
    kind: string;
    pack_id: string;
    claims: number;
};

export type Gap = { label: string; kind: string };

export type ClaimHealth = {
    claim_id: string;
    subject_id: string;
    subject_label: string;
    pack_id: string;
    title: string;
    refuted_by: number;
    independent_sources: number;
    best_tier: string;
    best_trust: number;
    oldest_retrieved_at: string | null;
    concern: unknown;
};

export type EvidenceRow = {
    quote: string;
    domain: string;
    tier: string;
    stance: string;
    independent: boolean;
    retrieved_at: string | null;
};

export type HealthTree = {
    label?: string;
    claims: { health: ClaimHealth; evidence: EvidenceRow[] }[];
};

export type Revision = {
    revision_id: string;
    version: string;
    content_digest: string;
    installed_at: string;
    active: boolean;
};

export type PackEvent = {
    action: string;
    created_at: string;
    revision_id: string;
    details: Record<string, unknown>;
};

export type LookupRequest = {
    kind: string;
    identity: Record<string, string | number>;
    context: Record<string, string | number>;
};

export type AnalyzeRequest = {
    url: string;
    title: string;
    description: string;
    fields: Record<string, unknown>;
};

export type HistoryItem = {
    lookup_id: string;
    created_at: string;
    source: string;
    label: string;
    claim_count: number;
};

export type StoredLookup = {
    lookup_id: string;
    created_at: string;
    source: string;
    label: string;
    request: Record<string, unknown>;
    response: LookupResult;
};
