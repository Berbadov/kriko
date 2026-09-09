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
    compatibility: {
        running_version: "",
        minimum_version: "0.3.0",
        state: "unknown",
        detail: "",
    },
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
                        version: "0.3.0",
                    },
                ],
            }),
        });
        render(Extension);
        expect(await screen.findByText(/Connected/)).toBeTruthy();
        expect(screen.getByText(/just now/)).toBeTruthy();
        expect(screen.getByText("chrome-extension://abc")).toBeTruthy();
    });

    it("says nothing about versions when it has nothing to compare", async () => {
        // Never having reached the app is not a version problem. Telling a
        // reader who has not installed the extension that theirs is out of
        // date is worse than saying nothing at all.
        stubFetch({ "/api/extension": status({ staged: true, staged_version: "0.2.0" }) });
        render(Extension);
        await screen.findByText("/home/reader/.kriko/extension");
        expect(screen.queryByText(/older than/)).toBeNull();
        expect(screen.queryByText(/Reload it/)).toBeNull();
    });

    it("names the extension the browser is actually running when it is too old", async () => {
        // The third version, and the only one that says what is loaded. Both
        // of the others can read current while the browser holds a months-old
        // copy — that is B73, and no view could tell the difference.
        stubFetch({
            "/api/extension": status({
                staged: true,
                staged_version: "0.4.0",
                version: "0.4.0",
                compatibility: {
                    running_version: "0.1.0",
                    minimum_version: "0.3.0",
                    state: "too_old",
                    detail:
                        "The extension in your browser is 0.1.0, and this app needs "
                        + "0.3.0 or newer. Reload it from the Extension page — the copy "
                        + "on disk is already current.",
                },
            }),
        });
        render(Extension);
        expect(await screen.findByText(/browser is 0.1.0/)).toBeTruthy();
    });

    it("renders the app's sentence rather than composing its own", async () => {
        // The page holds no version rule: the floor is one number in
        // app/extension.py, and a second copy of the comparison here would
        // disagree with it without ever failing.
        stubFetch({
            "/api/extension": status({
                staged: true,
                staged_version: "0.4.0",
                compatibility: {
                    running_version: "0.3.0",
                    minimum_version: "0.3.0",
                    state: "behind",
                    detail: "A sentence the app wrote.",
                },
            }),
        });
        render(Extension);
        expect(await screen.findByText("A sentence the app wrote.")).toBeTruthy();
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
        // The sentence is derived from the status now, not written per view
        // (B72), so this asserts the shape rather than this screen's own copy.
        expect(await screen.findByRole("alert")).toBeTruthy();
        expect(screen.getByText(/bug in Kriko, not something you did/)).toBeTruthy();
    });

    it("names the sites a pack can read, which is the reader's real question", async () => {
        stubFetch({
            "/api/extension": status({ staged: true }),
            "/api/adapters": [
                {
                    id: "a1",
                    site: "example.invalid",
                    pack_id: "org.kriko.cars",
                    match: ["/listing/"],
                    labels: [],
                },
            ],
        });
        render(Extension);
        expect(await screen.findByText("example.invalid")).toBeInTheDocument();
        expect(screen.getByText(/matches \/listing\//)).toBeInTheDocument();
    });

    it("tells the reader the shortcut and where the address is changed", async () => {
        // Both are unfindable otherwise: a browser never advertises an
        // extension's keyboard command, and the options page lives two clicks
        // deep in the extension manager — which is where a reader ends up
        // only after the panel has already told them nothing is listening.
        stubFetch({ "/api/extension": status({ staged: true }), "/api/adapters": [] });
        render(Extension);
        expect(await screen.findByText("Alt")).toBeInTheDocument();
        expect(screen.getByText("K")).toBeInTheDocument();
        expect(screen.getByText(/Extension options/)).toBeInTheDocument();
    });

    it("says the panel will stay quiet when no pack ships an adapter", async () => {
        stubFetch({ "/api/extension": status({ staged: true }), "/api/adapters": [] });
        render(Extension);
        expect(
            await screen.findByText(/No installed pack ships a site adapter/),
        ).toBeInTheDocument();
    });
});

describe("the one click", () => {
    // The whole point of the button: one press, and the page can say what
    // happened without the reader having pasted anything anywhere.
    it("opens a browser and names the one it started", async () => {
        stubFetch({
            "/api/extension": status({ staged: true, staged_version: "0.2.0" }),
            "/api/extension/launch": {
                launched: true,
                browser: "/usr/bin/chromium",
                path: "/home/reader/.kriko/extension",
                profile: "/home/reader/.kriko/browser-profile",
                note: "The window is a separate browser profile.",
                error: "",
            },
        });
        render(Extension);
        fireEvent.click(
            await screen.findByRole("button", { name: /Open a browser with Kriko/ }),
        );
        expect(await screen.findByText(/Started \/usr\/bin\/chromium/)).toBeTruthy();
        // Said before the reader wonders why none of their logins are there.
        expect(screen.getByText(/separate browser profile/)).toBeTruthy();
    });

    // No Chromium is a 200 with prose, not a failure: the manual steps are
    // still the install, and a red banner would read as "this is broken".
    it("says why nothing opened and leaves the manual steps standing", async () => {
        stubFetch({
            "/api/extension": status({ staged: true, staged_version: "0.2.0" }),
            "/api/extension/launch": {
                launched: false,
                browser: "",
                path: "/home/reader/.kriko/extension",
                profile: "/home/reader/.kriko/browser-profile",
                note: "The window is a separate browser profile.",
                error: "No Chrome, Chromium, Brave or Edge found on this machine.",
            },
        });
        render(Extension);
        fireEvent.click(
            await screen.findByRole("button", { name: /Open a browser with Kriko/ }),
        );
        expect(await screen.findByText(/No Chrome, Chromium, Brave or Edge/)).toBeTruthy();
        expect(screen.getByText(/Developer mode/)).toBeTruthy();
    });

    // The button stages as part of the same request, so it has to be offered
    // before anything is on disk — that is what makes it one click.
    it("is offered before the files are staged", async () => {
        stubFetch({ "/api/extension": status() });
        render(Extension);
        expect(
            await screen.findByRole("button", { name: /Open a browser with Kriko/ }),
        ).toBeTruthy();
    });
});
