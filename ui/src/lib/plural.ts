/* "0 claim(s)" is how a screen tells the reader nobody looked at it.
 *
 * It was in six places across five components — the history rail, the match
 * list, the brief's tally, the health tree, and twice in Knowledge, which
 * managed "{n} claim(s) about {m} subject(s)" in one sentence. Each was a
 * separate author reaching for the same shortcut, which is the tell that the
 * missing thing was a helper rather than six edits.
 *
 * Zero is the case the parenthesis hides. "0 claim(s)" is not merely clumsy:
 * it reads as a count that failed to load, when what it means is that this
 * lookup matched nothing a pack knows about — which is a real answer and
 * should sound like one. So zero gets words, not a digit.
 *
 * English only, and deliberately so. A locale-aware plural rule is a
 * dependency and a config surface; the app ships one language today, and the
 * day it ships two this is the one function that has to change.
 */

/** `3 claims`, `1 claim`, `no claims`. */
export function count(n: number, one: string, many = `${one}s`): string {
    if (n === 1) return `1 ${one}`;
    return `${n === 0 ? "no" : n} ${many}`;
}

/* The noun on its own, for the places the number is not next to it.
 *
 * A stat tile renders the figure large and the word small beneath it, so there
 * is no string for `count` to build — but the word still has to agree with a
 * figure sitting in a different element. Without this those tiles were the last
 * refuge of the parenthesis. */
/** `runs`, `run`, `runs` — the word `count` would have used. */
export function word(n: number, one: string, many = `${one}s`): string {
    return n === 1 ? one : many;
}
