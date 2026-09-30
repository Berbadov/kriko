import { humanize } from "./fields";
import type { Claim, LookupResult } from "./types";

/** Severity is one of the engine's few closed vocabularies (`rank.py`'s
 * SEVERITY_WEIGHT), so ordering on it here is not the hardcoded-pack-data bug
 * — a domain or a term id would be. */
const SEVERITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

const SEVERITY_WORD: Record<string, string> = {
    high: "Serious",
    medium: "Worth checking",
    low: "Minor",
};

export const severityRank = (severity: string): number =>
    SEVERITY_RANK[severity] ?? 1.5;

export const severityWord = (severity: string): string =>
    SEVERITY_WORD[severity] ?? severity;

/* What a re-check of a claim's sources means, in words a reader can act on.
 *
 * The verdict vocabulary is closed and owned by `src/app/factcheck.py`; what
 * lives here is the sentence, and the sentences are the whole point. "missing"
 * must never read as "this claim is false" — the page was rewritten, which is
 * a reason to look rather than a refutation, and the engine has no authority
 * to retract anything (see the marks table). Overstating it once would teach
 * the reader to distrust every other badge on the card.
 */
const FACT_WORD: Record<string, string> = {
    quoted: "Source still says this",
    missing: "Source has changed",
    unreadable: "Cannot check automatically",
    unreachable: "Source unreachable",
};
const FACT_TONE: Record<string, string> = {
    quoted: "ok",
    missing: "warn",
    unreadable: "meta",
    unreachable: "meta",
};

export const factWord = (verdict: string): string => FACT_WORD[verdict] ?? verdict;

/** The badge's tone. `unreachable` is deliberately neutral: a site that is
 * down says nothing at all about a claim, and colouring it like a problem
 * would put the blame on the pack. */
export const factTone = (verdict: string): string => FACT_TONE[verdict] ?? "meta";

/* What an offline grounding check answers, in words. This is a different
 * question than the fact-check above — no network, no fresh read — so it is
 * a separate vocabulary rather than a reuse of `FACT_WORD`: `not_kept` is not
 * "unreadable", it is "nothing to check against", and folding it into the
 * fact-check words would turn a missing document into what reads like a mild
 * version of an unreachable one, instead of what it is. Verdicts owned by
 * `app/findings.py`'s `regrounded`. `not_kept` must never share a tone with
 * `grounded` — that is the whole reason it is its own verdict.
 */
const GROUNDING_WORD: Record<string, string> = {
    grounded: "Quote found in the retained page",
    ungrounded: "Quote not found in the retained page",
    not_kept: "No page was kept to check this against",
};
const GROUNDING_TONE: Record<string, string> = {
    grounded: "ok",
    ungrounded: "warn",
    not_kept: "meta",
};

export const groundingWord = (verdict: string): string =>
    GROUNDING_WORD[verdict] ?? verdict;

export const groundingTone = (verdict: string): string =>
    GROUNDING_TONE[verdict] ?? "meta";

/** Whether a claim can be re-checked at all: it needs an identity the server
 * can look up, and a page to re-read. */
export const canCheckFacts = (claim: Claim): boolean =>
    Boolean(claim.claim_id && claim.pack_id && claim.sources?.some((s) => s.url));

/** A stable per-claim identity for the reader's own notes.
 *
 * `/api/lookup` returns `claim_id`; `/api/analyze` does not, and a checkmark
 * has to survive on both. The fallback is pack-scoped so two packs asserting
 * the same title stay two separate rows to tick off.
 */
export const claimKey = (claim: Claim): string =>
    claim.claim_id || `${claim.pack_id}:${claim.title}`;

/** Urgency order, which is not the engine's order.
 *
 * The engine sorts by relevance first (`lookup/__init__.py`), because
 * relevance is what it is confident about. A reader deciding whether to walk
 * away from a purchase reads consequence first: every serious risk should be
 * above every minor one, however well the minor one scored.
 */
export const orderClaims = (claims: Claim[]): Claim[] =>
    [...claims].sort(
        (a, b) =>
            severityRank(a.severity) - severityRank(b.severity) ||
            (b.relevance ?? 0) - (a.relevance ?? 0) ||
            a.title.localeCompare(b.title),
    );

export type Group = { domain: string; claims: Claim[] };

/** Grouped by the pack's own domain, groups ordered by their worst claim.
 *
 * The domain strings come from the payload and are never enumerated here —
 * a pack invents its own systems, and this function must not know one.
 */
export function groupByDomain(claims: Claim[]): Group[] {
    const groups = new Map<string, Claim[]>();
    for (const claim of orderClaims(claims)) {
        const domain = claim.domain || "other";
        if (!groups.has(domain)) groups.set(domain, []);
        groups.get(domain)!.push(claim);
    }
    return [...groups.entries()]
        .map(([domain, grouped]) => ({ domain, claims: grouped }))
        .sort(
            (a, b) =>
                severityRank(a.claims[0].severity) -
                    severityRank(b.claims[0].severity) ||
                b.claims.length - a.claims.length ||
                a.domain.localeCompare(b.domain),
        );
}

/** What the sources amount to, in a sentence rather than a tier table. */
export function sourceSummary(claim: Claim): string {
    const sources = claim.sources ?? [];
    if (!sources.length) return "No source cited — this is a service-interval item.";
    const against = sources.filter((s) => s.stance === "refutes").length;
    const forCount = sources.length - against;
    const agree =
        forCount === 1 ? "1 source reports this" : `${forCount} sources report this`;
    return against ? `${agree}, ${against} disagrees` : agree;
}

/** Why this report is empty, which is two different situations.
 *
 * "We could not identify the thing" and "we identified it and know nothing
 * about it" lead the reader to opposite next steps, and a single "no results"
 * hides which one happened.
 */
export function emptyReason(result: LookupResult): string {
    if (result.coverage === "NOT_MATCHED" || result.method === "no_match") {
        return (
            "No installed pack recognised this one. Check the details, " +
            "or install a pack that covers it."
        );
    }
    // "Several products match" is not "we found nothing" (check-3): the
    // details given narrow the field to more than one candidate, and the
    // reader's next step is picking one of them, not hearing that the packs
    // are thin. `result.subjects` already carries the candidates.
    if (result.method === "ambiguous") {
        const n = result.subjects?.length ?? 0;
        return (
            (n
                ? `${n} products match these details`
                : "Several products match these details") +
            " — add another identifying detail to narrow it down to one."
        );
    }
    return (
        "This one was identified, but the installed packs hold nothing " +
        "about it yet. That is a coverage gap, not a clean bill of health."
    );
}

/** Enum values a reader has never seen, spelled out. Owned entirely here so a
 * new value the engine invents falls back to a readable (if generic)
 * sentence rather than a raw enum leaking onto the page (shell-18). */
const METHOD_WORD: Record<string, string> = {
    exact: "Matched exactly on the details given",
    identity: "Matched exactly on the details given",
    ambiguous: "Matched loosely — more than one variant fits",
    near: "Matched closely, but not exactly",
    no_match: "Not matched",
};
const COVERAGE_WORD: Record<string, string> = {
    RISKS_FOUND: "risks found",
    MATCHED_WITH_DATA: "risks found",
    MATCHED_NO_DATA: "nothing known yet",
    NOT_MATCHED: "",
};

/** The header line, in words rather than in enum values. */
export function confidenceNote(result: LookupResult): string {
    const how =
        METHOD_WORD[result.method] ??
        `Matched by ${(result.method || "unknown").replace(/_/g, " ")}`;
    const coverageWord =
        result.coverage && result.coverage !== "NOT_MATCHED"
            ? (COVERAGE_WORD[result.coverage] ??
                  result.coverage.toLowerCase().replace(/_/g, " "))
            : "";
    return coverageWord ? `${how}, coverage ${coverageWord}.` : `${how}.`;
}

/** The internal source word, in the reader's language (check-23). Owned here
 * rather than duplicated in every place a history row or a Result footer
 * prints one. */
const SOURCE_WORD: Record<string, string> = {
    ask: "described",
    analyze: "from a listing",
};

export const sourceWord = (source: string): string => SOURCE_WORD[source] ?? source;

/** A local date and time, not the raw ISO stamp the server stores it as. */
export const localTime = (iso: string): string => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return new Intl.DateTimeFormat(undefined, {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
    }).format(d);
};

export const askLine = (claim: Claim): string =>
    claim.advice?.trim() ||
    "Ask the seller for proof this has been dealt with, and have it checked.";


/** How far through the list the reader has got.
 *
 * Empty when nothing is ticked: "0 of 10 dealt with" on a report someone has
 * just opened is a scold, not information. The count is of claims still
 * present in this answer, so a checkmark left over from a claim a pack has
 * since dropped cannot push the number past the total.
 */
export function handledNote(result: LookupResult, handled: string[]): string {
    const marked = new Set(handled);
    const done = result.claims.filter((claim) => marked.has(claimKey(claim))).length;
    if (!done) return "";
    const total = result.claims.length;
    return done >= total
        ? `All ${total} dealt with`
        : `${done} of ${total} dealt with`;
}

/** What the answer was computed against, in the pack's own words.
 *
 * The reader's first question about a short report is "did it even know the
 * usage figure", and the payload carries the answer. Rendered as key/value
 * pairs exactly as the adapter sent them — naming a key here (or deciding which one
 * is "the important one") would be the hardcoded-pack-data bug in the one
 * place it is hardest to notice.
 */
export function contextLines(
    context: Record<string, unknown> | undefined,
    units: Record<string, string> | undefined = {},
): { key: string; value: string }[] {
    if (!context) return [];
    return Object.entries(context)
        .filter(([, value]) => value !== null && value !== undefined && value !== "")
        .map(([key, value]) => ({
            key: key.replace(/_/g, " "),
            value: `${value}${units?.[key] ? ` ${units[key]}` : ""}`,
        }));
}

/** The report as text, for a mechanic who does not have Kriko.
 *
 * Markdown rather than a PDF because the destination is a message: the reader
 * pastes this into whatever they already use to talk to the seller or the
 * garage. Print stays for paper (`print.css`); this is for handing over.
 *
 * Includes the reader's own notes when there are any — a report with "seller
 * says belt done at 140k, no receipt" beside the claim is the artifact, and
 * one without it is just the pack again.
 */
export function asMarkdown(
    result: LookupResult,
    options: {
        heading?: string;
        notes?: Record<string, string>;
        handled?: string[];
    } = {},
): string {
    const notes = options.notes ?? {};
    const done = new Set(options.handled ?? []);
    const lines: string[] = [`# ${options.heading || "Known risks"}`, ""];
    lines.push(`_Asked ${localTime(new Date().toISOString())}_`, "");
    // The figures this was answered for (check-29): a reader looking at this
    // on paper has no other way to know what product it describes.
    const contextLine = Object.entries(result.context ?? {})
        .filter(([, v]) => String(v).trim())
        .map(([k, v]) => `${humanize(k)} ${v}${result.context_units?.[k] ? ` ${result.context_units[k]}` : ""}`)
        .join(", ");
    if (contextLine) lines.push(`_Answered for ${contextLine}_`, "");
    lines.push(confidenceNote(result), "");
    if (!result.claims.length) {
        lines.push(emptyReason(result), "");
        return lines.join("\n");
    }
    for (const group of groupByDomain(result.claims)) {
        lines.push(`## ${humanize(group.domain)}`, "");
        for (const claim of group.claims) {
            const key = claimKey(claim);
            lines.push(
                `### ${severityWord(claim.severity)} — ${claim.title}`,
                "",
                claim.body,
                "",
                `**Ask:** ${askLine(claim)}`,
            );
            if (notes[key]) lines.push("", `**Answer:** ${notes[key]}`);
            if (done.has(key)) lines.push("", "*Dealt with.*");
            lines.push("", `_${sourceSummary(claim)}_`, "");
        }
    }
    // Named rather than implied. A report handed to someone else has to say
    // what it is not: this is what the installed packs know, and silence in it
    // is a coverage gap rather than a clean bill of health.
    lines.push(
        "---",
        "",
        "Produced by Kriko from installed knowledge packs. Absence of a risk " +
            "here means no pack holds one, not that there is none.",
    );
    return lines.join("\n");
}



/** What a score means, in words, before the number.
 *
 * `relevance`, `trust` and `detection` were author-only raw numbers with no
 * legend: 0.72 is unreadable without knowing the scale, which makes ranking
 * look like magic rather than something auditable. This says what the engine
 * did, and leaves the figure in brackets for whoever wants to check it.
 */
export function rankingNote(claim: Claim): string {
    const parts: string[] = [];
    const relevance = claim.relevance;
    if (typeof relevance === "number") {
        const word =
            relevance >= 0.8 ? "Close" : relevance >= 0.5 ? "Partial" : "Loose";
        parts.push(`${word} match to the details given (${relevance})`);
    }
    if (claim.detection) {
        parts.push(`matched by ${claim.detection.replace(/_/g, " ")}`);
    }
    if (typeof claim.trust === "number") {
        const word = claim.trust >= 0.8 ? "strong" : claim.trust >= 0.5 ? "fair" : "weak";
        parts.push(`${word} sourcing (${claim.trust})`);
    }
    return parts.join(" · ");
}

/** Why a report can be short, said out loud.
 *
 * The coverage lens answers "what is missing" for an author. A reader looking
 * at three claims has the same question and no screen for it, and the honest
 * answer is the one thing this project must never leave implied: silence here
 * is what the packs do not hold, not a clean bill of health.
 */
export const absenceNote = (result: LookupResult): string =>
    result.claims.length
        ? "This is what the installed packs hold about this one. Anything not " +
          "listed is knowledge nobody has published yet, or has not reached " +
          "your packs — not a risk that has been ruled out."
        : emptyReason(result);
