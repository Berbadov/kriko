import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import FilePick from "./FilePick.svelte";

const SOURCES = import.meta.glob("../**/*.svelte", {
    query: "?raw",
    import: "default",
    eager: true,
}) as Record<string, string>;

const kpack = () => new File(["x"], "cars-1.2.kpack", { type: "application/octet-stream" });

/* B160: "Restyle the 'Choose File' box (unstylised)". The native control draws
 * "Choose File" and "No file chosen" in the platform's face and no stylesheet
 * reaches the second half, so it is never drawn: the real input is kept hidden
 * and a button takes its place. */
describe("FilePick", () => {
    it("shows a button, and the native control is out of the way", () => {
        const { container } = render(FilePick, { label: "Choose a .kpack file", accept: ".kpack" });
        expect(screen.getByRole("button", { name: "Choose a .kpack file" })).toBeInTheDocument();
        const input = container.querySelector('input[type="file"]') as HTMLInputElement;
        // Out of the tab order: the keyboard meets one control here, not two.
        expect(input.tabIndex).toBe(-1);
        expect(input.getAttribute("accept")).toBe(".kpack");
        // And nothing on the page says the platform's own words.
        expect(screen.queryByText(/no file chosen/i)).toBeNull();
    });

    it("opens the file dialog through the input when the button is pressed", async () => {
        const { container } = render(FilePick, { label: "Choose a file" });
        const input = container.querySelector('input[type="file"]') as HTMLInputElement;
        const opened = vi.spyOn(input, "click").mockImplementation(() => {});
        await fireEvent.click(screen.getByRole("button", { name: "Choose a file" }));
        expect(opened).toHaveBeenCalledTimes(1);
    });

    it("names the chosen file beside the button, and says nothing before one is chosen", async () => {
        const { container } = render(FilePick, { label: "Choose a file" });
        expect(container.querySelector(".file-name")).toBeNull();
        const input = container.querySelector('input[type="file"]') as HTMLInputElement;
        await fireEvent.change(input, { target: { files: [kpack()] } });
        expect(await screen.findByText("cars-1.2.kpack")).toHaveClass("file-name");
    });

    it("keeps the input's own label, so a form label still names it", () => {
        render(FilePick, { id: "kpack", label: "Choose a file" });
        const label = document.createElement("label");
        label.htmlFor = "kpack";
        label.textContent = "Or install a .kpack file you already have";
        document.body.append(label);
        expect(screen.getByLabelText(/\.kpack file you already have/)).toHaveAttribute("id", "kpack");
        label.remove();
    });

    it("hands the change to the caller", async () => {
        const onchange = vi.fn();
        const { container } = render(FilePick, { label: "Choose a file", onchange });
        const input = container.querySelector('input[type="file"]') as HTMLInputElement;
        await fireEvent.change(input, { target: { files: [kpack()] } });
        expect(onchange).toHaveBeenCalledTimes(1);
    });
});

describe("file inputs across the app", () => {
    it("are all FilePick, so no screen can draw the native control", () => {
        const bare = Object.entries(SOURCES)
            .filter(([path]) => !path.endsWith("FilePick.svelte"))
            .filter(([, source]) => /<input\b[^>]*type=["']file["']/.test(source))
            .map(([path]) => path);
        expect(bare).toEqual([]);
        // And the two screens that take a file do so through it.
        for (const file of ["./PacksSection", "../routes/Welcome"]) {
            const source = SOURCES[`${file}.svelte`];
            expect(source, file).toMatch(/<FilePick\b/);
        }
    });
});
