"""What the frozen build needs told, checked without a frozen build.

The spec file is the least testable code in the repo: it only ever runs inside
PyInstaller, on a machine that has it, with a ten-minute build behind it. So the
one decision in it that has already been wrong lives in a plain module, and is
asserted here — collecting all of `mcp` imports `mcp.cli`, which raises "typer
is required" and failed the freeze on all three runners at once.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packaging"))

import freeze_imports  # noqa: E402


def test_the_cli_extra_is_never_collected():
    """`mcp.cli` needs typer, which the sidecar has no use for."""
    assert not freeze_imports.wanted("mcp.cli")
    assert not freeze_imports.wanted("mcp.cli.claude")
    # …and the server half, which is the whole point, still is.
    assert freeze_imports.wanted("mcp.server.fastmcp")
    assert freeze_imports.wanted("mcp.types")


def test_the_collection_finds_the_server_and_survives_a_missing_extra():
    """Run the real collection, since the failure was in the walk itself."""
    pytest.importorskip("PyInstaller")
    modules = freeze_imports.mcp_submodules()
    assert "mcp.server.fastmcp" in modules, modules[:10]
    assert not [name for name in modules if name.startswith("mcp.cli")]


def test_the_spec_uses_the_helper_rather_than_its_own_collection():
    """A second copy of this decision in the spec would drift silently."""
    spec = (
        Path(__file__).resolve().parents[3] / "packaging" / "kriko-sidecar.spec"
    ).read_text()
    assert "mcp_submodules()" in spec
    assert "collect_submodules(" not in spec, (
        "the spec collects submodules itself again — put the decision in "
        "packaging/freeze_imports.py where a test can reach it"
    )
