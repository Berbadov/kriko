<script lang="ts">
    import type { BenchPoint } from "./bench";
    import { formatInterval, formatPct, formatUsd, hallucinationSeverity, plottable } from "./bench";

    let { llm, points }: { llm: string; points: BenchPoint[] } = $props();

    const WIDTH = 340;
    const HEIGHT = 210;
    const PAD_LEFT = 46;
    const PAD_RIGHT = 16;
    const PAD_TOP = 16;
    const PAD_BOTTOM = 40;
    const PLOT_W = WIDTH - PAD_LEFT - PAD_RIGHT;
    const PLOT_H = HEIGHT - PAD_TOP - PAD_BOTTOM;

    function niceMax(value: number): number {
        if (value <= 0) return 1;
        const magnitude = 10 ** Math.floor(Math.log10(value));
        for (const step of [1, 2, 2.5, 5, 10]) {
            const candidate = step * magnitude;
            if (candidate >= value * 1.001) return candidate;
        }
        return 10 * magnitude;
    }

    const shown = $derived(plottable(points));
    const skipped = $derived(points.length - shown.length);

    const xMax = $derived(
        niceMax(
            Math.max(
                0.001,
                ...shown.map((point) => (point.hallucinationInterval?.[1] ?? point.hallucinationRate) * 100),
            ),
        ),
    );
    const yMax = $derived(
        niceMax(Math.max(0.0001, ...shown.map((point) => point.usdPerAcceptedClaim ?? 0))),
    );

    const xAt = (pct: number) => PAD_LEFT + (pct / xMax) * PLOT_W;
    const yAt = (usd: number) => PAD_TOP + PLOT_H - (usd / yMax) * PLOT_H;

    const xTicks = $derived([0, xMax / 2, xMax]);
    const yTicks = $derived([0, yMax / 2, yMax]);
</script>

<figure class="bench-chart">
    <figcaption>{llm}</figcaption>
    {#if !shown.length}
        <p class="state empty">
            {points.length
                ? "Every measured protocol here is missing a priced run, so cost cannot be plotted."
                : "No graded run for this LLM yet."}
        </p>
    {:else}
        <svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{llm}: cost per accepted claim against hallucination rate, by protocol">
            {#each yTicks as tick, i (i)}
                <line
                    class="grid"
                    x1={PAD_LEFT}
                    x2={WIDTH - PAD_RIGHT}
                    y1={yAt(tick)}
                    y2={yAt(tick)}
                />
                <text class="tick" x={PAD_LEFT - 6} y={yAt(tick)} text-anchor="end" dominant-baseline="middle">
                    {formatUsd(tick, tick < 0.01 ? 4 : 2)}
                </text>
            {/each}
            {#each xTicks as tick, i (i)}
                <text class="tick" x={xAt(tick)} y={HEIGHT - PAD_BOTTOM + 14} text-anchor="middle">
                    {tick.toFixed(tick < 1 ? 1 : 0)}%
                </text>
            {/each}
            <line class="axis" x1={PAD_LEFT} x2={PAD_LEFT} y1={PAD_TOP} y2={HEIGHT - PAD_BOTTOM} />
            <line
                class="axis"
                x1={PAD_LEFT}
                x2={WIDTH - PAD_RIGHT}
                y1={HEIGHT - PAD_BOTTOM}
                y2={HEIGHT - PAD_BOTTOM}
            />
            <text class="axis-label" x={(PAD_LEFT + WIDTH - PAD_RIGHT) / 2} y={HEIGHT - 4} text-anchor="middle">
                Hallucination rate
            </text>
            <text
                class="axis-label"
                x={-(PAD_TOP + PLOT_H / 2)}
                y="12"
                text-anchor="middle"
                transform="rotate(-90)"
            >
                Cost / accepted claim
            </text>

            {#each shown as point (point.protocol)}
                {@const cx = xAt(point.hallucinationRate * 100)}
                {@const cy = yAt(point.usdPerAcceptedClaim ?? 0)}
                {@const severity = hallucinationSeverity(point.hallucinationRate)}
                <title>
                    {point.protocol} — batch {point.batchSize}, {point.contextChars.toLocaleString()}
                    chars{point.preamble ? `, ${point.preamble} preamble` : ""}. {formatPct(
                        point.hallucinationRate,
                    )} hallucinated{point.hallucinationInterval
                        ? ` (${formatInterval(point.hallucinationInterval)} interval)`
                        : ""}, {formatUsd(point.usdPerAcceptedClaim)} per accepted claim over {point.runs}
                    run{point.runs === 1 ? "" : "s"}.{point.chosen ? " Chosen protocol." : ""}
                </title>
                {#if point.hallucinationInterval}
                    {@const lo = xAt(point.hallucinationInterval[0] * 100)}
                    {@const hi = xAt(point.hallucinationInterval[1] * 100)}
                    <line class="whisker" x1={lo} x2={hi} y1={cy} y2={cy} />
                    <line class="whisker" x1={lo} x2={lo} y1={cy - 3} y2={cy + 3} />
                    <line class="whisker" x1={hi} x2={hi} y1={cy - 3} y2={cy + 3} />
                {/if}
                <circle
                    class="mark {severity}"
                    class:chosen={point.chosen}
                    cx={cx}
                    cy={cy}
                    r={point.chosen ? 6 : 4}
                />
            {/each}
        </svg>
        {#if skipped}
            <p class="meta">
                {skipped} more protocol{skipped === 1 ? "" : "s"} measured for {llm}, without enough
                priced runs to place on this chart — see the table above.
            </p>
        {/if}
        <p class="meta legend">
            <span class="swatch low"></span> ≤5% hallucinated
            <span class="swatch medium"></span> ≤15%
            <span class="swatch high"></span> above 15% ·
            <span class="swatch-ring"></span> filled = protocol this install uses today
        </p>
        <details>
            <summary>Table</summary>
            <table>
                <thead>
                    <tr>
                        <th scope="col">Protocol</th>
                        <th scope="col" class="num">Batch</th>
                        <th scope="col" class="num">Context</th>
                        <th scope="col" class="num">Hallucination</th>
                        <th scope="col" class="num">Cost / claim</th>
                        <th scope="col" class="num">Runs</th>
                    </tr>
                </thead>
                <tbody>
                    {#each points as point (point.protocol)}
                        <tr>
                            <th scope="row">{point.protocol}{point.chosen ? " (chosen)" : ""}</th>
                            <td class="num">{point.batchSize}</td>
                            <td class="num">{point.contextChars.toLocaleString()}</td>
                            <td class="num">
                                {formatPct(point.hallucinationRate)}
                                {#if point.hallucinationInterval}
                                    <span class="meta">({formatInterval(point.hallucinationInterval)})</span>
                                {/if}
                            </td>
                            <td class="num">{formatUsd(point.usdPerAcceptedClaim)}</td>
                            <td class="num">{point.runs}</td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </details>
    {/if}
</figure>

<style>
    .bench-chart {
        margin: 0;
        padding: var(--s-3);
        border: 1px solid var(--line);
        border-radius: var(--radius-sm);
        background: var(--panel);
    }
    figcaption {
        font-size: var(--t-sm);
        font-weight: 600;
        margin-block-end: var(--s-2);
    }
    svg {
        width: 100%;
        height: auto;
        overflow: visible;
    }
    .grid {
        stroke: var(--line);
        stroke-width: 1;
    }
    .axis {
        stroke: var(--dim);
        stroke-width: 1;
    }
    .tick,
    .axis-label {
        fill: var(--dim);
        font-size: 9px;
    }
    .whisker {
        stroke: var(--dim);
        stroke-width: 2;
        stroke-linecap: round;
    }
    .mark {
        stroke-width: 2;
    }
    .mark.low {
        stroke: var(--low);
    }
    .mark.medium {
        stroke: var(--medium);
    }
    .mark.high {
        stroke: var(--high);
    }
    .mark:not(.chosen) {
        fill: var(--panel);
    }
    .mark.chosen.low {
        fill: var(--low);
    }
    .mark.chosen.medium {
        fill: var(--medium);
    }
    .mark.chosen.high {
        fill: var(--high);
    }
    .legend {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--s-1);
    }
    .swatch,
    .swatch-ring {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 999px;
        margin-inline-start: var(--s-2);
    }
    .swatch.low {
        background: var(--low);
    }
    .swatch.medium {
        background: var(--medium);
    }
    .swatch.high {
        background: var(--high);
    }
    .swatch-ring {
        background: var(--panel);
        border: 2px solid var(--dim);
    }
    details {
        margin-block-start: var(--s-2);
    }
</style>
