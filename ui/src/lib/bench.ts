import type { Bench } from "./types";

export type BenchPoint = {
    protocol: string;
    batchSize: number;
    contextChars: number;
    preamble: string;
    hallucinationRate: number;
    hallucinationInterval: [number, number] | null;
    usdPerAcceptedClaim: number | null;
    runs: number;
    chosen: boolean;
};

const HALLUCINATION_LOW_MAX = 0.05;
const HALLUCINATION_MEDIUM_MAX = 0.15;

export const hallucinationSeverity = (rate: number | null): "high" | "medium" | "low" | "" => {
    if (rate === null) return "";
    if (rate <= HALLUCINATION_LOW_MAX) return "low";
    if (rate <= HALLUCINATION_MEDIUM_MAX) return "medium";
    return "high";
};

export const formatUsd = (value: number | null, digits = 4): string =>
    value === null ? "n/a" : `$${value.toFixed(digits)}`;

export const formatPct = (value: number | null, digits = 1): string =>
    value === null ? "n/a" : `${(value * 100).toFixed(digits)}%`;

export const formatInterval = (interval: [number, number] | null): string =>
    interval === null ? "" : `${(interval[0] * 100).toFixed(0)}–${(interval[1] * 100).toFixed(0)}%`;

type UsdAccumulator = { usd: number; accepted: number; priced: boolean };

const groupKey = (plane: string, llm: string, protocol: string) =>
    `${plane}::${llm}::${protocol}`;

export function pointsByLlm(bench: Bench): Record<string, BenchPoint[]> {
    const protocolMeta = new Map(bench.protocols.map((one) => [one.name, one]));
    const usdByKey = new Map<string, UsdAccumulator>();
    for (const row of bench.summary) {
        const key = groupKey(row.plane, row.llm, row.protocol);
        const acc = usdByKey.get(key) ?? { usd: 0, accepted: 0, priced: false };
        if (row.usd !== null) {
            acc.usd += row.usd;
            acc.priced = true;
        }
        acc.accepted += row.accepted ?? 0;
        usdByKey.set(key, acc);
    }

    const out: Record<string, BenchPoint[]> = {};
    for (const group of bench.scored.groups) {
        if (!group.llm || group.hallucination_rate === null) continue;
        const meta = protocolMeta.get(group.protocol);
        const priced = usdByKey.get(groupKey(group.plane, group.llm, group.protocol));
        const list = out[group.llm] ?? (out[group.llm] = []);
        list.push({
            protocol: group.protocol,
            batchSize: meta?.batch_size ?? 0,
            contextChars: meta?.context_chars ?? 0,
            preamble: meta?.preamble ?? "",
            hallucinationRate: group.hallucination_rate,
            hallucinationInterval: group.hallucination_interval,
            usdPerAcceptedClaim:
                priced && priced.priced && priced.accepted > 0
                    ? priced.usd / priced.accepted
                    : null,
            runs: group.runs,
            chosen: bench.chosen[group.llm] === group.protocol,
        });
    }
    for (const list of Object.values(out)) {
        list.sort((a, b) => Number(b.chosen) - Number(a.chosen) || a.protocol.localeCompare(b.protocol));
    }
    return out;
}

export const plottable = (points: BenchPoint[]): BenchPoint[] =>
    points.filter((point) => point.usdPerAcceptedClaim !== null);
