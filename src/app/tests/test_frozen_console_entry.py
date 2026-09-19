import ast
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "packaging" / "kriko-sidecar.spec"

sys.path.insert(0, str(ROOT / "packaging"))

import freeze_imports


def test_the_spec_collects_the_kriko_package_through_the_helper():
    text = SPEC.read_text(encoding="utf-8")
    assert "kriko_submodules()" in text


def test_the_spec_collects_the_console_entry_points():
    text = SPEC.read_text(encoding="utf-8")
    assert "CONSOLE_MODULES" in text
    assert "list(CONSOLE_MODULES)" in text


def test_the_console_modules_are_importable():
    for module in freeze_imports.CONSOLE_MODULES:
        assert importlib.import_module(module) is not None


def test_the_cli_entry_needs_the_kriko_package_at_module_scope():
    tree = ast.parse((ROOT / "src" / "app" / "cli.py").read_text(encoding="utf-8"))
    tops = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            tops.add(node.module.split(".")[0])
        if isinstance(node, ast.Import):
            for alias in node.names:
                tops.add(alias.name.split(".")[0])
    assert "kriko" in tops
    assert "app" in tops


def test_the_kriko_collection_covers_the_engine_packages():
    pytest.importorskip("PyInstaller")
    modules = freeze_imports.kriko_submodules()
    assert "kriko.lookup" in modules
    assert "kriko.store.db" in modules


def test_the_spec_holds_no_second_copy_of_the_collection():
    text = SPEC.read_text(encoding="utf-8")
    assert "collect_submodules(" not in text
