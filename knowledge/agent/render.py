"""Render the agent contract into every harness's file format.

The contract lived in two hand-maintained copies — `.claude/agents/` and
`.opencode/agents/` — which is the same failure mode as a rule living in a
test and a gate: they drift, and the harness a run happens to use decides
which rules the agent was told about. One body, generated frontmatter, and a
test that fails if a checked-in file is stale (`test_agent_contract.py`).

Adding a harness is a dict entry here, not a new copy of the prose.

    python -m knowledge.agent.render          # write the harness files
    python -m knowledge.agent.render --check  # CI: are they current?
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONTRACT = Path(__file__).resolve().parent / "kriko_research.md"

AGENT_NAME = "kriko_research"
DESCRIPTION = (
    "Kriko knowledge researcher — fills coverage gaps in the installed packs "
    "through the kriko MCP server at $0. Use when the user names a product to "
    "research, or asks what the installed packs are missing. Works for whatever "
    "categories are installed, not cars specifically.")

# The tools the agent is allowed to reach. MCP write tools are all $0; the two
# web tools are the research surface. Anything else (bash, file edits) is
# deliberately absent — the ledger is the only thing this agent changes.
# The tools the contract grants. Five car-shaped ones (onboard_model,
# submit_trims, list_generations, submit_generations, finish_model) collapsed
# into generic equivalents when the MCP server moved onto the pack store — a
# category is data now, so a tool per category was a tool per data edit.
MCP_TOOLS = (
    "list_packs", "store_status", "list_subjects", "get_subject",
    "lookup", "research_brief", "coverage_gaps",
    "submit_findings", "install_pack", "set_pack_enabled",
)


def _claude_frontmatter() -> str:
    tools = ", ".join(["WebFetch", "WebSearch"]
                      + [f"mcp__kriko__{t}" for t in MCP_TOOLS])
    return (f"---\n"
            f"name: {AGENT_NAME}\n"
            f"description: {DESCRIPTION}\n"
            f"tools: {tools}\n"
            f"---\n\n")


def _opencode_frontmatter() -> str:
    return ("---\n"
            f"description: {DESCRIPTION}\n"
            "mode: all\n"
            "permission:\n"
            "  bash: deny\n"
            "  edit: deny\n"
            "  webfetch: allow\n"
            "  websearch: allow\n"
            "---\n\n")


TARGETS: dict[str, tuple[Path, Callable[[], str]]] = {
    "claude": (REPO_ROOT / ".claude" / "agents" / f"{AGENT_NAME}.md",
               _claude_frontmatter),
    "opencode": (REPO_ROOT / ".opencode" / "agents" / f"{AGENT_NAME}.md",
                 _opencode_frontmatter),
}

_GENERATED = ("<!-- generated from knowledge/agent/kriko_research.md by "
              "knowledge.agent.render — edit that file, not this one -->\n\n")


def rendered(harness: str) -> str:
    _, frontmatter = TARGETS[harness]
    return frontmatter() + _GENERATED + CONTRACT.read_text(encoding="utf-8")


def write_all() -> list[Path]:
    written = []
    for harness, (path, _) in TARGETS.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        text = rendered(harness)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            written.append(path)
    return written


def stale() -> list[Path]:
    """Harness files that no longer match the contract."""
    out = []
    for harness, (path, _) in TARGETS.items():
        if not path.exists() or path.read_text(encoding="utf-8") != rendered(harness):
            out.append(path)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.check:
        bad = stale()
        for path in bad:
            print(f"stale: {path.relative_to(REPO_ROOT)}")
        print("all harness agent files current" if not bad else
              "run: python -m knowledge.agent.render")
        return 1 if bad else 0

    for path in write_all():
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
