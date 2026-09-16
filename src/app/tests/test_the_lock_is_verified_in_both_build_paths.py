from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "desktop.yml"
SCRIPT = ROOT / "packaging" / "build_desktop.ps1"


def test_the_workflow_verifies_the_lock_before_installing_python():
    text = WORKFLOW.read_text(encoding="utf-8")
    lock = text.index("cargo metadata --locked")
    install = text.index("Install Python side")
    assert lock < install


def test_the_hand_script_verifies_the_lock_too():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "cargo metadata" in text and "--locked" in text, (
        f"{WORKFLOW.name}'s bundle job runs `cargo metadata --locked` before "
        f"anything else, and {SCRIPT.name} does not run it at all — a hand "
        "build can bundle a crate graph nobody reviewed while the tagged "
        "build refuses to."
    )


def test_the_hand_script_verifies_the_lock_before_bundling():
    text = SCRIPT.read_text(encoding="utf-8")
    lock = text.index("cargo metadata")
    bundle = text.index("tauri run tauri build")
    assert lock < bundle
