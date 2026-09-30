import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import RunWith from "./RunWith.svelte";
import { stubFetch } from "./stub-fetch";

/* B175: the Run screen's dials. Marks on agents and models, the LLM list asked
 * of the CLI when the screen opens, and no paragraph under any control. */

const prefs = (harness: Record<string, unknown>) => ({
    chosen: { preferred_harness: "" },
    harnesses: [
        { id: "claude-code", label: "Claude Code", command: "claude", llm_selectable: true, ...harness },
        { id: "mistral-vibe", label: "Mistral Vibe", command: "vibe" },
    ],
});

describe("RunWith", () => {
    it("shows each agent with its provider's mark", async () => {
        stubFetch({ "/api/prefs": prefs({ llms: ["claude-sonnet-x"] }) });
        const { container } = render(RunWith);
        await screen.findByRole("button", { name: /Agent: Claude Code/ });
        await fireEvent.click(screen.getByRole("button", { name: /Agent:/ }));
        const marks = [...container.querySelectorAll("[role=option] svg")].map((one) =>
            one.getAttribute("data-mark"),
        );
        expect(marks).toEqual(["anthropic", "mistral"]);
    });

    it("lists the models the CLI returned, each with its mark", async () => {
        stubFetch({ "/api/prefs": prefs({ llms: ["claude-sonnet-x", "gemini-9"] }) });
        const { container } = render(RunWith);
        const llm = await screen.findByRole("button", { name: /LLM:/ });
        await fireEvent.click(llm);
        expect(await screen.findByRole("option", { name: "claude-sonnet-x" })).toBeInTheDocument();
        const marks = [...container.querySelectorAll("[role=option] svg")].map((one) =>
            one.getAttribute("data-mark"),
        );
        expect(marks).toEqual(["anthropic", "anthropic", "google"]);
    });

    it("asks the CLI for the model list when it opens, not only the cache", async () => {
        stubFetch({ "/api/prefs": prefs({ llms: ["a-model"] }) });
        render(RunWith);
        await screen.findByRole("button", { name: /LLM:/ });
        const asked = vi.mocked(fetch).mock.calls.map((call) => String(call[0]));
        expect(asked).toContain("/api/prefs?fresh=true");
    });

    it("draws no LLM choice for an agent that lists none, and no paragraph", async () => {
        stubFetch({ "/api/prefs": prefs({ llms: [], llms_note: "This CLI does not list its models" }) });
        const { container } = render(RunWith);
        await screen.findByRole("button", { name: /Agent:/ });
        expect(screen.queryByRole("button", { name: /LLM:/ })).toBeNull();
        expect(container.querySelector("p")).toBeNull();
    });

    it("chooses with the keyboard, as a select does", async () => {
        stubFetch({ "/api/prefs": prefs({ llms: ["a-model", "b-model"] }) });
        render(RunWith);
        const llm = await screen.findByRole("button", { name: /LLM:/ });
        await fireEvent.keyDown(llm, { key: "ArrowDown" });
        const list = await screen.findByRole("listbox", { name: "LLM" });
        await fireEvent.keyDown(list, { key: "ArrowDown" });
        await fireEvent.keyDown(list, { key: "ArrowDown" });
        await fireEvent.keyDown(list, { key: "Enter" });
        expect(screen.queryByRole("listbox")).toBeNull();
    });
});
