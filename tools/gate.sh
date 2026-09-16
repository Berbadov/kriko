#!/usr/bin/env bash
# The gate, now that it runs here instead of on a runner.
#
# `.github/workflows/ci.yml` was deleted on 2026-09-13. Not because the checks
# stopped mattering — the 1.0.0 audit's finding was the opposite, that four
# reported defects had passed every automated gate — but because the account's
# Actions minutes are gone, and a workflow that cannot get a runner is worse
# than no workflow: every commit since 2026-09-08 carried a red CI that was
# never a test result, so the red stopped being information.
#
# So the jobs move here, verbatim. One command, no network, no runner, no bill.
# Run it before every push; `CLAUDE.md`'s app-first rule 1 already asked for
# pytest, and this is the rest of what the branch used to be checked for.
#
#     tools/gate.sh          # everything
#     tools/gate.sh py       # just the Python suite
#     tools/gate.sh ui       # just vitest, types, and the stale-bundle check
#
# Exits non-zero on the first failure, and says which gate failed. Nothing here
# needs secrets: the suite must pass without an API key, which is the same rule
# the workflow had.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
only="${1:-all}"
ran=0

step() { printf '\n\033[1m── %s\033[0m\n' "$1"; }

if [ "$only" = all ] || [ "$only" = py ]; then
    ran=1
    # Four files carry this project's version and only one of them names the
    # installer. Two releases have now shipped under a number the tree did not
    # contain, each caught at build time on the Windows host -- hours after the
    # commit that caused it. It costs a second here.
    step "the four version strings agree"
    "$PYTHON" tools/bump.py --show
    # B138: ruff before pytest, so a lint failure is cheap to see and does not
    # wait behind a ~80s test run. Config (the curated rule set, and every
    # per-file ignore with its reason) lives in pyproject.toml, not here.
    step "ruff (src/kriko, src/app, packs)"
    "$PYTHON" -m ruff check src packs
    # Three invocations, not one `mypy src packs`: `kriko/ledger/extraction.py`
    # and `packs/cars/pipeline/ledger/extraction.py` share a module-path
    # suffix, and mypy's module resolution conflates them into one "Module
    # kriko.ledger has no attribute extraction" false positive when both are
    # on the same command line. Each of the three checks clean alone; the
    # per-module strictness tiers in pyproject.toml apply regardless of how
    # many invocations they are split across.
    step "mypy (src/kriko)"
    "$PYTHON" -m mypy src/kriko
    step "mypy (src/app)"
    "$PYTHON" -m mypy src/app
    step "mypy (packs)"
    "$PYTHON" -m mypy packs
    # No arguments: pytest.ini pins testpaths. Naming directories by hand is how
    # the suite silently shrank to 576 of 761 tests once app/pipeline/ existed.
    # test_repo_invariants.py enforces the layering rules and the testpaths
    # coverage, so the architecture is checked here too.
    step "pytest (engine + catalog + pipeline)"
    "$PYTHON" -m pytest
fi

if [ "$only" = all ] || [ "$only" = node ]; then
    ran=1
    step "node (scraper + extension panel)"
    npm test
fi

if [ "$only" = all ] || [ "$only" = ui ]; then
    ran=1
    step "vitest (svelte components)"
    npm --prefix ui test

    # Types, which was a local-only gate until the workflow took it, and is a
    # local-only gate again. `--threshold error` because the two standing
    # warnings are accessibility notes on markup that is deliberate, and a
    # warning that fails a build is a warning somebody silences.
    step "svelte-check"
    npm --prefix ui run check -- --threshold error

    # src/app/web/static/ is committed build output: the wheel ships it, so a
    # stale bundle means `pip install kriko` serves a UI nobody can reproduce
    # from source. Rebuild and require a clean diff.
    step "the committed bundle is not stale"
    npm --prefix ui run build
    if ! git diff --exit-code -- src/app/web/static; then
        echo "src/app/web/static is stale — the rebuild above changed it. Commit the result." >&2
        exit 1
    fi
fi

if [ "$ran" = 0 ]; then
    echo "unknown gate: $only (expected: all, py, node, ui)" >&2
    exit 2
fi

printf '\n\033[32mall gates passed\033[0m\n'
