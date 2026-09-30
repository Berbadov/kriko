<script lang="ts">
    import type { Day } from "./homeSeries";

    /* A bar per day, hand-drawn like `BenchChart.svelte`: no chart library
     * (B174). The label carries the total and the window, so the picture has
     * a text equivalent. */
    let {
        label,
        days,
        format = (n: number) => String(n),
    }: { label: string; days: Day[]; format?: (n: number) => string } = $props();

    const W = 360;
    const H = 120;
    const PAD_L = 4;
    const PAD_B = 18;
    const PLOT_H = H - PAD_B - 6;
    const max = $derived(Math.max(...days.map((d) => d.value), 0));
    const slot = $derived((W - PAD_L * 2) / days.length);
    const total = $derived(days.reduce((sum, d) => sum + d.value, 0));
</script>

<svg
    class="day-bars"
    viewBox="0 0 {W} {H}"
    role="img"
    aria-label="{label}: {format(total)} over the last {days.length} days"
>
    <line class="axis" x1={PAD_L} x2={W - PAD_L} y1={H - PAD_B} y2={H - PAD_B} />
    {#each days as d, i (d.day)}
        {@const h = max ? (d.value / max) * PLOT_H : 0}
        <rect
            class="bar"
            x={PAD_L + i * slot + slot * 0.15}
            y={H - PAD_B - h}
            width={slot * 0.7}
            height={h}
        ><title>{d.day}: {format(d.value)}</title></rect>
    {/each}
    <text class="tick" x={PAD_L} y={H - 4}>{days[0]?.day.slice(5)}</text>
    <text class="tick" x={W - PAD_L} y={H - 4} text-anchor="end">{days.at(-1)?.day.slice(5)}</text>
</svg>

<style>
    .day-bars {
        width: 100%;
        height: auto;
        display: block;
    }
    .axis {
        stroke: var(--line, currentColor);
        opacity: 0.6;
    }
    .bar {
        fill: var(--accent, currentColor);
    }
    .tick {
        fill: var(--dim, currentColor);
        font-size: 10px;
    }
</style>
