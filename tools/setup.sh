#!/usr/bin/env bash
# One command to a working tree. Run it first, run it again whenever something
# feels wrong; it is idempotent.
#
#     tools/setup.sh
#
# **Why this exists.** Getting a checkout to the point where `pytest` tells the
# truth took, on 2026-09-13, six separate discoveries: that the declared Python
# floor was one the machine could not satisfy (B110); that `requirements.lock`
# is the closure
# the installer freezes and installing anything else makes the suite's central
# claim false; that `-e .` is needed for `app.version` to report the tree's
# version rather than a stale one; that the `pipeline` extra is not optional for
# the *suite* even though it is optional for serving — without it six modules
# fail to import and four tests error; that `ui/` and the repo root have
# separate `node_modules`; and that `src/*.egg-info` goes stale and makes a
# version test fail for a reason that has nothing to do with the tree.
#
# Every one of those is a thing a person had to find out by failing. None of
# them is interesting. So they live here instead, and `docs/DOCTRINE.md` says to
# run this rather than listing them again.
#
# It never touches `~/.kriko`: your store, your history and your keys are not
# development environment, and a setup script that resets them is a setup script
# people are afraid to run.
set -euo pipefail

cd "$(dirname "$0")/.."
VENV="${VENV:-.venv}"

say() { printf '\n\033[1m── %s\033[0m\n' "$1"; }
bad() { printf '\033[31m%s\033[0m\n' "$1" >&2; }

# ── the interpreter ─────────────────────────────────────────────────────
#
# `requires-python` is the authority; asking it beats hardcoding a number here
# that drifts the day the tree moves on.
WANT=$(sed -n 's/^requires-python *= *"\(.*\)"/\1/p' pyproject.toml | tr -d '>=" ')

if [ ! -x "$VENV/bin/python" ] && [ ! -x "$VENV/Scripts/python.exe" ]; then
    say "creating $VENV (Python $WANT+)"
    if command -v uv >/dev/null 2>&1; then
        uv venv --python "$WANT" "$VENV"
    else
        # No uv: whatever `python3` is, and a clear failure if it is too old
        # rather than a confusing one 400 lines into an install.
        python3 -c "
import sys
want = tuple(int(p) for p in '$WANT'.split('.'))
if sys.version_info[:len(want)] < want:
    sys.exit(f'python3 is {sys.version.split()[0]}, and this tree needs $WANT+. '
             'Install it, or install uv (https://docs.astral.sh/uv/) and re-run.')
"
        python3 -m venv "$VENV"
    fi
fi

PY="$VENV/bin/python"
[ -x "$PY" ] || PY="$VENV/Scripts/python.exe"

# An existing venv on the wrong interpreter, said here rather than 200 lines
# into a resolver error. `uv pip install -e .` fails with "only kriko==X is
# available and the current Python version does not satisfy Python>=3.14",
# which is true, unhelpful, and three steps removed from "your .venv is old".
if ! "$PY" -c "
import sys
want = tuple(int(p) for p in '$WANT'.split('.'))
sys.exit(0 if sys.version_info[:len(want)] >= want else 1)
"; then
    bad "$VENV runs $("$PY" -V | cut -d' ' -f2), and pyproject.toml requires $WANT+."
    bad ""
    bad "Delete it and re-run, once you have an interpreter that new:"
    bad "    uv python install $WANT && rm -rf $VENV && tools/setup.sh"
    bad ""
    bad "Note that a *pre-release* is not enough either: the pydantic pinned"
    bad "in requirements.lock raises on import under 3.14.0rc2, which is why"
    bad "the floor is 3.13 rather than 3.14 (B110, resolved 2026-09-14)."
    exit 1
fi

# ── Python ──────────────────────────────────────────────────────────────
#
# The lock first and on its own line. `requirements.lock` is the closure the
# installer freezes, and the suite's central claim is that it passed against
# *that* closure — an install that resolves freely makes the claim false, which
# is the exact drift `test_dependencies_are_locked.py` fails on.
#
# Then the extras, unpinned on purpose: they never reach a reader's machine.
# `pipeline` is not optional here even though it is optional for serving —
# without it, six test modules cannot be imported.
say "python dependencies"
if command -v uv >/dev/null 2>&1; then
    VIRTUAL_ENV="$VENV" uv pip install --quiet -r requirements.lock
    VIRTUAL_ENV="$VENV" uv pip install --quiet -e ".[dev,pipeline]"
else
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet -r requirements.lock
    "$PY" -m pip install --quiet -e ".[dev,pipeline]"
fi

# `-e .` writes `src/*.egg-info`, and its version is what `/api/health` and
# `app.version` report. A tree bumped since the last install reports the old
# number and `test_the_version_the_app_reports_is_the_version_the_tree_says`
# fails for a reason that is about this directory, not about the tree.
say "checking the installed version matches the tree"
"$PY" - <<'CHECK'
import tomllib
from pathlib import Path

from app.version import app_version

declared = tomllib.loads(Path("pyproject.toml").read_text("utf-8"))["project"]["version"]
installed = app_version()
if installed != declared:
    raise SystemExit(
        f"the installed distribution says {installed}, pyproject says {declared} — "
        "re-run this script, or delete src/*.egg-info"
    )
print(f"ok: {installed}")
CHECK

# The check that matters, and the one the first version of this script did not
# have: does the tree actually *import*?
#
# It reported "ready" on a venv where `import fastapi` raised, because every
# check above passed — the interpreter was new enough, the lock installed
# cleanly, the version matched. `uv venv --python 3.14` had resolved 3.14.0rc2,
# a pre-release that satisfies `requires-python = ">=3.14"`, and the pinned
# pydantic cannot run on it. A setup script whose failure mode is a confident
# "ready" is worse than no setup script: it moves the discovery to whatever you
# ran next, with none of this context attached.
say "checking the tree imports"
if ! "$PY" -c "import fastapi, uvicorn, app.web.app, kriko.lookup, app.tui" 2>/tmp/kriko-import.$$; then
    bad "the environment installed cleanly and cannot import the app:"
    sed 's/^/    /' /tmp/kriko-import.$$ >&2
    rm -f /tmp/kriko-import.$$
    bad ""
    bad "If that traceback ends inside pydantic, this is the known pre-release"
    bad "problem: $("$PY" -V) is probably an rc, and requirements.lock pins a"
    bad "pydantic that cannot run on it. Install a stable interpreter and re-run:"
    bad "    uv python install $WANT && rm -rf $VENV && tools/setup.sh"
    exit 1
fi
rm -f /tmp/kriko-import.$$

# ── Node ────────────────────────────────────────────────────────────────
#
# Two trees, and they are not the same install. The root holds the extension's
# tests; `ui/` holds the Svelte app, and its lockfile is committed because the
# stale-bundle check needs the same dependency versions to produce the same
# asset hashes.
if command -v npm >/dev/null 2>&1; then
    say "node dependencies (root: extension tests)"
    npm install --silent --no-audit --no-fund
    say "node dependencies (ui: the dashboard)"
    npm --prefix ui ci --silent --no-audit --no-fund
else
    bad "npm not found — the Python half is ready, the two JS suites are not."
fi

# The coding-agent files are local, ignored output, not source. A fresh
# checkout still needs them before the contract test and local CLI runs can
# agree with the canonical prompt under packs/cars/pipeline/agent/.
say "rendering local research-agent prompts"
"$PY" -m packs.cars.pipeline.agent.render

say "ready"
cat <<'DONE'
  tools/gate.sh            everything the branch used to be checked for
  .venv/bin/kriko tui      the operator console
  .venv/bin/python -m app.web    the dashboard on 127.0.0.1:8787

Nothing here touched ~/.kriko — your store, history and keys are untouched.
DONE
