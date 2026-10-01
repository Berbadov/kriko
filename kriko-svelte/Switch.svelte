<script lang="ts">
  interface Props {
    checked?: boolean;
    label: string;
    disabled?: boolean;
    onchange?: (value: boolean) => void;
  }
  let { checked = $bindable(false), label, disabled = false, onchange }: Props = $props();
  function toggle() {
    checked = !checked;
    onchange?.(checked);
  }
</script>

<button class="k-switch" role="switch" aria-checked={checked} aria-label={label} {disabled} onclick={toggle}></button>
