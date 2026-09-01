<script lang="ts">
    import { api } from "../lib/api";
    import type { Subject } from "../lib/types";

    let query = $state("");
    let subjects = $state<Subject[]>([]);
    let error = $state("");
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function search() {
        try {
            subjects = await api.subjects(query.trim());
            error = "";
        } catch (e) {
            error = (e as Error).message;
        }
    }

    function onInput() {
        clearTimeout(timer);
        timer = setTimeout(search, 180);
    }

    const ready = search();
</script>

<div class="row">
    <div class="field">
        <label for="search">Search subjects</label>
        <input id="search" bind:value={query} oninput={onInput} style="min-width: 280px" />
    </div>
</div>

{#await ready}
    <p class="state loading">Loading…</p>
{:then}
    {#if error}
        <p class="state error">Could not load this view: {error}</p>
    {:else if subjects.length}
        <table>
            <thead>
                <tr><th>Subject</th><th>Kind</th><th>Pack</th><th>Claims</th></tr>
            </thead>
            <tbody>
                {#each subjects as subject}
                    <tr>
                        <td>{subject.label}</td>
                        <td>{subject.kind}</td>
                        <td>{subject.pack_id}</td>
                        <td class="num">{subject.claims}</td>
                    </tr>
                {/each}
            </tbody>
        </table>
    {:else}
        <p class="state empty">No matching subjects.</p>
    {/if}
{/await}
