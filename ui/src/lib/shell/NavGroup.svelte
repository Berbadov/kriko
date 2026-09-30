<script lang="ts">
    import Icon from "../Icon.svelte";
    import NavIcon from "./NavIcon.svelte";
    import Sparkline from "./Sparkline.svelte";
    import type { Figure } from "./figures";
    import type { NavGroupSpec } from "./nav";

    let {
        group,
        current,
        href,
        figures = {},
        folded = false,
        locked = false,
        ontoggle = () => {},
    }: {
        group: NavGroupSpec;
        current: string;
        href: (name: string) => string;
        /* Keyed by route name, and absent for most of them. A row with no
         * entry renders exactly what it rendered before this existed — which
         * is what keeps a failed poll from reshaping the rail. */
        figures?: Record<string, Figure>;
        /* A foldable group's rows are hidden while this is true (B167). */
        folded?: boolean;
        /* The group holds the open screen, so it cannot fold: the reader would
         * lose the row they are standing on. The title says so rather than
         * looking dead. */
        locked?: boolean;
        ontoggle?: () => void;
    } = $props();
</script>

<div class="nav-group">
    <!-- Every group is titled, and each title carries its symbol (B159). The
         rail always shows all four (B165), so there is no lone group to leave
         bare. -->
    {#if group.foldable}
        <!-- A tab for its rows (B167): a real button, so Enter and Space work
             and it is in the Tab order. `aria-expanded` is what is on screen,
             which for a locked group is always open. -->
        <button
            type="button"
            class="nav-title nav-fold"
            aria-expanded={!folded}
            aria-disabled={locked ? "true" : undefined}
            title={locked ? "Holds the open screen" : undefined}
            onclick={() => {
                if (!locked) ontoggle();
            }}
        >
            <Icon name={group.symbol} size={14} class="nav-title-icon" />
            <span class="nav-title-text">{group.title}</span>
            <Icon name="chevron" size={12} class="nav-fold-chevron" />
        </button>
    {:else}
        <p class="nav-title">
            <Icon name={group.symbol} size={14} class="nav-title-icon" />
            {group.title}
        </p>
    {/if}
    {#if !folded}
    <ul>
        {#each group.items as item (item.name)}
            <li>
                <!-- `data-route` carries the row's own name so the rail's
                     marker can be *told* which row to sit on, rather than
                     hunting for an `.active` class this component may not
                     have applied yet. See lib/shell/mark.ts. -->
                <a
                    class="nav-link"
                    class:active={current === item.name}
                    data-route={item.name}
                    aria-current={current === item.name ? "page" : undefined}
                    href={href(item.name)}
                >
                    <NavIcon name={item.name} />
                    <span class="nav-label">{item.label}</span>
                    {#if figures[item.name]}
                        {@const figure = figures[item.name]}
                        <span class="nav-figure" class:live={figure.live}>
                            {#if figure.trail}
                                <Sparkline values={figure.trail} label={figure.title} />
                            {/if}
                            <!-- The title is on the text rather than the row:
                                 a tooltip covering the whole link would fire
                                 wherever the reader aims, including on the way
                                 to somewhere else. -->
                            <span class="nav-figure-text" title={figure.title}
                                >{figure.text}</span
                            >
                        </span>
                    {/if}
                </a>
            </li>
        {/each}
    </ul>
    {/if}
</div>
