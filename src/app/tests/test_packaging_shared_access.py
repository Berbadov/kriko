"""The desktop build carries the same app-bound shared-access contract."""

from __future__ import annotations

import ast
import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "packaging" / "configure_share_pepper.py"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _helper():
    return _module("configure_share_pepper", HELPER)


def test_build_secret_is_baked_without_printing_it(monkeypatch, tmp_path, capsys):
    helper = _helper()
    target = tmp_path / "sharekeys_pepper.py"
    monkeypatch.setattr(helper, "TARGET", target)
    secret = "ab" * 32
    monkeypatch.setenv("KRIKO_SHARE_PEPPER", secret)

    assert helper.main() == 0
    assert f'PEPPER = {secret!r}' in target.read_text(encoding="utf-8")
    assert secret not in capsys.readouterr().out


def test_build_fails_explicitly_without_a_stable_pepper(monkeypatch, tmp_path, capsys):
    helper = _helper()
    monkeypatch.setattr(helper, "TARGET", tmp_path / "missing.py")
    monkeypatch.delenv("KRIKO_SHARE_PEPPER", raising=False)

    assert helper.main() == 2
    assert "cannot be packaged without a stable pepper" in capsys.readouterr().err


def test_existing_local_pepper_is_preserved_when_no_secret_is_injected(
    monkeypatch, tmp_path
):
    helper = _helper()
    target = tmp_path / "sharekeys_pepper.py"
    monkeypatch.setattr(helper, "TARGET", target)
    monkeypatch.delenv("KRIKO_SHARE_PEPPER", raising=False)
    pepper = "cd" * 32
    target.write_text(f"PEPPER = {pepper!r}\n", encoding="utf-8")

    assert helper.main() == 0
    assert target.read_text(encoding="utf-8") == f"PEPPER = {pepper!r}\n"


def test_injected_pepper_does_not_replace_a_different_local_pepper(
    monkeypatch, tmp_path, capsys
):
    helper = _helper()
    target = tmp_path / "sharekeys_pepper.py"
    monkeypatch.setattr(helper, "TARGET", target)
    local = "cd" * 32
    target.write_text(f"PEPPER = {local!r}\n", encoding="utf-8")
    monkeypatch.setenv("KRIKO_SHARE_PEPPER", "ab" * 32)

    assert helper.main() == 2
    assert target.read_text(encoding="utf-8") == f"PEPPER = {local!r}\n"
    assert "differs from the existing local pepper" in capsys.readouterr().err


def test_shared_access_runtime_dependency_is_locked():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    runtime = {str(dep).split(">", 1)[0].split("=", 1)[0]
               for dep in project["project"]["dependencies"]}
    pins = {
        line.split("==", 1)[0].lower(): line.split("==", 1)[1]
        for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines()
        if "==" in line and not line.lstrip().startswith("#")
    }
    assert "cryptography" in runtime
    assert pins["cryptography"] == "50.0.2"
    assert pins["cffi"] == "2.1.1"
    assert pins["pycparser"] == "3.11"
    uv_versions = {package["name"]: package["version"] for package in uv_lock["package"]}
    assert {name: pins[name] for name in ("cryptography", "cffi", "pycparser")} == {
        name: uv_versions[name] for name in ("cryptography", "cffi", "pycparser")
    }


def test_both_desktop_build_paths_configure_and_freeze_app_bound_shared_access():
    workflow = (ROOT / ".github" / "workflows" / "desktop.yml").read_text(encoding="utf-8")
    script = (ROOT / "kriko-ui" / "package.ps1").read_text(encoding="utf-8")
    spec = (ROOT / "packaging" / "kriko-sidecar.spec").read_text(encoding="utf-8")

    assert "KRIKO_SHARE_PEPPER: ${{ secrets.KRIKO_SHARE_PEPPER }}" in workflow
    assert "packaging/configure_share_pepper.py" in workflow
    assert "packaging/configure_share_pepper.py" in script
    assert '"app.sharekeys_pepper"' in spec
    assert '"cryptography.hazmat.primitives.ciphers.aead"' in spec


def test_the_freeze_refuses_a_trial_bundle_its_pepper_cannot_open(monkeypatch, tmp_path):
    """A stale bundle would be frozen into a trial nobody can spend.

    The app-side half of the same rule — never count questions from a bundle
    this build cannot open — is
    `test_a_trial_bundle_this_build_cannot_open_is_no_trial`.
    """
    verify = _module("verify_trial_bundle", ROOT / "packaging" / "verify_trial_bundle.py")
    from app import sharekeys

    bundle_file = tmp_path / "trial_access.json"
    monkeypatch.setenv("KRIKO_SHARE_PEPPER", "the-pepper-this-build-carries")
    sharekeys.write_trial(
        sharekeys.make_trial({"mercury": "sk-mercury", "deepseek": "sk-deepseek"}),
        where=bundle_file,
    )
    assert verify.reason(bundle_file) == ""

    monkeypatch.setenv("KRIKO_SHARE_PEPPER", "the-pepper-another-build-carried")
    assert "another one" in verify.reason(bundle_file)

    # No bundle at all is a build without a trial, not a failed build.
    assert verify.reason(tmp_path / "absent.json") == ""


def test_the_frozen_sidecar_stops_on_a_trial_bundle_it_cannot_open():
    spec = (ROOT / "packaging" / "kriko-sidecar.spec").read_text(encoding="utf-8")
    assert "from verify_trial_bundle import reason as trial_bundle_problem" in spec
    assert "raise SystemExit(PROBLEM)" in spec


def test_pyinstaller_spec_compiles_with_one_complete_hidden_import_list():
    spec_path = ROOT / "packaging" / "kriko-sidecar.spec"
    source = spec_path.read_text(encoding="utf-8")
    tree = compile(source, str(spec_path), "exec", ast.PyCF_ONLY_AST)
    analysis = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Analysis"
    )
    hidden = [keyword for keyword in analysis.keywords if keyword.arg == "hiddenimports"]
    assert len(hidden) == 1
    literal_lists = [node for node in ast.walk(hidden[0].value) if isinstance(node, ast.List)]
    imported = {
        elt.value
        for literal in literal_lists
        for elt in literal.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    }
    assert {
        "app.sharekeys",
        "app.sharekeys_pepper",
        "cryptography.hazmat.primitives.ciphers.aead",
    } <= imported

