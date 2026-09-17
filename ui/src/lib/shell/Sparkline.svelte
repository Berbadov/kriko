<script lang="ts">
    /* A line with no axes, no grid and no legend, sized to sit beside a figure.
     *
     * It is not a chart and must not grow into one. Its whole job is to say
     * whether the number next to it has been climbing, and a sparkline that
     * earns a tooltip has outgrown the rail it lives in — the row is a link,
     * and a hover layer inside a link fights the thing the reader is
     * actually pointing at. The accessible name carries the shape instead.
     *
     * Single series, so no legend: the figure beside it is the direct label,
     * which is the rule for one series. The stroke is the accent because
     * there is nothing for it to be distinguished *from*; the moment a second
     * series appears here, this component is the wrong one.
     *
     * Drawn in a normalised 0..1 box and stretched by the viewBox with
     * `vector-effect`, so the stroke stays 2px at any width the rail gives it
     * rather than scaling into a wedge.
     */
    let {
        values,
        label = "",
        width = 48,
        height = 16,
    }: {
        values: number[];
        label?: string;
        width?: number;
        height?: number;
    } = $props();

    // Two points or it is not a shape. A single reading drawn as a flat line
    // reads as "no change", which is more than one number can support.
    const points = $derived(values.filter((one) => Number.isFinite(one)));
    const enough = $derived(points.length > 1);

    const path = $derived.by(() => {
        if (!enough) return "";
        const low = Math.min(...points);
        const high = Math.max(...points);
        // A flat series has no range to divide by; draw it down the middle
        // rather than at the top, which is what a zero span would produce.
        const span = high - low || 1;
        const flat = high === low;
        return points
            .map((value, index) => {
                const x = index / (points.length - 1);
                const y = flat ? 0.5 : 1 - (value - low) / span;
                return `${index ? "L" : "M"}${x.toFixed(4)} ${y.toFixed(4)}`;
            })
            .join(" ");
    });

    const last = $derived(enough ? points[points.length - 1] : 0);
    const first = $derived(enough ? points[0] : 0);

    /* Where the line ends, in the same normalised box the path is drawn in.
     * Computed rather than read back off the path string: parsing your own
     * output is a bug waiting for the day the format changes. */
    const endY = $derived.by(() => {
        if (!enough) return 0.5;
        const low = Math.min(...points);
        const high = Math.max(...points);
        return high === low ? 0.5 : 1 - (last - low) / (high - low);
    });
    const direction = $derived(
        !enough ? "" : last > first ? "rising" : last < first ? "falling" : "level",
    );
</script>

{#if enough}
    <svg
        class="spark"
        {width}
        {height}
        viewBox="0 0 1 1"
        preserveAspectRatio="none"
        role="img"
        aria-label={label ? `${label}, ${direction}` : direction}
    >
        <path d={path} vector-effect="non-scaling-stroke" />
        <!-- The last point, because "where it ended" is the half of a
             sparkline a reader actually reads.
             A zero-length line with a round cap rather than a `<circle>`: the
             box is normalised and three times wider than it is tall, so a
             radius in user units draws an ellipse. A non-scaling stroke is
             round whatever the box does to it. -->
        <line
            class="end"
            x1="1"
            y1={endY}
            x2="1"
            y2={endY}
            vector-effect="non-scaling-stroke"
        />
    </svg>
{/if}

<style>
    .spark {
        display: block;
        overflow: visible;
    }

    .spark path {
        fill: none;
        stroke: var(--accent);
        stroke-width: 2;
        stroke-linecap: round;
        stroke-linejoin: round;
    }

    .spark .end {
        stroke: var(--accent);
        stroke-width: 5;
        stroke-linecap: round;
    }

    @media (prefers-reduced-motion: no-preference) {
        .spark {
            transition: opacity 120ms ease;
        }
    }
</style>
