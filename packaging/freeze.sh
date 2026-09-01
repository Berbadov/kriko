#!/usr/bin/env bash
# Freeze the sidecar and prove the frozen binary works — the same two steps CI
# runs between "build the UI" and "bundle the desktop app", available locally
# because the failures they catch (a missing hidden import, an undeclared data
# file) do not exist in a source checkout and so cannot be caught by pytest.
#
#   packaging/freeze.sh            # build + smoke
#   packaging/freeze.sh --no-ui    # skip the npm build (bundle already fresh)
#
# Needs no Rust toolchain. The Tauri bundle around this binary is still only
# built in .github/workflows/desktop.yml.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=${PYTHON:-.venv/bin/python}

if [[ "${1:-}" != "--no-ui" ]]; then
    npm --prefix ui run build
fi

"$PYTHON" -m PyInstaller --noconfirm --distpath dist --workpath build \
    packaging/kriko-sidecar.spec

"$PYTHON" packaging/smoke_sidecar.py dist/kriko-sidecar
ls -lh dist/kriko-sidecar
