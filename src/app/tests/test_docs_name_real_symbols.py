"""The current docs may not name a call that no longer exists.

B90 was a research brief telling agents to call `add_document` and
`add_evidence`, tools deleted months earlier. The brief was written against a
tool list in `docs/USAGE.md` Step 4e — a *second written copy* of the MCP
surface, which went stale the moment the surface consolidated on
`submit_findings`. Nobody noticed, because prose has no compiler.

`test_agent_instructions_name_real_tools.py` closes the agent-facing half: the
brief and the generated skill are now compared against what
`app/mcp_server.py` registers. This closes the half upstream of it. A doc that
names `finish_model(...)` is where the next brief gets written from, and the
cost lands on a reader pressing Research rather than on whoever wrote the
sentence.

**The rule is resolution, not a whitelist.** A backticked call in a doc must
name something that exists: a registered MCP tool, or any `def` / `function` /
`const` in the tree. That distinction matters — `create_app(...)` and
`declared_columns(...)` are real functions and docs are right to name them,
while `normalize_fuel(...)` and `finish_model(...)` are not anything. Deriving
the vocabulary from the tree means a renamed function fails here without
anyone maintaining a list, which is the failure mode being fixed rather than
repeated one layer out.

**Scope is the docs CLAUDE.md's documentation map calls current.** `docs/*.md`,
plus `docs/PACK_CONTRACT.md` and the rest at that level. Excluded:

- `docs/historical/` — explicitly "do not follow". Being stale is its content.
- `docs/superpowers/specs/` — dated design records. A spec describes the tree
  as of the day it was written; forcing it current would either rewrite
  history or delete the record.
- blockquoted lines — this repo marks a superseded passage by quoting it and
  saying so (Step 4e's own note names all nineteen retired tools on purpose).
  A quote is a citation, not an instruction.
"""

import inspect
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

EXCLUDED = ("historical", "specs")

# `name(` — a call, not a mention. `templates.yaml` and `research/` stay prose.
_CALL = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\s*\(")


def _tracked(*globs: str) -> str:
    files = subprocess.run(["git", "ls-files", *globs], cwd=REPO,
                           capture_output=True, text=True, check=True).stdout.split()
    out = []
    for name in files:
        if "web/static" in name:  # committed build output, not source
            continue
        try:
            out.append((REPO / name).read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n".join(out)


def _known_symbols() -> set[str]:
    """Everything the tree defines, plus what the MCP server registers."""
    from app import mcp_server

    names = set(mcp_server.registered_tools())
    names |= set(re.findall(r"^\s*(?:async )?def (\w+)",
                            _tracked("*.py"), re.M))
    names |= set(re.findall(r"(?:function|const|let)\s+(\w+)",
                            _tracked("*.ts", "*.js", "*.svelte")))
    return names


def _current_docs() -> list[Path]:
    return sorted(p for p in (REPO / "docs").rglob("*.md")
                  if not any(part in EXCLUDED for part in p.parts))


def _calls(path: Path) -> dict[str, int]:
    found: dict[str, int] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith(">"):
            continue
        for name in _CALL.findall(line):
            found.setdefault(name, number)
    return found


def test_no_current_doc_names_a_call_that_does_not_exist():
    known = _known_symbols()
    assert len(known) > 1000, "symbol extraction broke; the gate would pass vacuously"

    offenders = []
    docs = _current_docs()
    for path in docs:
        for name, line in sorted(_calls(path).items()):
            if name not in known:
                offenders.append(
                    f"{path.relative_to(REPO)}:{line} names `{name}()`, "
                    "which is not a tool and not defined anywhere")

    assert not offenders, (
        "\n".join(offenders)
        + "\n\nEither the doc is stale, or the passage is history — a "
          "superseded passage belongs in a blockquote saying so."
    )
    assert len(docs) >= 5, f"only checked {len(docs)} docs; the glob is wrong"


def test_the_mcp_surface_is_documented_by_reference_not_by_copy():
    """USAGE.md Step 4e held a nineteen-tool inventory. One copy, or none."""
    usage = (REPO / "docs" / "USAGE.md").read_text(encoding="utf-8")
    from app import mcp_server

    tools = set(mcp_server.registered_tools())
    named = {tool for tool in tools if f"`{tool}" in usage}
    assert len(named) < len(tools) / 2, (
        f"USAGE.md names {len(named)} of {len(tools)} MCP tools — that is an "
        "inventory again, and an inventory is the thing that goes stale. "
        "Point at app/mcp_server.py or at the generated skill instead."
    )


def test_a_retired_tool_name_would_be_caught():
    """The gate's own regression: prove it reads what it claims to read."""
    known = _known_symbols()
    for retired in ("add_document", "add_evidence", "finish_model"):
        assert retired not in known, (
            f"{retired} is defined again — this gate's fixtures assume it is "
            "gone, so either the tool is back or the extraction is wrong"
        )
    assert _CALL.findall("call `add_evidence(x)` now") == ["add_evidence"]
    assert _CALL.findall("see `research/templates.yaml`") == []
