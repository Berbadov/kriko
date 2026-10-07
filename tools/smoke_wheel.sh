#!/usr/bin/env bash
# Does the thing we ship actually import?
#
#     tools/smoke_wheel.sh
#
# **Why this exists.** A reader installed Kriko and got:
#
#     File "…\Scripts\kriko.exe\__main__.py", line 4, in <module>
#     ModuleNotFoundError: No module named 'kriko'
#
# The console script was installed and the package it imports was not. Nothing
# in the tree could have caught that, because everything in the tree runs
# against a *checkout*: `pip install -e .` puts `src/` on the path, so `kriko`
# imports whether or not the wheel would have contained it. The suite, the
# linters and the type checker all passed on an artifact none of them had built.
#
# So this builds the real wheel, looks inside it, installs it into an empty
# environment with nothing else on the path, and runs the command. Four checks,
# and each one is a way the reader's failure could have happened:
#
#   1. the wheel contains BOTH top-level packages — `kriko` is imported by
#      `app.cli` at module scope, so a wheel with only `app` gives exactly the
#      traceback above;
#   2. the data files are in it — `schema.sql` is read from disk at every
#      `connect()`, and an editable install finds it in the checkout while a
#      wheel without it raises on the first query;
#   3. a clean interpreter can import both, with the source tree nowhere near
#      the path;
#   4. the console script runs. `kriko --version` needs no store, no packs and
#      no network, so a failure here is the packaging and nothing else.
#
# It does not prove the reader's Windows install. It proves the artifact, which
# is the half this repository can hold itself to; the rest is in
# `docs/INSTALL_WINDOWS.md`.
set -euo pipefail

cd "$(dirname "$0")/.."
# The same probe `tools/gate.sh` opens with, and for the same reason: a venv
# puts its interpreter in `bin/` on POSIX and `Scripts/` on Windows, and a
# worktree has no `.venv` of its own. This script asserted `bin/` — so on the
# Windows host that builds every installer, the one check that looks at the
# shipped artifact could not start. `gate.sh` exports PYTHON when it calls us,
# so in the normal path this loop does not run; it is here for the direct
# invocation the header documents.
if [ -z "${PYTHON:-}" ]; then
    main_checkout=""
    if common_dir=$(git rev-parse --git-common-dir 2>/dev/null); then
        main_checkout=$(cd "$common_dir/.." 2>/dev/null && pwd) || main_checkout=""
    fi
    for candidate in \
        .venv/bin/python .venv/Scripts/python.exe \
        ${main_checkout:+"$main_checkout/.venv/bin/python"} \
        ${main_checkout:+"$main_checkout/.venv/Scripts/python.exe"}
    do
        if [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
    done
fi
PYTHON="${PYTHON:-.venv/bin/python}"
WORK="${TMPDIR:-/tmp}/kriko-smoke-$$"
trap 'rm -rf "$WORK"' EXIT

say() { printf '\n\033[1m── %s\033[0m\n' "$1"; }
bad() { printf '\033[31m%s\033[0m\n' "$1" >&2; exit 1; }

[ -x "$PYTHON" ] || bad "no interpreter at '$PYTHON'; see docs/DOCTRINE.md or set PYTHON="

# `uv` when it is there, pip and the stdlib when it is not. Requiring uv made
# this gate unrunnable rather than strict: it is installed by `tools/setup.sh`,
# which the Windows host never ran, so the leg exited before building anything
# and took the three legs after it down with it. Nothing here needs uv's
# resolver — we build one wheel and install it into an empty environment, both
# of which pip and `venv` do — so the requirement was a convenience that had
# become a stop.
#
# `--no-build-isolation` on the pip path because setuptools and wheel are
# already in the interpreter this runs from, and the gate is offline by design;
# isolation would go to the network for what is on the machine.
if command -v uv >/dev/null 2>&1; then
    BUILDER=uv
else
    BUILDER=pip
    "$PYTHON" -c "import setuptools, wheel" 2>/dev/null \
        || bad "neither uv nor setuptools+wheel are available; tools/setup.sh installs them"
fi

mkdir -p "$WORK"

# From scratch, and this is not hygiene — it is the check working at all.
# setuptools copies into `build/lib` and *reuses* what is there, so a wheel
# built over a previous one contains whatever the previous one contained. The
# first version of this script passed happily on a pyproject.toml with `kriko`
# deliberately removed from the packages list, because a stale `build/lib` was
# still supplying it. A gate that cannot fail is the thing `CLAUDE.md` warns is
# worse than no gate.
say "clearing what a previous build left behind"
rm -rf build src/*.egg-info
echo "  build/ and src/*.egg-info"

say "building the wheel"
if [ "$BUILDER" = uv ]; then
    uv build --wheel --out-dir "$WORK/dist" >/dev/null
else
    "$PYTHON" -m pip wheel --no-deps --no-build-isolation \
        --wheel-dir "$WORK/dist" . >/dev/null
fi
WHEEL=$(ls "$WORK"/dist/*.whl)
echo "  $(basename "$WHEEL")"

say "looking inside it"
"$PYTHON" - "$WHEEL" <<'PY'
import sys, zipfile

names = zipfile.ZipFile(sys.argv[1]).namelist()
tops = {name.split("/")[0] for name in names}
missing = [one for one in ("kriko", "app") if one not in tops]
if missing:
    raise SystemExit(
        f"the wheel is missing {missing}. `app.cli` imports `kriko` at module "
        f"scope, so a wheel without it installs a `kriko` command that raises "
        f"ModuleNotFoundError before any subcommand runs. Check "
        f"[tool.setuptools.packages.find] in pyproject.toml."
    )
# Read from disk at runtime, so being declared as package data is the only
# thing standing between a wheel and a FileNotFoundError on the first query.
# One entry per file that is *data*: each is invisible to PyInstaller and to
# setuptools alike, and each fails only in a real install.
for data in ("kriko/store/schema.sql", "app/models.toml"):
    if not any(name.endswith(data) for name in names):
        raise SystemExit(
            f"the wheel has no {data}. It is read from disk at runtime, so a "
            f"checkout finds it and a wheel does not; see "
            f"[tool.setuptools.package-data]."
        )
print("  kriko and app are both in it, with the store's DDL and the "
      "model catalogue")
PY

say "installing it somewhere with nothing else on the path"
if [ "$BUILDER" = uv ]; then
    uv venv --python "$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" \
        "$WORK/venv" >/dev/null 2>&1
    VIRTUAL_ENV="$WORK/venv" uv pip install --quiet "$WHEEL" >/dev/null
else
    "$PYTHON" -m venv "$WORK/venv" >/dev/null
fi
# The new environment has the same split its parent does, and hardcoding one
# half of it is the bug this script was carrying twice.
if [ -d "$WORK/venv/Scripts" ]; then VENV_BIN="$WORK/venv/Scripts"; else VENV_BIN="$WORK/venv/bin"; fi
[ "$BUILDER" = uv ] || "$VENV_BIN/python" -m pip install --quiet "$WHEEL" >/dev/null

say "does it import"
# `cd /` so the checkout's own `src/` cannot be what answers. Without this the
# test passes on a tree that ships nothing at all.
(cd / && "$VENV_BIN/python" -c "import kriko, app; print('  both import')")

say "does the command run"
(cd / && "$VENV_BIN/kriko" --version | sed 's/^/  /')

printf '\n\033[32m── the shipped artifact works\033[0m\n'
