<script lang="ts">
    /* Picking a file without the platform's own control.
     *
     * The native `<input type="file">` draws "Choose File" and "No file chosen"
     * in the platform's own face, and nothing in a stylesheet reaches the second
     * half of it (B160: "Restyle the 'Choose File' box (unstylised)"). So the
     * real input is kept, hidden, as the thing that holds the file and answers
     * to its `<label for>`, and what the reader sees is a button on the same
     * raised face as every other button, with the chosen name beside it.
     *
     * The button is a real `<button>`: it is in the tab order, Enter and Space
     * open the file dialog through the hidden input's `click()`, and its
     * accessible name is its own label. The input is out of the tab order so
     * the keyboard meets one control here, not two.
     */
    let {
        id,
        label = "Choose a file",
        accept = "",
        files = $bindable<FileList | null>(null),
        onchange,
    }: {
        id?: string;
        label?: string;
        accept?: string;
        files?: FileList | null;
        onchange?: (event: Event) => void;
    } = $props();

    let input = $state<HTMLInputElement | undefined>();
    const name = $derived(files?.length ? files[0].name : "");
</script>

<span class="file-pick">
    <input
        bind:this={input}
        {id}
        type="file"
        {accept}
        tabindex="-1"
        bind:files
        {onchange}
    />
    <button type="button" onclick={() => input?.click()}>{label}</button>
    {#if name}
        <span class="file-name" title={name}>{name}</span>
    {/if}
</span>
