import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Lazy from "./Lazy.svelte";

describe("Lazy", () => {
    it("renders the loaded component with its props once the import resolves", async () => {
        render(Lazy, {
            props: {
                loader: () => import("./EmptyState.svelte"),
                props: { title: "Loaded on demand" },
            },
        });
        expect(await screen.findByText("Loaded on demand")).toBeInTheDocument();
    });

    it("shows a starting state before the module resolves", () => {
        render(Lazy, {
            props: {
                loader: () => import("./EmptyState.svelte"),
                props: { title: "Loaded on demand" },
            },
        });
        expect(screen.getByText("Starting…")).toBeInTheDocument();
    });

    it("surfaces a failed chunk the way every other view does", async () => {
        render(Lazy, {
            props: { loader: () => Promise.reject(new Error("chunk failed to load")) },
        });
        expect(await screen.findByRole("alert")).toBeInTheDocument();
    });
});
