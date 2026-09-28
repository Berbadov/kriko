import { api } from "./api";

/** How often an open answer asks whether the knowledge moved (B152.4). */
export const CLOCK_MS = 1500;

type Listener = () => void;

const listeners = new Set<Listener>();
let timer: ReturnType<typeof setTimeout> | undefined;
let last: string | undefined;

/**
 * Call `onChange` whenever anything writes to the knowledge — an agent's
 * findings through MCP, a research job, a pack install — and return the way
 * to stop.
 *
 * One timer for the whole app however many screens listen, and none while the
 * window is hidden: the shell hides the window rather than closing it, and a
 * hidden window asking every second and a half is cost with no reader. The
 * first reading only sets the baseline, so opening a screen is not itself a
 * "change".
 */
export function onKnowledgeChange(onChange: Listener): () => void {
    listeners.add(onChange);
    if (listeners.size === 1) {
        document.addEventListener("visibilitychange", wake);
        void tick();
    }
    return () => {
        listeners.delete(onChange);
        if (listeners.size) return;
        if (timer) clearTimeout(timer);
        timer = undefined;
        last = undefined;
        document.removeEventListener("visibilitychange", wake);
    };
}

function wake() {
    if (!document.hidden && listeners.size && !timer) void tick();
}

async function tick() {
    timer = undefined;
    if (!listeners.size) return;
    if (document.hidden) return;
    try {
        const { clock } = await api.knowledgeClock();
        if (last !== undefined && clock !== last)
            for (const listener of [...listeners]) listener();
        last = clock;
    } catch {
        // An engine that is restarting is not a change; the next answer is.
    }
    if (listeners.size && !timer) timer = setTimeout(tick, CLOCK_MS);
}
