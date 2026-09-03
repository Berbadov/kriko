<script lang="ts">
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
                <a
                    class="nav-link"
                    class:active={current === item.name}
                    aria-current={current === item.name ? "page" : undefined}
                    href={href(item.name)}>{item.label}</a
                >
            </li>
        {/each}
    </ul>
</div>
