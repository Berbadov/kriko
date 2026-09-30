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
        titled = true,
    }: {
        group: NavGroupSpec;
        current: string;
        href: (name: string) => string;
        /* Keyed by route name, and absent for most of them. A row with no
         * entry renders exactly what it rendered before this existed — which
         * is what keeps a failed poll from reshaping the rail. */
        figures?: Record<string, Figure>;
        /* Whether the group's title is drawn. The rail says yes whenever it
         * shows more than one group; a lone group has nothing to be told
         * apart from, so a heading over one list would be noise. */
        titled?: boolean;
    } = $props();
</script>

<div class="nav-group">
    <!-- Every group is titled once the rail shows more than one, and each
         title carries its symbol (B159). Until then only the author-only
         groups were, which left "Check" and "This install" as bare runs of
         rows with nothing to hang a symbol on. -->
    {#if titled}
        <p class="nav-title">
            <Icon name={group.symbol} size={14} class="nav-title-icon" />
            {group.title}
        </p>
    {/if}
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
</div>
