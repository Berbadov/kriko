# How these documents are written

These documents use **ASD-STE100 Simplified Technical English**. The standard
(Issue 9, January 2025) holds 53 writing rules and a dictionary of about 900
approved words. It is free from [asd-ste100.org](https://www.asd-ste100.org/).

A rule below is a requirement. A page that breaks a rule is wrong.

## The rules

1. **Use an approved word only in its given part of speech and meaning.** One
   word has one meaning. If the dictionary does not approve a word, use another
   word.
2. **Write short sentences.** A step has a maximum of 20 words. A description
   has a maximum of 25 words.
3. **Write one instruction in each sentence.** Start a step with the verb.
4. **Write one topic in each paragraph.** A paragraph has a maximum of six
   sentences.
5. **Use the active voice.** Use the simple present, the simple past, the
   simple future, the imperative, and the infinitive. Use a past participle
   only as an adjective.
6. **Do not use a verb form with "-ing",** unless it is a technical noun.
7. **Do not put more than three nouns together.** "Catalog lookup limit" is
   correct. "Catalog lookup limit value" is not.
8. **Do not omit a part of the sentence.** Keep the subject, the verb, and the
   article.
9. **Use the words of the reader.** The screen says *risk* where the code says
   *claim*. Give the code word in brackets at the first use.
10. **Show the failure under the step.** A step that can fail needs its repair
    in the same place. Never put the repair in a section at the end of the
    page.
11. **Use a vertical list for complex text.** One item for each action. Do not
    put two actions in one item.
12. **Do not use an em dash, a semicolon, or a contraction.** Write two
    sentences instead.
13. **Every page stands alone.** Give the full path and the full command. Link
    with a description, not with the word "here".
14. **Name no product, no brand, no model, and no search provider.** Use the
    function: *a coding agent*, *a local model server*, *a hosted search*. A
    name in a page is a promise to every reader, and the answer of this program
    is different on each computer.
15. **Use British English.** *Colour*, *behaviour*, *recognise*.
16. **Lead with the task of the reader.** Title a page with the action
    ("Install Kriko on Windows"), not with the object ("Extension
    architecture"). The first sentence answers the title.
17. **No page is a status list.** Open work is a GitHub issue. A finished task
    is a commit, and its message holds the reason.

## The words

A word below is a **technical name** for this product. A technical name is
correct in every document, and its meaning does not change.

| Word | Meaning |
|---|---|
| **catalog** | One product category as data. The code says *pack*. |
| **product** | One manufactured thing that the store answers about. The code says *subject*. |
| **problem** | One known failure of a product, with its sources. The code says *claim*. The screen says *risk*. |
| **source** | The page behind a problem. |
| **quotation** | The words copied from a source. |
| **identity key** | A pair that names a product, for example `make=Toyota`. The code says *identity*. |
| **adapter** | The data that tells the extension how to read one site. |
| **bar** | What a catalog counts as worth the attention of a reader. It is in the `research/principle.md` file of that catalog. |
| **trust tier** | The grade of a source, for example `authoritative`. A confirming tier makes a problem *Confirmed*. |
| **check** | One lookup or one research run for one product. |
| **quick look** | A short research run from the panel, which keeps its sources. |
| **run** | The research work behind one check. It has four stages. |
| **draft** | The proposal of an agent, before an install. It contains data only. |
| **engine** | `src/kriko/` and the sidecar: the store, the lookup, and the ranking. |
| **sidecar** | The engine as a child process of the desktop app. |
| **store** | `~/.kriko/knowledge.sqlite`: the catalogs. |
| **history** | `~/.kriko/app.sqlite`: the past checks, the saved pages, and the settings. |
| **agent** | A program that reads and researches. Kriko starts it. |
| **local model** | A model that runs on your computer. |
| **paid API** | A service that bills your account for each token. |
| **job** | Long work as a durable row. The id comes at once. The log and the result outlive the process. |
| **reader** | The person who reads a listing. |

Three words have more than one meaning. Use the full form:

- **agent** is the researching program, a coding agent on this source tree, or
  the skill that an agent reads. Say *the agent*, *a contributor*, or *the
  research skill*.
- **shell** is the desktop app or the terminal shell. Say *the desktop app* or
  *the terminal*.
- **ledger** is the evidence ledger of a catalog or the ledgering stage of a
  check. Say *the evidence ledger* or *the ledgering stage*.

## Diagrams

A diagram wears the colours of the desktop app (`kriko-ui/src/styles/tokens.css`).
Start each diagram with this line, without a change:

```text
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
```

Colour a node by its function. Copy only the lines that you use:

```text
classDef brand  fill:#1F4FFF,stroke:#86A3FF,color:#F2F5FF
classDef plain  fill:#090E1B,stroke:#3A4156,color:#C9D1EA
classDef ice    fill:#BFE4FF,stroke:#1F4FFF,color:#05070F
classDef danger fill:#FF6B5E,stroke:#05070F,color:#05070F
classDef mark   fill:#E8C04B,stroke:#05070F,color:#05070F
```

| Class | Use it for |
|---|---|
| `brand` | The subject of the diagram. One node or two nodes. |
| `plain` | Everything else. |
| `ice` | What the reader sees or types: a screen, a command, a result. |
| `danger` | A refusal, a failure, or a red line. |
| `mark` | One node only: the answer, or the problem that Kriko shows. |

The lines are `BRAND_BRIGHT` (`#86A3FF`). Do not set a background, because the
page draws it.

## Code comments

A code comment is exempt from these rules. A comment answers the question "why
is this correct", and it can take the length that the answer needs.
