import { writable } from "svelte/store";
import { api } from "./api";
import { setQuery } from "./router";

/** The two readers of one payload.
 *
 * `buyer` wants to know what to worry about and what to ask; `author` wants to
 * know why the engine ranked it there and which pack said so. This is a
 * *projection*: no request carries a mode and no endpoint branches on one, so
 * the engine cannot grow a second answer shape it has to keep in sync.
 */
export type Mode = "buyer" | "author";

export const MODES: Mode[] = ["buyer", "author"];
export const DEFAULT_MODE: Mode = "buyer";

export const asMode = (value: unknown): Mode =>
    value === "author" ? "author" : "buyer";

export const mode = writable<Mode>(DEFAULT_MODE);

/** URL first, then the remembered setting.
 *
 * The order is the point: a link someone pasted into a chat must open in the
 * mode it was written for, even if the reader's own default is the other one.
 */
export async function initMode(fromUrl?: string): Promise<Mode> {
    if (fromUrl) {
        const wanted = asMode(fromUrl);
        mode.set(wanted);
        return wanted;
    }
    try {
        const stored = asMode((await api.settings()).mode);
        mode.set(stored);
        setQuery("mode", stored);
        return stored;
    } catch {
        return DEFAULT_MODE;
    }
}

export function setMode(next: Mode): void {
    mode.set(next);
    setQuery("mode", next);
    // Fire and forget: failing to remember a preference must not break the
    // switch the reader just used.
    void api.putSettings({ mode: next }).catch(() => {});
}
