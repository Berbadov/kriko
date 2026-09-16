<script lang="ts">
    import NavIcon from "./NavIcon.svelte";
    import Sparkline from "./Sparkline.svelte";
    import type { Figure } from "./figures";
    import type { NavGroupSpec } from "./nav";

    let {
        group,
        current,
        href,
        figures = {},
    }: {
        group: NavGroupSpec;
        current: string;
        href: (name: string) => string;
        /* Keyed by route name, and absent for most of them. A row with no
         * entry renders exactly what it rendered before this existed — which
         * is what keeps a failed poll from reshaping the rail. */
        figures?: Record<string, Figure>;
    } = $props();
</script>

<div class="nav-group">
    <!-- The buyer's single group is unlabelled: one heading over one list of
         two is noise, and there is nothing for it to distinguish from. -->
    {#if group.authorOnly}
        <p class="nav-title">{group.title}</p>
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
