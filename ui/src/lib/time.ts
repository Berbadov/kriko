/** One place to turn a server timestamp into words, so every lens agrees.
 *
 * ops-6: the server writes UTC (`datetime.utcnow().isoformat()` and
 * friends), and three lenses (Live, Research runs, Submissions) rendered
 * that string by slicing characters out of it — which shows the UTC clock
 * face, unlabelled, right next to a fourth lens (Pipeline) that parsed the
 * same kind of string with `Date` and got the reader's own local time. On a
 * UTC+3 host the same run read "11:30" in one place and "2:30 PM" in
 * another. `Date` already knows the string is UTC (the `Z`/offset FastAPI's
 * JSON encoder writes) and converts it for free — the slicing was strictly
 * extra code for the wrong answer.
 */

function parse(at: string): Date | null {
    if (!at) return null;
    // Some rows are naive ("2026-09-25T11:35:00" with no offset) because they
    // were written before this fix; `Date` treats a naive string as local,
    // which would double-shift a value that is really UTC. Force it.
    const withZone = /[zZ]|[+-]\d\d:\d\d$/.test(at) ? at : `${at}Z`;
    const date = new Date(withZone);
    return Number.isNaN(date.getTime()) ? null : date;
}

/** A short clock face, for a row that only has room for the time. */
export function clock(at: string): string {
    const date = parse(at);
    return date ? date.toLocaleTimeString() : "";
}

/** Date and time together, for a row that spans more than a day. */
export function stamp(at: string): string {
    const date = parse(at);
    if (!date) return "";
    return date.toLocaleString(undefined, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
}

/** How long ago `at` was, as "45s" or "6m 12s" — for a run that is still going.
 *
 * B146: a live run showed one static sentence for minutes, and "it seems like
 * they are stuck" was how anyone would read it. A counter that
 * advances every second is the cheapest proof that the run is alive. */
export function elapsed(at: string | null | undefined, now: number = Date.now()): string {
    const date = parse(at ?? "");
    if (!date) return "";
    const whole = Math.max(0, Math.floor((now - date.getTime()) / 1000));
    if (whole < 60) return `${whole}s`;
    const minutes = Math.floor(whole / 60);
    if (minutes < 60) return `${minutes}m ${String(whole % 60).padStart(2, "0")}s`;
    return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}
