import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "desktop.yml"
SCRIPT = ROOT / "kriko-gpui" / "package.ps1"


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
    build = text.index("cargo build --release")
    assert lock < build


def test_both_paths_build_the_app_from_the_locked_graph():
    """`cargo build --release` must be `--locked` too, or the metadata check
    above verifies one graph and the build resolves another."""
    for path in (WORKFLOW, SCRIPT):
        text = path.read_text(encoding="utf-8")
        builds = [
            ln for ln in text.splitlines()
            if re.search(r"(^|run: )\s*cargo build --release", ln.strip())
        ]
        assert builds, f"{path.name} never builds the app"
        assert all("--locked" in ln for ln in builds), (
            f"{path.name} builds without --locked: {builds}"
        )
