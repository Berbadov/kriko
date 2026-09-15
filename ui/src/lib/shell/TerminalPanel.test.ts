/* The shell that replaced the Console — and the transport that replaced the
 * WebSocket.
 *
 * Two jsdom gaps stand between this test and a real `@xterm/xterm` mount:
 * no `window.matchMedia` (xterm's `CoreBrowserService` calls it
 * unconditionally) and no `ResizeObserver` (this component's own fit-on-resize
 * effect constructs one). Both are polyfilled below, once, for every test in
 * this file — neither exists to test jsdom, only to let xterm run inside it.
 *
 * The other jsdom gap, `HTMLCanvasElement.getContext` returning `null`, is
 * harmless: xterm's DOM renderer tolerates it and logs a warning, nothing more.
 *
 * The network is replaced with `FakeEventSource` (output) and a `fetch` spy
 * (input) — the two halves the panel now speaks instead of one socket. jsdom
 * has no `EventSource` at all, which is itself worth knowing: the panel's
 * polling fallback is not a legacy-browser courtesy, it is the path a
 * hostile-to-streaming environment actually takes.
 */
import { render, screen, waitFor } from "@testing-library/svelte";
import { fireEvent } from "@testing-library/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TerminalPanel from "./TerminalPanel.svelte";
import { terminalOpen, toggleTerminal } from "./terminal";

class FakeEventSource {
    static instances: FakeEventSource[] = [];

    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onerror: (() => void) | null = null;
    closed = false;

    constructor(public url: string) {
        FakeEventSource.instances.push(this);
    }

    open() {
        this.onopen?.();
    }

    receive(payload: unknown) {
        this.onmessage?.({ data: JSON.stringify(payload) });
    }

    fail() {
        this.onerror?.();
    }

    close() {
        this.closed = true;
    }
}

/** Every request the panel made, newest last. */
let calls: Array<{ url: string; body: unknown }> = [];
/** What `GET /api/terminal/state` answers, for the polling-fallback tests. */
let stateBody: Record<string, unknown> = { data: "", offset: 0, running: true, ended: false, failure: "" };

beforeEach(() => {
    terminalOpen.set(false);
    FakeEventSource.instances = [];
    calls = [];
    stateBody = { data: "", offset: 0, running: true, ended: false, failure: "" };
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
        calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
        if (String(url).includes("/api/terminal/state")) {
            return { ok: true, status: 200, json: async () => stateBody } as Response;
        }
        return { ok: true, status: 200, json: async () => ({ ok: true }) } as Response;
    });
    vi.stubGlobal(
        "matchMedia",
        (query: string) => ({
            matches: false,
            media: query,
            onchange: null,
            addListener() {},
            removeListener() {},
            addEventListener() {},
            removeEventListener() {},
            dispatchEvent() {
                return false;
            },
        }),
    );
    vi.stubGlobal(
        "ResizeObserver",
        class {
            observe() {}
            unobserve() {}
            disconnect() {}
        },
    );
});

afterEach(() => {
    terminalOpen.set(false);
    vi.unstubAllGlobals();
});

const openPanel = async () => {
    render(TerminalPanel);
    toggleTerminal();
    return screen.findByRole("complementary", { name: "Terminal" });
};

describe("TerminalPanel", () => {
    it("renders nothing until the panel has ever been opened", () => {
        render(TerminalPanel);
        expect(screen.queryByRole("complementary", { name: "Terminal" })).toBeNull();
        expect(FakeEventSource.instances).toHaveLength(0);
    });

    it("opens one stream the first time it opens", async () => {
        await openPanel();
        expect(FakeEventSource.instances).toHaveLength(1);
    });

    it("dials a relative URL, so it cannot disagree about where the server is", async () => {
        // B109's last confirmed fact was close code 1006 on a socket whose URL
        // the old `wsUrl()` built out of `location.host` — a second chance to
        // be wrong about the port the sidecar announced. A relative URL
        // resolves against the document that is already loaded from the
        // server, so there is nothing left to disagree with.
        await openPanel();
        const url = FakeEventSource.instances[0].url;
        expect(url.startsWith("/api/terminal/stream")).toBe(true);
        expect(url).not.toContain("://");
    });

    it("stays connected — closing again hides rather than unmounts", async () => {
        const panel = await openPanel();
        toggleTerminal();
        await waitFor(() => expect(panel).toHaveAttribute("hidden"));
        expect(FakeEventSource.instances).toHaveLength(1);

        toggleTerminal();
        await waitFor(() => expect(panel).not.toHaveAttribute("hidden"));
        expect(FakeEventSource.instances).toHaveLength(1);
    });

    it("posts the terminal's geometry when it mounts", async () => {
        await openPanel();
        await waitFor(() =>
            expect(calls.some((call) => call.url === "/api/terminal/resize")).toBe(true),
        );
        const resize = calls.find((call) => call.url === "/api/terminal/resize");
        expect(typeof (resize?.body as { cols: number }).cols).toBe("number");
        expect(typeof (resize?.body as { rows: number }).rows).toBe("number");
    });

    it("posts typed keystrokes", async () => {
        // A real keypress into xterm's DOM renderer does not survive jsdom
        // reliably, but the component reaches the network through exactly one
        // seam — `term.onData(...)` — so capturing the callback it registers
        // there and calling it by hand exercises the same wiring.
        // `onData` is a getter returning the subscribe function, not a plain
        // method, hence the `"get"` access type and the cast.
        const xterm = await import("@xterm/xterm");
        let onData: ((data: string) => void) | undefined;
        const prototype = xterm.Terminal.prototype as unknown as Record<string, unknown>;
        const spy = vi
            .spyOn(prototype, "onData", "get")
            .mockImplementation(() => (callback: (data: string) => void) => {
                onData = callback;
                return { dispose() {} };
            });

        await openPanel();
        expect(onData).toBeDefined();
        onData?.("ls\n");

        await waitFor(() =>
            expect(calls.some((call) => call.url === "/api/terminal/input")).toBe(true),
        );
        const input = calls.find((call) => call.url === "/api/terminal/input");
        expect(input?.body).toEqual({ data: "ls\n" });
        spy.mockRestore();
    });

    it("writes a received data frame into the terminal", async () => {
        const xterm = await import("@xterm/xterm");
        const writeSpy = vi.spyOn(xterm.Terminal.prototype, "write");
        await openPanel();
        FakeEventSource.instances[0].receive({ type: "data", data: "hello", offset: 5 });
        await waitFor(() => expect(writeSpy).toHaveBeenCalledWith("hello"));
        writeSpy.mockRestore();
    });

    it("drops a frame that is not this protocol's JSON, without throwing", async () => {
        await openPanel();
        const stream = FakeEventSource.instances[0];
        expect(() => stream.onmessage?.({ data: "not json" })).not.toThrow();
    });

    it("writes the reason into the terminal on an error frame", async () => {
        const xterm = await import("@xterm/xterm");
        const writeSpy = vi.spyOn(xterm.Terminal.prototype, "write");
        await openPanel();
        FakeEventSource.instances[0].receive({
            type: "error",
            message: "OSError: no such shell",
        });
        await waitFor(() => {
            const written = writeSpy.mock.calls.map((call) => call[0]).join("");
            expect(written).toContain("no such shell");
        });
        writeSpy.mockRestore();
    });

    it("resumes from the last byte it saw rather than restarting blank", async () => {
        // The property the socket could never have: a dropped connection costs
        // latency, not output. The reconnect asks for what came after the
        // offset already on screen.
        await openPanel();
        const first = FakeEventSource.instances[0];
        first.receive({ type: "data", data: "hello", offset: 42 });
        first.fail();
        await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(1));
        expect(FakeEventSource.instances[1].url).toContain("offset=42");
    });

    it("falls back to polling when the stream keeps failing", async () => {
        // Whatever refuses a stream here is the same class of thing that
        // refused the WebSocket in the reader's install. Polling is the floor
        // this panel is not allowed to fall through.
        stateBody = { data: "from the poll", offset: 13, running: true, ended: false, failure: "" };
        const xterm = await import("@xterm/xterm");
        const writeSpy = vi.spyOn(xterm.Terminal.prototype, "write");
        await openPanel();
        for (let attempt = 0; attempt < 4; attempt += 1) {
            const latest = FakeEventSource.instances[FakeEventSource.instances.length - 1];
            latest.fail();
            await waitFor(() =>
                expect(
                    FakeEventSource.instances.length > attempt + 1 ||
                        calls.some((call) => call.url.startsWith("/api/terminal/state")),
                ).toBe(true),
            );
        }
        await waitFor(() => expect(writeSpy).toHaveBeenCalledWith("from the poll"));
        writeSpy.mockRestore();
    });

    it("shows a disconnected state when the shell exits", async () => {
        await openPanel();
        FakeEventSource.instances[0].receive({ type: "ended" });
        await waitFor(() => expect(screen.getByText("disconnected")).toBeInTheDocument());
    });

    it("offers a way back when the shell exits", async () => {
        // `exit` is an ordinary thing to type, and on the 0.8.0 Windows install
        // the shell died on its own at every open. Either way the panel used to
        // say so and offer nothing, for the life of the app.
        await openPanel();
        FakeEventSource.instances[0].receive({ type: "ended" });
        const restart = await screen.findByRole("button", { name: "Restart" });

        await fireEvent.click(restart);
        await waitFor(() =>
            expect(calls.some((call) => call.url === "/api/terminal/restart")).toBe(true),
        );
        // And it re-reads from the start: the transcript went with the old
        // shell, so a cursor still pointing at byte 400 of it waits forever.
        await waitFor(() =>
            expect(
                FakeEventSource.instances[FakeEventSource.instances.length - 1].url,
            ).toContain("offset=0"),
        );
    });

    it("treats a keystroke into a dead shell as asking for a live one", async () => {
        const xterm = await import("@xterm/xterm");
        let onData: ((data: string) => void) | undefined;
        const prototype = xterm.Terminal.prototype as unknown as Record<string, unknown>;
        const spy = vi
            .spyOn(prototype, "onData", "get")
            .mockImplementation(() => (callback: (data: string) => void) => {
                onData = callback;
                return { dispose() {} };
            });

        await openPanel();
        FakeEventSource.instances[0].receive({ type: "ended" });
        await screen.findByRole("button", { name: "Restart" });
        calls.length = 0;

        onData?.("\r");
        await waitFor(() =>
            expect(calls.some((call) => call.url === "/api/terminal/restart")).toBe(true),
        );
        // And not as input, which would go to a pty that is not there.
        expect(calls.some((call) => call.url === "/api/terminal/input")).toBe(false);
        spy.mockRestore();
    });

    it("toggles on Ctrl+` from anywhere in the window", async () => {
        render(TerminalPanel);
        expect(screen.queryByRole("complementary", { name: "Terminal" })).toBeNull();

        await fireEvent.keyDown(window, { key: "`", ctrlKey: true });
        await waitFor(() =>
            expect(screen.getByRole("complementary", { name: "Terminal" })).toBeInTheDocument(),
        );
    });

    it("closes on the panel's own close button", async () => {
        const panel = await openPanel();
        await fireEvent.click(screen.getByRole("button", { name: "Close terminal" }));
        await waitFor(() => expect(panel).toHaveAttribute("hidden"));
    });

    it("actually disappears when closed, not just in the attribute", async () => {
        // The bug this exists for: `hidden`'s `display: none` comes from the
        // user-agent stylesheet and `.terminal-panel { display: flex }` is an
        // author rule, so the author rule won and the panel stayed on screen —
        // fixed, full-height, over the whole app, with a close button that
        // visibly did nothing. Reported from the 0.8.0 install.
        //
        // The test above asserted the *attribute*, which was true the entire
        // time. Only computed style can tell these apart.
        const panel = await openPanel();

        // Canary first. If jsdom is not applying this component's <style> at
        // all, every assertion below passes for the wrong reason and this file
        // silently stops testing the thing it is named after.
        //
        // `display: flex` rather than `position: fixed` since the panel became
        // a column in the shell's grid rather than a sheet over it — the page
        // now reflows around it instead of continuing underneath, which was the
        // other half of the same report.
        expect(getComputedStyle(panel).display).toBe("flex");

        await fireEvent.click(screen.getByRole("button", { name: "Close terminal" }));
        await waitFor(() => expect(getComputedStyle(panel).display).toBe("none"));
    });
});
