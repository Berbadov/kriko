<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import Async from "../lib/Async.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import { api } from "../lib/api";
    import { follow, stateWord } from "../lib/jobs";
    import type { Job, Site, SiteDetail, SiteRule } from "../lib/types";

    const load = () => api.sites();
    let promise = $state(load());
    let busy = $state("");
    let started = $state("");
    let registerJob = $state<Job | null>(null);
    let failure = $state<unknown>(null);
    let confirmForget = $state("");

    /* One expanded site at a time (B181). */
    let openHost = $state("");
    let detail = $state<SiteDetail | null>(null);
    let detailError = $state<unknown>(null);

    /* Amendments (B181): the spec as editable JSON. */
    let draft = $state("");
    let savedNote = $state("");
    let amendError = $state<unknown>(null);
    let amendKey = $state(0);

    /* B184: a search box over both lists. */
    let filterText = $state("");
    const matches = (one: string) =>
        !filterText.trim() || one.toLowerCase().includes(filterText.trim().toLowerCase());

    const ASK_WORDS: Record<string, string> = {
        working: "Working…",
        refused: "Could not read it",
    };

    async function toggleDetail(site: Site) {
        const key = `${site.pack_id}|${site.id}`;
        if (openHost === key) {
            openHost = "";
            return;
        }
        openHost = key;
        detail = null;
        detailError = null;
        try {
            detail = await api.siteDetail(site.site);
            if (detail?.spec) draft = JSON.stringify(detail.spec, null, 2);
        } catch (cause) {
            detailError = cause;
        }
    }

    async function saveAmend() {
        amendError = null;
        savedNote = "";
        let spec: unknown;
        try {
            spec = JSON.parse(draft);
        } catch {
            amendError = "not valid JSON";
            return;
        }
        try {
            await api.amendSite(detail!.site, spec as Record<string, unknown>);
            savedNote = "Saved. Reload a listing to read it with the new rules.";
            amendKey += 1;
            detail = await api.siteDetail(detail!.site);
            if (detail?.spec) draft = JSON.stringify(detail.spec, null, 2);
        } catch (cause) {
            amendError = cause;
        }
    }

    async function register(host: string) {
        if (busy) return;
        busy = host;
        failure = null;
        try {
            const { job_id } = await api.registerSite(host);
            started = host;
            registerJob = await api.job(job_id);
            follow(job_id, async (job) => {
                registerJob = job;
                if (job.done) {
                    promise = load();
                    started = "";
                }
            });
        } catch (thrown) {
            failure = thrown;
            started = "";
        } finally {
            busy = "";
        }
    }

    async function forget(host: string) {
        if (confirmForget !== host) {
            confirmForget = host;
            return;
        }
        confirmForget = "";
        if (busy) return;
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

<h2><Icon name="sites" size={22} /> Sites</h2>
<p class="lede">
    An <em>adapter</em> turns a listing page into a product. Packs ship them;
    this install can also learn one.
</p>

{#if failure}
    <Failure error={failure} />
{/if}

{#if started}
    <p class="state">
        Reading {started}{#if registerJob}, {stateWord(registerJob)}{/if}
        on <a href="#/activity">Activity</a>.
    </p>
{/if}

<Async {promise} loading="Reading the adapters…">
    {#snippet children(data)}
        <section>
            <h3><Icon name="eye" size={16} /> Readable here</h3>
            {#if data.registered.length > 3}
                <form class="filters" onsubmit={(event) => event.preventDefault()}>
                    <label class="field grow">
                        <span>Filter sites</span>
                        <input bind:value={filterText} placeholder="site or source" />
                    </label>
                </form>
            {/if}
            {#if !data.registered.length}
                <EmptyState
                    title="No site can be read yet"
                    detail="Install a catalog that ships an adapter, or press the
                            extension button on a listing."
                    actionLabel="Open Browse"
                    actionHref="#/knowledge"
                />
            {:else}
                <ul class="klist" aria-label="Readable sites">
                    {#each data.registered as site (`${site.pack_id}|${site.id}|${site.site}|${site.source}`)}
                        {@const openKey = `${site.pack_id}|${site.id}`}
                        {#if matches(`${site.site} ${site.source} ${site.pack_id}`)}
                        <li class="krow">
                            <div class="kmain">
                                <span class="klabel">{site.site}</span>
                                <span class="meta">
                                    {site.source === "pack"
                                        ? `from ${site.pack_id}`
                                        : "learned here"}
                                    {#if site.superseded}· unused{/if}
                                </span>
                                {#if site.activation && site.activation.state !== "active"}
                                    <span class="meta">
                                        {#if site.activation.state === "needs_permission"}
                                            · permission pending: press Grant on the
                                            extension's options page
                                        {:else if site.activation.state === "unknown"}
                                            · the extension has not reported on this
                                            site yet
                                        {:else}
                                            · {site.activation.detail || "the panel will not appear here yet"}
                                        {/if}
                                    </span>
                                {/if}
                            </div>
                            <div class="kactions">
                                <button
                                    aria-expanded={openHost === `${site.pack_id}|${site.id}`}
                                    onclick={() => toggleDetail(site)}
                                >{openHost === `${site.pack_id}|${site.id}` ? "Hide" : "Detail"}</button>
                                {#if site.source === "local"}
                                    <button
                                        class="ghost"
                                        onclick={() => forget(site.site)}
                                        disabled={busy === site.site}
                                        >{confirmForget === site.site ? "Really forget it?" : "Forget it"}</button
                                    >
                                    {#if confirmForget === site.site}
                                        <button class="ghost" onclick={() => (confirmForget = "")}>Cancel</button>
                                    {/if}
                                {/if}
                            </div>
                        </li>
                        {#if openHost === openKey}
                            <li class="detail">
                                {#if detailError}
                                    <Failure error={detailError} />
                                {:else if !detail}
                                    <p class="state loading">Reading the adapter…</p>
                                {:else}
                                    <dl class="facts">
                                        <dt>Match</dt>
                                        <dd class="path">{detail.match.join(", ") || "the whole site"}</dd>
                                        <dt>Fields read</dt>
                                        <dd>
                                            {#if detail.rules.length}
                                                {#each detail.rules as rule (rule.kind + rule.key)}
                                                    <span class="meta">
                                                        {rule.kind}: <code>{rule.key}</code>
                                                        {#if rule.labels.length}
                                                            from {rule.labels.join(", ")}
                                                        {:else}
                                                            from the page {rule.from}
                                                        {/if}
                                                    </span>
                                                {/each}
                                            {:else}
                                                <span class="meta">none declared</span>
                                            {/if}
                                        </dd>
                                        {#if detail.unmapped.length}
                                            <dt>Labels seen, not read</dt>
                                            <dd>
                                                {#each detail.unmapped as one (one.label)}
                                                    <span class="meta">
                                                        <code>{one.label}</code> · {one.seen} time{one.seen === 1 ? "" : "s"}
                                                        {#if one.sample_url}
                                                            · <a href={one.sample_url} target="_blank" rel="noreferrer">sample</a>
                                                        {/if}
                                                    </span>
                                                {/each}
                                            </dd>
                                        {/if}
                                        {#if detail.sample_url}
                                            <dt>Last page asked about</dt>
                                            <dd class="path"><a href={detail.sample_url} target="_blank" rel="noreferrer">{detail.sample_url}</a></dd>
                                        {/if}
                                        {#if detail.editable}
                                            <dt>Adapter</dt>
                                            <dd>
                                                <details open={amendKey > 0}>
                                                    <summary>Amend the rules</summary>
                                                    <p class="meta">
                                                        Edit the JSON, then Save. Checked before it
                                                        is stored, exactly as at registration.
                                                    </p>
                                                    <textarea bind:value={draft} rows="12" aria-label="Adapter rules"></textarea>
                                                    <p class="row">
                                                        <button class="primary" onclick={saveAmend}>Save</button>
                                                        {#if savedNote}<span class="state fact-ok">{savedNote}</span>{/if}
                                                    </p>
                                                    {#if amendError}<Failure error={amendError} />{/if}
                                                </details>
                                            </dd>
                                        {:else}
                                            <dt>Adapter</dt>
                                            <dd class="meta">shipped with {detail.pack_id || "a catalog"}, read-only here</dd>
                                        {/if}
                                    </dl>
                                {/if}
                            </li>
                        {/if}
                        {/if}
                    {/each}
                </ul>
            {/if}
        </section>

        <section>
            <h3><Icon name="plus" size={16} /> Asked for</h3>
            {#if !data.requested.length}
                <p class="state">Nothing yet. Press the extension button on a listing page.</p>
            {:else}
                <ul class="klist" aria-label="Sites asked for">
                    {#each data.requested as ask (ask.host)}
                        {#if matches(ask.host)}
                        <li class="krow">
                            <div class="kmain">
                                <span class="klabel">{ask.host}</span>
                                <span class="meta">
                                    asked {ask.asks} time{ask.asks === 1 ? "" : "s"}
                                    {#if ask.state === "refused"}
                                        · could not read it
                                        {#if ask.detail}<details><summary>Why</summary>{ask.detail}</details>{/if}
                                    {:else if ask.state !== "open"}
                                        · {ASK_WORDS[ask.state] ?? ask.state}
                                    {/if}
                                </span>
                            </div>
                            <button
                                onclick={() => register(ask.host)}
                                disabled={busy === ask.host || ask.state === "working"}
                                >{ask.state === "working"
                                    ? "Working…"
                                    : ask.state === "refused"
                                      ? "Try again"
                                      : "Teach Kriko this site"}</button
                            >
                        </li>
                        {/if}
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
    .kactions {
        display: flex;
        gap: var(--s-2);
        align-items: center;
    }
    li.detail {
        margin-inline-start: var(--s-5);
        padding: var(--s-3);
        border: 1px solid var(--line);
        border-radius: var(--radius);
    }
    li.detail dd span.meta {
        display: block;
    }
    textarea {
        width: 100%;
        min-height: 12rem;
    }
</style>
