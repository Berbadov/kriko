<script lang="ts">
    import Connect from "./Connect.svelte";
    import Console from "./Console.svelte";

    /* The agent side of this app, in one place.
     *
     * Connect and Console were always halves of one thing. Connect wires a
     * harness to the MCP server, hands it the generated research skill, and
     * tells you whether it actually answers; the console is where you drive
     * the same API by hand when it does not — and where you check what the
     * agent did afterwards. Two rail entries made the reader choose between
     * them before they could know which one they needed, and the answer is
     * usually "both, in that order".
     *
     * Which is why the order here is fixed and the wiring lens is first: a
     * console against an installation with no connected harness is a prompt
     * with nothing on the other end.
     */

    type Lens = "connect" | "console";
    const LENSES: { id: Lens; label: string }[] = [
        { id: "connect", label: "Wiring" },
        { id: "console", label: "Console" },
    ];

    let { lens: initial = "connect" }: { lens?: string } = $props();
    let lens = $state<Lens>(
        (LENSES.some((l) => l.id === initial) ? initial : "connect") as Lens,
    );

    /* Mounted on first sight, then never unmounted.
     *
     * Two rules pull opposite ways. The console must survive a lens switch —
     * it holds scrollback and a half-typed line, and a reader who flips over
     * to check a config path expects to come back to their prompt, so it
     * cannot be behind an `{#if lens === ...}`. But it also carries
     * `autofocus`, and App.svelte hands focus to the `[autofocus]` control
     * inside the arriving view — so a console mounted-but-hidden underneath
     * the wiring lens would swallow the keyboard on a screen it is not even
     * showing.
     *
     * Mounting lazily and keeping it satisfies both: arriving at `#/console`
     * mounts it and the prompt takes focus as it should; arriving at
     * `#/agents` does not, and the console appears — once — the first time
     * the lens is chosen.
     */
    let consoleMounted = $state(initial === "console");
    $effect(() => {
        if (lens === "console") consoleMounted = true;
    });
</script>

<div class="lenses" role="tablist" aria-label="Agents">
    {#each LENSES as candidate (candidate.id)}
        <button
            class="tab"
            role="tab"
            aria-selected={lens === candidate.id}
            class:active={lens === candidate.id}
            onclick={() => (lens = candidate.id)}>{candidate.label}</button
        >
    {/each}
</div>

<!-- Not keyed, and that is the difference from Activity: the console holds
     scrollback and a half-typed line, and a reader who flips to the wiring
     lens to check a path expects to come back to what they were typing.
     `hidden` rather than `{#if}` for the same reason — an unmounted console
     is a cleared one. -->
<div hidden={lens !== "connect"}>
    <Connect />
</div>
{#if consoleMounted}
    <div hidden={lens !== "console"}>
        <Console />
    </div>
{/if}
