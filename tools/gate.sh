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
#     tools/gate.sh tauri    # just the shell's cargo check, native + windows-target
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
    echo "Create the venv (see CONTRIBUTING.md) or set PYTHON=/path/to/python." >&2
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
    # Four files carry this project's version and only one of them names the
    # installer. Two releases have now shipped under a number the tree did not
    # contain, each caught at build time on the Windows host -- hours after the
    # commit that caused it. It costs a second here.
    step "the four version strings agree"
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

if [ "$only" = all ] || [ "$only" = tauri ]; then
    ran=1
    CRATE="tauri/src-tauri"
    CARGO="$(command -v cargo || true)"
    if [ -z "$CARGO" ]; then
        CARGO_BIN="${CARGO_HOME:-$HOME/.cargo}/bin/cargo"
        [ -x "$CARGO_BIN" ] && CARGO="$CARGO_BIN"
    fi

    if [ -z "$CARGO" ]; then
        step "cargo check (tauri/src-tauri)"
        echo "no cargo on this machine — skipping. pytest's test_the_shell_is_valid_rust.py already parsed every .rs file above; a real compile still needs a Rust toolchain (rustup.rs) or the Windows host that builds the installer."
    else
        export PATH="$(dirname "$CARGO"):$PATH"

        _tauri_cargo_check() {
            local target_flag="$1" desc="$2" out status
            out=$(cd "$CRATE" && cargo check --locked --offline $target_flag 2>&1)
            status=$?
            printf '%s\n' "$out"
            [ "$status" = 0 ] && return 0
            # The last alternative is the gap the first version had: a machine
            # with no pkg-config *binary* at all fails with "The pkg-config
            # command could not be found", which matches none of the
            # package-name patterns above and used to fail the gate instead
            # of skipping — the tauri leg was unrunnable on a clean container,
            # the exact thing the skip exists to prevent.
            if printf '%s' "$out" | grep -qiE "webkit2gtk.*not found|Package .*was not found|glib-2\.0.*not found|appindicator.*not found|pkg-config command could not be found"; then
                echo "skipping $desc — a system dev package pkg-config cannot find is missing (see tauri/README.md's pre-flight apt-get line: libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev)"
                return 2
            fi
            if printf '%s' "$out" | grep -qiE "target .* may not be installed|can't find crate for \`core\`"; then
                echo "skipping $desc — the $target_flag target is not installed (rustup target add x86_64-pc-windows-gnu)"
                return 2
            fi
            if printf '%s' "$out" | grep -qiE "failed to get |spurious network error|unable to get packages from source|offline mode|no matching package named"; then
                echo "skipping $desc — the cargo registry cache is not warm and this gate runs --offline; run \`cargo fetch --locked\` once in $CRATE (needs network), then re-run"
                return 2
            fi
            return 1
        }

        # tauri.conf.json declares the sidecar as an external binary, and its
        # build script refuses to run when the file for the triple being built
        # is absent. That is correct — it is what stops an installer shipping
        # without an engine — so a *check* has to place an empty stand-in and
        # take it away again.
        #
        # This used to happen for the gnu cross-target only, which made the
        # native leg unrunnable on Windows: the host triple there is
        # `x86_64-pc-windows-msvc`, whose stub nothing created, so the leg died
        # on `resource path binaries\kriko-sidecar-x86_64-pc-windows-msvc.exe
        # doesn't exist` before rustc read a line. Same shape as the `bin/` vs
        # `Scripts/` bug this file opens with: written for a Linux host, run on
        # the Windows one that actually builds the installer. Stub whichever
        # triple the check is about, and ask rustc what the host's is rather
        # than assuming.
        _tauri_check_with_stub() {
            local triple="$1" target_flag="$2" desc="$3" stub created=0 result=0
            stub="$CRATE/binaries/kriko-sidecar-$triple"
            case "$triple" in *windows*) stub="$stub.exe" ;; esac
            if [ -n "$triple" ] && [ ! -e "$stub" ]; then
                mkdir -p "$(dirname "$stub")"
                : > "$stub"
                created=1
            fi
            _tauri_cargo_check "$target_flag" "$desc" || result=$?
            [ "$created" = 1 ] && rm -f "$stub"
            return "$result"
        }

        HOST_TRIPLE=$(rustc -vV 2>/dev/null | sed -n 's/^host: //p')

        # `icons/` is gitignored but for the 1024px master, because every other
        # size is generated at packaging time by `tauri icon` — which needs the
        # Tauri CLI, which needs a network this gate does not have. One of those
        # generated files is not a bundling detail though: `tauri-build` turns
        # `icon.ico` into a Win32 resource *before* rustc runs, so on a Windows
        # host its absence is not a missing icon, it is `cargo check` refusing
        # to start. `render_icon.py` derives that one file from the same master,
        # offline and deterministically, which is what makes this leg runnable
        # on the machine that actually builds installers.
        if [ ! -e "$CRATE/icons/icon.ico" ]; then
            "$PYTHON" packaging/render_icon.py >/dev/null
        fi

        step "cargo check (tauri/src-tauri, native)"
        result=0
        _tauri_check_with_stub "$HOST_TRIPLE" "" "the native cargo check" || result=$?
        [ "$result" = 1 ] && exit 1

        step "cargo check (tauri/src-tauri, windows cross-target)"
        result=0
        _tauri_check_with_stub "x86_64-pc-windows-gnu" \
            "--target x86_64-pc-windows-gnu" \
            "the windows cross-target cargo check" || result=$?
        [ "$result" = 1 ] && exit 1
    fi
fi

if [ "$ran" = 0 ]; then
    echo "unknown gate: $only (expected: all, py, wheel, node, tauri)" >&2
    exit 2
fi

printf '\n\033[32mall gates passed\033[0m\n'
