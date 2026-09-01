"""The app's own update path, checked where CI can check it.

No Rust toolchain is needed for this suite, and the two failure modes here are
silent ones: an app that stamps the wrong version offers itself its own update
forever, and a manifest that names a bundle with no signature makes every
client download something it will then refuse.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packaging"))

import configure_updater  # noqa: E402
import updater_manifest  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
CONFIG = json.loads(
    (REPO / "tauri" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
)


def test_the_committed_config_ships_no_updater():
    """The tree builds without a signing key, and says so by holding none.

    A committed endpoint plus a committed `createUpdaterArtifacts` would make
    every fork's build fail on a missing secret.
    """
    assert "updater" not in (CONFIG.get("plugins") or {})
    assert "createUpdaterArtifacts" not in (CONFIG.get("bundle") or {})


def test_the_four_version_strings_agree():
    """One release, one number — in four files nothing links together.

    The updater compares the running app's version against the manifest, so a
    shell that says 0.1.0 inside a 0.2.0 release offers itself its own update
    forever. Nothing in the toolchain notices: Cargo, npm, setuptools and Tauri
    each read their own file.
    """
    import tomllib

    versions = {
        "tauri.conf.json": CONFIG["version"],
        "pyproject.toml": tomllib.loads(
            (REPO / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"],
        "src-tauri/Cargo.toml": tomllib.loads(
            (REPO / "tauri" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
        )["package"]["version"],
        "tauri/package.json": json.loads(
            (REPO / "tauri" / "package.json").read_text(encoding="utf-8")
        )["version"],
    }
    assert len(set(versions.values())) == 1, (
        "these files disagree about which version this is: "
        + ", ".join(f"{name}={value}" for name, value in sorted(versions.items()))
    )
    assert configure_updater.SEMVER.match(CONFIG["version"]), CONFIG["version"]


def test_configuring_with_a_key_turns_the_updater_on():
    out = configure_updater.configure(CONFIG, "owner/name", "pub-key-here", "v9.9.9")
    updater = out["plugins"]["updater"]
    assert updater["pubkey"] == "pub-key-here"
    assert updater["endpoints"] == [
        "https://github.com/owner/name/releases/latest/download/latest.json"
    ]
    assert out["bundle"]["createUpdaterArtifacts"] is True
    # The leading v is a tag convention; a version is a version.
    assert out["version"] == "9.9.9"


@pytest.mark.parametrize("version", ["3/merge", "main", "v", "0.1", "latest"])
def test_a_version_that_is_not_semver_is_ignored_rather_than_stamped(version):
    """CI passes `github.ref_name`, which on a pull request is `<n>/merge`.

    Tauri refuses a non-semver version outright, so stamping one turns every
    non-tag build into three failed OS runners.
    """
    out = configure_updater.configure(CONFIG, "owner/name", "", version)
    assert out["version"] == CONFIG["version"]


def test_configuring_without_a_key_is_a_no_op_the_build_survives():
    out = configure_updater.configure(CONFIG, "owner/name", "  ")
    assert "updater" not in out["plugins"]
    assert "createUpdaterArtifacts" not in out["bundle"]
    assert out["version"] == CONFIG["version"]


def test_configuring_round_trips_the_committed_file():
    """Running it with no key must leave the tree exactly as it was."""
    assert configure_updater.configure(CONFIG, "owner/name", "") == CONFIG


def test_the_endpoint_and_the_pack_index_point_at_the_same_place():
    """Two clocks, one origin. If they diverge, one of them is a typo."""
    from app.web.settings import Settings

    host = re.match(r"(https://github.com/[^/]+/[^/]+)/", Settings().pack_index_url)
    assert host, Settings().pack_index_url
    assert configure_updater.ENDPOINT.format(repo="Berbadov/kriko").startswith(
        host.group(1)
    )


def test_the_manifest_covers_every_platform_it_was_given(tmp_path):
    artifacts = tmp_path / "artifacts"
    for name in ("Kriko.AppImage", "Kriko.app.tar.gz", "Kriko-setup.exe"):
        (artifacts / name).parent.mkdir(parents=True, exist_ok=True)
        (artifacts / name).write_bytes(b"bundle")
        (artifacts / f"{name}.sig").write_text("sig-for-" + name, encoding="utf-8")

    out = tmp_path / "release" / "latest.json"
    _run(artifacts, out, "0.4.0")
    manifest = json.loads(out.read_text())
    assert manifest["version"] == "0.4.0"
    assert sorted(manifest["platforms"]) == [
        "darwin-aarch64",
        "darwin-x86_64",
        "linux-x86_64",
        "windows-x86_64",
    ]
    assert manifest["platforms"]["linux-x86_64"]["signature"] == "sig-for-Kriko.AppImage"
    assert manifest["platforms"]["linux-x86_64"]["url"].endswith("/Kriko.AppImage")
    # The bundles the manifest names have to be beside it on the release page.
    assert (out.parent / "Kriko.app.tar.gz").exists()


def test_one_missing_platform_still_publishes_the_others(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "Kriko.AppImage").write_bytes(b"b")
    (artifacts / "Kriko.AppImage.sig").write_text("s", encoding="utf-8")
    out = tmp_path / "release" / "latest.json"
    _run(artifacts, out, "0.4.0")
    assert list(json.loads(out.read_text())["platforms"]) == ["linux-x86_64"]


def test_a_signature_with_no_bundle_is_fatal(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "Kriko.AppImage.sig").write_text("s", encoding="utf-8")
    with pytest.raises(SystemExit):
        _run(artifacts, tmp_path / "release" / "latest.json", "0.4.0", check=False)


def test_no_artifacts_at_all_is_fatal_rather_than_an_empty_manifest(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    with pytest.raises(SystemExit):
        _run(artifacts, tmp_path / "release" / "latest.json", "0.4.0", check=False)


def _run(artifacts, out, version, check=True):
    argv = [
        "updater_manifest",
        "--artifacts",
        str(artifacts),
        "--version",
        version,
        "--base-url",
        "https://example.invalid/dl",
        "--out",
        str(out),
    ]
    original = sys.argv
    sys.argv = argv
    try:
        updater_manifest.main()
    finally:
        sys.argv = original


def test_the_shell_asks_before_it_restarts_the_app():
    """An update that closes the window unasked is a bug, not a feature."""
    main_rs = (REPO / "tauri" / "src-tauri" / "src" / "main.rs").read_text()
    assert "blocking_show" in main_rs, "the shell installs without asking"
    assert "app.restart()" in main_rs
    # The old engine holds the store's WAL lock; restarting around it is the
    # bug that makes the *next* launch fail.
    order = main_rs.index("kill_engine(&app);\n        app.restart();")
    assert order > 0

    # And it must already be dead when the installer starts writing, because on
    # Windows the installer overwrites the running sidecar's own file.
    body = main_rs.split("fn offer_update")[1]
    install = body.index("download_and_install")
    assert body[:install].rindex("kill_engine(&app);") < install, (
        "the update installs while the engine is still running — on Windows "
        "that is the locked kriko-sidecar.exe failure, unattended"
    )


def test_the_workflow_never_hard_requires_the_signing_secret():
    """A fork with no secret must still get installers out of a tag."""
    workflow = (REPO / ".github" / "workflows" / "desktop.yml").read_text()
    assert "TAURI_SIGNING_PRIVATE_KEY" in workflow
    assert "configure_updater.py" in workflow
    # The manifest step is conditional on a .sig actually existing.
    assert "no updater artifacts" in workflow


def test_the_scripts_run_as_scripts(tmp_path):
    """They are invoked by CI as `python packaging/x.py`, not imported."""
    config = tmp_path / "tauri.conf.json"
    config.write_text(json.dumps(CONFIG), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(REPO / "packaging" / "configure_updater.py"),
            "--repo",
            "owner/name",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert "updater disabled" in done.stdout
