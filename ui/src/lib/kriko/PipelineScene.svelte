<script lang="ts">
    import { onMount } from "svelte";
    import { prefersReducedMotion } from "../motion";
    import {
        REDUCED_FRAME_SECONDS,
        SCENE_HEIGHT,
        SCENE_WIDTH,
        paletteFrom,
        sceneOps,
        stageAt,
        type Op,
        type Stage,
    } from "./pipelineScene";

    /* The agent pipeline, drawn on a 360 by 132 canvas and scaled up with
     * nearest-neighbour so each drawn pixel stays a square (Motion.md). It loops
     * every ten seconds and pauses while the tab is hidden or the scene is off
     * screen. Under reduced motion it draws its one stable frame and stops.
     * The brand flash marks the moment the run is committed, once per loop. */

    let canvas = $state<HTMLCanvasElement>();
    let caption = $state(stageAt(0).caption);
    let flashes = $state(0);

    const FRAME_MS = 1000 / 30;

    onMount(() => {
        const ctx = canvas?.getContext("2d", { willReadFrequently: true });
        if (!canvas || !ctx) return;

        const style = getComputedStyle(document.documentElement);
        const palette = paletteFrom((token) => style.getPropertyValue(`--${token}`).trim());
        const reduced = prefersReducedMotion();

        let previous: Stage | null = null;
        const paint = (t: number) => {
            const { stage, caption: text } = stageAt(t);
            caption = text;
            draw(ctx, sceneOps(t, reduced, palette));
            if (previous === "write" && stage === "done" && !reduced) flashes++;
            previous = stage;
        };

        if (reduced) {
            paint(REDUCED_FRAME_SECONDS);
            return;
        }

        let clock = 0;
        let last = performance.now();
        let lastPaint = -Infinity;
        let frame = 0;
        let visible = true;
        const running = () => visible && !document.hidden;

        const schedule = () => {
            if (!frame && running()) frame = requestAnimationFrame(tick);
        };
        const tick = (now: number) => {
            frame = 0;
            if (!running()) return;
            clock += Math.min(0.1, (now - last) / 1000);
            last = now;
            if (now - lastPaint >= FRAME_MS) {
                lastPaint = now;
                paint(clock);
            }
            schedule();
        };

        // Resuming must not replay the time the scene spent paused.
        const onVisibility = () => {
            last = performance.now();
            schedule();
        };
        document.addEventListener("visibilitychange", onVisibility);
        const watch =
            typeof IntersectionObserver === "undefined"
                ? null
                : new IntersectionObserver(([entry]) => {
                      visible = entry.isIntersecting;
                      if (visible) last = performance.now();
                      schedule();
                  });
        watch?.observe(canvas);

        paint(clock);
        schedule();
        return () => {
            cancelAnimationFrame(frame);
            watch?.disconnect();
            document.removeEventListener("visibilitychange", onVisibility);
        };
    });

    /** Paint the ops far to near, then set every pixel either in or out: the
     * scene is pixel art, so a half-covered pixel is not allowed to exist. */
    function draw(ctx: CanvasRenderingContext2D, ops: Op[]) {
        ctx.clearRect(0, 0, SCENE_WIDTH, SCENE_HEIGHT);
        for (const op of ops) {
            if (op.kind === "poly") {
                ctx.beginPath();
                op.pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
                ctx.closePath();
                ctx.fillStyle = op.fill;
                ctx.fill();
                if (op.stroke) {
                    ctx.strokeStyle = op.stroke;
                    ctx.lineWidth = 1;
                    ctx.stroke();
                }
            } else if (op.kind === "seg") {
                ctx.strokeStyle = op.c;
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(op.a[0], op.a[1]);
                ctx.lineTo(op.b[0], op.b[1]);
                ctx.stroke();
            } else {
                ctx.fillStyle = op.c;
                ctx.fillRect(
                    Math.round(op.x - op.size / 2),
                    Math.round(op.y - op.size / 2),
                    op.size,
                    op.size,
                );
            }
        }
        const image = ctx.getImageData(0, 0, SCENE_WIDTH, SCENE_HEIGHT);
        const pixels = image.data;
        for (let i = 3; i < pixels.length; i += 4) pixels[i] = pixels[i] > 110 ? 255 : 0;
        ctx.putImageData(image, 0, 0);
    }
</script>

<figure class="pipeline">
    <div
        class="stage"
        role="img"
        aria-label="Animated agent pipeline: a web globe, a page being scanned, claims lifted out and written to a SQLite cylinder"
    >
        <canvas bind:this={canvas} aria-hidden="true" width={SCENE_WIDTH} height={SCENE_HEIGHT}></canvas>
        {#key flashes}
            {#if flashes}<span class="scene-flash" aria-hidden="true"></span>{/if}
        {/key}
    </div>
    <figcaption class="caption">{caption}</figcaption>
</figure>

<style>
    .pipeline {
        margin: 0;
    }
    .stage {
        position: relative;
        width: 100%;
        max-width: 720px;
        aspect-ratio: 360 / 132;
        overflow: hidden;
        border-radius: var(--radius);
        background: var(--n-0);
    }
    canvas {
        display: block;
        width: 100%;
        height: 100%;
        image-rendering: pixelated;
    }
    .caption {
        margin-top: var(--s-2);
        font-family: var(--font-mono);
        font-size: var(--t-xs);
        color: var(--dim);
    }
</style>
