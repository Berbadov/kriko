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

export type PackUpdate = {
    pack_id: string;
    name: string;
    installed_version: string;
    offered_version?: string;
    /** available | up_to_date | unknown | refused | not_installed */
    state: string;
    reason: string;
    url?: string;
    size?: number;
    published_at?: string;
};

export type PackUpdates = {
    index_url: string;
    error: string | null;
    checked_at?: string;
    packs: PackUpdate[];
};

// How an agent reaches this installation. The shape is the server's, verbatim:
// the JSON block is meant to be copied, not rebuilt here from parts.
export type AgentConfig = {
    server_name: string;
    frozen: boolean;
    store: string;
    mcp_json: unknown;
    tools: string[];
};

export type AgentTarget = {
    id: string;
    label: string;
    path: string;
    exists: boolean;
    state: "connected" | "stale" | "absent" | "unreadable";
    detail?: string;
};

export type AgentTargets = { server_name: string; store: string; targets: AgentTarget[] };

export type AgentSkill = {
    name: string;
    steps: { tool: string; why: string }[];
    /** null when no pack is installed: there is no protocol without knowledge. */
    body: string | null;
};

export type AgentVerify = { ok: boolean; server?: string; detail?: string };

export type Kind = { kind: string; pack_id: string };
export type IdentityKey = { key: string; match_json?: string };
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
    claim_id?: string;
    title: string;
    body: string;
    advice?: string;
    severity: string;
    domain?: string;
    subject: string;
    relevance: number;
    disputed?: boolean;
    detection?: string;
    trust?: number;
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
    /** What the answer was computed against, when the caller sent any.
     *
     * Optional here rather than only on `AnalyzeResult` because a stored
     * lookup is an analyze payload that has been through SQLite: the report
     * renders both, and a reader asking "did it know how much use this one
     * has had" is asking about the stored one as often as the fresh one. */
    context?: Record<string, unknown>;
    context_units?: Record<string, string>;
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
    // Required, not optional. `/api/subjects` selects it in every branch, so
    // an optional field here only forced every caller to handle a case the
    // server cannot produce — which they did by asserting it away with `!`,
    // i.e. by turning the type off.
    subject_id: string;
    label: string;
    kind: string;
    pack_id: string;
    claims: number;
};

export type Gap = { subject_id: string; label: string; kind: string };

/** A reader's verdict on one claim.
 *
 * Interface state, not pack content: it lives in `app.sqlite`, so it cannot
 * move a pack's `content_digest` and it survives uninstalling the pack the
 * claim came from. Which is why `title` is stored *on the mark* — the claim
 * it names may not be installed any more, and "you marked something wrong,
 * we no longer know what" is not a report.
 */
export type Mark = {
    pack_id: string;
    claim_id: string;
    verdict: string;
    note: string;
    subject_id: string;
    title: string;
    created_at: string;
    updated_at: string;
};

export type Marks = {
    items: Mark[];
    counts: Record<string, number>;
    verdicts: string[];
};

/** What a pile of marks adds up to, split by which system has the problem.
 *
 * Two queues rather than one list, because the two verdicts are failures of
 * different things: `wrong` is a knowledge problem (research it again),
 * `not_applicable` is a *matching* problem (identity extraction, or a gate
 * that is too broad). `sources` counts the doors the subject was reached
 * through, which is what separates "the page was read wrong" from "what was
 * typed in matched too much".
 */
export type MarkQueueItem = {
    subject_id: string;
    pack_id: string;
    count: number;
    notes: string[];
    claim_ids: string[];
    sources?: Record<string, number>;
};

export type MarkSignals = {
    research: MarkQueueItem[];
    matching: MarkQueueItem[];
};

/** A pack about to exist. `identity` is kind → the attribute keys that tell
 *  two subjects of that kind apart; its shape is the author's, not this app's. */
export type NewPack = {
    root: string;
    pack_id: string;
    name: string;
    identity: Record<string, string[]>;
    version?: string;
};

export type Job = {
    job_id: string;
    kind: string;
    params: Record<string, unknown>;
    state: string;
    progress: number;
    message: string;
    log: string;
    result: Record<string, unknown> | null;
    done: boolean;
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
};

export type ResearchRequest = {
    subject_id: string;
    pack_id?: string;
    backend?: string;
    budget_usd?: number;
    max_documents?: number;
};

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

export type Adapter = {
    id: string;
    site: string;
    pack_id: string;
    match: string[];
    labels: string[];
};

export type SubjectDetail = {
    subject_id: string;
    pack_id: string;
    kind: string;
    label: string;
    attributes: {
        key: string;
        value_text: string;
        unit: string;
        is_identity: number;
    }[];
    relations: { predicate: string; object_label: string; object_id: string }[];
    claims: { claim_id: string; title: string; severity: string; domain: string }[];
};

export type Brief = { subject: string; queries: string[]; brief: string };

/** What `/api/health` reports about this install.
 *
 * `version`, `schema_version` and each pack's version are three independent
 * clocks — see `app/version.py` for why they are never collapsed into one.
 */
export type Health = {
    ok: boolean;
    store: string;
    app_state: string;
    analysis_log: string;
    version: string;
    schema_version: number;
    packs: { pack_id: string; version: string }[];
    releases_url: string;
};

export type ExtensionBrowser = { id: string; name: string; url: string };
export type ExtensionSighting = {
    origin: string;
    first_at: string;
    last_at: string;
    hits: number;
};
export type ExtensionStatus = {
    available: boolean;
    version: string;
    staged: boolean;
    staged_version: string;
    path: string;
    port: number;
    port_is_ours: boolean;
    browsers: ExtensionBrowser[];
    sightings: ExtensionSighting[];
    connected: boolean;
    seconds_since_seen: number | null;
};
export type ExtensionStaged = { path: string; written: string[]; version: string };
export type ExtensionRevealed = { path: string; error: string };


/** The reader's own marks on one stored answer: what they ticked, and what
 * the seller said. Read together because they render together. */
export type Triage = {
    lookup_id: string;
    checked: string[];
    notes: Record<string, string>;
};

/** One batch a researcher submitted, and what the gate did with it.
 *
 * `rejected` carries the gate's own sentence per finding — the most useful
 * data in the system for improving the agent skill, and previously returned
 * to the agent and then discarded.
 */
export type Submission = {
    submission_id: string;
    created_at: string;
    /** mcp | job — which door it came in. */
    door: string;
    subject_id: string;
    pack_id: string;
    accepted: number;
    refused: number;
    verdicts: {
        accepted?: { title: string; claim_id: string }[];
        rejected?: { title: string; reason: string }[];
        error?: string;
    };
};

export type Submissions = {
    items: Submission[];
    accepted: number;
    refused: number;
    reasons: { reason: string; count: number }[];
};
