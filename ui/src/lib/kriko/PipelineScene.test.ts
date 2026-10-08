import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PipelineScene from "./PipelineScene.svelte";

/* jsdom has no canvas. The scene's geometry is tested in pipelineScene.test.ts;
 * here the contract is the component's: it draws, it names its stage, and it
 * stops looping when the reader asked for less motion. */

function fakeContext() {
    return {
        fillStyle: "",
        strokeStyle: "",
        lineWidth: 1,
        clearRect() {},
        beginPath() {},
        moveTo() {},
        lineTo() {},
        closePath() {},
        fill: vi.fn(),
        stroke: vi.fn(),
        fillRect: vi.fn(),
        getImageData: () => ({ data: new Uint8ClampedArray(360 * 132 * 4) }),
        putImageData() {},
    };
}

function setReducedMotion(matches: boolean) {
    Object.defineProperty(window, "matchMedia", {
        configurable: true,
        writable: true,
        value: (query: string) => ({
            matches,
            media: query,
            onchange: null,
            addEventListener() {},
            removeEventListener() {},
            addListener() {},
            removeListener() {},
            dispatchEvent: () => false,
        }),
    });
}

describe("PipelineScene", () => {
    let ctx: ReturnType<typeof fakeContext>;

    beforeEach(() => {
        ctx = fakeContext();
        vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
            ctx as unknown as CanvasRenderingContext2D,
        );
        vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1);
        vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
    });

    afterEach(() => {
        cleanup();
        vi.restoreAllMocks();
        setReducedMotion(false);
    });

    it("is a labelled picture of the agent pipeline", () => {
        setReducedMotion(false);
        render(PipelineScene);
        expect(screen.getByRole("img", { name: /agent pipeline/i })).toBeInTheDocument();
    });

    it("draws, and keeps the loop going, when motion is allowed", () => {
        setReducedMotion(false);
        render(PipelineScene);
        expect(ctx.fill.mock.calls.length + ctx.stroke.mock.calls.length).toBeGreaterThan(0);
        expect(window.requestAnimationFrame).toHaveBeenCalled();
    });

    it("draws the stable frame once and runs no loop under reduced motion", () => {
        setReducedMotion(true);
        render(PipelineScene);
        expect(ctx.fill.mock.calls.length + ctx.stroke.mock.calls.length).toBeGreaterThan(0);
        expect(window.requestAnimationFrame).not.toHaveBeenCalled();
    });

    it("says which stage it is on, in the spec's words", () => {
        setReducedMotion(true);
        render(PipelineScene);
        expect(screen.getByText(/^done · committed/)).toBeInTheDocument();
    });
});
