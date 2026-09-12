/* The shell that replaced the Console.
 *
 * Two jsdom gaps stood between this test and a real `@xterm/xterm` mount:
 * no `window.matchMedia` (xterm's `CoreBrowserService` calls it
 * unconditionally) and no `ResizeObserver` (this component's own fit-on-resize
 * effect constructs one). Both are polyfilled below, once, for every test in
 * this file — neither exists to test jsdom, only to let xterm run inside it.
 *
 * The other jsdom gap, `HTMLCanvasElement.getContext` returning `null`, is
 * harmless: xterm's DOM renderer tolerates it and logs a warning, nothing
 * more, so it needs no polyfill here.
 *
 * The real network is replaced with `FakeWebSocket`, a minimal stand-in
 * whose `onopen`/`onmessage`/`onclose` are triggered by hand — this
 * component owns no server, so nothing here should attempt a real socket.
 */
import { render, screen, waitFor } from "@testing-library/svelte";
import { fireEvent } from "@testing-library/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TerminalPanel from "./TerminalPanel.svelte";
import { terminalOpen, toggleTerminal } from "./terminal";

class FakeWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSING = 2;
    static readonly CLOSED = 3;
    static instances: FakeWebSocket[] = [];

    readyState = FakeWebSocket.CONNECTING;
    sent: string[] = [];
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onerror: (() => void) | null = null;

    constructor(public url: string) {
        FakeWebSocket.instances.push(this);
    }

    send(data: string) {
        this.sent.push(data);
    }

    open() {
        this.readyState = FakeWebSocket.OPEN;
        this.onopen?.();
    }

    receive(payload: unknown) {
        this.onmessage?.({ data: JSON.stringify(payload) });
    }

    onclose: ((event: { code?: number; reason?: string }) => void) | null = null;

    close(code?: number, reason?: string) {
        this.readyState = FakeWebSocket.CLOSED;
        this.onclose?.({ code, reason });
    }
}

beforeEach(() => {
    terminalOpen.set(false);
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
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

describe("TerminalPanel", () => {
    it("renders nothing until the panel has ever been opened", () => {
        render(TerminalPanel);
        expect(screen.queryByRole("complementary", { name: "Terminal" })).toBeNull();
        expect(FakeWebSocket.instances).toHaveLength(0);
    });

    it("mounts and connects the first time it opens", async () => {
        render(TerminalPanel);
        toggleTerminal();
        await waitFor(() =>
            expect(screen.getByRole("complementary", { name: "Terminal" })).toBeInTheDocument(),
        );
        expect(FakeWebSocket.instances).toHaveLength(1);
        expect(FakeWebSocket.instances[0].url).toBe("ws://localhost:3000/api/terminal/ws");
    });

    it("stays connected — closing again hides rather than unmounts", async () => {
        render(TerminalPanel);
        toggleTerminal();
        const panel = await screen.findByRole("complementary", { name: "Terminal" });
        toggleTerminal();
        await waitFor(() => expect(panel).toHaveAttribute("hidden"));
        expect(FakeWebSocket.instances).toHaveLength(1);

        toggleTerminal();
        await waitFor(() => expect(panel).not.toHaveAttribute("hidden"));
        // Still the one connection from the first open, not a second one.
        expect(FakeWebSocket.instances).toHaveLength(1);
    });

    it("sends a resize frame once the socket is open", async () => {
        render(TerminalPanel);
        toggleTerminal();
        await screen.findByRole("complementary", { name: "Terminal" });
        const ws = FakeWebSocket.instances[0];
        expect(ws.sent).toHaveLength(0);

        ws.open();
        await waitFor(() => expect(ws.sent).toHaveLength(1));
        const frame = JSON.parse(ws.sent[0]);
        expect(frame).toMatchObject({ type: "resize" });
        expect(typeof frame.cols).toBe("number");
        expect(typeof frame.rows).toBe("number");
    });

    it("sends typed keystrokes as data frames", async () => {
        // A real keypress into xterm's DOM renderer does not survive jsdom
        // reliably, but the component reaches the network through exactly
        // one seam — `term.onData(...)` — so capturing the callback it
        // registers there and calling it by hand exercises the same wiring
        // a keystroke would.
        // `onData` is a getter returning the subscribe function, not a plain
        // method — `vi.spyOn` needs the `"get"` access type to reach it, and
        // xterm's own public typings (a plain method signature) do not admit
        // that at the type level even though the compiled class does at
        // runtime, hence the cast.
        const xterm = await import("@xterm/xterm");
        let onData: ((data: string) => void) | undefined;
        const prototype = xterm.Terminal.prototype as unknown as Record<string, unknown>;
        const onDataSpy = vi
            .spyOn(prototype, "onData", "get")
            .mockImplementation(() => (callback: (data: string) => void) => {
                onData = callback;
                return { dispose() {} };
            });

        render(TerminalPanel);
        toggleTerminal();
        await screen.findByRole("complementary", { name: "Terminal" });
        const ws = FakeWebSocket.instances[0];
        ws.open();
        await waitFor(() => expect(ws.sent).toHaveLength(1));
        ws.sent.length = 0;

        expect(onData).toBeDefined();
        onData?.("ls\n");
        expect(ws.sent).toEqual([JSON.stringify({ type: "data", data: "ls\n" })]);

        onDataSpy.mockRestore();
    });

    it("writes a received data frame into the terminal", async () => {
        const xterm = await import("@xterm/xterm");
        const writeSpy = vi.spyOn(xterm.Terminal.prototype, "write");
        render(TerminalPanel);
        toggleTerminal();
        await screen.findByRole("complementary", { name: "Terminal" });
        const ws = FakeWebSocket.instances[0];
        ws.open();

        ws.receive({ type: "data", data: "hello" });
        await waitFor(() => expect(writeSpy).toHaveBeenCalledWith("hello"));
        writeSpy.mockRestore();
    });

    it("drops a frame that is not this protocol's JSON, without throwing", async () => {
        render(TerminalPanel);
        toggleTerminal();
        await screen.findByRole("complementary", { name: "Terminal" });
        const ws = FakeWebSocket.instances[0];
        ws.open();
        expect(() => ws.onmessage?.({ data: "not json" })).not.toThrow();
    });

    it("shows a disconnected state when the socket closes", async () => {
        render(TerminalPanel);
        toggleTerminal();
        await screen.findByRole("complementary", { name: "Terminal" });
        const ws = FakeWebSocket.instances[0];
        ws.open();

        ws.close();
        await waitFor(() => expect(screen.getByText("disconnected")).toBeInTheDocument());
    });

    it("writes the close code into the disconnect banner when the socket never sent an error frame", async () => {
        // B109, fourth gap: 0.7.7-0.7.9 each closed a path that could reach
        // the bare "[disconnected]" line with no error frame, and the
        // reader still saw exactly that after all three shipped -- meaning
        // the socket never finished connecting in the first place. Code
        // 1006 ("abnormal closure") is what the browser reports for exactly
        // that case, with no server-sent frame required, so it belongs in
        // the banner every time, not just when a frame told us why.
        const xterm = await import("@xterm/xterm");
        const writeSpy = vi.spyOn(xterm.Terminal.prototype, "write");
        render(TerminalPanel);
        toggleTerminal();
        await screen.findByRole("complementary", { name: "Terminal" });
        const ws = FakeWebSocket.instances[0];

        ws.close(1006, "");
        await waitFor(() => expect(screen.getByText("disconnected")).toBeInTheDocument());

        const written = writeSpy.mock.calls.map((call) => call[0]).join("");
        expect(written).toContain("1006");
        // The reader's 0.7.10 report came back exactly 1006 -- confirmed
        // abnormal closure -- but that alone doesn't say whether the socket
        // even dialed the right place. `ws.url` is the one fact 1006 can't
        // carry on its own.
        expect(written).toContain(ws.url);
        writeSpy.mockRestore();
    });

    it("writes the reason into the terminal and skips the bare disconnect banner on an error frame", async () => {
        // B109: a `TermSession.start()` failure now arrives as an
        // `{type: "error"}` frame right before the close — the reader should
        // see *why*, not the old undifferentiated "[disconnected]".
        const xterm = await import("@xterm/xterm");
        const writeSpy = vi.spyOn(xterm.Terminal.prototype, "write");
        render(TerminalPanel);
        toggleTerminal();
        await screen.findByRole("complementary", { name: "Terminal" });
        const ws = FakeWebSocket.instances[0];
        ws.open();

        ws.receive({ type: "error", message: "OSError: no such shell" });
        ws.close();
        await waitFor(() => expect(screen.getByText("disconnected")).toBeInTheDocument());

        const written = writeSpy.mock.calls.map((call) => call[0]).join("");
        expect(written).toContain("no such shell");
        expect(written).not.toContain("[disconnected]");
        writeSpy.mockRestore();
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
        render(TerminalPanel);
        toggleTerminal();
        const panel = await screen.findByRole("complementary", { name: "Terminal" });

        await fireEvent.click(screen.getByRole("button", { name: "Close terminal" }));
        await waitFor(() => expect(panel).toHaveAttribute("hidden"));
    });
});
