"""The agent contract has one source, and the harness files follow it.

Two hand-maintained copies of the prompt (.claude/ and .opencode/) meant the
harness a run happened to use decided which rules the agent was told about —
the same drift that let a rule live in a test but not in the write gate. The
body lives in packs/cars/pipeline/agent/kriko_research.md. Harness files are
generated locally and are not shipped in a checkout; these tests exercise the
renderer in isolation and check the contract against the actual server tools.
"""

import re

from app import mcp_server as server
from packs.cars.pipeline.agent import render


def test_generated_harness_files_match_the_contract(tmp_path, monkeypatch):
    targets = {
        name: (tmp_path / name / path.name, frontmatter)
        for name, (path, frontmatter) in render.TARGETS.items()
    }
    monkeypatch.setattr(render, "TARGETS", targets)
    paths = [path for path, _ in targets.values()]
    assert render.stale() == paths
    assert render.write_all() == paths
    assert render.stale() == []
    assert render.write_all() == []
    for name, (path, _) in targets.items():
        assert path.read_text(encoding="utf-8") == render.rendered(name)
    paths[0].write_text("outdated contract", encoding="utf-8")
    assert render.stale() == [paths[0]]
    assert render.write_all() == [paths[0]]
    assert render.stale() == []


def test_every_tool_the_contract_grants_exists_on_the_server():
    for tool in render.MCP_TOOLS:
        assert callable(getattr(server, tool, None)), f"no MCP tool {tool!r}"


def test_the_contract_names_the_tools_the_agent_must_call():
    body = render.CONTRACT.read_text(encoding="utf-8")
    # The car-shaped tools are gone; a category is data now, so a tool per
    # category was a tool per data edit.
    for tool in ("research_brief", "submit_findings", "coverage_gaps", "list_packs"):
        assert tool in body, f"contract never mentions {tool}"


def test_harness_files_carry_a_do_not_edit_marker():
    for harness in render.TARGETS:
        assert "generated from packs/cars/pipeline/agent" in render.rendered(harness)


def test_claude_frontmatter_lists_prefixed_mcp_tools():
    text = render.rendered("claude")
    front = text.split("---")[1]
    assert re.search(r"tools:.*mcp__kriko__submit_findings", front)
    assert "WebSearch" in front


def test_opencode_frontmatter_denies_bash_and_edit():
    front = render.rendered("opencode").split("---")[1]
    assert "bash: deny" in front and "edit: deny" in front
