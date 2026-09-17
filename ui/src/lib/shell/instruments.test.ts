import { afterEach, describe, expect, it, vi } from "vitest";
import { stubFetch } from "../stub-fetch";
import { read, unwatch } from "./instruments";

afterEach(() => {
    unwatch();
    vi.unstubAllGlobals();
});

const usage = (over = {}) => ({
    research: { spent_usd: 1.25, planes: [], ...over },
    analyses: {},
});

describe("reading the rail's three numbers", () => {
    it("reads claims, running jobs and spend from endpoints that already exist", async () => {
        stubFetch({
            "/api/status": { ok: true, packs: 1, enabled_packs: 1, counts: { claims: 162 } },
            "/api/jobs": { items: [{ done: false }, { done: true }] },
            "/api/usage": usage(),
        });
        const out = await read();
        expect(out.claims).toBe(162);
        expect(out.running).toBe(1);
        expect(out.spentUsd).toBe(1.25);
        expect(out.stale).toBe(false);
    });

    it("keeps the numbers it could read when one endpoint dies", async () => {
        // The whole reason for allSettled. A rail that blanks two good figures
        // because a third request failed reads as "you have nothing".
        stubFetch({
            "/api/status": { ok: true, packs: 1, enabled_packs: 1, counts: { claims: 8 } },
            "/api/jobs": { status: 500, body: "nope" },
            "/api/usage": usage(),
        });
        const out = await read();
        expect(out.claims).toBe(8);
        expect(out.running).toBeNull();
        expect(out.spentUsd).toBe(1.25);
        expect(out.stale).toBe(false);
    });

    it("calls itself stale only when nothing at all could be read", async () => {
        stubFetch({
            "/api/status": { status: 500, body: "nope" },
            "/api/jobs": { status: 500, body: "nope" },
            "/api/usage": { status: 500, body: "nope" },
        });
        expect((await read()).stale).toBe(true);
    });

    it("reports an unpriced total as unknown rather than as zero", async () => {
        stubFetch({
            "/api/status": { ok: true, packs: 0, enabled_packs: 0, counts: {} },
            "/api/jobs": { items: [] },
            "/api/usage": usage({ spent_usd: null }),
        });
        const out = await read();
        expect(out.spentUsd).toBeNull();
        expect(out.claims).toBeNull();
    });

    it("draws no trail from a single plane, because one point is not a shape", async () => {
        stubFetch({
            "/api/status": { ok: true, packs: 1, enabled_packs: 1, counts: { claims: 1 } },
            "/api/jobs": { items: [] },
            "/api/usage": usage({ planes: [{ plane: "a", spent_usd: 0.4 }] }),
        });
        expect((await read()).trail).toEqual([]);
    });

    it("keeps the priced planes in order and drops the ones nobody could price", async () => {
        stubFetch({
            "/api/status": { ok: true, packs: 1, enabled_packs: 1, counts: { claims: 1 } },
            "/api/jobs": { items: [] },
            "/api/usage": usage({
                planes: [
                    { plane: "a", spent_usd: 0.4 },
                    { plane: "b", spent_usd: null },
                    { plane: "c", spent_usd: 0.9 },
                ],
            }),
        });
        expect((await read()).trail).toEqual([0.4, 0.9]);
    });
});
