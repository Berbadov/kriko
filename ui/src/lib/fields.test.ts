import { describe, expect, it } from "vitest";
import { coerce, collect, humanize } from "./fields";

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

describe("humanize", () => {
    it("turns a pack's key into something a reader can read", () => {
        expect(humanize("engine_code")).toBe("Engine code");
        expect(humanize("odometer_km")).toBe("Odometer km");
    });

    it("leaves an already-readable label alone", () => {
        expect(humanize("Year")).toBe("Year");
    });

    it("survives the shapes a key can actually arrive in", () => {
        expect(humanize("")).toBe("");
        expect(humanize("a")).toBe("A");
        expect(humanize("__")).toBe("");
    });

    it("is a transform, not a table — an unseen key still reads", () => {
        expect(humanize("thermal_paste_grade")).toBe("Thermal paste grade");
    });
});
