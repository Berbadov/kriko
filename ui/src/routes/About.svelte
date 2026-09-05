<script lang="ts">
    import { api } from "../lib/api";
    import { THEMES, THEME_LABELS, setTheme, theme } from "../lib/theme";
    import type { Health } from "../lib/types";

    let health = $state<Health | null>(null);
    let error = $state("");

    async function load() {
        try {
            health = await api.health();
        } catch (e) {
            error = (e as Error).message;
        }
    }

    const ready = load();
</script>

<h2>This install</h2>
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
        <p class="state error">Could not read this install's health: {error}</p>
    {:else if health}
        <dl class="facts">
            <dt>App</dt>
            <dd>{health.version} <span class="meta">schema {health.schema_version}</span></dd>
            <dt>Knowledge store</dt>
            <dd class="path">{health.store}</dd>
            <dt>App state</dt>
            <dd class="path">{health.app_state}</dd>
        </dl>

        <h3>Appearance</h3>
        <p class="meta">
            A theme is one complete palette, not a tweak — every colour in the
            app comes from the one you pick here.
        </p>
        <div class="row">
            {#each THEMES as id (id)}
                <label>
                    <input
                        type="radio"
                        name="theme"
                        value={id}
                        checked={$theme === id}
                        onchange={() => setTheme(id)}
                    />
                    {THEME_LABELS[id]}
                </label>
            {/each}
        </div>

        <h3>Updating</h3>
        <p class="meta">
            The app updates itself when a release is signed — it checks on its
            own at startup and asks before installing anything. A release that
            carries no signature cannot be installed that way, and there is no
            in-app version switch: moving between builds means running an
            installer.
            <a href={health.releases_url} target="_blank" rel="noreferrer"
                >All releases</a
            >
        </p>
        <p class="meta">
            Packs update on their own clock, from the Packs screen — knowledge
            changes far more often than this binary does.
        </p>

        <h3>Installed packs</h3>
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
                screen, not here — this view reports, it does not change anything.
            </p>
        {:else}
            <p class="state empty">No packs installed yet.</p>
        {/if}
    {/if}
{/await}
