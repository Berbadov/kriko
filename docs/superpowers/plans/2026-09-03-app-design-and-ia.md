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

const HERE = dirname(fileURLToPath(import.meta.url));

const read = (name: string) => readFileSync(join(HERE, name), "utf8");

const sheets = () =>
    readdirSync(HERE).filter((n) => n.endsWith(".css"));

// A literal colour is how #e5e5e5 got into `.history` and #b3261e into
// `tr.concern`: both invisible in dark, both wrong in light. tokens.css is the
// one file allowed to name a colour; everything else asks for one.
const COLOUR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;

describe("the stylesheets", () => {
    it("names a colour only in tokens.css", () => {
        const offenders: string[] = [];
        for (const name of sheets()) {
            if (name === "tokens.css") continue;
            read(name)
                .split("\n")
                .forEach((line, i) => {
                    if (COLOUR.test(line)) offenders.push(`${name}:${i + 1}: ${line.trim()}`);
                });
        }
        expect(offenders).toEqual([]);
    });

    it("references no custom property it never defines", () => {
        const all = sheets().map(read).join("\n");
        const defined = new Set(
            [...all.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]),
        );
        const used = new Set([...all.matchAll(/var\((--[a-z0-9-]+)/g)].map((m) => m[1]));
        expect([...used].filter((name) => !defined.has(name))).toEqual([]);
    });

    it("loads no webfont — the app must render styled with no network", () => {
        const all = sheets().map(read).join("\n");
        expect(all).not.toMatch(/@import|fonts\.googleapis|fonts\.gstatic/);
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
 */
:root {
    /* neutrals — 0 is the page ground, 9 is the strongest text */
    --n-0: #0f1115;
    --n-1: #14171d;
    --n-2: #171a21;
    --n-3: #1e222b;
    --n-4: #2a2f3a;
    --n-5: #3a4150;
    --n-6: #5b6475;
    --n-7: #8b93a5;
    --n-8: #c3c9d6;
    --n-9: #e6e8ee;

    --accent: #5b9dff;
    --accent-ink: #0b1220;
    --accent-soft: #1b2942;

    --high: #ff6b6b;
    --high-soft: #3a1f22;
    --medium: #ffb454;
    --medium-soft: #3a2e1a;
    --low: #6ec7a0;
    --low-soft: #172e26;

    /* semantic aliases — components speak these, never a ramp step */
    --bg: var(--n-0);
    --panel: var(--n-2);
    --panel-2: var(--n-3);
    --line: var(--n-4);
    --text: var(--n-9);
    --dim: var(--n-7);

    /* spacing — 4 8 12 16 24 32 48 */
    --s-1: 4px;
    --s-2: 8px;
    --s-3: 12px;
    --s-4: 16px;
    --s-5: 24px;
    --s-6: 32px;
    --s-7: 48px;

    /* type — size paired with its own line-height, never guessed at call site */
    --t-xs: 12px;
    --lh-xs: 1.4;
    --t-sm: 13px;
    --lh-sm: 1.45;
    --t-base: 15px;
    --lh-base: 1.55;
    --t-md: 17px;
    --lh-md: 1.4;
    --t-lg: 21px;
    --lh-lg: 1.3;
    --t-xl: 28px;
    --lh-xl: 1.2;

    /* the report reads rather than operates: wider leading, bounded measure */
    --lh-read: 1.65;
    --measure: 68ch;

    --radius: 10px;
    --radius-sm: 8px;
    --ring: 2px;

    --dur-fast: 120ms;
    --dur-slow: 240ms;

    --rail: 15rem;

    --font-sans:
        ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
}

/* Light is derived from the same ramp rather than patched on top of dark, which
 * is why `--high`/`--medium`/`--low` used to survive into light unchanged and
 * read as neon. */
@media (prefers-color-scheme: light) {
    :root {
        --n-0: #f6f7f9;
        --n-1: #ffffff;
        --n-2: #ffffff;
        --n-3: #f0f2f6;
        --n-4: #dfe3ea;
        --n-5: #c3cad6;
        --n-6: #8b93a5;
        --n-7: #626b7d;
        --n-8: #3a4150;
        --n-9: #1b1f27;

        --accent: #2563eb;
        --accent-ink: #ffffff;
        --accent-soft: #e7effd;

        --high: #b3261e;
        --high-soft: #fdeceb;
        --medium: #8a5a00;
        --medium-soft: #fdf3e2;
        --low: #1d6b4c;
        --low-soft: #e9f6f0;
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

body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font: var(--t-base) / var(--lh-base) var(--font-sans);
    font-variant-numeric: tabular-nums;
}

h1,
h2,
h3 {
    letter-spacing: -0.01em;
}
h2 {
    font-size: var(--t-lg);
    line-height: var(--lh-lg);
    margin: 0 0 var(--s-4);
}
h3 {
    font-size: var(--t-md);
    line-height: var(--lh-md);
    margin: 0 0 var(--s-1);
}

a {
    color: var(--accent);
}

code,
pre {
    font-family: var(--font-mono);
}

/* One focus treatment, on :focus-visible so a mouse click does not draw it.
 * Previously only inputs had any focus style at all. */
:focus-visible {
    outline: var(--ring) solid var(--accent);
    outline-offset: 1px;
}

hr {
    border: 0;
    border-top: 1px solid var(--line);
    margin: var(--s-6) 0 var(--s-5);
}

@media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        transition-duration: 1ms !important;
        animation-duration: 1ms !important;
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

501 lines, eleven colour variables, twenty-nine colour literals, and no
spacing or type scale — which is why `.history` had a raw #e5e5e5 border
that is invisible in dark and `tr.concern` a raw #b3261e, and why light
mode kept dark's neon severity colours. A flat variable list gives a new
surface nothing to use, so the next person reaches for a literal too.

tokens.css is now the only file permitted to name a colour, and
styles/tokens.test.ts reads the sheets off disk and fails on a literal
anywhere else, on a var() nobody defines, and on a webfont import — the
last because this is an offline desktop app that must not render
unstyled without a network. Light derives from the same ramp instead of
patching over dark.

No markup changed and no class was renamed: every selector app.css had
still exists, so this diff is reviewable as a port.
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
 * `test_ui_contains_no_pack_vocabulary` greps it like production code. Pass
 * your own payloads from the test that needs them.
 */
export function stubFetch(routes: Record<string, unknown>): void {
    vi.stubGlobal(
        "fetch",
        vi.fn(async (path: string) => {
            // Longest prefix wins. "/api/packs" and "/api/packs/p1/gaps" are
            // both real routes and both legitimate keys, so first-match would
            // silently answer the specific one with the general one's payload.
            const key = Object.keys(routes)
                .filter((route) => path.startsWith(route))
                .sort((a, b) => b.length - a.length)[0];
            if (!key) return new Response(`not stubbed: ${path}`, { status: 500 });
            const value = routes[key];
            // A route may name a failure instead of a payload — an unreadable
            // site is a 404 the view is supposed to explain, not an accident.
            if (isFailure(value)) {
                return new Response(value.body, { status: value.status });
            }
            return new Response(JSON.stringify(value));
        }),
    );
}

type Failure = { status: number; body: string };

const isFailure = (value: unknown): value is Failure =>
    typeof value === "object" &&
    value !== null &&
    typeof (value as Failure).status === "number" &&
    typeof (value as Failure).body === "string";

/** Every request fails — for the "surfaces a failure instead of rendering
 * blank" case that each view owes its reader. */
export function stubFetchFailing(status = 500): void {
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
it. Deliberately not a `.test.ts` file and deliberately holding no
fixture data: the pack-vocabulary invariant exempts only `*.test.ts`, so
realistic identity keys in a shared helper would fail the Python suite.

stubFetchFailing() comes along because "surfaces a failure instead of
rendering blank" is a case every view owes its reader, and it was being
retyped too.
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
        const groups = groupsFor("buyer");
        expect(groups.map((g) => g.title)).toEqual(["Check"]);
        expect(groups[0].items.map((i) => i.name)).toEqual([
            "check",
            "history",
            "compare",
        ]);
    });

    it("gives an author all three groups", () => {
        expect(groupsFor("author").map((g) => g.title)).toEqual([
            "Check",
            "Knowledge",
            "System",
        ]);
    });

    it("knows which routes a buyer may not open", () => {
        expect(isAuthorOnly("overview")).toBe(true);
        expect(isAuthorOnly("health")).toBe(true);
        expect(isAuthorOnly("check")).toBe(false);
        expect(isAuthorOnly("compare")).toBe(false);
    });

    it("lists every destination once, so App.svelte and the rail cannot drift", () => {
        expect(ALL_ROUTES).toEqual([
            "check",
            "history",
            "compare",
            "overview",
            "subjects",
            "coverage",
            "health",
            "packs",
            "jobs",
        ]);
        expect(new Set(ALL_ROUTES).size).toBe(ALL_ROUTES.length);
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

/** The destinations, grouped by verb.
 *
 * Nine tabs in one row said only "the backend has nine capabilities". The
 * groups are the three things someone does here: use the knowledge, grow it,
 * and mind the machine. `Health` sits under Knowledge rather than System
 * because it is about claim quality, not about this process.
 *
 * One table, read by both the rail and App.svelte's guard, so a route cannot
 * appear in one and not the other.
 */
export const NAV: NavGroupSpec[] = [
    {
        title: "Check",
        authorOnly: false,
        items: [
            { name: "check", label: "New check" },
            { name: "history", label: "History" },
            { name: "compare", label: "Compare" },
        ],
    },
    {
        title: "Knowledge",
        authorOnly: true,
        items: [
            { name: "overview", label: "Overview" },
            { name: "subjects", label: "Subjects" },
            { name: "coverage", label: "Coverage" },
            { name: "health", label: "Health" },
        ],
    },
    {
        title: "System",
        authorOnly: true,
        items: [
            { name: "packs", label: "Packs" },
            { name: "jobs", label: "Runs" },
        ],
    },
];

export const groupsFor = (mode: Mode): NavGroupSpec[] =>
    NAV.filter((group) => mode === "author" || !group.authorOnly);

export const ALL_ROUTES: string[] = NAV.flatMap((group) =>
    group.items.map((item) => item.name),
);

const AUTHOR_ROUTES = new Set(
    NAV.filter((group) => group.authorOnly).flatMap((group) =>
        group.items.map((item) => item.name),
    ),
);

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
    it("shows a buyer two group-less destinations and no operator work", () => {
        render(Sidebar, { mode: "buyer" });
        expect(screen.getByRole("link", { name: "New check" })).toBeInTheDocument();
        expect(screen.queryByRole("link", { name: "Coverage" })).toBeNull();
        expect(screen.queryByText("Knowledge")).toBeNull();
    });

    it("shows an author the grouped operator destinations", () => {
        render(Sidebar, { mode: "author" });
        expect(screen.getByText("Knowledge")).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Overview" })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Runs" })).toBeInTheDocument();
    });

    it("carries the mode into every link, so a click does not silently switch it", () => {
        render(Sidebar, { mode: "author" });
        const link = screen.getByRole("link", { name: "Coverage" }) as HTMLAnchorElement;
        expect(link.getAttribute("href")).toContain("mode=author");
    });

    it("offers the mode switch as a labelled group", () => {
        render(Sidebar, { mode: "buyer" });
        expect(screen.getByRole("group", { name: "Mode" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "author" })).toBeInTheDocument();
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
        current,
        href,
    }: {
        group: NavGroupSpec;
        current: string;
        href: (name: string) => string;
    } = $props();
</script>

<div class="nav-group">
    <!-- The buyer's single group is unlabelled: one heading over one list of
         two is noise, and there is nothing for it to distinguish from. -->
    {#if group.authorOnly}
        <p class="nav-title">{group.title}</p>
    {/if}
    <ul>
        {#each group.items as item (item.name)}
            <li>
                <a
                    class="nav-link"
                    class:active={current === item.name}
                    aria-current={current === item.name ? "page" : undefined}
                    href={href(item.name)}>{item.label}</a
                >
            </li>
        {/each}
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

    let { mode }: { mode: Mode } = $props();

    const groups = $derived(groupsFor(mode));

    // Every rail link carries the mode. A link that drops it looks like the app
    // switching modes on its own.
    const href = (name: string) => hashWith({ mode: $route.query.mode }, name);
</script>

<aside class="rail">
    <a class="brand" href={href("check")}>
        <span class="mark" aria-hidden="true">◆</span>
        <span class="brand-text">
            <strong>Kriko</strong>
            <span class="meta">local product knowledge</span>
        </span>
    </a>

    <nav class="rail-nav">
        {#each groups as group (group.title)}
            <NavGroup {group} current={$route.name} {href} />
        {/each}
    </nav>

    <div class="rail-foot">
        <span class="modes" role="group" aria-label="Mode">
            {#each MODES as candidate (candidate)}
                <button
                    class="tab"
                    class:active={mode === candidate}
                    onclick={() => setMode(candidate as Mode)}>{candidate}</button
                >
            {/each}
        </span>
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
    gap: var(--s-5);
    padding: var(--s-4) var(--s-3);
    border-right: 1px solid var(--line);
    background: var(--n-1);
    height: 100vh;
    position: sticky;
    top: 0;
    overflow-y: auto;
}
.brand {
    display: flex;
    gap: var(--s-2);
    align-items: center;
    padding: 0 var(--s-2);
    text-decoration: none;
    color: var(--text);
}
.brand .mark {
    color: var(--accent);
    font-size: var(--t-md);
}
.brand-text {
    display: grid;
}
.brand-text strong {
    font-size: var(--t-md);
    letter-spacing: -0.01em;
}
.brand-text .meta {
    font-size: var(--t-xs);
}
.rail-nav {
    display: grid;
    gap: var(--s-5);
}
.nav-group ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 1px;
}
.nav-title {
    margin: 0 var(--s-2) var(--s-2);
    font-size: var(--t-xs);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--dim);
}
.nav-link {
    display: block;
    padding: var(--s-2) var(--s-2);
    border-radius: var(--radius-sm);
    text-decoration: none;
    color: var(--n-8);
    transition: background var(--dur-fast) ease;
}
.nav-link:hover {
    background: var(--panel-2);
    color: var(--text);
}
.nav-link.active {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 600;
}
.rail-foot {
    margin-top: auto;
    padding-top: var(--s-3);
    border-top: 1px solid var(--line);
}
.rail-foot .modes {
    margin: 0;
    padding: 0;
    border-left: 0;
    display: flex;
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
anti-pattern the 2026-09-01 spec named in app.js reproduced a level up.
The rail groups by verb instead: Check is using the knowledge, Knowledge
is growing and inspecting it, System is the machine. Health moves under
Knowledge — it is about claim quality, not about this process.

nav.ts is one table read by both the rail and (next task) App.svelte's
author guard, so a destination cannot exist in one and be missing from
the other. Every link carries ?mode, because a link that drops it looks
like the app changing modes by itself.

The buyer's single group renders without a heading: one title over one
list of two, with nothing to distinguish it from, is noise.
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
    it("says what is empty and why it matters", () => {
        render(EmptyState, {
            title: "Nothing asked yet",
            detail: "Checks you run show up here.",
        });
        expect(screen.getByText("Nothing asked yet")).toBeInTheDocument();
        expect(screen.getByText("Checks you run show up here.")).toBeInTheDocument();
    });

    it("offers a link when the next step is somewhere else", () => {
        render(EmptyState, { title: "No packs", actionLabel: "Open Packs", actionHref: "#/packs" });
        const link = screen.getByRole("link", { name: "Open Packs" }) as HTMLAnchorElement;
        expect(link.getAttribute("href")).toBe("#/packs");
    });

    it("offers a button when the next step is right here", async () => {
        const onAction = vi.fn();
        render(EmptyState, { title: "No packs", actionLabel: "Check for updates", onAction });
        screen.getByRole("button", { name: "Check for updates" }).click();
        expect(onAction).toHaveBeenCalledOnce();
    });

    it("renders no action when there is nothing useful to offer", () => {
        render(EmptyState, { title: "Nothing here" });
        expect(screen.queryByRole("button")).toBeNull();
        expect(screen.queryByRole("link")).toBeNull();
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
        actionHref = "",
        onAction,
    }: {
        title: string;
        detail?: string;
        actionLabel?: string;
        actionHref?: string;
        onAction?: () => void;
    } = $props();
</script>

<!-- An empty screen is a state, not an absence. "No coverage gaps" and
     "nothing asked yet" lead a reader to opposite next steps, and a bare grey
     sentence tells them neither. -->
<div class="empty-state">
    <p class="empty-title">{title}</p>
    {#if detail}<p class="meta">{detail}</p>{/if}
    {#if actionLabel && actionHref}
        <a class="tab" href={actionHref}>{actionLabel}</a>
    {:else if actionLabel && onAction}
        <button onclick={onAction}>{actionLabel}</button>
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
    border: 1px dashed var(--line);
    border-radius: var(--radius);
    background: var(--panel);
    margin: var(--s-3) 0;
}
.empty-title {
    margin: 0;
    font-size: var(--t-md);
    font-weight: 600;
}
.empty-state .meta {
    margin: 0;
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

const EMPTY = {
    "/api/settings": { mode: "buyer" },
    "/api/status": { ok: true, packs: 1, enabled_packs: 1, counts: {} },
    "/api/packs": [],
    "/api/adapters": [],
    "/api/history": { items: [] },
};

describe("App", () => {
    beforeEach(() => {
        window.location.hash = "";
    });

    it("renders the rail beside the workspace", async () => {
        stubFetch(EMPTY);
        render(App);
        expect(await screen.findByRole("link", { name: "New check" })).toBeInTheDocument();
    });

    it("explains an author route to a buyer instead of rendering nothing", async () => {
        window.location.hash = "#/coverage?mode=buyer";
        stubFetch(EMPTY);
        render(App);
        expect(await screen.findByText(/author view/i)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "author" })).toBeInTheDocument();
    });

    it("names an unknown route rather than showing a blank workspace", async () => {
        window.location.hash = "#/nonsense?mode=buyer";
        stubFetch(EMPTY);
        render(App);
        expect(await screen.findByText(/No such view/)).toBeInTheDocument();
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
    import { initMode, mode } from "./lib/mode";
    import { hashWith, route } from "./lib/router";
    import Check from "./routes/Check.svelte";
    import Coverage from "./routes/Coverage.svelte";
    import Health from "./routes/Health.svelte";
    import Jobs from "./routes/Jobs.svelte";
    import Packs from "./routes/Packs.svelte";
    import Result from "./routes/Result.svelte";

    // The sidebar panel belongs where a past answer is relevant: beside the
    // form that produces one and beside a result being read. On the History
    // *page* it would be the page twice.
    const WITH_HISTORY = new Set(["check", "result"]);
    const showHistory = $derived(WITH_HISTORY.has($route.name));

    // A view only an author has is not hidden from a buyer who has its link —
    // it is explained, and the switch is one click away in the rail. Silently
    // rendering nothing would look like a broken link.
    const authorOnly = $derived($mode !== "author" && isAuthorOnly($route.name));

    const ready = initMode($route.query.mode);
</script>

<div class="shell">
    <Sidebar mode={$mode} />

    <main class="work" class:with-history={showHistory}>
        <div class="view">
            {#await ready}
                <p class="state loading">Starting…</p>
            {:then}
                {#if authorOnly}
                    <EmptyState
                        title="{$route.name} is an author view"
                        detail="It is real work a pack author does, and none of it helps
                                someone deciding whether to go and look at a listing.
                                Switch to author mode in the rail to open it."
                    />
                {:else if $route.name === "check"}
                    <Check mode={$mode} />
                {:else if $route.name === "history"}
                    <h2>History</h2>
                    <History page />
                {:else if $route.name === "coverage"}
                    <Coverage />
                {:else if $route.name === "packs"}
                    <Packs />
                {:else if $route.name === "health"}
                    <Health />
                {:else if $route.name === "jobs"}
                    <Jobs />
                {:else if $route.name === "result"}
                    <!-- Keyed: Result fetches once on init, so moving between two
                         stored results must remount rather than reuse. -->
                    {#key $route.params[0]}
                        <Result lookupId={$route.params[0]} mode={$mode} />
                    {/key}
                {:else}
                    <EmptyState
                        title="No such view: {$route.name}"
                        detail="The link may be from an older version."
                        actionLabel="Go to New check"
                        actionHref={hashWith({ mode: $route.query.mode }, "check")}
                    />
                {/if}
            {/await}
        </div>
        {#if showHistory}
            {#key $route.params[0] ?? $route.name}
                <History />
            {/key}
        {/if}
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
if/else chain, so a destination could be added to one and forgotten in
the other. Both now read nav.ts. The header's inline tabs and the mode
switch move into the rail's footer, where the switch is a setting rather
than a navigation item sitting among navigation items.

The author-only explanation survives the move and gets better: it is an
EmptyState that says why the view exists and where the switch is, not a
one-line scold. An unknown route now offers a way out instead of naming
itself and stopping.

overview/subjects/compare/welcome land on "No such view" until their own
tasks wire them, which is honest and covered by a test.
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

const ITEMS = {
    "/api/history": {
        items: [
            { lookup_id: "a1", created_at: "2026-09-01", source: "url", label: "One", claim_count: 3 },
            { lookup_id: "b2", created_at: "2026-09-02", source: "form", label: "Two", claim_count: 0 },
        ],
    },
};

describe("History", () => {
    beforeEach(() => {
        window.location.hash = "#/check?mode=author";
    });

    it("carries the mode into a stored result, instead of dropping the reader into buyer", async () => {
        stubFetch(ITEMS);
        render(History);
        const link = (await screen.findByRole("link", { name: "One" })) as HTMLAnchorElement;
        expect(link.getAttribute("href")).toContain("mode=author");
        expect(link.getAttribute("href")).toContain("result/a1");
    });

    it("says what the list is for when it is empty", async () => {
        stubFetch({ "/api/history": { items: [] } });
        render(History);
        expect(await screen.findByText(/Nothing asked yet/)).toBeInTheDocument();
    });

    it("as a page, offers comparing two of them", async () => {
        stubFetch(ITEMS);
        render(History, { page: true });
        const compare = (await screen.findByRole("link", { name: /Compare/ })) as HTMLAnchorElement;
        expect(compare.getAttribute("href")).toContain("compare");
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

    let { page = false }: { page?: boolean } = $props();

    let items = $state<HistoryItem[]>([]);

    // hashWith, not toHash: a bare link dropped ?mode, so an author clicking a
    // recent result landed in buyer mode with no indication why.
    const link = (name: string, ...params: string[]) =>
        hashWith({ mode: $route.query.mode }, name, ...params);

    async function refresh() {
        items = (await api.history()).items;
    }

    async function forget(item: HistoryItem) {
        await api.forget(item.lookup_id);
        await refresh();
    }

    const ready = refresh();
</script>

<svelte:element this={page ? "section" : "aside"} class={page ? "history page" : "history"}>
    {#if !page}<h3>Recent</h3>{/if}
    {#await ready then}
        {#if items.length}
            {#if page}
                <p class="meta">
                    <a href={link("compare")}>Compare two of these →</a>
                </p>
            {/if}
            <ul>
                {#each items as item (item.lookup_id)}
                    <li>
                        <a href={link("result", item.lookup_id)}>{item.label}</a>
                        <span class="meta"
                            >{item.claim_count} claim(s) · {item.source}{#if page} ·
                                {item.created_at}{/if}</span
                        >
                        <button class="ghost" onclick={() => forget(item)}>Forget</button>
                    </li>
                {/each}
            </ul>
        {:else}
            <EmptyState
                title="Nothing asked yet"
                detail="Every check you run is kept here so you can reopen it, link it, or
                        compare two listings."
                actionLabel="Run a check"
                actionHref={link("check")}
            />
        {/if}
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
    grid-template-columns: minmax(0, 1fr) auto auto;
    align-items: baseline;
    gap: var(--s-3);
    justify-items: start;
    padding: var(--s-2) 0;
    border-bottom: 1px solid var(--line);
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
query — so an author clicking any recent result landed in buyer mode
with no indication that anything had changed. hashWith carries it, the
same way every other link in the app already did.

While here: the component takes a `page` prop so the rail panel and the
new History destination are one component rather than two that drift,
and its empty state now says what the list is for and offers a check to
run instead of a grey "Nothing asked yet."
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

const ROUTES = {
    "/api/status": { ok: true, packs: 2, enabled_packs: 1, counts: { subjects: 12, claims: 34 } },
    "/api/packs": [
        { pack_id: "p1", name: "Pack One", version: "1.0", enabled: 1, subjects: 12, claims: 34, evidence: 9, digest: "d" },
    ],
    "/api/packs/p1/gaps": [{ subject_id: "s1", label: "One", kind: "k" }],
    "/api/packs/updates": { index_url: "u", error: null, packs: [{ pack_id: "p1", name: "Pack One", installed_version: "1.0", offered_version: "1.1", state: "available", reason: "" }] },
    "/api/jobs": { items: [{ job_id: "j1", kind: "research", params: {}, state: "running", progress: 0.4, message: "reading", log: "", result: null, done: false, created_at: "", started_at: null, finished_at: null }] },
    "/api/health/weakest": { claims: [{ claim_id: "c1", subject_id: "s1", subject_label: "One", pack_id: "p1", title: "Weak thing", refuted_by: 0, independent_sources: 1, best_tier: "forum", best_trust: 0.2, oldest_retrieved_at: null, concern: null }] },
};

describe("Overview", () => {
    it("leads with the work waiting, not with the store's size", async () => {
        stubFetch(ROUTES);
        render(Overview);
        expect(await screen.findByText(/1 coverage gap/i)).toBeInTheDocument();
        expect(screen.getByText(/1 pack update/i)).toBeInTheDocument();
        expect(screen.getByText(/1 run in flight/i)).toBeInTheDocument();
    });

    it("still shows the store counts, in a strip rather than as the headline", async () => {
        stubFetch(ROUTES);
        render(Overview);
        expect(await screen.findByText("34")).toBeInTheDocument();
        expect(screen.getByText("Claims")).toBeInTheDocument();
    });

    it("names the weakest claim, so 'what should I work on' has an answer", async () => {
        stubFetch(ROUTES);
        render(Overview);
        expect(await screen.findByText("Weak thing")).toBeInTheDocument();
    });

    it("says the store is empty rather than printing zeroes", async () => {
        stubFetch({ ...ROUTES, "/api/status": { ok: true, packs: 0, enabled_packs: 0, counts: {} }, "/api/packs": [] });
        render(Overview);
        expect(await screen.findByText(/No packs installed/i)).toBeInTheDocument();
    });

    it("surfaces a failure instead of rendering blank", async () => {
        stubFetchFailing();
        render(Overview);
        expect(await screen.findByText(/Could not load this view/)).toBeInTheDocument();
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
    import { hashWith, route } from "../lib/router";

    // Five counts and a table that duplicated History did not answer "what
    // should I work on". Everything here is either work waiting or a link to
    // where that work is done.
    const load = async () => {
        const [status, packs, updates, jobs, weakest] = await Promise.all([
            api.status(),
            api.packs(),
            api.packUpdates().catch(() => null),
            api.jobs(10).catch(() => ({ items: [] })),
            api.weakest(5).catch(() => ({ claims: [] })),
        ]);
        const gapLists = await Promise.all(
            packs.map((pack) => api.gaps(pack.pack_id).catch(() => [])),
        );
        return {
            status,
            packs,
            gaps: gapLists.flat().length,
            updatable: (updates?.packs ?? []).filter((p) => p.state === "available").length,
            live: (jobs.items ?? []).filter(isLive).length,
            weakest: weakest.claims,
        };
    };
    const data = load();

    const link = (name: string) => hashWith({ mode: $route.query.mode }, name);

    const plural = (n: number, one: string, many: string) =>
        `${n} ${n === 1 ? one : many}`;
</script>

<h2>Overview</h2>

<Async promise={data}>
    {#snippet children(d)}
        {#if !d.packs.length}
            <EmptyState
                title="No packs installed"
                detail="The engine holds no knowledge yet, so nothing here has anything to
                        report. Install a pack and this page fills in."
                actionLabel="Open Packs"
                actionHref={link("packs")}
            />
        {:else}
            <ul class="worklist">
                <li>
                    <a href={link("coverage")}
                        >{plural(d.gaps, "coverage gap", "coverage gaps")}</a
                    >
                    <span class="meta">subjects a pack names but knows nothing about</span>
                </li>
                <li>
                    <a href={link("packs")}
                        >{plural(d.updatable, "pack update", "pack updates")} waiting</a
                    >
                    <span class="meta">knowledge moves weekly; the app rarely</span>
                </li>
                <li>
                    <a href={link("jobs")}>{plural(d.live, "run in flight", "runs in flight")}</a>
                    <span class="meta">research and pack builds outlive the page</span>
                </li>
            </ul>

            <div class="stats">
                {#each [["Packs", d.status.packs], ["Enabled", d.status.enabled_packs], ["Subjects", d.status.counts.subjects ?? 0], ["Claims", d.status.counts.claims ?? 0]] as [label, value] (label)}
                    <div class="stat"><strong>{value}</strong><span>{label}</span></div>
                {/each}
            </div>

            <h3>Thinnest evidence</h3>
            <p class="meta">
                The claims we ship with the least behind them. Fixing these is worth more
                than adding new ones.
            </p>
            {#if d.weakest.length}
                <ul class="worklist">
                    {#each d.weakest as claim (claim.claim_id)}
                        <li>
                            <a href={link("health")}>{claim.title}</a>
                            <span class="meta"
                                >{claim.subject_label} · {claim.independent_sources} independent
                                source(s) · best {claim.best_tier}</span
                            >
                        </li>
                    {/each}
                </ul>
            {:else}
                <p class="meta">Nothing reported — every shipped claim has sources behind it.</p>
            {/if}
        {/if}
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
    gap: var(--s-1);
}
.worklist li {
    display: flex;
    gap: var(--s-3);
    align-items: baseline;
    flex-wrap: wrap;
    padding: var(--s-2) 0;
    border-bottom: 1px solid var(--line);
}
.worklist li > a {
    font-size: var(--t-md);
    text-decoration: none;
}
.worklist li > a:hover {
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

Dashboard was five counts and a recent-analysis table that History
already is, better. The author's landing page now leads with work
waiting — open coverage gaps, pack updates available, runs in flight,
each a link to where that work is done — then the store counts as a
strip, then the five claims with the thinnest evidence behind them.

Every panel degrades on its own: the gaps, updates, jobs and weakest
calls each catch, so one failing endpoint costs its own row rather than
the page. An empty store says so and points at Packs rather than
printing four zeroes.
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

"Browse" names a gesture, not a thing, and it was the only rail label
that did not say what you would find. Moved with git mv so the rename
reads as one change, and its no-results state now explains that an empty
search may be a coverage gap rather than a spelling mistake.

Ends phase 1: the rail, the shell, History, Overview and this. All nine
destinations resolve.
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
    claim_id: id,
    title: `t-${id}`,
    body: "b",
    severity,
    subject: "s",
    relevance: 0.5,
    pack_id: "p",
});

const result = (claims: Claim[], over: Partial<LookupResult> = {}): LookupResult => ({
    method: "exact",
    coverage: "FULL",
    claims,
    ...over,
});

describe("verdictFor", () => {
    it("leads with the serious count when there is one", () => {
        const v = verdictFor(result([claim("high", "a"), claim("low", "b")]), []);
        expect(v.tone).toBe("alarm");
        expect(v.headline).toMatch(/1 serious/);
        expect(v.counts).toMatchObject({ total: 2, high: 1, low: 1, handled: 0 });
    });

    it("does not cry alarm over minor items alone", () => {
        const v = verdictFor(result([claim("low", "a"), claim("low", "b")]), []);
        expect(v.tone).toBe("caution");
        expect(v.headline).not.toMatch(/serious/);
    });

    it("counts what the reader has already handled", () => {
        const v = verdictFor(result([claim("high", "a"), claim("high", "b")]), ["a"]);
        expect(v.counts.handled).toBe(1);
        expect(v.headline).toMatch(/1 handled/);
    });

    it("separates 'we could not identify it' from 'we know nothing about it'", () => {
        const unmatched = verdictFor(result([], { coverage: "NOT_MATCHED", method: "no_match" }), []);
        expect(unmatched.tone).toBe("unknown");
        expect(unmatched.note).toMatch(/No installed pack recognised/);

        const empty = verdictFor(result([], { coverage: "FULL" }), []);
        expect(empty.tone).toBe("unknown");
        expect(empty.note).toMatch(/coverage gap, not a clean bill of health/);
    });

    it("never claims a clean bill of health from an empty answer", () => {
        const v = verdictFor(result([], { coverage: "FULL" }), []);
        expect(v.headline).not.toMatch(/nothing wrong|clean|fine/i);
    });

    it("quotes how the match was made, so a count is never read alone", () => {
        const v = verdictFor(result([claim("high", "a")], { method: "family" }), []);
        expect(v.note).toMatch(/Matched by family/);
    });

    it("carries no money in it, because the payload has none", () => {
        const v = verdictFor(result([claim("high", "a")]), []);
        expect(`${v.headline} ${v.note}`).not.toMatch(/[€$₺£]|\bTL\b|cost|price/i);
    });
});

describe("severityShare", () => {
    it("is proportional and ordered worst-first", () => {
        const share = severityShare({ total: 4, high: 2, medium: 1, low: 1, handled: 0 });
        expect(share.map((s) => s.severity)).toEqual(["high", "medium", "low"]);
        expect(share[0].percent).toBe(50);
    });

    it("is empty when there is nothing to divide", () => {
        expect(severityShare({ total: 0, high: 0, medium: 0, low: 0, handled: 0 })).toEqual([]);
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
    high: number;
    medium: number;
    low: number;
    handled: number;
};

export type Verdict = {
    headline: string;
    counts: Counts;
    note: string;
    tone: "clear" | "caution" | "alarm" | "unknown";
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The report's top line, derived from the payload and nothing else.
 *
 * Two rules this function exists to keep. It never states a clean bill of
 * health: an empty answer means the packs hold nothing, which is a coverage
 * gap, and saying "nothing wrong" would be a claim the engine never made. And
 * it never carries a repair cost — `Claim` has no price field, so any figure
 * here would be invented.
 */
export function verdictFor(result: LookupResult, handled: string[]): Verdict {
    const marked = new Set(handled);
    const counts: Counts = {
        total: result.claims.length,
        high: result.claims.filter((c) => c.severity === "high").length,
        medium: result.claims.filter((c) => c.severity === "medium").length,
        low: result.claims.filter((c) => c.severity === "low").length,
        handled: result.claims.filter((c) => marked.has(claimKey(c))).length,
    };

    if (!counts.total) {
        return {
            headline: "Nothing known about this one yet",
            counts,
            note: emptyReason(result),
            tone: "unknown",
        };
    }

    const tail = counts.handled ? ` · ${counts.handled} handled` : "";
    const headline = counts.high
        ? `${plural(counts.total, "known risk")}, ${counts.high} serious${tail}`
        : `${plural(counts.total, "known risk")}, none serious${tail}`;

    return {
        headline,
        counts,
        note: confidenceNote(result),
        tone: counts.high ? "alarm" : "caution",
    };
}

/** The distribution bar's segments, worst first. Percentages, not counts, so
 * the bar reads at a glance without a legend. */
export function severityShare(
    counts: Counts,
): { severity: string; percent: number }[] {
    if (!counts.total) return [];
    return (["high", "medium", "low"] as const)
        .map((severity) => ({
            severity,
            percent: Math.round((counts[severity] / counts.total) * 100),
        }))
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
Two rules it exists to hold, each with a test: it never states a clean
bill of health, because an empty answer means the packs hold nothing and
that is a coverage gap rather than good news; and it carries no money,
because Claim has no price field and any figure would be invented.

It also always quotes how the match was made beside the count. "3
serious" read alone is a different claim from "3 serious, matched by
family" — and the second is the one the engine actually made.
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

    let {
        result,
        handled = [],
        mode = "buyer",
    }: { result: LookupResult; handled?: string[]; mode?: Mode } = $props();

    const verdict = $derived(verdictFor(result, handled));
    const share = $derived(severityShare(verdict.counts));

    // The bar is decoration for a sighted reader and noise for a screen
    // reader unless it says what it means, so it carries the same numbers the
    // headline does as its accessible name.
    const barLabel = $derived(
        `severity mix: ${share.map((s) => `${s.percent}% ${s.severity}`).join(", ")}`,
    );
</script>

<div class="verdict {verdict.tone}">
    <p class="verdict-line">{verdict.headline}</p>
    {#if share.length}
        <div class="verdict-bar" role="img" aria-label={barLabel}>
            {#each share as segment (segment.severity)}
                <span
                    class="seg {segment.severity}"
                    style="width: {segment.percent}%"
                ></span>
            {/each}
        </div>
    {/if}
    <p class="verdict-note">{verdict.note}</p>
    {#if mode === "author" && result.flags?.length}
        <p class="flag">flags: {result.flags.join(", ")}</p>
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
                {#each group.claims as claim (claimKey(claim))}
                    <ClaimCard
                        {claim}
                        {mode}
                        checked={handled.includes(claimKey(claim))}
                        onCheck={(next) => check(claimKey(claim), next)}
                    />
                {/each}
            </section>
        {/each}
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
    font-size: var(--t-md);
    line-height: var(--lh-read);
}
.verdict {
    border-left: var(--ring) solid var(--line);
    padding: var(--s-3) 0 var(--s-3) var(--s-4);
    margin-bottom: var(--s-5);
}
.verdict.alarm {
    border-left-color: var(--high);
}
.verdict.caution {
    border-left-color: var(--medium);
}
.verdict.unknown {
    border-left-color: var(--dim);
}
.verdict-line {
    font-size: var(--t-lg);
    line-height: var(--lh-lg);
    font-weight: 600;
    margin: 0 0 var(--s-2);
    font-variant-numeric: tabular-nums;
}
.verdict-note {
    margin: var(--s-2) 0 0;
    color: var(--dim);
    font-size: var(--t-sm);
    max-width: var(--measure);
}
.verdict-bar {
    display: flex;
    height: 6px;
    border-radius: 999px;
    overflow: hidden;
    background: var(--panel-2);
    max-width: 22rem;
}
.verdict-bar .seg.high {
    background: var(--high);
}
.verdict-bar .seg.medium {
    background: var(--medium);
}
.verdict-bar .seg.low {
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
can act on, a proportional severity bar, and the match note underneath —
in that order, because "3 known risks, 1 serious" is the sentence and
"matched by family" is the qualification, not the other way round.

The bar carries the same numbers as its accessible name; a decorative
div that says nothing to a screen reader is not decoration, it is a hole.
The claim column gets a 68ch measure and reading leading: this is the one
surface in the app someone reads rather than operates, and the one they
print.
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

const CLAIM: Claim = {
    claim_id: "c1",
    title: "A known risk",
    body: "What goes wrong.",
    advice: "Ask for the receipt.",
    severity: "high",
    subject: "S",
    relevance: 0.9,
    pack_id: "p",
    why: ["mileage over the interval"],
    sources: [{ domain: "d.example", quote: "q", stance: "supports", tier: "forum" }],
};

describe("ClaimCard", () => {
    it("says what to ask, because that is the reader's next action", () => {
        render(ClaimCard, { claim: CLAIM });
        expect(screen.getByText("Ask for the receipt.")).toBeInTheDocument();
    });

    it("keeps the author's provenance out of a buyer's card entirely", () => {
        render(ClaimCard, { claim: CLAIM, mode: "buyer" });
        expect(screen.queryByText(/relevance/)).not.toBeInTheDocument();
    });

    it("gives an author the provenance, but folded away", () => {
        render(ClaimCard, { claim: CLAIM, mode: "author" });
        const summary = screen.getByText(/Provenance/);
        expect(summary).toBeInTheDocument();
        expect(summary.closest("details")).not.toHaveAttribute("open");
    });

    it("marks a handled claim so the eye can skip it", () => {
        const { container } = render(ClaimCard, {
            claim: CLAIM,
            checked: true,
            onCheck: () => {},
        });
        expect(container.querySelector(".card.risk.done")).not.toBeNull();
    });

    it("does not offer a checkbox where nothing can record it", () => {
        render(ClaimCard, { claim: CLAIM });
        expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
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
            <p class="meta">
                {claim.pack_id} · relevance {claim.relevance}
                {#if claim.detection} · detection {claim.detection}{/if}
                {#if claim.trust !== undefined} · trust {claim.trust}{/if}
                {#if claim.disputed}<span class="badge disputed">disputed</span>{/if}
            </p>
            {#if claim.why?.length}
                <ul class="why">
                    {#each claim.why as reason}<li>{reason}</li>{/each}
                </ul>
            {/if}
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
    border-left: 3px solid var(--line);
}
.card.risk:has(.sev.high) {
    border-left-color: var(--high);
    background: var(--high-soft);
}
.card.risk:has(.sev.medium) {
    border-left-color: var(--medium);
    background: var(--medium-soft);
}
.card.risk:has(.sev.low) {
    border-left-color: var(--low);
    background: var(--low-soft);
}
.card.risk.done {
    opacity: 0.55;
}
.card.risk.done h3 {
    text-decoration: line-through;
}
.ask {
    border-top: 1px solid var(--line);
    padding-top: var(--s-2);
    margin-top: var(--s-3);
}
.provenance {
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
leading edge and a tinted ground, in the same three colours the verdict
bar uses — so the shape of a report is legible before any of it is read.
The word stays, because colour on its own is not a signal everyone gets.

Author metadata moves into a closed "Provenance" disclosure, which makes
an author's card the same shape as a buyer's rather than a longer one.
Sources keep their own disclosure: reading the quotes and auditing the
relevance score are two different questions and merging them buries the
quotes.
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
    .shell {
        display: block;
    }
    .rail,
    .no-print,
    .history,
    button,
    .check {
        display: none !important;
    }
    .work {
        padding: 0;
        max-width: none;
    }
    .report-body {
        max-width: none;
    }
    details {
        display: block;
    }
    details > summary {
        display: none;
    }
    details > *:not(summary) {
        display: revert;
    }
    .card.risk {
        break-inside: avoid;
        page-break-inside: avoid;
        background: none;
        border: 1px solid #999;
        border-left-width: 3px;
    }
    .verdict {
        break-after: avoid;
    }
    blockquote {
        break-inside: avoid;
    }
    a[href^="#"]::after {
        content: "";
    }
    a[href^="http"]::after {
        content: " (" attr(href) ")";
        font-size: 90%;
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
path on every platform Tauri ships to — so there is no export format to
maintain and no file the app has to write anywhere.

The sheet drops the rail, the buttons and the checkboxes, and forces every
disclosure open: a folded source on paper is a source the reader cannot
reach. Cards avoid page breaks, and external links print their href,
because a citation the reader cannot follow off the page is not a citation.

print.css is the one sheet allowed a raw colour, and the guard test now
says why: paper has no theme, so a token resolving against the screen's
palette is the wrong grey there by construction.
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
        expect(humanize("odometer_km")).toBe("Odometer km");
    });

    it("leaves an already-readable label alone", () => {
        expect(humanize("Year")).toBe("Year");
    });

    it("survives the shapes a key can actually arrive in", () => {
        expect(humanize("")).toBe("");
        expect(humanize("a")).toBe("A");
        expect(humanize("__")).toBe("");
    });

    it("is a transform, not a table — an unseen key still reads", () => {
        expect(humanize("thermal_paste_grade")).toBe("Thermal paste grade");
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
 * thing that goes stale the first time a pack adds a key. This reads whatever
 * the API hands it, including keys from a category nobody has written yet.
 */
export const humanize = (key: string): string => {
    const words = (key ?? "").replace(/[_-]+/g, " ").trim();
    if (!words) return "";
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
map would fix that and break something bigger: it is pack vocabulary in
the frontend, which test_ui_contains_no_pack_vocabulary forbids for the
good reason that it goes stale the first time a pack adds a key.

humanize is a transform over whatever the API hands it, so a key from a
category nobody has authored yet reads correctly too. Tested with a key
that exists in no pack, to make the point that it is not a table.
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
        await userEvent.click(screen.getByText(/More details/));
        expect(await screen.findByLabelText(/Beta key/)).toBeInTheDocument();
    });

    it("says there is nothing to ask when no pack is installed", async () => {
        stubFetch({ ...ONE_PACK, "/api/packs": [] });
        render(Describe, { onResult: () => {} });
        expect(await screen.findByText(/nothing to ask/)).toBeInTheDocument();
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

    let { onResult }: { onResult: (result: LookupResult) => void } = $props();

    let packs = $state<Pack[]>([]);
    let packId = $state("");
    let kinds = $state<string[]>([]);
    let kind = $state("");
    let identityKeys = $state<{ key: string; required: boolean }[]>([]);
    let contextTerms = $state<Term[]>([]);
    let identity = $state<Record<string, string>>({});
    let context = $state<Record<string, string>>({});

    let query = $state("");
    let matches = $state<Subject[]>([]);
    let searching = false;
    let error = $state("");
    let busy = $state(false);

    // A choice with one option is not a choice; asking it is a step the reader
    // pays for and learns nothing from.
    const choosePack = $derived(packs.length > 1);
    const chooseKind = $derived(kinds.length > 1);

    const requiredKeys = $derived(identityKeys.filter((k) => k.required));
    const optionalKeys = $derived(identityKeys.filter((k) => !k.required));
    const missing = $derived(
        requiredKeys.filter((k) => !(identity[k.key] ?? "").trim()).map((k) => k.key),
    );

    function required(key: { key: string; match_json?: string }): boolean {
        // The pack declares which attributes select a subject; the form reads
        // that rather than deciding for itself which fields matter.
        try {
            return Boolean(JSON.parse(key.match_json || "{}").required);
        } catch {
            return false;
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
        identityKeys = keys.map((k) => ({ key: k.key, required: required(k) }));
        contextTerms = vocabulary.context_key ?? [];
        identity = {};
        context = {};
    }

    async function load() {
        packs = (await api.packs()).filter((p) => p.enabled);
        if (packs.length) {
            packId = packs[0].pack_id;
            await loadPack();
        }
    }

    async function search() {
        if (searching || query.trim().length < 2) {
            matches = [];
            return;
        }
        searching = true;
        try {
            matches = (await api.subjects(query.trim(), 8)).filter(
                (s) => s.pack_id === packId,
            );
        } finally {
            searching = false;
        }
    }

    // Picking a known subject fills the identity keys from the store, which is
    // the whole point of searching first: the reader stops guessing spellings.
    async function pick(subject: Subject) {
        query = subject.label;
        matches = [];
        const detail: SubjectDetail = await api.subject(subject.subject_id!);
        kind = detail.kind;
        identity = Object.fromEntries(
            detail.attributes.filter((a) => a.is_identity).map((a) => [a.key, a.value_text]),
        );
    }

    async function ask() {
        error = "";
        if (missing.length) return;
        busy = true;
        try {
            onResult(
                await api.lookup({
                    kind,
                    identity: collect(identity),
                    context: collect(context),
                }),
            );
        } catch (e) {
            error = e instanceof Error ? e.message : String(e);
        } finally {
            busy = false;
        }
    }

    function clear() {
        identity = {};
        context = {};
        query = "";
        matches = [];
        error = "";
    }

    const ready = load();
</script>

{#await ready}
    <p class="state loading">Loading packs…</p>
{:then}
    {#if !packs.length}
        <EmptyState
            title="No packs installed, so there is nothing to ask"
            detail="The engine answers from installed knowledge. Install a pack and this
                    form fills itself in from what that pack declares."
        />
    {:else}
        {#if choosePack || chooseKind}
            <div class="row">
                {#if choosePack}
                    <div class="field">
                        <label for="pack">Pack</label>
                        <select id="pack" bind:value={packId} onchange={loadPack}>
                            {#each packs as pack (pack.pack_id)}
                                <option value={pack.pack_id}>{pack.name}</option>
                            {/each}
                        </select>
                    </div>
                {/if}
                {#if chooseKind}
                    <div class="field">
                        <label for="kind">Kind</label>
                        <select id="kind" bind:value={kind}>
                            {#each kinds as k (k)}<option value={k}>{k}</option>{/each}
                        </select>
                    </div>
                {/if}
            </div>
        {/if}

        <div class="field wide">
            <label for="subject-search">Find one the pack already knows</label>
            <input
                id="subject-search"
                bind:value={query}
                oninput={search}
                autocomplete="off"
                placeholder="start typing…"
            />
        </div>

        {#if matches.length}
            <ul class="matches">
                {#each matches as match (match.subject_id)}
                    <li>
                        <button class="ghost" onclick={() => pick(match)}>
                            {match.label}
                            <span class="meta">{match.kind} · {match.claims} claim(s)</span>
                        </button>
                    </li>
                {/each}
            </ul>
        {/if}

        <div class="row">
            {#each requiredKeys as key (key.key)}
                <div class="field">
                    <label for="id-{key.key}">
                        {humanize(key.key)}<span class="req">*</span>
                    </label>
                    <input id="id-{key.key}" bind:value={identity[key.key]} />
                </div>
            {/each}
        </div>

        {#if optionalKeys.length || contextTerms.length}
            <details class="wide">
                <summary class="meta">More details — narrows the answer</summary>
                <div class="row">
                    {#each optionalKeys as key (key.key)}
                        <div class="field">
                            <label for="id-{key.key}">{humanize(key.key)}</label>
                            <input id="id-{key.key}" bind:value={identity[key.key]} />
                        </div>
                    {/each}
                </div>
                <div class="row">
                    {#each contextTerms as term (term.term_id)}
                        <div class="field">
                            <label for="ctx-{term.term_id}">
                                {humanize(term.term_id)}
                                <span class="meta">{term.unit}</span>
                            </label>
                            <input id="ctx-{term.term_id}" bind:value={context[term.term_id]} />
                        </div>
                    {/each}
                </div>
            </details>
        {/if}

        <div class="row">
            <button onclick={ask} disabled={busy || missing.length > 0}>
                {busy ? "Looking…" : "What goes wrong with this one?"}
            </button>
            <button class="ghost" onclick={clear}>Clear</button>
            {#if missing.length}
                <span class="meta">Still needed: {missing.map(humanize).join(", ")}</span>
            {/if}
        </div>

        <div aria-live="polite">
            {#if error}<p class="state error">{error}</p>{/if}
        </div>
    {/if}
{:catch e}
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
context term, about fifteen inputs, all labelled in snake_case. Now the
pack and kind selects appear only when there is more than one to pick —
a choice with one option is not a choice — the required keys are the
visible form, and everything optional sits behind "More details".

Labels go through humanize, so the reader sees "Engine code" without the
frontend ever holding a list of what a pack's keys are called. Extracted
from Check.svelte as its own component with its own test, since a staged
form has states worth testing and a hero input does not.
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

const ROUTES = {
    "/api/adapters": [{ id: "a1", site: "example.com", pack_id: "p1", match: [], labels: [] }],
    "/api/packs": [
        { pack_id: "p1", name: "Pack One", version: "1", enabled: 1, subjects: 1, claims: 1, evidence: 1, digest: "d" },
    ],
    "/api/kinds": [{ kind: "widget", pack_id: "p1" }],
    "/api/identity-keys/p1": [{ key: "alpha_key", match_json: '{"required": true}' }],
    "/api/packs/p1/vocabulary": { context_key: [] },
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
        await userEvent.click(await screen.findByRole("button", { name: /Check this listing/ }));
        expect(await screen.findByText(/Paste the listing's web address first/)).toBeInTheDocument();
    });

    it("names the sites that can be read when one cannot", async () => {
        stubFetch({ ...ROUTES, "/api/analyze": { status: 404, body: "no adapter" } });
        render(Check);
        await userEvent.type(await screen.findByLabelText(/web address/i), "https://nope.example");
        await userEvent.click(screen.getByRole("button", { name: /Check this listing/ }));
        expect(await screen.findByText(/example.com/)).toBeInTheDocument();
    });

    it("offers the describe-it path below the link path, not instead of it", async () => {
        stubFetch(ROUTES);
        render(Check);
        expect(await screen.findByText(/No link\?/)).toBeInTheDocument();
    });

    it("keeps the author's scraped-fields tool out of a buyer's way", async () => {
        stubFetch(ROUTES);
        render(Check, { mode: "buyer" });
        await screen.findByLabelText(/web address/i);
        expect(screen.queryByText(/Page fields/)).not.toBeInTheDocument();
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
    import { navigate } from "../lib/router";
    import type { Adapter, LookupResult } from "../lib/types";

    let { mode = "buyer" }: { mode?: Mode } = $props();

    let url = $state("");
    let adapters = $state<Adapter[]>([]);
    let unreadable = $state(false);
    let pageFields = $state<{ label: string; value: string }[]>([]);
    let result = $state<LookupResult | null>(null);
    let error = $state("");
    let busy = $state(false);

    async function load() {
        adapters = await api.adapters().catch(() => [] as Adapter[]);
    }

    async function checkUrl() {
        error = "";
        unreadable = false;
        result = null;
        if (!url.trim()) {
            error = "Paste the listing's web address first.";
            return;
        }
        busy = true;
        try {
            const fields = Object.fromEntries(
                pageFields.filter((f) => f.label.trim()).map((f) => [f.label.trim(), f.value]),
            );
            const data = await api.analyze({
                url: url.trim(),
                title: "",
                description: "",
                fields,
            });
            if (data.lookup_id) navigate("result", data.lookup_id);
            else result = data;
        } catch (e) {
            // A 404 here is not an error the reader caused: it means no
            // installed pack ships an adapter for that site, which has its own
            // answer and its own next step.
            if (e instanceof ApiError && e.status === 404) unreadable = true;
            else error = e instanceof Error ? e.message : String(e);
        } finally {
            busy = false;
        }
    }

    function onResult(data: LookupResult) {
        if (data.lookup_id) navigate("result", data.lookup_id);
        else result = data;
    }

    const ready = load();
</script>

<section class="hero">
    <h2>Check one before you buy it</h2>
    <p class="hero-sub">
        Paste a listing and Kriko reports what is known to go wrong with that exact
        one — from the packs installed on this machine, with no account and nothing
        sent anywhere.
    </p>
    <div class="field wide">
        <label for="listing-url">Paste the listing's web address</label>
        <input
            id="listing-url"
            type="url"
            bind:value={url}
            placeholder="https://…"
            onkeydown={(e) => e.key === "Enter" && checkUrl()}
        />
    </div>
    <div class="row">
        <button onclick={checkUrl} disabled={busy}>
            {busy ? "Checking…" : "Check this listing"}
        </button>
    </div>
</section>

{#await ready then}
    {#if unreadable}
        <div class="state no-match">
            <strong>No installed pack can read that site.</strong>
            {#if adapters.length}
                <p class="meta">Readable right now:</p>
                <ul class="meta">
                    {#each adapters as adapter (adapter.id)}
                        <li>{adapter.site} — {adapter.pack_id}</li>
                    {/each}
                </ul>
            {:else}
                <p class="meta">
                    No installed pack ships a site adapter, so there is nothing to read
                    a listing with yet.
                </p>
            {/if}
            <p class="meta">Describe it by hand below instead.</p>
        </div>
    {/if}

    <div aria-live="polite">
        {#if error}
            <p class="state error">{error}</p>
        {:else if result}
            <Report {result} {mode} lookupId={result.lookup_id ?? ""} />
        {/if}
    </div>

    <details class="alt-path" open={unreadable}>
        <summary><h3>No link? Describe it instead</h3></summary>
        <Describe {onResult} />
    </details>

    {#if mode === "author"}
        <details class="wide">
            <summary class="meta">Page fields, as scraped (author)</summary>
            <p class="meta">
                Sent with the URL, to try an adapter's mapping against fields you paste
                by hand.
            </p>
            {#each pageFields as field, index}
                <div class="row">
                    <div class="field">
                        <label for="fl-{index}">Label</label>
                        <input id="fl-{index}" bind:value={field.label} />
                    </div>
                    <div class="field">
                        <label for="fv-{index}">Value</label>
                        <input id="fv-{index}" bind:value={field.value} />
                    </div>
                    <button
                        class="ghost"
                        onclick={() => (pageFields = pageFields.filter((_, i) => i !== index))}
                        >Remove</button
                    >
                </div>
            {/each}
            <button
                class="ghost"
                onclick={() => (pageFields = [...pageFields, { label: "", value: "" }])}
                >Add a field</button
            >
        </details>
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
    font-size: var(--t-xl);
    line-height: var(--lh-xl);
    margin: 0 0 var(--s-2);
}
.hero-sub {
    color: var(--dim);
    line-height: var(--lh-read);
    margin: 0 0 var(--s-5);
}
.hero input {
    font-size: var(--t-md);
    padding: var(--s-3);
}
.alt-path {
    border-top: 1px solid var(--line);
    padding-top: var(--s-4);
    margin-top: var(--s-6);
}
.alt-path > summary {
    cursor: pointer;
}
.alt-path > summary h3 {
    display: inline;
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

The check page opened with a URL field and then, with equal weight, a
fifteen-input form for the case where you have no URL. Now the paste box
is the page — with a sentence saying what happens and that nothing leaves
the machine — and the describe-it path is a disclosure underneath, which
opens itself when a site turns out to be unreadable, the one moment the
reader definitely wants it.

The author's scraped-fields tool moves below the fold, where an author's
debugging tool belongs; it sat above the divider, between a buyer and the
form they were reading towards.
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

const OFFERED = {
    "/api/packs/updates": {
        index_url: "https://example.invalid/packs.json",
        error: null,
        packs: [
            { pack_id: "p1", name: "Pack One", installed_version: "", offered_version: "1.0", state: "not_installed", reason: "" },
        ],
    },
};

describe("Welcome", () => {
    it("names what it would install, and where from", async () => {
        stubFetch(OFFERED);
        render(Welcome, { onDone: () => {} });
        expect(await screen.findByText("Pack One")).toBeInTheDocument();
        expect(screen.getByText(/example.invalid/)).toBeInTheDocument();
    });

    it("offers the file path when the index cannot be reached", async () => {
        stubFetch({
            "/api/packs/updates": { index_url: "u", error: "getaddrinfo failed", packs: [] },
        });
        render(Welcome, { onDone: () => {} });
        expect(await screen.findByText(/could not be reached/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/\.kpack file/i)).toBeInTheDocument();
    });

    it("lets the reader past without installing anything", async () => {
        const onDone = vi.fn();
        stubFetch(OFFERED);
        render(Welcome, { onDone });
        await userEvent.click(await screen.findByRole("button", { name: /Skip/ }));
        expect(onDone).toHaveBeenCalled();
    });

    it("says what an empty store means rather than looking broken", async () => {
        stubFetch({ "/api/packs/updates": { index_url: "u", error: null, packs: [] } });
        render(Welcome, { onDone: () => {} });
        expect(await screen.findByText(/offers no packs/i)).toBeInTheDocument();
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

    let { onDone }: { onDone: () => void } = $props();

    let busy = $state(false);
    let log = $state("");
    let failure = $state("");

    const offer = api.packUpdates();

    // Installing is a job, because a download outlives the request — the same
    // path Packs uses, so a pack installed here has the same provenance as one
    // installed later.
    async function install() {
        busy = true;
        failure = "";
        try {
            const { job_id } = await api.updatePacks();
            // follow() returns the way to stop watching, not a promise — the
            // job's own `done` is what says the pack is on disk. Awaiting the
            // returned function would resolve at once and hand the reader an
            // app that still knows nothing.
            await new Promise<void>((resolve) => {
                follow(job_id, (job) => {
                    log = job.message || job.log.split("\n").slice(-1)[0] || "";
                    if (!job.done) return;
                    if (job.state === "failed") failure = job.message || "Install failed.";
                    resolve();
                });
            });
            if (!failure) onDone();
        } catch (e) {
            failure = e instanceof Error ? e.message : String(e);
        } finally {
            busy = false;
        }
    }

    async function chooseFile(event: Event) {
        const file = (event.currentTarget as HTMLInputElement).files?.[0];
        if (!file) return;
        busy = true;
        failure = "";
        try {
            await api.installPack(file);
            onDone();
        } catch (e) {
            failure = e instanceof Error ? e.message : String(e);
        } finally {
            busy = false;
        }
    }
</script>

<section class="welcome">
    <h2>Kriko is installed. It knows nothing yet.</h2>
    <p class="hero-sub">
        The engine ships empty on purpose: knowledge changes weekly and the app rarely,
        so they update on separate clocks. Install a knowledge pack and the app has
        something to answer with. Everything stays on this machine.
    </p>

    <Async promise={offer} loading="Looking for packs…">
        {#snippet children(updates)}
            {#if updates.error}
                <p class="state no-match">
                    The pack index could not be reached — {updates.error}. You can install
                    a pack from a file instead, or skip and do it later from Packs.
                </p>
            {:else if !updates.packs.length}
                <p class="state empty">
                    The index offers no packs right now. Skip for now; Packs will check
                    again whenever you ask it to.
                </p>
            {:else}
                <ul class="worklist">
                    {#each updates.packs as pack (pack.pack_id)}
                        <li>
                            <strong>{pack.name}</strong>
                            <span class="meta"
                                >version {pack.offered_version ?? "unknown"}</span
                            >
                        </li>
                    {/each}
                </ul>
                <p class="meta">from {updates.index_url}</p>
                <div class="row">
                    <button onclick={install} disabled={busy}>
                        {busy ? "Installing…" : "Install and get started"}
                    </button>
                </div>
            {/if}

            <div class="field wide">
                <label for="kpack">Or install a .kpack file you already have</label>
                <input id="kpack" type="file" accept=".kpack" onchange={chooseFile} />
            </div>

            <div class="row">
                <button class="ghost" onclick={onDone}>Skip for now</button>
            </div>

            <div aria-live="polite">
                {#if log}<p class="meta">{log}</p>{/if}
                {#if failure}<p class="state error">{failure}</p>{/if}
            </div>
        {/snippet}
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
fresh launch answered nothing until someone found Check for updates.
This offers the index by name and by URL, installs through the same job
path Packs uses — so a pack installed on first run has exactly the same
provenance as one installed later — and takes a .kpack file when the
index cannot be reached.

Deliberately not bundling cars.kpack in the installer, which was the
other option on the table: that would pin knowledge to the binary's
release cadence, and the two clocks are separate on purpose. The empty
store is explained as a design decision rather than apologised for.
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

it("does not show first run once a pack is installed", async () => {
    stubFetch(EMPTY);
    render(App);
    expect(await screen.findByRole("link", { name: "New check" })).toBeInTheDocument();
    expect(screen.queryByText(/knows nothing yet/)).not.toBeInTheDocument();
});

it("does not block the app when the status call fails", async () => {
    stubFetch({ ...EMPTY, "/api/status": { status: 500, body: "boom" } });
    render(App);
    expect(await screen.findByRole("link", { name: "New check" })).toBeInTheDocument();
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
    // the app — an unreachable engine is a health problem, not a first run.
    let empty = $state(false);
    const checkStore = api
        .status()
        .then((s) => (empty = s.packs === 0))
        .catch(() => (empty = false));

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
write, migrate or reset, and a reader who removes every pack gets the
offer again — which is the right thing to show at that moment too.

The gate fails open in both directions that matter: a failing /api/status
renders the app rather than the welcome, because an unreachable engine is
a health problem and not a first run; and Skip is session state, so
skipping never writes a flag that later hides the one screen a
pack-less install needs.
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
    claim_id: id,
    title,
    body: "b",
    severity,
    subject: "s",
    relevance: 0.5,
    pack_id: "p",
});

const stored = (id: string, claims: Claim[]): StoredLookup => ({
    lookup_id: id,
    created_at: "2026-09-01",
    source: "form",
    label: `L-${id}`,
    request: {},
    response: { method: "exact", coverage: "FULL", claims },
});

describe("compare", () => {
    it("puts a claim both answers share on one row", () => {
        const c = compare(stored("a", [claim("x")]), stored("b", [claim("x")]));
        expect(c.rows).toHaveLength(1);
        expect(c.rows[0].left).not.toBeNull();
        expect(c.rows[0].right).not.toBeNull();
        expect(c.shared).toBe(1);
    });

    it("shows a claim only one of them has, on the correct side", () => {
        const c = compare(stored("a", [claim("x")]), stored("b", [claim("y")]));
        expect(c.onlyLeft).toBe(1);
        expect(c.onlyRight).toBe(1);
        const left = c.rows.find((r) => r.key.endsWith("x"))!;
        expect(left.right).toBeNull();
    });

    it("orders the rows worst first, so the difference that matters is at the top", () => {
        const c = compare(
            stored("a", [claim("low1", "low"), claim("high1", "high")]),
            stored("b", []),
        );
        expect(c.rows[0].key).toContain("high1");
    });

    it("aligns on claim_id where there is one, and pack+title where there is not", () => {
        const noId: Claim = { ...claim("ignored"), claim_id: undefined, title: "Same thing" };
        const c = compare(stored("a", [noId]), stored("b", [{ ...noId }]));
        expect(c.rows).toHaveLength(1);
        expect(c.shared).toBe(1);
    });

    it("compares two empty answers without inventing a difference", () => {
        const c = compare(stored("a", []), stored("b", []));
        expect(c).toEqual({ rows: [], shared: 0, onlyLeft: 0, onlyRight: 0 });
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
    title: string;
    left: Claim | null;
    right: Claim | null;
};

export type Comparison = {
    rows: ComparedRow[];
    shared: number;
    onlyLeft: number;
    onlyRight: number;
};

/** Two stored answers, aligned by claim identity.
 *
 * Entirely client-side over two answers the reader already has: there is no
 * compare endpoint, and adding one would put a two-listing product decision
 * into the engine, which knows nothing about listings.
 *
 * Alignment uses `claimKey`, so it works across `/api/lookup` (which returns
 * claim_id) and `/api/analyze` (which does not) — the same identity the
 * reader's own handled-checkmarks use, which is what makes a row mean the same
 * thing on both sides.
 */
export function compare(left: StoredLookup, right: StoredLookup): Comparison {
    const rows = new Map<string, ComparedRow>();

    const put = (claim: Claim, side: "left" | "right") => {
        const key = claimKey(claim);
        const row =
            rows.get(key) ?? { key, title: claim.title, left: null, right: null };
        row[side] = claim;
        rows.set(key, row);
    };

    for (const claim of left.response.claims) put(claim, "left");
    for (const claim of right.response.claims) put(claim, "right");

    // Worst first: the reason to put two listings side by side is to find the
    // difference that would change the decision, and that is a serious claim
    // one of them has.
    const worst = (row: ComparedRow) =>
        Math.min(
            row.left ? severityRank(row.left.severity) : 99,
            row.right ? severityRank(row.right.severity) : 99,
        );

    const ordered = [...rows.values()].sort(
        (a, b) => worst(a) - worst(b) || a.title.localeCompare(b.title),
    );

    return {
        rows: ordered,
        shared: ordered.filter((r) => r.left && r.right).length,
        onlyLeft: ordered.filter((r) => r.left && !r.right).length,
        onlyRight: ordered.filter((r) => !r.left && r.right).length,
    };
}

/** One side's claims in the report's own order — used to render a column when
 * the reader asks for the two answers whole rather than aligned. */
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
decision about listings, and the engine knows nothing about listings. Two
getLookup calls the reader has already made are enough.

Alignment goes through claimKey, which is the same identity the handled
checkmarks use — so it works across /api/lookup, which returns claim_id,
and /api/analyze, which does not, and a row means the same claim on both
sides. Rows come back worst-first, because the reason to put two of these
side by side is to find the difference that changes the decision.
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

const HISTORY = {
    "/api/history": {
        items: [
            { lookup_id: "a1", created_at: "2026-09-01", source: "url", label: "One", claim_count: 2 },
            { lookup_id: "b2", created_at: "2026-09-02", source: "url", label: "Two", claim_count: 1 },
        ],
    },
};

const claim = (id: string, severity: string) => ({
    claim_id: id, title: `T-${id}`, body: "b", severity,
    subject: "s", relevance: 0.5, pack_id: "p",
});

const BOTH = {
    ...HISTORY,
    "/api/lookup/a1": {
        lookup_id: "a1", created_at: "", source: "url", label: "One", request: {},
        response: { method: "exact", claims: [claim("x", "high"), claim("y", "low")] },
    },
    "/api/lookup/b2": {
        lookup_id: "b2", created_at: "", source: "url", label: "Two", request: {},
        response: { method: "exact", claims: [claim("x", "high")] },
    },
};

describe("Compare", () => {
    beforeEach(() => {
        window.location.hash = "#/compare?left=a1&right=b2";
    });

    it("puts the two labels at the head of their columns", async () => {
        stubFetch(BOTH);
        render(Compare);
        expect(await screen.findByText("One")).toBeInTheDocument();
        expect(screen.getByText("Two")).toBeInTheDocument();
    });

    it("says how the two differ before listing how", async () => {
        stubFetch(BOTH);
        render(Compare);
        expect(await screen.findByText(/1 in both/)).toBeInTheDocument();
        expect(screen.getByText(/1 only in One/)).toBeInTheDocument();
    });

    it("asks for two answers when the link names none", async () => {
        window.location.hash = "#/compare";
        stubFetch(HISTORY);
        render(Compare);
        expect(await screen.findByLabelText("First")).toBeInTheDocument();
        expect(screen.getByLabelText("Second")).toBeInTheDocument();
    });

    it("says there is nothing to compare with fewer than two stored answers", async () => {
        window.location.hash = "#/compare";
        stubFetch({ "/api/history": { items: [HISTORY["/api/history"].items[0]] } });
        render(Compare);
        expect(await screen.findByText(/two saved checks/i)).toBeInTheDocument();
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
    import { severityWord } from "../lib/report";
    import { hashWith, route, setQuery } from "../lib/router";
    import type { HistoryItem } from "../lib/types";

    let items = $state<HistoryItem[]>([]);

    const left = $derived($route.query.left ?? "");
    const right = $derived($route.query.right ?? "");
    const chosen = $derived(Boolean(left && right && left !== right));

    const listed = api.history(50).then((h) => (items = h.items));

    // The two ids live in the URL, so a comparison is a link someone can
    // paste — the same reason mode does.
    const pair = $derived(
        chosen
            ? Promise.all([api.getLookup(left), api.getLookup(right)]).then(
                  ([a, b]) => ({ a, b, diff: compare(a, b) }),
              )
            : null,
    );
</script>

<h2>Compare two checks</h2>

<Async promise={listed} loading="Loading history…">
    {#snippet children()}
        {#if items.length < 2}
            <EmptyState
                title="Compare needs two saved checks"
                detail="Run a check on each of the two you are weighing up and they will
                        both be here."
                actionLabel="Run a check"
                actionHref={hashWith({ mode: $route.query.mode }, "check")}
            />
        {:else}
            <div class="row">
                <div class="field">
                    <label for="left">First</label>
                    <select
                        id="left"
                        value={left}
                        onchange={(e) => setQuery("left", e.currentTarget.value)}
                    >
                        <option value="">choose…</option>
                        {#each items as item (item.lookup_id)}
                            <option value={item.lookup_id}>{item.label}</option>
                        {/each}
                    </select>
                </div>
                <div class="field">
                    <label for="right">Second</label>
                    <select
                        id="right"
                        value={right}
                        onchange={(e) => setQuery("right", e.currentTarget.value)}
                    >
                        <option value="">choose…</option>
                        {#each items as item (item.lookup_id)}
                            <option value={item.lookup_id}>{item.label}</option>
                        {/each}
                    </select>
                </div>
            </div>

            {#if pair}
                <Async promise={pair} loading="Loading both answers…">
                    {#snippet children(d)}
                        <p class="lede-compare">
                            {d.diff.shared} in both · {d.diff.onlyLeft} only in
                            {d.a.label} · {d.diff.onlyRight} only in {d.b.label}
                        </p>
                        <table class="compare">
                            <thead>
                                <tr>
                                    <th scope="col">Known risk</th>
                                    <th scope="col">{d.a.label}</th>
                                    <th scope="col">{d.b.label}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {#each d.diff.rows as row (row.key)}
                                    <tr>
                                        <th scope="row">{row.title}</th>
                                        <td>
                                            {#if row.left}
                                                <span class="sev {row.left.severity}"
                                                    >{severityWord(row.left.severity)}</span
                                                >
                                            {:else}<span class="meta">—</span>{/if}
                                        </td>
                                        <td>
                                            {#if row.right}
                                                <span class="sev {row.right.severity}"
                                                    >{severityWord(row.right.severity)}</span
                                                >
                                            {:else}<span class="meta">—</span>{/if}
                                        </td>
                                    </tr>
                                {/each}
                            </tbody>
                        </table>
                    {/snippet}
                </Async>
            {:else}
                <p class="meta">Pick two different saved checks to line them up.</p>
            {/if}
        {/if}
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
table.compare {
    width: 100%;
    border-collapse: collapse;
}
table.compare th[scope="row"] {
    text-align: left;
    font-weight: 400;
    max-width: 34ch;
}
table.compare th,
table.compare td {
    padding: var(--s-2);
    border-bottom: 1px solid var(--line);
    vertical-align: top;
}
table.compare thead th {
    font-size: var(--t-sm);
    color: var(--dim);
    text-transform: uppercase;
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
comparison is a link someone can paste, and reloading restores it. Worst
rows first, and the count line says how the two differ before the table
says how.

Reached from a report ("Compare with another", which prefills that
answer as the first side) and from History as a page. Both are links, so
the entry point is a URL rather than a mode the app remembers being in.
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
in the navigation and not in the router.

- `styles/` — `tokens.css` (the only file naming a colour), `base.css`,
  `components.css`, `print.css`. Class-based, no component `<style>` blocks.
- `lib/` — the typed API client, pure derivation (`report.ts`, `verdict.ts`,
  `compare.ts`, `health.ts`, `fields.ts`) and shared components. Derivation is
  pure so it is tested without a DOM.
- `routes/` — one component per destination.

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
ci.yml was hand-dispatched for its stale-bundle comparison — which is a
local obligation while the workflow is paused to workflow_dispatch, not a
gate that fires on push.

B52's first-run bullet is the only reader-facing item this pass closes;
signing, the Windows success path and the extension against a real
Sahibinden page are all still unconfirmed by a human, and the bullet says
so rather than being struck through.
EOF
)"
```

- [ ] **Step 9: Push**

```bash
git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
```

Ship to the reader, not to the branch: the next `v*` tag is what puts any of this in an
installer someone can double-click.
