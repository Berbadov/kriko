# How Kriko's docs are written

Rules, not taste. A page that breaks one is wrong. They exist because the docs
outgrew their author, and "it is all in the docs" is false of a page nobody
opens.

1. **Lead with the task.**
   Title pages and sections by what the reader is doing ("Install it on
   Windows"), not by what the thing is ("Extension architecture"). The first
   sentence answers the heading; background comes after, or never.
2. **One page per job.** One sitting's work per page.
   Split two jobs; fold half a job into its neighbour.
   Pages that exist for completeness get deleted: completeness is the code's
   job.
3. **Short sentences.** One idea each; split on "which" and "and".
   No filler ("The store is SQLite", not "It is worth noting that...").
4. **Show it.** An example beats a description; a pasteable command beats an
   example. Show what it prints when it works, because a command with no
   expected output is half an instruction.
5. **Scannable in a minute.** Headings, first lines and code blocks carry the
   shape. Tables over paragraphs; lists over tables for incomparable items;
   never a wall.
6. **Say the failure.** Every fallible setup step shows the failure and the fix,
   in a blockquote under the step, not in a bottom troubleshooting section the
   reader reaches after guessing.
7. **Diagrams for structure, prose for reasons.**
   Diagram the shapes (sequences, layerings, branched decisions), not the
   sentences: two boxes and an arrow is a slow sentence.
   **Mermaid only.** Text survives rebases and diffs, and artifacts and GitHub
   render it.
8. **Write for the stranger.** No "as discussed above" across pages.
   Link with a description ("see [the pack contract](PACK_CONTRACT.md) for what
   a pack must contain"), never "see [here](PACK_CONTRACT.md)".
9. **British English, the product's words.** Colour, behaviour, recognise.
   Use the on-screen word (*risk*, not *claim*, where the reader says risk) and
   give the code's word once in brackets on first use.
10. **Every install doc stands alone.**
    Real paths, real commands, all prerequisites, no assumed checkout (unless
    it is for contributors). Test by reading as a stranger: a step that needs
    something unmentioned is broken.
11. **No category, no vendor.** A document names no product type, no catalog
    and no brand; and no model, no agent product and no search provider. Roles
    instead: *a coding agent CLI*, *a local model server*, *a hosted search*.
    A name in a document is a promise to every reader, and this project's
    answers change per machine: the model list is read from the installed CLI at
    runtime precisely because a typed list is stale within days. A path under
    `packs/<name>/` is a location, not a category claim, and stays. A worked
    example built on one category is a claim, and goes.
12. **No document is a second status list.** `backlog.md` holds open work and
    nothing else. Finished work is a commit, and its message carries the
    reasoning, so no document can drift away from the tree.

## Exempt

- **`backlog.md`** — a work log, allowed length, carrying the reasoning that a
  finished item's commit message cannot hold in a table.
- **`docs/superpowers/specs/`** — frozen dated design records. Never tidy: a
  rewritten record is not a record.
- **`docs/audits/`** — a dated audit of a named release, read as the record of
  what was found at the time.
- **Code comments** — answer "why is this like this", at whatever length that
  takes.
