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

#: Said in every brief that lets an agent fetch (B154). A run was seen asking
#: one site three times for the page it had refused with a 403 the first time:
#: a site that turns away the agent's fetcher usually does it every time, and
#: the run spends its budget on the one source it cannot have. Imported by the
#: other briefs that fetch (the quick look, the pack author) so there is one
#: wording, and by the door that spawns agents, which adds it to any brief
#: that lacks it.
REFUSED_PAGE = (
    "A page that answers 401, 403 or 429, or shows a captcha or an \"access "
    "denied\" page, is that site refusing your fetcher, and it will most "
    "likely refuse the same way again. Do not fetch it a second time: take the "
    "same question to another source."
)


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

        # Whose bar this is, said rather than implied. (D5) A reader read one
        # pack's bullets as Kriko's own taste and reported the section as
        # fixated on that pack's category. It is not the engine's:
        # `research/principle.md` is pack data, quoted verbatim, and a pack
        # for another category ships a different bar — the two in this
        # repository state very different ones, and the scaffold's
        # placeholder states none. But a heading that names no owner invites
        # exactly that reading, and the fix is one line here rather than an
        # explanation nobody will be given at the moment they need it.
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

        # The pack's identification method travelled in the generated skill
        # until B178 capped that document; it arrives here instead, beside the
        # bar it serves.
        if task.identification.strip():
            lines += ["", "## How to identify this subject before searching", "",
                      task.identification.strip()]

        # What earlier runs did, so this one starts from their lessons
        # instead of their mistakes. The runs arrive as plain data
        # (`task.prior_runs`, from the interface's submission log) and are
        # rendered here rather than in the engine, so a researcher running
        # with no history beside it simply renders no section — and the two
        # planes keep one protocol.
        memory = _memory_section(task)
        if memory:
            lines += [""] + memory

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

        # Reading strategy, because "read the page" is where runs quietly
        # lose: a whole page pushed wholesale into a finding, a long page
        # re-fetched for each quote, an aggregator's rewrite trusted as if it
        # were an owner's own words. Extract-then-verify is the whole of the
        # instruction, and the source order is deliberately generic — the
        # pack's bar owns category taste, not which sites lie.
        lines += [
            "",
            "## How to read",
            "",
            "Read for the passages about this subject, not the page: find "
            "the part that names a failure, copy the quote while the page is "
            "open, and move on. A page too long to search inside is one to "
            "skip, not one to re-fetch. Run searches in parallel where your "
            "harness allows, and read the promising pages while the next "
            "search runs.",
            "",
            "Sources, best first: official notices and technical bulletins, "
            "regulator or recall databases, specialist threads where owners "
            "describe their own unit. Worst: pages that repeat a category's "
            "marketing or aggregate other pages. A finding resting on an "
            "owner's own words is stronger than the same words on a site "
            "that sells replacements.",
            "",
            f"## How much run this is ({task.effort})",
            "",
        ]
        lines += _budget_lines(task)
        lines += [
            "",
            REFUSED_PAGE,
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
            "Each finding is an object, and these seven fields are not optional:",
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
            f"- `rationale` — {task.rationale_rule}",
            "",
            "Worth setting too: `component` or `component_hint` — the concrete "
            "part the finding is about. A risk with nothing to anchor it to is "
            "refused, because a risk that could belong to any configuration "
            "belongs to none.",
            "",
            # The loop, and the half of it that was missing: the answer tells
            # the agent what the run did NOT establish, so the next queries can
            # come from the gap instead of from re-rolling the seeds. A submit
            # that only reported its own verdicts made the next search a
            # guess, and the guess was always "run the seeds again".
            "The call answers with a verdict per finding, so you learn "
            "immediately which of your work did not survive, and with what "
            "this run did not establish: the pack's domains that still hold "
            "no claim for this subject. That answer is the loop's turn. "
            "After a submit, write the next queries for the domains it names "
            "as empty — never re-run a seed that already returned its page — "
            "and submit a refused finding again once the field its verdict "
            "names is filled in. Stop when the answer names nothing missing "
            "or two rounds of gap queries keep nothing new, and report what "
            "you could not establish. Findings arrive as drafts: submitting "
            "is not publishing, and one you are unsure of is better filed "
            "with its weak source than dropped.",
            "",
            # The verifier's agent-side half. The mechanical half is the
            # gate itself; this pass catches what a gate never sees — a
            # finding the agent would refuse itself if it reread it. Cheap
            # (it costs one reread, not a round trip) and it is the only
            # quality pass that runs *before* work is stored.
            "Before you submit, grade each finding against the bar above: "
            "is the quote copied character for character from a page you "
            "still hold? does the rationale say what goes wrong, when, and "
            "what it costs? could the title belong to any product, or only "
            "this one? Drop the ones you would refuse yourself.",
            "",
            "If a search returns nothing usable, report that. An empty result is "
            "a coverage finding; a plausible-looking invented one is a defect "
            "that will outlive you in the pack. A query that twice returns "
            "nothing usable is a dead end — record it and take a different "
            "shape; a third run of the same words is a seed re-roll.",
        ]
        widening = tuple(task.search_aliases) + tuple(task.search_names)
        if widening:
            lines += ["",
                      "Aliases below may be used to WIDEN a search. They must "
                      "never be used to attribute a claim, because they are "
                      "shared with sibling products: "
                      + ", ".join(widening)]
        if task.guidance.strip():
            lines += ["", task.guidance.strip()]
        return "\n".join(lines)

    def gather(self, task: ResearchTask) -> list[Document]:
        """Nothing. The harness fetches; Kriko stores what it submits."""
        return []

    def extract(self, task: ResearchTask, document: Document) -> list[Finding]:
        """Nothing. The harness reads; Kriko stores what it submits."""
        return []


def _budget_lines(task: ResearchTask) -> list[str]:
    """The effort, stated as numbers and stop conditions.

    A brief that asks for depth without naming a number produces the
    documented failure mode of every budget-less research loop: searching
    endlessly for sources that do not exist, and stopping nowhere. The two
    modes buy different amounts of run, and both say when they are over.
    """
    if task.effort == "deep":
        pages = max(task.max_documents, 4)
        return [
            "This is a deep run, and the budget is the point. Run at most 4 "
            "parallel search threads; after each submit, write up to 2 "
            f"follow-up queries per open domain from the gap the answer "
            f"named — never a seed re-roll. Read at most {pages} pages "
            f"before the first submit, and stop the whole run at "
            f"{2 * pages}. Stop when the submit answer names no gap, or "
            "when two rounds of gap queries keep nothing new. Depth comes "
            "from following the gap, not from searching the same thing "
            "longer.",
        ]
    return [
        "This is a fast run: one breadth of searches — the seeds worth "
        "running and your own, in parallel where your harness allows — then "
        "one read pass per promising page, and no follow-up round the "
        "submit answer does not ask for. Stop when the answer names no gap, "
        f"or when a round of searches keeps nothing new, and read at most "
        f"{max(task.max_documents, 4)} pages. This is a minutes-long job, "
        "not a project.",
    ]


def _memory_section(task: ResearchTask) -> list[str]:
    """What earlier runs did, rendered as instructions rather than as history.

    The three lines an agent can act on: which queries earned their keep
    (reuse the shapes), which ones led to nothing (do not repeat them), and
    what the refusals said (write past them). The runs arrive as plain dicts
    (`kept`, `refused`, `queries`, and refusal heads already summarised by
    the caller), so this stays a rendering decision — the engine never reads
    its own history to make one.
    """
    runs = [run for run in task.prior_runs if isinstance(run, dict)]
    if not runs:
        return []
    kept = sum(int(run.get("kept") or 0) for run in runs)
    refused = sum(int(run.get("refused") or 0) for run in runs)
    lines = [
        "## What earlier runs on this subject did",
        "",
        f"{len(runs)} submit(s) before this one kept {kept} and lost "
        f"{refused} findings. Start from their lessons:",
        "",
    ]
    live: dict[str, int] = {}
    dead: dict[str, int] = {}
    for run in runs:
        bucket = live if int(run.get("kept") or 0) else dead
        for query in run.get("queries") or []:
            query = str(query).strip()
            if query:
                bucket[query] = bucket.get(query, 0) + 1
    # A query that once led to something kept is a live shape even if another
    # run of it found nothing — the shape earned its keep, the subject may
    # simply have been covered.
    for query in [q for q in dead if q in live]:
        del dead[query]
    if live:
        shapes = ", ".join(f"'{q}'" for q in sorted(
            live, key=lambda q: live[q], reverse=True)[:5])
        lines.append(f"- Searches that led to kept findings: {shapes} — "
                     "shapes worth reusing.")
    if dead:
        shapes = ", ".join(f"'{q}'" for q in sorted(
            dead, key=lambda q: dead[q], reverse=True)[:5])
        lines.append(f"- Searches that led to nothing kept: {shapes} — do "
                     "not repeat these; write different shapes.")
    heads: dict[str, int] = {}
    for run in runs:
        for head in run.get("refusal_heads") or []:
            heads[str(head)] = heads.get(str(head), 0) + 1
    if heads:
        top = "; ".join(f"{head} (x{count})" for head, count in
                        sorted(heads.items(), key=lambda kv: -kv[1])[:3])
        lines.append(f"- Findings were refused for: {top} — write past "
                     "these this time.")
    return lines
