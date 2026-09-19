"""Which modules the frozen sidecar has to be told about.

Separate from `kriko-sidecar.spec` so it can be *tested*. A spec file only
executes inside a PyInstaller run on a machine that has PyInstaller, which in
practice means the mistake here is only ever discovered by three CI runners
failing at once, ten minutes in.

That is not hypothetical: `collect_submodules("mcp")` walks the whole package,
and `mcp.cli` raises "typer is required" the moment it is imported — an optional
CLI extra the sidecar has no use for. The freeze failed on Linux, macOS and
Windows identically, and nothing in the ordinary test suite could have said so.
"""

#: Optional extras inside `mcp` that raise on import. They are not needed to
#: serve tools over stdio, and collecting them is what broke the freeze.
MCP_EXCLUDED_PREFIXES = ("mcp.cli",)

CONSOLE_MODULES = (
    "app.cli",
    "app.tui",
    "app.tui.app",
    "app.tui.client",
    "app.tui.screen",
    "app.tui.term",
)


def wanted(name: str) -> bool:
    """The filter `collect_submodules` applies before importing a candidate."""
    return not name.startswith(MCP_EXCLUDED_PREFIXES)


def mcp_submodules() -> list[str]:
    """Every `mcp` submodule the server may resolve by string at startup.

    FastMCP finds transports and validators dynamically, so PyInstaller's import
    graph cannot see them: the binary would answer HTTP perfectly and die on an
    agent's first `initialize`.
    """
    from PyInstaller.utils.hooks import collect_submodules

    return collect_submodules("mcp", filter=wanted)


def kriko_submodules() -> list[str]:
    from PyInstaller.utils.hooks import collect_submodules

    return collect_submodules("kriko")
