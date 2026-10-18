"""The hardened macOS app needs one identity on every embedded executable.

The frozen engine is the part of a macOS bundle that is built here, so its
signing hook is held now. The macOS package recipe itself is not written for
the Tauri app yet; when it is, its test goes beside this one.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "packaging" / "kriko-sidecar.spec"


def test_pyinstaller_signs_the_onefile_archive_with_the_macos_identity():
    source = SPEC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    exe_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "EXE"
    ]
    assert len(exe_calls) == 1
    identity = next(
        keyword.value
        for keyword in exe_calls[0].keywords
        if keyword.arg == "codesign_identity"
    )
    assert isinstance(identity, ast.Name)
    assert identity.id == "CODESIGN_IDENTITY"
    assert 'os.environ.get("KRIKO_MACOS_SIGN_IDENTITY")' in source
    assert 'sys.platform == "darwin"' in source
    assert 'CODESIGN_IDENTITY = None\nif sys.platform == "darwin":' in source
