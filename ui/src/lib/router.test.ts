import { describe, expect, it } from "vitest";
import { parseHash, toHash } from "./router";

describe("parseHash", () => {
    it("defaults to ask when there is no hash", () => {
        expect(parseHash("")).toEqual({ name: "ask", params: [] });
        expect(parseHash("#")).toEqual({ name: "ask", params: [] });
        expect(parseHash("#/")).toEqual({ name: "ask", params: [] });
    });

    it("reads the view name and its params", () => {
        expect(parseHash("#/packs")).toEqual({ name: "packs", params: [] });
        expect(parseHash("#/result/abc123")).toEqual({
            name: "result",
            params: ["abc123"],
        });
    });

    it("decodes params so an id with a slash survives a round trip", () => {
        expect(parseHash(toHash("result", "a/b"))).toEqual({
            name: "result",
            params: ["a/b"],
        });
    });
});
