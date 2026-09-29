> TL;DR (archived 2026-09-25): Replace 443-line `app.js` with Svelte 5 + Vite + TS frontend (`ui/`, committed bundle in `src/app/web/static/`), hash router, typed client, 10 views, then `app.sqlite` history (`state.py`, lookup recording, linkable results). 14 tasks (phases 0-1).
> Constraints: no `src/kriko/` diff, no pack vocab in `ui/src/`, bind stays 127.0.0.1, Vite base `/static/`. Full file dumps trimmed below — see git history.

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

- **Python ≥ 3.14.** Use the project venv: `.venv/bin/python -m pytest`. Bare `python3` is system 3.13 and lacks the deps.

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
```
*[... 21 lines trimmed - see git history]*
```python
    assert assets.is_dir(), f"{assets} missing — run: npm --prefix ui run build"
    assert any(assets.glob("*.js")), "no built JS in the committed bundle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/app/tests/test_web_bundle.py -v`
Expected: FAIL — `index.html is not the Svelte mount point`.

- [ ] **Step 3: Create the scaffold**

`ui/package.json`:

```json
{
  "name": "kriko-ui",
  "private": true,
  "type": "module",
  "scripts": {
```
*[... 15 lines trimmed - see git history]*
```json
  }
}
```

`ui/vite.config.ts`:

```ts
/// <reference types="vitest" />
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// base is /static/ because FastAPI mounts StaticFiles at /static and serves
```
*[... 11 lines trimmed - see git history]*
```ts
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
```
*[... 7 lines trimmed - see git history]*
```json
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

Run: `.venv/bin/python -m pytest src/app/tests/test_web_bundle.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Run the whole Python suite**

Run: `.venv/bin/python -m pytest`
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
```
*[... 25 lines trimmed - see git history]*
```ts
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
```
*[... 128 lines trimmed - see git history]*
```ts
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
```
*[... 61 lines trimmed - see git history]*
```ts
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
```
*[... 18 lines trimmed - see git history]*
```ts
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
```
*[... 24 lines trimmed - see git history]*
```ts
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
```
*[... 28 lines trimmed - see git history]*
```svelte
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

Run: `npm --prefix ui test && npm --prefix ui run build && .venv/bin/python -m pytest src/app/tests/test_web_bundle.py`
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
```
*[... 35 lines trimmed - see git history]*
```ts
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
```
*[... 14 lines trimmed - see git history]*
```svelte
    <p class="state error">Could not load this view: {error.message}</p>
{/await}
```

- [ ] **Step 4: Write `Dashboard.svelte`**

```svelte
<script lang="ts">
    import Async from "../lib/Async.svelte";
    import { api } from "../lib/api";

    const load = async () => {
```
*[... 36 lines trimmed - see git history]*
```svelte
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
```
*[... 13 lines trimmed - see git history]*
```ts
    });
});
```

`ui/src/routes/Ask.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Ask from "./Ask.svelte";

const ROUTES: Record<string, unknown> = {
```
*[... 29 lines trimmed - see git history]*
```ts
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
```
*[... 16 lines trimmed - see git history]*
```ts
            .filter(([, value]) => value !== ""),
    );
```

- [ ] **Step 4: Write `ClaimCard.svelte`**

```svelte
<script lang="ts">
    import type { Claim } from "./types";

    let { claim, detailed = false }: { claim: Claim; detailed?: boolean } = $props();
</script>
```
*[... 26 lines trimmed - see git history]*
```svelte
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
```
*[... 128 lines trimmed - see git history]*
```svelte
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
```
*[... 37 lines trimmed - see git history]*
```ts
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

```
*[... 97 lines trimmed - see git history]*
```svelte
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
```
*[... 23 lines trimmed - see git history]*
```ts
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
```
*[... 137 lines trimmed - see git history]*
```svelte
    {/if}
{/await}
```

- [ ] **Step 4: Write `Coverage.svelte`**

```svelte
<script lang="ts">
    import Async from "../lib/Async.svelte";
    import { api } from "../lib/api";

    const load = async () => {
```
*[... 28 lines trimmed - see git history]*
```svelte
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
```
*[... 46 lines trimmed - see git history]*
```ts
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
```
*[... 32 lines trimmed - see git history]*
```ts
    );
}
```

- [ ] **Step 4: Write `Health.svelte`**

```svelte
<script lang="ts">
    import { api } from "../lib/api";
    import { signalNote, tieNote } from "../lib/health";
    import type { ClaimHealth, HealthTree } from "../lib/types";

```
*[... 115 lines trimmed - see git history]*
```svelte
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
```
*[... 27 lines trimmed - see git history]*
```ts
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
```
*[... 51 lines trimmed - see git history]*
```svelte
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
```
*[... 51 lines trimmed - see git history]*
```python
        f"replaces them; delete them and rebuild."
    )
```

Note the test excludes `*.test.ts`, because fixtures legitimately need realistic
values, and `ui/src/lib/types.ts` uses only generic names (`Claim`, `Subject`,
`Term`) so it passes unchanged.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/app/pipeline/tests/test_repo_invariants.py -v`
Expected: FAIL if `app.js`/`app.css` survived the build, or if any ported view kept a
literal key name. Fix the source, not the test.

- [ ] **Step 3: Delete the stale frontend**

```bash
git rm -f --ignore-unmatch src/app/web/static/app.js src/app/web/static/app.css
npm --prefix ui run build
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest src/app/pipeline/tests/test_repo_invariants.py -v`
Expected: PASS.

- [ ] **Step 5: Add the CI job**

In `.github/workflows/ci.yml`, add alongside the `extension` job:

```yaml
    ui:
        name: vitest + stale-bundle check
        runs-on: ubuntu-latest
        steps:
            - uses: actions/checkout@v4
```
*[... 14 lines trimmed - see git history]*
```yaml
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

````markdown
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
````

- [ ] **Step 8: Run everything**

Run: `.venv/bin/python -m pytest && npm --prefix ui test && npm test`
Expected: all PASS.

*[... 13 lines trimmed - see git history]*

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
```
*[... 64 lines trimmed - see git history]*
```python
    assert settings.app_state_path != settings.store_path
    assert settings.app_state_path.name == "app.sqlite"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/app/tests/test_state.py -v`
Expected: FAIL — `ImportError: cannot import name 'state'`.

- [ ] **Step 3: Write `state.py`**

```python
"""UI state: lookup history and interface settings.

This is `app/`'s own SQLite file, `~/.kriko/app.sqlite`, deliberately separate
from the engine's `knowledge.sqlite`. The engine's schema is its contract with
pack authors — every table in it is something a pack writes or a ranker reads.
```
*[... 111 lines trimmed - see git history]*
```python
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

Run: `.venv/bin/python -m pytest src/app/tests/test_state.py -v`
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
```
*[... 62 lines trimmed - see git history]*
```python
def test_history_stays_empty_when_nothing_was_asked(client):
    assert client.get("/api/history").json()["items"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest src/app/tests/test_history_api.py -v`
Expected: FAIL — `KeyError: 'lookup_id'` and 404s on `/api/history`.

- [ ] **Step 3: Write the router**

`src/app/web/routers/history.py`:

```python
"""Past answers, so a reload is not a loss.

Reads and writes `app.sqlite` only. Nothing here touches the knowledge store,
and nothing here changes a ranking — this router is the UI's memory, not the
engine's.
```
*[... 35 lines trimmed - see git history]*
```python
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

Run: `.venv/bin/python -m pytest src/app/tests/test_history_api.py -v && .venv/bin/python -m pytest`
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
```
*[... 36 lines trimmed - see git history]*
```ts
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
```
*[... 9 lines trimmed - see git history]*
```ts
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

```
*[... 24 lines trimmed - see git history]*
```svelte
    {/if}
{/await}
```

- [ ] **Step 5: Write `History.svelte`**

```svelte
<script lang="ts">
    import { api } from "../lib/api";
    import { toHash } from "./router";
    import type { HistoryItem } from "./types";

```
*[... 30 lines trimmed - see git history]*
```svelte
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
```
*[... 6 lines trimmed - see git history]*
```css
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

Run: `npm --prefix ui test && npm --prefix ui run build && .venv/bin/python -m pytest`
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

Run: `.venv/bin/python -m pytest && npm --prefix ui test && npm test`
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

