<script lang="ts">
    import { api } from "./api";
    import type { Mode } from "./mode";
    import { nextStep, type Step } from "./nextStep";
    import { hashWith, route } from "./router";

    let { mode = "author" as Mode }: { mode?: Mode } = $props();

    // Guidance must never be an error surface. Every call here is optional and
    // every failure resolves to a neutral value: if the engine is unwell the
    // reader should be told that by Health, not by a hint bar that has turned
    // into a stack trace.
    let step = $state<Step | null>(null);
    // The dismissal key from a previous run, read from app.sqlite rather than
    // held only in this component: a `$state(false)` here forgot "Not now"
    // the moment the reader closed the app, so the same suggestion — often
    // this one — greeted them on every launch no matter how many times they
    // had already declined it. Keyed by step id, not a bare flag, so
    // dismissing one suggestion does not silence a later, different one.
    const DISMISS_KEY = "nextstep_dismissed_id";
    let dismissedId = $state<string | null>(null);

    // Every field this hint bar reads except pack updates is local data.
    // Joining `packUpdates()` into the same Promise.all made a bar that is
    // mounted on every screen wait on a remote fetch too — up to the
    // server's own 15s timeout when the index was unreachable (B145
    // desktop-2). It resolves separately below and only ever *adds* an
    // "update available" suggestion once it lands; it never blocks or
    // retracts the ones local data already earned.
    let updatable = $state(0);
    let args: Parameters<typeof nextStep>[0] | null = null;

    const load = async () => {
        const [status, targets, history, extension, settings] = await Promise.all([
            api.status().catch(() => null),
            api.agentTargets().catch(() => null),
            api.history(1).catch(() => null),
            api.extension().catch(() => null),
            api.settings().catch(() => ({}) as Record<string, unknown>),
        ]);
        if (!status) return;
        const packs = await api.packs().catch(() => []);
        const gapLists = await Promise.all(
            packs.map((pack) => api.gaps(pack.pack_id).catch(() => [])),
        );
        const stored = settings?.[DISMISS_KEY];
        dismissedId = typeof stored === "string" ? stored : null;
        args = {
            packs: status.packs,
            enabled: status.enabled_packs,
            gaps: gapLists.flat().length,
            agentsConnected: (targets?.targets ?? []).filter(
                (t) => t.state === "connected",
            ).length,
            agentsKnown: (targets?.targets ?? []).length,
            updatable,
            checks: (history?.items ?? []).length,
            // Null, not false, when the status could not be read or this build
            // carries no extension: a suggestion to install something that is
            // not there would be the hint bar lying. `ever_connected`, not
            // `connected`: this is a one-time "was it ever set up" question,
            // and the live badge on the Extension page goes stale after a few
            // quiet hours — reusing it here (B85) kept re-offering the install
            // to readers whose extension had worked for weeks.
            extensionConnected:
                extension && extension.available ? extension.ever_connected : null,
        };
        step = nextStep(args, mode);
    };
    // Re-run when the mode switch flips: a buyer step and an author step can
    // point at different routes for the same signals (check-7), and staying
    // on the load that ran before the switch would keep offering a dead end.
    $effect(() => {
        mode;
        void load();
    });

    api.packUpdates()
        .then((updates) => {
            updatable = updates.packs.filter((p) => p.state === "available").length;
            if (args) step = nextStep({ ...args, updatable }, mode);
        })
        .catch(() => {});

    function dismiss() {
        if (!step) return;
        dismissedId = step.id;
        // Fire-and-forget: a failed write means "Not now" does not survive a
        // restart this one time, not that the click did nothing — the bar
        // still closes for this session either way.
        void api.putSettings({ [DISMISS_KEY]: step.id }).catch(() => {});
    }
</script>

{#if step && step.id !== dismissedId && step.route !== $route.name}
    <aside class="nextstep enter" aria-label="Suggested next step">
        <div>
            <strong>{step.title}</strong>
            <span class="meta">{step.detail}</span>
        </div>
        <div class="nextstep-do">
            <a class="tab" href={hashWith({ mode: $route.query.mode }, step.route)}>
                {step.action}
            </a>
            <button class="ghost" onclick={dismiss} aria-label="Dismiss this suggestion"
                >Not now</button
            >
        </div>
    </aside>
{/if}
