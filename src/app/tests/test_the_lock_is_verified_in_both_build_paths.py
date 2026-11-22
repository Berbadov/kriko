import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "desktop.yml"
SCRIPT = ROOT / "kriko-ui" / "package.ps1"
PACKAGE = ROOT / "kriko-ui" / "package.json"


def _bundle_commands(text: str) -> list[str]:
    """The `tauri build` commands a recipe runs, through `bun run <script>` too.

    The command moved into `kriko-ui/package.json`'s `bundle` script when Bun
    began eating the `--` in `bun run tauri build ... -- --locked`; resolving
    the script keeps this check on the command that actually runs.
    """
    scripts = json.loads(PACKAGE.read_text(encoding="utf-8"))["scripts"]
    found = []
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        if "tauri build --config" in line:
            found.append(line.strip())
            continue
        match = re.search(r"\bbun run ([\w:.-]+)", line)
        if match and "tauri build --config" in scripts.get(match.group(1), ""):
            found.append(scripts[match.group(1)])
    return found


def test_the_workflow_verifies_the_lock_before_installing_python():
    text = WORKFLOW.read_text(encoding="utf-8")
    lock = text.index("cargo metadata --locked")
    install = text.index("Install Python side")
    assert lock < install


def test_the_hand_script_verifies_the_lock_too():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "cargo metadata" in text and "--locked" in text, (
        f"{WORKFLOW.name}'s bundle job runs `cargo metadata --locked` before "
        f"anything else, and {SCRIPT.name} does not run it at all: a hand "
        "build can bundle a crate graph nobody reviewed while the tagged "
        "build refuses to."
    )


def test_the_hand_script_verifies_the_lock_before_building():
    text = SCRIPT.read_text(encoding="utf-8")
    lock = text.index("cargo metadata")
    build = text.index("bun run bundle")
    assert lock < build


def test_both_paths_build_the_app_from_the_locked_graph():
    """`tauri build` must pass `--locked` on to cargo, or the metadata check
    above verifies one graph and the build resolves another."""
    for path in (WORKFLOW, SCRIPT):
        builds = _bundle_commands(path.read_text(encoding="utf-8"))
        assert builds, f"{path.name} never builds the app"
        assert all("--locked" in ln for ln in builds), (
            f"{path.name} builds without --locked: {builds}"
        )
