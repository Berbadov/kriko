"""Refuse to freeze a trial bundle this build's pepper cannot open.

`src/app/trial_access.json` is sealed with the pepper of the build that made it
(`tools/make_trial_access.py`). A bundle left behind when the pepper was rotated
— or made by another checkout — is still a file the sidecar spec's `datas` would
carry, and frozen it would be a trial nobody can spend: the app would advertise
questions the reader cannot ask. This is the check the freeze runs, in a module
a test can call, because a PyInstaller spec file cannot be imported.

No bundle at all is a valid build — the screen says "No free trial is included
in this build" — so that case is silent here and reported in the build log.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "src" / "app" / "trial_access.json"


def bundles() -> Path:
    """Where the trial bundle travels, for the spec and for whoever bakes one."""
    return BUNDLE


def reason(bundle_file: Path | None = None) -> str:
    """`""` when there is nothing to stop for, else the sentence to stop with."""
    path = bundle_file or BUNDLE
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return f"{path} is not readable JSON: {error}"
    bundle = str((data or {}).get("bundle") or "") if isinstance(data, dict) else ""
    sys.path.insert(0, str(ROOT / "src"))
    from app import sharekeys

    if not bundle or not sharekeys.trial_keys(bundle):
        return (
            f"{path} does not open with the pepper this build carries: it was "
            "sealed by a build with another one, so the frozen app would carry "
            "a trial it cannot spend. Bake it again for this pepper with "
            "tools/make_trial_access.py, or remove it to ship no trial."
        )
    return ""
