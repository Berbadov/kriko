"""The agent contract has one source, and the harness files follow it.

Two hand-maintained copies of the prompt (.claude/ and .opencode/) meant the
harness a run happened to use decided which rules the agent was told about —
the same drift that let a rule live in a test but not in the write gate. The
body lives in knowledge/agent/kriko_research.md; these tests fail when a
checked-in harness file is stale, and when the contract stops describing the
tools the server actually exposes.
"""

import re

from knowledge.agent import render
from ops.mcp import server


def test_checked_in_harness_files_match_the_contract():
    stale = render.stale()
    assert stale == [], (
        "stale agent files: " + ", ".join(str(p) for p in stale) +
        " — run: python -m knowledge.agent.render")


def test_every_tool_the_contract_grants_exists_on_the_server():
    for tool in render.MCP_TOOLS:
        assert callable(getattr(server, tool, None)), f"no MCP tool {tool!r}"


def test_the_contract_names_the_tools_the_agent_must_call():
    body = render.CONTRACT.read_text()
    for tool in ("onboard_model", "submit_trims", "research_brief",
                 "add_document", "add_evidence", "finish_model",
                 "submit_generations"):
        assert tool in body, f"contract never mentions {tool}"


def test_harness_files_carry_a_do_not_edit_marker():
    for harness in render.TARGETS:
        assert "generated from knowledge/agent" in render.rendered(harness)


def test_claude_frontmatter_lists_prefixed_mcp_tools():
    text = render.rendered("claude")
    front = text.split("---")[1]
    assert re.search(r"tools:.*mcp__kriko__add_evidence", front)
    assert "WebSearch" in front


def test_opencode_frontmatter_denies_bash_and_edit():
    front = render.rendered("opencode").split("---")[1]
    assert "bash: deny" in front and "edit: deny" in front
