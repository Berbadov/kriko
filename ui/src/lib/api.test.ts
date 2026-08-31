import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

describe("api", () => {
    beforeEach(() => vi.unstubAllGlobals());

    it("returns parsed JSON on success", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => new Response(JSON.stringify({ ok: true, packs: 2 }))),
        );
        await expect(api.status()).resolves.toEqual({ ok: true, packs: 2 });
    });

    it("throws ApiError carrying the status code", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => new Response("no adapter", { status: 404 })),
        );
        const error = await api.status().catch((e) => e);
        expect(error).toBeInstanceOf(ApiError);
        expect(error.status).toBe(404);
        expect(error.message).toContain("no adapter");
    });

    it("encodes path segments so an id with a slash cannot escape", async () => {
        const fetchMock = vi.fn(async () => new Response("[]"));
        vi.stubGlobal("fetch", fetchMock);
        await api.identityKeys("a/b");
        expect(fetchMock.mock.calls[0][0]).toBe("/api/identity-keys/a%2Fb");
    });
});
