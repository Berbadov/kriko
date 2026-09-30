<script lang="ts">
    import AgentPrefs from "../lib/Agents.prefs.svelte";
    import Icon from "../lib/Icon.svelte";
    import Failure from "../lib/Failure.svelte";
    import { remedyFor } from "../lib/failure";
    import { api } from "../lib/api";
    import { copyText, copyWord } from "../lib/clipboard";
    import type { AgentConfig, AgentVerify } from "../lib/types";

    // B164: this screen is the agents and nothing else. The harness list, the
    // top-N agenda, the build-knowledge planes, the schedule and the skill text
    // used to sit under it. Connecting an agent is an action on its own row in
    // "Your agents" now; research starts per product, from Run, Browse or the
    // extension.
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

    async function verify() {
        verifying = true;
        verdict = null;
        try {
            verdict = await api.verifyAgent();
        } catch (cause) {
            // Not the whole remedy: the verdict block below already says
            // "it did not answer", which is the headline. What it needs
            // from the exception is the detail under it.
            verdict = { ok: false, detail: remedyFor(cause).technical };
        } finally {
            verifying = false;
        }
    }
</script>

<h2><Icon name="connect" size={22} /> Agents</h2>

{#if loadError}
    <Failure error={loadError} retry={refresh} />
{:else if data}
    <!-- Before Verify, because a preference chosen after the check is a check
         that tested the other one. -->
    <AgentPrefs />

    <article class="card">
        <div class="cardhead">
            <h3><Icon name="ok" /> Does it actually run?</h3>
            <button disabled={verifying} onclick={verify}>
                {verifying ? "Starting…" : "Verify"}
            </button>
        </div>
        <p class="meta">
            Starts the command the config names and waits for it to answer.
        </p>
        {#if verdict?.ok}
            <p class="state ok">Answered as <code>{verdict.server}</code>.</p>
        {:else if verdict}
            <p class="state error">It did not answer.</p>
            <pre>{verdict.detail}</pre>
        {/if}
    </article>

    <article class="card">
        <h3><Icon name="agents" /> Another harness</h3>
        <p class="meta">
            Anything that speaks MCP works. Paste this into its config.
        </p>
        {#if showManual}
            <pre>{snippet}</pre>
            <button onclick={copy}>{copied ? copyWord(copied === "yes") : "Copy"}</button>
        {:else}
            <button onclick={() => (showManual = true)}>Show the config block</button>
        {/if}
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
    pre {
        max-height: 24rem;
        overflow: auto;
    }
</style>
