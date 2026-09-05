import { describe, expect, it } from "vitest";
import { nextStep, type Signals } from "./nextStep";

const OK: Signals = {
    packs: 1,
    enabled: 1,
    gaps: 0,
    agentsConnected: 1,
    agentsKnown: 2,
    updatable: 0,
    checks: 3,
    extensionConnected: true,
};
const at = (over: Partial<Signals>) => nextStep({ ...OK, ...over })?.id ?? null;

describe("the next step", () => {
    it("asks for the extension once a check has been run, and before an agent", () => {
        // The extension is what the reader came for; the agent is maintenance.
        expect(at({ extensionConnected: false })).toBe("install-extension");
        expect(at({ extensionConnected: false, agentsConnected: 0 })).toBe(
            "install-extension",
        );
        // But not before they have seen the app answer anything at all.
        expect(at({ extensionConnected: false, checks: 0 })).toBe("first-check");
    });

    it("does not suggest an extension a build does not carry", () => {
        // `null` is "no answer", and a hint bar that invents a missing feature
        // is worse than a silent one.
        expect(at({ extensionConnected: null })).toBeNull();
    });

    it("says nothing when there is nothing to say", () => {
        expect(nextStep(OK)).toBeNull();
    });

    it("asks for a pack before anything else", () => {
        // Every other signal is also screaming here. None of them are
        // actionable without knowledge in the store.
        expect(
            at({ packs: 0, enabled: 0, checks: 0, gaps: 9, agentsConnected: 0 }),
        ).toBe("install-pack");
    });

    it("counts an installed-but-disabled pack as no pack at all", () => {
        expect(at({ enabled: 0 })).toBe("enable-pack");
    });

    it("waits for the reader to see one answer before selling them research", () => {
        // The ordering that matters most: connect-agent outranks nothing until
        // a check has been run, because it asks someone to maintain a pipeline
        // feeding a thing they have not watched work once.
        expect(at({ checks: 0, agentsConnected: 0, gaps: 9 })).toBe("first-check");
        expect(at({ checks: 1, agentsConnected: 0, gaps: 9 })).toBe("connect-agent");
    });

    it("does not ask for a harness this build cannot write a config for", () => {
        expect(at({ agentsConnected: 0, agentsKnown: 0, gaps: 9 })).toBe("close-gaps");
    });

    it("prefers updating knowledge over researching against a stale copy", () => {
        expect(at({ updatable: 2, gaps: 9 })).toBe("update-packs");
    });

    it("names the count it is talking about", () => {
        expect(nextStep({ ...OK, gaps: 1 })?.title).toContain("1 subject with");
        expect(nextStep({ ...OK, gaps: 4 })?.title).toContain("4 subjects with");
    });
});
