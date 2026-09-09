<script lang="ts">
    import { onDestroy } from "svelte";
    import { api } from "../lib/api";
    import Failure from "../lib/Failure.svelte";
    import type { Adapter, ExtensionLaunched, ExtensionStatus } from "../lib/types";

    let status = $state<ExtensionStatus | null>(null);
    // Which sites the installed packs can read. It belongs on this screen
    // rather than an author one: "will it do anything on the page I am
    // looking at" is the reader's actual question about an extension, and
    // until now the only way to find out was to open a listing and see. The
    // list is pack data — a pack ships its adapters — so installing one
    // changes this without a line of app code.
    let adapters = $state<Adapter[]>([]);
    let loadError = $state<unknown>(null);
    let busy = $state("");
    let actionError = $state<unknown>(null);
    let copied = $state("");

    async function refresh() {
        try {
            status = await api.extension();
            adapters = await api.adapters().catch(() => [] as Adapter[]);
            loadError = null;
        } catch (cause) {
            loadError = cause;
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
        actionError = null;
        try {
            await api.stageExtension();
            await refresh();
        } catch (cause) {
            actionError = cause;
        } finally {
            busy = "";
        }
    }

    // The one click. `launched` is deliberately not treated as success: the
    // window opening is all this app can observe, and a Chrome build that has
    // stopped honouring --load-extension opens an ordinary one. So the button
    // hands over to the same polling that proves every other install.
    let launched = $state<ExtensionLaunched | null>(null);

    async function launch() {
        busy = "launch";
        actionError = null;
        try {
            launched = await api.launchExtension();
            await refresh();
        } catch (cause) {
            actionError = cause;
        } finally {
            busy = "";
        }
    }

    async function reveal() {
        busy = "reveal";
        actionError = null;
        try {
            const done = await api.revealExtension();
            // A machine with no file manager is not an error worth a banner —
            // the path is on screen and copyable, which is what they need.
            actionError = new Error(done.error);
        } catch (cause) {
            actionError = cause;
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
        No browser lets an application install an extension into a browser that is
        already running — that is a deliberate rule, not a gap. What it can do is start
        a fresh Chromium with the extension already loaded, which is the button below.
        The numbered steps stay for the browser you already have open, and for Firefox.
    </p>
</article>

{#if loadError}
    <Failure error={loadError} />
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

            <!-- A third version, and the only one that describes what is
                 actually running: an unpacked extension is loaded once and
                 stays loaded, so both numbers above can read current while
                 the browser holds a copy from months ago. The app wrote the
                 sentence, because the floor it was compared against lives
                 there and a second copy of that rule would drift. -->
            {#if status.compatibility?.detail}
                <p
                    class="state"
                    class:error={status.compatibility.state === "too_old"}
                    class:warn={status.compatibility.state === "behind"}
                >
                    {status.compatibility.detail}
                </p>
            {/if}
        </article>

        <!-- The one click, above the numbered steps rather than instead of
             them: this cannot report success (see `launch` above), and a
             browser that quietly ignored the extension has to leave the
             reader somewhere other than a dead end. -->
        <article class="card">
            <h3>One click</h3>
            <p class="meta">
                Opens a new Chromium — Chrome, Chromium, Brave or Edge, whichever is on
                this machine — with the extension already loaded, on this page, so the
                Status above turns green in front of you.
            </p>
            <p>
                <button class="primary" disabled={busy === "launch"} onclick={launch}>
                    {busy === "launch"
                        ? "Opening a browser…"
                        : "Open a browser with Kriko loaded"}
                </button>
            </p>
            {#if launched}
                {#if launched.error}
                    <p class="state warn">{launched.error}</p>
                {:else}
                    <p class="state">
                        Started {launched.browser}. If the window opened and Status is
                        still waiting, that browser declined the extension — the steps
                        below are the install then.
                    </p>
                {/if}
                <p class="meta">{launched.note}</p>
                <p class="meta">
                    Its profile: <code class="path">{launched.profile}</code>
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
            {#if actionError}<Failure error={actionError} />{/if}
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

        <article class="card">
            <h3>Once it is loaded</h3>
            <!-- Two facts a reader can only learn by being told. A keyboard
                 shortcut nobody knows about is a shortcut nobody has, and the
                 extension's own settings page is buried in the browser's
                 extension manager — which is the last place someone looks
                 when the panel says nothing is listening. -->
            <ul class="plain">
                <li>
                    The panel opens from the toolbar button, or with
                    <kbd>Alt</kbd> + <kbd>K</kbd> on the listing itself. If
                    another extension already owns that combination the browser
                    silently declines it — the toolbar button always works.
                </li>
                <li>
                    It looks for this app at <code>{status.port
                        ? `127.0.0.1:${status.port}`
                        : "127.0.0.1"}</code>. If you run the app somewhere
                    else, the extension's own options page is where that
                    address is changed — reachable from
                    <strong>Details → Extension options</strong> on your
                    browser's extensions page.
                </li>
            </ul>
        </article>

        <article class="card">
            <h3>Sites the installed packs can read</h3>
            {#if adapters.length}
                <ul>
                    {#each adapters as adapter (adapter.id)}
                        <li class="target">
                            <code>{adapter.site}</code>
                            <span class="meta">{adapter.pack_id}</span>
                            {#if adapter.match.length}
                                <span class="meta">matches {adapter.match.join(", ")}</span>
                            {/if}
                        </li>
                    {/each}
                </ul>
                <p class="meta">
                    On any other page the extension stays quiet — it has nothing to read
                    the page with, and guessing would be worse than silence. Describing
                    the thing by hand on New check works everywhere.
                </p>
            {:else}
                <p class="state empty">
                    No installed pack ships a site adapter, so the extension has nothing
                    to read a page with yet. Everything still works by hand on New check.
                </p>
            {/if}
        </article>

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
