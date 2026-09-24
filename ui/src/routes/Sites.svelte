<script lang="ts">
    import Async from "../lib/Async.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { api } from "../lib/api";
    import type { Site } from "../lib/types";

    /* Which sites Kriko can read, and how it learns another.
     *
     * The reader's sentence this exists for: "I cannot open the extension on
     * pages that aren't registered, so basically it opens on sahibinden only."
     * Nothing was broken there — the panel was missing because the *site* was,
     * and the only way to add one was to author a whole pack.
     *
     * Two lists, because they are two different facts: what can be read (from
     * packs, or learned here), and what somebody stood on and asked for. The
     * second is the demand signal, and it only exists because the extension
     * now reports a page it could not read when the toolbar button is pressed.
     */

    const load = () => api.sites();
    let promise = $state(load());
    let busy = $state("");
    let started = $state("");
    let failure = $state<unknown>(null);

    async function register(host: string) {
        busy = host;
        failure = null;
        try {
            const job = await api.registerSite(host);
            started = host;
            promise = load();
        } catch (thrown) {
            failure = thrown;
        } finally {
            busy = "";
        }
    }

    async function forget(host: string) {
        busy = host;
        failure = null;
        try {
            await api.forgetSite(host);
            promise = load();
        } catch (thrown) {
            failure = thrown;
        } finally {
            busy = "";
        }
    }
</script>

<h2>Sites</h2>
<p class="lede">
    Kriko reads a listing page through an <strong>adapter</strong> — the rules for
    turning that page into "which product is this". Packs ship them; this
    installation can also learn one. Until a site has an adapter the extension has
    nothing to do on it, which is why its button reports the page instead.
</p>

{#if failure}<Failure error={failure} />{/if}
{#if started}
    <p class="state">
        Reading {started} — <a href="#/activity">watch it on Activity</a>. When it
        finishes, open a listing there and press the extension button.
    </p>
{/if}

<Async {promise} loading="Reading the adapters…">
    {#snippet children(data)}
        <section>
            <h3>Readable here</h3>
            {#if !data.registered.length}
                <EmptyState
                    title="No site can be read yet"
                    detail="Install a pack that ships an adapter, or open a listing page
                            and press the extension button — the site lands below and an
                            agent can work out how to read it."
                    actionLabel="Packs"
                    actionHref="#/packs"
                />
            {:else}
                <ul class="klist" aria-label="Readable sites">
                    {#each data.registered as site (site.site + site.source)}
                        <li class="krow">
                            <div class="kmain">
                                <span class="klabel">{site.site}</span>
                                <span class="meta">
                                    {site.source === "pack"
                                        ? `from ${site.pack_id}`
                                        : "learned here"}
                                    {#if site.superseded}
                                        · a pack now ships one for this site, so this copy
                                        is unused
                                    {/if}
                                </span>
                                {#if site.activation && site.activation.state !== "active"}
                                    <span class="meta">
                                        {#if site.activation.state === "needs_permission"}
                                            · adapter ready, but the browser has not
                                            granted permission — open the extension's
                                            options page and press Grant, then reload
                                            the listing
                                        {:else if site.activation.state === "unknown"}
                                            · adapter ready; the extension has not
                                            reported on this site yet — open a listing
                                            there and press the extension button
                                        {:else}
                                            · {site.activation.detail ||
                                                "the panel will not appear here yet"}
                                        {/if}
                                    </span>
                                {/if}
                            </div>
                            {#if site.source === "local"}
                                <button
                                    class="ghost"
                                    onclick={() => forget(site.site)}
                                    disabled={busy === site.site}>Forget it</button
                                >
                            {/if}
                        </li>
                    {/each}
                </ul>
            {/if}
        </section>

        <section>
            <h3>Asked for</h3>
            <p class="meta">
                Pages somebody opened that nothing here could read. One row per site,
                with the page an agent would read to work it out.
            </p>
            {#if !data.requested.length}
                <p class="state">
                    Nothing yet. Press the extension's button on a listing page Kriko
                    does not know and it will appear here.
                </p>
            {:else}
                <ul class="klist" aria-label="Sites asked for">
                    {#each data.requested as ask (ask.host)}
                        <li class="krow">
                            <div class="kmain">
                                <span class="klabel">{ask.host}</span>
                                <span class="meta">
                                    asked {ask.asks} time{ask.asks === 1 ? "" : "s"}
                                    {#if ask.state !== "open"}· {ask.state}{/if}
                                    {#if ask.detail}· {ask.detail}{/if}
                                </span>
                            </div>
                            <button
                                onclick={() => register(ask.host)}
                                disabled={busy === ask.host || ask.state === "working"}
                                >{ask.state === "working"
                                    ? "Working…"
                                    : "Teach Kriko this site"}</button
                            >
                        </li>
                    {/each}
                </ul>
            {/if}
        </section>
    {/snippet}
</Async>

<style>
    section {
        margin-block: 1.5rem;
    }
</style>
