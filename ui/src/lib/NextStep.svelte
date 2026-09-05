<script lang="ts">
    import { api } from "./api";
    import { nextStep, type Step } from "./nextStep";
    import { hashWith, route } from "./router";

    // Guidance must never be an error surface. Every call here is optional and
    // every failure resolves to a neutral value: if the engine is unwell the
    // reader should be told that by Health, not by a hint bar that has turned
    // into a stack trace.
    let step = $state<Step | null>(null);
    let dismissed = $state(false);

    const load = async () => {
        const [status, updates, targets, history, extension] = await Promise.all([
            api.status().catch(() => null),
            api.packUpdates().catch(() => null),
            api.agentTargets().catch(() => null),
            api.history(1).catch(() => null),
            api.extension().catch(() => null),
        ]);
        if (!status) return;
        const packs = await api.packs().catch(() => []);
        const gapLists = await Promise.all(
            packs.map((pack) => api.gaps(pack.pack_id).catch(() => [])),
        );
        step = nextStep({
            packs: status.packs,
            enabled: status.enabled_packs,
            gaps: gapLists.flat().length,
            agentsConnected: (targets?.targets ?? []).filter(
                (t) => t.state === "connected",
            ).length,
            agentsKnown: (targets?.targets ?? []).length,
            updatable: (updates?.packs ?? []).filter((p) => p.state === "available")
                .length,
            checks: (history?.items ?? []).length,
            // Null, not false, when the status could not be read or this build
            // carries no extension: a suggestion to install something that is
            // not there would be the hint bar lying.
            extensionConnected:
                extension && extension.available ? extension.connected : null,
        });
    };
    void load();
</script>

{#if step && !dismissed}
    <aside class="nextstep enter" aria-label="Suggested next step">
        <div>
            <strong>{step.title}</strong>
            <span class="meta">{step.detail}</span>
        </div>
        <div class="nextstep-do">
            <a class="tab" href={hashWith({ mode: $route.query.mode }, step.route)}>
                {step.action}
            </a>
            <button
                class="ghost"
                onclick={() => (dismissed = true)}
                aria-label="Dismiss this suggestion">Not now</button
            >
        </div>
    </aside>
{/if}
