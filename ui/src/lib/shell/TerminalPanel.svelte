<script lang="ts">
    import "@xterm/xterm/css/xterm.css";
    import { Terminal } from "@xterm/xterm";
    import { FitAddon } from "@xterm/addon-fit";
    import { terminalOpen, toggleTerminal } from "./terminal";
    import { remedyFor } from "../failure";

    /* A real shell, always one keystroke away.
     *
     * Kriko's harnesses (Claude Code, opencode) sometimes need an interactive
     * `login` no API call can do on their behalf — the CLI itself has to run
     * once with a human watching. Sending the reader out to their OS's own
     * terminal for that is exactly the friction this app exists to remove,
     * so this is a real shell, not the old Console's API-only prompt.
     *
     * **No WebSocket.** This panel spoke one for six releases and the reader
     * never once saw a shell: 0.7.10's banner came back `1006`, the browser's
     * "the opening handshake never finished", while a raw socket against the
     * same frozen sidecar on the same machine got `101` and real PTY bytes.
     * The upgrade is refused above this code, so no amount of fixing inside it
     * could work. It now speaks what the rest of this app already speaks and
     * what demonstrably works in the reader's install — Server-Sent Events for
     * output, `POST` for input — with a plain polling fallback under that.
     *
     * Three things fall out, and all three were impossible on the socket:
     *
     * - **The URL cannot be wrong.** `/api/terminal/stream` is relative, so it
     *   resolves against the document. `wsUrl()` built an absolute one out of
     *   `location.host`, which is a second chance to disagree about where the
     *   server is.
     * - **A dropped connection loses nothing.** The transcript lives on the
     *   session, addressed by byte offset, so a reconnect resumes at `offset`
     *   instead of starting a blank screen.
     * - **It degrades instead of dying.** If SSE fails too, `poll()` reads the
     *   same bytes from `GET /state`. Chunkier, still a shell.
     *
     * One session for the app's whole life, made on first open and never torn
     * down — closing the panel only hides it (`hidden`), and the backend
     * mirrors that: `termpty.SESSION` is one PTY for the process's life.
     */

    /** How often the fallback re-reads the transcript when SSE is unavailable. */
    const POLL_MS = 350;
    /** How long to wait before re-opening a stream that dropped. */
    const RETRY_MS = 700;
    /** Consecutive stream failures before giving up on SSE and polling. */
    const GIVE_UP_AFTER = 3;

    let open = $derived($terminalOpen);
    let everOpened = $state(false);
    let container = $state<HTMLDivElement | undefined>();
    let status = $state<"connecting" | "open" | "closed">("connecting");

    let term: Terminal | undefined;
    let fit: FitAddon | undefined;

    /** Bytes of transcript already written to the screen. The resume cursor. */
    let offset = 0;
    let source: EventSource | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    let polling = false;
    let stopped = false;

    /** Keystrokes waiting on the in-flight POST, so a paste is one request. */
    let pending = "";
    let sending = false;

    function handle(msg: { type?: string; data?: string; message?: string; offset?: number }) {
        if (msg.type === "data" && typeof msg.data === "string") {
            term?.write(msg.data);
            if (typeof msg.offset === "number") offset = msg.offset;
        } else if (msg.type === "error" && typeof msg.message === "string") {
            // The shell failed to start, or died, or something scrolled out
            // of the buffer. Say it in the panel: the one person who can act
            // on it is looking at this, not at app.log.
            term?.write(`\r\n\x1b[31m[terminal] ${msg.message}\x1b[0m\r\n`);
        } else if (msg.type === "ended") {
            status = "closed";
            term?.write("\r\n\x1b[2m[the shell exited]\x1b[0m\r\n");
            stopped = true;
        }
    }

    async function poll() {
        if (stopped) return;
        try {
            const response = await fetch(
                `/api/terminal/state?offset=${offset}`,
                { headers: { accept: "application/json" } },
            );
            if (!response.ok) throw new Error(`${response.status}`);
            const body = await response.json();
            status = "open";
            if (body.dropped) {
                handle({ type: "error", message: "Some output scrolled out of the buffer." });
            }
            if (body.data) handle({ type: "data", data: body.data, offset: body.offset });
            else if (typeof body.offset === "number") offset = body.offset;
            if (body.failure) handle({ type: "error", message: body.failure });
            if (body.ended) return handle({ type: "ended" });
        } catch (cause) {
            // `remedyFor` rather than the exception: the reader of a local app
            // has no terminal to check and nobody to page, so whatever this
            // line says is the whole of the help available to them. (It is
            // also the rule `failure.test.ts` enforces across every view.)
            status = "closed";
            const remedy = remedyFor(cause);
            term?.write(
                `\r\n\x1b[31m[terminal] ${remedy.headline}. ${remedy.next}\x1b[0m\r\n`,
            );
        }
        timer = setTimeout(poll, POLL_MS);
    }

    function connect() {
        if (stopped) return;
        if (typeof EventSource === "undefined" || polling) {
            polling = true;
            void poll();
            return;
        }
        const cols = term?.cols ?? 80;
        const rows = term?.rows ?? 24;
        const stream = new EventSource(
            `/api/terminal/stream?offset=${offset}&cols=${cols}&rows=${rows}`,
        );
        source = stream;
        stream.onopen = () => {
            status = "open";
            failures = 0;
        };
        stream.onmessage = (event) => {
            try {
                handle(JSON.parse(event.data as string));
            } catch {
                // Not this protocol's frame. Dropping it beats dumping raw
                // bytes into a terminal that would try to render them.
            }
        };
        stream.onerror = () => {
            // EventSource retries on its own, but it would re-ask for the
            // offset this URL was built with — reconnecting by hand is how the
            // cursor moves forward across a drop.
            stream.close();
            if (source === stream) source = undefined;
            if (stopped) return;
            status = "closed";
            failures += 1;
            if (failures >= GIVE_UP_AFTER) {
                // Whatever is refusing the stream here refused the WebSocket
                // too, in the reader's install. Polling is the floor this
                // panel is not allowed to fall through.
                polling = true;
                term?.write(
                    "\r\n\x1b[2m[live stream unavailable — falling back to polling]\x1b[0m\r\n",
                );
                void poll();
                return;
            }
            timer = setTimeout(connect, RETRY_MS);
        };
    }

    async function flush() {
        if (sending || !pending) return;
        sending = true;
        const data = pending;
        pending = "";
        try {
            const response = await fetch("/api/terminal/input", {
                method: "POST",
                headers: { "content-type": "application/json" },
                body: JSON.stringify({ data }),
            });
            if (!response.ok) {
                const body = await response.json().catch(() => ({}));
                handle({ type: "error", message: body?.detail ?? `input failed (${response.status})` });
            }
        } catch (cause) {
            const remedy = remedyFor(cause);
            handle({ type: "error", message: `${remedy.headline}. ${remedy.next}` });
        } finally {
            sending = false;
            if (pending) void flush();
        }
    }

    function send(data: string) {
        pending += data;
        void flush();
    }

    function sendResize() {
        if (!term) return;
        void fetch("/api/terminal/resize", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ cols: term.cols, rows: term.rows }),
        }).catch(() => {
            // A geometry that did not land is a cosmetic loss; the next
            // resize or reconnect carries it. Never a reason to shout.
        });
    }

    /* Mounted once, on the first open — never after. `container` only exists
     * once `everOpened` flips `{#if}` on below, so this effect's real job is
     * noticing that moment and doing the one-time setup, not re-running per
     * toggle. */
    $effect(() => {
        if (open) everOpened = true;
    });

    $effect(() => {
        if (!everOpened || !container || term) return;
        const t = new Terminal({ cursorBlink: true, convertEol: false });
        const f = new FitAddon();
        t.loadAddon(f);
        t.open(container);
        f.fit();
        t.onData(send);
        term = t;
        fit = f;
        connect();
        sendResize();

        const observer = new ResizeObserver(() => {
            fit?.fit();
            sendResize();
        });
        observer.observe(container);

        return () => {
            observer.disconnect();
            stopped = true;
            source?.close();
            if (timer) clearTimeout(timer);
        };
    });

    $effect(() => {
        if (open) {
            fit?.fit();
            sendResize();
            term?.focus();
        }
    });

    function onKeydown(event: KeyboardEvent) {
        if ((event.metaKey || event.ctrlKey) && event.key === "`") {
            event.preventDefault();
            toggleTerminal();
        }
    }
</script>

<svelte:window onkeydown={onKeydown} />

{#if everOpened}
    <div class="terminal-panel" hidden={!open} role="complementary" aria-label="Terminal">
        <div class="head">
            <span class="title">Terminal</span>
            {#if status === "closed"}
                <span class="state">disconnected</span>
            {/if}
            <button type="button" class="close" onclick={toggleTerminal} aria-label="Close terminal">
                ×
            </button>
        </div>
        <div class="body" bind:this={container}></div>
    </div>
{/if}

<style>
    .terminal-panel {
        position: fixed;
        inset-block: 0;
        inset-inline-end: 0;
        z-index: 40;
        width: min(38rem, 42vw);
        min-width: 22rem;
        display: flex;
        flex-direction: column;
        background: var(--panel);
        border-inline-start: 1px solid var(--line);
        box-shadow: var(--shadow-2);
    }
    .head {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        padding: var(--s-2) var(--s-3);
        border-block-end: 1px solid var(--line);
        flex: none;
    }
    .head .title {
        font-size: var(--t-sm);
        line-height: var(--lh-sm);
        font-weight: 600;
    }
    .head .state {
        font-size: var(--t-xs);
        line-height: var(--lh-xs);
        color: var(--dim);
    }
    .close {
        margin-inline-start: auto;
        background: transparent;
        border: 0;
        color: inherit;
        font-size: var(--t-lg);
        line-height: 1;
        cursor: pointer;
        padding: 0 var(--s-1);
    }
    .body {
        flex: 1;
        min-height: 0;
        padding: var(--s-2);
    }
    /* xterm sizes its own canvas from the container; without a hard height
       this flex child collapses to zero and FitAddon has nothing to fit. */
    .body :global(.xterm) {
        height: 100%;
    }
</style>
