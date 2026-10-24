"""A macOS package is assembled on macOS, by one recipe, and this holds it.

`kriko-ui/package-macos.sh` is what a reader with a Mac runs, and what the
`macos-arm64` job in `.github/workflows/desktop.yml` runs. Tauri and PyInstaller
do not cross-compile, so no test here can build the bundle; what a test can do
is hold the recipe to the facts that make the result a macOS package: the
architecture it refuses to fake, the one-file engine it places, the signature
over the whole bundle, and the disk image that is uploaded.

The behaviour on the machine is the job's own smoke steps, not this file's.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "kriko-ui" / "package-macos.sh"
MAC_CONF = ROOT / "kriko-ui" / "src-tauri" / "tauri.macos.bundle.conf.json"
WIN_CONF = ROOT / "kriko-ui" / "src-tauri" / "tauri.bundle.conf.json"
WORKFLOW = ROOT / ".github" / "workflows" / "desktop.yml"
FETCH_MACOS = ROOT / "packaging" / "fetch_openserp_macos.sh"
FETCH_WINDOWS = ROOT / "packaging" / "fetch_openserp.ps1"


@pytest.fixture(scope="module")
def recipe() -> str:
    return SCRIPT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _macos_job(workflow: str) -> str:
    """The `bundle-macos:` job's own text, so another job's steps cannot satisfy a check."""
    match = re.search(r"^    bundle-macos:\n(.*?)(?=^    [a-z][\w-]*:\s*$|\Z)", workflow, re.M | re.S)
    assert match, "desktop.yml has no `bundle-macos:` job"
    return match.group(1)


def test_the_recipe_is_a_posix_script_that_stops_at_the_first_failure(recipe):
    assert recipe.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in recipe
    assert not any(ord(character) > 127 for character in recipe), "package-macos.sh is ASCII only"


@pytest.mark.skipif(sys.platform == "win32", reason="bash here is WSL and needs a Linux path")
def test_the_recipe_parses_with_bash():
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on this machine")
    subprocess.run([bash, "-n", str(SCRIPT)], check=True)


def test_a_package_is_never_built_for_an_architecture_this_mac_is_not(recipe):
    assert 'if [ "$arch" != "$host_arch" ]' in recipe
    assert "cross-compile" in recipe
    assert 'triple="aarch64-apple-darwin"' in recipe
    assert 'triple="x86_64-apple-darwin"' in recipe


def test_the_engine_is_one_file_so_nothing_had_to_be_moved_beside_it(recipe):
    # The Windows bundle puts `_internal` in Contents/Resources and has to solve
    # placing it beside the executable. One file has no such folder, which is
    # why this recipe names none.
    assert "KRIKO_FREEZE=onefile" in recipe
    assert "binaries/_internal" not in recipe
    assert "kriko-sidecar-$triple" in recipe


def test_the_engine_and_the_search_binary_carry_the_pinned_architecture(recipe):
    assert 'packaging/fetch_openserp_macos.sh" "$serp_arch" "$staged/openserp-$triple"' in recipe
    assert 'openserp-$triple' in recipe


def test_the_freeze_and_its_handshake_come_before_the_bundle(recipe):
    freeze = recipe.index("packaging/kriko-sidecar.spec")
    handshake = recipe.index("smoke_sidecar.py")
    bundle = recipe.index("tauri build")
    assert freeze < handshake < bundle


def test_the_whole_bundle_is_signed_and_the_signature_checked(recipe):
    assert 'identity="${KRIKO_MACOS_SIGN_IDENTITY:--}"' in recipe
    assert 'codesign --force --sign "$identity"' in recipe
    assert 'codesign --force --deep --sign "$identity" "$app"' in recipe
    assert "codesign --verify --deep --strict" in recipe


def test_the_app_is_started_before_it_is_shipped(recipe):
    assert "smoke_app.py" in recipe
    assert recipe.index("smoke_app.py") < recipe.index("hdiutil create")


def test_the_disk_image_is_a_dmg_with_the_app_and_an_applications_link(recipe):
    assert "hdiutil create" in recipe
    assert "-format UDZO" in recipe
    assert 'ln -s /Applications' in recipe
    assert 'kriko-$tree-$arch.dmg' in recipe
    assert "shasum -a 256" in recipe


def test_the_version_asked_for_has_to_be_the_tree(recipe):
    assert "tools/bump.py --show" in recipe
    assert 'want="${version#v}"' in recipe
    assert '"$want" != "$tree"' in recipe


def test_the_macos_bundle_config_places_what_the_app_looks_for():
    config = json.loads(MAC_CONF.read_text(encoding="utf-8"))
    bundle = config["bundle"]
    # `app` only: the disk image is made from the signed bundle by the recipe,
    # after the signature is verified, so Tauri's own dmg step never runs.
    assert bundle["targets"] == ["app"]
    assert bundle["externalBin"] == ["binaries/kriko-sidecar", "binaries/openserp"]
    assert "third-party/OpenSERP-LICENSE.txt" in bundle["resources"]
    assert bundle["resources"]["third-party/OpenSERP-LICENSE.txt"] == "OpenSERP-LICENSE.txt"
    assert "_internal" not in json.dumps(config)
    assert [int(part) for part in bundle["macOS"]["minimumSystemVersion"].split(".")] >= [11, 0]


def test_the_windows_bundle_still_ships_the_folder_the_mac_one_cannot():
    windows = json.loads(WIN_CONF.read_text(encoding="utf-8"))["bundle"]
    assert windows["externalBin"] == ["binaries/kriko-sidecar", "binaries/OpenSERP"]
    assert windows["resources"]["binaries/_internal"] == "_internal"


def test_the_workflow_runs_the_recipe_and_uploads_what_it_writes(workflow):
    job = _macos_job(workflow)
    assert "runs-on: macos-14" in job
    assert 'kriko-ui/package-macos.sh --arch arm64 --version "$VERSION"' in job
    assert "KRIKO_MACOS_SIGN_IDENTITY" in job
    assert "name: kriko-macos" in job
    assert "kriko-ui/builds/*.dmg" in job
    assert "kriko-ui/builds/SHA256SUMS-macos.txt" in job


def test_the_macos_job_does_not_publish_a_release_nobody_observed(workflow):
    # Release assets stay Windows-only until a macOS observation exists in the
    # release evidence that `tools/release_readiness.py` reads.
    assert "needs: [bundle, packs]" in workflow
    assert "artifacts/kriko-macos" not in workflow


def test_both_packagers_pin_the_same_openserp_release():
    macos = FETCH_MACOS.read_text(encoding="utf-8")
    windows = FETCH_WINDOWS.read_text(encoding="utf-8")
    macos_version = re.search(r"^version=([0-9.]+)$", macos, re.M).group(1)
    windows_version = re.search(r"\$taskSerpVersion = '([0-9.]+)'", windows).group(1)
    assert macos_version == windows_version
