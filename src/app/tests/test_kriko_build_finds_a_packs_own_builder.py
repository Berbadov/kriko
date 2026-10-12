"""`kriko build packs/<name>` is the command the docs give for a pack that
ships its own builder. It used to need PYTHONPATH set to the checkout, and
failed with "No module named 'packs'" without it."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_a_pack_with_its_own_builder_builds_from_anywhere(tmp_path):
    own = next(p for p in sorted((REPO / "packs").iterdir()) if (p / "build.py").is_file())
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["HOME"] = str(tmp_path)
    out = tmp_path / "built.kpack"
    done = subprocess.run(
        [sys.executable, "-m", "app.cli", "build", str(own), "--out", str(out)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    assert out.is_file()
