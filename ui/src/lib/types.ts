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
    /** Whether the protocol on disk is the one this build would write.
     *  A harness can be wired and carrying a skill from three versions ago. */
    skill?: {
        supported: boolean;
        path: string | null;
        present: boolean;
        stale: boolean;
    };
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
export type IdentityKey = { key: string; match_json?: string; required: boolean };
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
    /** Which subjects the resolution matched, echoed by `/api/lookup` for the
     * same reason context is (check-13): an ambiguous match needs to say how
     * many, and by what, rather than just that it was ambiguous. */
    subjects?: string[];
};

export type AnalyzeResult = LookupResult & {
    // Present, and always `true`, only so this discriminates against
    // `UnreadPage`'s `readable: false` — TS cannot narrow a union on a field
    // that is absent from one side of it.
    readable?: true;
    adapter: string;
    packs: { pack_id: string; version: string }[];
    context_units: Record<string, string>;
    identity: Record<string, unknown>;
    context: Record<string, unknown>;
    unmapped_labels: string[];
};

// A distinct, expected shape (check-1): the adapter matched the URL's site,
// but a pasted-in URL has no page for it to read, so there is nothing to
// look up yet. Never call this a "no pack covers this" answer.
export type UnreadPage = {
    readable: false;
    reason: "page_not_read" | "no_adapter";
    adapter?: string | null;
    next_step?: string;
    readable_sites?: { site: string; pack_id: string }[];
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

/** One `/api/search` hit — a `Subject` plus the identity that tells two rows
 * sharing a label apart, which is the entire reason `/api/search` exists
 * over `/api/subjects?q=` (check-5). */
export type SearchHit = Subject & {
    identity: Record<string, string>;
    why: string[];
};

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
    /* Set by `_with_attention` in `app/web/routers/jobs.py` when the run put
     * something to the reader. Null is the ordinary case. */
    attention: Attention | null;
};

/* One thing the identification pass could not settle on its own.
 *
 * It did not wait for the answer — `app/disambiguate.py` states a default and
 * carries on, because a run that blocks on a person is a run nobody finishes.
 * So `default` is what it actually used, and an answer here changes the *next*
 * run rather than this one.
 */
export type Question = {
    id: string;
    ask: string;
    /* Which part of the scope this settles. Empty means `id` is the key. */
    key: string;
    /* At most eight, and possibly none — then it is a free-text answer. */
    options: string[];
    /* What the run assumed. Never empty: a question without one would have
     * had to block, so `normalise` drops it. */
    default: string;
    because: string;
};

export type Attention = {
    kind: string;
    count: number;
    say: string;
    questions: Question[];
};

/* One position on the depth dial, as `app/scale.py` defines it.
 *
 * `usd` and `tokens` are `null` where this installation has never measured a
 * run of that shape — inherited from `costs.estimate`, which refuses to
 * invent a number, and rendered as "not measured" rather than as zero. A
 * promise about somebody's money that the app cannot keep is worse than none.
 *
 * `custom` reports `max_documents: 0`, meaning "your own number" — the screen
 * offers a field, and an explicit count wins over whatever a preset proposes.
 */
export type Scale = {
    id: string;
    label: string;
    note: string;
    max_documents: number;
    context_chars: number;
    batch_size: number;
    usd: number | null;
    tokens: number | null;
    basis: number;
    cap_usd: number;
};

export type Scales = { scales: Scale[]; default: string };

export type RunSelection = { llm?: string; harness?: string; search?: string };

export type ResearchRequest = RunSelection & {
    subject_id: string;
    pack_id?: string;
    backend?: string;
    budget_usd?: number;
    max_documents?: number;
    /** `quick` | `standard` | `deep` | `custom`. The server owns the numbers
     *  behind each name (`app/scale.py`) — a client that restated them would
     *  be the hand-maintained correspondence this repository keeps catching.
     *  An explicit `max_documents` wins over whatever the preset proposes. */
    scale?: string;
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

/** One piece of evidence, checked offline against the page this install
 * actually kept — never a fresh fetch. `not_kept` means no copy exists to
 * check against at all, which is a different fact than `ungrounded` and
 * must never be shown as a pass. See `app/findings.py`'s `regrounded`. */
export type GroundingEvidence = {
    evidence_id: string;
    source_id: string;
    quote: string;
    url: string;
    verdict: string;
};
export type Grounding = {
    claim_id: string;
    pack_id: string;
    evidence: GroundingEvidence[];
    not_kept: number;
    ungrounded: number;
};

/** The retained page text behind one piece of evidence — "here is the page
 * that proved this quote". See `GET /api/factcheck/document`. */
export type RetainedDocument = {
    source_id: string;
    pack_id: string;
    url: string;
    text: string;
    chars: number;
    retained_at: string;
};

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
/** One unit of agent-driven work on the knowledge, as the feed sees it.
 *
 * `request`/`response` are summaries the server made — a page of
 * `document_text` is elided there rather than carried here. See
 * `app/operations.py`. */
/** What a draft currently holds, and what of its line-up it does not cover. */
export type DraftState = {
    slug: string;
    pack_id: string;
    name: string;
    version: string;
    identity: Record<string, string[]>;
    principle: string;
    subjects: string[];
    claims: number;
    uncovered: string[];
    lineup: string[];
};

/** A site this installation can read, and where the adapter came from. */
export type Site = {
    site: string;
    id: string;
    pack_id: string;
    match: string[];
    /** pack | local — a pack author's, or one this copy learned. */
    source: string;
    superseded?: boolean;
    /** Whether the panel will actually appear there — an adapter existing
     *  and a browser permitting injection are two different facts. */
    activation?: { host: string; state: string; detail: string; pattern?: string };
};

export type SiteRequest = {
    host: string;
    asks: number;
    sample_url: string;
    title: string;
    /** open | working | done | refused. */
    state: string;
    detail: string;
    first_at: string;
    last_at: string;
};

export type Sites = { registered: Site[]; requested: SiteRequest[] };

/** Which agent, which LLM, which search provider — and what could be chosen. */
export type LlmChoice = {
    id: string; label: string; provider: string; context: number | null;
    usd_in: number | null; usd_out: number | null; speed: string;
    unusable: string; known: boolean; note?: string;
};

/** One installed coding-agent CLI and its LLM choice. `llm` throughout:
 *  the frontend may not name a pack's identity keys. */
export type HarnessModel = {
    id: string;
    label: string;
    command: string;
    path?: string;
    needs_account?: string;
    /** The stored per-harness LLM, or "" for the CLI default. */
    llm?: string;
    /** What the CLI itself offers, or [] when it named nothing. */
    llms?: string[];
    llm_hint?: string;
    /** False where Kriko has no verified per-run switch yet. */
    llm_selectable?: boolean;
    /** The stored effort level, or "" for the CLI's own default. */
    effort?: string;
    /** The levels this machine's CLI declares in its own --help. `[]` means
     *  it has no such dial and the control is not drawn at all. */
    efforts?: string[];
    effort_hint?: string;
};

export type Prefs = {
    chosen: { preferred_harness: string; llm_model: string; search_provider: string; llm_model_extract?: string; llm_model_plan?: string; llm_model_synthesise?: string; llm_model_validate?: string };
    harnesses: HarnessModel[];
    unusable: { id: string; label: string; why: string }[];
    missing: {
        id: string;
        label: string;
        command: string;
        download_url: string;
        install_hint: string;
        needs_account: string;
    }[];
    dirs_env: string;
    search_providers: { id: string; label: string; ready: boolean }[];
    models: { current: string; default: string; note: string; offered?: LlmChoice[]; catalogue?: string };
    roles?: { id: string; note: string; chosen: string; active: boolean; effective: string; inactive_reason: string }[];
    effective?: { llm: string; search: string; ready: boolean; reason: string; harness: string; harness_note: string };
};

/** What has been spent, and what the next run is likely to cost.
 *
 * `usd: null` means nobody counted — never zero. And there is no balance:
 * no provider exposes one to an API key, so the screen says where it lives
 * instead of inventing a number. */
export type Costs = {
    spent: {
        days: number;
        usd: number;
        tokens: number;
        runs: number;
        planes: {
            plane: string;
            /** Which LLM answered. Spelled `llm` here and in the payload: the
             *  client may not contain a pack's identity key. */
            llm: string;
            runs: number;
            priced: number;
            usd: number;
            tokens: number;
            usd_per_run: number | null;
        }[];
    };
    estimates: Record<
        string,
        {
            plane: string;
            subjects: number;
            usd: number | null;
            tokens: number | null;
            basis: number;
            note: string;
        }
    >;
    keys: { id: string; label: string; present: boolean; purpose: string }[];
    balance: { known: boolean; note: string };
};

export type Operation = {
    op_id: number;
    /** mcp | job | extension | app | cli — which door it came in. */
    door: string;
    /** research | agenda | author | recheck | lookup | read | write. */
    kind: string;
    /** The tool or job as it is actually called. */
    name: string;
    subject_id: string;
    pack_id: string;
    /** running | ok | failed. */
    state: string;
    request_json: string;
    response_json: string;
    error: string;
    ms: number | null;
    started_at: string;
    ended_at: string;
    /** The job this operation *is*, when it came in by the `job` door.
     *
     * Empty for every other door, and that emptiness is load-bearing: a job
     * belongs to the runner in this process and can be stopped from the feed
     * watching it, while an MCP call belongs to the process that made it and
     * cannot. The Stop button is offered on exactly the rows that carry one. */
    job_id?: string;
    /** What that job is saying right now — its named stage, live.
     *
     * An operation row says nothing between opening and closing, so a long run
     * was a line that sat there for forty minutes. The job underneath it was
     * naming its stage the whole time; this is the feed finally asking. Null
     * for a door that has no job. */
    note?: string | null;
    /** How far along that job claims to be, 0–1. Null where there is no job. */
    progress?: number | null;
    /** The job's own state, which outlives the operation's: a cancelled job is
     *  not a failed one, and colouring a deliberate stop like a crash teaches
     *  the reader to ignore the colour. */
    job_state?: string | null;
};

export type Operations = {
    items: Operation[];
    running: number;
    last_id: number;
};

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
    /** The searches this batch actually came from. Empty on an older row. */
    queries?: string[];
};

export type Submissions = {
    items: Submission[];
    accepted: number;
    refused: number;
    reasons: { reason: string; count: number }[];
    /** Which searches earn their place, best first. See `state.query_shapes`. */
    shapes: { query: string; batches: number; accepted: number; refused: number }[];
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
    /** Whether it can run *now*. False on the paid plane with no keys set,
     *  and on the harness plane with no coding-agent CLI installed. */
    ready: boolean;
    needs_keys: boolean;
    selected_harness?: string;
    reason?: string;
    llm?: string;
    search?: string;
    /** The harness plane only: which coding-agent CLIs were found here. */
    harnesses?: HarnessModel[];
    /** The harness plane only: the commands that were looked for, so a card
     *  that cannot run names the thing to install. */
    looked_for?: string[];
    /** Found on this machine and deliberately not driven, each with the
     *  reason. "My agent is installed, why isn't Kriko using it" is a fair
     *  question, and silence is not an answer to it. */
    unusable?: { id: string; label: string; command: string; why: string }[];
    /** Not found here, each with where to get it and what account it bills
     *  to. A missing CLI is the ordinary state, not an error — the card
     *  lists the way out rather than just the absence. */
    missing?: {
        id: string;
        label: string;
        command: string;
        download_url: string;
        install_hint: string;
        needs_account: string;
    }[];
    /** The environment variable that adds another directory to the CLI
     *  search, and the home-relative directories searched without it. */
    dirs_env?: string;
    search_dirs?: string[];
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
    /** Tokens, when the plane can count them. `null` is "this plane cannot
     *  count", never "this cost nothing" — see `state.usage_totals`. Only
     *  ever rendered when it is a number. */
    tokens_used: number | null;
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

export type AgendaRunRequest = RunSelection & {
    rows?: number;
    pack_id?: string | null;
    backend?: string;
    budget_usd?: number;
    max_documents?: number;
    /** See `ResearchRequest.scale`. An agenda run multiplies the per-subject
     *  cost by the number of rows, so it is the screen that most needs one. */
    scale?: string;
};

/* A pack an agent wrote, waiting for the reader to install or throw away.
 *
 * An agent's write surface used to stop at claims: it could add to a pack that
 * already declared the subject, and it could not start a pack for a category
 * nobody had modelled. It can now, into `~/.kriko/drafts` — data files only,
 * no code, and nothing reaches the store without the press below. `error` is
 * set when the draft no longer loads, which is worth showing rather than
 * hiding: installing it will fail, and whoever wrote it needs to know which
 * edit broke it.
 */
export type PackDraft = {
    slug: string;
    root: string;
    files: string[];
    artifact: string | null;
    pack_id: string;
    name: string;
    version: string;
    error: string;
    /** The pack id this draft was installed as, or "". A draft that has been
     *  installed is still a draft — it can be amended and installed again —
     *  but a card that cannot say so reads as an install that did not work. */
    installed_as: string;
};

/* What this installation has spent, and what it was asked. (B97)
 *
 * A per-run row could always say what one run cost. The only question a
 * reader actually has — what has this cost me so far, and is it worth it —
 * is a sum, and there was nowhere to read a sum from.
 *
 * Every metered field is nullable on purpose, and `metered_runs` travels
 * with the totals so a figure can be read against how many of the runs
 * behind it were counted at all.
 */
export type UsageTotals = {
    runs: number;
    metered_runs: number;
    counted_runs: number;
    spent_usd: number | null;
    tokens_used: number | null;
    claims: number;
    cost_per_claim: number | null;
    planes: {
        plane: string;
        runs: number;
        metered_runs: number;
        spent_usd: number | null;
        tokens_used: number | null;
    }[];
};

/** What the analyses log holds. No timestamps: the records carry none. */
export type UsageAnalyses = {
    analyses: number;
    malformed: number;
    claims_shown: number;
    answered_nothing: number;
    subjects: number;
    adapters: string[];
};

export type Usage = { research: UsageTotals; analyses: UsageAnalyses };

/* B98 — the agenda, walked with nobody watching.
 *
 * `last` is the record of the most recent tick, and it is deliberately
 * separate from the setting: a tick that declined still wrote a reason, and
 * that reason is the only output an unattended feature has on the days it
 * does nothing. It is `{}` on an installation where no tick has ever run.
 */
export type ScheduleLast = {
    checked_at?: string;
    reason?: string;
    due_at?: string;
    run_at?: string;
    job_id?: string;
    runs?: number;
};

export type Schedule = {
    enabled: boolean;
    every_hours: number;
    rows: number;
    plane: string;
    budget_usd: number;
    max_documents: number;
    last: ScheduleLast;
    /** Queued plus running. The loop will not add to this. */
    in_flight: number;
};

/** Partial by design — see `api.saveSchedule`. */
export type ScheduleRequest = Partial<
    Pick<Schedule, "enabled" | "every_hours" | "rows" | "plane" | "budget_usd" | "max_documents">
>;

export type ScheduleCheck = Schedule & {
    ran: boolean;
    reason: string;
    due_at: string;
};

export type BenchProtocol = {
    name: string;
    context_chars: number;
    batch_size: number;
    preamble: string;
};

export type BenchRun = {
    id?: number;
    at?: string;
    plane: string;
    llm: string;
    protocol: string;
    kind: string;
    search_provider: string;
    ms?: number | null;
    tokens?: number | null;
    usd: number | null;
    documents?: number | null;
    findings?: number | null;
    accepted?: number | null;
    refused?: number | null;
    error?: string;
    reasons: string[];
    gold: Record<string, unknown> | null;
};

export type BenchScoredGroup = {
    plane: string;
    llm: string;
    protocol: string;
    runs: number;
    found: number;
    wanted: number;
    produced: number;
    hallucinated: number;
    recall: number | null;
    recall_interval: [number, number] | null;
    hallucination_rate: number | null;
    hallucination_interval: [number, number] | null;
};

export type BenchSummaryRow = {
    plane: string;
    llm: string;
    protocol: string;
    runs: number;
    ms: number | null;
    tokens: number | null;
    usd: number | null;
    documents: number | null;
    findings: number | null;
    accepted: number | null;
    refused: number | null;
    failures: number;
    acceptance: number | null;
};

export type BenchReadoutRow = {
    llm: string;
    protocol: string;
    batch_size: number;
    context_chars: number;
    preamble: string;
    search_provider: string;
    usd_per_accepted_claim: number | null;
    hallucination_rate: number | null;
    hallucination_interval: [number, number] | null;
    runs: number;
    note: string;
};

export type Bench = {
    runs: BenchRun[];
    verdict: Record<string, unknown>;
    scored: { groups: BenchScoredGroup[] };
    summary: BenchSummaryRow[];
    cases: Record<string, unknown>[];
    protocols: BenchProtocol[];
    chosen: Record<string, string>;
    readout: BenchReadoutRow[];
};

export type BenchRequest = Partial<{
    planes: string;
    pack_id: string;
    cases: number;
    max_documents: number;
    budget_usd: number;
    protocols: string;
    reps: number;
    llms: string;
    searches: string;
}>;

export type BenchEstimate = { runs: number; usd: number | null; tokens: number | null; basis: number; note: string; axes: Record<string, number> };

export type ProviderTest = {
    provider: string;
    ok: boolean;
    latency_ms: number;
    error: string;
    detail: string;
    results: number | null;
    tokens_in: number | null;
    tokens_out: number | null;
    tokens: number | null;
    usd: number | null;
    llm: string;
};
