import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Keys from "./Keys.svelte";
import { stubFetch, stubFetchFailing } from "./stub-fetch";

/** The fixture, chosen so a leak is unmistakable in a diff or a snapshot. */
const SECRET = "sk-test-DO-NOT-LEAK-0123456789abcdef4f2a";

const both = (present: boolean) => ({
    "/api/keys": {
        providers: [
            {
                id: "exa",
                label: "Exa",
                env: "EXA_API_KEY",
                purpose: "Receives your search queries — never a page you visited.",
                present,
                hint: present ? "…4f2a" : "",
                source: present ? "file" : "",
            },
            {
                id: "openai",
                label: "OpenAI",
                env: "OPENAI_API_KEY",
                purpose: "Receives the text of the pages research fetched.",
                present: false,
                hint: "",
                source: "",
            },
        ],
        ready: false,
        path: "/home/somebody/.kriko/env",
    },
});

describe("the research keys section", () => {
    it("asks for a key without ever showing one", async () => {
        stubFetch(both(true));
        const { container } = render(Keys);
        expect(await screen.findByText("Exa")).toBeTruthy();

        // Present, and identifiable by its tail — which is the whole of what
        // a reader needs to answer "is this the key I think it is".
        expect(await screen.findByText("set …4f2a")).toBeTruthy();
        expect(container.textContent).not.toContain(SECRET);

        // A password field, and empty: a stored key is never round-tripped
        // into an input, because a bound input is a key in the DOM.
        const inputs = container.querySelectorAll("input");
        expect(inputs.length).toBeGreaterThan(0);
        inputs.forEach((input) => {
            expect(input.getAttribute("type")).toBe("password");
            expect((input as HTMLInputElement).value).toBe("");
        });
    });

    it("prints what each provider receives, beside the box asking for it", async () => {
        stubFetch(both(false));
        render(Keys);
        // The data-flow sentence comes from the server so there is one copy of
        // it; what this asserts is that the screen actually shows it, at the
        // point of the decision rather than in a privacy page.
        expect(
            await screen.findByText(/Receives your search queries/),
        ).toBeTruthy();
        expect(
            await screen.findByText(/Receives the text of the pages/),
        ).toBeTruthy();
    });

    it("says both are needed, because the plane searches and reads", async () => {
        stubFetch(both(true));
        render(Keys);
        expect(await screen.findByText(/Both are needed/)).toBeTruthy();
    });

    it("clears the field after saving rather than leaving the key in the DOM", async () => {
        stubFetch(both(false));
        const { container } = render(Keys);
        await screen.findByText("Exa");

        const input = container.querySelector("input") as HTMLInputElement;
        input.value = SECRET;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        await Promise.resolve();

        const form = container.querySelector("form") as HTMLFormElement;
        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        // Two microtask turns: the PUT, then the re-read it triggers.
        await new Promise((resolve) => setTimeout(resolve, 0));
        await new Promise((resolve) => setTimeout(resolve, 0));

        expect(input.value).toBe("");
        expect(container.textContent).not.toContain(SECRET);
    });

    it("never sends a key anywhere but this app's own keys endpoint", async () => {
        stubFetch(both(false));
        const { container } = render(Keys);
        await screen.findByText("Exa");

        const input = container.querySelector("input") as HTMLInputElement;
        input.value = SECRET;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        const form = container.querySelector("form") as HTMLFormElement;
        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        await new Promise((resolve) => setTimeout(resolve, 0));

        // Every call that carried the fixture went to /api/keys, and to
        // nothing else. The providers are reached from the server, and a
        // frontend that talked to api.exa.ai directly would put the key in a
        // page's network log and in every extension the browser has.
        const calls = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
        const leaked = calls.filter((call) => JSON.stringify(call).includes(SECRET));
        expect(leaked.length).toBe(1);
        expect(String(leaked[0][0])).toBe("/api/keys");
    });

    it("explains an environment key rather than offering a delete that cannot work", async () => {
        const data = both(true);
        data["/api/keys"].providers[0].source = "environment";
        stubFetch(data);
        render(Keys);
        expect(await screen.findByText(/comes from the environment/)).toBeTruthy();
        // No form for that provider: this app did not set it and cannot unset
        // it, and a button that silently fails is worse than an explanation.
        expect(screen.queryByText("Forget it")).toBeNull();
    });

    it("surfaces a failure instead of rendering an empty section", async () => {
        stubFetchFailing();
        render(Keys);
        expect(await screen.findByText(/Research keys/)).toBeTruthy();
        expect(await screen.findByRole("button", { name: /again|retry/i })).toBeTruthy();
    });
});
