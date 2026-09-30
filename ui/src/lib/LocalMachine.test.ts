import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import LocalMachine from "./LocalMachine.svelte";

const status = (over: Record<string, unknown> = {}) => ({
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
    ...over,
});

function serve(first: Record<string, unknown>) {
    const saves: unknown[] = [];
    vi.stubGlobal(
        "fetch",
        vi.fn(async (path: string, init?: RequestInit) => {
            if (String(path).startsWith("/api/prefs")) {
                saves.push(JSON.parse(String(init?.body)));
                return new Response(JSON.stringify({}));
            }
            return new Response(JSON.stringify(first));
        }),
    );
    return saves;
}

describe("Settings, Local machine", () => {
    it("shows the readiness line and the server's own model list", async () => {
        serve(status());
        render(LocalMachine);
        expect(await screen.findByText(/Ready: qwen3-4b on Ollama/)).toBeInTheDocument();
        const options = screen.getAllByRole("option").map((one) => one.textContent);
        expect(options).toEqual(["First one the server lists", "qwen3-4b", "llama3.2"]);
    });

    it("says a running server with no model has none downloaded", async () => {
        const line = "Ollama is running at http://127.0.0.1:11434 but no model is downloaded. Download one in that app, then check again.";
        serve(status({ ready: false, line, reason: line, models: [], model: "" }));
        render(LocalMachine);
        expect(await screen.findByText(/no model is downloaded/)).toBeInTheDocument();
        expect(screen.getAllByRole("option")).toHaveLength(1);
    });

    it("saves the four settings under the server's own key names", async () => {
        const saves = serve(status());
        render(LocalMachine);
        const address = await screen.findByLabelText(/Server address/);
        await fireEvent.input(address, { target: { value: "http://127.0.0.1:1234" } });
        await fireEvent.click(screen.getByRole("button", { name: "Save" }));
        await waitFor(() => expect(saves).toHaveLength(1));
        expect(saves[0]).toEqual({
            local_url: "http://127.0.0.1:1234",
            local_model: "",
            local_search_url: "",
            local_timeout: "",
        });
        expect(await screen.findByText("Saved.")).toBeInTheDocument();
    });

    it("fills the form from what was saved", async () => {
        serve(status({ stored: { local_url: "http://10.0.0.5:8080", local_model: "llama3.2", local_search_url: "", local_timeout: "900" } }));
        render(LocalMachine);
        const address = (await screen.findByLabelText(/Server address/)) as HTMLInputElement;
        await waitFor(() => expect(address.value).toBe("http://10.0.0.5:8080"));
        expect((screen.getByLabelText(/Wait for one answer/) as HTMLInputElement).value).toBe("900");
    });

    it("reports a failed read instead of rendering blank", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
        render(LocalMachine);
        expect(await screen.findByText(/Could not read the local plane/)).toBeInTheDocument();
    });
});
