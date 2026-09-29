import { describe, expect, it } from "vitest";
import { demandWord, kindTone, kindWord, promptFor, rowName } from "./agenda";
import type { AgendaRow } from "./types";

const ROW = (over: Partial<AgendaRow> = {}): AgendaRow =>
    ({
        kind: "empty_subject",
        subject_id: "s1",
        pack_id: "org.example.pack",
        label: "A thing",
        why: "nothing known yet",
        asked: 0,
        ...over,
    }) as AgendaRow;

describe("wording for what to research next", () => {
    it("never renders a kind as the token the database stores", () => {
        // The one failure mode the Python drift gate exists to catch, asserted
        // from this side too: every kind the union allows has a sentence.
        for (const kind of [
            "empty_subject",
            "stale_claim",
            "thin_subject",
            "unknown_subject",
        ] as const) {
            expect(kindWord(kind)).not.toContain("_");
            expect(["warn", "meta"]).toContain(kindTone(kind));
        }
    });

    it("says a source moved and never that the claim is false", () => {
        const prompt = promptFor(ROW({ kind: "stale_claim", claim_id: "c1" }));
        expect(prompt).toMatch(/no longer contains its quote/);
        expect(prompt).toMatch(/do not say the claim is false/);
        expect(prompt).not.toMatch(/wrong|false claim|refuted/);
    });

    it("refuses to invite a finding against something the catalog cannot name", () => {
        // `unknown_subject` has no subject_id an agent could file against, so
        // the prompt must not contain a call that takes one. An agent that
        // invents one files a real finding against the wrong car.
        const prompt = promptFor(
            ROW({ kind: "unknown_subject", subject_id: "", label: "", identity: "{a}" }),
        );
        expect(prompt).not.toContain("submit_findings(");
        expect(prompt).toMatch(/do not submit findings/);
        expect(prompt).toMatch(/catalog gap/);
    });

    it("spells out the real ids so nothing has to be guessed", () => {
        const prompt = promptFor(ROW({ subject_id: "s-audi", pack_id: "org.k.cars" }));
        expect(prompt).toContain('research_brief("s-audi", "org.k.cars")');
        expect(prompt).toContain("submit_findings");
    });

    it("names an unknown identity by the identity, having nothing else", () => {
        expect(rowName(ROW({ label: "", identity: "make=x" }))).toBe("make=x");
        expect(rowName(ROW())).toBe("A thing");
    });

    it("reads a JSON identity as words, not as the JSON (B146)", () => {
        const identity = JSON.stringify({ a: "Subaru", b: "Impreza", c: 2008, d: null });
        expect(rowName(ROW({ label: "", identity }))).toBe("Subaru Impreza 2008");
    });

    it("prints demand as words, and prints nothing when there is none", () => {
        expect(demandWord(ROW({ asked: 0 }))).toBe("");
        expect(demandWord(ROW({ asked: 1 }))).toBe("asked about once");
        expect(demandWord(ROW({ asked: 4 }))).toContain("4");
    });
});
