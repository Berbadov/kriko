# How Kriko's docs are written

Rules, not taste. If a page breaks one, the page is wrong.

They exist because the docs got long enough that the person who wrote them
stopped reading them. Nobody is eager to read a boring page, and "it is all in
the docs" is not true of a page nobody opens.

---

## 1. Lead with the task

A reader arrives mid-problem. Title every page and every section by what they
are trying to do, not by what the thing is.

- **Yes:** "Install it on Windows", "Add a site the extension can read"
- **No:** "The extension architecture", "Overview of site adapters"

The first sentence of a section answers the question in its heading. Background
comes after, or not at all.

## 2. One page per job

A page covers one thing somebody does in one sitting. If it covers two, split
it. If it covers less than one, fold it into its neighbour.

**A page that exists for completeness gets deleted.** Completeness is what the
code is for.

## 3. Short sentences

One idea each. If a sentence has two clauses joined by "which" or "and", it is
usually two sentences.

No filler openings. Not "It is worth noting that the store is SQLite" — "The
store is SQLite."

## 4. Show it

An example beats a description. A command a reader can paste beats an example.

Every command shows what it prints when it works, so a reader can tell whether
it did. A command with no expected output is half an instruction.

## 5. Scannable in a minute

Someone should get the shape of a page from headings, the first line of each
section, and the code blocks. Write so that works.

Prefer a table to three paragraphs. Prefer a list to a table when the items are
not comparable. Never a wall.

## 6. Say the failure

Every setup step that can fail says what the failure looks like and what to do.
A step that only describes success is a step somebody gets stuck on alone.

Put it in a blockquote right under the step, not in a troubleshooting section
at the bottom — by the time they scroll there, they have already guessed.

## 7. Diagrams for structure, prose for reasons

A diagram earns its place when the thing is a *shape*: a sequence, a layering,
a decision with branches. Draw those.

Never draw what a sentence says better. A diagram of two boxes and an arrow is
a sentence that took longer to read.

**Mermaid only**, in a fenced block. It is text, so it survives a rebase and a
diff shows what changed; a picture does neither. Artifacts and GitHub both
render it, so nobody needs a tool to look at it.

## 8. Write for the person who has not read the other pages

No "as discussed above" across pages. Link instead, and say what is at the other
end: "see [the pack contract](PACK_CONTRACT.md) for what a pack must contain",
never "see [here](PACK_CONTRACT.md)".

## 9. British English, and the product's own words

Colour, behaviour, recognise. And the words the app itself uses on screen: a
reader who searched for *risk* should not have to work out that the docs call it
a *claim*. Where the code's word and the reader's word differ, the docs use the
reader's and say the code's once, in brackets.

## 10. Every install doc is followable alone

A reader on their own machine finishes it without asking anybody. That means
real paths, real commands, every prerequisite stated, and no step that assumes
a checkout unless the page is for contributors.

Test by reading it as somebody who has never seen the repository. If a step
needs something the page never mentioned, the page is broken.

---

## What this does not apply to

**`backlog.md` and `done.md`** are a log, not documentation. They are written
for whoever is doing the work, they are allowed to be long, and they carry the
reasoning that would clutter a doc.

**`docs/superpowers/specs/`** are design records, dated and frozen. They say
what was decided and why at a moment in time. Do not tidy them — a rewritten
record is not a record.

**Code comments** answer "why is this like this", which is the opposite job.
They are allowed the length that takes.
