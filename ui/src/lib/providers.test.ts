import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import ProviderMark from "./ProviderMark.svelte";
import { markFor } from "./providers";

describe("markFor", () => {
    it("reads a harness id", () => {
        expect(markFor("claude-code")).toBe("anthropic");
        expect(markFor("antigravity-cli")).toBe("google");
        expect(markFor("opencode")).toBe("opencode");
        expect(markFor("mistral-vibe")).toBe("mistral");
    });

    it("reads a model name the CLI listed, including one released later", () => {
        expect(markFor("claude-sonnet-9")).toBe("anthropic");
        expect(markFor("gemini-3-pro")).toBe("google");
        expect(markFor("openai/gpt-7")).toBe("openai");
    });

    it("lets a harness that runs other vendors' models keep its own mark", () => {
        expect(markFor("opencode-anthropic/claude-x")).toBe("opencode");
    });

    it("never guesses: an unknown name is the generic mark", () => {
        expect(markFor("some-new-vendor-1")).toBe("generic");
        expect(markFor("")).toBe("generic");
        expect(markFor(undefined)).toBe("generic");
    });
});

describe("ProviderMark", () => {
    it("draws the mark its name resolves to, hidden from screen readers", () => {
        const { container } = render(ProviderMark, { name: "gemini-2.5-pro" });
        const svg = container.querySelector("svg");
        expect(svg?.getAttribute("data-mark")).toBe("google");
        expect(svg?.getAttribute("aria-hidden")).toBe("true");
    });
});
