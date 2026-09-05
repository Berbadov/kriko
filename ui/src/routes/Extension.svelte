<script lang="ts">
    import { onDestroy } from "svelte";
    import { api } from "../lib/api";
    import type { ExtensionStatus } from "../lib/types";

    let status = $state<ExtensionStatus | null>(null);
    let loadError = $state("");
    let busy = $state("");
    let actionError = $state("");
    let copied = $state("");

    async function refresh() {
        try {
            status = await api.extension();
            loadError = "";
        } catch (cause) {
            loadError = String(cause);
        }
    }
    refresh();

    // The last step of this install happens in another window, and the reader
    // will not think to come back and press something. Polling is how the page
    // gets to say "there it is" in the moment it becomes true — which is the
    // whole reason this is a status screen and not a list of instructions.
    // Cheap: one local request against a SQLite read.
    const timer = setInterval(refresh, 4000);
    onDestroy(() => clearInterval(timer));

    async function add() {
        busy = "stage";
        actionError = "";
        try {
            await api.stageExtension();
            await refresh();
        } catch (cause) {
            actionError = String(cause);
        } finally {
            busy = "";
        }
    }

    async function reveal() {
        busy = "reveal";
        actionError = "";
        try {
            const done = await api.revealExtension();
            // A machine with no file manager is not an error worth a banner —
            // the path is on screen and copyable, which is what they need.
            actionError = done.error;
        } catch (cause) {
            actionError = String(cause);
        } finally {
            busy = "";
        }
    }

    async function copy(text: string, what: string) {
        try {
            await navigator.clipboard.writeText(text);
            copied = what;
            setTimeout(() => (copied = ""), 2000);
        } catch {
            copied = ""; // a denied clipboard is not a failure of this page
        }
    }

    function ago(seconds: number | null): string {
        if (seconds === null) return "";
        if (seconds < 60) return "just now";
        if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
        return `${Math.round(seconds / 3600)} h ago`;
    }

    // Stale rather than absent: the folder is loaded, but it holds an older
    // extension than this app carries. Pressing Add again is the whole repair.
    const outdated = $derived(
        !!status?.staged &&
            !!status.staged_version &&
            status.staged_version !== status.version,
    );
</script>

<h2>Browser extension</h2>

<article class="card">
    <p class="meta">
        The extension is what puts Kriko on a listing page — it reads the ad you are
        looking at and asks this app what is known to go wrong with that one. It talks
        only to <code>127.0.0.1:{status?.port ?? 8787}</code>; nothing leaves your machine.
    </p>
    <p class="meta">
        No browser lets an application install an extension — that is a deliberate rule,
        not a gap, and it is why the last three steps below are yours. This page does
        everything on this side of it: puts the files somewhere stable, opens the folder,
        and tells you the moment the extension actually reaches the app.
    </p>
</article>

{#if loadError}
    <p class="state error">Could not read the extension status: {loadError}</p>
{:else if status}
    {#if !status.available}
        <p class="state error">
            This build does not carry the extension files. That is a packaging fault
            rather than something to fix here.
        </p>
    {:else}
        <article class="card">
            <h3>
                Status
                {#if status.connected}
                    <span class="badge state-connected"
                        ><span class="live-dot"></span> Connected</span
                    >
                {:else if status.staged}
                    <span class="badge state-absent">Waiting for the browser</span>
                {:else}
                    <span class="badge state-absent">Not added yet</span>
                {/if}
            </h3>

            {#if status.connected}
                <p class="meta">
                    An extension called this app {ago(status.seconds_since_seen)}. That
                    is real evidence, not a setting: a browser stamps its own origin on
                    every request, so nothing but a running extension could have sent it.
                </p>
            {:else}
                <p class="meta">
                    Nothing has called yet. This flips on its own the first time you open
                    a listing with the extension loaded — no need to come back and press
                    anything.
                </p>
            {/if}

            {#if !status.port_is_ours}
                <p class="state error">
                    Port {status.port} is not held by this app, so the extension has no way
                    to reach it. Something else on this machine took it — close that, then
                    restart Kriko. Until then the extension will install correctly and
                    still fail on every listing.
                </p>
            {/if}

            {#if outdated}
                <p class="state warn">
                    The loaded folder holds extension {status.staged_version}; this app
                    carries {status.version}. Press Add again, then hit Reload on the
                    extension's card in your browser.
                </p>
            {/if}
        </article>

        <article class="card">
            <h3>1 · Put the files somewhere the browser can keep</h3>
            <p class="meta">
                Written to your Kriko folder rather than the install directory, because a
                browser remembers an unpacked extension by path and would drop it every
                time the app updates.
            </p>
            <p>
                <button disabled={busy === "stage"} onclick={add}>
                    {#if busy === "stage"}
                        Adding…
                    {:else if status.staged}
                        Add again
                    {:else}
                        Add the extension
                    {/if}
                </button>
                {#if status.staged}
                    <button disabled={busy === "reveal"} onclick={reveal}>
                        Open the folder
                    </button>
                    <button onclick={() => copy(status!.path, "path")}>
                        {copied === "path" ? "Copied" : "Copy the path"}
                    </button>
                {/if}
            </p>
            {#if status.staged}
                <p><code class="path">{status.path}</code></p>
            {/if}
            {#if actionError}<p class="state error">{actionError}</p>{/if}
        </article>

        {#if status.staged}
            <article class="card">
                <h3>2 · Load it, once</h3>
                <ol class="steps">
                    <li>
                        Open your browser's extensions page:
                        <span class="urls">
                            {#each status.browsers as browser (browser.id)}
                                <button
                                    class="link"
                                    onclick={() => copy(browser.url, browser.id)}
                                    title="Copy — browsers refuse to open these from an app"
                                >
                                    {copied === browser.id ? "copied" : browser.url}
                                </button>
                            {/each}
                        </span>
                        <span class="meta"
                            >These have to be pasted into the address bar; a browser will
                            not open its own settings page on an app's say-so.</span
                        >
                    </li>
                    <li>Turn on <strong>Developer mode</strong>.</li>
                    <li>
                        Choose <strong>Load unpacked</strong> and pick the folder above.
                        On Firefox it is <strong>Load Temporary Add-on</strong>, and you
                        pick <code>manifest.json</code> inside it.
                    </li>
                    <li>
                        Open any listing. The status above turns green by itself when the
                        extension reaches this app.
                    </li>
                </ol>
            </article>
        {/if}

        {#if status.sightings.length}
            <article class="card">
                <h3>Extensions that have called</h3>
                <ul>
                    {#each status.sightings as seen (seen.origin)}
                        <li class="target">
                            <code>{seen.origin}</code>
                            <span class="meta">{seen.hits} calls, last {seen.last_at}</span>
                        </li>
                    {/each}
                </ul>
                <p class="meta">
                    One row per browser profile: each install gets its own id, so two rows
                    means two browsers wired to this app rather than a duplicate.
                </p>
            </article>
        {/if}
    {/if}
{:else}
    <p class="state loading">Reading the extension status…</p>
{/if}

<style>
    .path {
        word-break: break-all;
    }
    .steps {
        margin: 0;
        padding-left: 1.2rem;
        display: grid;
        gap: 0.6rem;
    }
    .steps .meta {
        display: block;
    }
    .urls {
        display: inline-flex;
        flex-wrap: wrap;
        gap: 0.4rem;
    }
    button.link {
        background: none;
        border: 1px solid var(--line);
        color: var(--accent);
        font-family: var(--font-mono);
        cursor: pointer;
    }
</style>
