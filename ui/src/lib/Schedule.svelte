<script lang="ts">
    import Async from "./Async.svelte";
    import { api } from "./api";
    import { remedyFor } from "./failure";
    import type { Schedule } from "./types";

    /* B98 — the agenda, walked with nobody watching.
     *
     * Everything under this card already existed: the agenda knows what is
     * worth researching next, and `agenda_run` walks it. What was missing was
     * the clock, and the reason it is a *card with an off switch* rather than
     * a background behaviour is consent — an app that started spawning agents
     * because a window was left open would be a defect no matter how good
     * the agenda underneath it was.
     *
     * The card leads with the last decision, not with the controls. On the
     * days the loop declines, that sentence is its only output; a panel that
     * showed only the settings would leave a reader unable to tell a loop
     * that is waiting from one that is broken.
     */

    /* Filled in rather than trusted, for the same reason `Usage.svelte`
     * does it: a payload missing `last` is a payload from an older engine,
     * and a template that reads `.last.reason` off an absent field takes the
     * whole card down — so the reader loses the off switch as well as the
     * history. */
    const shape = (raw: Partial<Schedule> | undefined): Schedule => ({
        enabled: false,
        every_hours: 24,
        rows: 5,
        plane: "harness",
        budget_usd: 0,
        max_documents: 5,
        in_flight: 0,
        ...(raw ?? {}),
        last: raw?.last ?? {},
    });

    let promise = $state(api.schedule());
    let saving = $state(false);
    let failed = $state("");
    /* The answer to "check now", held separately from `last` so that a
     * refusal stays on screen while the reader changes a setting to fix it. */
    let checked = $state("");

    async function save(next: Partial<Schedule>) {
        failed = "";
        saving = true;
        try {
            const body = await api.saveSchedule(next);
            promise = Promise.resolve(body);
        } catch (cause) {
            failed = remedyFor(cause).headline;
        } finally {
            saving = false;
        }
    }

    async function checkNow() {
        failed = "";
        checked = "";
        try {
            const body = await api.checkSchedule();
            checked = body.reason;
            promise = Promise.resolve(body);
        } catch (cause) {
            failed = remedyFor(cause).headline;
        }
    }

    /* The reader's question, not the engine's word — the same three names
     * the card above uses, for the same reason. "I'll run it myself" is
     * absent on purpose: it produces a brief for a person to hand over, and
     * there is nobody here to hand it to. */
    const NAMES: Record<string, string> = {
        harness: "Run my agent",
        api: "Kriko itself",
    };

    const every = (hours: number) =>
        hours < 1
            ? `every ${Math.round(hours * 60)} minutes`
            : hours === 1
              ? "hourly"
              : hours === 24
                ? "daily"
                : `every ${hours} hours`;

    /** A stored timestamp, in the reader's own clock. */
    const when = (stamp?: string) =>
        stamp ? new Date(stamp).toLocaleString() : "";
</script>

<article class="card">
    <h3>On a schedule</h3>
    <p class="meta">
        Off until you turn it on. Once on, Kriko walks the top of the agenda by
        itself and every run lands in <strong>Activity → Runs</strong>, undoable,
        exactly like one you started by hand.
    </p>

    <Async {promise} loading="Reading…" retry={() => (promise = api.schedule())}>
        {#snippet children(raw: Schedule)}
            {@const data = shape(raw)}
            <label class="row switch">
                <input
                    type="checkbox"
                    checked={data.enabled}
                    disabled={saving}
                    onchange={(event) =>
                        save({ enabled: event.currentTarget.checked })}
                />
                <span>
                    {data.enabled
                        ? `On — ${every(data.every_hours)}`
                        : "Off"}
                </span>
            </label>

            <div class="grid">
                <label class="field">
                    <span class="meta">How often, hours</span>
                    <input
                        type="number"
                        min="0.25"
                        max="720"
                        step="0.25"
                        value={data.every_hours}
                        disabled={saving}
                        onchange={(event) =>
                            save({ every_hours: Number(event.currentTarget.value) })}
                    />
                </label>
                <label class="field">
                    <span class="meta">Subjects per run</span>
                    <input
                        type="number"
                        min="1"
                        max="100"
                        value={data.rows}
                        disabled={saving}
                        onchange={(event) =>
                            save({ rows: Number(event.currentTarget.value) })}
                    />
                </label>
                <label class="field">
                    <span class="meta">Who does the reading</span>
                    <select
                        value={data.plane}
                        disabled={saving}
                        onchange={(event) => save({ plane: event.currentTarget.value })}
                    >
                        {#each Object.entries(NAMES) as [id, label] (id)}
                            <option value={id}>{label}</option>
                        {/each}
                    </select>
                </label>
                {#if data.plane === "api"}
                    <label class="field">
                        <span class="meta">Ceiling per run, $</span>
                        <input
                            type="number"
                            min="0"
                            max="100"
                            step="0.01"
                            value={data.budget_usd}
                            disabled={saving}
                            onchange={(event) =>
                                save({ budget_usd: Number(event.currentTarget.value) })}
                        />
                    </label>
                {/if}
            </div>

            {#if data.plane === "api"}
                <p class="meta">
                    A ceiling of zero means no ceiling. An unattended run that spends
                    per token is the one place to put a number in.
                </p>
            {/if}

            <p class="row">
                <button type="button" onclick={checkNow}>Check now</button>
                <span class="meta">
                    Asks what it would decide this second. It does not skip ahead.
                </span>
            </p>

            {#if checked}
                <p class="state">{checked}</p>
            {/if}

            {#if data.last.reason}
                <dl class="last">
                    <dt class="meta">Last checked</dt>
                    <dd>{when(data.last.checked_at)}</dd>
                    <dt class="meta">Decided</dt>
                    <dd>{data.last.reason}</dd>
                    {#if data.last.runs}
                        <dt class="meta">Runs started</dt>
                        <dd>{data.last.runs}</dd>
                    {/if}
                </dl>
            {:else}
                <p class="meta">It has not checked yet.</p>
            {/if}

            {#if data.in_flight}
                <p class="meta">
                    {data.in_flight} job{data.in_flight === 1 ? "" : "s"} queued or
                    running — the loop waits rather than piling on.
                </p>
            {/if}
        {/snippet}
    </Async>

    {#if failed}
        <p class="state error">{failed}</p>
    {/if}
</article>

<style>
    .switch {
        gap: var(--s-2);
        margin-block: var(--s-3);
    }
    .grid {
        display: grid;
        gap: var(--s-3);
        grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
        margin-block: var(--s-3);
    }
    .last {
        display: grid;
        grid-template-columns: auto 1fr;
        gap: var(--s-1) var(--s-3);
        margin-block: var(--s-3) 0;
    }
    .last dd {
        margin: 0;
    }
</style>
