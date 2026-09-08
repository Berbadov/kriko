import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { stubFetch, stubFetchFailing } from "../lib/stub-fetch";
import About from "./About.svelte";

const HEALTH = {
    ok: true,
    store: "/home/x/.kriko/knowledge.sqlite",
    app_state: "/home/x/.kriko/app.sqlite",
    analysis_log: "/home/x/logs/analyses.jsonl",
    version: "0.2.6",
    schema_version: 1,
    packs: [{ pack_id: "cars", version: "1.4.0" }],
    releases_url: "https://example.invalid/releases",
    log_file: "/home/x/.kriko/logs/app.log",
    log_problem: null,
    analysis_log_problem: null,
    shell_attached: true,
    extension_port: 8787,
    port_is_ours: true,
};

describe("About", () => {
    it("names the app version, the schema version and every pack version", async () => {
        stubFetch({ "/api/health": HEALTH });
        render(About);
        expect(await screen.findByText("0.2.6")).toBeInTheDocument();
        expect(screen.getByText("1.4.0")).toBeInTheDocument();
        expect(screen.getByText("cars")).toBeInTheDocument();
        expect(screen.getByText(/schema 1/i)).toBeInTheDocument();
    });

    it("names both databases, because two files is a thing an operator must know", async () => {
        stubFetch({ "/api/health": HEALTH });
        render(About);
        expect(await screen.findByText(/knowledge\.sqlite/)).toBeInTheDocument();
        expect(screen.getByText(/app\.sqlite/)).toBeInTheDocument();
    });

    it("points at the releases page rather than implying an in-app switch", async () => {
        // Self-update is real but signature-gated, and there is no version
        // picker for the binary. Saying so beats a control that does nothing.
        stubFetch({ "/api/health": HEALTH });
        render(About);
        expect(await screen.findByRole("link", { name: /all releases/i })).toHaveAttribute(
            "href",
            "https://example.invalid/releases",
        );
    });

    it("surfaces a failure rather than rendering blank", async () => {
        stubFetchFailing();
        render(About);
        expect(await screen.findByText(/could not/i)).toBeInTheDocument();
    });

    // ── the diagnostics block ────────────────────────────────────────────
    //
    // This exists because of a two-month silence: the analysis log's failures
    // were reported through `log.warning` into a root logger with no handler,
    // so nothing was written and nothing said so. The lesson was not "add a
    // log file" — it was that a fallback the reader cannot see is
    // indistinguishable from a feature that works. So the tests below are
    // about the *reasons* being visible, not the happy paths.

    it("names the log file, because that is the thing a reader sends us", async () => {
        stubFetch({ "/api/health": HEALTH });
        render(About);
        expect(await screen.findByText(/logs\/app\.log/)).toBeInTheDocument();
    });

    it("says so when nothing is being written down, and why", async () => {
        stubFetch({
            "/api/health": {
                ...HEALTH,
                log_file: null,
                log_problem: "PermissionError: [Errno 13] /opt/kriko/logs",
            },
        });
        render(About);
        expect(await screen.findByText(/Nothing is being written down/)).toBeInTheDocument();
        expect(screen.getByText(/Errno 13/)).toBeInTheDocument();
    });

    it("shows the fallback path next to the reason the configured one was refused", async () => {
        stubFetch({
            "/api/health": {
                ...HEALTH,
                analysis_log: "/home/x/.kriko/logs/analyses.jsonl",
                analysis_log_problem: "PermissionError: owned by root",
            },
        });
        render(About);
        expect(await screen.findByText(/owned by root/)).toBeInTheDocument();
    });

    it("explains an unraisable window rather than leaving it a dead button", async () => {
        // The reported bug: "Open in App opens a web page". With no shell
        // attached that is the correct answer, and this is the only place
        // that can say so.
        stubFetch({ "/api/health": { ...HEALTH, shell_attached: false } });
        render(About);
        expect(await screen.findByText(/Not attached/)).toBeInTheDocument();
        expect(screen.getByText(/opens a browser tab/)).toBeInTheDocument();
    });

    it("flags a lost extension port, which no other screen would explain", async () => {
        stubFetch({ "/api/health": { ...HEALTH, port_is_ours: false } });
        render(About);
        expect(await screen.findByText(/not held by this app/)).toBeInTheDocument();
    });
});
