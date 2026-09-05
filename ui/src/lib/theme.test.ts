import { beforeEach, describe, expect, it, vi } from "vitest";
import { stubFetch, stubFetchFailing } from "./stub-fetch";
import { DEFAULT_THEME, THEMES, applyTheme, asTheme, initTheme, setTheme } from "./theme";

beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
});

describe("themes", () => {
    it("falls back to the default rather than trusting a stored string", () => {
        // The value round-trips through the settings table, which is free-form
        // JSON — a theme id that no longer exists must not leave the app
        // unpainted.
        expect(asTheme("lemonade")).toBe("lemonade");
        expect(asTheme("dracula")).toBe(DEFAULT_THEME);
        expect(asTheme(undefined)).toBe(DEFAULT_THEME);
    });

    it("names every theme the stylesheets ship", () => {
        expect(THEMES).toEqual(["slate", "lemonade"]);
    });

    it("writes the choice where CSS can see it", () => {
        applyTheme("lemonade");
        expect(document.documentElement.dataset.theme).toBe("lemonade");
    });

    it("reads the remembered theme at startup", async () => {
        stubFetch({ "/api/settings": { theme: "lemonade" } });
        expect(await initTheme()).toBe("lemonade");
        expect(document.documentElement.dataset.theme).toBe("lemonade");
    });

    it("still paints when the setting cannot be read", async () => {
        // An unreachable engine is a reason to look plain, never a reason to
        // look broken.
        stubFetchFailing();
        expect(await initTheme()).toBe(DEFAULT_THEME);
        expect(document.documentElement.dataset.theme).toBe(DEFAULT_THEME);
    });

    it("applies the switch before it tries to remember it", async () => {
        // Fire and forget: failing to persist a preference must not undo the
        // switch the reader just made.
        const fetchMock = vi.fn(async () => {
            throw new Error("offline");
        });
        vi.stubGlobal("fetch", fetchMock);
        setTheme("lemonade");
        expect(document.documentElement.dataset.theme).toBe("lemonade");
    });
});
