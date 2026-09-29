import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import CloseNotice from "./CloseNotice.svelte";

/* B152: "we need dont show me again button and more stylised warning box;
 * and please no OS warning sound." The shell asks this component through
 * `window.__krikoClose()`; every answer goes back through `/api/window`. */

type Posted = { action: string; remember: boolean };

function stub(closeNotice: boolean) {
    const posted: Posted[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith("/api/window") && (!init || !init.method || init.method === "GET"))
            return new Response(JSON.stringify({ shell: true, close_notice: closeNotice }));
        if (url.endsWith("/api/window")) {
            posted.push(JSON.parse(String(init!.body)));
            return new Response(JSON.stringify({ action: "x", shell: true }));
        }
        return new Response("{}", { status: 404 });
    }));
    return posted;
}

const ask = () => (window as unknown as { __krikoClose: () => void }).__krikoClose();

afterEach(() => vi.unstubAllGlobals());

describe("the close notice", () => {
    it("is drawn by the app, and tells the shell it is up", async () => {
        const posted = stub(true);
        render(CloseNotice);
        ask();
        expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
        expect(screen.getByText("Kriko keeps running")).toBeInTheDocument();
        expect(posted).toEqual([{ action: "ack", remember: false }]);
    });

    it("don't show again is remembered with Keep running", async () => {
        const posted = stub(true);
        render(CloseNotice);
        ask();
        await fireEvent.click(await screen.findByLabelText("Don't show this again"));
        await fireEvent.click(screen.getByRole("button", { name: "Keep running" }));
        await vi.waitFor(() =>
            expect(posted.at(-1)).toEqual({ action: "hide", remember: true }));
        await vi.waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    });

    it("Quit asks the shell to quit and remembers nothing", async () => {
        const posted = stub(true);
        render(CloseNotice);
        ask();
        await fireEvent.click(await screen.findByLabelText("Don't show this again"));
        await fireEvent.click(screen.getByRole("button", { name: "Quit Kriko" }));
        await vi.waitFor(() =>
            expect(posted.at(-1)).toEqual({ action: "quit", remember: false }));
    });

    it("once dismissed for good, a close hides at once with no box", async () => {
        const posted = stub(false);
        render(CloseNotice);
        ask();
        await vi.waitFor(() => expect(posted).toEqual([{ action: "hide", remember: false }]));
        expect(screen.queryByRole("alertdialog")).toBeNull();
    });
});
