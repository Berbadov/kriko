import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText, copyWord } from "./clipboard";

describe("copyText", () => {
    const real = navigator.clipboard;
    afterEach(() => {
        Object.defineProperty(navigator, "clipboard", { value: real, configurable: true });
        vi.restoreAllMocks();
    });

    it("uses the async clipboard when it is allowed", async () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
        expect(await copyText("hello")).toBe(true);
        expect(writeText).toHaveBeenCalledWith("hello");
    });

    it("falls back to execCommand where the async clipboard is refused", async () => {
        Object.defineProperty(navigator, "clipboard", {
            value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
            configurable: true,
        });
        const exec = vi.fn().mockReturnValue(true);
        document.execCommand = exec as typeof document.execCommand;
        expect(await copyText("hello")).toBe(true);
        expect(exec).toHaveBeenCalledWith("copy");
        expect(document.querySelector("textarea")).toBeNull();
    });

    it("says so when neither path works, rather than looking like it did", async () => {
        Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
        document.execCommand = (() => false) as typeof document.execCommand;
        expect(await copyText("hello")).toBe(false);
        expect(copyWord(false)).toMatch(/blocked/);
    });
});
