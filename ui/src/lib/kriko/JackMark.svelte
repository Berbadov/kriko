<script lang="ts">
    import { prefersReducedMotion } from "../motion";

    /* The loading mark: the K's two arms swing toward each other while the
     * screw nub slides back and the wing nut turns (Motion.md, the loader).
     * It is inline markup, not an asset, because the asset store strips the
     * animation out of an SVG file. Under reduced motion the animation
     * elements are not rendered at all, so the mark sits at rest. */
    const reduced = prefersReducedMotion();

    // One clip id per mark, so two loaders on one screen do not share a clip.
    const clip = `jack-clip-${Math.random().toString(36).slice(2, 8)}`;
    const keySplines = ".3 0 .2 1;.3 0 .2 1";
</script>

<svg class="jack" viewBox="0 0 72 100" aria-hidden="true" focusable="false">
    <defs>
        <clipPath id={clip}>
            <rect x="-30" y="0" width="132" height="100" />
        </clipPath>
    </defs>
    <g transform="translate(18 0)">
        <g
            clip-path="url(#{clip})"
            fill="none"
            stroke="currentColor"
            stroke-width="16"
            stroke-linejoin="miter"
            stroke-miterlimit="6"
        >
            <path d="M8 17V83" />
            <path d="M8 50L54 -16">
                {#if !reduced}
                    <animateTransform
                        attributeName="transform"
                        type="rotate"
                        values="0 8 50;-10 8 50;0 8 50"
                        dur="2.6s"
                        repeatCount="indefinite"
                        calcMode="spline"
                        keyTimes="0;0.5;1"
                        keySplines={keySplines}
                    />
                {/if}
            </path>
            <path d="M8 50L54 116">
                {#if !reduced}
                    <animateTransform
                        attributeName="transform"
                        type="rotate"
                        values="0 8 50;10 8 50;0 8 50"
                        dur="2.6s"
                        repeatCount="indefinite"
                        calcMode="spline"
                        keyTimes="0;0.5;1"
                        keySplines={keySplines}
                    />
                {/if}
            </path>
        </g>
        <path d="M-12 50H40" stroke="currentColor" stroke-width="5" fill="none" stroke-dasharray="3 2">
            {#if !reduced}
                <animate attributeName="stroke-dashoffset" values="0;-5" dur="0.35s" repeatCount="indefinite" />
            {/if}
        </path>
        <rect x="-18" y="36" width="6" height="28" fill="currentColor">
            {#if !reduced}
                <animate attributeName="y" values="36;44;36" dur="0.7s" repeatCount="indefinite" />
                <animate attributeName="height" values="28;12;28" dur="0.7s" repeatCount="indefinite" />
            {/if}
        </rect>
        <rect x="42" y="44" width="12" height="12" fill="currentColor">
            {#if !reduced}
                <animateTransform
                    attributeName="transform"
                    type="translate"
                    values="0 0;-8 0;0 0"
                    dur="2.6s"
                    repeatCount="indefinite"
                    calcMode="spline"
                    keyTimes="0;0.5;1"
                    keySplines={keySplines}
                />
            {/if}
        </rect>
    </g>
</svg>
