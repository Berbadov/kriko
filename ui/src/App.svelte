<script lang="ts">
    import EmptyState from "./lib/EmptyState.svelte";
    import { api } from "./lib/api";
    import History from "./lib/History.svelte";
    import Lazy from "./lib/Lazy.svelte";
    import { asMode, initMode, mode, setMode } from "./lib/mode";
    import NextStep from "./lib/NextStep.svelte";
    import { initTheme } from "./lib/theme";
    import { watchFocus } from "./lib/focus";
    import { hashWith, route } from "./lib/router";
    import Palette from "./lib/shell/Palette.svelte";
    import Sidebar from "./lib/shell/Sidebar.svelte";
    import { isAuthorOnly, labelOf, resolve } from "./lib/shell/nav";
    import About from "./routes/About.svelte";
    import Activity from "./routes/Activity.svelte";
    import Agents from "./routes/Agents.svelte";
    import Bench from "./routes/Bench.svelte";
    import Check from "./routes/Check.svelte";
    import Compare from "./routes/Compare.svelte";
    import Extension from "./routes/Extension.svelte";
    import Knowledge from "./routes/Knowledge.svelte";
    import Overview from "./routes/Overview.svelte";
    import Packs from "./routes/Packs.svelte";
    import Questions from "./routes/Questions.svelte";
    import Settings from "./routes/Settings.svelte";
    import Sites from "./routes/Sites.svelte";
    import Result from "./routes/Result.svelte";
    import Welcome from "./routes/Welcome.svelte";

    // The sidebar panel belongs where a past answer is relevant: beside the
    // form that produces one and beside a result being read. On the History
    // *page* it would be the page twice.
    const WITH_HISTORY = new Set(["check", "result"]);
    const showHistory = $derived(WITH_HISTORY.has($route.name));

    // A view only an author has is not hidden from a buyer who has its link —
    // it is explained, and the switch is one click away in the rail. Silently
    // rendering nothing would look like a broken link.
    const authorOnly = $derived($mode !== "author" && isAuthorOnly($route.name));

    // Retired route names still resolve. Three screens became three lenses on
    // one, and `#/coverage` is a link the browser extension and this app's own
    // older hints both hand out — turning those into "No such view" would be
    // the reorganisation breaking the reader's bookmarks to prove a point.
    const view = $derived(resolve($route.name));

    // First run is a state of the store, not a stored flag: nothing to reset,
    // and a reader who removes every pack gets the offer again, which is the
    // right answer at that moment too. A failing status call must never gate
    // the app — an unreachable engine is a health problem, not a first run.
    let empty = $state(false);
    const checkStore = api
        .status()
        .then((s) => (empty = s.packs === 0))
        .catch(() => (empty = false));

    let dismissed = $state(false);
    const firstRun = $derived(empty && !dismissed && $route.name !== "welcome");

    // The theme joins the same gate rather than running after it: a first
    // paint in slate followed by a swap to lemonade is a flash the reader reads
    // as a bug.
    const ready = Promise.all([initMode($route.query.mode), initTheme(), checkStore]);

    // The browser extension's "Open in Kriko" arrives here: it posts a route
    // to the engine, the shell raises the window, and this is the half that
    // navigates. Mounted at the app root because the destination is any
    // screen — a watcher living in one route could only ever hand off to
    // itself. See lib/focus.ts.
    $effect(() => watchFocus());

    $effect(() => {
    });

    /* Saying that the page changed, and putting focus where it changed.
     *
     * A hash router replaces the contents of one document. A sighted reader
     * sees the swap; a screen reader is told nothing at all, because no
     * document load happened, and focus stays on whatever was clicked — in
     * the rail, three groups above the thing that just appeared. Both halves
     * are the same omission: navigation that the browser would have narrated
     * for free, now nobody's job.
     *
     * `.view` carries `tabindex="-1"` so it can receive focus without
     * entering the tab order, and it sits *outside* the `{#key}` so the
     * element focus lands on is not the one being replaced.
     */
    let viewEl = $state<HTMLElement | undefined>();
    let announced = $state("");

    // The first render is not a navigation. Stealing focus into the view on
    // load would drop the reader past the rail and the skip control before
    // they have heard either.
    let navigated = false;

    /* The container is the *fallback*, not the rule.
     *
     * This effect used to call `viewEl.focus()` unconditionally, which is
     * correct for a document and wrong for a prompt: the Console autofocuses
     * its input, we landed focus on the wrapping div instead, and the one
     * screen in the app whose whole purpose is typing became a screen you
     * could not type into. All 263 tests still passed, because none of them
     * asserted where focus goes.
     *
     * So a view that autofocuses a control is taken at its word. `[autofocus]`
     * is the declaration — already in the markup, already the thing Svelte
     * acts on, and it means "this is the element the reader wants", which is
     * exactly the question being asked here. Reading it beats both a
     * hardcoded list of route names and a `document.activeElement` race.
     *
     * No current route claims `[autofocus]` — the Console that did was folded
     * into Agents, and the terminal panel that replaced *it* is gone too. The
     * check stays anyway: it costs one `querySelector` per navigation, and the
     * alternative is deleting the one thing standing between the next
     * typing-first route and the exact regression above.
     */
    function focusTheView() {
        if (!viewEl) return;
        const claimed = viewEl.querySelector<HTMLElement>("[autofocus]");
        (claimed ?? viewEl).focus();
    }

    $effect(() => {
        const name = $route.name;
        if (!navigated) {
            navigated = true;
            return;
        }
        announced = labelOf(name);
        focusTheView();
        // A route change resets scroll the way a real document load would —
        // the main.work container is reused across every route (App.svelte
        // is one page, not many), so without this a scroll position from the
        // screen just left carries over and the new one opens part-way down.
        const work = document.querySelector("main.work");
        if (work) work.scrollTop = 0;
    });

    // The URL is read once at startup (`ready` above). mode.ts's own comment
    // says a pasted link opens in the mode it was written for — that has to
    // hold for a link followed *inside* a running app too, not only on a
    // fresh load, or `?mode=author` in the address bar becomes a lie the
    // moment the reader is already here (check-20, knowledge-20, settings-15).
    $effect(() => {
        const wanted = $route.query.mode;
        // `mode.set`, not `setMode`: following a link is not the reader
        // saying "remember this as my mode" the way clicking the rail's
        // switch is, so this must not overwrite the stored preference.
        if (wanted && asMode(wanted) !== $mode) mode.set(asMode(wanted));
    });
</script>

<div class="shell">
    <!-- A button, not `<a href="#main">`: the app is hash-routed, so a URL
         fragment is an address here. `#main` would parse as the route `main`
         and the skip link would navigate to "No such view" — the one place
         where the standard accessible pattern is actively wrong. -->
    <button
        type="button"
        class="skip"
        onclick={() => {
            announced = labelOf($route.name);
            focusTheView();
        }}
    >
        Skip to content
    </button>

    <Sidebar mode={$mode} />
    <Palette mode={$mode} />

    <!-- Polite, and outside the keyed subtree: a live region that is itself
         replaced on navigation announces nothing, because the announcement
         and the element carrying it arrive in the same paint. -->
    <p class="sr-only" role="status" aria-live="polite">{announced}</p>

    <main class="work" class:with-history={showHistory}>
        <div class="view" bind:this={viewEl} tabindex="-1">
            {#await ready}
                <p class="state loading">Starting…</p>
            {:then}
                <!-- Keyed so a view arrives rather than swapping in place: at a
                     glance, an instant repaint of a same-shaped page is hard to
                     tell from nothing having happened. NextStep sits outside the
                     key because it is about the installation, not the page:
                     re-animating it on every navigation would be nagging. -->
                {#if !firstRun}
                    <NextStep mode={$mode} />
                {/if}
                {#key $route.name}
                    <div class="enter">
                    {#if firstRun}
                        <Welcome
                            onDone={() => {
                                dismissed = true;
                                void api.status().then((s) => (empty = s.packs === 0));
                            }}
                        />
                    {:else if authorOnly}
                        <!-- Named by the rail's own label, not the route id
                             (shell-11, knowledge-31, settings-15) — "packs is
                             an author view" tells a reader nothing they can
                             act on, and at a short window the rail's own mode
                             switch can be scrolled out of reach, so the way
                             back has to be right here. -->
                        <EmptyState
                            title="{labelOf($route.name)} is for pack authors"
                            detail="It is real work a pack author does, and none of it helps
                                    someone deciding whether to go and look at a listing."
                            actionLabel="Switch to author mode"
                            onAction={() => setMode("author")}
                        />
                    {:else if $route.name === "welcome"}
                        <!-- #/welcome is the reopening address for the offer
                             firstRun shows automatically — a reader who
                             pressed Skip, or a link that wants to point
                             someone at "install a pack" again, needs a real
                             destination rather than "No such view" (shell-21,
                             settings-14). -->
                        <Welcome
                            onDone={() => {
                                dismissed = true;
                                void api.status().then((s) => (empty = s.packs === 0));
                            }}
                        />
                    {:else if $route.name === "check"}
                        <Check mode={$mode} />
                    {:else if $route.name === "overview"}
                        <Overview />
                    {:else if view.name === "knowledge"}
                        <Knowledge
                            lens={view.lens ?? $route.query.lens ?? "all"}
                            subjectId={$route.params[0] ?? ""}
                        />
                    {:else if $route.name === "history"}
                        <h2>History</h2>
                        <History page />
                    {:else if $route.name === "compare"}
                        <Compare />
                    {:else if $route.name === "questions"}
                        <!-- The id rides in the query rather than the path so
                             the rail's own entry (no id at all) is the same
                             route, and resolves to the newest saved answer.

                             A path segment is accepted as well, and only for
                             one caller: the browser extension hands a route
                             to `/api/focus`, which refuses a query string on
                             purpose (a closed route shape is what makes an
                             address posted by a web page safe to act on). So
                             `questions/<id>` is the same destination spelled
                             in the alphabet that handoff allows. -->
                        {#key $route.params[0] ?? $route.query.id ?? ""}
                            <Questions
                                lookupId={$route.params[0] ?? $route.query.id ?? ""}
                            />
                        {/key}
                    {:else if $route.name === "extension"}
                        <Extension />
                    {:else if $route.name === "packs"}
                        <Packs />
                    {:else if $route.name === "sites"}
                        <!-- Which listing sites can be read here, and the one
                             button that turns "the extension does nothing on
                             this page" into a site Kriko knows. -->
                        <Sites />
                    {:else if $route.name === "settings"}
                        <Settings />
                    {:else if $route.name === "about"}
                        <About />
                    {:else if view.name === "activity"}
                        <!-- Runs, the pipeline and what researchers sent, as
                             three lenses on one screen. `#/jobs`,
                             `#/pipeline` and `#/submissions` are links this
                             app's own responses and hints hand out, so they
                             resolve here rather than to "No such view" — same
                             contract as the Knowledge lenses above. -->
                        <Activity
                            lens={view.lens ?? $route.query.lens ?? "live"}
                        />
                    {:else if view.name === "agents"}
                        <Agents />
                    {:else if $route.name === "bench"}
                        <Bench />
                    {:else if $route.name === "result"}
                        <!-- Keyed: Result fetches once on init, so moving between two
                             stored results must remount rather than reuse. -->
                        {#key $route.params[0]}
                            <Result lookupId={$route.params[0]} mode={$mode} />
                        {/key}
                    {:else}
                        <EmptyState
                            title="No such view: {$route.name}"
                            detail="The link may be from an older version."
                            actionLabel="Go to New check"
                            actionHref={hashWith({ mode: $route.query.mode }, "check")}
                        />
                    {/if}
                    </div>
                {/key}
            {/await}
        </div>
        {#if showHistory}
            {#key $route.params[0] ?? $route.name}
                <History />
            {/key}
        {/if}
    </main>
</div>
