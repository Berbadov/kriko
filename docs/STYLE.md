# How Kriko's docs are written

These are rules, not taste. A page that does not follow them is wrong. The
rules exist because the docs outgrew their author, and "it is all in the docs"
is false of a page nobody opens.

1. **Lead with the task.**
   Give titles and sections the reader's job ("Install it on Windows"), not
   the thing itself ("Extension architecture"). The first sentence answers
   the heading. Background comes after, or not at all.
2. **One page per job.** One sitting of work per page. Split a page that
   holds two jobs. Delete a page that only exists for completeness: the code
   owns completeness.
3. **Simplified Technical English.** Every sentence obeys the STE rules in
   [the language section](#the-language-asd-ste100). One idea per sentence,
   approved words, no idioms.
4. **Show it.** An example is better than a description; a command the
   reader can paste is better than an example. Show what the command prints
   when it works, because a command with no expected output is half an
   instruction.
5. **Scannable in a minute.** Headings, first lines and code blocks carry
   the shape. Use tables before paragraphs; use lists before tables for
   items the reader cannot compare. Never write a wall of text.
6. **Say the failure.** Each setup step that can fail shows the failure and
   its fix, in a blockquote under the step. Do not put them in a
   troubleshooting section the reader reaches only after they guess.
7. **Diagrams for structure, prose for reasons.**
   Diagram the shapes (sequences, layers, branched decisions), not the
   sentences. Two boxes and an arrow is a slow sentence.
   **Mermaid only.** Text survives rebases and diffs, and GitHub renders it.
8. **Write for the stranger.** No "as discussed above" across pages. When
   you link, say what the link holds: "see [the pack contract](PACK_CONTRACT.md)
   for what a pack must contain", never "see [here](PACK_CONTRACT.md)".
9. **British English, and the product's words.** Colour, behaviour,
   recognise. Use the word the screen shows (*risk*, not *claim*), and give
   the code's word once, in brackets, at first use.
10. **Every install doc stands alone.**
    Real paths, real commands, all prerequisites, no assumed checkout
    (unless the page is for contributors). Read it as a stranger: a step
    that needs something the page does not name is broken.
11. **No category, no vendor.** A document names no product type, no
    catalog and no brand; and no model, no agent product and no search
    provider. Use roles: *a coding agent CLI*, *a local model server*, *a
    hosted search*. A name in a document is a promise to every reader, and
    this project's answers change per machine: the model list comes from
    the installed CLI at runtime, because a typed list is stale within
    days. A path under `packs/<name>/` is a location, not a category claim,
    and stays. A worked example built on one category is a claim, and goes.
12. **No document is a status list.** Open work lives in GitHub issues
    (mirrored to Linear), never in a file in the repo. Finished work is a
    commit, and the commit message holds the reasoning, so no document can
    drift away from the tree.

## The language: ASD-STE100

The docs use Simplified Technical English, per the ASD-STE100 specification.
The rules below are the ones that shape these pages:

| Rule | Do this | Not this |
|---|---|---|
| Approved words | Use plain, approved words, one meaning each | Jargon, corporate words, invented verbs |
| Sentence length | Keep to 20 words, one idea | Long sentences joined with "which", "and", "while" |
| Procedures | Write the imperative: "Open the file." | "The file should be opened." |
| Facts | Write simple present: "The store holds claims." | "The store will be holding claims." |
| Verb forms | No `-ing` after a preposition: "Before you close the window" | "Before closing the window" |
| Idioms | Say the thing itself: "fails", "stops" | "crash belt", "red line", "the smell", "load-bearing" |
| Strength | "must" for a requirement, imperative for an instruction | "shall", "should", "might be" |
| Articles | Keep them: "Close **the** window" | "Close window" |
| Voice | Active: "The engine refuses the claim" | "The claim is refused by the engine" |

Technical names are exempt: file paths, commands, code words and the
glossary's words (`pack`, `claim`, `plane`, `bar`, `lineup`, `draft`) keep
their exact forms. Where a glossary word has a plain-English meaning, say it
once in [GLOSSARY.md](GLOSSARY.md).

If a sentence needs "and" twice, split it. If a paragraph holds more than
six sentences, split it.

## Draw a diagram in the app's colours

Every Mermaid diagram uses the desktop app's palette, so a page reads as
part of the same product. The values come from `kriko-gpui/src/theme.rs`; if
a token moves there, it moves here.

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
| `danger` | `DANGER` `#FF6B5E` | A refusal, a failure, a limit that must not be crossed |
| `mark` | the mark's arm `#E8C04B` | At most one node: the answer, the risk shown |

Lines use `BRAND_BRIGHT` (`#86A3FF`), which reads on GitHub's light and dark
pages alike. Do not set `background`: GitHub draws the page behind the
diagram.

## Exempt

- **Code comments** — they answer "why is this like this", at whatever
  length that takes.
