import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import Extension from "./Extension.svelte";
import { stubFetch, stubFetchFailing } from "../lib/stub-fetch";

const BROWSERS = [
    { id: "chrome", name: "Chrome", url: "chrome://extensions" },
    { id: "firefox", name: "Firefox", url: "about:debugging#/runtime/this-firefox" },
];

const status = (over: Record<string, unknown> = {}) => ({
    available: true,
    version: "0.2.0",
    staged: false,
    staged_version: "",
    path: "/home/reader/.kriko/extension",
    port: 8787,
    port_is_ours: true,
    browsers: BROWSERS,
    sightings: [],
    connected: false,
    seconds_since_seen: null,
    ...over,
});

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

describe("adding the browser extension", () => {
    it("says what has not happened yet before offering the steps", async () => {
        stubFetch({ "/api/extension": status() });
        render(Extension);
        expect(await screen.findByText(/Not added yet/)).toBeTruthy();
        // The load instructions are useless — worse, confusing — while there is
        // no folder to point the browser at.
        expect(screen.queryByText(/Developer mode/)).toBeNull();
    });

    it("shows the path and the steps once the files are staged", async () => {
        stubFetch({ "/api/extension": status({ staged: true, staged_version: "0.2.0" }) });
        render(Extension);
        expect(await screen.findByText("/home/reader/.kriko/extension")).toBeTruthy();
        expect(screen.getByText(/Developer mode/)).toBeTruthy();
        expect(screen.getByText("chrome://extensions")).toBeTruthy();
    });

    it("reports a sighting as connection, because that is what it is", async () => {
        stubFetch({
            "/api/extension": status({
                staged: true,
                staged_version: "0.2.0",
                connected: true,
                seconds_since_seen: 12,
                sightings: [
                    {
                        origin: "chrome-extension://abc",
                        first_at: "2026-09-05T10:00:00+00:00",
                        last_at: "2026-09-05T10:05:00+00:00",
                        hits: 4,
                    },
                ],
            }),
        });
        render(Extension);
        expect(await screen.findByText(/Connected/)).toBeTruthy();
        expect(screen.getByText(/just now/)).toBeTruthy();
        expect(screen.getByText("chrome-extension://abc")).toBeTruthy();
    });

    it("warns when the port the extension must use is not ours", async () => {
        // The install can be flawless and still fail on every listing. Without
        // this the reader's only evidence is a red banner inside the browser,
        // and the obvious response — reinstall the extension — never works.
        stubFetch({ "/api/extension": status({ staged: true, port_is_ours: false }) });
        render(Extension);
        expect(await screen.findByText(/not held by this app/)).toBeTruthy();
    });

    it("notices a staged copy older than the one this app carries", async () => {
        stubFetch({
            "/api/extension": status({ staged: true, staged_version: "0.1.0" }),
        });
        render(Extension);
        expect(await screen.findByText(/holds extension 0.1.0/)).toBeTruthy();
    });

    it("stages on demand and re-reads the status", async () => {
        stubFetch({
            "/api/extension": status(),
            "/api/extension/stage": {
                path: "/home/reader/.kriko/extension",
                written: ["manifest.json"],
                version: "0.2.0",
            },
        });
        render(Extension);
        fireEvent.click(await screen.findByText("Add the extension"));
        const calls = () =>
            (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
        await waitFor(() =>
            expect(
                calls().some((call) => String(call[0]) === "/api/extension/stage"),
            ).toBe(true),
        );
    });

    it("says a build without the files is a packaging fault, not a user error", async () => {
        stubFetch({ "/api/extension": status({ available: false }) });
        render(Extension);
        expect(await screen.findByText(/packaging fault/)).toBeTruthy();
    });

    it("surfaces a failure to read the status instead of an empty page", async () => {
        stubFetchFailing();
        render(Extension);
        expect(await screen.findByText(/Could not read the extension status/)).toBeTruthy();
    });
});
