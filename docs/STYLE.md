# How Kriko's docs are written

Rules, not taste. A page that breaks one is wrong.
They exist because the docs outgrew their author — "it is all in the docs"
is false of a page nobody opens.

1. **Lead with the task.**
   Title pages and sections by what the reader is doing
   ("Install it on Windows"), not what the thing is ("Extension architecture").
   First sentence answers the heading; background after, or never.
2. **One page per job.** One sitting's work per page.
   Split two jobs; fold half a job into its neighbour.
   Pages that exist for completeness get deleted — completeness is the code's job.
3. **Short sentences.** One idea each; split on "which"/"and".
   No filler ("The store is SQLite", not "It is worth noting that…").
4. **Show it.** An example beats a description; a pasteable command beats an example.
   Show what it prints when it works — a command with no expected output
   is half an instruction.
5. **Scannable in a minute.** Headings + first lines + code blocks carry the shape.
   Tables over paragraphs; lists over tables for incomparable items; never a wall.
6. **Say the failure.** Every fallible setup step shows the failure and the fix,
   in a blockquote under the step — not in a bottom troubleshooting section
   they reach after guessing.
7. **Diagrams for structure, prose for reasons.**
   Diagram shapes (sequences, layerings, branched decisions),
   not sentences (two boxes and an arrow is a slow sentence).
   **Mermaid only** — text survives rebases and diffs; artifacts and GitHub render it.
8. **Write for the stranger.** No "as discussed above" across pages.
   Link with a description
   ("see [the pack contract](PACK_CONTRACT.md) for what a pack must contain"),
   never "see [here](PACK_CONTRACT.md)".
9. **British English, the product's words.** Colour, behaviour, recognise.
   Use on-screen words (*risk*, not *claim* where the reader says risk);
   give the code's word once in brackets on first use.
10. **Every install doc stands alone.**
    Real paths, real commands, all prerequisites, no assumed checkout
    (unless for contributors). Test by reading as a stranger —
    a step needing something unmentioned is broken.

## Exempt

- **`backlog.md` / `done.md`** — a work log, allowed length,
  carries the reasoning docs must not.
- **`docs/superpowers/specs/`** — frozen dated design records.
  Never tidy; a rewritten record is not a record.
- **Code comments** — answer "why is this like this",
  at whatever length that takes.
