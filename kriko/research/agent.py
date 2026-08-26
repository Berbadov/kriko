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
        if queries:
            lines += ["", "## Searches to run", ""]
            lines += [f"{n}. {q}" for n, q in enumerate(queries, 1)]

        lines += [
            "",
            "## How to report findings",
            "",
            f"At most {task.max_documents} documents. For each claim, call "
            "`add_document` then `add_evidence` with:",
            "",
            "- `quote` — VERBATIM from the page. Never paraphrase, never "
            "reconstruct from memory. The quote is what makes the claim "
            "checkable later; an invented one is worse than no claim at all.",
            "- `title` — one specific line naming the part and the failure.",
            f"- `domain` — one of: {', '.join(task.domains) or '(pack vocabulary)'}",
            "- `severity` — high | medium | low",
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
