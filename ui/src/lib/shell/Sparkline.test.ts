import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Sparkline from "./Sparkline.svelte";

const path = (container: HTMLElement) =>
    container.querySelector("path")?.getAttribute("d") ?? "";

describe("Sparkline", () => {
    it("draws nothing from one point, because one reading is not a shape", () => {
        const { container } = render(Sparkline, { values: [0.4] });
        expect(container.querySelector("svg")).toBeNull();
    });

    it("draws nothing from no points at all", () => {
        const { container } = render(Sparkline, { values: [] });
        expect(container.querySelector("svg")).toBeNull();
    });

    it("normalises into its own box, so the shape is the change and not the units", () => {
        // Same shape, different magnitudes. Cents and dollars have to draw the
        // same line or the rail's sparkline is a second, worse axis.
        const cheap = render(Sparkline, { values: [1, 2, 3] });
        const dear = render(Sparkline, { values: [100, 200, 300] });
        expect(path(cheap.container)).toBe(path(dear.container));
    });

    it("puts the low point at the bottom and the high at the top", () => {
        const { container } = render(Sparkline, { values: [0, 1] });
        expect(path(container)).toBe("M0.0000 1.0000 L1.0000 0.0000");
    });

    it("runs a flat series down the middle rather than along an edge", () => {
        // Dividing by a zero span would pin it to the top, which reads as a
        // maximum rather than as "nothing moved".
        const { container } = render(Sparkline, { values: [2, 2, 2] });
        expect(path(container)).toContain("0.5000");
    });

    it("names the direction, since the shape is the whole content", () => {
        render(Sparkline, { values: [1, 5], label: "spend" });
        expect(screen.getByRole("img", { name: "spend, rising" })).toBeInTheDocument();
    });

    it("says falling when it falls", () => {
        render(Sparkline, { values: [5, 1], label: "spend" });
        expect(screen.getByRole("img", { name: "spend, falling" })).toBeInTheDocument();
    });

    it("ends its marker where the line ends", () => {
        const { container } = render(Sparkline, { values: [0, 1] });
        const end = container.querySelector(".end");
        expect(end?.getAttribute("y1")).toBe("0");
        expect(end?.getAttribute("y1")).toBe(end?.getAttribute("y2"));
    });

    it("carries no interaction, because the row around it is the target", () => {
        const { container } = render(Sparkline, { values: [1, 2] });
        expect(container.querySelector("[title]")).toBeNull();
        expect(container.querySelector("button")).toBeNull();
    });
});
