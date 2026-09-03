<script lang="ts">
    let {
        title,
        detail = "",
        actionLabel = "",
        actionHref = "",
        onAction,
    }: {
        title: string;
        detail?: string;
        actionLabel?: string;
        actionHref?: string;
        onAction?: () => void;
    } = $props();
</script>

<!-- An empty screen is a state, not an absence. "No coverage gaps" and
     "nothing asked yet" lead a reader to opposite next steps, and a bare grey
     sentence tells them neither. -->
<div class="empty-state">
    <p class="empty-title">{title}</p>
    {#if detail}<p class="meta">{detail}</p>{/if}
    {#if actionLabel && actionHref}
        <a class="tab" href={actionHref}>{actionLabel}</a>
    {:else if actionLabel && onAction}
        <button onclick={onAction}>{actionLabel}</button>
    {/if}
</div>
