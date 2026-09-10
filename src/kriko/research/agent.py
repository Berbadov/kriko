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

        lines += ["", "## What makes a claim worth keeping", ""]
        lines.append(task.value_principle.strip() or
                     "(this pack ships no value principle — keep only claims "
                     "specific to this subject and predictable without inspecting it)")

        queries = task.rendered_queries()
        lines += ["", "## Searches to run", ""]
        if queries:
            lines += [f"{n}. {q}" for n, q in enumerate(queries, 1)]
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
            f"pack_id=\"{task.pack_id}\", findings=[...])",
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
        if task.search_aliases:
            lines += ["",
                      "Aliases below may be used to WIDEN a search. They must "
                      "never be used to attribute a claim, because they are "
                      "shared with sibling products: "
                      + ", ".join(task.search_aliases)]
        return "\n".join(lines)

    def gather(self, task: ResearchTask) -> list[Document]:
        """Nothing. The harness fetches; Kriko stores what it submits."""
        return []

    def extract(self, task: ResearchTask, document: Document) -> list[Finding]:
        """Nothing. The harness reads; Kriko stores what it submits."""
        return []
