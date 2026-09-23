import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import HarnessLlm from "./HarnessLlm.svelte";

describe("HarnessLlm", () => {
    it("offers exactly what the CLI named, the default first and Other last", () => {
        render(HarnessLlm, { label: "LLM", llms: ["fable", "opus"] });
        const box = screen.getByRole("combobox", { name: "LLM" }) as HTMLSelectElement;
        expect([...box.options].map((one) => one.textContent)).toEqual([
            "CLI default", "fable", "opus", "Other…",
        ]);
        expect(screen.queryByRole("textbox")).toBeNull();
    });

    it("reports a picked name", async () => {
        const onchange = vi.fn();
        render(HarnessLlm, { label: "LLM", llms: ["fable", "opus"], onchange });
        await fireEvent.change(screen.getByRole("combobox"), { target: { value: "opus" } });
        expect(onchange).toHaveBeenCalledWith("opus");
    });

    it("types past the list only when asked to, and a stored unlisted name shows as typed", async () => {
        const onchange = vi.fn();
        render(HarnessLlm, { label: "LLM", llms: ["fable"], onchange });
        await fireEvent.change(screen.getByRole("combobox"), { target: { value: "__other__" } });
        expect(onchange).not.toHaveBeenCalled();
        const typed = screen.getByRole("textbox", { name: "LLM, typed" });
        await fireEvent.change(typed, { target: { value: " my-gateway/x " } });
        expect(onchange).toHaveBeenCalledWith("my-gateway/x");
    });

    it("a stored name the CLI no longer lists is kept visible, not silently dropped", () => {
        render(HarnessLlm, { label: "LLM", llms: ["fable"], value: "haiku" });
        expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("haiku");
    });
});
