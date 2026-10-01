<script lang="ts">
    import Icon from "./Icon.svelte";
    import { api } from "./api";
    import type { BoardNote, BoardStroke, CompareBoard } from "./types";

    /* Focus a fresh note's textarea the moment it lands, so typing a note
     * is one click and keys, never a click into the box first. */
    function focusOnMount(node: HTMLElement) {
        node.focus();
    }

    /* The drawing half of the Compare board (B194): a canvas laid over the
     * comparison's own table, holding whatever the reader marks while they
     * weigh the shortlist. Circled winner, crossed-out column, a note
     * pointing at the row that decided it.
     *
     * Coordinates are fractions (0..1) of the board's own box, not pixels:
     * the board is saved against the draft and reopened at whatever width
     * the next window has, and a mark stored in pixels would land on the
     * wrong column the moment anything resized. Fractions land where the
     * reader drew them, whatever the size.
     *
     * Saved wholesale and often: pen-up and every note edit each send the
     * whole document, because the store replaces rather than merges (an
     * erased mark must stay erased), and a crash costs one pen lift at
     * most, never the drawing.
     */
    let {
        draftId,
        onClose,
    }: { draftId: string; onClose: () => void } = $props();

    let board = $state<CompareBoard | null>(null);
    let strokes = $state<BoardStroke[]>([]);
    let notes = $state<BoardNote[]>([]);
    let canvas = $state<HTMLCanvasElement | null>(null);
    let box = $state<HTMLDivElement | null>(null);
    let drawing = false;
    let current: { x: number; y: number }[] = [];
    let tool = $state<"pen" | "note">("pen");
    let saveTimer: ReturnType<typeof setTimeout> | undefined;
    let boardError = $state("");
    // Which note is open for editing, by its index. One at a time, the same
    // discipline as the table's own detail rows.
    let openNote = $state(-1);

    $effect(() => {
        api.compareBoard(draftId)
            .then((b) => {
                board = b;
                strokes = b.strokes ?? [];
                notes = b.notes ?? [];
            })
            .catch(() => {
                // Fails open, like the drafts list: a board that will not
                // load is an empty one, and the reader can still draw.
                board = {
                    draft_id: draftId, strokes: [], notes: [], updated_at: "",
                };
            });
    });

    const ctx = $derived(canvas?.getContext("2d") ?? null);

    $effect(() => {
        if (!ctx || !box || !board) return;
        const redraw = () => {
            const rect = box!.getBoundingClientRect();
            const { width, height } = rect;
            canvas!.width = width;
            canvas!.height = height;
            const c = ctx!;
            c.clearRect(0, 0, width, height);
            c.lineWidth = 2.5;
            c.lineCap = "round";
            c.lineJoin = "round";
            c.strokeStyle = "var(--ink, #333)";
            const all = drawing ? [...strokes, current] : strokes;
            for (const stroke of all) {
                const points = stroke as { x: number; y: number }[];
                if (!points.length) continue;
                c.beginPath();
                c.moveTo(points[0].x * width, points[0].y * height);
                for (const p of points.slice(1)) {
                    c.lineTo(p.x * width, p.y * height);
                }
                c.stroke();
            }
        };
        redraw();
        // Redraw on resize, because the canvas is the box's size and the
        // fractions only mean anything against the current one.
        const observer = new ResizeObserver(redraw);
        observer.observe(box);
        return () => observer.disconnect();
    });

    const point = (event: PointerEvent) => {
        const rect = box!.getBoundingClientRect();
        return {
            x: (event.clientX - rect.left) / rect.width,
            y: (event.clientY - rect.top) / rect.height,
        };
    };

    function down(event: PointerEvent) {
        if (tool !== "pen" || event.button !== 0) return;
        drawing = true;
        current = [point(event)];
        box!.setPointerCapture(event.pointerId);
    }

    function move(event: PointerEvent) {
        if (!drawing) return;
        current.push(point(event));
    }

    function up() {
        if (!drawing) return;
        drawing = false;
        if (current.length > 1) strokes = [...strokes, current];
        current = [];
        save();
    }

    async function save() {
        if (!board) return;
        boardError = "";
        // Debounced, not deferred: a fast scribble is many pen-ups, and
        // each one sending the whole document would write the board once
        // per second of drawing.
        clearTimeout(saveTimer);
        saveTimer = setTimeout(async () => {
            try {
                const saved = await api.saveCompareBoard(
                    draftId, strokes, notes);
                strokes = saved.strokes ?? strokes;
                notes = saved.notes ?? notes;
            } catch {
                // The marks stay on screen; losing the last lift to a
                // closed window is the accepted cost, stated in the save's
                // own contract.
                boardError = "The board could not be saved; the marks are still here.";
            }
        }, 400);
    }

    function addNote(event: MouseEvent) {
        if (tool !== "note") return;
        const rect = box!.getBoundingClientRect();
        const note: BoardNote = {
            x: (event.clientX - rect.left) / rect.width,
            y: (event.clientY - rect.top) / rect.height,
            text: "",
        };
        notes = [...notes, note];
        openNote = notes.length - 1;
    }

    function editNote(i: number, text: string) {
        const next = [...notes];
        next[i] = { ...next[i], text };
        notes = next;
        save();
    }

    function removeNote(i: number) {
        notes = notes.filter((_, index) => index !== i);
        openNote = -1;
        save();
    }

    function clearBoard() {
        strokes = [];
        notes = [];
        openNote = -1;
        save();
    }

    const undoStroke = () => {
        strokes = strokes.slice(0, -1);
        save();
    };
</script>

{#if board}
    <div class="board" bind:this={box}>
        <canvas
            bind:this={canvas}
            role="img"
            aria-label="Your marks over the comparison"
            onpointerdown={down}
            onpointermove={move}
            onpointerup={up}
            onpointercancel={up}
            onclick={addNote}
        ></canvas>
        {#each notes as note, i (i)}
            <div
                class="stickie"
                style="left: {note.x * 100}%; top: {note.y * 100}%;"
            >
                {#if openNote === i}
                    <textarea
                        rows="2"
                        value={note.text}
                        onblur={(e) => {
                            editNote(i, e.currentTarget.value);
                            openNote = -1;
                        }}
                        placeholder="e.g. this one, if the price drops"
                        use:focusOnMount
                    ></textarea>
                {:else}
                    <button
                        type="button"
                        class="stickie-text"
                        onclick={() => (openNote = i)}
                    >{note.text || "Empty note"}</button>
                {/if}
                {#if openNote === i}
                    <button
                        type="button"
                        class="ghost"
                        aria-label="Remove this note"
                        onclick={() => removeNote(i)}>Remove</button
                    >
                {/if}
            </div>
        {/each}
    </div>
    <div class="board-tools">
        <button
            type="button"
            class:primary={tool === "pen"}
            aria-pressed={tool === "pen"}
            onclick={() => (tool = "pen")}
        >
            <Icon name="edit" size={16} /> Pen
        </button>
        <button
            type="button"
            class:primary={tool === "note"}
            aria-pressed={tool === "note"}
            onclick={() => (tool = "note")}
        >
            <Icon name="plus" size={16} /> Note
        </button>
        <button type="button" onclick={undoStroke} disabled={!strokes.length}>
            Undo mark
        </button>
        <button
            type="button"
            onclick={clearBoard}
            disabled={!strokes.length && !notes.length}
        >Clear the board</button>
        <button type="button" class="ghost" onclick={onClose}>Close the board</button>
        {#if boardError}<p class="state" role="alert">{boardError}</p>{/if}
    </div>
{:else}
    <p class="meta">Opening the board…</p>
{/if}

<style>
    .board {
        position: relative;
        touch-action: none;
        border: 1px dashed var(--line, #888);
        border-radius: var(--r, 6px);
        min-height: 18rem;
        margin: var(--s-2) 0;
        overflow: hidden;
    }

    .board canvas {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        cursor: crosshair;
    }

    .stickie {
        position: absolute;
        transform: translateY(-100%);
        max-width: 14rem;
    }

    .stickie-text {
        white-space: pre-wrap;
        text-align: left;
        width: 100%;
    }

    .stickie textarea {
        width: 100%;
    }

    .board-tools {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-2);
        align-items: center;
        margin-bottom: var(--s-3);
    }
</style>
