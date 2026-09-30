/** Letting another process choose what this window shows.
 *
 * The browser extension's "Open in Kriko" cannot raise a native window and
 * cannot reach this SPA directly, so the handoff runs through the engine:
 * the extension posts a route, the sidecar prints a line that makes the Tauri
 * shell raise the window, and this poll is the half that actually navigates.
 * See `src/app/web/routers/focus.py` for the whole shape of it.
 *
 * A poll rather than a push. `EventSource` would hold a connection open for
 * the life of the window to carry a message that arrives a handful of times a
 * day, and the server would then need to keep per-client state for something
 * that is already consume-once. Two seconds is well inside the time it takes
 * a reader to look from their browser to the app.
 *
 * It stops while the window is hidden, which is most of its life: a minimised
 * app has nothing to navigate for, and a nudge posted meanwhile is still
 * waiting when the window comes back — the server holds it for 30 seconds,
 * and `visibilitychange` checks immediately rather than waiting out the
 * interval.
 */
import { api } from "./api";
import { navigate } from "./router";

/** How often to ask, while the window is actually being looked at. */
export const EVERY_MS = 2000;

export function watchFocus(every = EVERY_MS): () => void {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const check = async () => {
        if (stopped || document.hidden) return;
        try {
            const { route } = await api.focus();
            // `result/abc` → navigate("result", "abc"). Splitting here rather
            // than assigning `location.hash` directly keeps every navigation
            // in this app going through the one function that builds hashes.
            if (route) {
                const [name, ...params] = route.split("/");
                if (name) navigate(name, ...params);
            }
        } catch {
            // A failed poll is not worth a word. The engine restarting, or a
            // request racing shutdown, must not put an error on a screen the
            // reader is reading for another reason entirely.
        }
    };

    const loop = () => {
        timer = setTimeout(async () => {
            await check();
            if (!stopped) loop();
        }, every);
    };

    const onVisible = () => {
        if (!document.hidden) void check();
    };

    document.addEventListener("visibilitychange", onVisible);
    loop();

    return () => {
        stopped = true;
        if (timer !== undefined) clearTimeout(timer);
        document.removeEventListener("visibilitychange", onVisible);
    };
}
