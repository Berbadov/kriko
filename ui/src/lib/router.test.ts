import { describe, expect, it } from "vitest";
import { hashWith, parseHash, toHash } from "./router";

describe("parseHash", () => {
    it("defaults to Activity when there is no hash (B163)", () => {
        expect(parseHash("")).toEqual({ name: "activity", params: [], query: {} });
        expect(parseHash("#")).toEqual({ name: "activity", params: [], query: {} });
        expect(parseHash("#/")).toEqual({ name: "activity", params: [], query: {} });
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

    it("carries query state other than the retired mode", () => {
        expect(parseHash("#/activity?lens=runs")).toEqual({
            name: "activity",
            params: [],
            query: { lens: "runs" },
        });
        expect(hashWith({ lens: "runs" }, "activity")).toBe("#/activity?lens=runs");
    });

    it("never reads a mode from an address, so an old link cannot carry one on (B165)", () => {
        expect(parseHash("#/result/abc?mode=author")).toEqual({
            name: "result",
            params: ["abc"],
            query: {},
        });
    });

    it("drops empty query values rather than writing lens= into every link", () => {
        expect(hashWith({ lens: undefined }, "activity")).toBe("#/activity");
        expect(hashWith({ lens: "" }, "activity")).toBe("#/activity");
    });

    it("sends the retired question sheet to the result it was for (B163)", () => {
        // The extension's "Ask the seller" hands over `questions/<id>`.
        expect(parseHash("#/questions/abc")).toEqual({ name: "result", params: ["abc"], query: {} });
        expect(parseHash("#/questions?id=abc")).toEqual({ name: "result", params: ["abc"], query: {} });
        // No id: the newest answer used to open; History is where it is chosen.
        expect(parseHash("#/questions")).toEqual({ name: "history", params: [], query: {} });
    });

    it("keeps a malformed %-escape raw instead of throwing and blanking the app", () => {
        expect(() => parseHash("#/subject/%E0%A4%A")).not.toThrow();
        expect(parseHash("#/subject/%E0%A4%A")).toEqual({
            name: "subject",
            params: ["%E0%A4%A"],
            query: {},
        });
    });
});
