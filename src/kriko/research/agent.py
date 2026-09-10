"""The $0 plane: let the harness that is already paid for do the reading.

A Claude Code or opencode subscription comes with web search and a model that
can read. Kriko does not need to buy either again — it needs to say precisely
what to look for, what counts as worth keeping, and what shape to return. That
is what `brief()` produces; the harness does the work and submits results back
through the MCP tools, which never spend a token of Kriko's own.

`gather()` and `extract()` return nothing on purpose. This plane does not fetch
and does not call a model, and pretending otherwise by quietly falling back to a
paid path would turn "free" into a surprise bill. When there is no agent, the
honest answer is an empty list and a brief someone can act on.

**Which makes the brief an interface, not prose.** It is this plane's whole
output, and every tool name in it is a call an agent will actually attempt.
Until 2026-09-10 it named `add_document` and `add_evidence` — two tools from
before the MCP surface consolidated on `submit_findings`, neither of which has
existed for months. An agent handed this brief followed it and failed, and the
reader saw a Research button that produced a document nothing could act on.
`test_agent_instructions_name_real_tools.py` now compares every tool named
here against what `app/mcp_server.py` actually registers, because two
documents that instruct agents — this one and the generated skill in
`app/agentskill.py` — drifting apart is a class of defect, not an incident.
"""

from kriko.research.base import Document, Finding, ResearchTask


class AgentResearcher:
    """Research by instructing a harness. Marginal cost: zero."""

    name = "agent"
    cost_basis = "subscription"

    def brief(self, task: ResearchTask) -> str:
        lines = [
            f"# Research: {task.subject_label}",
            "",
            f"- subject id: `{task.subject_id}`",
            f"- kind: {task.subject_kind}",
            f"- pack: {task.pack_id}",
        ]
        if task.identity:
            known = ", ".join(f"{k}={v}" for k, v in sorted(task.identity.items()))
            lines.append(f"- known: {known}")
        if task.attribution_aliases:
            lines.append(f"- also called: {', '.join(task.attribution_aliases)}")
        if task.markets:
            lines.append(f"- market: {', '.join(task.markets)}")
        if task.languages:
            lines.append(f"- pack languages: {', '.join(task.languages)}")

        # Whose bar this is, said rather than implied. (D5) The reader read
        # the cars pack's four bullets — "this engine code, this gearbox
        # type" — as Kriko's own taste and reported the section as "still car
        # fixated". It is not the engine's: `research/principle.md` is pack
        # data, quoted verbatim, and a pack for a different category ships a
        # different bar (`packs/drill/` does, and the scaffold's placeholder
        # is generic). But a heading that names no owner invites exactly that
        # reading, and the fix is one line here rather than an explanation
        # nobody will be given at the moment they need it.
        lines += [
            "",
            f"## What makes a claim worth keeping — the `{task.pack_id}` pack's bar",
            "",
            f"Set by the pack, not by Kriko: this is `{task.pack_id}`'s own "
            "`research/principle.md`, quoted as written. Another category's "
            "pack states a different bar, and it is the pack's to change.",
            "",
        ]
        lines.append(task.value_principle.strip() or
                     "(this pack ships no value principle — keep only claims "
                     "specific to this subject and predictable without inspecting it)")

        plan = task.rendered_plan()
        lines += ["", "## Searches to run", ""]
        if plan:
            # **Seeds, not a script**, and said in the brief rather than left
            # to be inferred. The pack's templates are one author's guess at
            # the query shapes that work for this category; the agent is
            # holding the subject, and it is the only party that can see that
            # a query returned a sibling engine or a different market. B95:
            # the reader's words were "agent should decide the queries".
            lines += [
                "These are the pack's seed queries, not a script. Run the ones "
                "that are worth running, drop the ones that clearly do not fit "
                "this subject, and write better ones — the search that finds "
                "the finding is the one you should report.",
                "",
            ]
            # Grouped by language, because a pack that serves a market
            # searches in that market's language and an ungrouped list makes
            # that look like a mistake. Order is the pack's, primary first.
            order: list[str] = []
            for _, lang in plan:
                if lang not in order:
                    order.append(lang)
            number = 0
            for lang in order:
                if len(order) > 1 or lang:
                    lines.append(f"**In {lang or 'the pack\'s language'}:**")
                for query, query_lang in plan:
                    if query_lang != lang:
                        continue
                    number += 1
                    lines.append(f"{number}. {query}")
                lines.append("")
            if task.languages:
                lines.append(
                    f"Search in the language a source is written in, not in a "
                    f"mixture: this pack ships text in "
                    f"{', '.join(task.languages)}"
                    + (f" and its claims are about "
                       f"{', '.join(task.markets)}" if task.markets else "")
                    + ". A part name, a symptom and a subject's own name "
                      "written in three languages at once is a query nobody "
                      "types, and "
                      "it is the one thing that reliably returns nothing."
                )
        else:
            # Said, not omitted. A pack with no `research/templates.yaml`
            # renders zero queries, and a brief that simply skips the section
            # is indistinguishable from a brief for a pack that had nothing
            # worth searching — which is how "Research does nothing" looked
            # for every freshly scaffolded pack. The gap is the finding.
            lines += [
                f"This pack ships no `research/templates.yaml`, so it names no "
                f"searches of its own. Search for `{task.subject_label}` in the "
                f"terms the section above sets out, and tell whoever authored "
                f"`{task.pack_id}` that its templates file is missing — the "
                f"queries are meant to be the pack's, not yours.",
            ]

        lines += [
            "",
            "## How to report findings",
            "",
            f"At most {task.max_documents} documents. File them in one call:",
            "",
            f"    submit_findings(subject_id=\"{task.subject_id}\", "
            f"pack_id=\"{task.pack_id}\", findings=[...], queries=[...])",
            "",
            # The other half of the latitude granted above. Telling an agent
            # to write its own queries and then not asking which ones it wrote
            # means the pack can never learn anything from having asked.
            "`queries` is the searches you actually ran — the seeds you kept, "
            "the ones you rewrote, and the ones that returned nothing. It has "
            "no effect on whether a finding is kept; it is how the pack finds "
            "out which shapes were worth shipping.",
            "",
            "Each finding is an object, and these six fields are not optional:",
            "",
            "- `quote` — VERBATIM from the page. Never paraphrase, never "
            "reconstruct from memory. The quote is what makes the claim "
            "checkable later; an invented one is worse than no claim at all.",
            "- `document_text` — the text you read the quote in. Without it "
            "there is nothing to check the quote against, and the finding is "
            "refused rather than trusted.",
            "- `source_url` — where you read it.",
            "- `title` — one specific line naming the part and the failure.",
            f"- `domain` — one of: {', '.join(task.domains) or '(pack vocabulary)'}",
            "- `severity` — high | medium | low",
            "",
            "Worth setting too: `component` or `component_hint` — the concrete "
            "part the finding is about. A risk with nothing to anchor it to is "
            "refused, because a risk that could belong to any configuration "
            "belongs to none.",
            "",
            "The call answers with a verdict per finding, so you learn "
            "immediately which of your work did not survive. Findings arrive as "
            "drafts: submitting is not publishing, and one you are unsure of is "
            "better filed with its weak source than dropped.",
            "",
            "If a search returns nothing usable, report that. An empty result is "
            "a coverage finding; a plausible-looking invented one is a defect "
            "that will outlive you in the pack.",
        ]
        widening = tuple(task.search_aliases) + tuple(task.search_names)
        if widening:
            lines += ["",
                      "Aliases below may be used to WIDEN a search. They must "
                      "never be used to attribute a claim, because they are "
                      "shared with sibling products: "
                      + ", ".join(widening)]
        return "\n".join(lines)

    def gather(self, task: ResearchTask) -> list[Document]:
        """Nothing. The harness fetches; Kriko stores what it submits."""
        return []

    def extract(self, task: ResearchTask, document: Document) -> list[Finding]:
        """Nothing. The harness reads; Kriko stores what it submits."""
        return []
