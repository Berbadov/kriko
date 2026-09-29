/* Wording for what to research next.
 *
 * The verdict-style rule from `report.ts` applies here too: the app may say a
 * source moved, never that a claim is false. And one row kind is not a task —
 * `unknown_subject` is a product this installation was asked about that no
 * subject exists for, so an agent cannot file anything against it and the
 * wording must not invite it to try.
 *
 * The keys are a closed vocabulary owned by `src/app/agenda.py`, and
 * `src/app/tests/test_agenda.py` fails if this map and `KINDS` there drift
 * apart — a row rendered as a bare token is the failure mode.
 */
import type { AgendaRow } from "./types";

const KIND_WORD: Record<string, string> = {
    empty_subject: "Nothing known yet",
    stale_claim: "A source moved",
    thin_subject: "Thinly supported",
    unknown_subject: "Not in the catalog",
};

const KIND_TONE: Record<string, string> = {
    empty_subject: "warn",
    stale_claim: "meta",
    thin_subject: "meta",
    unknown_subject: "warn",
};

export const kindWord = (kind: string): string => KIND_WORD[kind] ?? kind;
export const kindTone = (kind: string): string => KIND_TONE[kind] ?? "meta";

/** What to call the thing a row is about. An unknown identity has no label —
 * there is no subject to have named it — so the identity itself is the name. */
export function rowName(row: AgendaRow): string {
    return row.label || identityWords(row.identity) || row.subject_id || "Unnamed";
}

/** An identity arrives as the JSON the lookup stored — `{"a":"X","b":2008}`
 * printed as-is read like a stack trace. Its values, in order, are the name a
 * reader would have typed; anything that is not a JSON object stays as given. */
function identityWords(identity: string | undefined): string {
    if (!identity) return "";
    try {
        const parsed: unknown = JSON.parse(identity);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            const words = Object.values(parsed as Record<string, unknown>)
                .filter((value) => value !== null && value !== "" && typeof value !== "object")
                .map(String);
            if (words.length) return words.join(" ");
        }
    } catch {
        /* not JSON — an identity already in words */
    }
    return identity;
}

/** How often this installation was asked, in words rather than a bare integer.
 * "Asked about 0×" is noise; the absence of demand is not a number worth
 * printing. */
export function demandWord(row: AgendaRow): string {
    if (!row.asked) return "";
    return row.asked === 1 ? "asked about once" : `asked about ${row.asked}×`;
}

/** A row as a prompt, for a harness this app cannot reach.
 *
 * The tool call is spelled out with the real ids because the alternative is an
 * agent guessing them, and a finding filed against a guessed subject is worse
 * than no finding. An `unknown_subject` gets no call: nothing would accept it.
 */
export function promptFor(row: AgendaRow): string {
    const name = rowName(row);
    if (row.kind === "unknown_subject") {
        return (
            `Kriko was asked about ${name} and has no subject for it. ` +
            `This is a catalog gap, not a research task: do not submit findings ` +
            `against another subject.`
        );
    }
    const call = `research_brief("${row.subject_id}", "${row.pack_id}")`;
    if (row.kind === "stale_claim") {
        return (
            `The page cited for a claim about ${name} no longer contains its ` +
            `quote. Call ${call}, re-read the source, and file what it says now ` +
            `with submit_findings. Say the page changed; do not say the claim is false.`
        );
    }
    if (row.kind === "thin_subject") {
        return (
            `A claim about ${name} rests on too little. Call ${call} and look for ` +
            `an independent source, then submit_findings with the quote you found.`
        );
    }
    return (
        `Research ${name} for Kriko. Call ${call} for what counts as worth ` +
        `keeping, then submit_findings with a verbatim quote for each finding.`
    );
}
