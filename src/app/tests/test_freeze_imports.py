"""What the frozen build needs told, checked without a frozen build.

The spec file is the least testable code in the repo: it only ever runs inside
PyInstaller, on a machine that has it, with a ten-minute build behind it. So the
one decision in it that has already been wrong lives in a plain module, and is
asserted here — collecting all of `mcp` imports `mcp.cli`, which raises "typer
is required" and failed the freeze on all three runners at once.
"""

import ast
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
    ).read_text(encoding="utf-8")
    assert "mcp_submodules()" in spec
    assert "collect_submodules(" not in spec, (
        "the spec collects submodules itself again — put the decision in "
        "packaging/freeze_imports.py where a test can reach it"
    )


def test_the_binary_carries_no_tests_and_no_pipeline_extra():
    """0.10.3 froze pytest, trafilatura and numpy and doubled to 66 MB.

    Nothing failed: each was an optional import PyInstaller followed because
    the build venv happened to have the `pipeline` and `dev` extras.
    """
    pytest.importorskip("PyInstaller")
    assert not [name for name in freeze_imports.kriko_submodules() if ".tests" in name]
    for name in ("pytest", "_pytest", "trafilatura", "numpy", "PIL", "mistralai",
                 "IPython", "jedi", "parso", "mypy"):
        assert name in freeze_imports.FROZEN_EXCLUDES, name
    spec = (
        Path(__file__).resolve().parents[3] / "packaging" / "kriko-sidecar.spec"
    ).read_text(encoding="utf-8")
    assert "excludes=list(FROZEN_EXCLUDES)" in spec


def test_excluded_developer_packages_are_not_imported_by_runtime_source():
    """An exclusion must not hide a package the shipped app actually uses."""
    root = Path(__file__).resolve().parents[3]
    blocked = {"IPython", "jedi", "parso", "mypy"}
    used = set()
    for package in (root / "src" / "app", root / "src" / "kriko"):
        for source in package.rglob("*.py"):
            if "tests" in source.parts:
                continue
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    used.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    used.add(node.module.split(".", 1)[0])
    assert not (used & blocked), sorted(used & blocked)


def test_the_evidence_gate_never_reaches_the_installer():
    """The NLI gate is the optional `nli` extra; the desktop build carries none.

    `app/nli_gate.py` imports `transformers` and `torch` inside
    `TransformersNliVerifier.__init__` only, so the frozen import walk cannot
    follow them — but an eager import anywhere would put two gigabytes into
    every reader's installer, and the exclusion below is what makes that a
    build failure rather than a surprise. The frozen sidecar's gate is off, and
    claims pass through marked `unchecked`: the designed fail-open.
    """
    root = Path(__file__).resolve().parents[3]
    for name in ("torch", "transformers"):
        assert name in freeze_imports.FROZEN_EXCLUDES, name

    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    extra = pyproject.split("nli = [", 1)[1].split("]", 1)[0]
    assert "torch" in extra and "transformers" in extra
    runtime = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    for name in ("torch", "transformers"):
        assert name not in runtime, f"{name} is a runtime dependency again"
    lock = root / "requirements.lock"
    if lock.is_file():
        text = lock.read_text(encoding="utf-8").lower()
        for name in ("torch", "transformers"):
            assert f"\n{name}" not in text, f"{name} reached requirements.lock"

    # The one module that may name them imports them inside its own class.
    for source in (root / "src" / "app").rglob("*.py"):
        if "tests" in source.parts:
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in tree.body:
            imported = (
                [alias.name.split(".", 1)[0] for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module.split(".", 1)[0]] if isinstance(node, ast.ImportFrom)
                and node.module else [])
            assert not ({"torch", "transformers"} & set(imported)), (
                f"{source} imports torch/transformers at module level — the "
                "frozen sidecar would carry them")
