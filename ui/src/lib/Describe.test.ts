import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Describe from "./Describe.svelte";
import { stubFetch } from "./stub-fetch";

const ONE_PACK = {
    "/api/packs": [
        { pack_id: "p1", name: "Pack One", version: "1", enabled: 1, subjects: 3, claims: 4, evidence: 2, digest: "d" },
    ],
    "/api/kinds": [{ kind: "widget", pack_id: "p1" }],
    "/api/identity-keys/p1": [
        { key: "alpha_key", match_json: '{"required": true}' },
        { key: "beta_key", match_json: "{}" },
    ],
    "/api/packs/p1/vocabulary": { context_key: [{ term_id: "usage_hours", unit: "h" }] },
    "/api/subjects": [],
};

const TWO_PACKS = {
    ...ONE_PACK,
    "/api/packs": [
        ...ONE_PACK["/api/packs"],
        { pack_id: "p2", name: "Pack Two", version: "1", enabled: 1, subjects: 1, claims: 1, evidence: 1, digest: "e" },
    ],
    "/api/kinds": [{ kind: "widget", pack_id: "p1" }, { kind: "gadget", pack_id: "p2" }],
};

describe("Describe", () => {
    it("does not ask which pack when there is only one", async () => {
        stubFetch(ONE_PACK);
        render(Describe, { onResult: () => {} });
        await screen.findByLabelText(/Alpha key/);
        expect(screen.queryByLabelText("Pack")).not.toBeInTheDocument();
        expect(screen.queryByLabelText("Kind")).not.toBeInTheDocument();
    });

    it("asks which pack when there are two", async () => {
        stubFetch(TWO_PACKS);
        render(Describe, { onResult: () => {} });
        expect(await screen.findByLabelText("Pack")).toBeInTheDocument();
    });

    it("labels a pack's keys readably rather than in snake_case", async () => {
        stubFetch(ONE_PACK);
        render(Describe, { onResult: () => {} });
        expect(await screen.findByLabelText(/Alpha key/)).toBeInTheDocument();
    });

    it("holds the ask until the required keys are filled, and says which", async () => {
        stubFetch(ONE_PACK);
        render(Describe, { onResult: () => {} });
        const button = await screen.findByRole("button", { name: /What goes wrong/ });
        expect(button).toBeDisabled();
        expect(screen.getByText(/Still needed: Alpha key/)).toBeInTheDocument();
    });

    it("keeps the optional keys out of the way until asked for", async () => {
        stubFetch(ONE_PACK);
        render(Describe, { onResult: () => {} });
        await screen.findByLabelText(/Alpha key/);
        expect(screen.queryByLabelText(/Beta key/)).not.toBeInTheDocument();
        await fireEvent.click(screen.getByText(/More details/));
        expect(await screen.findByLabelText(/Beta key/)).toBeInTheDocument();
    });

    it("says there is nothing to ask when no pack is installed", async () => {
        stubFetch({ ...ONE_PACK, "/api/packs": [] });
        render(Describe, { onResult: () => {} });
        expect(await screen.findByText(/nothing to ask/)).toBeInTheDocument();
    });
});
