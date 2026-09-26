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

#: What the build venv has installed and the binary must not carry. PyInstaller
#: follows an optional import exactly as it follows a real one, so a venv with
#: the `pipeline` and `dev` extras froze trafilatura (and dateparser, babel),
#: pytest, and numpy and PIL behind them — 0.10.3's sidecar came out at 66 MB
#: against 0.10.2's 35. Every one of these is either imported inside a
#: `try`/fallback (`app.providers.fetch`, pygments' image formatter, anyio's
#: pytest plugin) or only by test modules.
FROZEN_EXCLUDES = (
    "tkinter",
    "matplotlib",
    # The research API plane and the whole pipeline are optional extras; a
    # reader installing packs must not carry mistralai or yt-dlp.
    "mistralai",
    "yt_dlp",
    "textual",
    "langextract",
    "trafilatura",
    "pytest",
    "_pytest",
    "numpy",
    "PIL",
)

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

    return collect_submodules("kriko", filter=lambda name: ".tests" not in name)
