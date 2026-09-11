<script lang="ts">
    import "@xterm/xterm/css/xterm.css";
    import { Terminal } from "@xterm/xterm";
    import { FitAddon } from "@xterm/addon-fit";
    import { terminalOpen, toggleTerminal } from "./terminal";

    /* A real shell, always one keystroke away.
     *
     * Kriko's harnesses (Claude Code, opencode) sometimes need an interactive
     * `login` no API call can do on their behalf — the CLI itself has to run
     * once with a human watching. Sending the reader out to their OS's own
     * terminal for that is exactly the friction this app exists to remove,
     * so this is a real shell, not the old Console's API-only prompt.
     *
     * One connection for the app's whole session, made on first open and
     * never torn down after — closing the panel only hides it (`hidden`,
     * the same choice Agents made for the old Console, and for the same
     * reason: an unmounted terminal is a cleared one, and a reader who
     * flips to another screen mid-command expects to come back to it).
     * The backend mirrors this on its own side: `termpty.SESSION` is one
     * PTY for the process's life, not one per connection.
     */

    let open = $derived($terminalOpen);
    let everOpened = $state(false);
    let container = $state<HTMLDivElement | undefined>();
    let status = $state<"connecting" | "open" | "closed">("connecting");

    let term: Terminal | undefined;
    let fit: FitAddon | undefined;
    let socket: WebSocket | undefined;

    function wsUrl(): string {
        const scheme = location.protocol === "https:" ? "wss:" : "ws:";
        return `${scheme}//${location.host}/api/terminal/ws`;
    }

    function connect() {
        const ws = new WebSocket(wsUrl());
        socket = ws;
        ws.onopen = () => {
            status = "open";
            sendResize();
        };
        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data as string) as {
                    type: string;
                    data?: string;
                };
                if (msg.type === "data" && typeof msg.data === "string") {
                    term?.write(msg.data);
                }
            } catch {
                // A frame that is not JSON is not this protocol's; drop it
                // rather than dump raw bytes into a terminal reading it.
            }
        };
        ws.onclose = () => {
            status = "closed";
            term?.write("\r\n\x1b[2m[disconnected]\x1b[0m\r\n");
        };
        ws.onerror = () => {
            status = "closed";
        };
    }

    function sendResize() {
        if (!term || !socket || socket.readyState !== WebSocket.OPEN) return;
        socket.send(
            JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }),
        );
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
        t.onData((data) => {
            if (socket?.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: "data", data }));
            }
        });
        term = t;
        fit = f;
        connect();

        const observer = new ResizeObserver(() => {
            fit?.fit();
            sendResize();
        });
        observer.observe(container);

        return () => observer.disconnect();
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
