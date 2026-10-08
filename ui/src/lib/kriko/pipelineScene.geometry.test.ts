import { describe, expect, it } from "vitest";
import {
    REDUCED_FRAME_SECONDS,
    SCENE_SECONDS,
    sceneOps,
    stageAt,
    type Op,
    type Palette,
} from "./pipelineScene";

const palette: Palette = {
    deep: "#0a1a66",
    low: "#1739c2",
    brand: "#1f4fff",
    hover: "#3a64ff",
    bright: "#86a3ff",
    ice: "#bfe4ff",
    off: "#161d36",
};

/** Every colour an op paints with. */
function coloursOf(ops: Op[]): string[] {
    return ops.flatMap((op) => {
        if (op.kind === "poly") return op.stroke ? [op.fill, op.stroke] : [op.fill];
        return [op.c];
    });
}

describe("the pipeline scene", () => {
    it("is ten seconds long and closes on its first frame", () => {
        expect(SCENE_SECONDS).toBe(10);
        expect(sceneOps(SCENE_SECONDS, false, palette)).toEqual(sceneOps(0, false, palette));
    });

    it("draws the same frame for the same moment", () => {
        expect(sceneOps(3.3, false, palette)).toEqual(sceneOps(3.3, false, palette));
    });

    it("has something on stage at every moment", () => {
        for (const t of [0, 2, 5, 7, 9]) {
            expect(sceneOps(t, false, palette).length, `t=${t}`).toBeGreaterThan(20);
        }
    });

    it("paints only the blue ramp the design system allows", () => {
        const allowed = new Set(Object.values(palette));
        for (const t of [0.5, 2, 5, 7, 9]) {
            for (const c of coloursOf(sceneOps(t, false, palette))) {
                expect(allowed.has(c), `${c} at t=${t}`).toBe(true);
            }
        }
    });

    it("says which stage it is in, on the spec's windows", () => {
        expect(stageAt(0.5).stage).toBe("fetch");
        expect(stageAt(2).stage).toBe("read");
        expect(stageAt(5).stage).toBe("extract");
        expect(stageAt(7).stage).toBe("write");
        expect(stageAt(9).stage).toBe("done");
    });

    it("rests on a finished frame under reduced motion", () => {
        expect(REDUCED_FRAME_SECONDS).toBe(8.9);
        expect(stageAt(REDUCED_FRAME_SECONDS).stage).toBe("done");
    });
});
