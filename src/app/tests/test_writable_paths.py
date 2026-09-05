"""Nothing this app writes may depend on the directory it was started in.

The three failures behind "I cannot connect an agent and do a package" were
one bug wearing three hats. `Settings.packs_dir` was `Path("packs")`,
`Settings.analysis_log_path` was `Path("logs/analyses.jsonl")` and `pack_build`
defaulted its output to `Path("dist")`. A relative path resolves against the
current working directory, and the desktop shell does not set one — on Windows
an installed app inherits `C:\\Program Files\\Kriko`, which is read-only.

From a checkout all three are correct, which is exactly why this shipped: the
working directory *is* the repo, so the test suite, the smoke test and every
manual run agreed. The mechanism below is the difference — it asks whether a
default is absolute, which is a question the repo cannot answer in the
affirmative by accident.
"""

from dataclasses import fields
from pathlib import Path

from app.web import settings as settings_module
from app.web.settings import Settings


def test_no_default_path_is_relative():
    """The ratchet. A fourth path added here fails until it names its root."""
    relative = [
        f.name
        for f in fields(Settings)
        if isinstance(f.default, Path) and not f.default.is_absolute()
    ]
    assert relative == [], (
        f"{relative} resolve against the working directory, which an installed "
        f"app does not own — anchor them to settings.KRIKO_HOME or the "
        f"source checkout, the way default_packs_dir() does"
    )


def test_the_environment_cannot_reintroduce_a_relative_default(monkeypatch):
    """`from_env` builds its own defaults, so it needs its own check."""
    for name in ("KRIKO_STORE", "KRIKO_PACKS", "KRIKO_ANALYSES_LOG",
                 "KRIKO_APP_STATE", "KRIKO_DIST"):
        monkeypatch.delenv(name, raising=False)
    built = Settings.from_env()
    for field in fields(Settings):
        value = getattr(built, field.name)
        if isinstance(value, Path):
            assert value.is_absolute(), f"{field.name} is {value}"


def test_a_frozen_build_writes_under_the_store_s_own_directory(monkeypatch):
    """With no checkout to prefer, everything lands beside knowledge.sqlite.

    `sys.frozen` is what PyInstaller sets and what tells `source_root()` that
    the parents of `__file__` are a temporary unpack directory rather than a
    repo. This is the case no developer ever runs and every reader does.
    """
    monkeypatch.setattr(settings_module.sys, "frozen", True, raising=False)
    home = settings_module.KRIKO_HOME
    assert settings_module.source_root() is None
    assert settings_module.default_packs_dir() == home / "packs"
    assert settings_module.default_analysis_log() == home / "logs/analyses.jsonl"
    assert settings_module.default_dist_dir() == home / "dist"


def test_a_checkout_keeps_using_the_checkout():
    """A developer's packs and logs do not move out from under them."""
    root = settings_module.source_root()
    assert root is not None and (root / "packs").is_dir()
    assert settings_module.default_packs_dir() == root / "packs"


def test_the_default_analysis_log_agrees_with_observability_s():
    """Two modules, one default — they were allowed to disagree before."""
    from app.web.observability import DEFAULT_LOG_PATH

    assert DEFAULT_LOG_PATH == Settings.analysis_log_path
