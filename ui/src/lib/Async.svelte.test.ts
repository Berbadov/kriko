import { render, screen } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import Async from "./Async.svelte";

// A view refreshes by handing Async a new promise. It must not blank to the
// loading sentence while the new one is out: that unmounted every <details>
// and every dropdown built from the last answer, mid-use.

// Reactive like a compiled snippet: the same node, its text following the value.
const children = createRawSnippet((value: () => string) => ({
    render: () => `<p></p>`,
    setup: (node) => {
        $effect(() => {
            node.textContent = value();
        });
    },
}));

function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((r) => (resolve = r));
    return { promise, resolve };
}

describe("Async", () => {
    it("keeps the last answer on screen while the next one loads", async () => {
        const view = render(Async, { promise: Promise.resolve("first answer"), children });
        expect(await screen.findByText("first answer")).toBeInTheDocument();

        const next = deferred<string>();
        await view.rerender({ promise: next.promise, children });
        expect(screen.getByText("first answer")).toBeInTheDocument();
        expect(screen.queryByText("Loading…")).toBeNull();

        next.resolve("second answer");
        expect(await screen.findByText("second answer")).toBeInTheDocument();
    });

    it("drops an answer to a promise that has since been replaced", async () => {
        const slow = deferred<string>();
        const view = render(Async, { promise: slow.promise, children });
        expect(screen.getByText("Loading…")).toBeInTheDocument();

        await view.rerender({ promise: Promise.resolve("newer"), children });
        expect(await screen.findByText("newer")).toBeInTheDocument();

        slow.resolve("older");
        await new Promise((r) => setTimeout(r, 0));
        expect(screen.queryByText("older")).toBeNull();
        expect(screen.getByText("newer")).toBeInTheDocument();
    });

    it("says why it failed, and a retry goes back to the loading sentence", async () => {
        const view = render(Async, { promise: Promise.reject(new Error("boom")), children });
        expect(await screen.findByRole("alert")).toBeInTheDocument();

        await view.rerender({ promise: new Promise(() => {}), children });
        expect(screen.getByText("Loading…")).toBeInTheDocument();
    });
});
