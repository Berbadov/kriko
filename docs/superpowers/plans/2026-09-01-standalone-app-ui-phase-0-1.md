# Standalone app — Phases 0–1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 443-line `app.js` control plane with a Svelte + Vite + TypeScript
frontend that reaches feature parity, gains a real router, and persists lookup history in
its own SQLite file — so results survive a reload and every view is linkable.

**Architecture:** A new `ui/` directory outside `src/` holds the Svelte source and builds
into `src/app/web/static/`, which is committed so the Python wheel needs no Node. The UI
talks to the existing FastAPI routers over `/api`. Phase 1 adds `src/app/web/state.py` over
`~/.kriko/app.sqlite` for history and settings, keeping interface state out of the engine's
`knowledge.sqlite`.

**Tech Stack:** Svelte 5 (runes), Vite 7, TypeScript, Vitest + jsdom +
`@testing-library/svelte`, FastAPI, SQLite (WAL), pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-standalone-app-ui-design.md`

## Global Constraints

- **Python ≥ 3.14**; the interpreter on this machine is `python3` (bare `python` is not on
  PATH). Run tests as `python3 -m pytest`.
- **Node 24 / npm 11.** CI's node job uses `node-version: "24"`.
- **`kriko/` must not be modified by this plan.** A diff under `src/kriko/` means something
  went wrong. Layering: `ui/` and `tauri/` reach `app/` over HTTP only.
- **No pack vocabulary in `ui/src/`.** No `make`, `model`, `engine_code`, `fuel`,
  `mileage`, `car`, `vehicle` in code positions. Every form field comes from
  `/api/identity-keys/{pack_id}` and `/api/packs/{pack_id}/vocabulary` at runtime. This is
  the G6 invariant; Task 10 enforces it mechanically.
- **The built bundle is committed.** `src/app/web/static/` is build output under version
  control. `ui/node_modules/` and `ui/dist/` are gitignored.
- **Bind address stays `127.0.0.1`.** No auth exists because nothing is exposed.
- **Vite `base` is `/static/`**, because FastAPI mounts `StaticFiles` at `/static` and
  serves `static/index.html` from `/`.
- **Commit style:** conventional commits, ending with
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

# Phase 0 — Svelte scaffold at feature parity

### Task 1: `ui/` scaffold that builds into the served bundle

**Files:**
- Create: `ui/package.json`, `ui/vite.config.ts`, `ui/tsconfig.json`, `ui/svelte.config.js`,
  `ui/index.html`, `ui/src/main.ts`, `ui/src/App.svelte`, `ui/src/app.css`,
  `ui/src/vite-env.d.ts`
- Modify: `.gitignore`
- Test: `src/app/tests/test_web_bundle.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a committed bundle at `src/app/web/static/index.html` referencing
  `/static/assets/*.js`; `npm --prefix ui run build` as the rebuild command.

- [ ] **Step 1: Write the failing test**

Create `src/app/tests/test_web_bundle.py`:

```python
"""The committed bundle is what `python -m app.web` actually serves.

`ui/` is the source; `src/app/web/static/` is build output under version control,
so that `pip install kriko` needs no Node and a clean checkout serves a working
UI. These tests fail when the two drift apart in the ways that matter.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


def test_index_is_the_svelte_bundle(tmp_path):
    client = TestClient(create_app(Settings(store_path=tmp_path / "k.sqlite")))
    body = client.get("/").text
    assert '<div id="app">' in body, "index.html is not the Svelte mount point"
    assert "/static/assets/" in body, "index.html references no built asset"


def test_built_assets_are_committed():
    assets = STATIC / "assets"
    assert assets.is_dir(), f"{assets} missing — run: npm --prefix ui run build"
    assert any(assets.glob("*.js")), "no built JS in the committed bundle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest src/app/tests/test_web_bundle.py -v`
Expected: FAIL — `index.html is not the Svelte mount point`.

- [ ] **Step 3: Create the scaffold**

`ui/package.json`:

```json
{
  "name": "kriko-ui",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "check": "svelte-check --tsconfig ./tsconfig.json",
    "test": "vitest run"
  },
  "devDependencies": {
    "@sveltejs/vite-plugin-svelte": "^5.0.3",
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/svelte": "^5.2.6",
    "jsdom": "^26.0.0",
    "svelte": "^5.19.0",
    "svelte-check": "^4.1.4",
    "typescript": "^5.7.3",
    "vite": "^7.0.0",
    "vitest": "^3.0.0"
  }
}
```

`ui/vite.config.ts`:

```ts
/// <reference types="vitest" />
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// base is /static/ because FastAPI mounts StaticFiles at /static and serves
// static/index.html from /. outDir is the committed bundle, deliberately
// outside ui/ so the Python wheel ships it without shipping the source.
export default defineConfig({
    plugins: [svelte()],
    base: "/static/",
    build: { outDir: "../src/app/web/static", emptyOutDir: true },
    server: { proxy: { "/api": "http://127.0.0.1:8787" } },
    test: {
        environment: "jsdom",
        globals: true,
        setupFiles: ["./src/test-setup.ts"],
    },
});
```

`ui/svelte.config.js`:

```js
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

export default { preprocess: vitePreprocess() };
```

`ui/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "types": ["vitest/globals"],
    "noEmit": true
  },
  "include": ["src/**/*.ts", "src/**/*.svelte", "vite.config.ts"]
}
```

`ui/src/vite-env.d.ts`:

```ts
/// <reference types="svelte" />
/// <reference types="vite/client" />
```

`ui/index.html`:

```html
<!doctype html>
<html lang="en">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Kriko</title>
    </head>
    <body>
        <div id="app"></div>
        <script type="module" src="/src/main.ts"></script>
    </body>
</html>
```

`ui/src/main.ts`:

```ts
import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";

export default mount(App, { target: document.getElementById("app")! });
```

`ui/src/App.svelte`:

```svelte
<script lang="ts">
</script>

<header>
    <h1>Kriko</h1>
</header>
<main></main>
```

`ui/src/app.css`: copy `src/app/web/static/app.css` verbatim for now. It is a
reasonable 331-line sheet and restyling is Phase 2, not this task.

```bash
cp src/app/web/static/app.css ui/src/app.css
```

- [ ] **Step 4: Add the setup file Vitest expects**

`ui/src/test-setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 5: Ignore node_modules, keep the bundle**

Append to `.gitignore`:

```
# UI build inputs. The build *output* (src/app/web/static/) is committed on
# purpose — the wheel ships it, so `pip install kriko` needs no Node.
ui/node_modules/
ui/.svelte-kit/
```

- [ ] **Step 6: Install and build**

Run:

```bash
npm --prefix ui install --no-audit --no-fund
npm --prefix ui run build
```

Expected: `src/app/web/static/index.html` plus `src/app/web/static/assets/*.js`.
Note `emptyOutDir: true` deletes the old `app.js`/`app.css`/`index.html` — that is
intended; they are replaced, and Task 10 confirms nothing still references them.

- [ ] **Step 7: Run test to verify it passes**

Run: `python3 -m pytest src/app/tests/test_web_bundle.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Run the whole Python suite**

Run: `python3 -m pytest`
Expected: PASS. If `src/app/tests/test_web.py` asserts on old markup, update those
assertions to the new mount point — do not restore `app.js`.

- [ ] **Step 9: Commit**

```bash
git add ui .gitignore src/app/web/static src/app/tests/test_web_bundle.py
git commit -m "$(cat <<'EOF'
feat(ui): scaffold a Svelte + Vite frontend that builds into the served bundle

ui/ is source, src/app/web/static/ is committed build output, so the wheel
ships a working UI without a Node toolchain. base=/static/ matches the
existing StaticFiles mount.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Typed API client

**Files:**
- Create: `ui/src/lib/types.ts`, `ui/src/lib/api.ts`, `ui/src/lib/api.test.ts`

**Interfaces:**
- Consumes: the scaffold from Task 1.
- Produces: `api.get<T>(path)`, `api.post<T>(path, body)`, `ApiError` with a `.status`
  number, and the named calls `api.status()`, `api.activity()`, `api.packs()`,
  `api.kinds()`, `api.identityKeys(packId)`, `api.vocabulary(packId)`, `api.lookup(req)`,
  `api.analyze(req)`, `api.subjects(q)`, `api.gaps(packId)`, `api.weakest(limit)`,
  `api.healthSubject(subjectId)`, `api.revisions(packId)`, `api.events(packId)`,
  `api.setEnabled(packId, enabled)`, `api.activate(packId, revision)`,
  `api.installPack(file)`. Every view in Tasks 4–9 uses these and never calls `fetch`.

- [ ] **Step 1: Write the failing test**

`ui/src/lib/api.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

describe("api", () => {
    beforeEach(() => vi.unstubAllGlobals());

    it("returns parsed JSON on success", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => new Response(JSON.stringify({ ok: true, packs: 2 }))),
        );
        await expect(api.status()).resolves.toEqual({ ok: true, packs: 2 });
    });

    it("throws ApiError carrying the status code", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => new Response("no adapter", { status: 404 })),
        );
        const error = await api.status().catch((e) => e);
        expect(error).toBeInstanceOf(ApiError);
        expect(error.status).toBe(404);
        expect(error.message).toContain("no adapter");
    });

    it("encodes path segments so an id with a slash cannot escape", async () => {
        const fetchMock = vi.fn(async () => new Response("[]"));
        vi.stubGlobal("fetch", fetchMock);
        await api.identityKeys("a/b");
        expect(fetchMock.mock.calls[0][0]).toBe("/api/identity-keys/a%2Fb");
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix ui test`
Expected: FAIL — cannot resolve `./api`.

- [ ] **Step 3: Write the types**

`ui/src/lib/types.ts` — mirrors the router payloads. Field names are copied from
`src/app/web/routers/*.py`; changing one there means changing it here.

```ts
export type Status = {
    ok: boolean;
    packs: number;
    enabled_packs: number;
    counts: Record<string, number>;
};

export type ActivityItem = {
    timestamp?: string;
    created_at?: string;
    url?: string;
    method?: string;
    coverage?: string;
    claim_titles?: string[];
};

export type Pack = {
    pack_id: string;
    name: string;
    version: string;
    enabled: boolean | number;
    subjects: number;
    claims: number;
    evidence: number;
    digest: string;
};

export type Kind = { kind: string; pack_id: string };
export type IdentityKey = { key: string };
export type Term = { term_id: string; unit: string };
export type Vocabulary = { context_key?: Term[] } & Record<string, Term[] | undefined>;

export type Source = {
    url?: string;
    domain: string;
    quote: string;
    stance: string;
    tier: string;
};

export type Claim = {
    title: string;
    body: string;
    advice?: string;
    severity: string;
    domain?: string;
    subject: string;
    relevance: number;
    disputed?: boolean;
    pack_id: string;
    why?: string[];
    sources?: Source[];
};

export type LookupResult = {
    method: string;
    coverage?: string;
    flags?: string[];
    claims: Claim[];
};

export type AnalyzeResult = LookupResult & {
    adapter: string;
    packs: { pack_id: string; version: string }[];
    context_units: Record<string, string>;
    identity: Record<string, unknown>;
    context: Record<string, unknown>;
    unmapped_labels: string[];
};

export type Subject = {
    subject_id?: string;
    label: string;
    kind: string;
    pack_id: string;
    claims: number;
};

export type Gap = { label: string; kind: string };

export type ClaimHealth = {
    claim_id: string;
    subject_id: string;
    subject_label: string;
    pack_id: string;
    title: string;
    refuted_by: number;
    independent_sources: number;
    best_tier: string;
    best_trust: number;
    oldest_retrieved_at: string | null;
    concern: unknown;
};

export type EvidenceRow = {
    quote: string;
    domain: string;
    tier: string;
    stance: string;
    independent: boolean;
    retrieved_at: string | null;
};

export type HealthTree = {
    label?: string;
    claims: { health: ClaimHealth; evidence: EvidenceRow[] }[];
};

export type Revision = {
    revision_id: string;
    version: string;
    content_digest: string;
    installed_at: string;
    active: boolean;
};

export type PackEvent = {
    action: string;
    created_at: string;
    revision_id: string;
    details: Record<string, unknown>;
};

export type LookupRequest = {
    kind: string;
    identity: Record<string, string | number>;
    context: Record<string, string | number>;
};

export type AnalyzeRequest = {
    url: string;
    title: string;
    description: string;
    fields: Record<string, unknown>;
};
```

- [ ] **Step 4: Write the client**

`ui/src/lib/api.ts`:

```ts
import type * as T from "./types";

export class ApiError extends Error {
    constructor(
        public status: number,
        body: string,
    ) {
        super(`${status}: ${body}`);
        this.name = "ApiError";
    }
}

async function request<R>(path: string, init?: RequestInit): Promise<R> {
    const response = await fetch(path, init);
    if (!response.ok) throw new ApiError(response.status, await response.text());
    return (await response.json()) as R;
}

const get = <R>(path: string) => request<R>(path);

const postJson = <R>(path: string, body: unknown) =>
    request<R>(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
    });

const seg = encodeURIComponent;

export const api = {
    status: () => get<T.Status>("/api/status"),
    activity: (limit = 20) =>
        get<{ items: T.ActivityItem[]; malformed: number }>(
            `/api/activity?limit=${limit}`,
        ),
    packs: () => get<T.Pack[]>("/api/packs"),
    kinds: () => get<T.Kind[]>("/api/kinds"),
    identityKeys: (packId: string) =>
        get<T.IdentityKey[]>(`/api/identity-keys/${seg(packId)}`),
    vocabulary: (packId: string) =>
        get<T.Vocabulary>(`/api/packs/${seg(packId)}/vocabulary`),
    gaps: (packId: string) => get<T.Gap[]>(`/api/packs/${seg(packId)}/gaps`),
    subjects: (q: string, limit = 60) =>
        get<T.Subject[]>(`/api/subjects?limit=${limit}&q=${encodeURIComponent(q)}`),
    weakest: (limit = 40) =>
        get<{ claims: T.ClaimHealth[] }>(`/api/health/weakest?limit=${limit}`),
    healthSubject: (subjectId: string) =>
        get<T.HealthTree>(`/api/health/subject/${seg(subjectId)}`),
    revisions: (packId: string) => get<T.Revision[]>(`/api/packs/${seg(packId)}/revisions`),
    events: (packId: string) => get<T.PackEvent[]>(`/api/packs/${seg(packId)}/events`),
    lookup: (body: T.LookupRequest) => postJson<T.LookupResult>("/api/lookup", body),
    analyze: (body: T.AnalyzeRequest) => postJson<T.AnalyzeResult>("/api/analyze", body),
    setEnabled: (packId: string, enabled: boolean) =>
        request<unknown>(`/api/packs/${seg(packId)}/enabled?enabled=${enabled}`, {
            method: "POST",
        }),
    activate: (packId: string, revision: string) =>
        request<unknown>(
            `/api/packs/${seg(packId)}/activate?revision=${encodeURIComponent(revision)}`,
            { method: "POST" },
        ),
    installPack: (file: File) =>
        request<{ pack: T.Pack; revision: T.Revision }>("/api/packs/install", {
            method: "POST",
            headers: { "X-Filename": file.name },
            body: file,
        }),
};
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm --prefix ui test`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add ui/src/lib
git commit -m "$(cat <<'EOF'
feat(ui): a typed client over the /api surface

One function per endpoint, path segments encoded, and errors carry the status
code so a 404 from /api/analyze can be told from a real failure.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Hash router and app shell

**Files:**
- Create: `ui/src/lib/router.ts`, `ui/src/lib/router.test.ts`
- Modify: `ui/src/App.svelte`

**Interfaces:**
- Consumes: Task 2's `api`.
- Produces: `parseHash(hash): Route` where `Route = { name: string; params: string[] }`;
  a `route` Svelte store exposing `$route`; `navigate(name, ...params)`. Views in Tasks
  4–9 are rendered by `App.svelte` keyed on `$route.name`.

- [ ] **Step 1: Write the failing test**

`ui/src/lib/router.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { parseHash, toHash } from "./router";

describe("parseHash", () => {
    it("defaults to ask when there is no hash", () => {
        expect(parseHash("")).toEqual({ name: "ask", params: [] });
        expect(parseHash("#")).toEqual({ name: "ask", params: [] });
        expect(parseHash("#/")).toEqual({ name: "ask", params: [] });
    });

    it("reads the view name and its params", () => {
        expect(parseHash("#/packs")).toEqual({ name: "packs", params: [] });
        expect(parseHash("#/result/abc123")).toEqual({
            name: "result",
            params: ["abc123"],
        });
    });

    it("decodes params so an id with a slash survives a round trip", () => {
        expect(parseHash(toHash("result", "a/b"))).toEqual({
            name: "result",
            params: ["a/b"],
        });
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix ui test`
Expected: FAIL — cannot resolve `./router`.

- [ ] **Step 3: Write the router**

`ui/src/lib/router.ts`:

```ts
import { readable } from "svelte/store";

export type Route = { name: string; params: string[] };

export const DEFAULT_ROUTE = "ask";

export function parseHash(hash: string): Route {
    const parts = hash
        .replace(/^#\/?/, "")
        .split("/")
        .filter(Boolean)
        .map(decodeURIComponent);
    if (!parts.length) return { name: DEFAULT_ROUTE, params: [] };
    return { name: parts[0], params: parts.slice(1) };
}

export const toHash = (name: string, ...params: string[]) =>
    `#/${[name, ...params].map(encodeURIComponent).join("/")}`;

export const navigate = (name: string, ...params: string[]) => {
    window.location.hash = toHash(name, ...params);
};

export const route = readable<Route>(
    parseHash(typeof window === "undefined" ? "" : window.location.hash),
    (set) => {
        const onChange = () => set(parseHash(window.location.hash));
        window.addEventListener("hashchange", onChange);
        return () => window.removeEventListener("hashchange", onChange);
    },
);
```

- [ ] **Step 4: Wire the shell**

`ui/src/App.svelte`:

```svelte
<script lang="ts">
    import { route, toHash } from "./lib/router";

    const VIEWS = [
        { name: "ask", label: "Ask" },
        { name: "analyze", label: "Analyze" },
        { name: "dashboard", label: "Dashboard" },
        { name: "browse", label: "Browse" },
        { name: "coverage", label: "Coverage" },
        { name: "health", label: "Health" },
        { name: "packs", label: "Packs" },
    ];
</script>

<header>
    <h1>Kriko</h1>
    <span class="sub">local product knowledge</span>
    <nav>
        {#each VIEWS as view (view.name)}
            <a
                class="tab"
                class:active={$route.name === view.name}
                href={toHash(view.name)}>{view.label}</a
            >
        {/each}
    </nav>
</header>

<main>
    {#if $route.name === "ask"}
        <section class="active"><h2>Ask</h2></section>
    {:else}
        <section class="active"><h2>{$route.name}</h2></section>
    {/if}
</main>
```

Add to `ui/src/app.css` so the ported `.tab` rules apply to anchors too:

```css
nav a.tab {
    text-decoration: none;
    display: inline-block;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm --prefix ui test && npm --prefix ui run build && python3 -m pytest src/app/tests/test_web_bundle.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ui src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): a hash router, so every view is linkable and back works

Nav becomes anchors rather than buttons: the browser's own history is the
state we were hand-rolling.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Dashboard view

**Files:**
- Create: `ui/src/routes/Dashboard.svelte`, `ui/src/lib/Async.svelte`,
  `ui/src/routes/Dashboard.test.ts`
- Modify: `ui/src/App.svelte`

**Interfaces:**
- Consumes: `api.status()`, `api.activity()`.
- Produces: `Async.svelte`, a `{#await}` wrapper taking `promise` and a `children`
  snippet, rendering `<p class="state loading">`, and on rejection
  `<p class="state error">Could not load this view: …</p>`. Tasks 5–9 all use it.

- [ ] **Step 1: Write the failing test**

`ui/src/routes/Dashboard.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard.svelte";

const STATUS = {
    ok: true,
    packs: 2,
    enabled_packs: 1,
    counts: { subjects: 12, claims: 34 },
};

function stubFetch(routes: Record<string, unknown>) {
    vi.stubGlobal(
        "fetch",
        vi.fn(async (path: string) => {
            const key = Object.keys(routes).find((r) => path.startsWith(r));
            if (!key) return new Response("not stubbed", { status: 500 });
            return new Response(JSON.stringify(routes[key]));
        }),
    );
}

describe("Dashboard", () => {
    it("shows the store counts", async () => {
        stubFetch({ "/api/status": STATUS, "/api/activity": { items: [], malformed: 0 } });
        render(Dashboard);
        expect(await screen.findByText("34")).toBeInTheDocument();
        expect(await screen.findByText("Claims")).toBeInTheDocument();
    });

    it("says so when there is no activity, rather than showing an empty table", async () => {
        stubFetch({ "/api/status": STATUS, "/api/activity": { items: [], malformed: 0 } });
        render(Dashboard);
        expect(await screen.findByText(/No analysis activity yet/)).toBeInTheDocument();
    });

    it("surfaces a failure instead of rendering blank", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
        render(Dashboard);
        expect(await screen.findByText(/Could not load this view/)).toBeInTheDocument();
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix ui test`
Expected: FAIL — cannot resolve `./Dashboard.svelte`.

- [ ] **Step 3: Write `Async.svelte`**

```svelte
<script lang="ts">
    import type { Snippet } from "svelte";

    let {
        promise,
        loading = "Loading…",
        children,
    }: {
        promise: Promise<unknown>;
        loading?: string;
        children: Snippet<[any]>;
    } = $props();
</script>

{#await promise}
    <p class="state loading">{loading}</p>
{:then value}
    {@render children(value)}
{:catch error}
    <p class="state error">Could not load this view: {error.message}</p>
{/await}
```

- [ ] **Step 4: Write `Dashboard.svelte`**

```svelte
<script lang="ts">
    import Async from "../lib/Async.svelte";
    import { api } from "../lib/api";

    const load = async () => {
        const [status, activity] = await Promise.all([api.status(), api.activity()]);
        return { status, activity };
    };
    const data = load();
</script>

<h2>Dashboard</h2>
<Async promise={data}>
    {#snippet children({ status, activity })}
        <div class="stats">
            {#each [["Packs", status.packs], ["Enabled", status.enabled_packs], ["Subjects", status.counts.subjects], ["Claims", status.counts.claims], ["Analyses", activity.items.length]] as [label, value]}
                <div class="stat"><strong>{value}</strong><span>{label}</span></div>
            {/each}
        </div>

        <h2>Recent analysis activity</h2>
        {#if activity.items.length}
            <table>
                <thead>
                    <tr><th>When</th><th>URL</th><th>Method</th><th>Coverage</th><th>Claims</th></tr>
                </thead>
                <tbody>
                    {#each activity.items as item}
                        <tr>
                            <td class="meta">{item.timestamp ?? item.created_at ?? "—"}</td>
                            <td>{item.url ?? "—"}</td>
                            <td>{item.method ?? "—"}</td>
                            <td>{item.coverage ?? "—"}</td>
                            <td class="num">{item.claim_titles?.length ?? "—"}</td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        {:else}
            <p class="state empty">No analysis activity yet.</p>
        {/if}
    {/snippet}
</Async>
```

- [ ] **Step 5: Render it from the shell**

In `ui/src/App.svelte`, import `Dashboard` and replace the placeholder branch:

```svelte
{:else if $route.name === "dashboard"}
    <section class="active"><Dashboard /></section>
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npm --prefix ui test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ui src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): port the dashboard, with a reusable Async wrapper

Loading, error and empty are three visible states rather than a blank div —
the old showError() only covered one of them per view.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Ask view — the pack-driven form

**Files:**
- Create: `ui/src/lib/fields.ts`, `ui/src/lib/fields.test.ts`,
  `ui/src/lib/ClaimCard.svelte`, `ui/src/routes/Ask.svelte`,
  `ui/src/routes/Ask.test.ts`
- Modify: `ui/src/App.svelte`

**Interfaces:**
- Consumes: `api.packs()`, `api.kinds()`, `api.identityKeys()`, `api.vocabulary()`,
  `api.lookup()`.
- Produces: `coerce(value: string): string | number` and
  `collect(entries: Record<string, string>): Record<string, string | number>` in
  `fields.ts`; `ClaimCard.svelte` taking `{ claim: Claim, detailed?: boolean }`, reused by
  Task 6.

**This is the task where the G6 invariant lives.** No identity key name may appear in the
source. The form is built from what the pack declared.

- [ ] **Step 1: Write the failing test**

`ui/src/lib/fields.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { coerce, collect } from "./fields";

describe("coerce", () => {
    it("keeps a numeric string as a number", () => {
        expect(coerce("190000")).toBe(190000);
    });
    it("keeps a non-numeric string as text", () => {
        expect(coerce("volkswagen")).toBe("volkswagen");
    });
    it("does not turn an empty string into zero", () => {
        expect(coerce("")).toBe("");
    });
});

describe("collect", () => {
    it("drops blank fields so an untouched input is not sent as an empty value", () => {
        expect(collect({ a: "x", b: "  ", c: "7" })).toEqual({ a: "x", c: 7 });
    });
});
```

`ui/src/routes/Ask.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Ask from "./Ask.svelte";

const ROUTES: Record<string, unknown> = {
    "/api/packs": [
        { pack_id: "tools", name: "Tools", version: "0.2.0", enabled: true },
    ],
    "/api/kinds": [{ kind: "product", pack_id: "tools" }],
    "/api/identity-keys/tools": [{ key: "brand" }, { key: "model" }],
    "/api/packs/tools/vocabulary": {
        context_key: [{ term_id: "usage_hours", unit: "hours" }],
    },
};

describe("Ask", () => {
    it("builds its fields from what the pack declared, not from a hardcoded list", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async (path: string) => {
                const key = Object.keys(ROUTES).find((r) => path.startsWith(r));
                return new Response(JSON.stringify(key ? ROUTES[key] : []));
            }),
        );
        render(Ask);
        expect(await screen.findByLabelText("brand")).toBeInTheDocument();
        expect(await screen.findByLabelText("model")).toBeInTheDocument();
        expect(await screen.findByLabelText(/usage_hours/)).toBeInTheDocument();
    });

    it("says so when no packs are installed", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("[]")));
        render(Ask);
        expect(await screen.findByText(/No packs installed/)).toBeInTheDocument();
    });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm --prefix ui test`
Expected: FAIL — cannot resolve `./fields` and `./Ask.svelte`.

- [ ] **Step 3: Write `fields.ts`**

```ts
/** A form value as the API should receive it.
 *
 * Identity and context values are typed by the pack, not by us: a pack may
 * declare a text attribute whose values happen to look numeric, and a context
 * key that is genuinely a number. Coercing a numeric-looking string is what
 * the old app.js did and it is the right default; the important part is that
 * an empty field stays empty rather than becoming 0.
 */
export const coerce = (value: string): string | number => {
    const trimmed = value.trim();
    if (!trimmed) return "";
    const asNumber = Number(trimmed);
    return Number.isNaN(asNumber) ? trimmed : asNumber;
};

export const collect = (
    entries: Record<string, string>,
): Record<string, string | number> =>
    Object.fromEntries(
        Object.entries(entries)
            .map(([key, value]) => [key, coerce(value)] as const)
            .filter(([, value]) => value !== ""),
    );
```

- [ ] **Step 4: Write `ClaimCard.svelte`**

```svelte
<script lang="ts">
    import type { Claim } from "./types";

    let { claim, detailed = false }: { claim: Claim; detailed?: boolean } = $props();
</script>

<article class="card">
    <h3>
        {#if claim.severity}<span class="sev {claim.severity}">{claim.severity}</span>{/if}
        {claim.title}
    </h3>
    <p>{claim.body}</p>
    {#if claim.advice}<p class="advice">{claim.advice}</p>{/if}
    <p class="meta">
        {claim.subject} · {claim.pack_id}{#if detailed} · relevance {claim.relevance}{/if}
    </p>
    {#if detailed && claim.why?.length}
        <ul class="meta">
            {#each claim.why as reason}<li>{reason}</li>{/each}
        </ul>
    {/if}
    {#if claim.sources?.length}
        <details>
            <summary class="meta">{claim.sources.length} source(s)</summary>
            {#each claim.sources as source}
                <blockquote class={source.stance === "refutes" ? "refutes" : ""}>
                    {source.quote}
                    <footer class="meta">{source.domain} · {source.tier} · {source.stance}</footer>
                </blockquote>
            {/each}
        </details>
    {/if}
</article>
```

- [ ] **Step 5: Write `Ask.svelte`**

```svelte
<script lang="ts">
    import ClaimCard from "../lib/ClaimCard.svelte";
    import { api } from "../lib/api";
    import { collect } from "../lib/fields";
    import type { LookupResult, Pack } from "../lib/types";

    let packs = $state<Pack[]>([]);
    let packId = $state("");
    let kinds = $state<string[]>([]);
    let kind = $state("");
    let identityKeys = $state<string[]>([]);
    let contextTerms = $state<{ term_id: string; unit: string }[]>([]);
    let identity = $state<Record<string, string>>({});
    let context = $state<Record<string, string>>({});
    let result = $state<LookupResult | null>(null);
    let error = $state("");
    let busy = $state(false);

    async function loadPacks() {
        packs = (await api.packs()).filter((p) => p.enabled);
        if (packs.length) {
            packId = packs[0].pack_id;
            await loadPack();
        }
    }

    async function loadPack() {
        const [allKinds, keys, vocabulary] = await Promise.all([
            api.kinds(),
            api.identityKeys(packId),
            api.vocabulary(packId),
        ]);
        kinds = allKinds.filter((k) => k.pack_id === packId).map((k) => k.kind);
        kind = kinds[0] ?? "";
        identityKeys = keys.map((k) => k.key);
        contextTerms = vocabulary.context_key ?? [];
        identity = {};
        context = {};
    }

    async function ask() {
        busy = true;
        error = "";
        result = null;
        try {
            result = await api.lookup({
                kind,
                identity: collect(identity),
                context: collect(context),
            });
        } catch (e) {
            error = (e as Error).message;
        } finally {
            busy = false;
        }
    }

    const ready = loadPacks();
</script>

<h2>Ask the installed knowledge</h2>

{#await ready}
    <p class="state loading">Loading packs…</p>
{:then}
    {#if !packs.length}
        <p class="state empty">No packs installed.</p>
    {:else}
        <div class="row">
            <div class="field">
                <label for="pack">Pack</label>
                <select id="pack" bind:value={packId} onchange={loadPack}>
                    {#each packs as pack}<option value={pack.pack_id}>{pack.name}</option>{/each}
                </select>
            </div>
            <div class="field">
                <label for="kind">Kind</label>
                <select id="kind" bind:value={kind}>
                    {#each kinds as k}<option value={k}>{k}</option>{/each}
                </select>
            </div>
        </div>

        <div class="row">
            {#each identityKeys as key (key)}
                <div class="field">
                    <label for="id-{key}">{key}</label>
                    <input id="id-{key}" bind:value={identity[key]} />
                </div>
            {/each}
        </div>

        <div class="row">
            {#each contextTerms as term (term.term_id)}
                <div class="field">
                    <label for="ctx-{term.term_id}">
                        {term.term_id} <span class="meta">{term.unit}</span>
                    </label>
                    <input id="ctx-{term.term_id}" bind:value={context[term.term_id]} />
                </div>
            {/each}
        </div>

        <div class="row">
            <button onclick={ask} disabled={busy}>{busy ? "Looking up…" : "Ask"}</button>
            <button
                class="ghost"
                onclick={() => {
                    identity = {};
                    context = {};
                    result = null;
                    error = "";
                }}>Clear</button
            >
        </div>

        <div aria-live="polite">
            {#if error}
                <p class="state error">{error}</p>
            {:else if result}
                {#if result.claims.length}
                    {#each result.claims as claim}<ClaimCard {claim} detailed />{/each}
                {:else}
                    <p class="state {result.method === 'no_match' ? 'no-match' : 'empty'}">
                        {result.method === "no_match"
                            ? "No matching subject."
                            : "No claims found."}
                    </p>
                {/if}
            {/if}
        </div>
    {/if}
{:catch e}
    <p class="state error">Could not load this view: {e.message}</p>
{/await}
```

- [ ] **Step 6: Render it from the shell**

In `App.svelte`, import `Ask` and make the `ask` branch render `<Ask />`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `npm --prefix ui test`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add ui src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): port Ask, with the pack-declared form it always had

Fields still come from /api/identity-keys and the pack vocabulary — the test
asserts it, so the domain-freedom invariant now has a check in the language
where it is easiest to break.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Analyze view

**Files:**
- Create: `ui/src/routes/Analyze.svelte`, `ui/src/routes/Analyze.test.ts`
- Modify: `ui/src/App.svelte`

**Interfaces:**
- Consumes: `api.analyze()`, `ClaimCard.svelte`, `ApiError`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

`ui/src/routes/Analyze.test.ts`:

```ts
import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Analyze from "./Analyze.svelte";

describe("Analyze", () => {
    it("refuses to submit without a URL", async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal("fetch", fetchMock);
        render(Analyze);
        await fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
        expect(await screen.findByText(/URL is required/)).toBeInTheDocument();
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it("reports malformed JSON fields before hitting the API", async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal("fetch", fetchMock);
        render(Analyze);
        await fireEvent.input(screen.getByLabelText("URL"), {
            target: { value: "https://example.invalid/1" },
        });
        await fireEvent.input(screen.getByLabelText(/Raw fields/), {
            target: { value: "{not json" },
        });
        await fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
        expect(await screen.findByText(/must be a JSON object/)).toBeInTheDocument();
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it("explains a 404 as a missing adapter, not as an error", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => new Response("no adapter", { status: 404 })),
        );
        render(Analyze);
        await fireEvent.input(screen.getByLabelText("URL"), {
            target: { value: "https://example.invalid/1" },
        });
        await fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
        expect(
            await screen.findByText(/No adapter is installed for this listing/),
        ).toBeInTheDocument();
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix ui test`
Expected: FAIL — cannot resolve `./Analyze.svelte`.

- [ ] **Step 3: Write `Analyze.svelte`**

```svelte
<script lang="ts">
    import ClaimCard from "../lib/ClaimCard.svelte";
    import { ApiError, api } from "../lib/api";
    import type { AnalyzeResult } from "../lib/types";

    let url = $state("");
    let title = $state("");
    let description = $state("");
    let rawFields = $state("{}");
    let result = $state<AnalyzeResult | null>(null);
    let message = $state("");
    let messageState = $state("error");
    let busy = $state(false);

    const SUMMARY: Record<string, string> = {
        "no-match": "No installed pack matched this listing.",
        empty: "A subject matched, but there are no claims to show.",
        results: "Known risks for this listing.",
    };

    function outcome(data: AnalyzeResult): string {
        if (data.claims.length) return "results";
        return data.coverage === "NOT_MATCHED" ? "no-match" : "empty";
    }

    async function analyze() {
        result = null;
        message = "";
        if (!url.trim()) {
            messageState = "error";
            message = "URL is required.";
            return;
        }
        let fields: Record<string, unknown>;
        try {
            fields = JSON.parse(rawFields || "{}");
        } catch (e) {
            messageState = "error";
            message = `Fields must be a JSON object: ${(e as Error).message}`;
            return;
        }
        busy = true;
        try {
            result = await api.analyze({ url: url.trim(), title, description, fields });
            messageState = outcome(result);
            message = SUMMARY[messageState];
        } catch (e) {
            messageState = e instanceof ApiError && e.status === 404 ? "unknown" : "error";
            message =
                messageState === "unknown"
                    ? "No adapter is installed for this listing."
                    : `Analysis failed: ${(e as Error).message}`;
        } finally {
            busy = false;
        }
    }
</script>

<h2>Analyze a raw listing</h2>
<p class="meta">Send the listing as captured. Pack adapters decide which fields matter.</p>

<div class="field wide">
    <label for="raw-url">URL</label>
    <input id="raw-url" type="url" bind:value={url} placeholder="https://example.invalid/item/1" />
</div>
<div class="field wide">
    <label for="raw-title">Title</label>
    <input id="raw-title" bind:value={title} />
</div>
<div class="field wide">
    <label for="raw-description">Description</label>
    <textarea id="raw-description" rows="3" bind:value={description}></textarea>
</div>
<div class="field wide">
    <label for="raw-fields">Raw fields (JSON object)</label>
    <textarea id="raw-fields" rows="6" bind:value={rawFields}></textarea>
</div>

<div class="row">
    <button onclick={analyze} disabled={busy}>{busy ? "Analyzing…" : "Analyze"}</button>
    <button
        class="ghost"
        onclick={() => {
            url = "";
            title = "";
            description = "";
            rawFields = "{}";
            result = null;
            message = "";
        }}>Clear</button
    >
</div>

<div aria-live="polite">
    {#if message}
        <div class="state {messageState}">
            <strong>{message}</strong>
            {#if result}<span> {result.coverage ?? "UNKNOWN"} · {result.method}</span>{/if}
        </div>
    {/if}
    {#each result?.claims ?? [] as claim}
        <ClaimCard {claim} detailed />
    {/each}
</div>
```

- [ ] **Step 4: Render it from the shell**

In `App.svelte`, import `Analyze` and make the `analyze` branch render `<Analyze />`.

- [ ] **Step 5: Run test to verify it passes**

Run: `npm --prefix ui test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ui src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): port Analyze, with validation before the request

A 404 means no adapter is installed, which is a coverage answer rather than a
failure; it now reads as one.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Packs and Coverage views

**Files:**
- Create: `ui/src/routes/Packs.svelte`, `ui/src/routes/Coverage.svelte`,
  `ui/src/routes/Packs.test.ts`
- Modify: `ui/src/App.svelte`

**Interfaces:**
- Consumes: `api.packs()`, `api.installPack()`, `api.setEnabled()`, `api.revisions()`,
  `api.events()`, `api.activate()`, `api.gaps()`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

`ui/src/routes/Packs.test.ts`:

```ts
import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Packs from "./Packs.svelte";

const PACK = {
    pack_id: "tools",
    name: "Tools",
    version: "0.2.0",
    enabled: true,
    subjects: 4,
    claims: 9,
    evidence: 12,
    digest: "abc123",
};

describe("Packs", () => {
    it("lists an installed pack with its counts", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([PACK]))));
        render(Packs);
        expect(await screen.findByText("Tools")).toBeInTheDocument();
        expect(await screen.findByText(/4 subjects · 9 claims/)).toBeInTheDocument();
    });

    it("refuses to install with no file chosen", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("[]")));
        render(Packs);
        await fireEvent.click(await screen.findByRole("button", { name: "Install pack" }));
        expect(await screen.findByText(/Choose a .kpack file first/)).toBeInTheDocument();
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix ui test`
Expected: FAIL — cannot resolve `./Packs.svelte`.

- [ ] **Step 3: Write `Packs.svelte`**

```svelte
<script lang="ts">
    import { api } from "../lib/api";
    import type { Pack, PackEvent, Revision } from "../lib/types";

    let packs = $state<Pack[]>([]);
    let error = $state("");
    let installMessage = $state("");
    let installState = $state("results");
    let files = $state<FileList | null>(null);
    let lifecycle = $state<Record<string, { revisions: Revision[]; events: PackEvent[] }>>({});

    async function refresh() {
        try {
            packs = await api.packs();
            error = "";
        } catch (e) {
            error = (e as Error).message;
        }
    }

    async function install() {
        const file = files?.[0];
        if (!file) {
            installState = "error";
            installMessage = "Choose a .kpack file first.";
            return;
        }
        installState = "loading";
        installMessage = `Installing ${file.name}…`;
        try {
            const data = await api.installPack(file);
            installState = "results";
            installMessage = `Installed ${data.pack.name} ${data.pack.version}`;
            await refresh();
        } catch (e) {
            installState = "error";
            installMessage = `Install failed: ${(e as Error).message}`;
        }
    }

    async function toggle(pack: Pack) {
        await api.setEnabled(pack.pack_id, !pack.enabled);
        await refresh();
    }

    async function loadLifecycle(packId: string) {
        const [revisions, events] = await Promise.all([
            api.revisions(packId),
            api.events(packId),
        ]);
        lifecycle = { ...lifecycle, [packId]: { revisions, events } };
    }

    const ready = refresh();
</script>

<h2>Installed packs</h2>

<div class="row">
    <input type="file" accept=".kpack,application/octet-stream" bind:files />
    <button onclick={install}>Install pack</button>
</div>
{#if installMessage}
    <p class="state {installState}" aria-live="polite">{installMessage}</p>
{/if}

{#await ready}
    <p class="state loading">Loading packs…</p>
{:then}
    {#if error}
        <p class="state error">Could not load this view: {error}</p>
    {:else if !packs.length}
        <p class="state empty">No packs installed.</p>
    {:else}
        {#each packs as pack (pack.pack_id)}
            <article class="card">
                <h3>{pack.name} <span class="badge">{pack.version}</span></h3>
                <p class="meta">
                    {pack.pack_id} · {pack.subjects} subjects · {pack.claims} claims ·
                    {pack.evidence} evidence · digest {pack.digest}
                </p>
                <div class="row">
                    <button onclick={() => toggle(pack)}>
                        {pack.enabled ? "Disable" : "Enable"}
                    </button>
                    <button class="ghost" onclick={() => loadLifecycle(pack.pack_id)}>
                        Lifecycle
                    </button>
                    {#if !pack.enabled}<span class="meta">disabled</span>{/if}
                </div>
                {#if lifecycle[pack.pack_id]}
                    {@const life = lifecycle[pack.pack_id]}
                    <details open>
                        <summary>Revision history ({life.revisions.length})</summary>
                        {#if life.revisions.length}
                            <table>
                                <thead>
                                    <tr><th>Revision</th><th>Installed</th><th>State</th><th></th></tr>
                                </thead>
                                <tbody>
                                    {#each life.revisions as revision}
                                        <tr>
                                            <td>
                                                {revision.version}
                                                <span class="meta">
                                                    {revision.content_digest.slice(0, 12)}
                                                </span>
                                            </td>
                                            <td class="meta">{revision.installed_at}</td>
                                            <td>{revision.active ? "active" : "retained"}</td>
                                            <td>
                                                {#if !revision.active}
                                                    <button
                                                        onclick={async () => {
                                                            await api.activate(
                                                                pack.pack_id,
                                                                revision.revision_id,
                                                            );
                                                            await refresh();
                                                            await loadLifecycle(pack.pack_id);
                                                        }}>Activate</button
                                                    >
                                                {/if}
                                            </td>
                                        </tr>
                                    {/each}
                                </tbody>
                            </table>
                        {:else}
                            <p class="state empty">No retained revisions.</p>
                        {/if}
                        <p class="meta">{life.events.length} lifecycle event(s)</p>
                        {#each life.events.slice(-5).reverse() as event}
                            <div class="event">
                                <strong>{event.action}</strong> · {event.created_at}
                                <span class="meta">{event.revision_id}</span>
                            </div>
                        {/each}
                    </details>
                {/if}
            </article>
        {/each}
    {/if}
{/await}
```

- [ ] **Step 4: Write `Coverage.svelte`**

```svelte
<script lang="ts">
    import Async from "../lib/Async.svelte";
    import { api } from "../lib/api";

    const load = async () => {
        const packs = await api.packs();
        return Promise.all(
            packs.map(async (pack) => ({ pack, gaps: await api.gaps(pack.pack_id) })),
        );
    };
    const data = load();
</script>

<h2>Coverage gaps</h2>
<Async promise={data}>
    {#snippet children(sections)}
        {#if !sections.length}
            <p class="state empty">No packs installed.</p>
        {/if}
        {#each sections as { pack, gaps } (pack.pack_id)}
            <article class="card">
                <h3>{pack.name} <span class="badge">{gaps.length} gap(s)</span></h3>
                {#if gaps.length}
                    <ul>
                        {#each gaps as gap}
                            <li>{gap.label} <span class="meta">({gap.kind})</span></li>
                        {/each}
                    </ul>
                {:else}
                    <p class="state empty">No coverage gaps reported.</p>
                {/if}
            </article>
        {/each}
    {/snippet}
</Async>
```

- [ ] **Step 5: Render both from the shell**

Add `packs` and `coverage` branches to `App.svelte`.

- [ ] **Step 6: Run test to verify it passes**

Run: `npm --prefix ui test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ui src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): port Packs and Coverage

Lifecycle is per-pack local state now, so opening one pack's revisions no
longer re-binds every Activate button on the page.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Health view

**Files:**
- Create: `ui/src/lib/health.ts`, `ui/src/lib/health.test.ts`,
  `ui/src/routes/Health.svelte`
- Modify: `ui/src/App.svelte`

**Interfaces:**
- Consumes: `api.weakest()`, `api.healthSubject()`.
- Produces: `signalNote(claim: ClaimHealth): string` and `tieNote(claims: ClaimHealth[]):
  string` — the two pieces of copy that were tuned in commits `8e7369b` and `f121dee` and
  must survive the port unchanged in meaning.

- [ ] **Step 1: Write the failing test**

`ui/src/lib/health.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { signalNote, tieNote } from "./health";
import type { ClaimHealth } from "./types";

const claim = (over: Partial<ClaimHealth> = {}): ClaimHealth => ({
    claim_id: "c1",
    subject_id: "s1",
    subject_label: "Subject",
    pack_id: "tools",
    title: "A claim",
    refuted_by: 0,
    independent_sources: 3,
    best_tier: "manufacturer",
    best_trust: 0.9,
    oldest_retrieved_at: "2026-01-01",
    concern: [0, 3, 0.9, "2026-01-01"],
    ...over,
});

describe("signalNote", () => {
    it("names contradiction first, ahead of thinness", () => {
        expect(signalNote(claim({ refuted_by: 2, independent_sources: 1 }))).toBe(
            "a source in the pack contradicts this claim",
        );
    });
    it("calls a single-source claim thin", () => {
        expect(signalNote(claim({ independent_sources: 1 }))).toBe(
            "only one independent source supports this",
        );
    });
    it("calls a low-tier best source weak", () => {
        expect(signalNote(claim({ best_trust: 0.3 }))).toBe(
            "the best supporting source is a low-trust tier",
        );
    });
    it("says nothing about a well-supported claim", () => {
        expect(signalNote(claim())).toBe("");
    });
});

describe("tieNote", () => {
    it("is silent when nothing ties", () => {
        expect(tieNote([claim(), claim({ concern: [1, 1, 0.2, null] })])).toBe("");
    });
    it("warns when the top of the list ties on every signal", () => {
        expect(tieNote([claim(), claim(), claim({ concern: [9] })])).toContain(
            "2 of the claims shown tie on every signal",
        );
    });
    it("is silent on an empty list", () => {
        expect(tieNote([])).toBe("");
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix ui test`
Expected: FAIL — cannot resolve `./health`.

- [ ] **Step 3: Write `health.ts`**

```ts
import type { ClaimHealth } from "./types";

const NOTE = {
    refuted: "a source in the pack contradicts this claim",
    thin: "only one independent source supports this",
    weak: "the best supporting source is a low-trust tier",
};

/** The one signal worth naming for this claim, worst first.
 *
 * Order matters and is not cosmetic: a contradicted claim is a different
 * problem from a thinly sourced one, and showing "only one source" on a claim
 * we hold a rebuttal to would bury the more serious signal.
 */
export function signalNote(claim: ClaimHealth): string {
    if (claim.refuted_by > 0) return NOTE.refuted;
    if (claim.independent_sources <= 1) return NOTE.thin;
    if (claim.best_trust < 0.5) return NOTE.weak;
    return "";
}

/** Warn when the worst claims are indistinguishable on every signal.
 *
 * Without this the reader takes the row order for a ranking. The list is the
 * worst N, not the whole ranking, and rows tied on all four signals are in
 * arbitrary order relative to each other.
 */
export function tieNote(claims: ClaimHealth[]): string {
    if (!claims.length) return "";
    const top = JSON.stringify(claims[0].concern);
    const tied = claims.filter((c) => JSON.stringify(c.concern) === top).length;
    if (tied < 2) return "";
    return (
        `${tied} of the claims shown tie on every signal — contradiction, ` +
        `independent sources, best-source trust and staleness alike — so their ` +
        `order relative to each other is arbitrary. This list is not the whole ` +
        `ranking, just the worst ${claims.length}.`
    );
}
```

- [ ] **Step 4: Write `Health.svelte`**

```svelte
<script lang="ts">
    import { api } from "../lib/api";
    import { signalNote, tieNote } from "../lib/health";
    import type { ClaimHealth, HealthTree } from "../lib/types";

    let claims = $state<ClaimHealth[]>([]);
    let tree = $state<HealthTree | null>(null);
    let askedClaimId = $state("");
    let error = $state("");

    async function load() {
        try {
            claims = (await api.weakest(40)).claims;
        } catch (e) {
            error = (e as Error).message;
        }
    }

    async function openTree(claim: ClaimHealth) {
        askedClaimId = claim.claim_id;
        tree = await api.healthSubject(claim.subject_id);
    }

    const ready = load();
</script>

<h2>Claim health</h2>
<p class="meta">
    The weakest-supported claims we ship, worst first. Contradicted, then fewest
    independent sources, then weakest best source, then stalest. No combined score — each
    signal is its own column.
    <em>Independence and stance are flags the pack author supplied, not verified facts.</em>
    Claims with no sources at all are not listed here — that is a coverage question,
    answered by the Coverage tab, not a weakness one.
</p>
{#if tieNote(claims)}<p class="meta">{tieNote(claims)}</p>{/if}

{#await ready}
    <p class="state loading">Loading…</p>
{:then}
    {#if error}
        <p class="state error">Could not load this view: {error}</p>
    {:else if !claims.length}
        <p class="state empty">No sourced claims installed yet.</p>
    {:else}
        <table>
            <thead>
                <tr>
                    <th>Claim</th><th>Contradicted</th><th>Independent sources</th>
                    <th>Best source</th><th>Last retrieved</th><th></th>
                </tr>
            </thead>
            <tbody>
                {#each claims as claim (claim.claim_id)}
                    <tr class={claim.refuted_by > 0 ? "concern" : ""}>
                        <td>
                            {claim.title}
                            <div class="meta">{claim.subject_label} · {claim.pack_id}</div>
                            {#if signalNote(claim)}
                                <div class="meta">{signalNote(claim)}</div>
                            {/if}
                        </td>
                        <td class="num signal">
                            {#if claim.refuted_by > 0}
                                <span class="badge">{claim.refuted_by} refuting</span>
                            {:else}—{/if}
                        </td>
                        <td class="num signal">{claim.independent_sources}</td>
                        <td class="signal">
                            {claim.best_tier}
                            <span class="meta">{claim.best_trust.toFixed(2)}</span>
                        </td>
                        <td class="signal {claim.oldest_retrieved_at ? '' : 'stale'}">
                            {claim.oldest_retrieved_at ?? "unknown"}
                        </td>
                        <td><button onclick={() => openTree(claim)}>Evidence</button></td>
                    </tr>
                {/each}
            </tbody>
        </table>

        {#if tree}
            <article class="card">
                <h3>
                    {tree.label ?? "Subject"}
                    <span class="badge">{tree.claims.length} claim(s)</span>
                </h3>
                {#each tree.claims as node (node.health.claim_id)}
                    {@const asked = node.health.claim_id === askedClaimId}
                    <details open={asked} class={asked ? "asked" : ""}>
                        <summary>
                            {#if asked}<span class="badge">Asked about</span>{/if}
                            {node.health.title}
                            <span class="meta">
                                {node.health.independent_sources} source(s) ·
                                {node.health.best_tier}
                            </span>
                        </summary>
                        {#if node.evidence.length}
                            {#each node.evidence as row}
                                <blockquote class={row.stance === "refutes" ? "refutes" : ""}>
                                    {row.quote}
                                    <footer class="meta">
                                        {row.domain} · {row.tier} · {row.stance}{row.independent
                                            ? ""
                                            : " · not independent"} · retrieved
                                        {row.retrieved_at ?? "unknown"}
                                    </footer>
                                </blockquote>
                            {/each}
                        {:else}
                            <p class="state empty">
                                No sources — this claim rests on an interval or a rule, not
                                a citation.
                            </p>
                        {/if}
                    </details>
                {/each}
            </article>
        {/if}
    {/if}
{/await}
```

- [ ] **Step 5: Render it from the shell**

Add the `health` branch to `App.svelte`.

- [ ] **Step 6: Run test to verify it passes**

Run: `npm --prefix ui test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ui src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): port Health, with the tie and signal copy under test

The copy in 8e7369b and f121dee was corrected twice; extracting it into
health.ts means the next port cannot quietly undo either fix.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Browse view

**Files:**
- Create: `ui/src/routes/Browse.svelte`, `ui/src/routes/Browse.test.ts`
- Modify: `ui/src/App.svelte`

**Interfaces:**
- Consumes: `api.subjects(q)`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

`ui/src/routes/Browse.test.ts`:

```ts
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Browse from "./Browse.svelte";

describe("Browse", () => {
    it("lists subjects and re-queries as you type", async () => {
        const fetchMock = vi.fn(
            async () =>
                new Response(
                    JSON.stringify([
                        { label: "Makita DHP484", kind: "product", pack_id: "tools", claims: 3 },
                    ]),
                ),
        );
        vi.stubGlobal("fetch", fetchMock);
        render(Browse);
        expect(await screen.findByText("Makita DHP484")).toBeInTheDocument();

        await fireEvent.input(screen.getByLabelText("Search subjects"), {
            target: { value: "makita" },
        });
        await waitFor(() =>
            expect(
                fetchMock.mock.calls.some(([path]) => String(path).includes("q=makita")),
            ).toBe(true),
        );
    });

    it("says so when nothing matches", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("[]")));
        render(Browse);
        expect(await screen.findByText(/No matching subjects/)).toBeInTheDocument();
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix ui test`
Expected: FAIL — cannot resolve `./Browse.svelte`.

- [ ] **Step 3: Write `Browse.svelte`**

```svelte
<script lang="ts">
    import { api } from "../lib/api";
    import type { Subject } from "../lib/types";

    let query = $state("");
    let subjects = $state<Subject[]>([]);
    let error = $state("");
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function search() {
        try {
            subjects = await api.subjects(query.trim());
            error = "";
        } catch (e) {
            error = (e as Error).message;
        }
    }

    function onInput() {
        clearTimeout(timer);
        timer = setTimeout(search, 180);
    }

    const ready = search();
</script>

<div class="row">
    <div class="field">
        <label for="search">Search subjects</label>
        <input id="search" bind:value={query} oninput={onInput} style="min-width: 280px" />
    </div>
</div>

{#await ready}
    <p class="state loading">Loading…</p>
{:then}
    {#if error}
        <p class="state error">Could not load this view: {error}</p>
    {:else if subjects.length}
        <table>
            <thead>
                <tr><th>Subject</th><th>Kind</th><th>Pack</th><th>Claims</th></tr>
            </thead>
            <tbody>
                {#each subjects as subject}
                    <tr>
                        <td>{subject.label}</td>
                        <td>{subject.kind}</td>
                        <td>{subject.pack_id}</td>
                        <td class="num">{subject.claims}</td>
                    </tr>
                {/each}
            </tbody>
        </table>
    {:else}
        <p class="state empty">No matching subjects.</p>
    {/if}
{/await}
```

- [ ] **Step 4: Render it from the shell**

Add the `browse` branch to `App.svelte`.

- [ ] **Step 5: Run test to verify it passes**

Run: `npm --prefix ui test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ui src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): port Browse

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Retire `app.js`, and enforce the invariants mechanically

**Files:**
- Delete: any surviving `src/app/web/static/app.js`, `src/app/web/static/app.css`
- Modify: `src/app/pipeline/tests/test_repo_invariants.py`, `.github/workflows/ci.yml`,
  `CONTRIBUTING.md`, `pyproject.toml`
- Test: `src/app/pipeline/tests/test_repo_invariants.py`

**Interfaces:**
- Consumes: everything above.
- Produces: a CI job named `ui` running `npm --prefix ui test`, `npm --prefix ui run
  build`, and `git diff --exit-code src/app/web/static`.

- [ ] **Step 1: Write the failing test**

Append to `src/app/pipeline/tests/test_repo_invariants.py`:

```python
UI_SRC = REPO / "ui" / "src"

# Pack vocabulary. The engine's domain-freedom is checked by
# src/kriko/tests/test_core_is_domain_free.py walking kriko/'s AST; the same
# failure mode is now reachable in TypeScript, where no Python test looks. One
# `if (key === "make")` in a form component and G6 is over at the DOM boundary.
PACK_VOCABULARY = (
    "make",
    "model",
    "engine_code",
    "gearbox",
    "fuel",
    "mileage",
    "vehicle",
    "car",
)


def test_ui_contains_no_pack_vocabulary():
    """ui/ builds its forms from pack rows, never from a hardcoded key list.

    Identity keys come from /api/identity-keys/{pack_id} and context keys from
    /api/packs/{pack_id}/vocabulary. A literal key name in the frontend is the
    same scalability bug as a Python constant, in a language the AST test does
    not read.
    """
    if not UI_SRC.is_dir():
        return
    pattern = re.compile(rf"\b(?:{'|'.join(PACK_VOCABULARY)})\b", re.IGNORECASE)
    hits = []
    for path in sorted(UI_SRC.rglob("*")):
        if path.suffix not in {".ts", ".svelte"} or path.name.endswith(".test.ts"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(REPO)}:{n}: {line.strip()}")
    assert not hits, (
        "pack vocabulary in ui/src — build the field from the pack's own rows "
        "(/api/identity-keys, /api/packs/{id}/vocabulary) instead:\n"
        + "\n".join(hits)
    )


def test_no_hand_written_frontend_survives():
    """app.js was replaced by ui/, not supplemented by it.

    Two frontends in one directory is how the built bundle silently stops
    being what the server serves.
    """
    stale = [
        p.name
        for p in (REPO / "src" / "app" / "web" / "static").glob("*")
        if p.name in {"app.js", "app.css"}
    ]
    assert not stale, (
        f"{stale} still in the served static dir — the Svelte build in ui/ "
        f"replaces them; delete them and rebuild."
    )
```

Note the test excludes `*.test.ts`, because fixtures legitimately need realistic
values, and `ui/src/lib/types.ts` uses only generic names (`Claim`, `Subject`,
`Term`) so it passes unchanged.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest src/app/pipeline/tests/test_repo_invariants.py -v`
Expected: FAIL if `app.js`/`app.css` survived the build, or if any ported view kept a
literal key name. Fix the source, not the test.

- [ ] **Step 3: Delete the stale frontend**

```bash
git rm -f --ignore-unmatch src/app/web/static/app.js src/app/web/static/app.css
npm --prefix ui run build
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest src/app/pipeline/tests/test_repo_invariants.py -v`
Expected: PASS.

- [ ] **Step 5: Add the CI job**

In `.github/workflows/ci.yml`, add alongside the `extension` job:

```yaml
    ui:
        name: vitest + stale-bundle check
        runs-on: ubuntu-latest
        steps:
            - uses: actions/checkout@v4

            - uses: actions/setup-node@v4
              with:
                  node-version: "24"

            - run: npm --prefix ui install --no-audit --no-fund
            - run: npm --prefix ui test

            # src/app/web/static/ is committed build output: the wheel ships it,
            # so a stale bundle means `pip install kriko` serves a UI nobody can
            # reproduce from source. Rebuild and require a clean diff.
            - name: Bundle is not stale
              run: |
                  npm --prefix ui run build
                  git diff --exit-code -- src/app/web/static \
                    || { echo "::error::src/app/web/static is stale — run 'npm --prefix ui run build' and commit"; exit 1; }
```

- [ ] **Step 6: Keep `ui/` out of the wheel**

In `pyproject.toml`, confirm `[tool.setuptools.packages.find]` has `where = ["src"]` —
it does, so `ui/` is already excluded. Add the bundle as package data so a wheel
carries it:

```toml
[tool.setuptools.package-data]
"app.web" = ["static/**/*"]
```

- [ ] **Step 7: Document the rebuild step**

In `CONTRIBUTING.md`, under the test-gate section, add:

```markdown
### The frontend

`ui/` is the Svelte source; `src/app/web/static/` is its committed build output — the
wheel ships the bundle so `pip install kriko` needs no Node. After changing anything
under `ui/src/`:

```bash
npm --prefix ui test
npm --prefix ui run build      # rewrites src/app/web/static/
git add ui src/app/web/static
```

CI rebuilds and fails on a dirty diff, so a forgotten rebuild is caught rather than
shipped.
```

- [ ] **Step 8: Run everything**

Run: `python3 -m pytest && npm --prefix ui test && npm test`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat(ui): retire app.js and enforce the frontend invariants in CI

Two mechanisms rather than two rules: a grep that fails when pack vocabulary
appears in ui/src, and a CI rebuild that fails when the committed bundle is
stale. Neither needs anyone to remember anything.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

# Phase 1 — Persistence and linkable results

### Task 11: `app.sqlite` — the interface's own store

**Files:**
- Create: `src/app/web/state.py`, `src/app/tests/test_state.py`
- Modify: `src/app/web/settings.py`, `src/app/web/deps.py`, `src/app/web/app.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Settings.app_state_path: Path` (env `KRIKO_APP_STATE`, default
    `DEFAULT_STORE.parent / "app.sqlite"`).
  - `state.connect(path) -> sqlite3.Connection` — creates the schema, WAL on,
    `row_factory = sqlite3.Row`.
  - `state.record_lookup(conn, *, source: str, label: str, request: dict, response: dict) -> str`
    returning a `lookup_id`.
  - `state.recent(conn, limit: int = 20) -> list[dict]` — newest first, each
    `{lookup_id, created_at, source, label, claim_count}`.
  - `state.get_lookup(conn, lookup_id: str) -> dict | None` — the full row with
    `request` and `response` decoded.
  - `state.delete_lookup(conn, lookup_id: str) -> bool`.
  - `get_app_state` FastAPI dependency in `deps.py`.

- [ ] **Step 1: Write the failing test**

`src/app/tests/test_state.py`:

```python
"""The interface's own store, deliberately not the engine's.

Lookup history is an app/ concern. Putting it in knowledge.sqlite would add the
first tables in kriko/store/schema.sql that nothing in kriko/ reads — a layering
violation expressed as schema rather than as an import. The practical version:
uninstalling a pack must not drop your history, and a history table must never
appear in a .kpack diff.
"""

from app.web import state
from app.web.settings import Settings


def test_records_and_reads_back_a_lookup(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    lookup_id = state.record_lookup(
        conn,
        source="ask",
        label="Makita DHP484",
        request={"kind": "product", "identity": {"brand": "makita"}},
        response={"method": "exact", "claims": [{"title": "A"}, {"title": "B"}]},
    )
    row = state.get_lookup(conn, lookup_id)
    assert row["label"] == "Makita DHP484"
    assert row["source"] == "ask"
    assert row["request"]["kind"] == "product"
    assert len(row["response"]["claims"]) == 2


def test_recent_is_newest_first_and_counts_claims(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    for name in ("first", "second"):
        state.record_lookup(
            conn,
            source="ask",
            label=name,
            request={},
            response={"claims": [{"title": "x"}]},
        )
    rows = state.recent(conn)
    assert [r["label"] for r in rows] == ["second", "first"]
    assert rows[0]["claim_count"] == 1


def test_recent_honours_its_limit(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    for n in range(5):
        state.record_lookup(
            conn, source="ask", label=str(n), request={}, response={"claims": []}
        )
    assert len(state.recent(conn, limit=2)) == 2


def test_missing_lookup_is_none_not_an_error(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    assert state.get_lookup(conn, "nope") is None


def test_delete_reports_whether_it_deleted_anything(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    lookup_id = state.record_lookup(
        conn, source="ask", label="x", request={}, response={"claims": []}
    )
    assert state.delete_lookup(conn, lookup_id) is True
    assert state.delete_lookup(conn, lookup_id) is False


def test_settings_keeps_ui_state_beside_the_store_but_separate(tmp_path):
    settings = Settings()
    assert settings.app_state_path != settings.store_path
    assert settings.app_state_path.name == "app.sqlite"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest src/app/tests/test_state.py -v`
Expected: FAIL — `ImportError: cannot import name 'state'`.

- [ ] **Step 3: Write `state.py`**

```python
"""UI state: lookup history and interface settings.

This is `app/`'s own SQLite file, `~/.kriko/app.sqlite`, deliberately separate
from the engine's `knowledge.sqlite`. The engine's schema is its contract with
pack authors — every table in it is something a pack writes or a ranker reads.
A `lookups` table there would be the first one nobody in `kriko/` uses, and the
precedent that admits the next one.

Two consequences settle it: uninstalling a pack must not drop your history, and
a history row must never affect a pack's `content_digest`.
"""

import json
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS lookups (
    lookup_id     TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    source        TEXT NOT NULL,
    label         TEXT NOT NULL,
    request_json  TEXT NOT NULL,
    response_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lookups_created_at ON lookups (created_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def record_lookup(
    conn: sqlite3.Connection,
    *,
    source: str,
    label: str,
    request: dict,
    response: dict,
) -> str:
    lookup_id = secrets.token_hex(8)
    conn.execute(
        "INSERT INTO lookups"
        " (lookup_id, created_at, source, label, request_json, response_json)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            lookup_id,
            datetime.now(UTC).isoformat(timespec="seconds"),
            source,
            label,
            json.dumps(request),
            json.dumps(response),
        ),
    )
    conn.commit()
    return lookup_id


def _decode(row: sqlite3.Row) -> dict:
    return {
        "lookup_id": row["lookup_id"],
        "created_at": row["created_at"],
        "source": row["source"],
        "label": row["label"],
        "request": json.loads(row["request_json"]),
        "response": json.loads(row["response_json"]),
    }


def recent(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Newest first. `claim_count` is computed here so the list view does not
    have to parse every stored response just to show a number."""
    rows = conn.execute(
        "SELECT lookup_id, created_at, source, label, response_json FROM lookups"
        " ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (max(0, limit),),
    ).fetchall()
    out = []
    for row in rows:
        response = json.loads(row["response_json"])
        out.append(
            {
                "lookup_id": row["lookup_id"],
                "created_at": row["created_at"],
                "source": row["source"],
                "label": row["label"],
                "claim_count": len(response.get("claims") or []),
            }
        )
    return out


def get_lookup(conn: sqlite3.Connection, lookup_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM lookups WHERE lookup_id = ?", (lookup_id,)
    ).fetchone()
    return _decode(row) if row else None


def delete_lookup(conn: sqlite3.Connection, lookup_id: str) -> bool:
    cursor = conn.execute("DELETE FROM lookups WHERE lookup_id = ?", (lookup_id,))
    conn.commit()
    return cursor.rowcount > 0
```

- [ ] **Step 4: Extend `Settings`**

In `src/app/web/settings.py`, add the field and the env default:

```python
@dataclass(frozen=True)
class Settings:
    store_path: Path = DEFAULT_STORE
    packs_dir: Path = Path("packs")
    title: str = "Kriko"
    analysis_log_path: Path = Path("logs/analyses.jsonl")
    #: UI state — history and interface settings. Beside the engine's store in
    #: ~/.kriko, never inside it: see app/web/state.py for why.
    app_state_path: Path = DEFAULT_STORE.parent / "app.sqlite"
```

and in `from_env`:

```python
            "app_state_path": Path(
                os.environ.get("KRIKO_APP_STATE", DEFAULT_STORE.parent / "app.sqlite")
            ),
```

- [ ] **Step 5: Add the dependency**

Append to `src/app/web/deps.py`:

```python
from app.web import state


def get_app_state(request: Request):
    """One connection per request to the UI's own SQLite file."""
    conn = state.connect(request.app.state.settings.app_state_path)
    try:
        yield conn
    finally:
        conn.close()
```

- [ ] **Step 6: Report both paths from the liveness endpoint**

In `src/app/web/app.py`, add to the `liveness()` payload:

```python
            "app_state": str(app.state.settings.app_state_path),
```

Two SQLite files is a thing an operator has to know about; `/api/health` already
names the store, so it is the honest place to name the other one.

- [ ] **Step 7: Run test to verify it passes**

Run: `python3 -m pytest src/app/tests/test_state.py -v`
Expected: PASS (6 passed).

- [ ] **Step 8: Commit**

```bash
git add src/app/web/state.py src/app/web/settings.py src/app/web/deps.py src/app/web/app.py src/app/tests/test_state.py
git commit -m "$(cat <<'EOF'
feat(web): ~/.kriko/app.sqlite for interface state

History is an app/ concern, so it gets app/'s own file. Uninstalling a pack
must not drop your history and a history row must not touch a content_digest.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Record every lookup, and serve it back

**Files:**
- Create: `src/app/web/routers/history.py`, `src/app/tests/test_history_api.py`
- Modify: `src/app/web/routers/query.py`, `src/app/web/routers/analyze.py`,
  `src/app/web/app.py`

**Interfaces:**
- Consumes: `state.record_lookup`, `state.recent`, `state.get_lookup`,
  `state.delete_lookup`, `get_app_state`.
- Produces:
  - `POST /api/lookup` and `POST /api/analyze` responses gain `"lookup_id": str`.
  - `GET /api/history?limit=20` → `{"items": [...]}`.
  - `GET /api/lookup/{lookup_id}` → the stored `{lookup_id, created_at, source, label,
    request, response}`, or 404.
  - `DELETE /api/history/{lookup_id}` → `{"deleted": true}` or 404.

- [ ] **Step 1: Write the failing test**

`src/app/tests/test_history_api.py`:

```python
"""A result you cannot reopen is a result you did not get.

The old dashboard rendered into innerHTML and forgot; a tab switch or a reload
destroyed the answer. These tests pin the fix at the API boundary, where the UI
can rely on it.
"""

import pytest
from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def client(tmp_path):
    return TestClient(
        create_app(
            Settings(
                store_path=tmp_path / "knowledge.sqlite",
                app_state_path=tmp_path / "app.sqlite",
                analysis_log_path=tmp_path / "analyses.jsonl",
            )
        )
    )


def test_a_lookup_is_recorded_and_reopenable(client):
    posted = client.post(
        "/api/lookup",
        json={"kind": "product", "identity": {"brand": "acme"}, "context": {}},
    )
    assert posted.status_code == 200
    lookup_id = posted.json()["lookup_id"]
    assert lookup_id

    reopened = client.get(f"/api/lookup/{lookup_id}")
    assert reopened.status_code == 200
    assert reopened.json()["request"]["identity"] == {"brand": "acme"}
    assert reopened.json()["response"]["method"] == posted.json()["method"]


def test_history_lists_newest_first(client):
    for brand in ("one", "two"):
        client.post(
            "/api/lookup",
            json={"kind": "product", "identity": {"brand": brand}, "context": {}},
        )
    items = client.get("/api/history").json()["items"]
    assert len(items) == 2
    assert "two" in items[0]["label"]


def test_an_unknown_lookup_is_a_404_not_a_500(client):
    assert client.get("/api/lookup/deadbeef").status_code == 404


def test_a_lookup_can_be_forgotten(client):
    lookup_id = client.post(
        "/api/lookup",
        json={"kind": "product", "identity": {"brand": "acme"}, "context": {}},
    ).json()["lookup_id"]
    assert client.delete(f"/api/history/{lookup_id}").status_code == 200
    assert client.get(f"/api/lookup/{lookup_id}").status_code == 404
    assert client.delete(f"/api/history/{lookup_id}").status_code == 404


def test_history_stays_empty_when_nothing_was_asked(client):
    assert client.get("/api/history").json()["items"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest src/app/tests/test_history_api.py -v`
Expected: FAIL — `KeyError: 'lookup_id'` and 404s on `/api/history`.

- [ ] **Step 3: Write the router**

`src/app/web/routers/history.py`:

```python
"""Past answers, so a reload is not a loss.

Reads and writes `app.sqlite` only. Nothing here touches the knowledge store,
and nothing here changes a ranking — this router is the UI's memory, not the
engine's.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api", tags=["history"])


def label_for(identity: dict, fallback: str = "lookup") -> str:
    """A human-readable name for a lookup, built from whatever the pack's
    identity keys happen to be. The engine has no title for a query and this
    must stay true for any category, so the values are joined in the order the
    caller sent them rather than picked by name."""
    values = [str(v) for v in identity.values() if str(v).strip()]
    return " ".join(values) or fallback


@router.get("/history")
def history(limit: int = Query(20, ge=1, le=200), app_state=Depends(get_app_state)):
    return {"items": state.recent(app_state, limit)}


@router.get("/lookup/{lookup_id}")
def get_lookup(lookup_id: str, app_state=Depends(get_app_state)):
    row = state.get_lookup(app_state, lookup_id)
    if row is None:
        raise HTTPException(404, f"no such lookup: {lookup_id}")
    return row


@router.delete("/history/{lookup_id}")
def forget(lookup_id: str, app_state=Depends(get_app_state)):
    if not state.delete_lookup(app_state, lookup_id):
        raise HTTPException(404, f"no such lookup: {lookup_id}")
    return {"deleted": True, "lookup_id": lookup_id}
```

- [ ] **Step 4: Record from `/api/lookup`**

In `src/app/web/routers/query.py`, add the imports and record before returning. The
existing handler builds a payload dict; capture it, record, then return with the id:

```python
from app.web import state
from app.web.deps import get_app_state, get_store
from app.web.routers.history import label_for
```

Change the signature to
`def run_lookup(body: LookupRequest, store=Depends(get_store), app_state=Depends(get_app_state)):`
and replace the final `return payload` with:

```python
    payload["lookup_id"] = state.record_lookup(
        app_state,
        source="ask",
        label=label_for(body.identity),
        request=body.model_dump(),
        response=payload,
    )
    return payload
```

If the current handler returns a literal dict rather than a named `payload`, bind it to
`payload` first — do not duplicate the dict.

- [ ] **Step 5: Record from `/api/analyze`**

In `src/app/web/routers/analyze.py`, add the same imports, add
`app_state=Depends(get_app_state)` to the `analyze` signature, and immediately before
`return payload` (after the JSONL log call, which stays exactly as it is):

```python
    payload["lookup_id"] = state.record_lookup(
        app_state,
        source="analyze",
        label=body.title.strip() or body.url,
        request=body.model_dump(),
        response=payload,
    )
    return payload
```

The JSONL analysis log is untouched: it is the parity corpus and the demand signal, a
different artifact from the UI's history, and collapsing the two would make clearing
your history delete research data.

- [ ] **Step 6: Register the router**

In `src/app/web/app.py`, import `history` and add `history.router` to the tuple.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python3 -m pytest src/app/tests/test_history_api.py -v && python3 -m pytest`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/app/web/routers src/app/web/app.py src/app/tests/test_history_api.py
git commit -m "$(cat <<'EOF'
feat(web): record every lookup and serve it back by id

/api/lookup and /api/analyze now return a lookup_id, and /api/lookup/{id}
reopens it. The JSONL analysis log is left alone — it is the parity corpus,
not the UI's memory, and clearing history must not delete research data.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: History in the UI, and a linkable result route

**Files:**
- Create: `ui/src/routes/Result.svelte`, `ui/src/lib/History.svelte`,
  `ui/src/routes/Result.test.ts`
- Modify: `ui/src/lib/api.ts`, `ui/src/lib/types.ts`, `ui/src/routes/Ask.svelte`,
  `ui/src/routes/Analyze.svelte`, `ui/src/App.svelte`

**Interfaces:**
- Consumes: `GET /api/history`, `GET /api/lookup/{id}`, `DELETE /api/history/{id}`.
- Produces: the `#/result/:lookup_id` route; `api.history()`, `api.getLookup(id)`,
  `api.forget(id)`.

- [ ] **Step 1: Write the failing test**

`ui/src/routes/Result.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Result from "./Result.svelte";

const STORED = {
    lookup_id: "abc123",
    created_at: "2026-09-01T10:00:00+00:00",
    source: "ask",
    label: "Makita DHP484",
    request: { kind: "product", identity: { brand: "makita" } },
    response: {
        method: "exact",
        coverage: "RISKS_FOUND",
        claims: [
            {
                title: "Chuck runout",
                body: "Wears with charge cycles.",
                severity: "high",
                subject: "Makita DHP484",
                pack_id: "tools",
                relevance: 0.27,
            },
        ],
    },
};

describe("Result", () => {
    it("renders a stored lookup from its id", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(STORED))));
        render(Result, { props: { lookupId: "abc123" } });
        expect(await screen.findByText("Chuck runout")).toBeInTheDocument();
        expect(await screen.findByText(/Makita DHP484/)).toBeInTheDocument();
    });

    it("says the lookup is gone rather than rendering blank", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => new Response("no such lookup", { status: 404 })),
        );
        render(Result, { props: { lookupId: "gone" } });
        expect(await screen.findByText(/no longer in your history/)).toBeInTheDocument();
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix ui test`
Expected: FAIL — cannot resolve `./Result.svelte`.

- [ ] **Step 3: Extend the types and client**

In `ui/src/lib/types.ts`:

```ts
export type HistoryItem = {
    lookup_id: string;
    created_at: string;
    source: string;
    label: string;
    claim_count: number;
};

export type StoredLookup = {
    lookup_id: string;
    created_at: string;
    source: string;
    label: string;
    request: Record<string, unknown>;
    response: LookupResult;
};
```

Add `lookup_id?: string` to `LookupResult`.

In `ui/src/lib/api.ts`, add to the `api` object:

```ts
    history: (limit = 20) =>
        get<{ items: T.HistoryItem[] }>(`/api/history?limit=${limit}`),
    getLookup: (lookupId: string) => get<T.StoredLookup>(`/api/lookup/${seg(lookupId)}`),
    forget: (lookupId: string) =>
        request<{ deleted: boolean }>(`/api/history/${seg(lookupId)}`, {
            method: "DELETE",
        }),
```

- [ ] **Step 4: Write `Result.svelte`**

```svelte
<script lang="ts">
    import ClaimCard from "../lib/ClaimCard.svelte";
    import { ApiError, api } from "../lib/api";
    import type { StoredLookup } from "../lib/types";

    let { lookupId }: { lookupId: string } = $props();

    const load = async (): Promise<StoredLookup> => api.getLookup(lookupId);
    const stored = load();
</script>

{#await stored}
    <p class="state loading">Loading…</p>
{:then result}
    <h2>{result.label}</h2>
    <p class="meta">
        {result.source} · {result.created_at} · {result.response.method}
        {#if result.response.coverage} · {result.response.coverage}{/if}
    </p>
    {#if result.response.claims.length}
        {#each result.response.claims as claim}<ClaimCard {claim} detailed />{/each}
    {:else}
        <p class="state empty">This lookup returned no claims.</p>
    {/if}
{:catch error}
    {#if error instanceof ApiError && error.status === 404}
        <p class="state empty">That lookup is no longer in your history.</p>
    {:else}
        <p class="state error">Could not load this view: {error.message}</p>
    {/if}
{/await}
```

- [ ] **Step 5: Write `History.svelte`**

```svelte
<script lang="ts">
    import { api } from "../lib/api";
    import { toHash } from "./router";
    import type { HistoryItem } from "./types";

    let items = $state<HistoryItem[]>([]);

    export async function refresh() {
        items = (await api.history()).items;
    }

    async function forget(item: HistoryItem) {
        await api.forget(item.lookup_id);
        await refresh();
    }

    const ready = refresh();
</script>

<aside class="history">
    <h3>Recent</h3>
    {#await ready then}
        {#if items.length}
            <ul>
                {#each items as item (item.lookup_id)}
                    <li>
                        <a href={toHash("result", item.lookup_id)}>{item.label}</a>
                        <span class="meta">{item.claim_count} claim(s) · {item.source}</span>
                        <button class="ghost" onclick={() => forget(item)}>Forget</button>
                    </li>
                {/each}
            </ul>
        {:else}
            <p class="state empty">Nothing asked yet.</p>
        {/if}
    {/await}
</aside>
```

Add to `ui/src/app.css`:

```css
.history {
    border-left: 1px solid #e5e5e5;
    padding-left: 1rem;
}
.history ul {
    list-style: none;
    padding: 0;
}
.history li {
    display: grid;
    gap: 0.125rem;
    margin-bottom: 0.75rem;
}
```

- [ ] **Step 6: Navigate to the result after a lookup**

In `Ask.svelte`, import `navigate` from `../lib/router` and, at the end of `ask()`'s
`try` block, replace the inline result rendering with a redirect:

```ts
            const data = await api.lookup({
                kind,
                identity: collect(identity),
                context: collect(context),
            });
            if (data.lookup_id) navigate("result", data.lookup_id);
            else result = data;
```

Keep the inline `result` branch as the fallback for a server that did not return an id,
so the view degrades rather than showing nothing. Do the same in `Analyze.svelte`,
guarding on `result.lookup_id`.

- [ ] **Step 7: Route it and show history in the shell**

In `App.svelte`, add:

```svelte
{:else if $route.name === "result"}
    <section class="active"><Result lookupId={$route.params[0]} /></section>
```

and render `<History />` beside `<main>` for the `ask` and `analyze` routes.

- [ ] **Step 8: Run tests to verify they pass**

Run: `npm --prefix ui test && npm --prefix ui run build && python3 -m pytest`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add ui src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): history and a linkable result route

An answer now has a URL, survives a reload, and can be reopened from the
sidebar — the single biggest thing the old dashboard could not do.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: Update the docs and the backlog

**Files:**
- Modify: `docs/INTERNALS.md`, `docs/ARCHITECTURE.md`, `README.md`, `backlog.md`,
  `done.md`, `CLAUDE.md`

- [ ] **Step 1: Record the new layer**

In `CLAUDE.md`'s layering diagram and `docs/ARCHITECTURE.md`, add:

```
ui/        the frontend — Svelte source, built into src/app/web/static/.
           Talks to app/ over HTTP; imports nothing Python. Contains no pack
           vocabulary (enforced by test_repo_invariants.py).
```

- [ ] **Step 2: Document the two SQLite files**

In `docs/INTERNALS.md` and `docs/USAGE.md`, state that `~/.kriko/knowledge.sqlite` is the
engine's store and `~/.kriko/app.sqlite` is the interface's history and settings, that
`/api/health` reports both, and that deleting `app.sqlite` loses history and nothing else.

- [ ] **Step 3: Move the finished work**

Add to `done.md` with today's date and the commit range: the Svelte rewrite at parity, the
router, `app.sqlite`, and the history API. Add to `backlog.md` a new item for Phases 2–5
pointing at the spec, noting that Phase 4 (jobs) is what closes G6's web-first delivery
constraint.

- [ ] **Step 4: Run the full suite one more time**

Run: `python3 -m pytest && npm --prefix ui test && npm test`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
docs: record the ui/ layer, the second SQLite file, and phases 2-5

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Out of scope for this plan

Deliberately deferred to their own plans, each named in the spec:

- **Phase 2** — buyer/author projections and the report screen.
- **Phase 3** — input overhaul (URL paste, autocomplete, no raw JSON textarea).
- **Phase 4** — the jobs backend and Jobs view; research and pack builds from the browser.
  This is what closes G6's web-first delivery constraint.
- **Phase 5** — the Tauri shell, the PyInstaller sidecar, and installers.
