<script lang="ts">
    import { api } from "../lib/api";
    import type {
        AgentConfig,
        AgentSkill,
        AgentTarget,
        AgentTargets,
        AgentVerify,
    } from "../lib/types";

    // Both halves are loaded together because they answer one question between
    // them — "is an agent going to be able to do this?" — and a page that
    // resolves half of it invites the reader to act on the wrong half.
    const load = async () =>
        Promise.all([api.agentTargets(), api.agentConfig(), api.agentSkill()]);

    let data = $state<[AgentTargets, AgentConfig, AgentSkill] | null>(null);
    let loadError = $state("");
    let busy = $state("");
    let showManual = $state(false);
    let copied = $state(false);

    async function refresh() {
        try {
            data = await load();
            loadError = "";
        } catch (cause) {
            loadError = String(cause);
        }
    }
    refresh();

    // Errors land on the row rather than the page: one harness whose config
    // someone broke by hand must not hide the three that are fine.
    let rowError = $state<Record<string, string>>({});

    async function connect(target: AgentTarget) {
        busy = target.id;
        rowError = { ...rowError, [target.id]: "" };
        try {
            await api.connectAgent(target.id);
            await refresh();
        } catch (cause) {
            rowError = { ...rowError, [target.id]: String(cause) };
        } finally {
            busy = "";
        }
    }

    const snippet = $derived(data ? JSON.stringify(data[1].mcp_json, null, 2) : "");

    async function copy() {
        try {
            await navigator.clipboard.writeText(snippet);
            copied = true;
        } catch {
            copied = false; // a denied clipboard is not an error worth a banner
        }
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
            verdict = { ok: false, detail: String(cause) };
        } finally {
            verifying = false;
        }
    }

    const WORDS: Record<string, string> = {
        connected: "Connected",
        stale: "Points elsewhere",
        absent: "Not connected",
        unreadable: "Config unreadable",
    };
</script>

<h2>Connect an agent</h2>

<article class="card">
    <p class="meta">
        Kriko gathers nothing on its own. It hands a coding agent a brief — what to look
        for and what counts as evidence — and checks every quote against the page it came
        from. Connecting writes this app's address into the harness's own config, so the
        agent reads and writes <em>this</em> window's knowledge and not some other copy.
    </p>
</article>

{#if loadError}
    <p class="state error">Could not read the harness config: {loadError}</p>
{:else if data}
    <article class="card">
        <h3>Harnesses on this machine</h3>
        <ul>
            {#each data[0].targets as target (target.id)}
                <li class="target">
                    <span>
                        <strong>{target.label}</strong>
                        <span class="meta">{target.path}</span>
                    </span>
                    <span class="badge state-{target.state}">{WORDS[target.state]}</span>
                    {#if target.state !== "unreadable"}
                        <button disabled={busy === target.id} onclick={() => connect(target)}>
                            {#if busy === target.id}
                                Connecting…
                            {:else if target.state === "connected"}
                                Rewrite
                            {:else}
                                Connect
                            {/if}
                        </button>
                    {/if}
                    {#if target.detail}<span class="meta">{target.detail}</span>{/if}
                    {#if rowError[target.id]}
                        <span class="state error">{rowError[target.id]}</span>
                    {/if}
                </li>
            {/each}
        </ul>
        <p class="meta">
            Restart the harness afterwards — none of them re-read their config while
            running. Connecting points it at <code>{data[0].store}</code>.
        </p>
    </article>

    <article class="card">
        <h3>Does it actually run?</h3>
        <p class="meta">
            Starts the same command the config names and waits for it to introduce
            itself. This is the half a written config cannot tell you: a moved virtual
            environment or a missing module fails here and nowhere else, and in a harness
            it surfaces only as an agent that returns nothing.
        </p>
        <button disabled={verifying} onclick={verify}>
            {verifying ? "Starting…" : "Verify"}
        </button>
        {#if verdict?.ok}
            <p class="state ok">Answered as <code>{verdict.server}</code>.</p>
        {:else if verdict}
            <p class="state error">It did not answer.</p>
            <pre>{verdict.detail}</pre>
        {/if}
    </article>

    <article class="card">
        <h3>What the agent is told</h3>
        {#if data[2].body}
            <p class="meta">
                Installed alongside the config, and rebuilt from the packs you have
                installed — so updating a pack updates what counts as a good finding,
                without updating this app.
            </p>
            <ol>
                {#each data[2].steps as step (step.tool)}
                    <li><code>{step.tool}</code> — {step.why}</li>
                {/each}
            </ol>
            <details>
                <summary>Read the skill</summary>
                <pre>{data[2].body}</pre>
            </details>
        {:else}
            <p class="state empty">
                No packs installed, so there is nothing to research yet and nothing to say
                what would count.
            </p>
        {/if}
    </article>

    <article class="card">
        <h3>Another harness</h3>
        <p class="meta">
            Anything that speaks MCP works — the validation lives in the server, so no
            client can bypass it. Paste this into its config.
        </p>
        {#if showManual}
            <pre>{snippet}</pre>
            <button onclick={copy}>{copied ? "Copied" : "Copy"}</button>
        {:else}
            <button onclick={() => (showManual = true)}>Show the config block</button>
        {/if}
    </article>
{/if}

<style>
    .target {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        flex-wrap: wrap;
        padding: var(--s-2) 0;
        border-bottom: 1px solid var(--line);
    }
    .target span:first-child {
        display: flex;
        flex-direction: column;
        min-width: 14rem;
    }
    .state-connected {
        background: var(--low-soft);
        color: var(--low);
    }
    .state-stale,
    .state-unreadable {
        background: var(--high-soft);
        color: var(--high);
    }
    pre {
        max-height: 24rem;
        overflow: auto;
    }
</style>
