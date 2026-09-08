import { api } from "./api";
import type { PipelineFrame, PipelineStage } from "./types";

/** How often the fallback re-reads. Matches the server's stream poll. */
export const POLL_MS = 700;

/**
 * Follow the pipeline until the run it is watching settles.
 *
 * Same shape as `follow` in `jobs.ts`, and for the same reason: SSE where the
 * browser has it, polling where it does not — and the fallback is not only
 * for old browsers. A stream that opens and then dies (a proxy that buffers,
 * a dropped connection) would otherwise leave a run looking frozen forever.
 * The rows are the truth either way, which is what makes falling back safe.
 *
 * `after` is threaded through both paths because the events are cursored:
 * re-reading the whole log on every frame would grow quadratically on a run
 * that reads fifty sources, and dropping the cursor would replay events the
 * reader has already watched arrive.
 */
export function followPipeline(
    onFrame: (frame: PipelineFrame) => void,
    runId?: string,
): () => void {
    let stopped = false;
    let cursor = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let source: EventSource | undefined;

    const stop = () => {
        stopped = true;
        if (timer) clearTimeout(timer);
        source?.close();
    };

    const take = (frame: PipelineFrame) => {
        cursor = frame.cursor;
        onFrame(frame);
    };

    const poll = async () => {
        if (stopped) return;
        try {
            if (!runId) {
                // No id: find whatever is most interesting, then follow it.
                const { runs } = await api.pipelineRuns(1);
                if (!runs.length) {
                    timer = setTimeout(poll, POLL_MS);
                    return;
                }
                runId = runs[0].run_id;
            }
            const frame = await api.pipelineRun(runId, cursor);
            take(frame);
            if (!frame.live) return stop();
        } catch {
            return stop();
        }
        timer = setTimeout(poll, POLL_MS);
    };

    if (typeof EventSource === "undefined") {
        void poll();
        return stop;
    }

    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    source = new EventSource(`/api/pipeline/stream${query}`);
    source.onmessage = (event) => {
        const frame = JSON.parse(event.data) as PipelineFrame;
        take(frame);
        if (!frame.live) stop();
    };
    source.onerror = () => {
        source?.close();
        source = undefined;
        if (!stopped) void poll();
    };
    return stop;
}

/** What a run's state is called in front of the reader.
 *
 * `interrupted` gets a sentence rather than a word: it is the one state whose
 * cause is outside the run — the app stopped — and a reader who reads it as a
 * failure of the research goes looking for a bug that is not there. */
export const RUN_WORD: Record<string, string> = {
    running: "running",
    done: "finished",
    failed: "failed",
    cancelled: "stopped by you",
    interrupted: "cut short when the app stopped",
};

export const runWord = (state: string) => RUN_WORD[state] ?? state;

/** The count that means something for each stage.
 *
 * Deliberately not one universal number. "Items" on a Discovery stage is
 * sources; on Ingestion it is verdicts. A single column headed with a generic
 * word would be a column the reader has to decode per row.
 */
export function stageCount(
    stage: PipelineStage,
    run: { sources: number; findings: number; accepted: number; refused: number },
): string {
    if (stage.state === "waiting") return "";
    switch (stage.stage) {
        case "discovery":
            return `${run.sources} source${run.sources === 1 ? "" : "s"}`;
        case "extraction":
            return `${run.findings} finding${run.findings === 1 ? "" : "s"}`;
        case "ingestion":
            return `${run.accepted} kept, ${run.refused} refused`;
        default:
            return stage.items ? `${stage.items} line${stage.items === 1 ? "" : "s"}` : "";
    }
}

/** How far along a run is, for the bar at the top.
 *
 * Counted in settled stages rather than interpolated from item counts: the
 * pipeline has no idea how many findings a source will yield, so a percentage
 * derived from them would move backwards, and a bar that goes backwards is
 * worse than a coarse one.
 */
export function runProgress(stages: PipelineStage[]): number {
    const settled = stages.filter((stage) =>
        ["done", "skipped", "failed"].includes(stage.state),
    ).length;
    return stages.length ? settled / stages.length : 0;
}
