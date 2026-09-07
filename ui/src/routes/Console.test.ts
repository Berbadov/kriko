import { render, screen, waitFor } from "@testing-library/svelte";
import { fireEvent } from "@testing-library/dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Console from "./Console.svelte";
import { stubFetch } from "../lib/stub-fetch";

/** Type a line and press Enter, the way the only input here is used. */
async function run(line: string) {
    const field = screen.getByRole("textbox", { name: "Console command" });
    await fireEvent.input(field, { target: { value: line } });
    await fireEvent.keyDown(field, { key: "Enter" });
}

describe("Console", () => {
    beforeEach(() => {
        vi.restoreAllMocks();
        localStorage.clear();
    });

    it("says what it is and is not, before anything is typed", () => {
        render(Console, {});
        // "no shell" is the load-bearing half of the banner: this process
        // listens on a fixed port a browser extension talks to, so a
        // command-execution endpoint here would be a remote shell for any
        // page that guessed the port. Every verb is an API call instead.
        // Twice, in fact — the screen's intro and the transcript banner. Both
        // are deliberate: the reader who scrolled past the intro still meets
        // the claim at the top of the log.
        expect(screen.getAllByText(/no shell/).length).toBeGreaterThan(0);
    });

    it("echoes what was typed, so the log reads as a transcript", async () => {
        render(Console, {});
        await run("help");
        await waitFor(() => expect(screen.getByText(/❯ help/)).toBeInTheDocument());
    });

    it("suggests the nearest verb rather than only refusing", async () => {
        render(Console, {});
        await run("hel");
        await waitFor(() =>
            expect(screen.getByText(/did you mean help/)).toBeInTheDocument(),
        );
    });

    it("names an unknown verb and points at the one that lists them", async () => {
        render(Console, {});
        await run("zzz");
        await waitFor(() =>
            expect(screen.getByText(/no verb zzz/)).toBeInTheDocument(),
        );
    });

    it("prints the API's own reason for a failure, not a stringified object", async () => {
        // A console that printed "[object Object]" would be worse than the
        // screen it exists to be faster than.
        stubFetch({ "/api/status": { status: 503, body: '{"detail":"store is locked"}' } });
        render(Console, {});
        await run("status");
        await waitFor(() =>
            expect(screen.getByText(/store is locked/)).toBeInTheDocument(),
        );
    });

    it("recalls the previous line on ArrowUp", async () => {
        render(Console, {});
        await run("help");
        const field = screen.getByRole("textbox", {
            name: "Console command",
        }) as HTMLInputElement;
        await fireEvent.keyDown(field, { key: "ArrowUp" });
        expect(field.value).toBe("help");
    });

    it("clears back to the banner, keeping what the console is", async () => {
        render(Console, {});
        await run("help");
        await run("clear");
        await waitFor(() => expect(screen.queryByText(/❯ help/)).toBeNull());
        expect(screen.getAllByText(/no shell/).length).toBeGreaterThan(0);
    });
});
