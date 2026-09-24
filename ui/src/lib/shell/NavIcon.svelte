<script lang="ts">
    /* One 20px glyph per destination in the rail.
     *
     * The table itself lives in `lib/Icon.svelte` now — it stopped being a
     * rail-only concern the moment the Agents screen wanted the same
     * glyphs, and two copies of path data is two copies to keep in step.
     * What stays here is the one thing the rail owns: the `.nav-icon`
     * class, which `styles/components.css` dims until the row matters and
     * brightens on hover and on the active link. Keeping this wrapper means
     * that rule, and `NavGroup`'s single use of `<NavIcon {name} />`, did
     * not have to change at all.
     */
    import Icon from "../Icon.svelte";

    let { name }: { name: string } = $props();
</script>

<Icon {name} class="nav-icon" />
