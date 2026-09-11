import { writable } from "svelte/store";

/** Whether the terminal panel is open.
 *
 * Shared rather than owned by the panel: the button that opens it lives in
 * the rail (`Sidebar.svelte`) and the panel itself is mounted at the app
 * root (`App.svelte`), and neither is the other's parent. Closed by default
 * — a shell is not what a reader who opens this app is usually here for,
 * and `TerminalPanel.svelte` reads this same flag to decide whether it has
 * ever needed to connect at all.
 */
export const terminalOpen = writable(false);

export const toggleTerminal = (): void => terminalOpen.update((open) => !open);
