import { cleanup, render } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";
import JackMark from "./JackMark.svelte";

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

/** SVG animation elements (`<animate>`, `<animateTransform>`), by local name. */
function animations(container: HTMLElement) {
    return [...container.querySelectorAll("*")].filter((el) => /^animate/.test(el.localName));
}

describe("JackMark", () => {
    afterEach(() => {
        cleanup();
        setReducedMotion(false);
    });

    it("draws the jack, hidden from assistive technology", () => {
        setReducedMotion(false);
        const { container } = render(JackMark);
        const svg = container.querySelector("svg.jack");
        expect(svg).not.toBeNull();
        expect(svg?.getAttribute("aria-hidden")).toBe("true");
    });

    it("lifts the jack while the wait lasts", () => {
        setReducedMotion(false);
        const { container } = render(JackMark);
        expect(animations(container).length).toBeGreaterThan(0);
    });

    it("holds the jack at rest under reduced motion", () => {
        setReducedMotion(true);
        const { container } = render(JackMark);
        expect(container.querySelector("svg.jack")).not.toBeNull();
        expect(animations(container).length).toBe(0);
    });
});
