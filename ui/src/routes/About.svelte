<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import { api } from "../lib/api";
    import Failure from "../lib/Failure.svelte";
    import type { Health } from "../lib/types";
import PageHead from "../lib/kriko/PageHead.svelte";

    let health = $state<Health | null>(null);
    let error = $state<unknown>(null);

    async function load() {
        try {
            health = await api.health();
        } catch (e) {
            error = e;
        }
    }

    const ready = load();
</script>

<PageHead crumb="this install / about" title="This install" lead="What this is, and what it runs on." />
<p class="meta">
    Three versions, on three clocks. The app updates itself through its own
    installer; a pack updates through the engine whenever its knowledge changes;
    the store's schema changes with neither. Quote the one that matches the
    question.
</p>

{#await ready}
    <p class="state loading">Loading…</p>
{:then}
    {#if error}
        <Failure {error} retry={load} />
    {:else if health}
        <dl class="facts">
            <dt>App</dt>
            <dd>{health.version} <span class="meta">schema {health.schema_version}</span></dd>
            <dt>Knowledge store</dt>
            <dd class="path">{health.store}</dd>
            <dt>App state</dt>
            <dd class="path">{health.app_state}</dd>
        </dl>

        <h3><Icon name="download" /> Updating</h3>
        <p class="meta">
            The app updates itself when a release is signed; it checks on its
            own at startup and asks before installing anything. A release that
            carries no signature cannot be installed that way, and there is no
            in-app version switch: moving between builds means running an
            installer.
            <a href={health.releases_url} target="_blank" rel="noreferrer"
                >All releases</a
            >
        </p>
        <p class="meta">
            Packs update on their own clock, from the Packs screen; knowledge
            changes far more often than this binary does.
        </p>

        <h3><Icon name="console" /> Diagnostics</h3>
        <p class="meta">
            What to send us when something is wrong. Every line here is
            something this window cannot see for itself; it is reported by
            the process serving it.
        </p>
        <dl class="facts">
            <dt>Log file</dt>
            <dd class="path">
                {#if health.log_file}
                    {health.log_file}
                {:else}
                    <span class="state error"
                        >Nothing is being written down{health.log_problem
                            ? `: ${health.log_problem}`
                            : "."}</span
                    >
                {/if}
            </dd>
            <dt>Analysis log</dt>
            <dd class="path">
                {health.analysis_log}
                {#if health.analysis_log_problem}
                    <span class="state warn"
                        >The configured path could not be written, so this one is
                        in use instead: {health.analysis_log_problem}</span
                    >
                {/if}
            </dd>
            <dt>Desktop shell</dt>
            <dd>
                {#if health.shell_attached}
                    Attached <span class="meta"
                        >: "Open in Kriko" raises this window.</span
                    >
                {:else}
                    Not attached
                    <span class="meta"
                        >: this server is running on its own, so "Open in Kriko"
                        opens a browser tab instead of raising a window. That is
                        the correct behaviour here, not a fault.</span
                    >
                {/if}
            </dd>
            <dt>Extension port</dt>
            <dd>
                {health.extension_port}
                {#if !health.port_is_ours}
                    <p class="state error">
                        not held by this app, so the extension cannot reach
                        it. Something else on this machine took it.
                    </p>
                {/if}
            </dd>
        </dl>

        <h3><Icon name="packs" /> Installed packs</h3>
        {#if health.packs.length}
            <table>
                <thead><tr><th>Pack</th><th>Version</th></tr></thead>
                <tbody>
                    {#each health.packs as pack (pack.pack_id)}
                        <tr><td>{pack.pack_id}</td><td>{pack.version}</td></tr>
                    {/each}
                </tbody>
            </table>
            <p class="meta">
                Rolling a pack back to a retained revision is done on the Packs
                screen, not here; this view reports, it does not change anything.
            </p>
        {:else}
            <p class="state empty">No packs installed yet.</p>
        {/if}
    {/if}
{/await}
