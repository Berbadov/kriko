import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import RunWith from "./RunWith.svelte";
import { stubFetch } from "./stub-fetch";

/* B158: the Run screen's LLM pick says when the agent lists no LLMs. */

const prefs = (harness: Record<string, unknown>) => ({
    chosen: { preferred_harness: "" },
    harnesses: [{ id: "mistral-vibe", label: "Mistral Vibe", command: "vibe", llm_selectable: true, ...harness }],
});

describe("RunWith", () => {
    it("says an agent lists no LLMs instead of showing an empty pick", async () => {
        stubFetch({ "/api/prefs": prefs({ llms: [], llms_note: "This CLI does not list its models" }) });
        render(RunWith);
        expect(await screen.findByText("This CLI does not list its models")).toBeInTheDocument();
        expect(screen.queryByRole("combobox", { name: "LLM" })).toBeNull();
    });

    it("keeps the list for an agent that lists LLMs", async () => {
        stubFetch({ "/api/prefs": prefs({ llms: ["a-model"], llms_note: "" }) });
        render(RunWith);
        expect(await screen.findByRole("option", { name: "a-model" })).toBeInTheDocument();
        expect(screen.queryByText("This CLI does not list its models")).toBeNull();
    });
});
