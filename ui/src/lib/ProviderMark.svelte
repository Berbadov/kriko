<script lang="ts">
    import { markFor } from "./providers";

    /* A small monochrome mark for a provider, drawn inline (B175, D2).
     *
     * Inline and on `currentColor` for the reason `Icon.svelte` gives: no
     * network, no extra file paths, and the surrounding text colours it. These
     * are simplified glyphs that stand for a vendor, not a copy of its
     * published artwork; swapping in the official files later changes this
     * one table and nothing that uses it. `name` is whatever text the API
     * gave (a harness id, an LLM name) and `markFor` does the reading.
     */
    let { name, size = 16 }: { name: string; size?: number } = $props();

    const id = $derived(markFor(name));
</script>

<svg
    class="provider-mark"
    data-mark={id}
    viewBox="0 0 24 24"
    width={size}
    height={size}
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
>
    {#if id === "anthropic"}
        <path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9" stroke-width="2.4" />
    {:else if id === "google"}
        <path
            d="M12 2.5c.6 5.2 4.3 8.9 9.5 9.5-5.2.6-8.9 4.3-9.5 9.5-.6-5.2-4.3-8.9-9.5-9.5 5.2-.6 8.9-4.3 9.5-9.5z"
            fill="currentColor"
            stroke="none"
        />
    {:else if id === "openai"}
        <path d="M12 2.8 20 7.4v9.2L12 21.2 4 16.6V7.4z" />
        <path d="M12 8 16 10.3v3.4L12 16l-4-2.3v-3.4z" />
    {:else if id === "mistral"}
        <path
            d="M3.5 4h4v4h-4zM16.5 4h4v4h-4zM3.5 10h4v4h-4zM9.5 10h5v4h-5zM16.5 10h4v4h-4zM3.5 16h4v4h-4zM16.5 16h4v4h-4z"
            fill="currentColor"
            stroke="none"
        />
    {:else if id === "github"}
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="2.6" fill="currentColor" stroke="none" />
    {:else if id === "opencode"}
        <path d="M8.5 5 3.5 12l5 7M15.5 5l5 7-5 7" />
    {:else}
        <rect x="4" y="4" width="16" height="16" rx="4" />
    {/if}
</svg>

<style>
    .provider-mark {
        flex: none;
        vertical-align: -0.2em;
    }
</style>
