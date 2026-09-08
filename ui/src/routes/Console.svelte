<script lang="ts">
    import { remedyFor } from "../lib/failure";
    import { byName, complete, tokenize, VERBS, type Line } from "../lib/console/commands";

    /* A terminal, inside the app, for the half of Kriko that was terminal-only.
     *
     * G6's delivery constraint says every operation must be operable from the
     * dashboard. The screens got there one at a time, and each one answers a
     * *question* — but some of what an author does is not a question, it is a
     * sequence: enable a pack, list its gaps, brief one, run research, read
     * the log. Five screens and eleven clicks, or five lines here.
     *
     * It runs no shell. See `lib/console/commands.ts` for why that is a design
     * decision rather than an omission: every verb is a call against this
     * app's own HTTP API, dispatched from the browser, so the console holds
     * exactly the authority this window already has and adds no server
     * surface whatever.
     */

    const BANNER: Line[] = [
        { kind: "note", text: "Kriko console — no shell, only this app's own API." },
        { kind: "note", text: "`help` lists the verbs. Tab completes, ↑ recalls." },
    ];

    let lines = $state<Line[]>([...BANNER]);
    let input = $state("");
    let busy = $state(false);
    let scroller: HTMLDivElement | undefined = $state();
    let field: HTMLInputElement | undefined = $state();

    // History outlives the page but not the machine: it is a convenience for
    // one reader on one browser, so localStorage is the right place and a
    // failure to read it is not worth a message.
    const HISTORY_KEY = "kriko.console.history";
    let history = $state<string[]>(read());
    let cursor = $state(-1);

    function read(): string[] {
        try {
            const raw = localStorage.getItem(HISTORY_KEY);
            return raw ? (JSON.parse(raw) as string[]).slice(-200) : [];
        } catch {
            return [];
        }
    }

    function remember(line: string) {
        // No consecutive duplicates: pressing ↑ through six identical
        // `status` calls is history that has stopped being useful.
        if (history[history.length - 1] === line) return;
        history = [...history, line].slice(-200);
        try {
            localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
        } catch {
            /* a browser with storage denied still gets a working console */
        }
    }

    function emit(line: Line) {
        lines = [...lines, line];
        // After paint, so the element being scrolled to exists. Bounded to the
        // last 500 lines: a long research run can print hundreds, and a
        // terminal that grows without limit eventually stops repainting.
        if (lines.length > 500) lines = lines.slice(-500);
        queueMicrotask(() => {
            if (scroller) scroller.scrollTop = scroller.scrollHeight;
        });
    }

    async function submit() {
        const raw = input.trim();
        input = "";
        cursor = -1;
        if (!raw) return;
        emit({ kind: "in", text: raw });
        remember(raw);

        if (raw === "clear") {
            lines = [...BANNER];
            return;
        }

        const [verb, ...args] = tokenize(raw);
        const command = byName(verb);
        if (!command) {
            const guess = complete(verb).options;
            emit({
                kind: "err",
                text: guess.length
                    ? `no verb ${verb} — did you mean ${guess.join(", ")}?`
                    : `no verb ${verb}. \`help\` lists them.`,
            });
            return;
        }

        busy = true;
        try {
            await command.run(args, emit);
        } catch (cause) {
            // The API's own reason, which `ApiError` has already extracted
            // from the response body. A console that printed "[object Object]"
            // would be worse than the screen it is meant to be faster than.
            //
            // `technical` rather than `headline`: this is the one surface in
            // the app whose reader *asked for* the exception — a console that
            // answered "that is a bug in Kriko" would be hiding the thing they
            // opened it to see. It goes through `remedyFor` anyway so that
            // "the exception as text" has one definition (B72).
            emit({ kind: "err", text: remedyFor(cause).technical });
        } finally {
            busy = false;
            queueMicrotask(() => field?.focus());
        }
    }

    function onKey(event: KeyboardEvent) {
        if (event.key === "Enter") {
            event.preventDefault();
            void submit();
            return;
        }
        if (event.key === "Tab") {
            event.preventDefault();
            // Only the verb completes. Arguments are ids and file paths — the
            // console has no business guessing at either.
            if (input.includes(" ")) return;
            const { value, options } = complete(input);
            if (options.length > 1 && value === input) {
                emit({ kind: "note", text: options.join("  ") });
            }
            input = value;
            return;
        }
        if (event.key === "ArrowUp") {
            event.preventDefault();
            if (!history.length) return;
            cursor = cursor < 0 ? history.length - 1 : Math.max(0, cursor - 1);
            input = history[cursor];
            return;
        }
        if (event.key === "ArrowDown") {
            event.preventDefault();
            if (cursor < 0) return;
            cursor += 1;
            if (cursor >= history.length) {
                cursor = -1;
                input = "";
            } else {
                input = history[cursor];
            }
            return;
        }
        // Ctrl+L, as everywhere else a terminal has ever existed.
        if (event.key === "l" && event.ctrlKey) {
            event.preventDefault();
            lines = [...BANNER];
        }
    }
</script>

<h2>Console</h2>
<p class="meta">
    Every verb is one call against this app's own API — there is no shell here and no
    endpoint that runs a command you name, because this process also answers a browser
    extension on a fixed port. `help` lists what it understands.
</p>

<!-- The output is a log, so it is a log element: a screen reader following a
     job's progress should hear the lines arrive rather than have to go and
     look for them. -->
<div class="term" bind:this={scroller} role="log" aria-live="polite" aria-label="Console output">
    {#each lines as line, index (index)}
        <pre class="line {line.kind}">{line.kind === "in" ? `❯ ${line.text}` : line.text}</pre>
    {/each}
    {#if busy}
        <pre class="line note"><span class="live-dot"></span> working…</pre>
    {/if}
</div>

<div class="prompt">
    <span class="sigil" aria-hidden="true">❯</span>
    <!-- svelte-ignore a11y_autofocus -->
    <input
        bind:this={field}
        bind:value={input}
        onkeydown={onKey}
        autofocus
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        aria-label="Console command"
        placeholder={VERBS.slice(0, 4).join("  ")}
    />
</div>

<style>
    .term {
        /* Tall, and it is the page: a console that shows six lines is a
         * search box with extra steps. */
        height: min(58vh, 34rem);
        overflow-y: auto;
        padding: var(--s-3);
        background: var(--panel-2);
        border: 1px solid var(--line);
        border-radius: var(--radius) var(--radius) 0 0;
        font-family: var(--font-mono);
        font-size: var(--t-sm);
        line-height: var(--lh-sm);
    }
    .line {
        margin: 0;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        font: inherit;
    }
    /* What the reader typed, kept legible as the thing they typed: an echoed
     * command that looks like output makes a long session unreadable. */
    .line.in {
        color: var(--accent);
        margin-top: var(--s-2);
    }
    .line.note {
        color: var(--dim);
    }
    .line.err {
        color: var(--high);
    }
    .prompt {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        padding: var(--s-2) var(--s-3);
        border: 1px solid var(--line);
        border-top: 0;
        border-radius: 0 0 var(--radius) var(--radius);
        background: var(--panel);
    }
    .sigil {
        color: var(--accent);
        font-family: var(--font-mono);
    }
    .prompt input {
        flex: 1;
        border: 0;
        background: none;
        color: var(--text);
        font-family: var(--font-mono);
        font-size: var(--t-sm);
        padding: 0;
    }
    .prompt input:focus {
        outline: none;
    }
    /* The focus ring goes on the whole prompt bar rather than the bare input:
     * the input has no border of its own, so a ring on it would float. */
    .prompt:focus-within {
        outline: var(--ring) solid var(--accent);
        outline-offset: -1px;
    }
</style>
