<script lang="ts">
    import { MODES, setMode, type Mode } from "../mode";
    import { hashWith, route } from "../router";
    import NavGroup from "./NavGroup.svelte";
    import { groupsFor } from "./nav";

    let { mode }: { mode: Mode } = $props();

    const groups = $derived(groupsFor(mode));

    // Every rail link carries the mode, and it comes from the prop rather than
    // from the URL: the URL may legitimately omit it — a first visit reads the
    // remembered setting — and a link that drops it looks like the app
    // switching modes on its own.
    const href = (name: string) => hashWith({ mode }, name);
</script>

<aside class="rail">
    <a class="brand" href={href("check")}>
        <!-- The extension's toolbar icon, the same file the installer's
             app icon is rendered from. The reader met this product in a
             browser toolbar; a different mark here reads as a different
             tool. -->
        <!-- `/static/`, not `/`: Vite's base is /static/ because FastAPI
             mounts StaticFiles there, so a root-relative path to a
             public/ asset falls through to the SPA catch-all and the mark
             renders as a broken image. Guarded by public-assets.test.ts. -->
        <img class="mark" src="/static/mark.svg" alt="" width="28" height="28" />
        <span class="brand-text">
            <strong>Kriko</strong>
            <span class="meta">local product knowledge</span>
        </span>
    </a>

    <nav class="rail-nav">
        {#each groups as group (group.title)}
            <NavGroup {group} current={$route.name} {href} />
        {/each}
    </nav>

    <div class="rail-foot">
        <span class="modes" role="group" aria-label="Mode">
            {#each MODES as candidate (candidate)}
                <button
                    class="tab"
                    class:active={mode === candidate}
                    onclick={() => setMode(candidate as Mode)}>{candidate}</button
                >
            {/each}
        </span>
    </div>
</aside>
