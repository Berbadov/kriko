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
});
