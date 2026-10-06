<script lang="ts">
    /* The design system's page frame: a mono
     * crumb line, the display title, a one-line lead. Every screen wears it
     * so the rail is not the only thing saying where the reader is. */
    let {
        crumb,
        title,
        lead = "",
    }: { crumb: string; title: string; lead?: string } = $props();
</script>

<div class="k-crumb">kriko / <b>{crumb}</b></div>
<h1 class="k-title">{title}</h1>
{#if lead}<p class="k-lead">{lead}</p>{/if}
