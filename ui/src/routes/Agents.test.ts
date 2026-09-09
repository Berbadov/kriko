import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Agents from "./Agents.svelte";

/* The shell. Connect and Console keep their own suites; what is asserted here
 * is the lens, and the one thing this merge could plausibly break — a console
 * that loses what you typed, or takes the keyboard on a screen it is not
 * showing. */

function stub() {
    vi.stubGlobal(
        "fetch",
        vi.fn(
            async (path: string) =>
                new Response(
                    JSON.stringify(
                        // `/api/packs` answers with an array, and Connect
                        // filters it — an object here throws inside an effect
                        // rather than failing a test.
                        String(path).includes("/api/packs")
                            ? []
                            : String(path).includes("agent-targets")
                              ? { targets: [] }
                              : String(path).includes("agent-skill")
                                ? { name: "kriko-research", body: "", packs: [] }
                                : { mcp_json: {}, items: [], packs: [] },
                    ),
                ),
        ),
    );
}

describe("Agents", () => {
    it("opens on the wiring, because a console with nothing on the other end is a prompt", async () => {
        stub();
        render(Agents, {});
        expect(await screen.findByRole("tablist", { name: "Agents" })).toBeInTheDocument();
        expect(screen.getByRole("tab", { name: "Wiring" })).toHaveAttribute(
            "aria-selected",
            "true",
        );
    });

    it("does not mount the console until it is asked for", async () => {
        // Not a performance point. The console carries `autofocus`, and
        // App.svelte hands focus to the `[autofocus]` control inside the
        // arriving view — so a console mounted underneath the wiring lens
        // would swallow the keyboard on a screen it is not even showing.
        stub();
        render(Agents, {});
        await screen.findByRole("tablist", { name: "Agents" });
        expect(screen.queryByRole("heading", { name: "Console" })).toBeNull();
        await fireEvent.click(screen.getByRole("tab", { name: "Console" }));
        expect(
            await screen.findByRole("heading", { name: "Console" }),
        ).toBeInTheDocument();
    });

    it("mounts the console straight away when that is the address asked for", async () => {
        // `#/console` was a rail entry for six versions and is a bookmark
        // now. Landing on Agents and making the reader click again would be
        // the merge charging them for it.
        stub();
        render(Agents, { lens: "console" });
        expect(
            await screen.findByRole("heading", { name: "Console" }),
        ).toBeInTheDocument();
        expect(screen.getByRole("tab", { name: "Console" })).toHaveAttribute(
            "aria-selected",
            "true",
        );
    });

    it("keeps the console alive across a lens switch, half-typed line and all", async () => {
        stub();
        render(Agents, { lens: "console" });
        const field = (await screen.findByRole("textbox")) as HTMLInputElement;
        await fireEvent.input(field, { target: { value: "gaps cars" } });
        await fireEvent.click(screen.getByRole("tab", { name: "Wiring" }));
        await fireEvent.click(screen.getByRole("tab", { name: "Console" }));
        // Unmounting it would have cleared this — and with it the scrollback
        // of whatever the reader was in the middle of reading.
        expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("gaps cars");
    });
});
