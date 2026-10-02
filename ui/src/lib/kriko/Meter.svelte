<script lang="ts">
    interface Props {
        /** 0 to 100 */
        value: number;
        segments?: number;
        slim?: boolean;
        /** Blink the leading segment while the run is live. */
        live?: boolean;
    }
    let { value, segments = 24, slim = false, live = false }: Props = $props();
    const lit = $derived(Math.round((segments * Math.min(100, Math.max(0, value))) / 100));
</script>

<span class="k-meter" class:slim role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
    {#each { length: segments } as _, i (i)}<i class:on={i < lit} class:head={live && i === lit - 1}></i>{/each}
</span>
