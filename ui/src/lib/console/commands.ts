import { api } from "../api";
import { follow } from "../jobs";
import { navigate } from "../router";

/* The console's vocabulary, kept apart from its chrome.
 *
 * Two decisions are load-bearing here, and both are about what this is *not*.
 *
 * **It is not a shell.** There is no `sh -c`, no server endpoint that runs a
 * command a caller names, and there never will be: this process listens on a
 * fixed port that a browser extension also talks to, so a "run this for me"
 * route is a remote-code-execution hole with a friendly name — the same
 * reasoning `/api/agent-verify` is written down with. Every verb below is a
 * fixed call against the HTTP API the screens already use, dispatched from the
 * browser. The console therefore adds *no* server surface at all; it is a
 * keyboard over the API, and its authority is exactly the window's.
 *
 * **It is not a second implementation.** A verb that computed something the
 * screens compute differently would be a second truth about the same store.
 * Each handler calls `api.*` and formats; none of them reason.
 *
 * Handlers report through `emit` rather than returning a string, because the
 * useful ones are not instantaneous — a research run streams its log for
 * several seconds and the terminal has to fill while it does.
 */

export type Line = { kind: "in" | "out" | "err" | "note"; text: string };
export type Emit = (line: Line) => void;

export type Command = {
    name: string;
    /** Argument shape, shown by `help` and on a usage error. */
    usage: string;
    summary: string;
    run: (args: string[], emit: Emit) => Promise<void>;
};

const out = (emit: Emit, text: string) => emit({ kind: "out", text });
const note = (emit: Emit, text: string) => emit({ kind: "note", text });

/** Right-pad, for columns that stay columns in a proportional-font fallback. */
const pad = (text: string, width: number) =>
    text.length >= width ? text : text + " ".repeat(width - text.length);

const json = (value: unknown) => JSON.stringify(value, null, 2);

/** A table, as text. Widths from the content, capped so one long id cannot
 *  push every other column off the right edge. */
export function table(rows: string[][], max = 44): string {
    if (!rows.length) return "";
    const widths = rows[0].map((_, column) =>
        Math.min(max, Math.max(...rows.map((row) => (row[column] ?? "").length))),
    );
    return rows
        .map((row) =>
            row
                .map((cell, column) =>
                    column === row.length - 1 ? cell : pad(cell ?? "", widths[column] + 2),
                )
                .join("")
                .trimEnd(),
        )
        .join("\n");
}

/** The `k=v` shape to type, spelled from whatever the first pack declares.
 *
 * Falls back to the generic form when nothing is installed or the request
 * fails: a usage hint must never be the reason a command errors.
 */
async function usage(): Promise<string> {
    try {
        const packs = await api.packs();
        const first = packs[0];
        if (!first) return "<key>=<value>";
        const keys = await api.identityKeys(first.pack_id);
        const named = keys.slice(0, 3).map((key) => `${key.key}=…`);
        return named.length ? named.join(" ") : "<key>=<value>";
    } catch {
        return "<key>=<value>";
    }
}

/** `key=value key=value` → an object. The console's only syntax.
 *
 * Chosen over positional arguments because the engine has no fixed columns:
 * a pack declares its own identity keys, so nothing here may assume which
 * ones exist or what order they come in. `k=v` is the shape that survives a
 * pack the console has never heard of.
 */
export function parseFields(args: string[]): Record<string, string> {
    const fields: Record<string, string> = {};
    for (const arg of args) {
        const at = arg.indexOf("=");
        if (at > 0) fields[arg.slice(0, at)] = arg.slice(at + 1);
    }
    return fields;
}

/** Split a line into a verb and its arguments, honouring double quotes. */
export function tokenize(line: string): string[] {
    const tokens: string[] = [];
    const pattern = /"([^"]*)"|(\S+)/g;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(line)) !== null) tokens.push(match[1] ?? match[2]);
    return tokens;
}

/** Watch a job to completion, printing its log as it arrives. */
function streamJob(jobId: string, emit: Emit): Promise<void> {
    return new Promise((resolve) => {
        let printed = 0;
        follow(jobId, (job) => {
            // Only the tail is new. The row carries the whole log every poll,
            // so printing it verbatim would repeat everything each tick.
            const fresh = (job.log ?? "").slice(printed);
            printed = (job.log ?? "").length;
            for (const text of fresh.split("\n").filter(Boolean)) out(emit, `  ${text}`);
            if (!job.done) return;
            if (job.state === "succeeded") note(emit, `✓ ${job.message || job.state}`);
            else emit({ kind: "err", text: `✗ ${job.state}: ${job.message}` });
            resolve();
        });
    });
}

export const COMMANDS: Command[] = [
    {
        name: "help",
        usage: "help [verb]",
        summary: "what this console understands",
        async run(args, emit) {
            if (args[0]) {
                const found = COMMANDS.find((c) => c.name === args[0]);
                if (!found) return emit({ kind: "err", text: `no such verb: ${args[0]}` });
                return out(emit, `${found.usage}\n    ${found.summary}`);
            }
            note(emit, "Every verb is one call against this app's own HTTP API.");
            out(
                emit,
                table(COMMANDS.map((command) => [command.usage, command.summary])),
            );
        },
    },
    {
        name: "health",
        usage: "health",
        summary: "engine, store paths, versions",
        async run(_args, emit) {
            const health = await api.health();
            out(
                emit,
                table([
                    ["engine", health.ok ? "ok" : "unwell"],
                    ["app version", health.version],
                    ["schema", String(health.schema_version)],
                    ["knowledge store", health.store],
                    ["app state", health.app_state],
                ]),
            );
        },
    },
    {
        name: "status",
        usage: "status",
        summary: "row counts in the store",
        async run(_args, emit) {
            const status = await api.status();
            out(
                emit,
                table([
                    ["packs", `${status.enabled_packs} of ${status.counts.packs} enabled`],
                    ...Object.entries(status.counts).map(([key, value]) => [
                        key,
                        String(value),
                    ]),
                ]),
            );
        },
    },
    {
        name: "packs",
        usage: "packs [on|off <pack_id>]",
        summary: "installed packs; switch one on or off",
        async run(args, emit) {
            const [verb, packId] = args;
            if (verb === "on" || verb === "off") {
                if (!packId) return emit({ kind: "err", text: `packs ${verb} <pack_id>` });
                await api.setEnabled(packId, verb === "on");
                note(emit, `${packId} is now ${verb === "on" ? "enabled" : "disabled"}`);
            }
            const packs = await api.packs();
            if (!packs.length) return note(emit, "no packs installed");
            out(
                emit,
                table([
                    ["PACK", "VERSION", "ON", "SUBJECTS", "CLAIMS"],
                    ...packs.map((pack) => [
                        pack.pack_id,
                        pack.version,
                        pack.enabled ? "yes" : "no",
                        String(pack.subjects),
                        String(pack.claims),
                    ]),
                ]),
            );
        },
    },
    {
        name: "subjects",
        usage: "subjects [search…]",
        summary: "subjects an enabled pack covers",
        async run(args, emit) {
            const rows = await api.subjects(args.join(" "), 200);
            if (!rows.length)
                return note(
                    emit,
                    "nothing matched — a switched-off pack contributes no subjects",
                );
            out(
                emit,
                table([
                    ["SUBJECT", "CLAIMS", "ID"],
                    ...rows.map((row) => [
                        row.label,
                        String(row.claims),
                        row.subject_id.slice(0, 12),
                    ]),
                ]),
            );
            note(emit, `${rows.length} subject(s)`);
        },
    },
    {
        name: "subject",
        usage: "subject <subject_id>",
        summary: "one subject: attributes and claims",
        async run(args, emit) {
            if (!args[0]) return emit({ kind: "err", text: "subject <subject_id>" });
            const found = await resolveSubject(args[0], emit);
            if (!found) return;
            const detail = await api.subject(found);
            out(emit, `${detail.label}   (${detail.kind}, ${detail.pack_id})`);
            out(
                emit,
                table(
                    detail.attributes.map((attr) => [
                        attr.is_identity ? `* ${attr.key}` : `  ${attr.key}`,
                        `${attr.value_text}${attr.unit ? ` ${attr.unit}` : ""}`,
                    ]),
                ),
            );
            if (!detail.claims.length) return note(emit, "no claims — this is a gap");
            out(
                emit,
                table([
                    ["SEVERITY", "DOMAIN", "CLAIM"],
                    ...detail.claims.map((claim) => [
                        claim.severity,
                        claim.domain,
                        claim.title ?? claim.claim_id,
                    ]),
                ]),
            );
        },
    },
    {
        name: "gaps",
        usage: "gaps",
        summary: "subjects nothing is known about",
        async run(_args, emit) {
            const packs = await api.packs();
            let total = 0;
            for (const pack of packs) {
                const gaps = await api.gaps(pack.pack_id);
                total += gaps.length;
                if (!gaps.length) continue;
                note(emit, `${pack.pack_id} — ${gaps.length} gap(s)`);
                out(
                    emit,
                    table(gaps.map((gap) => [gap.label, gap.kind, gap.subject_id.slice(0, 12)])),
                );
            }
            if (!total) note(emit, "no gaps reported");
        },
    },
    {
        name: "brief",
        usage: "brief <subject_id>",
        summary: "the pack's research brief for one subject",
        async run(args, emit) {
            if (!args[0]) return emit({ kind: "err", text: "brief <subject_id>" });
            const found = await resolveSubject(args[0], emit);
            if (!found) return;
            const brief = await api.brief(found);
            out(emit, brief.brief);
            note(emit, `${brief.queries.length} query(ies) planned`);
        },
    },
    {
        name: "research",
        usage: "research <subject_id>",
        summary: "run the research job and stream its log",
        async run(args, emit) {
            if (!args[0]) return emit({ kind: "err", text: "research <subject_id>" });
            const found = await resolveSubject(args[0], emit);
            if (!found) return;
            const { job_id } = await api.research({ subject_id: found });
            note(emit, `job ${job_id}`);
            await streamJob(job_id, emit);
            note(
                emit,
                "the $0 plane gathers nothing itself — `brief` prints what an agent " +
                    "is meant to go and read",
            );
        },
    },
    {
        name: "lookup",
        usage: "lookup k=v [k=v…]",
        summary: "ask the packs about one thing",
        async run(args, emit) {
            // `kind=` is a field like any other so the console needs no
            // per-pack knowledge: a pack declares its own identity keys, and
            // "product" is the kind every pack has.
            const fields = parseFields(args);
            const kind = fields.kind ?? "product";
            delete fields.kind;
            if (!Object.keys(fields).length)
                // The example is spelled from the pack's own declared keys
                // rather than hardcoded here: a usage string naming one
                // category's fields is the same violation as a form doing it,
                // and would be wrong for the second pack installed.
                return emit({ kind: "err", text: `lookup ${await usage()}` });
            const result = await api.lookup({ kind, identity: fields, context: {} });
            if (!result.claims.length) return note(emit, "nothing known");
            out(
                emit,
                table([
                    ["SEVERITY", "CLAIM"],
                    ...result.claims.map((claim) => [claim.severity, claim.title]),
                ]),
            );
            note(emit, `${result.claims.length} claim(s), coverage ${result.coverage}`);
        },
    },
    {
        name: "weakest",
        usage: "weakest [n]",
        summary: "thinnest-supported claims, worst first",
        async run(args, emit) {
            const limit = Number(args[0]) || 15;
            const { claims } = await api.weakest(limit);
            if (!claims.length) return note(emit, "no sourced claims installed");
            out(
                emit,
                table([
                    ["SOURCES", "BEST", "REFUTED", "CLAIM"],
                    ...claims.map((claim) => [
                        String(claim.independent_sources),
                        claim.best_tier,
                        claim.refuted_by ? String(claim.refuted_by) : "-",
                        claim.title,
                    ]),
                ]),
            );
        },
    },
    {
        name: "jobs",
        usage: "jobs [job_id]",
        summary: "recent runs, or follow one",
        async run(args, emit) {
            if (args[0]) {
                const job = await api.job(args[0]);
                out(emit, json({ ...job, log: undefined }));
                if (job.log) out(emit, job.log);
                if (!job.done) await streamJob(job.job_id, emit);
                return;
            }
            const { items } = await api.jobs(20);
            if (!items.length) return note(emit, "nothing has run yet");
            out(
                emit,
                table([
                    ["JOB", "KIND", "STATE", "MESSAGE"],
                    ...items.map((job) => [
                        job.job_id.slice(0, 12),
                        job.kind,
                        job.state,
                        job.message,
                    ]),
                ]),
            );
        },
    },
    {
        name: "cancel",
        usage: "cancel <job_id>",
        summary: "ask a running job to stop",
        async run(args, emit) {
            if (!args[0]) return emit({ kind: "err", text: "cancel <job_id>" });
            const { state } = await api.cancelJob(args[0]);
            note(emit, `${args[0]} is ${state}`);
        },
    },
    {
        name: "build",
        usage: "build <pack-directory>",
        summary: "build a pack and install it",
        async run(args, emit) {
            if (!args[0]) return emit({ kind: "err", text: "build <pack-directory>" });
            const { job_id } = await api.buildPack(args[0]);
            note(emit, `job ${job_id}`);
            await streamJob(job_id, emit);
        },
    },
    {
        name: "agent",
        usage: "agent",
        summary: "which harnesses reach this store",
        async run(_args, emit) {
            const [targets, config] = await Promise.all([
                api.agentTargets(),
                api.agentConfig(),
            ]);
            out(
                emit,
                table([
                    ["HARNESS", "STATE", "CONFIG"],
                    ...targets.targets.map((target) => [
                        target.label,
                        target.state,
                        target.path,
                    ]),
                ]),
            );
            note(emit, `store: ${config.store}`);
        },
    },
    {
        name: "open",
        usage: "open <view>",
        summary: "go to a screen without the mouse",
        async run(args, emit) {
            if (!args[0]) return emit({ kind: "err", text: "open <view>" });
            navigate(args[0], ...args.slice(1));
            note(emit, `opened ${args[0]}`);
        },
    },
];

/** Accept a 12-character prefix wherever a full subject id is wanted.
 *
 * Every listing above abbreviates ids to keep its columns readable, so the id
 * a reader can *see* is not one the API accepts. Making them retype the long
 * form from another screen would be the console's own output being useless as
 * input, which is the one thing a terminal must never be.
 */
async function resolveSubject(given: string, emit: Emit): Promise<string | null> {
    if (given.length >= 32) return given;
    const rows = await api.subjects("", 500);
    const matches = rows.filter((row) => row.subject_id.startsWith(given));
    if (matches.length === 1) return matches[0]!.subject_id;
    if (!matches.length) {
        emit({ kind: "err", text: `no subject id starts with ${given}` });
        return null;
    }
    emit({ kind: "err", text: `${given} matches ${matches.length} subjects` });
    return null;
}

export const byName = (name: string): Command | undefined =>
    COMMANDS.find((command) => command.name === name);

export const VERBS = COMMANDS.map((command) => command.name);

/** Longest common prefix of the verbs a fragment could become — what Tab
 *  completes to. Returns the fragment unchanged when nothing matches. */
export function complete(fragment: string): { value: string; options: string[] } {
    const options = VERBS.filter((verb) => verb.startsWith(fragment));
    if (!options.length) return { value: fragment, options: [] };
    let value = options[0];
    for (const option of options.slice(1)) {
        let index = 0;
        while (index < value.length && value[index] === option[index]) index += 1;
        value = value.slice(0, index);
    }
    return { value, options };
}
