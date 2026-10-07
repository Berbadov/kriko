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
12. **No document is a status list.** Open work is GitHub issues (mirrored
    to Linear), never a file in the repo. Finished work is a commit, and its message carries the
    reasoning, so no document can drift away from the tree.

## Draw a diagram in the app's colours

Every Mermaid diagram wears the desktop app's palette, so a page reads as part
of the same product. The values come from `kriko-gpui/src/theme.rs`; if a
token moves there, it moves here.

Start every diagram with this line, unchanged:

```text
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
```

Then colour nodes by role with these classes. Copy only the ones you use:

```text
classDef brand  fill:#1F4FFF,stroke:#86A3FF,color:#F2F5FF
classDef plain  fill:#090E1B,stroke:#3A4156,color:#C9D1EA
classDef ice    fill:#BFE4FF,stroke:#1F4FFF,color:#05070F
classDef danger fill:#FF6B5E,stroke:#05070F,color:#05070F
classDef mark   fill:#E8C04B,stroke:#05070F,color:#05070F
```

| Class | Token | Use it for |
|---|---|---|
| `brand` | `BRAND` `#1F4FFF` | The thing the diagram is about; one or two nodes |
| `plain` | `SURFACE_1` `#090E1B` | Everything else |
| `ice` | `ICE` `#BFE4FF` | What the reader sees or types: a screen, a command, a result |
| `danger` | `DANGER` `#FF6B5E` | A refusal, a failure, a red line |
| `mark` | the mark's arm `#E8C04B` | At most one node: the answer, the risk shown |

Lines are `BRAND_BRIGHT` (`#86A3FF`), which reads on GitHub's light and dark
pages alike. Do not set `background`: GitHub draws the page behind the
diagram.

## Exempt

- **Code comments** — answer "why is this like this", at whatever length that
  takes.
