<script lang="ts">
    import AgentPrefs from "../lib/Agents.prefs.svelte";
    import Icon from "../lib/Icon.svelte";
    import Failure from "../lib/Failure.svelte";
    import { remedyFor } from "../lib/failure";
    import { api } from "../lib/api";
    import { copyText } from "../lib/clipboard";
    import type { AgentConfig, AgentVerify, VerifyStep } from "../lib/types";

    // B164: this screen is the agents and nothing else. The harness list, the
    // top-N agenda, the build-knowledge planes, the schedule and the skill text
    // used to sit under it. Connecting an agent is an action on its own row in
    // "Your agents" now; research starts per product, from Run, Browse or the
    // extension.
    //
    // B177: the two cards under the rows say it with states, not sentences.
    // Verify lists the handshake's own steps with a result each and keeps the
    // raw output behind "Show log"; connecting another harness is three steps
    // with a state icon each, where it used to be a paragraph and pasted JSON.
    let data = $state<AgentConfig | null>(null);
    let loadError = $state<unknown>(null);
    let showManual = $state(false);
    let copied = $state<"" | "yes" | "blocked">("");

    async function refresh() {
        try {
            data = await api.agentConfig();
            loadError = null;
        } catch (cause) {
            loadError = cause;
        }
    }
    refresh();

    const snippet = $derived(data ? JSON.stringify(data.mcp_json, null, 2) : "");

    async function copy() {
        copied = (await copyText(snippet)) ? "yes" : "blocked";
    }

    // Written and working are different failures with different fixes: a
    // config can be perfect and the command still unable to start, and the
    // only sign of that is an agent that quietly returns nothing.
    let verifying = $state(false);
    let verdict = $state<AgentVerify | null>(null);
    let showLog = $state(false);

    async function verify() {
        verifying = true;
        verdict = null;
        showLog = false;
        try {
            verdict = await api.verifyAgent();
        } catch (cause) {
            // The request itself failed, so no step ran: the log is the
            // technical detail and the headline is the failed verdict.
            const detail = remedyFor(cause).technical;
            verdict = { ok: false, detail, log: detail, steps: [] };
        } finally {
            verifying = false;
        }
    }

    // The words live here, the ids in the engine (`HANDSHAKE_STEPS`).
    const STEP_WORDS: Record<string, string> = {
        start: "Start the command",
        initialize: "Initialize",
        tools: "List the tools",
    };
    const STATE_WORDS = { ok: "Passed", failed: "Failed", skipped: "Not run", todo: "", wait: "Running" };

    type Shown = { id: string; label: string; state: keyof typeof STATE_WORDS };
    const verifySteps = $derived<Shown[]>(
        (verdict?.steps?.length
            ? verdict.steps
            : verdict
              ? [{ id: "start", state: "failed" } as VerifyStep]
              : Object.keys(STEP_WORDS).map((id) => ({ id, state: "todo" }))
        ).map((step) => ({
            id: step.id,
            label: STEP_WORDS[step.id] ?? step.id,
            state: verifying ? "wait" : (step.state as keyof typeof STATE_WORDS),
        })),
    );

    // Connecting a harness by hand. Only the first and last steps have a state
    // the app can know: pasting into another program's file is the reader's,
    // so that step carries no result and is never shown as done.
    const copyState = $derived<keyof typeof STATE_WORDS>(
        copied === "yes" ? "ok" : copied === "blocked" ? "failed" : "todo",
    );
    const verifyState = $derived<keyof typeof STATE_WORDS>(
        verifying ? "wait" : verdict ? (verdict.ok ? "ok" : "failed") : "todo",
    );
</script>

{#snippet mark(state: keyof typeof STATE_WORDS)}
    <span class="stateicon" data-state={state}>
        {#if state === "ok"}<Icon name="ok" size={16} />
        {:else if state === "failed"}<Icon name="warn" size={16} />
        {:else if state === "wait"}<Icon name="refresh" size={16} />
        {:else}<span class="ring" aria-hidden="true"></span>{/if}
    </span>
{/snippet}

<h2><Icon name="connect" size={22} /> Agents</h2>

{#if loadError}
    <Failure error={loadError} retry={refresh} />
{:else if data}
    <!-- Before Verify, because a preference chosen after the check is a check
         that tested the other one. -->
    <AgentPrefs />

    <article class="card">
        <div class="cardhead">
            <h3><Icon name="ok" /> Verify the connection</h3>
            <button disabled={verifying} onclick={verify}>
                {verifying ? "Starting…" : "Verify"}
            </button>
        </div>
        <ol class="steps" aria-label="Verify steps">
            {#each verifySteps as step (step.id)}
                <li>
                    {@render mark(step.state)}
                    <span>{step.label}</span>
                    {#if STATE_WORDS[step.state]}
                        <span class="meta state-{step.state}">{STATE_WORDS[step.state]}</span>
                    {/if}
                </li>
            {/each}
        </ol>
        {#if verdict?.log}
            <button class="ghost small" onclick={() => (showLog = !showLog)}>
                {showLog ? "Hide log" : "Show log"}
            </button>
            {#if showLog}<pre>{verdict.log}</pre>{/if}
        {/if}
    </article>

    <article class="card">
        <h3><Icon name="agents" /> Connect another harness</h3>
        <ol class="steps" aria-label="Connect another harness">
            <li>
                {@render mark(copyState)}
                <span>Copy the config block</span>
                <button class="small" onclick={copy}>Copy</button>
                <button class="ghost small" onclick={() => (showManual = !showManual)}>
                    {showManual ? "Hide the config block" : "Show the config block"}
                </button>
            </li>
            <li>
                {@render mark("todo")}
                <span>Paste it into the harness config</span>
            </li>
            <li>
                {@render mark(verifyState)}
                <span>Verify</span>
            </li>
        </ol>
        {#if showManual}<pre>{snippet}</pre>{/if}
    </article>
{/if}

<style>
    .cardhead {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-2);
        flex-wrap: wrap;
    }
    .cardhead h3 {
        margin: 0;
    }
    h2,
    h3 {
        display: flex;
        align-items: center;
        gap: var(--s-2);
    }
    .steps {
        list-style: none;
        margin: var(--s-2) 0;
        padding: 0;
    }
    .steps li {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        padding-block: 0.3rem;
        border-bottom: 1px solid var(--line);
    }
    .stateicon {
        display: inline-flex;
        width: 1rem;
        justify-content: center;
    }
    .stateicon[data-state="ok"] {
        color: var(--low);
    }
    .stateicon[data-state="failed"] {
        color: var(--high);
    }
    .ring {
        width: 0.7rem;
        height: 0.7rem;
        border: 1.5px solid var(--ink-2);
        border-radius: 50%;
    }
    .state-failed {
        color: var(--high);
    }
    pre {
        max-height: 24rem;
        overflow: auto;
    }
</style>
