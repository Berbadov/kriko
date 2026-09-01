import { describe, expect, it } from "vitest";
import { coerce, collect } from "./fields";

describe("coerce", () => {
    it("keeps a numeric string as a number", () => {
        expect(coerce("190000")).toBe(190000);
    });
    it("keeps a non-numeric string as text", () => {
        expect(coerce("acme-industrial")).toBe("acme-industrial");
    });
    it("does not turn an empty string into zero", () => {
        expect(coerce("")).toBe("");
    });
});

describe("collect", () => {
    it("drops blank fields so an untouched input is not sent as an empty value", () => {
        expect(collect({ a: "x", b: "  ", c: "7" })).toEqual({ a: "x", c: 7 });
    });
    it("tolerates undefined values from an unbound input", () => {
        expect(collect({ a: undefined as unknown as string, b: "y" })).toEqual({ b: "y" });
    });
});
