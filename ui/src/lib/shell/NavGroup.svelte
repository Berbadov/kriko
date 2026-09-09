<script lang="ts">
    import NavIcon from "./NavIcon.svelte";
    import type { NavGroupSpec } from "./nav";

    let {
        group,
        current,
        href,
    }: {
        group: NavGroupSpec;
        current: string;
        href: (name: string) => string;
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
                </a>
            </li>
        {/each}
    </ul>
</div>
