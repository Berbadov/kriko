<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import { tick } from "svelte";
    import { route, setQuery } from "../lib/router";
    import { api } from "../lib/api";
    import EmptyState from "../lib/EmptyState.svelte";
    import Failure from "../lib/Failure.svelte";
    import RunWith from "../lib/RunWith.svelte";
    import { elapsed } from "../lib/time";
    import { canCancel, follow, isLive, kindWord as libKindWord, stateWord } from "../lib/jobs";
    import type { Job, Question } from "../lib/types";

    let jobs = $state<Job[]>([]);
    // The exception, not a rendering of it: Failure reads the status to
    // decide what the reader can do next, and String(cause) has already
    // thrown that away (B72).
    let error = $state<unknown>(null);
    let open = $state<string | null>(null);
    let root = $state("");
    let busy = $state(false);
    let cancelPending = $state<string[]>([]);
    // ops-5: `retry` had no pending guard at all, and a double-click sent two
    // `POST /retry` before the first had come back — the server is now
    // idempotent (it hands back the same child), but the button should not
    // rely on that: a reader pressing it twice wants one run, not a lucky
    // dedupe.
    let retryPending = $state<string[]>([]);
    /* What the reader has typed back, per job and then per question id.
     *
     * Kept here rather than on the row because the row is replaced wholesale
     * every time the stream ticks — a draft held on `job` would be erased
     * twice a second by the thing that is supposed to be showing it. */
    let answers = $state<Record<string, Record<string, string>>>({});

    // One follower per live job, kept in a map so a re-render does not open a
    // second stream for the same row.
    const stops = new Map<string, () => void>();

    const replace = (job: Job) => {
        const index = jobs.findIndex((candidate) => candidate.job_id === job.job_id);
        if (index === -1) jobs = [job, ...jobs];
        else jobs[index] = job;
        if (job.done) {
            stops.get(job.job_id)?.();
            stops.delete(job.job_id);
        }
    };

    const watch = (job: Job) => {
        if (!isLive(job) || stops.has(job.job_id)) return;
        stops.set(job.job_id, follow(job.job_id, replace));
    };

    const load = async () => {
        try {
            jobs = (await api.jobs()).items ?? [];
            jobs.forEach(watch);
        } catch (cause) {
            error = cause;
        }
    };

    // A job started from another screen, another agent, or the API never
    // appeared here until the reader reloaded (B145 ops-8): `load` only ran
    // once, on mount, so a row this screen had never seen had no way in. This
    // re-reads the list on a slow clock and merges in anything new by id —
    // never touching a row already in `jobs`, so a stream mid-flight for a job
    // this screen is already following is not clobbered by a stale list read.
    const REFRESH_MS = 4000;
    let refresher: ReturnType<typeof setInterval> | undefined;

    const checkForNew = async () => {
        try {
            const seen = new Set(jobs.map((job) => job.job_id));
            const fetched = (await api.jobs()).items ?? [];
            const arrived = fetched.filter((job) => !seen.has(job.job_id));
            if (arrived.length) {
                jobs = [...arrived, ...jobs];
                arrived.forEach(watch);
            }
        } catch {
            // A missed poll is not worth surfacing; the next one retries.
        }
    };

    $effect(() => {
        void load();
        refresher = setInterval(() => void checkForNew(), REFRESH_MS);
        return () => {
            stops.forEach((stop) => stop());
            stops.clear();
            if (refresher) clearInterval(refresher);
        };
    });

    // ── starting a pack: one field, and an agent does the rest ──────────
    //
    // What was here asked for a directory, an id, a name and an identity
    // table before it would write anything, and the reader's verdict on that
    // was "it's gotta be automated with agents". They were right, and not
    // only about the typing: three of those four are decisions somebody who
    // has read the category can take well and somebody who has not cannot
    // take at all. The identity table is the sharp one — too few keys and
    // unrelated rows collide into one subject, too many and one thing splits
    // across subjects that never see each other's claims, and neither failure
    // raises anything. Asking for it first was asking for the one answer the
    // reader was least equipped to give.
    //
    // So: a category in plain words, one press. The agent proposes the data,
    // the engine writes the files, and the reader installs from Knowledge —
    // three steps and three different authorities, which is why nothing here
    // reaches the store.
    let category = $state("");
    let categoryInput: HTMLInputElement;
    /* B146: which agent, and how long it may take. The form used to be a
     * collapsed <details> with none of these, so "how hard will it try, and
     * when does it give up" had no answer anywhere near the button. */
    let harness = $state("");
    let timeout = $state(0);
    const TIMEOUTS = [
        { seconds: 0, label: "40 min (default)" },
        { seconds: 600, label: "10 min" },
        { seconds: 1200, label: "20 min" },
        { seconds: 3600, label: "60 min" },
    ];

    /* A clock for live rows. A harness that is thinking prints nothing for
     * minutes, and "running" with no sense of time read as stuck (B146). */
    let now = $state(Date.now());
    $effect(() => {
        const ticker = setInterval(() => (now = Date.now()), 1000);
        return () => clearInterval(ticker);
    });
    const lastLine = (job: Job) => {
        const lines = String(job.log ?? "").trimEnd().split(/\r?\n/);
        const last = lines[lines.length - 1]?.trim() ?? "";
        return last && last !== job.message ? last : "";
    };

    $effect(() => {
        if ($route.query.author !== "new") return;
        let active = true;
        void tick().then(() => {
            if (!active) return;
            categoryInput.focus();
            setQuery("author", undefined);
        });
        return () => { active = false; };
    });

    // The server's own field (`app/web/routers/jobs.py`'s AuthorRequest)
    // requires two characters — below that, `x` reached the server and came
    // back a 422 the reader had no way to anticipate (ops-4). Matching the
    // bound here means the button simply will not fire a request that could
    // not succeed.
    const CATEGORY_MIN = 2;

    async function authorPack() {
        if (category.trim().length < CATEGORY_MIN) return;
        busy = true;
        error = null;
        try {
            const { job_id } = await api.authorPack(category.trim(), harness, timeout);
            const job = await api.job(job_id);
            replace(job);
            watch(job);
            // Opened straight away, because this run is worth watching: it is
            // several minutes of an agent reading, and the log is where the
            // reader sees that it is reading rather than hung.
            open = job_id;
        } catch (cause) {
            error = cause;
        } finally {
            busy = false;
        }
    }

    async function build() {
        if (!root.trim()) return;
        busy = true;
        error = null;
        try {
            const { job_id } = await api.buildPack(root.trim());
            const job = await api.job(job_id);
            replace(job);
            watch(job);
            open = job_id;
        } catch (cause) {
            error = cause;
        } finally {
            busy = false;
        }
    }

    async function cancel(job: Job) {
        if (!canCancel(job) || cancelPending.includes(job.job_id)) return;
        cancelPending = [...cancelPending, job.job_id];
        try {
            await api.cancelJob(job.job_id);
            replace(await api.job(job.job_id));
        } catch (cause) {
            error = cause;
        } finally {
            cancelPending = cancelPending.filter((id) => id !== job.job_id);
        }
    }

    /* Saying something to a run that is still going.
     *
     * The questions below this are the *structured* path: the run stopped,
     * wrote a question with options, and the form re-applies the answer to a
     * fresh attempt. This is the unstructured one, and it is what B120 left
     * open — a harness run streams its thinking out and took nothing in, so a
     * run that paused on something the pack's own question schema never
     * anticipated could be watched and stopped and nothing else.
     *
     * Per job id, because two runs may be live at once and a draft typed
     * against one must not appear under the other. */
    let saying = $state<Record<string, string>>({});
    let sayPending = $state<Record<string, boolean>>({});
    let sayNote = $state<Record<string, string>>({});

    async function say(job: Job) {
        const text = (saying[job.job_id] || "").trim();
        if (!text || sayPending[job.job_id]) return;
        sayPending = { ...sayPending, [job.job_id]: true };
        try {
            const answer = await api.sayToJob(job.job_id, text);
            // Cleared only on delivery. A run that ended mid-sentence should
            // leave the reader holding what they wrote, not silently eat it.
            if (answer.delivered) {
                saying = { ...saying, [job.job_id]: "" };
                sayNote = { ...sayNote, [job.job_id]: "Sent." };
            } else {
                sayNote = {
                    ...sayNote,
                    [job.job_id]: "This run had already finished. Nothing was sent.",
                };
            }
        } catch (cause) {
            error = cause;
        } finally {
            sayPending = { ...sayPending, [job.job_id]: false };
        }
    }

    /** Run a finished job's work again.
     *
     * A failure here is usually a network that was down or a source that was
     * slow — nothing about the request was wrong, and retyping it from the
     * form was the only way back. The new row keeps `retry_of`, so the two
     * attempts stay legible as two attempts rather than one confusing
     * duplicate, and the failed row keeps its log: the reason it failed is the
     * most useful thing on this screen and a retry must not overwrite it.
     */
    async function retry(job: Job) {
        if (retryPending.includes(job.job_id)) return;
        retryPending = [...retryPending, job.job_id];
        try {
            const { job_id } = await api.retryJob(job.job_id, answers[job.job_id] ?? {});
            delete answers[job.job_id];
            const fresh = await api.job(job_id);
            replace(fresh);
            watch(fresh);
            open = job_id;
        } catch (cause) {
            error = cause;
        } finally {
            retryPending = retryPending.filter((id) => id !== job.job_id);
        }
    }

    /* One click on an answer (B147).
     *
     * The run that asked is usually still going: it stated a default and
     * carried on. So a click on a *live* run is said to it at once, over the
     * same pipe as the reply box, and the chip says whether it landed. On a
     * finished run the click only picks; the submit is the retry that applies
     * it. `told` is per job and question so a chip can show "sent" without
     * the next poll wiping it. */
    let told = $state<Record<string, "sending" | "sent" | "late">>({});

    async function choose(job: Job, question: Question, option: string) {
        answers[job.job_id] ??= {};
        answers[job.job_id][question.id] = option;
        if (isLive(job)) await tell(job, question);
    }

    async function tell(job: Job, question: Question) {
        const value = (answers[job.job_id]?.[question.id] ?? "").trim();
        const slot = `${job.job_id}/${question.id}`;
        if (!value || told[slot] === "sending") return;
        told = { ...told, [slot]: "sending" };
        try {
            const answer = await api.sayToJob(job.job_id, `Answer to "${question.ask}": ${value}`);
            told = { ...told, [slot]: answer.delivered ? "sent" : "late" };
        } catch (cause) {
            delete told[slot];
            told = { ...told };
            error = cause;
        }
    }

    async function answer(job: Job) {
        if (!isLive(job)) return retry(job);
        for (const question of job.attention?.questions ?? []) await tell(job, question);
    }

    const toldWord = (job: Job, question: Question) => {
        const state = told[`${job.job_id}/${question.id}`];
        return state === "sending" ? "Telling it…"
            : state === "sent" ? "It heard you."
            : state === "late" ? "The run had finished — press Answer and run again."
            : "";
    };

    const percent = (job: Job) => Math.round((job.progress ?? 0) * 100);
    const subjectOf = (job: Job) =>
        String(job.params?.subject_id ?? job.params?.category ?? job.params?.root ?? "");

    const kindWord = (job: Job) => libKindWord(job.kind);
</script>

<!-- "Runs", which is what the rail has always called it. The heading said
     "Jobs" — an implementation word for the row in `app.sqlite` — and now that
     this is a lens under Activity the mismatch is visible in one glance
     instead of across a navigation. -->
<h2><Icon name="jobs" size={22} /> Runs</h2>
<p class="lede">
    Research and pack builds run here, not in a terminal. A job keeps its log and
    saved results. Cancellation stops at a safe checkpoint; an in-flight request
    may finish. Only checkpointed results survive a restart.
</p>

<section class="card authoring">
    <h3><Icon name="plus" /> Start a new pack</h3>
    <p class="meta">
        Name a category in a few words and your own coding agent writes the whole
        pack — what tells two of these apart, the bar a claim has to clear, what
        to search for, and a first honest row. It lands as a draft you can read
        on Knowledge; nothing is installed until you press Install there.
    </p>
    <form
        class="ask"
        onsubmit={(event) => (event.preventDefault(), authorPack())}
    >
        <label class="field grow">
            <span>What is the category?</span>
            <!-- svelte-ignore a11y_autofocus -- deliberate: App.svelte's
                 focusTheView() reads this attribute to decide who gets focus
                 on navigation, rather than racing its own container-focus
                 fallback against this component's own tick().then() (shell-4).
                 It only carries the attribute while ?author=new is present,
                 which is itself the reader having just asked for this form. -->
            <input
                bind:this={categoryInput}
                bind:value={category}
                placeholder="cordless drills, espresso machines, e-bikes"
                autofocus={$route.query.author === "new"}
            />
        </label>
        <button
            class="primary"
            type="submit"
            disabled={busy || category.trim().length < CATEGORY_MIN}
        >
            {busy ? "Starting…" : "Have my agent write it"}
        </button>
    </form>
    <RunWith bind:harness bind:timeout timeouts={TIMEOUTS} disabled={busy} />
    {#if category.trim().length > 0 && category.trim().length < CATEGORY_MIN}
        <p class="meta">At least {CATEGORY_MIN} characters.</p>
    {/if}
    <p class="meta">
        Uses a coding-agent CLI you already have — no API cost. None installed?
        Connect your agent under <a href="#/agents">Agents</a> and let it use
        <code>draft_pack</code>.
    </p>
</section>

<form class="ask" onsubmit={(event) => (event.preventDefault(), build())}>
    <label class="field grow">
        <span>Build a pack from a directory</span>
        <input bind:value={root} placeholder="e.g. packs/drill" />
    </label>
    <button type="submit" disabled={busy || !root.trim()}>Build and install</button>
</form>

{#if error}
    <Failure {error} retry={load} />
{/if}

{#if !jobs.length}
    <EmptyState
        title="No runs yet"
        detail="Long work is a row here rather than a request that hangs — research
                and pack builds both land on this screen, and their log outlives
                the page. Start one above, or from a gap on Knowledge."
        actionLabel="Find a gap"
        actionHref="#/knowledge"
    />
{/if}

{#each jobs as job (job.job_id)}
    <article class="card job" class:live={isLive(job)}>
        <h3>
            {kindWord(job)}
            <span class="meta">{subjectOf(job)}</span>
            <span class="badge state-{job.state}">
                <!-- Only on a job that is still moving. A badge that reads
                     "running" on a page nobody has refreshed says the same
                     thing as one that is stale; the dot is what separates
                     them without the reader having to reload to find out. -->
                {#if isLive(job)}<span class="live-dot"></span>{/if}
                {stateWord(job)}
            </span>
            {#if isLive(job)}
                <span class="meta clock" title="Time since this run started">
                    {elapsed(job.started_at ?? job.created_at, now)}
                </span>
            {/if}
        </h3>
        {#if isLive(job)}
            <div class="bar" role="progressbar" aria-valuenow={percent(job)}>
                <span style="width: {percent(job)}%"></span>
            </div>
        {/if}
        <p class="meta">{job.message || "…"}</p>
        {#if isLive(job) && lastLine(job)}
            <p class="meta tail" title="Latest line of the log">{lastLine(job)}</p>
        {/if}
        <p class="row">
            <button
                onclick={() => (open = open === job.job_id ? null : job.job_id)}
                aria-expanded={open === job.job_id}>Log</button
            >
            {#if isLive(job)}
                <button
                    disabled={!canCancel(job) || cancelPending.includes(job.job_id)}
                    onclick={() => cancel(job)}
                >{job.state === "cancelling" || cancelPending.includes(job.job_id) ? "Stopping…" : "Cancel"}</button>
            {:else}
                <button
                    disabled={retryPending.includes(job.job_id)}
                    onclick={() => retry(job)}
                >{retryPending.includes(job.job_id) ? "Starting…" : "Run again"}</button>
            {/if}
        </p>
        {#if isLive(job)}
            <!-- Offered on every live run rather than only when one has
                 asked something, because nothing tells us it asked: the
                 question is a sentence in the agent's own output, not a
                 field. A box that appears only when we are sure is a box
                 that is never there when it is needed. -->
            <form class="say" onsubmit={(event) => { event.preventDefault(); say(job); }}>
                <!-- Written out rather than `bind:`, for the same reason the
                     question form below is: the backing record starts empty,
                     and a binding onto a slot that does not exist yet is
                     cleared again by the next poll — which lands every second
                     on exactly the runs this box is offered on. -->
                <input
                    aria-label="Reply to this run"
                    placeholder="Answer this run…"
                    value={saying[job.job_id] ?? ""}
                    oninput={(event) => {
                        saying = { ...saying, [job.job_id]: event.currentTarget.value };
                    }}
                    disabled={sayPending[job.job_id]}
                />
                <button type="submit" disabled={sayPending[job.job_id] || !(saying[job.job_id] || "").trim()}
                    >{sayPending[job.job_id] ? "Sending…" : "Send"}</button
                >
            </form>
            {#if sayNote[job.job_id]}
                <p class="meta" aria-live="polite">{sayNote[job.job_id]}</p>
            {/if}
        {/if}
        {#if job.attention?.questions?.length}
            <!-- B147: the question as something to press, not a dropdown under
                 a paragraph with a raw JSON dump below it. On a live run a
                 click reaches the agent now; on a finished one it shapes the
                 retry. The panel slides in, so a question that arrives mid-run
                 is seen rather than found. -->
            <form
                class="asked"
                aria-live="polite"
                onsubmit={(event) => { event.preventDefault(); answer(job); }}
            >
                <p class="asked-lede">
                    <span class="asked-mark" aria-hidden="true">?</span>
                    {isLive(job)
                        ? "Your agent has a question. Pick an answer and it hears it now."
                        : "Your agent had a question and went with its own guess. Answer it and run again."}
                </p>
                {#each job.attention.questions as question (question.id)}
                    <fieldset class="field question">
                        <legend>{question.ask}</legend>
                        {#if question.options.length}
                            <div class="chips" role="radiogroup" aria-label={question.ask}>
                                {#each question.options as option (option)}
                                    {@const picked = (answers[job.job_id]?.[question.id] ?? "") === option}
                                    <button
                                        type="button"
                                        class="chip"
                                        role="radio"
                                        aria-checked={picked}
                                        class:picked
                                        onclick={() => choose(job, question, option)}
                                    >
                                        {option}
                                        {#if option === question.default && !answers[job.job_id]?.[question.id]}
                                            <span class="chip-note">its guess</span>
                                        {/if}
                                    </button>
                                {/each}
                            </div>
                        {:else}
                            <input
                                aria-label={question.ask}
                                placeholder="It guessed {question.default}"
                                value={answers[job.job_id]?.[question.id] ?? ""}
                                oninput={(event) => {
                                    answers[job.job_id] ??= {};
                                    answers[job.job_id][question.id] = event.currentTarget.value;
                                }}
                            />
                        {/if}
                        {#if toldWord(job, question)}
                            <p class="meta told">{toldWord(job, question)}</p>
                        {:else if question.because}
                            <p class="meta">{question.because}</p>
                        {/if}
                    </fieldset>
                {/each}
                {#if !isLive(job) || job.attention.questions.some((q) => !q.options.length)}
                    <p class="row">
                        <button class="primary" type="submit" disabled={retryPending.includes(job.job_id)}>
                            {isLive(job) ? "Tell the run" : "Answer and run again"}
                        </button>
                    </p>
                {/if}
            </form>
        {/if}
        {#if open === job.job_id}
            <pre class="log">{job.log || "nothing logged yet"}</pre>
            {#if job.result && !job.attention?.questions?.length}
                <details class="raw">
                    <summary>What the run returned</summary>
                    <pre class="log">{JSON.stringify(job.result, null, 2)}</pre>
                </details>
            {/if}
        {/if}
    </article>
{/each}
