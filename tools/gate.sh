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
#     tools/gate.sh wheel    # just: does the artifact we ship actually import
#     tools/gate.sh ui       # just vitest, types, and the stale-bundle check
#     tools/gate.sh gpui     # just the desktop app: cargo check and cargo test, offline
#
# Exits non-zero on the first failure, and says which gate failed. Nothing here
# needs secrets: the suite must pass without an API key, which is the same rule
# the workflow had.
set -euo pipefail

cd "$(dirname "$0")/.."
# A venv puts its interpreter in `bin/` on POSIX and in `Scripts/` on Windows,
# and this script hardcoded the first. So `tools/gate.sh` exited 127 on the
# Windows host — the one machine every installer since 0.5.0 has been built on,
# and the only one where the app is actually assembled and run.
#
# That is this file's own premise failing. `ci.yml` was deleted because a gate
# that cannot get a runner teaches people to scroll past a red tick; a gate
# that dies on `No such file or directory` before its first check is the same
# thing with fewer steps. Probe for the interpreter instead of asserting where
# it lives. `PYTHON=` still overrides, and still wins.
# The second place to look is the main checkout. A git worktree has no `.venv`
# of its own and is not supposed to — the interpreter and its packages are the
# same ones either way — so a gate that only looks beside itself refuses to run
# in exactly the place this project does its isolated work.
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
if [ ! -x "$PYTHON" ]; then
    echo "gate.sh: no interpreter at '$PYTHON'." >&2
    echo "Create the venv (see docs/DOCTRINE.md) or set PYTHON=/path/to/python." >&2
    exit 1
fi
# Exported, not merely set: `tools/smoke_wheel.sh` is a separate process and
# was left to repeat the probe above — which it did not, so it asserted
# `.venv/bin/python` and could not start on Windows. One probe, one answer.
export PYTHON
only="${1:-all}"
ran=0

step() { printf '\n\033[1m── %s\033[0m\n' "$1"; }

if [ "$only" = all ] || [ "$only" = py ]; then
    ran=1
    # Three files carry this project's version (pyproject, the app's Cargo.toml
    # and its lock) and the app's is the one that names the installer. Two releases have now shipped under a number the tree did not
    # contain, each caught at build time on the Windows host -- hours after the
    # commit that caused it. It costs a second here.
    step "the version strings agree"
    "$PYTHON" tools/bump.py --show --strict
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

# Not in `py`: it builds an artifact and makes a virtualenv, which is a
# different order of cost from a test run, and `py` is the one people run in a
# loop. Its own word, in `all`.
if [ "$only" = all ] || [ "$only" = wheel ]; then
    ran=1
    # Everything above this line runs against the *checkout*, where `src/` is
    # on the path and `kriko` imports whether or not the wheel would contain
    # it. A reader's install failed on exactly that gap — the console script
    # was there and the package it imports was not — and nothing in the tree
    # could have seen it.
    step "the shipped wheel imports and runs"
    tools/smoke_wheel.sh
fi

if [ "$only" = all ] || [ "$only" = node ]; then
    ran=1
    step "node (scraper + extension panel)"
    # Not just `npm test`. `node --test` exits 0 when its pattern matches no
    # files, and the pattern was single-quoted — which cmd.exe does not strip,
    # so on the Windows host that runs this gate the leg printed `tests 0 /
    # pass 0 / fail 0` and passed, hiding 157 real tests including every one
    # that covers the extension reading a page. The quoting is fixed in
    # package.json; this is the part that makes the *next* such mistake loud.
    # An empty suite and a passing suite must not produce the same tick.
    node_out=$(npm test 2>&1)
    printf '%s\n' "$node_out"
    node_count=$(printf '%s' "$node_out" | sed -n 's/.*[^a-z]tests \([0-9][0-9]*\).*/\1/p' | tail -1)
    if [ "${node_count:-0}" -lt 1 ]; then
        echo "the node suite ran ${node_count:-no} tests — a glob that matches nothing is not a pass." >&2
        exit 1
    fi
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

    # The extension's colour tokens are generated from the app's theme — same
    # discipline as the bundle below, and for the same reason: the extension
    # loads static files with no build step, so the output is committed and
    # something has to notice when it stops matching its source.
    step "the panel's palette is not stale"
    python tools/tokens.py --check

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

if [ "$only" = all ] || [ "$only" = gpui ]; then
    ran=1
    CRATE="kriko-gpui"
    CARGO="$(command -v cargo || true)"
    if [ -z "$CARGO" ]; then
        CARGO_BIN="${CARGO_HOME:-$HOME/.cargo}/bin/cargo"
        [ -x "$CARGO_BIN" ] && CARGO="$CARGO_BIN"
    fi

    if [ -z "$CARGO" ]; then
        step "cargo check (kriko-gpui)"
        echo "no cargo on this machine — skipping. pytest's test_the_shell_is_valid_rust.py still reads the shell's sources above; a real compile needs a Rust toolchain (rustup.rs) or the Windows host that builds the installer."
    else
        export PATH="$(dirname "$CARGO"):$PATH"
        # Reuse the shipping cache on hosts with little disk space. Both
        # profiles still compile and run the same checks and tests.
        cargo_profile_args=()
        case "${KRIKO_GATE_CARGO_PROFILE:-dev}" in
            dev) ;;
            release) cargo_profile_args=(--release) ;;
            *) echo "KRIKO_GATE_CARGO_PROFILE must be dev or release" >&2; exit 2 ;;
        esac

        # Offline on purpose: a gate that fetches is a gate that fails for the
        # network. A cold registry cache is a skip with its remedy, never a
        # red tick that was not a test result.
        _gpui_cargo() {
            local desc="$1"; shift
            local out status
            out=$(cd "$CRATE" && cargo "$@" --locked --offline 2>&1)
            status=$?
            printf '%s
' "$out"
            [ "$status" = 0 ] && return 0
            if printf '%s' "$out" | grep -qiE "failed to get |spurious network error|unable to get packages from source|offline mode|no matching package named|attempting to make an HTTP request"; then
                echo "skipping $desc — the cargo registry cache is not warm and this gate runs --offline; run \`cargo fetch --locked\` once in $CRATE (needs network), then re-run"
                return 2
            fi
            return 1
        }

        step "cargo check (kriko-gpui)"
        result=0
        _gpui_cargo "the cargo check" check "${cargo_profile_args[@]}" || result=$?
        [ "$result" = 1 ] && exit 1

        if [ "$result" = 0 ]; then
            step "cargo test (kriko-gpui)"
            result=0
            _gpui_cargo "the cargo tests" test "${cargo_profile_args[@]}" || result=$?
            [ "$result" = 1 ] && exit 1
        fi
    fi
fi

if [ "$ran" = 0 ]; then
    echo "unknown gate: $only (expected: all, py, node, ui, gpui, wheel)" >&2
    exit 2
fi

printf '\n\033[32mall gates passed\033[0m\n'
