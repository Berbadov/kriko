import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import Check from "./Check.svelte";

// The guided form's own behaviour is Describe.test.ts's subject now; what is
// left here is the link path, the unreadable-site answer, and which of the two
// paths the page leads with.
const ROUTES: Record<string, unknown> = {
    "/api/adapters": [
        { id: "a1", site: "example.test", pack_id: "tools", match: [], labels: [] },
    ],
    "/api/packs": [
        { pack_id: "tools", name: "Tools", version: "1", enabled: 1, subjects: 1, claims: 1, evidence: 1, digest: "d" },
    ],
    "/api/kinds": [{ kind: "product", pack_id: "tools" }],
    "/api/identity-keys/tools": [
        { key: "brand", match_json: '{"required": true}' },
        { key: "model", match_json: "{}" },
    ],
    "/api/packs/tools/vocabulary": { context_key: [] },
    "/api/subjects": [],
};

describe("Check", () => {
    it("leads with the one input that does the work", async () => {
        stubFetch(ROUTES);
        render(Check);
        expect(await screen.findByLabelText(/web address/i)).toBeInTheDocument();
    });

    it("asks for a link before trying to read nothing", async () => {
        stubFetch(ROUTES);
        render(Check);
        await fireEvent.click(
            await screen.findByRole("button", { name: /check this listing/i }),
        );
        expect(
            await screen.findByText(/Paste the listing's web address first/),
        ).toBeInTheDocument();
    });

    it("names the sites it can read when the pasted host is not one", async () => {
        stubFetch({ ...ROUTES, "/api/analyze": { status: 404, body: "no adapter" } });
        render(Check);
        await fireEvent.input(await screen.findByLabelText(/web address/i), {
            target: { value: "https://unknown.test/x" },
        });
        await fireEvent.click(
            await screen.findByRole("button", { name: /check this listing/i }),
        );
        expect(
            await screen.findByText(/No installed pack can read that site/),
        ).toBeInTheDocument();
        expect(await screen.findByText(/example.test/)).toBeInTheDocument();
    });

    it("offers the describe-it path below the link path, not instead of it", async () => {
        stubFetch(ROUTES);
        render(Check);
        expect(await screen.findByText(/No link\?/)).toBeInTheDocument();
    });

    it("says what the page does, and that nothing leaves the machine", async () => {
        stubFetch(ROUTES);
        render(Check);
        expect(await screen.findByText(/nothing sent anywhere/)).toBeInTheDocument();
    });

    it("hosts the staged form rather than owning a flat one", async () => {
        // Describe's disclosure is the observable evidence that the guided form
        // is the extracted component and not this page's own fifteen inputs.
        stubFetch(ROUTES);
        render(Check);
        expect(await screen.findByText(/More details/)).toBeInTheDocument();
    });

    it("offers the scraped-fields editor only in author mode, and never as JSON", async () => {
        stubFetch(ROUTES);
        const { unmount } = render(Check, { props: { mode: "buyer" } });
        await screen.findByLabelText(/web address/i);
        expect(screen.queryByText(/Page fields/)).not.toBeInTheDocument();
        unmount();
        render(Check, { props: { mode: "author" } });
        expect(await screen.findByText(/Page fields/)).toBeInTheDocument();
        expect(screen.queryByLabelText(/JSON/i)).not.toBeInTheDocument();
    });
});
