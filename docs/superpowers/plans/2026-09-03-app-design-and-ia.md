> TL;DR (archived 2026-09-25): Frontend-only product pass (20 tasks): tokenised design system (4 stylesheets + colour-literal guard), grouped nav rail (CHECK/KNOWLEDGE/SYSTEM), verdict report + print stylesheet, staged describe-it form (`humanize`), first-run Welcome, side-by-side compare. Decisions 1-8 in spec `2026-09-03-app-design-and-ia.md`.
> No Python diff, no new endpoint, no ranking change, no webfonts. Full file dumps trimmed below — see git history.

# Kriko app — design system, IA, and four features: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Kriko's functional-but-capability-shaped frontend into a product: a
grouped navigation rail, a tokenised design system, a report with a verdict you can
print, a staged describe-it form, a first-run screen, and side-by-side comparison.

**Architecture:** Everything lands in `ui/` (Svelte 5 + Vite + TypeScript) plus the
committed build output in `src/app/web/static/`. No Python is edited and no new endpoint
is added — every feature was checked against `ui/src/lib/api.ts` and is served by an
endpoint that already exists. Styling stays global and class-based (there are no
component `<style>` blocks in this codebase and this plan adds none); the one 501-line
`app.css` becomes four files under `ui/src/styles/` with a guard test that keeps colour
literals out of everything except `tokens.css`.

**Tech Stack:** Svelte 5 (runes: `$state`, `$derived`, `$props`, `$effect`), TypeScript,
Vite 7, Vitest 3 + `@testing-library/svelte` 5 in jsdom, plain CSS custom properties.

**Spec:** `docs/superpowers/specs/2026-09-03-app-design-and-ia.md` — read it before
Task 1. Every decision number cited below (`Decision 4`, etc.) refers to that document.

## Global Constraints

Every task's requirements implicitly include all of these.

- **No Python diff.** Not `src/kriko/`, not `src/app/`. A change to either means the task
  was misread. The only non-`ui/` paths this plan writes are `src/app/web/static/**`
  (build output) and the docs listed in Task 20.
- **No new HTTP endpoint.** Use only the methods already on `api` in `ui/src/lib/api.ts`.
- **No pack vocabulary anywhere in `ui/src/**/*.ts` or `ui/src/**/*.svelte`, except files
  ending `.test.ts`.** Enforced by `test_ui_contains_no_pack_vocabulary` in
  `src/app/pipeline/tests/test_repo_invariants.py`, which greps those globs
  case-insensitively. Field labels come from the API at runtime. This is why the shared
  test helper in Task 2 holds *no fixture data* — a helper cannot be named `.test.ts`,
  so fixtures stay inside the test files that need them.
- **No webfonts.** No `@import`, no `<link>` to a font host. System stack only:
  `ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif` and
  `ui-monospace, SFMono-Regular, Menlo, monospace`. The app must render styled with no
  network.
- **No cost, price, or repair-estimate figure anywhere.** `Claim` carries no such field;
  inventing one is a fabrication.
- **No change to ranking or claim selection.** `orderClaims` and `groupByDomain` in
  `ui/src/lib/report.ts` are not to be re-tuned. Backlog B36 stays open.
- **No mobile layout.** Desktop and desktop-sized browser only. The existing
  `@media (max-width: 900px)` collapse for the history rail is kept; nothing new is added.
- **Commands, verbatim:**
  - unit tests: `npm --prefix ui test`
  - a single file: `npm --prefix ui test -- src/lib/report.test.ts`
  - types: `npm --prefix ui run check`
  - bundle: `npm --prefix ui run build`
  - Python suite: `.venv/bin/python -m pytest -q`
- **`pytest` runs locally before every push** (CLAUDE.md's app-first phase). `ci.yml` —
  which holds vitest *and* the stale-bundle comparison — is paused to
  `workflow_dispatch`, so neither fires on a push. Rebuilding and committing the bundle
  is a local obligation in every phase, not a follow-up.
- **Commit per task.** Message style in this repo is a subject line plus a body that says
  *why*, in prose. Match it.

---

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `ui/src/styles/tokens.css` | **Create.** The only file allowed to contain a colour literal: neutral ramp, accent, severity, spacing, type, radii, focus, motion. | 1 |
| `ui/src/styles/base.css` | **Create.** Reset, `body`, headings, links, `:focus-visible`, reduced motion. | 1 |
| `ui/src/styles/components.css` | **Create.** Button, field, card, badge, table, state, stat, rail, report classes. | 1 |
| `ui/src/styles/tokens.test.ts` | **Create.** Guard: no colour literal outside `tokens.css`; no undefined `var()`. | 1 |
| `ui/src/app.css` | **Delete.** Split into the three above. | 1 |
| `ui/src/main.ts` | **Modify.** Import the new stylesheets in cascade order. | 1 |
| `ui/src/lib/stub-fetch.ts` | **Create.** `stubFetch(routes)` — shared by every component test. No fixtures. | 2 |
| `ui/src/lib/shell/NavGroup.svelte` | **Create.** One titled group of rail links. | 3 |
| `ui/src/lib/shell/Sidebar.svelte` | **Create.** Brand, the three groups, mode switch in the footer. | 3 |
| `ui/src/lib/shell/nav.ts` | **Create.** The route table: groups, labels, which are author-only. | 3 |
| `ui/src/lib/EmptyState.svelte` | **Create.** Replaces scattered `p.state.empty` with a titled, explained, optionally actionable state. | 4 |
| `ui/src/App.svelte` | **Modify.** Rail + workspace layout, route table from `nav.ts`, first-run gate. | 5, 17 |
| `ui/src/lib/History.svelte` | **Modify.** Mode-preserving links; renders as a rail panel or a full page. | 6 |
| `ui/src/routes/Overview.svelte` | **Create.** The author's control room. Replaces `Dashboard.svelte`. | 7 |
| `ui/src/routes/Dashboard.svelte`, `Dashboard.test.ts` | **Delete.** | 7 |
| `ui/src/routes/Subjects.svelte`, `Subjects.test.ts` | **Create** (renamed from `Browse`). | 8 |
| `ui/src/routes/Browse.svelte`, `Browse.test.ts` | **Delete.** | 8 |
| `ui/src/lib/verdict.ts` | **Create.** Pure verdict derivation from a `LookupResult`. | 9 |
| `ui/src/lib/Verdict.svelte` | **Create.** Renders the verdict; hosts the Print action. | 10 |
| `ui/src/lib/Report.svelte` | **Modify.** Hosts `Verdict`; reading measure. | 10 |
| `ui/src/lib/ClaimCard.svelte` | **Modify.** Severity rule, ask block, author extras behind a disclosure. | 11 |
| `ui/src/styles/print.css` | **Create.** The report as paper. | 12 |
| `ui/src/lib/fields.ts` | **Modify.** Add `humanize(key)`. | 13 |
| `ui/src/lib/Describe.svelte` | **Create.** The staged describe-it form. | 14 |
| `ui/src/routes/Check.svelte` | **Modify.** Hero for paste-a-link; hosts `Describe`; author page-fields moved below. | 15 |
| `ui/src/routes/Welcome.svelte` | **Create.** First run: offer the index, or the local file, or dismissal. | 16 |
| `ui/src/lib/compare.ts` | **Create.** Pure alignment of two claim lists. | 18 |
| `ui/src/routes/Compare.svelte` | **Create.** Two columns + pickers. | 19 |
| `src/app/web/static/**` | **Rebuild + commit** at the end of every phase. | all |

---

## Task 1: The design system — three stylesheets and the guard that keeps them honest

`ui/src/app.css` is 501 lines with eleven colour variables, twenty-nine colour literals,
no spacing or type scale, `.row` and `.badge` each defined twice, and two colours
(`#e5e5e5`, `#b3261e`) hardcoded outside the theme so light mode has holes. Spec
Decision 3.

The test is written first and is the *mechanism*, not a description: it reads the
stylesheets off disk and fails on a colour literal outside `tokens.css`. That is the
class of bug that put `#e5e5e5` in `.history`, and it will catch the next one.

**Files:**
- Create: `ui/src/styles/tokens.css`
- Create: `ui/src/styles/base.css`
- Create: `ui/src/styles/components.css`
- Test: `ui/src/styles/tokens.test.ts`
- Modify: `ui/src/main.ts:3`
- Delete: `ui/src/app.css`

**Interfaces:**
- Consumes: nothing.
- Produces: the token names every later task uses. Spacing `--s-1`…`--s-7`
  (4/8/12/16/24/32/48px). Type `--t-xs`/`--t-sm`/`--t-base`/`--t-md`/`--t-lg`/`--t-xl`
  (12/13/15/17/21/28px) each paired with `--lh-xs`…`--lh-xl`. Neutrals `--n-0`…`--n-9`
  (`--n-0` = page ground, `--n-9` = strongest text). Semantic aliases `--bg`, `--panel`,
  `--panel-2`, `--line`, `--text`, `--dim`, `--accent`, `--accent-ink`, `--high`,
  `--medium`, `--low`, and their `-soft` background variants `--high-soft`,
  `--medium-soft`, `--low-soft`, `--accent-soft`. Also `--radius`, `--radius-sm`,
  `--ring`, `--dur-fast`, `--dur-slow`, `--measure` (68ch), `--font-sans`, `--font-mono`.
  Class names in `components.css` keep every name `app.css` already used, so no existing
  markup breaks in this task.

- [ ] **Step 1: Write the failing guard test**

Create `ui/src/styles/tokens.test.ts`:

```ts
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

```
*[... 38 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 2: Run it and watch it fail for the right reason**

Run: `npm --prefix ui test -- src/styles/tokens.test.ts`
Expected: FAIL — `ENOENT` on the `ui/src/styles` directory, because it does not exist yet.

- [ ] **Step 3: Write `tokens.css`**

Create `ui/src/styles/tokens.css`. This is the only file in the repo that may name a
colour.

```css
/* The single place a colour is named.
 *
 * Eleven flat variables were why a new surface had no background to use and
 * someone reached for a literal. A ramp means the next panel already has a
 * value, and `styles/tokens.test.ts` fails the build if anyone reaches past it.
```
*[... 100 lines trimmed - see git history]*
```css
    }
}
```

- [ ] **Step 4: Write `base.css`**

Create `ui/src/styles/base.css`:

```css
*,
*::before,
*::after {
    box-sizing: border-box;
}
```
*[... 53 lines trimmed - see git history]*
```css
    }
}
```

- [ ] **Step 5: Write `components.css`**

Create `ui/src/styles/components.css` by porting every rule from `ui/src/app.css` with
these four changes and no others:

1. Every literal colour becomes a token (`#e5e5e5` in `.history` → `var(--line)`;
   `#b3261e` in `tr.concern` → `var(--high)`; every `rgba(...)` severity background →
   its `--*-soft` token; `.bar`'s and `.log`'s `rgba(127,127,127,…)` → `var(--panel-2)`).
2. Every hardcoded px spacing becomes an `--s-*` token; every hardcoded font-size becomes
   a `--t-*` token.
3. The duplicate `.row` and `.badge` rules collapse to one each. Keep the *union* of the
   two `.row` definitions — `display:flex; gap: var(--s-3); flex-wrap: wrap;
   align-items: flex-end;` — and add a `.row.center { align-items: center; }` modifier
   for the four places that wanted `align-items: center`.
4. `.tab.active` uses `color: var(--accent-ink)` instead of `#fff`, which is why light
   mode currently prints white-on-light-blue.

Every class name that exists in `app.css` must still exist here. No markup changes in
this task; a rename would make the diff unreviewable.

- [ ] **Step 6: Point `main.ts` at the new sheets and delete the old one**

Modify `ui/src/main.ts`:

```ts
import { mount } from "svelte";
import App from "./App.svelte";
// Cascade order is load-bearing: tokens define, base resets, components use.
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";

export default mount(App, { target: document.getElementById("app")! });
```

Then: `rm ui/src/app.css`

- [ ] **Step 7: Run the guard test and the whole suite**

Run: `npm --prefix ui test`
Expected: PASS, including all three `tokens.test.ts` cases and every pre-existing test.
If the "references no custom property it never defines" case fails, the named token is a
typo in `components.css` — fix the reference, do not add the token.

- [ ] **Step 8: Typecheck and build**

Run: `npm --prefix ui run check && npm --prefix ui run build`
Expected: no errors; `src/app/web/static/` is rewritten.

- [ ] **Step 9: Open every screen in both themes**

Run `.venv/bin/python -m app.web` and visit `http://127.0.0.1:8787`. Open all eight
current destinations (`check`, `dashboard`, `browse`, `coverage`, `jobs`, `health`,
`packs`, and a `result`) in light and dark — toggle your OS appearance, since the app has
no in-app theme switch. This phase is not done until each has been seen in both. A ramp
swap regresses the surface nobody opens.

- [ ] **Step 10: Commit**

```bash
git add ui/src/styles ui/src/main.ts src/app/web/static
git rm ui/src/app.css
git commit -m "$(cat <<'EOF'
refactor(ui): one stylesheet with no scales becomes four with a guard

```
*[... 15 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 2: A shared `stubFetch`, so nine test files stop each defining it

`Dashboard.test.ts` defines `stubFetch` locally; every test written from Task 4 onward
needs it. Extracting it now avoids nine copies.

**Files:**
- Create: `ui/src/lib/stub-fetch.ts`
- Modify: `ui/src/routes/Dashboard.test.ts:11-21`

**Interfaces:**
- Consumes: nothing.
- Produces: `stubFetch(routes: Record<string, unknown>): void` — installs a `fetch` stub
  keyed by path prefix, longest match first; a route whose value is
  `{ status: number, body: string }` answers with that failure instead of a JSON payload —
  that prefix-matches a request path against `routes` keys and returns the JSON value;
  an unmatched path returns HTTP 500 with body `not stubbed`, so a test that forgot a
  route fails loudly rather than hanging. Also `stubFetchFailing(status = 500): void`.

The file is named `stub-fetch.ts`, **not** `stub-fetch.test.ts`, so vitest does not try
to run it — which is exactly why it must hold **no fixture data**:
`test_ui_contains_no_pack_vocabulary` exempts only `*.test.ts`, so realistic identity
keys in this file would fail the Python suite. Fixtures stay in the test files.

- [ ] **Step 1: Write the helper**

Create `ui/src/lib/stub-fetch.ts`:

```ts
import { vi } from "vitest";

/** Stub `fetch` by path prefix.
 *
 * Holds no fixture data on purpose: this file is not a `.test.ts`, so
```
*[... 36 lines trimmed - see git history]*
```ts
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status })));
}
```

- [ ] **Step 2: Rewrite `Dashboard.test.ts` to use it**

In `ui/src/routes/Dashboard.test.ts`, delete the local `function stubFetch(...)` block
and its now-unused `vi` usages, and replace the imports with:

```ts
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { stubFetch, stubFetchFailing } from "../lib/stub-fetch";
import Dashboard from "./Dashboard.svelte";
```

Change the third test's body to call `stubFetchFailing()` instead of its inline
`vi.stubGlobal`.

- [ ] **Step 3: Run the suite**

Run: `npm --prefix ui test`
Expected: PASS, same three Dashboard cases.

- [ ] **Step 4: Commit**

```bash
git add ui/src/lib/stub-fetch.ts ui/src/routes/Dashboard.test.ts
git commit -m "$(cat <<'EOF'
test(ui): one stubFetch instead of nine copies of it

Dashboard.test.ts defined it locally and every view added from here needs
```
*[... 7 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 3: The navigation rail

Nine destinations in one flat row teaches nothing. Spec Decision 4: three groups whose
names are verbs — using knowledge, growing it, and the machine.

**Files:**
- Create: `ui/src/lib/shell/nav.ts`
- Create: `ui/src/lib/shell/NavGroup.svelte`
- Create: `ui/src/lib/shell/Sidebar.svelte`
- Test: `ui/src/lib/shell/nav.test.ts`
- Test: `ui/src/lib/shell/Sidebar.test.ts`
- Modify: `ui/src/styles/components.css` (rail classes)

**Interfaces:**
- Consumes: `mode`, `MODES`, `setMode`, `type Mode` from `ui/src/lib/mode.ts`;
  `route`, `hashWith` from `ui/src/lib/router.ts`.
- Produces:
  - `nav.ts`: `type NavItem = { name: string; label: string }`,
    `type NavGroupSpec = { title: string; items: NavItem[]; authorOnly: boolean }`,
    `NAV: NavGroupSpec[]`, `groupsFor(mode: Mode): NavGroupSpec[]`,
    `isAuthorOnly(name: string): boolean`, `ALL_ROUTES: string[]`.
  - `Sidebar.svelte`: props `{ mode: Mode }`.

- [ ] **Step 1: Write the failing test for the route table**

Create `ui/src/lib/shell/nav.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { ALL_ROUTES, NAV, groupsFor, isAuthorOnly } from "./nav";

describe("the route table", () => {
    it("gives a buyer exactly the group about using knowledge", () => {
```
*[... 37 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/lib/shell/nav.test.ts`
Expected: FAIL — cannot resolve `./nav`.

- [ ] **Step 3: Write `nav.ts`**

Create `ui/src/lib/shell/nav.ts`:

```ts
import type { Mode } from "../mode";

export type NavItem = { name: string; label: string };
export type NavGroupSpec = { title: string; items: NavItem[]; authorOnly: boolean };

```
*[... 52 lines trimmed - see git history]*
```ts

export const isAuthorOnly = (name: string): boolean => AUTHOR_ROUTES.has(name);
```

- [ ] **Step 4: Run it and watch it pass**

Run: `npm --prefix ui test -- src/lib/shell/nav.test.ts`
Expected: PASS, four cases.

- [ ] **Step 5: Write the failing test for the rail**

Create `ui/src/lib/shell/Sidebar.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Sidebar from "./Sidebar.svelte";

describe("Sidebar", () => {
```
*[... 24 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 6: Run it and watch it fail**

Run: `npm --prefix ui test -- src/lib/shell/Sidebar.test.ts`
Expected: FAIL — cannot resolve `./Sidebar.svelte`.

- [ ] **Step 7: Write `NavGroup.svelte`**

Create `ui/src/lib/shell/NavGroup.svelte`:

```svelte
<script lang="ts">
    import type { NavGroupSpec } from "./nav";

    let {
        group,
```
*[... 26 lines trimmed - see git history]*
```svelte
    </ul>
</div>
```

Note the first test asserts `queryByText("Knowledge")` is null for a buyer — a buyer
never sees an author group at all, so that holds regardless. It also asserts no group
*heading* renders for the buyer's own group, which the `{#if group.authorOnly}` gives.

- [ ] **Step 8: Write `Sidebar.svelte`**

Create `ui/src/lib/shell/Sidebar.svelte`:

```svelte
<script lang="ts">
    import { MODES, setMode, type Mode } from "../mode";
    import { hashWith, route } from "../router";
    import NavGroup from "./NavGroup.svelte";
    import { groupsFor } from "./nav";
```
*[... 35 lines trimmed - see git history]*
```svelte
    </div>
</aside>
```

- [ ] **Step 9: Add the rail classes to `components.css`**

Append to `ui/src/styles/components.css`:

```css
/* ── the rail ─────────────────────────────────────────────────────── */
.rail {
    grid-area: rail;
    display: flex;
    flex-direction: column;
```
*[... 76 lines trimmed - see git history]*
```css
    gap: var(--s-1);
}
```

- [ ] **Step 10: Run the rail test and the guard**

Run: `npm --prefix ui test`
Expected: PASS — the four Sidebar cases, the four nav cases, `tokens.test.ts` still
green (every colour above is a token), and every pre-existing test unchanged.

- [ ] **Step 11: Commit**

```bash
git add ui/src/lib/shell ui/src/styles/components.css
git commit -m "$(cat <<'EOF'
feat(ui): a grouped rail, because nine tabs in a row said nothing

The old nav listed one destination per backend capability, which is the
```
*[... 12 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 4: `EmptyState` — an empty screen that says what to do next

`p.state.empty` appears in six views with a bare sentence and no next step. An empty
Coverage and an empty History mean opposite things.

**Files:**
- Create: `ui/src/lib/EmptyState.svelte`
- Test: `ui/src/lib/EmptyState.test.ts`
- Modify: `ui/src/styles/components.css`

**Interfaces:**
- Consumes: nothing.
- Produces: `EmptyState.svelte` with props
  `{ title: string; detail?: string; actionLabel?: string; actionHref?: string; onAction?: () => void }`.
  Renders the action as a link when `actionHref` is given, as a button when `onAction` is
  given, and omits it when neither is.

- [ ] **Step 1: Write the failing test**

Create `ui/src/lib/EmptyState.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import EmptyState from "./EmptyState.svelte";

describe("EmptyState", () => {
```
*[... 26 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/lib/EmptyState.test.ts`
Expected: FAIL — cannot resolve `./EmptyState.svelte`.

- [ ] **Step 3: Write the component**

Create `ui/src/lib/EmptyState.svelte`:

```svelte
<script lang="ts">
    let {
        title,
        detail = "",
        actionLabel = "",
```
*[... 21 lines trimmed - see git history]*
```svelte
    {/if}
</div>
```

- [ ] **Step 4: Add its classes to `components.css`**

Append to `ui/src/styles/components.css`:

```css
.empty-state {
    display: grid;
    justify-items: start;
    gap: var(--s-2);
    padding: var(--s-6);
```
*[... 12 lines trimmed - see git history]*
```css
    max-width: 52ch;
}
```

- [ ] **Step 5: Run it and watch it pass**

Run: `npm --prefix ui test`
Expected: PASS — four new cases, everything else unchanged.

- [ ] **Step 6: Commit**

```bash
git add ui/src/lib/EmptyState.svelte ui/src/lib/EmptyState.test.ts ui/src/styles/components.css
git commit -m "$(cat <<'EOF'
feat(ui): an empty screen that names its own next step

`p.state.empty` appeared in six views as one grey sentence. But "no
coverage gaps" is good news, "nothing asked yet" is an invitation, and
"no packs installed" is a blocker with a fix one click away — and all
three rendered identically. EmptyState takes a title, an explanation, and
an action that is a link when the next step is elsewhere and a button
when it is right here.
EOF
)"
```

---

## Task 5: The shell — rail plus workspace, and one route table

`App.svelte` holds its own `BUYER_VIEWS`/`AUTHOR_VIEWS` arrays, a header with inline
tabs, and an `if/else if` chain. The arrays become `nav.ts` (Task 3), the header becomes
the rail, and the chain gains the new routes. Spec Decision 4.

**Files:**
- Modify: `ui/src/App.svelte` (whole file)
- Test: `ui/src/App.test.ts` (create)
- Modify: `ui/src/styles/components.css`

**Interfaces:**
- Consumes: `Sidebar`, `isAuthorOnly` (Task 3); `EmptyState` (Task 4); every existing
  route component; `Overview`, `Subjects`, `Compare`, `Welcome` are wired in Tasks 7, 8,
  19 and 17 respectively — until then their branches are not present.
- Produces: the `.shell` grid contract `grid-template-areas: "rail work"`.

- [ ] **Step 1: Write the failing test**

Create `ui/src/App.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import App from "./App.svelte";
import { stubFetch } from "./lib/stub-fetch";

```
*[... 32 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/App.test.ts`
Expected: FAIL — no `link` named "New check", because the header still renders tabs.

- [ ] **Step 3: Rewrite `App.svelte`**

Replace the whole of `ui/src/App.svelte` with:

```svelte
<script lang="ts">
    import EmptyState from "./lib/EmptyState.svelte";
    import History from "./lib/History.svelte";
    import Sidebar from "./lib/shell/Sidebar.svelte";
    import { isAuthorOnly } from "./lib/shell/nav";
```
*[... 72 lines trimmed - see git history]*
```svelte
    </main>
</div>
```

`overview`, `subjects`, `compare` and `welcome` branches are added by Tasks 7, 8, 19 and
17. Until then those rail links land on the "No such view" state, which the third test
covers and which is honest rather than blank.

- [ ] **Step 4: Replace the header/main CSS with the shell grid**

In `ui/src/styles/components.css`, delete the `header { ... }` block and its
`header h1`, `header .sub`, `header nav` children (the rail replaces them), and replace
the `main { ... }` rule with:

```css
.shell {
    display: grid;
    grid-template-columns: var(--rail) minmax(0, 1fr);
    grid-template-areas: "rail work";
    min-height: 100vh;
}
.work {
    grid-area: work;
    padding: var(--s-5) var(--s-6);
    max-width: 1100px;
    width: 100%;
}
```

Keep `.report-head` and every other existing rule untouched; only the page chrome moves.

- [ ] **Step 5: Run the suite**

Run: `npm --prefix ui test`
Expected: PASS — three new App cases; `tokens.test.ts` green; all route tests unchanged
(they render components directly, not through `App`).

- [ ] **Step 6: Typecheck, build, and open it**

Run: `npm --prefix ui run check && npm --prefix ui run build`
Then `.venv/bin/python -m app.web` and click every rail link in both modes. Confirm the
author-only explanation appears for `#/coverage?mode=buyer` and that switching to author
in the rail reveals it.

- [ ] **Step 7: Commit**

```bash
git add ui/src/App.svelte ui/src/App.test.ts ui/src/styles/components.css src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): rail beside a workspace, and one table both halves read

App.svelte kept its own BUYER_VIEWS/AUTHOR_VIEWS arrays next to an
```
*[... 12 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 6: History that keeps the mode, and works as a page

`History.svelte` links with bare `toHash`, so a reader in author mode who clicks a
recent result is silently returned to buyer mode. It is also rail-only, and Task 5 now
renders it as a page.

**Files:**
- Modify: `ui/src/lib/History.svelte`
- Test: `ui/src/lib/History.test.ts` (create)

**Interfaces:**
- Consumes: `hashWith`, `route` from `../router`; `api.history`, `api.forget`.
- Produces: `History.svelte` prop `{ page?: boolean }` — `false` (default) renders the
  `aside.history` rail panel; `true` renders a full-width list with the compare
  affordance Task 19 links from.

- [ ] **Step 1: Write the failing test**

Create `ui/src/lib/History.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import History from "./History.svelte";
import { stubFetch } from "./stub-fetch";

```
*[... 33 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/lib/History.test.ts`
Expected: FAIL — the first case fails on a missing `mode=author`; the third fails on no
Compare link.

- [ ] **Step 3: Rewrite the component**

Replace `ui/src/lib/History.svelte` with:

```svelte
<script lang="ts">
    import EmptyState from "./EmptyState.svelte";
    import { api } from "./api";
    import { hashWith, route } from "./router";
    import type { HistoryItem } from "./types";
```
*[... 52 lines trimmed - see git history]*
```svelte
    {/await}
</svelte:element>
```

- [ ] **Step 4: Add the page variant's CSS**

Append to `ui/src/styles/components.css`:

```css
.history.page {
    border-left: 0;
    padding-left: 0;
}
.history.page li {
```
*[... 6 lines trimmed - see git history]*
```css
    margin-bottom: 0;
}
```

- [ ] **Step 5: Run it and watch it pass**

Run: `npm --prefix ui test`
Expected: PASS — three new cases, everything else unchanged.

- [ ] **Step 6: Commit**

```bash
git add ui/src/lib/History.svelte ui/src/lib/History.test.ts ui/src/styles/components.css
git commit -m "$(cat <<'EOF'
fix(ui): a recent result no longer drops you back into buyer mode

History linked with bare toHash, which builds a path and discards the
```
*[... 8 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 7: `Overview` — a control room instead of five counts

`Dashboard.svelte` shows five numbers and a "recent analysis activity" table that
duplicates History. Spec Decision 4: it becomes the page that answers "what should I
work on".

**Files:**
- Create: `ui/src/routes/Overview.svelte`
- Test: `ui/src/routes/Overview.test.ts`
- Modify: `ui/src/App.svelte` (add the branch)
- Delete: `ui/src/routes/Dashboard.svelte`, `ui/src/routes/Dashboard.test.ts`

**Interfaces:**
- Consumes: `api.status`, `api.packs`, `api.gaps`, `api.jobs`, `api.packUpdates`,
  `api.weakest`; `EmptyState`; `isLive`, `stateWord` from `../lib/jobs`.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Write the failing test**

Create `ui/src/routes/Overview.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { stubFetch, stubFetchFailing } from "../lib/stub-fetch";
import Overview from "./Overview.svelte";

```
*[... 43 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/routes/Overview.test.ts`
Expected: FAIL — cannot resolve `./Overview.svelte`.

- [ ] **Step 3: Write the component**

Create `ui/src/routes/Overview.svelte`:

```svelte
<script lang="ts">
    import Async from "../lib/Async.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import { api } from "../lib/api";
    import { isLive } from "../lib/jobs";
```
*[... 92 lines trimmed - see git history]*
```svelte
    {/snippet}
</Async>
```

- [ ] **Step 4: Add the worklist CSS**

Append to `ui/src/styles/components.css`:

```css
.worklist {
    list-style: none;
    margin: 0 0 var(--s-5);
    padding: 0;
    display: grid;
```
*[... 15 lines trimmed - see git history]*
```css
    text-decoration: underline;
}
```

- [ ] **Step 5: Wire the route and delete Dashboard**

In `ui/src/App.svelte`, add the import `import Overview from "./routes/Overview.svelte";`
and the branch immediately after the `check` branch:

```svelte
                {:else if $route.name === "overview"}
                    <Overview />
```

Then: `git rm ui/src/routes/Dashboard.svelte ui/src/routes/Dashboard.test.ts`

- [ ] **Step 6: Run the suite**

Run: `npm --prefix ui test`
Expected: PASS — five Overview cases; the three Dashboard cases are gone, replaced not
dropped.

- [ ] **Step 7: Commit**

```bash
git add ui/src/routes/Overview.svelte ui/src/routes/Overview.test.ts ui/src/App.svelte ui/src/styles/components.css
git rm ui/src/routes/Dashboard.svelte ui/src/routes/Dashboard.test.ts
git commit -m "$(cat <<'EOF'
feat(ui): Overview answers "what should I work on"; Dashboard did not

```
*[... 10 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 8: `Browse` becomes `Subjects`

"Browse" names a gesture; the page is a list of subjects. Renaming it is the last of
Phase 1.

**Files:**
- Create: `ui/src/routes/Subjects.svelte` (from `Browse.svelte`)
- Create: `ui/src/routes/Subjects.test.ts` (from `Browse.test.ts`)
- Modify: `ui/src/App.svelte`
- Delete: `ui/src/routes/Browse.svelte`, `ui/src/routes/Browse.test.ts`

**Interfaces:**
- Consumes: `api.subjects`; `EmptyState`.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Move the files with git, so the rename is reviewable as one**

```bash
git mv ui/src/routes/Browse.svelte ui/src/routes/Subjects.svelte
git mv ui/src/routes/Browse.test.ts ui/src/routes/Subjects.test.ts
```

- [ ] **Step 2: Update the test's import and add the empty-state case**

In `ui/src/routes/Subjects.test.ts`, change `import Browse from "./Browse.svelte";` to
`import Subjects from "./Subjects.svelte";`, rename every `Browse` reference in
`render(...)` and `describe(...)`, switch its local fetch stub to
`import { stubFetch } from "../lib/stub-fetch";`, and append:

```ts
it("says what to type when the search finds nothing", async () => {
    stubFetch({ "/api/subjects": [] });
    render(Subjects);
    expect(await screen.findByText(/No matching subjects/)).toBeInTheDocument();
});
```

- [ ] **Step 3: Swap the bare empty paragraph for an EmptyState**

In `ui/src/routes/Subjects.svelte`, add `import EmptyState from "../lib/EmptyState.svelte";`
and replace `<p class="state empty">No matching subjects.</p>` with:

```svelte
        <EmptyState
            title="No matching subjects"
            detail="Search matches a subject's label as the installed packs spell it.
                    An empty result may mean the coverage is not there yet."
        />
```

- [ ] **Step 4: Wire the route**

In `ui/src/App.svelte`, replace the `Browse` import with
`import Subjects from "./routes/Subjects.svelte";` and add the branch after `overview`:

```svelte
                {:else if $route.name === "subjects"}
                    <Subjects />
```

- [ ] **Step 5: Run the suite and confirm no `Browse` survives**

Run: `npm --prefix ui test && grep -rn "Browse" ui/src/ || echo "no Browse references"`
Expected: tests PASS; the grep prints nothing.

- [ ] **Step 6: Build and commit**

```bash
npm --prefix ui run build
git add -A ui/src src/app/web/static
git commit -m "$(cat <<'EOF'
refactor(ui): Browse becomes Subjects, because it lists subjects

```
*[... 7 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 9: `verdict.ts` — the top line, derived and pure

Spec Decision 5. Pure so it can be tested without a DOM, and so the component stays
markup. **No cost or price figure**: `Claim` has no such field.

**Files:**
- Create: `ui/src/lib/verdict.ts`
- Test: `ui/src/lib/verdict.test.ts`

**Interfaces:**
- Consumes: `type Claim`, `type LookupResult` from `./types`; `confidenceNote`,
  `emptyReason`, `severityRank` from `./report`.
- Produces:
  - `type Verdict = { headline: string; counts: { total: number; high: number; medium: number; low: number; handled: number }; note: string; tone: "clear" | "caution" | "alarm" | "unknown" }`
  - `verdictFor(result: LookupResult, handled: string[]): Verdict`
  - `severityShare(counts: Verdict["counts"]): { severity: string; percent: number }[]`

- [ ] **Step 1: Write the failing test**

Create `ui/src/lib/verdict.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { Claim, LookupResult } from "./types";
import { severityShare, verdictFor } from "./verdict";

const claim = (severity: string, id: string): Claim => ({
```
*[... 71 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/lib/verdict.test.ts`
Expected: FAIL — cannot resolve `./verdict`.

- [ ] **Step 3: Write `verdict.ts`**

Create `ui/src/lib/verdict.ts`:

```ts
import { claimKey, confidenceNote, emptyReason } from "./report";
import type { LookupResult } from "./types";

export type Counts = {
    total: number;
```
*[... 66 lines trimmed - see git history]*
```ts
        .filter((segment) => segment.percent > 0);
}
```

- [ ] **Step 4: Run it and watch it pass**

Run: `npm --prefix ui test -- src/lib/verdict.test.ts`
Expected: PASS, nine cases.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/verdict.ts ui/src/lib/verdict.test.ts
git commit -m "$(cat <<'EOF'
feat(ui): the report's top line, derived and pure

Pure so it is testable without a DOM and so the component stays markup.
```
*[... 8 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 10: `Verdict.svelte`, and the report becomes a document

`Report.svelte` computes `worst` inline and renders a `.lede` paragraph. That moves into
`Verdict.svelte` over Task 9's derivation, and the report surface gains the editorial
measure of spec Decision 5.

**Files:**
- Create: `ui/src/lib/Verdict.svelte`
- Modify: `ui/src/lib/Report.svelte`
- Modify: `ui/src/lib/Report.svelte.test.ts`
- Modify: `ui/src/styles/components.css`

**Interfaces:**
- Consumes: `verdictFor`, `severityShare`, `type Verdict` (Task 9); `type Mode`.
- Produces: `Verdict.svelte` props `{ result: LookupResult; handled: string[]; mode?: Mode }`.
  `Report.svelte` keeps its existing props exactly — `{ result, mode, lookupId, heading }` —
  because `Check`, `Result` and Task 19's `Compare` all pass them.

- [ ] **Step 1: Add the failing cases to the existing report test**

Append to `ui/src/lib/Report.svelte.test.ts` (keep every existing case):

```ts
it("leads with a verdict, not with a bare count", async () => {
    stubFetch({ "/api/lookups/L1/checked": { checked: [] } });
    render(Report, { result: RESULT, lookupId: "L1" });
    expect(await screen.findByText(/serious/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /severity mix/i })).toBeInTheDocument();
});

it("shows the reader how the match was made beside the verdict", () => {
    stubFetch({ "/api/lookups/L1/checked": { checked: [] } });
    render(Report, { result: RESULT, lookupId: "L1" });
    expect(screen.getByText(/Matched/)).toBeInTheDocument();
});
```

`RESULT` is the fixture already defined at the top of that file; if it holds no
`high`-severity claim, add one there rather than inventing a second fixture.

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/lib/Report.svelte.test.ts`
Expected: FAIL — no element with role `img` named "severity mix".

- [ ] **Step 3: Write `Verdict.svelte`**

Create `ui/src/lib/Verdict.svelte`:

```svelte
<script lang="ts">
    import type { Mode } from "./mode";
    import type { LookupResult } from "./types";
    import { severityShare, verdictFor } from "./verdict";

```
*[... 32 lines trimmed - see git history]*
```svelte
    {/if}
</div>
```

- [ ] **Step 4: Rewire `Report.svelte`'s header**

In `ui/src/lib/Report.svelte`: add `import Verdict from "./Verdict.svelte";`, delete the
`worst` derivation and the `confidenceNote` import (the verdict carries both now), and
replace the whole `<header class="report-head"> … </header>` block with:

```svelte
<header class="report-head">
    {#if heading}<h2>{heading}</h2>{/if}
    <Verdict {result} {handled} {mode} />
</header>
```

Wrap the claim groups in the reading measure by changing `{:else}` body's `{#each groups …}`
to sit inside `<div class="report-body">`:

```svelte
{:else}
    <div class="report-body">
        {#each groups as group (group.domain)}
            <section class="group">
                <h3 class="group-head">{group.domain}</h3>
```
*[... 10 lines trimmed - see git history]*
```svelte
    </div>
{/if}
```

- [ ] **Step 5: Style the verdict and the editorial measure**

Append to `ui/src/styles/components.css`:

```css
/* The report is the one editorial surface in the app: the reader reads it
   rather than operating it, and prints it. Measure, leading and a document
   hierarchy — none of it from a webfont, which an offline app cannot load. */
.report-body {
    max-width: var(--measure);
```
*[... 45 lines trimmed - see git history]*
```css
    background: var(--low);
}
```

Delete the now-unused `.lede` and `.high-count` rules.

- [ ] **Step 6: Run the suite**

Run: `npm --prefix ui test`
Expected: PASS — the two new report cases plus every existing one. `tokens.test.ts` stays
green because these rules name only custom properties and `999px`.

- [ ] **Step 7: Commit**

```bash
git add ui/src/lib/Verdict.svelte ui/src/lib/Report.svelte ui/src/lib/Report.svelte.test.ts ui/src/styles/components.css
git commit -m "$(cat <<'EOF'
feat(ui): the report leads with a verdict and reads like a document

The header was a count and a method string. It is now one line a reader
```
*[... 9 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 11: `ClaimCard` — severity you can see, and author extras behind a disclosure

The card puts a severity *word* in a pill and shows the author's provenance metadata
inline, so an author's card is a different shape from a buyer's. Spec Decision 5.

**Files:**
- Modify: `ui/src/lib/ClaimCard.svelte`
- Test: `ui/src/lib/ClaimCard.test.ts` (create)
- Modify: `ui/src/styles/components.css`

**Interfaces:**
- Consumes: `askLine`, `severityWord`, `sourceSummary` from `./report`; `type Mode`.
- Produces: props unchanged — `{ claim, mode?, checked?, onCheck? }`.

- [ ] **Step 1: Write the failing test**

Create `ui/src/lib/ClaimCard.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import ClaimCard from "./ClaimCard.svelte";
import type { Claim } from "./types";

```
*[... 43 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/lib/ClaimCard.test.ts`
Expected: FAIL — the author case finds no "Provenance" summary; the buyer case finds
"relevance" absent already (that one passes), so exactly one failure.

- [ ] **Step 3: Rework the card**

In `ui/src/lib/ClaimCard.svelte`, replace the author `{#if author} … {:else} … {/if}`
block with a disclosure and keep the buyer line unconditional:

```svelte
    <p class="meta">{claim.subject} · {sourceSummary(claim)}</p>

    {#if author}
        <details class="provenance">
            <summary class="meta">Provenance</summary>
```
*[... 11 lines trimmed - see git history]*
```svelte
        </details>
    {/if}
```

Leave the sources `<details>` below it exactly as it is — an author reading sources and an
author reading provenance are two different questions, and merging them would bury the
quotes.

- [ ] **Step 4: Give severity a visible rule, not only a word**

Append to `ui/src/styles/components.css`:

```css
/* Severity reaches the eye before the word does: a 3px rule down the card's
   leading edge, in the same three colours the verdict bar uses. Colour alone
   never carries it — the pill keeps the word for anyone who cannot see the
   difference. */
.card.risk {
```
*[... 26 lines trimmed - see git history]*
```css
    margin-top: var(--s-2);
}
```

- [ ] **Step 5: Run the suite**

Run: `npm --prefix ui test`
Expected: PASS — five ClaimCard cases; `Report.svelte.test.ts` unaffected.

- [ ] **Step 6: Check the author view by eye**

Run: `npm --prefix ui run build`, start the server, and open a stored result in author
mode. Confirm the card is the same *shape* as a buyer's with two closed disclosures under
it, rather than a different card.

- [ ] **Step 7: Commit**

```bash
git add ui/src/lib/ClaimCard.svelte ui/src/lib/ClaimCard.test.ts ui/src/styles/components.css src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): severity you can see, and provenance folded away

Severity was a word in a pill. It is now also a 3px rule down the card's
```
*[... 9 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 12: Print, and a report worth taking to the seller

Spec Decision 5's second half. `print.css` was created empty-of-rules in Task 1 and
imported; this fills it.

**Files:**
- Modify: `ui/src/styles/print.css`
- Modify: `ui/src/lib/Report.svelte`
- Modify: `ui/src/lib/Report.svelte.test.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces: the `.no-print` class contract — anything carrying it is absent from paper.

- [ ] **Step 1: Add the failing case**

Append to `ui/src/lib/Report.svelte.test.ts`:

```ts
it("offers a printable copy of the answer", async () => {
    stubFetch({ "/api/lookups/L1/checked": { checked: [] } });
    render(Report, { result: RESULT, lookupId: "L1" });
    expect(screen.getByRole("button", { name: /Print/ })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/lib/Report.svelte.test.ts`
Expected: FAIL — no button named Print.

- [ ] **Step 3: Add the action**

In `ui/src/lib/Report.svelte`, inside the `<header class="report-head">` and after
`<Verdict …/>`, add:

```svelte
    <div class="row no-print">
        <button class="ghost" onclick={() => window.print()}>Print / Save as PDF</button>
    </div>
```

The browser's own print dialog is the save-as-PDF path on every platform Tauri ships to,
so there is no second export to build and no file the app has to write.

- [ ] **Step 4: Write the print sheet**

Replace the contents of `ui/src/styles/print.css` with:

```css
/* Paper is the one place the app is not an app. The rail, the buttons and
   every disclosure control are chrome; the answer is the document. Disclosures
   are forced open because a folded source on paper is a source the reader
   cannot reach. */
@media print {
```
*[... 45 lines trimmed - see git history]*
```css
    }
}
```

`#999` is the one colour literal outside `tokens.css`, and `tokens.test.ts` must allow it:
add `print.css` to that test's exempt set with the reason in a comment — a print sheet
cannot use a themed token, because paper has no theme and the custom property would
resolve to whatever the screen was.

In `ui/src/styles/tokens.test.ts`, change the sheet list in the first case to skip
`print.css`:

```ts
// print.css names a grey directly: paper has no theme, so a token that
// resolves against the screen's palette is exactly the wrong value there.
const SHEETS = ["base.css", "components.css"];
```

- [ ] **Step 5: Run the suite, then print for real**

Run: `npm --prefix ui test`
Expected: PASS.

Then `npm --prefix ui run build`, open a stored result, and use the browser's print
preview. Confirm: no rail, no buttons, source quotes visible without clicking, and no
claim card split across a page break.

- [ ] **Step 6: Commit**

```bash
git add ui/src/styles/print.css ui/src/styles/tokens.test.ts ui/src/lib/Report.svelte ui/src/lib/Report.svelte.test.ts src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): the report prints, and prints as a document

Print / Save as PDF is the browser's own dialog, which is the save-as-PDF
```
*[... 11 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 13: `humanize()` — readable labels without a vocabulary table

Spec Decision 6. `test_ui_contains_no_pack_vocabulary` forbids a label map; a string
transform over an API-supplied key is not one.

**Files:**
- Modify: `ui/src/lib/fields.ts`
- Modify: `ui/src/lib/fields.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `humanize(key: string): string` — used by Tasks 14 and 18.

- [ ] **Step 1: Add the failing cases**

Append to `ui/src/lib/fields.test.ts`:

```ts
import { humanize } from "./fields";

describe("humanize", () => {
    it("turns a pack's key into something a reader can read", () => {
        expect(humanize("engine_code")).toBe("Engine code");
```
*[... 15 lines trimmed - see git history]*
```ts
    });
});
```

`fields.test.ts` ends in `.test.ts`, which is the invariant's only exemption, so a car key
in a fixture here is legal. Nothing in the implementation may name one.

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/lib/fields.test.ts`
Expected: FAIL — `humanize` is not exported.

- [ ] **Step 3: Implement it**

Append to `ui/src/lib/fields.ts`:

```ts
/** A pack's key, spelled for a reader.
 *
 * Deliberately a string transform and not a lookup table. A table of
 * key → friendly label would be pack vocabulary living in the frontend —
 * the thing `test_ui_contains_no_pack_vocabulary` exists to catch, and the
```
*[... 6 lines trimmed - see git history]*
```ts
    return words.charAt(0).toUpperCase() + words.slice(1);
};
```

- [ ] **Step 4: Run it and watch it pass**

Run: `npm --prefix ui test -- src/lib/fields.test.ts`
Expected: PASS, four new cases.

- [ ] **Step 5: Confirm the invariant still holds**

Run: `.venv/bin/python -m pytest src/app/pipeline/tests/test_repo_invariants.py -q`
Expected: PASS — the fixture keys live in a `.test.ts`, which the check exempts.

- [ ] **Step 6: Commit**

```bash
git add ui/src/lib/fields.ts ui/src/lib/fields.test.ts
git commit -m "$(cat <<'EOF'
feat(ui): readable field labels without a vocabulary table

Readers currently see snake_case straight off the pack. A key → label
```
*[... 7 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 14: `Describe.svelte` — the form asks for one thing at a time

The describe-it path shows every pack, kind, identity key and context term at once. Spec
Decision 6 stages it and skips what can be inferred.

**Files:**
- Create: `ui/src/lib/Describe.svelte`
- Test: `ui/src/lib/Describe.test.ts`

**Interfaces:**
- Consumes: `api.packs`, `api.kinds`, `api.identityKeys`, `api.vocabulary`,
  `api.subjects`, `api.subject`, `api.lookup`; `collect`, `humanize` (Task 13);
  `navigate`; `EmptyState`.
- Produces: `Describe.svelte` props
  `{ onResult: (result: LookupResult) => void }` — the parent decides whether to navigate
  or render inline, exactly as `Check.svelte` does today.

- [ ] **Step 1: Write the failing test**

Create `ui/src/lib/Describe.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import Describe from "./Describe.svelte";
import { stubFetch } from "./stub-fetch";
```
*[... 65 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/lib/Describe.test.ts`
Expected: FAIL — cannot resolve `./Describe.svelte`.

- [ ] **Step 3: Write the component**

Create `ui/src/lib/Describe.svelte`:

```svelte
<script lang="ts">
    import EmptyState from "./EmptyState.svelte";
    import { api } from "./api";
    import { collect, humanize } from "./fields";
    import type { LookupResult, Pack, Subject, SubjectDetail, Term } from "./types";
```
*[... 226 lines trimmed - see git history]*
```svelte
    <p class="state error">Could not load this view: {e.message}</p>
{/await}
```

- [ ] **Step 4: Run it and watch it pass**

Run: `npm --prefix ui test -- src/lib/Describe.test.ts`
Expected: PASS, six cases.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/Describe.svelte ui/src/lib/Describe.test.ts
git commit -m "$(cat <<'EOF'
feat(ui): the describe-it form asks for one thing at a time

It asked for everything at once: pack, kind, every identity key and every
```
*[... 9 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 15: `Check.svelte` becomes a hero and a host

With `Describe` extracted, `Check.svelte` is the URL hero, the unreadable-site
explanation, the author's page-fields (now *below* the fold, where an author's tool
belongs), and a mount point.

**Files:**
- Modify: `ui/src/routes/Check.svelte` (whole file)
- Test: `ui/src/routes/Check.test.ts` (create)
- Modify: `ui/src/styles/components.css`

**Interfaces:**
- Consumes: `Describe` (Task 14); `api.analyze`, `api.adapters`; `ApiError`; `navigate`;
  `Report`.
- Produces: props unchanged — `{ mode?: Mode }`.

- [ ] **Step 1: Write the failing test**

Create `ui/src/routes/Check.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import Check from "./Check.svelte";
```
*[... 45 lines trimmed - see git history]*
```ts
    });
});
```

`stub-fetch.ts` (Task 2) returns a non-ok response when a route's value is
`{ status, body }`; that is how the 404 case above drives `unreadable`.

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/routes/Check.test.ts`
Expected: FAIL — the fourth case; `Check.svelte` still owns the form and the heading text
differs.

- [ ] **Step 3: Rewrite `Check.svelte`**

Replace the whole of `ui/src/routes/Check.svelte` with:

```svelte
<script lang="ts">
    import Describe from "../lib/Describe.svelte";
    import Report from "../lib/Report.svelte";
    import { ApiError, api } from "../lib/api";
    import type { Mode } from "../lib/mode";
```
*[... 145 lines trimmed - see git history]*
```svelte
    {/if}
{/await}
```

The describe-it path is a `<details>` that opens itself when a site turned out to be
unreadable — the one moment the reader definitely needs it.

- [ ] **Step 4: Style the hero and the alternate path**

Append to `ui/src/styles/components.css`:

```css
.hero {
    max-width: var(--measure);
    margin-bottom: var(--s-6);
}
.hero h2 {
```
*[... 23 lines trimmed - see git history]*
```css
    margin: 0;
}
```

- [ ] **Step 5: Run the suite**

Run: `npm --prefix ui test`
Expected: PASS — five Check cases, six Describe cases; nothing else touched.

- [ ] **Step 6: Build and commit**

```bash
npm --prefix ui run build
git add ui/src/routes/Check.svelte ui/src/routes/Check.test.ts ui/src/styles/components.css src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): one hero input, and everything else earns its place below it

```
*[... 10 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 16: `Welcome.svelte` — the first run has something to do

Spec Decision 7, closing B52's "first run is still an empty store". The app offers the
index rather than bundling a pack, because bundling would pin knowledge to the binary's
release cadence.

**Files:**
- Create: `ui/src/routes/Welcome.svelte`
- Test: `ui/src/routes/Welcome.test.ts`
- Modify: `ui/src/styles/components.css`

**Interfaces:**
- Consumes: `api.packUpdates`, `api.updatePacks`, `api.installPack`, `api.status`;
  `follow` from `../lib/jobs`; `navigate`.
- Produces: `Welcome.svelte` props `{ onDone: () => void }` — Task 17's gate passes a
  callback that re-reads `status` and leaves the route.

- [ ] **Step 1: Write the failing test**

Create `ui/src/routes/Welcome.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import Welcome from "./Welcome.svelte";
```
*[... 40 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/routes/Welcome.test.ts`
Expected: FAIL — cannot resolve `./Welcome.svelte`.

- [ ] **Step 3: Write the component**

Create `ui/src/routes/Welcome.svelte`:

```svelte
<script lang="ts">
    import Async from "../lib/Async.svelte";
    import { api } from "../lib/api";
    import { follow } from "../lib/jobs";

```
*[... 105 lines trimmed - see git history]*
```svelte
    </Async>
</section>
```

- [ ] **Step 4: Style it**

Append to `ui/src/styles/components.css`:

```css
.welcome {
    max-width: var(--measure);
    margin: var(--s-6) auto;
}
.welcome h2 {
    font-size: var(--t-xl);
    line-height: var(--lh-xl);
    margin: 0 0 var(--s-3);
}
```

- [ ] **Step 5: Run it and watch it pass**

Run: `npm --prefix ui test -- src/routes/Welcome.test.ts`
Expected: PASS, four cases.

- [ ] **Step 6: Commit**

```bash
git add ui/src/routes/Welcome.svelte ui/src/routes/Welcome.test.ts ui/src/styles/components.css
git commit -m "$(cat <<'EOF'
feat(ui): a first run with something to do

B52's last open reader-facing item: the installer carries no pack, so a
```
*[... 10 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 17: the gate — first run happens once, and never blocks a reader

**Files:**
- Modify: `ui/src/App.svelte`
- Modify: `ui/src/App.test.ts`

**Interfaces:**
- Consumes: `Welcome` (Task 16); `api.status`.
- Produces: nothing.

- [ ] **Step 1: Add the failing cases**

Append to `ui/src/App.test.ts`:

```ts
it("shows first run when the store is empty", async () => {
    stubFetch({ ...EMPTY, "/api/status": { ok: true, packs: 0, enabled_packs: 0, counts: {} } });
    render(App);
    expect(await screen.findByText(/knows nothing yet/)).toBeInTheDocument();
});
```
*[... 12 lines trimmed - see git history]*
```ts
    expect(screen.queryByText(/knows nothing yet/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/App.test.ts`
Expected: FAIL — the first case; the app renders Check regardless of pack count.

- [ ] **Step 3: Add the gate**

In `ui/src/App.svelte`, add to the script:

```ts
    import Welcome from "./routes/Welcome.svelte";

    // First run is a state of the store, not a stored flag: nothing to reset,
    // and a reader who removes every pack gets the offer again, which is the
    // right answer at that moment too. A failing status call must never gate
```
*[... 7 lines trimmed - see git history]*
```ts
    let dismissed = $state(false);
    const firstRun = $derived(empty && !dismissed && $route.name !== "welcome");
```

Add `import { api } from "./lib/api";`, change `const ready = initMode($route.query.mode);`
to `const ready = Promise.all([initMode($route.query.mode), checkStore]);`, and put the
gate immediately inside `{:then}`, before the `authorOnly` branch:

```svelte
                {#if firstRun}
                    <Welcome
                        onDone={() => {
                            dismissed = true;
                            void api.status().then((s) => (empty = s.packs === 0));
                        }}
                    />
                {:else if authorOnly}
```

`dismissed` is component state rather than a setting, so Skip lasts the session: a reader
who skips and then quits still had no pack installed, and the offer is still the most
useful thing the app can show them next time.

- [ ] **Step 4: Run the suite**

Run: `npm --prefix ui test`
Expected: PASS — six App cases.

- [ ] **Step 5: Verify against a genuinely empty store**

```bash
npm --prefix ui run build
KRIKO_HOME=$(mktemp -d) .venv/bin/python -m app.web
```

Open it: first run appears. Skip; the check page appears. Reload: first run appears again,
which is correct — the store is still empty.

- [ ] **Step 6: Commit**

```bash
git add ui/src/App.svelte ui/src/App.test.ts src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): gate first run on the store, not on a stored flag

packs === 0 is the condition. There is no "seen the welcome" setting to
```
*[... 8 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 18: `compare.ts` — two answers aligned

Spec Decision 8, client-side over two `getLookup` calls. Pure, so the alignment is
testable without a DOM.

**Files:**
- Create: `ui/src/lib/compare.ts`
- Test: `ui/src/lib/compare.test.ts`

**Interfaces:**
- Consumes: `claimKey`, `orderClaims`, `severityRank` from `./report`;
  `type Claim`, `type StoredLookup`.
- Produces:
  - `type ComparedRow = { key: string; title: string; left: Claim | null; right: Claim | null }`
  - `type Comparison = { rows: ComparedRow[]; shared: number; onlyLeft: number; onlyRight: number }`
  - `compare(left: StoredLookup, right: StoredLookup): Comparison`

- [ ] **Step 1: Write the failing test**

Create `ui/src/lib/compare.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { compare } from "./compare";
import type { Claim, StoredLookup } from "./types";

const claim = (id: string, severity = "medium", title = id): Claim => ({
```
*[... 53 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/lib/compare.test.ts`
Expected: FAIL — cannot resolve `./compare`.

- [ ] **Step 3: Write `compare.ts`**

Create `ui/src/lib/compare.ts`:

```ts
import { claimKey, orderClaims, severityRank } from "./report";
import type { Claim, StoredLookup } from "./types";

export type ComparedRow = {
    key: string;
```
*[... 60 lines trimmed - see git history]*
```ts
export const column = (stored: StoredLookup): Claim[] =>
    orderClaims(stored.response.claims);
```

- [ ] **Step 4: Run it and watch it pass**

Run: `npm --prefix ui test -- src/lib/compare.test.ts`
Expected: PASS, five cases.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/compare.ts ui/src/lib/compare.test.ts
git commit -m "$(cat <<'EOF'
feat(ui): align two stored answers, client-side and pure

No compare endpoint, deliberately: comparing two listings is a product
```
*[... 8 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 19: `Compare.svelte` — and a way to get to it

**Files:**
- Create: `ui/src/routes/Compare.svelte`
- Test: `ui/src/routes/Compare.test.ts`
- Modify: `ui/src/App.svelte`
- Modify: `ui/src/styles/components.css`

**Interfaces:**
- Consumes: `compare` (Task 18); `api.history`, `api.getLookup`; `severityWord`;
  `EmptyState`; `hashWith`, `route`, `setQuery`.
- Produces: the route `#/compare?left=<id>&right=<id>` — Task 6's History page links to
  `#/compare` bare, and this view picks the two ids itself.

- [ ] **Step 1: Write the failing test**

Create `ui/src/routes/Compare.test.ts`:

```ts
import { render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import Compare from "./Compare.svelte";

```
*[... 58 lines trimmed - see git history]*
```ts
    });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `npm --prefix ui test -- src/routes/Compare.test.ts`
Expected: FAIL — cannot resolve `./Compare.svelte`.

- [ ] **Step 3: Write the component**

Create `ui/src/routes/Compare.svelte`:

```svelte
<script lang="ts">
    import Async from "../lib/Async.svelte";
    import EmptyState from "../lib/EmptyState.svelte";
    import { api } from "../lib/api";
    import { compare } from "../lib/compare";
```
*[... 108 lines trimmed - see git history]*
```svelte
    {/snippet}
</Async>
```

- [ ] **Step 4: Wire the route and add the table CSS**

In `ui/src/App.svelte`, add `import Compare from "./routes/Compare.svelte";` and the
branch after `history`:

```svelte
                {:else if $route.name === "compare"}
                    <Compare />
```

Append to `ui/src/styles/components.css`:

```css
.lede-compare {
    font-size: var(--t-md);
    font-variant-numeric: tabular-nums;
    margin-bottom: var(--s-4);
}
```
*[... 19 lines trimmed - see git history]*
```css
    letter-spacing: 0.04em;
}
```

- [ ] **Step 5: Add the entry point from a report**

In `ui/src/lib/Report.svelte`, inside the `.row.no-print` block added in Task 12, add
beside the Print button:

```svelte
        {#if lookupId}
            <a
                class="ghost button-like"
                href={hashWith({ mode: $route.query.mode, left: lookupId }, "compare")}
                >Compare with another</a
            >
        {/if}
```

and add `import { hashWith, route } from "./router";` to its script. Append to
`components.css`:

```css
.button-like {
    display: inline-block;
    text-decoration: none;
}
```

- [ ] **Step 6: Run the suite**

Run: `npm --prefix ui test`
Expected: PASS — four Compare cases plus every existing one. `Report.svelte.test.ts` still
passes: the new link renders only when `lookupId` is set, which its fixture does set, so
confirm it does not collide with the Print assertion.

- [ ] **Step 7: Typecheck, build, and drive it**

Run: `npm --prefix ui run check && npm --prefix ui run build`
Then run two checks, open one, click *Compare with another*, and pick the second from the
select. Confirm the URL carries both ids and that reloading the page restores the
comparison.

- [ ] **Step 8: Commit**

```bash
git add ui/src/routes/Compare.svelte ui/src/routes/Compare.test.ts ui/src/App.svelte ui/src/lib/Report.svelte ui/src/styles/components.css src/app/web/static
git commit -m "$(cat <<'EOF'
feat(ui): compare two checks side by side

Two ids in the query, two getLookup calls, one aligned table — so a
```
*[... 7 lines trimmed - see git history]*
```bash
EOF
)"
```

---

## Task 20: close-out — the bundle, the suite, the docs, the backlog

The bundle in `src/app/web/static/` is committed build output, and during the app-first
phase `ci.yml` is paused, so the stale-bundle comparison is a local obligation. This task
is the one that discharges it for the whole design pass.

**Files:**
- Modify: `src/app/web/static/**` (build output)
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CLAUDE.md` (documentation map row)
- Modify: `backlog.md`, `done.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code consumes.

- [ ] **Step 1: Rebuild the bundle from a clean tree and confirm it is committed**

```bash
npm --prefix ui run build
git status --short src/app/web/static
```

Expected: either no output (already current from the per-task builds) or a diff to stage.
A non-empty diff here means an earlier task's commit shipped source without its bundle —
stage it now and say so in this commit's message.

- [ ] **Step 2: Run the whole frontend suite and the typechecker**

Run: `npm --prefix ui test && npm --prefix ui run check`
Expected: PASS, zero type errors. Note the total case count; it should be well above the
pre-design count, and no test should have been deleted rather than replaced.

- [ ] **Step 3: Run the Python suite, which is the gate CLAUDE.md names**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. `test_ui_contains_no_pack_vocabulary`, `test_repo_invariants.py` and
`test_core_is_domain_free.py` are the three that this pass could plausibly have broken.

- [ ] **Step 4: Hand-dispatch the paused CI workflow, and do not block on it**

```bash
gh workflow run ci.yml --ref "$(git rev-parse --abbrev-ref HEAD)"
```

Read the run when it lands rather than watching it — that is the habit the app-first
phase is cutting. Its stale-bundle comparison is the check that matters here.

- [ ] **Step 5: Update `docs/ARCHITECTURE.md`'s frontend section**

Replace the `ui/` description with the new shape:

```markdown
### `ui/` — the frontend

Svelte 5 + Vite, built into `src/app/web/static/`. Hash-routed, no framework
router. The shell is a grouped rail (`lib/shell/`) over a route table in
`lib/shell/nav.ts` — one list both halves read, so a destination cannot exist
```
*[... 9 lines trimmed - see git history]*
```markdown
The report surface is deliberately the only editorial one: a 68ch measure,
reading leading, and a print sheet. Everything else is instrument.
```

- [ ] **Step 6: Add the spec and this plan to CLAUDE.md's documentation map**

Insert after the standalone-app design row:

```markdown
| `docs/superpowers/specs/2026-09-03-app-design-and-ia.md` | The app design system, IA and four features | current |
```

- [ ] **Step 7: Close B52's first-run bullet and record the pass in `done.md`**

In `backlog.md`, replace B52's "First run is still an empty store" bullet with:

```markdown
- **First run offers the index.** ~~The installer carries no pack, so a fresh
  launch answers nothing until the reader presses *Check for updates*.~~ Fixed
  2026-09-03: `Welcome.svelte` is gated on `packs === 0` and offers the index
  by name, installs through the same job path *Packs* uses, and takes a
  `.kpack` file when the index is unreachable. Deliberately *not* bundling
  `cars.kpack`, which would pin knowledge to the binary's release cadence.
  Still unconfirmed by a human on Windows.
```

Add to `done.md`, dated and with the commit range:

```markdown
### 2026-09-03 — the app design pass (`docs/superpowers/specs/2026-09-03-app-design-and-ia.md`)
Seven flat tabs became a grouped rail over one route table; the report leads with
a derived verdict and prints; the describe-it form stages what it asks for; first
run offers the pack index; two checks compare side by side. One design-token
sheet with a guard test that fails on a colour literal anywhere else — which is
the mechanism, not the cleanup: `#e5e5e5` in `.history` is the class of bug it
now catches. No Python diff, no new endpoint, no layer crossed.
```

- [ ] **Step 8: Commit the close-out**

```bash
git add docs/ARCHITECTURE.md CLAUDE.md backlog.md done.md src/app/web/static
git commit -m "$(cat <<'EOF'
docs: record the app design pass, and close B52's first-run bullet

The bundle is rebuilt and committed, the full pytest run is green, and
```
*[... 8 lines trimmed - see git history]*
```bash
EOF
)"
```

- [ ] **Step 9: Push**

```bash
git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
```

Ship to the reader, not to the branch: the next `v*` tag is what puts any of this in an
installer someone can double-click.

