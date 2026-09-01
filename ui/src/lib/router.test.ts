import { describe, expect, it } from "vitest";
import { hashWith, parseHash, toHash } from "./router";

describe("parseHash", () => {
    it("defaults to check when there is no hash", () => {
        expect(parseHash("")).toEqual({ name: "check", params: [], query: {} });
        expect(parseHash("#")).toEqual({ name: "check", params: [], query: {} });
        expect(parseHash("#/")).toEqual({ name: "check", params: [], query: {} });
    });

    it("reads the view name and its params", () => {
        expect(parseHash("#/packs")).toEqual({ name: "packs", params: [], query: {} });
        expect(parseHash("#/result/abc123")).toEqual({
            name: "result",
            params: ["abc123"],
            query: {},
        });
    });

    it("decodes params so an id with a slash survives a round trip", () => {
        expect(parseHash(toHash("result", "a/b"))).toEqual({
            name: "result",
            params: ["a/b"],
            query: {},
        });
    });

    it("carries query state, so a pasted link opens in the mode it was written for", () => {
        expect(parseHash("#/result/abc?mode=author")).toEqual({
            name: "result",
            params: ["abc"],
            query: { mode: "author" },
        });
        expect(hashWith({ mode: "author" }, "result", "abc")).toBe(
            "#/result/abc?mode=author",
        );
    });

    it("drops empty query values rather than writing mode= into every link", () => {
        expect(hashWith({ mode: undefined }, "check")).toBe("#/check");
        expect(hashWith({ mode: "" }, "check")).toBe("#/check");
    });
});
