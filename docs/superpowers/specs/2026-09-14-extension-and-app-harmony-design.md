# Extension and app as one system — design

**Status:** design, nothing implemented. Filed as backlog **B113**.
**Date:** 2026-09-14.
**Prompted by:** *"Harmony and compatibility between the web extension and the
app. Both visually and algorithmically. This is very important."*

---

## 1. What is actually true today

I assumed, before reading, that this was two design systems that had drifted
apart and needed reconciling. That is wrong in an interesting way, and the real
state changes what should be built.

### The visual convergence already happened — by copy

`ui/src/styles/themes/panel.css` opens by saying so:

> *Ported from `extension/hover_lite/hover_lite.css`, which is the **live**
> stylesheet … `extension/colors_and_type.css` is a cream/lemon design system
> that nothing loads — the extension has no HTML at all — and the lemonade
> theme beside this file was built from it by mistake.*

So the app's default theme *is* the extension's look. Somebody already did this
work. What they could not do was make it stay done.

### The two files share two token names out of sixty-six

| | count |
|---|---|
| tokens defined in `ui/src/styles/themes/panel.css` | 38 |
| tokens defined in `extension/hover_lite/hover_lite.css` | 28 |
| **names in both** | **2** (`--accent`, `--font-mono`) |

Two complete vocabularies for one palette.

### The translation between them exists — in a comment

`panel.css` annotates every grey with the extension's name for it:

```css
--n-0: #0a0b0d; /* --bg-base   — the page */
--n-2: #15171c; /* --bg-panel  — cards, the rail */
--n-4: #2c313a; /* --border    — hairlines */
--n-9: #e7e9ed; /* --fg        — headings */
```

All ten greys map, and **all ten values still agree exactly today**. Checked
pair by pair. Nothing has drifted.

That is the finding. This is not a divergence to repair; it is a **fork that
has not drifted yet**, with the mapping written in a comment that nothing
reads. It is the same failure this repository keeps catching one layer further
out — `SIBLING_CODE_FAMILIES` going stale, `_MAKE_MAP` in Python, then the
site's own words in `extension/`, and now the palette. Every one of them was a
hand-maintained correspondence that was correct on the day it was written.

The right moment to build the mechanism is precisely now, while the two sides
still agree and the change is provably a no-op.

### Severity: same intent, two derivations

The three inks are identical in both (`#f0565b`, `#e2933f`, `#46b48c`). The
shapes are not:

| | app | extension |
|---|---|---|
| the colour | `--high: #f0565b` | `--high-ink: #f0565b` |
| the fill | `--high-soft: #2a1719` (hand-picked opaque) | `--high-surface: rgba(240,86,91,0.10)` (**derived**) |
| the edge | *(none)* | `--high-border: rgba(240,86,91,0.30)` |

The extension's is better and should win: a fourth severity costs it one value,
and costs the app three hand-mixed ones. The app also has no border token at
all, which is a real visual difference and not only a naming one.

### The one genuine algorithmic divergence: `claims` become `risks`

`extension/background.js:595`:

```js
risks: claims.map((claim) => { … })
```

The engine says `claims`. The app says `claims`. The extension renames them to
`risks` at its own boundary and every downstream line — `risk.severity`,
`risk.inspection_advice`, the badge count — speaks the new word.

Nothing is gained. A shared component would have to translate, a bug report
that says "risk" needs a mental hop to reach a `claims` table, and B119 has to
carry the rename forever. This is the algorithmic half of the reader's request,
and it is one word.

### What is *correctly* divergent, and must stay so

The `local_panel` block — the damage silhouette and the equipment list — is
drawn from the reader's own page and **never reaches the engine**. It is absent
from the `/api/analyze` body on purpose: the engine has no schema for a damage
silhouette and should not acquire one.

That is right, and this design must not "harmonise" it away. It does mean the
two clients legitimately show different things, and a reader comparing them
will see that. The answer is to *say* so in the panel, not to move the data.

---

## 2. What the problem actually is

Stated precisely, so the fix can be judged against it:

1. **One palette, two vocabularies, no mechanism** keeping them equal. Correct
   today, and nothing would catch tomorrow.
2. **Severity is hand-mixed in the app and derived in the extension**, so they
   can disagree on the fill while agreeing on the ink.
3. **One row has two names** (`claims` / `risks`) for no reason.
4. **The dead stylesheet is still in the tree.** `extension/colors_and_type.css`
   is 172 lines that nothing loads — it is not even in `SHIPPED` in
   `app/extension.py`. It has already misled one effort into building a whole
   theme from it.

Everything else about these two clients is already shared: the engine, the
store, the adapter rows, the `local_panel` contract.

---

## 3. Principles for the fix

Drawn from what this repository already does, not invented here.

- **Make the shared thing data, with one owner.** The same move as adapters,
  `local_panel`, and pack vocabulary.
- **A correspondence a person maintains is a bug waiting.** If the app and the
  extension must agree, something must *make* them agree and fail when they do
  not.
- **Committed build output with a staleness gate is a pattern this repo already
  runs.** `src/app/web/static/` is generated, committed, and `tools/gate.sh`
  fails on a stale bundle. A generated token file inherits that discipline for
  free — no new idea to teach.
- **The extension may not gain a build step it does not already have.** It is
  static files Chrome loads directly. Generation happens in the repo and the
  output is committed, exactly like the frontend bundle.
- **No pack vocabulary in either client.** Already enforced by
  `test_ui_contains_no_pack_vocabulary` and
  `test_the_extension_speaks_no_sites_own_language`. Nothing here weakens that.

---

## 4. Proposal

Four phases, each shippable alone and each leaving the tree better than it
found it.

### Phase 0 — subtract (no mechanism yet)

* **Delete `extension/colors_and_type.css`.** Nothing loads it, it is not in
  `SHIPPED`, and it has already cost one wrong theme.
* **Rename `risks` to `claims` in the extension.** One word, `background.js`
  and its consumers, plus the tests that name it. Do it before anything shares
  code, so nothing is built on the translation.

Small, and it makes the next phases smaller.

### Phase 1 — one palette, generated

The comment becomes the mechanism.

* `ui/src/styles/themes/panel.css` is the **source**. It is the app's default
  theme, it already carries the mapping, and the app is where a theme is picked
  — `slate` and `lemonade` exist there and have no meaning in a content script.
* A generator (`tools/tokens.py`, or a step in the existing `ui` build) reads
  the source and emits the extension's `:host` token block under its own alias
  names, from an explicit `n-0 → bg-base` table that lives **in the generator,
  not in a comment**.
* The emitted block is committed into `extension/hover_lite/hover_lite.css`
  between markers, or into a small generated file the stylesheet `@import`s —
  whichever survives the shadow-root loading better; that is an implementation
  detail to settle when writing it.
* `tools/gate.sh` gains the staleness check it already performs for the
  frontend bundle: regenerate, `git diff --exit-code`, fail if it moved.

The first run must produce **no diff**, because the values already agree. That
is the test that the mapping was transcribed correctly, and it is available
exactly once — after any drift it is gone.

### Phase 2 — severity derived, in both

Adopt the extension's shape. One ink per severity; surface and border derived
with `color-mix()` or explicit alpha. The app gains a border token it does not
have, which is a small visual improvement as well as a structural one.

### Phase 3 — say what is legitimately different

The panel draws two blocks the app cannot: the damage silhouette and the
equipment list, both read from the reader's own page. Rather than hiding that,
the app's own view of a lookup should carry a line saying that the extension
shows two further blocks that come from the listing page and never reach the
engine — so a reader comparing them learns the rule rather than suspecting a
bug.

---

## 5. Deliberately not doing

* **Not sharing components between the two clients.** Svelte in a content
  script means a framework bundle injected into every page the extension
  matches, plus a CSP argument on every site. The panel is ~1,200 lines of CSS
  and some template strings; that is the right size for what it does.
* **Not serving the tokens from the engine at runtime.** `local_panel` is
  served because it is *pack* data and changes when a pack does. The palette
  changes when this repository does, which is exactly what a committed build
  artefact is for — and a runtime fetch buys a flash of unstyled panel in
  exchange for nothing.
* **Not moving `local_panel` into the engine.** See §1. The engine has no
  schema for a damage silhouette and acquiring one would be a G6 violation
  wearing a UX justification.
* **Not unifying by copying again.** The copy is how we got here.

---

## 6. The one open decision

**Which side owns the palette.** This design says the app, on the reasoning in
Phase 1 — the app is where themes are chosen, and `panel.css` already holds the
mapping. The argument for the other direction is real though: the extension's
stylesheet is the *live* one, the one a reader actually looks at, and it was
the original. If it is preferred as the source, everything above still stands
with the arrow reversed; only the generator's direction changes.

Worth settling before Phase 1 is written, and cheap to settle: it is one line
in the generator either way.

---

## 7. Relationship to the other filed ideas

* **B115 (agents author adapters)** builds directly on this. An agent-authored
  adapter changes what the panel renders, so the panel's contract — what is
  pack data, what is palette, what is the client's own — needs to be settled
  first. That is the reason to do this design before that one.
* **B119 (glossary)** absorbs the `claims`/`risks` rename the moment Phase 0
  lands, and the glossary is where the word is then pinned.
* **B114 (Web Store)** decides how the extension is distributed, which changes
  nothing here: a generated token file is committed either way.
