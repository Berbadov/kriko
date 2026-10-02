<script lang="ts">
    import Icon from "../lib/Icon.svelte";
    import LocalMachine from "../lib/LocalMachine.svelte";
import PageHead from "../lib/kriko/PageHead.svelte";
</script>

<PageHead crumb="this install / local llm" title="Local LLM" lead="An LLM on this computer reads and researches, with no key." />
<p class="meta">
    An LLM running on this computer reads and researches for Kriko, at no cost and with no key.
</p>
<LocalMachine />
