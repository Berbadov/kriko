"""Every tool an agent is told to call must be a tool that exists.

Kriko instructs agents from more than one document, and that is the whole
problem. `kriko/research/agent.py` renders the research **brief** — the sole
product of the $0 plane, since `gather()` returns nothing on purpose.
`app/agentskill.py` generates the **skill** a harness loads. `app/agenda.py`
writes the *why* on each agenda row, and `ui/src/lib/agenda.ts` writes the same
sentence for the screen. A pack may ship its own `research/skill.md`. All five
name MCP tools in prose, none of them is checked against the MCP server, and
nothing compares them to each other.

So they drifted. On 2026-09-10, on a freshly installed 0.5.2, the brief said:

    At most 5 documents. For each claim, call `add_document` then
    `add_evidence` with:

`add_document` and `add_evidence` have not existed since the MCP surface
consolidated on `submit_findings`. The generated skill had it right the whole
time; the brief did not, and the brief is the half a reader is handed when they
press Research. An agent that followed it called two tools its host could not
resolve, which from the reader's side is a Research button that does nothing —
the report that found this.

**Why this is a gate and not a correction.** Renaming a tool in
`app/mcp_server.py` is a one-line change that silently invalidates prose in
four other files, and prose has no compiler. This test is that compiler: it
reads the tools the server actually registers and fails if any document names
one it does not.

The hard part is telling a *tool* name from a field name, because both are
snake_case inside backticks and the documents are full of both — `quote`,
`document_text`, `subject_id`. Neither is enumerated here. The legitimate
non-tool words are **derived**:

* the finding fields `app/findings.py` actually reads, off its own source;
* the parameter names of every registered tool, off their signatures.

* the agenda row kinds `app/agenda.py` declares in `KINDS`;
* the alias tiers `kriko.research.plan_task` reads.

Anything else in a tool-shaped position has to be a real tool. A new field
therefore needs no edit here, and a *retired* tool cannot hide behind one.
The failure mode is deliberately a false positive: a word this cannot classify
fails the test and someone looks, rather than passing and reaching an agent.

**Only text that reaches an agent is read.** For a Python module that means
its string literals and not its docstrings — this file's own subject, the
retired `add_document`, is named three times in prose one function above the
brief it was removed from, and a check that could not tell the two apart would
have to choose between failing on its own history or not reading the brief at
all. `ast` makes the distinction exactly: a docstring is the first statement of
a module, class or function, and everything else is a string the code is
building output from.

Host prefixes pass. A harness renames what it exposes — Claude Code shows
`mcp__kriko__submit_findings`, OpenCode `kriko_submit_findings` — and a pack
that documents both forms is being helpful, not wrong, so a candidate ending in
a real tool's name is a real tool.
"""

import ast
import inspect
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

#: Where an agent is told what to call. Each of these is read as text, because
#: what reaches the agent is text — the brief's literals, the skill's header,
#: the agenda's sentence, and whatever a pack chose to write.
DOCUMENTS = [
    "src/kriko/research/agent.py",
    "src/app/agentskill.py",
    "src/app/agenda.py",
    "ui/src/lib/agenda.ts",
]

#: A pack's own agent-facing prose. Globbed rather than listed: a second
#: category's skill file must be held to the same rule as the first's, and a
#: pack nobody thought to add here is exactly the one that would drift.
PACK_GLOBS = ["packs/*/research/skill.md", "packs/*/pipeline/agent/*.md"]

#: A snake_case identifier — the shape both tools and fields take. Matched
#: inside backticks or before a `(`, which is every way these documents name a
#: callable.
_BACKTICKED = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`")
_CALLED = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\s*\(")


def _tools() -> dict:
    """The tools the MCP server registers, by name, with their signatures.

    Read off the module rather than off a list written here: a tool added,
    renamed or removed changes this set with no edit to this file, which is the
    only version of this check that keeps working.
    """
    from app import mcp_server

    names = sorted(mcp_server.registered_tools())
    return {name: getattr(mcp_server, name) for name in names}


def _finding_fields() -> set[str]:
    """The keys `accept_findings` reads out of a submitted finding.

    Derived from its source — `item.get("quote")` and its siblings — because
    the acceptance path is the definition of what a field is. A field it does
    not read is not a field, whatever a document calls it.
    """
    from app import findings

    source = inspect.getsource(findings.accept_findings)
    return set(re.findall(r'item\.get\(\s*"([a-z_]+)"', source))


def _agenda_kinds() -> set[str]:
    """The row kinds an agenda names, off the tuple that declares them.

    `unknown_subject` reads exactly like a tool and is not one; it is a kind of
    row, and both the packs' skill files and the UI's sentence name it because
    an agent has to be told that kind is a message to the catalog rather than a
    research task.
    """
    from app import agenda

    return set(agenda.KINDS)


def _alias_tiers() -> set[str]:
    """The alias tiers `plan_task` sorts a subject's names into."""
    from kriko import research

    source = inspect.getsource(research.plan_task)
    return set(re.findall(r'"(attribution_safe|search_only)"', source))


def _permitted() -> set[str]:
    """Tool names, plus every snake_case word that is legitimately not a tool."""
    tools = _tools()
    allowed = set(tools)
    allowed |= _finding_fields()
    allowed |= _agenda_kinds()
    allowed |= _alias_tiers()
    for func in tools.values():
        allowed |= set(inspect.signature(func).parameters)
    return allowed


def _host_prefixed(candidate: str, tools: set[str]) -> bool:
    """Is this a real tool under a harness's own naming?

    A rule rather than a list of prefixes: whatever a host prepends, the tool's
    own name is still the tail, and a pack documenting `kriko_submit_findings`
    beside `mcp__kriko__submit_findings` is documenting one real tool twice.
    """
    return any(candidate.endswith(tool) and candidate != tool for tool in tools)


def _agent_facing_text(path: Path) -> str:
    """The part of a file an agent actually reads.

    For Markdown, all of it. For TypeScript, everything but the comments. For
    Python, the string literals that are *not* docstrings: the brief and the
    skill are assembled out of literals, while the surrounding docstrings
    discuss the protocol — including, in this repo, the retired tool names this
    very test exists to keep out of the literals.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        return text
    if path.suffix == ".ts":
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
        return re.sub(r"//[^\n]*", " ", text)

    tree = ast.parse(text)
    docstrings = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        first = body[0] if body else None
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            docstrings.add(id(first.value))
    return "\n".join(
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings
    )


def _candidates(text: str) -> set[str]:
    return set(_BACKTICKED.findall(text)) | set(_CALLED.findall(text))


def _sources() -> list[Path]:
    found = [ROOT / name for name in DOCUMENTS]
    for pattern in PACK_GLOBS:
        found.extend(sorted(ROOT.glob(pattern)))
    return [path for path in found if path.is_file()]


def test_no_agent_facing_document_names_a_tool_that_does_not_exist():
    permitted = _permitted()
    assert "submit_findings" in permitted, "the tool list itself failed to load"

    tools = set(_tools())
    offenders = []
    checked = 0
    for source in _sources():
        checked += 1
        text = _agent_facing_text(source)
        unknown = _candidates(text) - permitted
        for candidate in sorted(c for c in unknown if not _host_prefixed(c, tools)):
            # A word this cannot classify is reported, not excused: see the
            # module docstring on why the false positive is the safe direction.
            offenders.append(f"{source.relative_to(ROOT)}: `{candidate}`")

    assert checked >= 3, f"only {checked} agent-facing document(s) found"
    assert not offenders, (
        "these documents name snake_case identifiers that are neither a "
        "registered MCP tool, a finding field `accept_findings` reads, nor a "
        "tool parameter:\n  " + "\n  ".join(offenders) + "\n\n"
        "If it is a retired tool name, fix the prose — an agent will attempt "
        "the call. If it is a legitimate new field, `accept_findings` should "
        "be reading it, and then this passes on its own."
    )


def test_the_brief_and_the_skill_agree_on_the_submission_tool():
    """Two documents, one protocol.

    The drift that shipped was not a typo — it was the brief and the skill
    describing different APIs while both looked plausible on their own. The
    tool that files a finding is the one thing they cannot disagree about, so
    it is asserted directly rather than left to the sweep above.
    """
    brief = (ROOT / "src/kriko/research/agent.py").read_text(encoding="utf-8")
    skill = (ROOT / "src/app/agentskill.py").read_text(encoding="utf-8")
    for name, text in (("brief", brief), ("skill", skill)):
        assert "submit_findings" in text, f"the {name} never names submit_findings"


def test_a_pack_with_no_templates_still_gets_a_searches_section():
    """The other half of "Research does nothing".

    `plan_task` renders queries from the pack's `research/templates.yaml`. A
    pack that ships none rendered zero, and the brief used to omit the whole
    section — so the reader of a freshly scaffolded pack got a brief that said
    what to keep and never said what to look for, indistinguishable from a
    pack with nothing worth searching. The absence is now stated.
    """
    from kriko.research.agent import AgentResearcher
    from kriko.research.base import ResearchTask

    task = ResearchTask(
        subject_id="s1", subject_label="Some Thing", subject_kind="part",
        pack_id="org.example.things", queries=[], domains=["general"],
    )
    body = AgentResearcher().brief(task)
    assert "## Searches to run" in body
    assert "research/templates.yaml" in body, (
        "a brief with no queries must say why, and name the file that would "
        "supply them"
    )
