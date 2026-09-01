<script lang="ts">
    import Async from "../lib/Async.svelte";
    import { api } from "../lib/api";
    import { follow, stateWord } from "../lib/jobs";
    import type { AgentConfig, Gap, Job } from "../lib/types";

    const load = async () => {
        const packs = await api.packs();
        return Promise.all(
            packs.map(async (pack) => ({ pack, gaps: await api.gaps(pack.pack_id) })),
        );
    };
    const data = load();

    // Research on the free plane produces a *brief* — instructions — not
    // claims. Saying so beside the button is the difference between "nothing
    // happened" and "here is the next step", and the next step needs an
    // address, which is what this fetches.
    let config = $state<AgentConfig | null>(null);
    let configError = $state("");
    let copied = $state(false);

    async function showConfig() {
        try {
            config = await api.agentConfig();
        } catch (cause) {
            configError = String(cause);
        }
    }

    const snippet = $derived(config ? JSON.stringify(config.mcp_json, null, 2) : "");

    async function copy() {
        try {
            await navigator.clipboard.writeText(snippet);
            copied = true;
        } catch {
            copied = false; // a denied clipboard is not an error worth a banner
        }
    }

    // A gap is only interesting if you can act on it, and until now acting on
    // it meant leaving the browser for a terminal. Keyed by subject so the
    // status lands on the row that started it.
    let started = $state<Record<string, Job>>({});

    async function research(gap: Gap, packId: string) {
        try {
            const { job_id } = await api.research({
                subject_id: gap.subject_id,
                pack_id: packId,
            });
            const job = await api.job(job_id);
            started = { ...started, [gap.subject_id]: job };
            follow(job_id, (update) => {
                started = { ...started, [gap.subject_id]: update };
            });
        } catch (cause) {
            // Reported inline rather than thrown: one gap failing to start
            // must not take the whole coverage report down with it.
            started = {
                ...started,
                [gap.subject_id]: {
                    state: "failed",
                    message: String(cause),
                    done: true,
                } as Job,
            };
        }
    }
</script>

<h2>Coverage gaps</h2>

<article class="card">
    <h3>Who does the research</h3>
    <p class="meta">
        <em>Research</em> below writes a <strong>brief</strong> — what to look for and what
        counts as evidence — and does not gather anything itself. That is deliberate: the
        free plane costs nothing because a coding agent you already pay for does the
        reading. Point one at this app and it can submit findings back through the same
        acceptance path, quotes checked against their source.
    </p>
    {#if configError}
        <p class="state error">Could not read the agent config: {configError}</p>
    {:else if config}
        <p class="meta">
            Paste into your harness (Claude Code: <code>.mcp.json</code>). It points at this
            window's own store, <code>{config.store}</code>. Tools: {config.tools.join(", ")}.
        </p>
        <pre>{snippet}</pre>
        <button onclick={copy}>{copied ? "Copied" : "Copy"}</button>
    {:else}
        <button onclick={showConfig}>Connect an agent</button>
    {/if}
</article>
<Async promise={data}>
    {#snippet children(sections)}
        {#if !sections.length}
            <p class="state empty">No packs installed.</p>
        {/if}
        {#each sections as { pack, gaps } (pack.pack_id)}
            <article class="card">
                <h3>{pack.name} <span class="badge">{gaps.length} gap(s)</span></h3>
                {#if gaps.length}
                    <ul>
                        {#each gaps as gap (gap.subject_id)}
                            <li class="gap">
                                <span>{gap.label} <span class="meta">({gap.kind})</span></span>
                                {#if started[gap.subject_id]}
                                    <span class="badge state-{started[gap.subject_id].state}"
                                        >{stateWord(started[gap.subject_id])}</span
                                    >
                                    <span class="meta">{started[gap.subject_id].message}</span>
                                {:else}
                                    <button onclick={() => research(gap, pack.pack_id)}
                                        >Research</button
                                    >
                                {/if}
                            </li>
                        {/each}
                    </ul>
                {:else}
                    <p class="state empty">No coverage gaps reported.</p>
                {/if}
            </article>
        {/each}
    {/snippet}
</Async>
