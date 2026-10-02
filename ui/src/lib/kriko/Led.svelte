<script lang="ts">
    /** A dot-matrix of lit and unlit squares. Style tokens: --led (colour),
     * --dot, --gap, --glow. */
    interface Props {
        rows: string[];
        anim?: "boot" | "blink";
    }
    let { rows, anim }: Props = $props();
    const cols = $derived(rows[0]?.length ?? 0);
    const cells = $derived(
        rows.flatMap((r, y) => [...r].map((ch, x) => ({ on: ch === "#", i: x + y * cols }))),
    );
</script>

<span
    class="k-led"
    class:boot={anim === "boot"}
    data-anim={anim === "blink" ? "blink" : undefined}
    style:--cols={cols}
    aria-hidden="true"
>
    {#each cells as c (c.i)}<i class:on={c.on} style:--i={c.i}></i>{/each}
</span>
