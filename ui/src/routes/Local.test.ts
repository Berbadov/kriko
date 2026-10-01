import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import Local from "./Local.svelte";

const READY = {
    "/api/local-plane": {
        ready: true,
        reason: "",
        line: "Ready: qwen3-4b on Ollama at http://127.0.0.1:11434; search through Exa's free hosted search.",
        url: "http://127.0.0.1:11434",
        name: "Ollama",
        model: "qwen3-4b",
        models: ["qwen3-4b", "llama3.2"],
        servers: [],
        search_kind: "exa",
        search_label: "Exa's free hosted search",
        timeout: 300,
        stored: { local_url: "", local_model: "", local_search_url: "", local_timeout: "" },
    },
};

describe("Local LLM page", () => {
    it("is a page of its own for the local plane, not a section of Settings", async () => {
        stubFetch(READY);
        render(Local);
        expect(await screen.findByRole("heading", { name: /Local LLM/ })).toBeInTheDocument();
        expect(await screen.findByText(/Ready: qwen3-4b on Ollama/)).toBeInTheDocument();
        expect(await screen.findByLabelText(/Server address/)).toBeInTheDocument();
    });
});
