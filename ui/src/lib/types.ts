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

/** One row of what to research next. The signals ride along rather than being
 * fused into a score: "nobody has researched this" and "the source moved" want
 * different work, and a single number cannot tell them apart. */
export type AgendaRow = {
    kind: "empty_subject" | "stale_claim" | "thin_subject" | "unknown_subject";
    subject_id: string;
    pack_id: string;
    label: string;
    why: string;
    asked: number;
    /** Only on `unknown_subject`: the identity, as the pack's adapter produced
     * it. There is no subject to name, which is the content of the row. */
    identity?: string;
    claim_id?: string;
    title?: string;
    checked_at?: string;
    independent_sources?: number;
    refuted_by?: number;
    subject_kind?: string;
};

export type Agenda = {
    rows: AgendaRow[];
    /** Why the ordering may be worse than usual — a missing or unreadable log.
     * Empty when nothing is wrong. */
    note: string;
    window: number;
    counts: Record<string, number>;
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
    /* Diagnostics. Every one of these is a fact this window cannot observe
     * about the process serving it, which is the only reason they are on the
     * wire: a reader whose app is half-working has no other instrument, and
     * neither do we when they write in.
     *
     * The two `*_problem` fields are the half that was missing. The paths
     * were always chosen and the failures were always caught — into a logger
     * with no handler, which is how two months of analyses went unwritten
     * with nothing anywhere saying so. A path that could not be opened now
     * says why, here, next to the path that was used instead. */
    log_file: string | null;
    log_problem: string | null;
    analysis_log_problem: string | null;
    /* Is anything reading the sidecar's stdout? The window cannot tell, and
     * "Open in Kriko" behaves differently depending on the answer. */
    shell_attached: boolean;
    extension_port: number;
    port_is_ours: boolean;
};

export type ExtensionBrowser = { id: string; name: string; url: string };
export type ExtensionSighting = {
    origin: string;
    first_at: string;
    last_at: string;
    hits: number;
    /** What the extension said it was, blank for one too old to say — which
     * is itself the answer, since every version that can say is newer. */
    version: string;
};

/** The two clocks compared. `state` is the app's verdict, not the page's:
 * the floor lives in `app/extension.py` and nothing here knows which
 * versions are compatible, so this cannot drift from the rule. */
export type ExtensionCompatibility = {
    running_version: string;
    minimum_version: string;
    state: "unknown" | "too_old" | "behind" | "current";
    detail: string;
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
    /** Has a sighting *ever* landed, regardless of age. `connected` is a live
     * badge — it goes false after FRESH_SECONDS of quiet — and reusing it to
     * decide whether to *suggest installing* the extension (B85) told a
     * reader whose history was full of extension-sourced answers to go add
     * it again the moment they left the app alone for a few hours. */
    ever_connected: boolean;
    seconds_since_seen: number | null;
    compatibility: ExtensionCompatibility;
};
export type ExtensionStaged = { path: string; written: string[]; version: string };
export type ExtensionRevealed = { path: string; error: string };
/** The one-click install's answer. `launched` says a browser was started, not
 * that it accepted the extension — nothing but the extension's own call to
 * this app can say that, and `ExtensionStatus.connected` is where it lands.
 * `error` is prose for the reader, and arrives with HTTP 200: both ways this
 * can fall short leave the manual steps as the install. */
export type ExtensionLaunched = {
    launched: boolean;
    browser: string;
    path: string;
    profile: string;
    /** The page the browser was opened on: a listing site an installed pack
     * can read, so the extension has something to do the moment the window
     * appears. Empty when no browser was started. Rendered, never named
     * here — which sites exist is pack data. */
    landing: string;
    note: string;
    error: string;
};


/** What the page a claim cites says *now*.
 *
 * Four verdicts and only one is bad news — see `src/app/factcheck.py`.
 * `missing` is a signal, not a refutation: pages get rewritten, and the engine
 * has no authority to retract a claim. Nothing here changes a ranking. */
export type FactCheck = {
    pack_id: string;
    claim_id: string;
    verdict: string;
    detail: string;
    sources: { url: string; verdict: string; detail: string }[];
    subject_id: string;
    title: string;
    checked_at: string;
};
export type FactChecks = { items: FactCheck[]; counts: Record<string, number> };

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

// ── the knowledge pipeline ───────────────────────────────────────────────
//
// What a run *did*, as opposed to what a job printed. A `Job` says whether
// long work is running and carries its log; these say which stage the
// pipeline reached, how many sources it read, how many findings survived the
// grounding check, and which source each one came from. Those are different
// questions, and the second set is the one that distinguishes "found nothing"
// from "found plenty and lost it all at acceptance".

export type PipelineRun = {
    run_id: string;
    /** The job this ran under, so the two views are two views of one thing. */
    job_id: string | null;
    kind: string;
    subject_id: string;
    subject: string;
    pack_id: string;
    /** Which research plane paid for it: `agent` ($0) or `api` (per token). */
    plane: string;
    state: "running" | "done" | "failed" | "cancelled" | "interrupted";
    sources: number;
    findings: number;
    accepted: number;
    refused: number;
    chars: number;
    /** NULL when nobody counted — which is not the same as zero. See
     *  `tokens_counted`: the agent plane's marginal cost really is zero, and
     *  rendering an uncounted run as free would be a measurement we do not
     *  have. */
    tokens: number | null;
    tokens_counted: boolean;
    started_at: string;
    ended_at: string | null;
    error: string | null;
};

export type PipelineStage = {
    stage: string;
    label: string;
    seq: number;
    /** `waiting` is the server's word for a stage that has not begun, so the
     *  view shows the pipeline's shape from the first frame rather than
     *  growing one box at a time. `skipped` is a stage that correctly did
     *  nothing — not a failure. */
    state: "waiting" | "running" | "done" | "failed" | "skipped";
    detail: string;
    items: number;
    started_at: string | null;
    ended_at: string | null;
};

export type PipelineEvent = {
    event_id: number;
    run_id: string;
    stage: string;
    at: string;
    level: "info" | "kept" | "refused" | "warn";
    message: string;
    source_url: string;
    detail: Record<string, unknown>;
};

export type PipelineFrame = {
    run: PipelineRun;
    stages: PipelineStage[];
    events: PipelineEvent[];
    /** Send back as `after` next time. Carried in the frame so the client and
     *  the server cannot disagree about what has already been seen. */
    cursor: number;
    live: boolean;
};


/** A label a listing page carried that no installed adapter reads.
 *
 * `seen` is the weight and `last_at` is the urgency: a label seen four hundred
 * times over six months is a known gap somebody decided not to map, and one
 * seen twice this week on a site that used to work is a markup change. */
export type UnmappedLabel = {
    adapter_id: string;
    label: string;
    seen: number;
    first_at: string;
    last_at: string;
    sample_url: string;
};


/** One research plane, as `/api/research-planes` describes it.
 *
 * `cost_basis` is the engine's own word (`subscription` / `per_token`) and
 * `what` is the sentence a reader can act on. Both come from the server: the
 * plane vocabulary belongs to `kriko/research/`, and a copy of it here would
 * be a second place to forget when a third plane arrives. */
export type ResearchPlane = {
    id: string;
    cost_basis: string;
    what: string;
    /** Whether it can run *now*. False on the paid plane with no keys set. */
    ready: boolean;
    needs_keys: boolean;
};

/** What `/api/keys` says about one provider — never the key itself.
 *
 * `hint` is a masked tail (`…4f2a`) and is the only part of a stored value
 * that ever leaves the server. `source` distinguishes a key this app wrote
 * from one that was already in the environment, because the second kind
 * cannot be deleted from here and a delete button that silently does nothing
 * is worse than no button. */
export type ApiKeyStatus = {
    id: string;
    label: string;
    env: string;
    /** What this provider receives. Printed, not summarised: a screen that
     *  asks for a key owes the reader the data-flow answer. */
    purpose: string;
    present: boolean;
    hint: string;
    source: "file" | "environment" | "";
};

export type ApiKeys = { providers: ApiKeyStatus[]; ready: boolean; path: string };

/** One research run's provenance row.
 *
 * `spent_usd` is `null` when nobody counted — the agent plane never does —
 * which is a different answer from a measured zero and is kept apart on
 * purpose. `claims` counts what is *still* in the store, so an undone run
 * reads as zero rather than advertising what it once added. */
export type ResearchRun = {
    run_id: string;
    job_id: string;
    plane: string;
    /** Which completion API wrote these claims. `llm` rather than the
     *  column's own name, which is a pack identity key the frontend may not
     *  contain — see `state._research_run`. */
    llm: string;
    search_provider: string;
    budget_usd: number | null;
    spent_usd: number | null;
    started_at: string;
    ended_at: string;
    outcome: string;
    claims: number;
    removed: number;
};

export type ResearchRunClaim = {
    run_id: string;
    pack_id: string;
    claim_id: string;
    subject_id: string;
    title: string;
    removed_at: string | null;
};

export type ResearchRunDetail = ResearchRun & {
    claims_detail: ResearchRunClaim[];
    /** The server's answer to "would the undo button do anything". */
    undoable: boolean;
};

export type AgendaRunRequest = {
    rows?: number;
    pack_id?: string | null;
    backend?: string;
    budget_usd?: number;
    max_documents?: number;
};
