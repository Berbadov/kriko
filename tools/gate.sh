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
# So the jobs move here, verbatim. One command, no runner, no bill — and *no
# network on a warm cache*, which is the honest version of what this line used
# to claim flatly. `smoke_wheel.sh` installs the freshly built wheel into an
# empty venv, and its dependencies have to come from an index: on a machine
# with a populated pip cache that is no traffic at all, and on a cold one it is
# the one stage that reaches out. Everything else — ruff, mypy, pytest, the
# node suite, cargo — runs offline.
# Run it before every push; `CLAUDE.md`'s app-first rule 1 already asked for
# pytest, and this is the rest of what the branch used to be checked for.
#
#     tools/gate.sh          # all required desktop stages run concurrently
#     tools/gate.sh py       # just the Python suite
#     tools/gate.sh wheel    # just: does the artifact we ship actually import
#     tools/gate.sh node     # just the JavaScript suites
#     tools/gate.sh ui       # desktop build, lint and behavior scenarios
#     tools/gate.sh site     # website tests
#     tools/gate.sh mobile   # the separate mobile prototype's static checks
#     tools/gate.sh tauri    # just the desktop shell: cargo check and cargo test, offline
#
# With no argument the stages are independent — py, wheel, node, ui, site and tauri —
# so they run concurrently. Each writes to its own log, and a log is printed as
# one block when its stage finishes, so output never interleaves. A failed stage
# does not stop the others: the gate then exits non-zero and names every stage
# that failed. Inside the python stage the order is still cheap-first: version,
# ruff, the three mypy runs, then pytest.
#
# pytest runs with `-n auto` (pytest-xdist, in the `dev` extra) when xdist is
# importable. `GATE_JOBS=1` turns that off and runs the whole gate serially, in
# the order it always had, for debugging; `GATE_JOBS=<n>` sets the worker count.
#
# Nothing here needs secrets: the suite must pass without an API key, which is
# the same rule the workflow had.
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
case "$only" in
    all|py|wheel|node|ui|site|mobile|tauri) ;;
    *) echo "unknown gate: $only (expected: all, py, node, ui, site, mobile, tauri, wheel)" >&2; exit 2 ;;
esac

# pytest workers: `auto` is every core. GATE_JOBS=1 makes the whole gate serial.
jobs="${GATE_JOBS:-auto}"
case "$jobs" in
    auto) ;;
    *[!0-9]*|0) echo "GATE_JOBS must be a worker count of 1 or more, or unset; got '$jobs'" >&2; exit 2 ;;
esac

# `wait -n -p` (which names the job that finished) needs bash 5.1. Without it the
# stages still run, one after another.
concurrent_ok=1
if [ "${BASH_VERSINFO[0]}" -lt 5 ] || { [ "${BASH_VERSINFO[0]}" -eq 5 ] && [ "${BASH_VERSINFO[1]}" -lt 1 ]; }; then
    concurrent_ok=0
fi

declare -A took_ms=() verdict_of=() exit_of=()
current_stage=""
tmp_dir=""

# Runs on every exit. A failing single stage, or a failing serial `all`, stops
# the script where it fails; this is where that stage is named.
cleanup() {
    local rc=$?
    if [ -n "$tmp_dir" ]; then rm -rf "$tmp_dir"; fi
    # 3 is a skip, not a failure: the stage said which check it could not run.
    if [ "$rc" = 3 ] && [ -n "$current_stage" ]; then
        echo "gate SKIPPED in stage: $current_stage — nothing was verified there" >&2
    elif [ "$rc" != 0 ] && [ -n "$current_stage" ]; then
        echo "gate FAILED in stage: $current_stage" >&2
    fi
}
trap cleanup EXIT

step() { printf '\n\033[1m── %s\033[0m\n' "$1"; }
now_ms() { echo $(( $(date +%s%N) / 1000000 )); }
fmt_ms() {
    local s=$(( $1 / 1000 ))
    if [ "$s" -ge 60 ]; then printf '%dm%02ds' $((s / 60)) $((s % 60)); else printf '%ds' "$s"; fi
}

gate_pytest() {
    # `-n auto` is pytest-xdist. Each test runs in one of N worker processes, so
    # the suite must not share state across processes. Each test's state lives
    # under tmp_path or is monkeypatched, and src/app/tests/conftest.py fences the
    # reader's ~/.kriko, the fixed extension port and the real agent CLIs.
    # `--durations=5` comes from pytest.ini's addopts and reports the same way.
    if [ "$jobs" = 1 ]; then
        "$PYTHON" -m pytest
    elif "$PYTHON" -c "import xdist" 2>/dev/null; then
        "$PYTHON" -m pytest -n "$jobs"
    else
        echo "pytest-xdist is not installed in $PYTHON, so pytest runs serially (pip install -e '.[dev]' adds it)."
        "$PYTHON" -m pytest
    fi
}

gate_py() {
    # Three files carry this project's version (pyproject, the app's Cargo.toml
    # and its lock) and the app's is the one that names the installer. Two releases have now shipped under a number the tree did not
    # contain, each caught at build time on the Windows host -- hours after the
    # commit that caused it. It costs a second here.
    step "the version strings agree"
    "$PYTHON" tools/bump.py --show --strict
    # B138: ruff before pytest, so a lint failure is cheap to see and does not
    # wait behind a ~80s test run. Config (the curated rule set, and every
    # per-file ignore with its reason) lives in pyproject.toml, not here.
    #
    # `tools` and `packaging` are in scope too. They were never linted — the
    # gate covered `src` and `packs`, and the scripts that build, freeze, sign
    # and package the release were the only Python in the tree nothing checked.
    # It found four unused imports the day it was turned on, two of them in
    # files that had never been read by a linter at all.
    step "ruff (src/kriko, src/app, packs, server, tools, packaging)"
    "$PYTHON" -m ruff check src packs server tools packaging
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
    step "mypy (server)"
    MYPYPATH=server "$PYTHON" -m mypy -p kriko_cloud
    # No arguments: pytest.ini pins testpaths. Naming directories by hand is how
    # the suite silently shrank to 576 of 761 tests once app/pipeline/ existed.
    # test_repo_invariants.py enforces the layering rules and the testpaths
    # coverage, so the architecture is checked here too.
    step "pytest (engine + catalog + pipeline)"
    gate_pytest
}

gate_wheel() {
    # Not in `py`: it builds an artifact and makes a virtualenv, which is a
    # different order of cost from a test run, and `py` is the one people run in
    # a loop. Its own word, in `all`.
    #
    # Everything in the python stage runs against the *checkout*, where `src/` is
    # on the path and `kriko` imports whether or not the wheel would contain
    # it. A reader's install failed on exactly that gap — the console script
    # was there and the package it imports was not — and nothing in the tree
    # could have seen it.
    step "the shipped wheel imports and runs"
    tools/smoke_wheel.sh
}

gate_node() {
    step "node (scraper + extension panel)"
    # Not just `npm test`. `node --test` exits 0 when its pattern matches no
    # files, and the pattern was single-quoted — which cmd.exe does not strip,
    # so on the Windows host that runs this gate the leg printed `tests 0 /
    # pass 0 / fail 0` and passed, hiding 157 real tests including every one
    # that covers the extension reading a page. The quoting is fixed in
    # package.json; this is the part that makes the *next* such mistake loud.
    # An empty suite and a passing suite must not produce the same tick.
    # And never `--test-force-exit`: it ends the run as soon as the tests
    # registered so far have finished, so a file that registers its tests a
    # moment later is skipped, silently. It cut 31 panel tests from about one
    # run in six, each such run still printing "fail 0".
    if grep -q -- "--test-force-exit" package.json; then
        echo "package.json runs node with --test-force-exit, which drops tests silently." >&2
        exit 1
    fi
    # The status is taken with `||`, not left to `set -e`: an assignment that
    # fails exits the script before its output is printed, so a red run used to
    # stop silently. Printing first and then exiting with the same status keeps
    # the verdict and shows the failure.
    local node_out node_status=0 node_count
    node_out=$(npm test 2>&1) || node_status=$?
    printf '%s\n' "$node_out"
    if [ "$node_status" != 0 ]; then
        echo "the node suite failed (npm test exited $node_status)." >&2
        exit "$node_status"
    fi
    node_count=$(printf '%s' "$node_out" | sed -n 's/.*[^a-z]tests \([0-9][0-9]*\).*/\1/p' | tail -1)
    if [ "${node_count:-0}" -lt 1 ]; then
        echo "the node suite ran ${node_count:-no} tests — a glob that matches nothing is not a pass." >&2
        exit 1
    fi
}

gate_ui() {
    step "desktop interface build, behavior checks and lint"
    (cd kriko-ui && npm run build && npm run lint)
    local ui_out ui_status=0 ui_count
    ui_out=$(cd kriko-ui && node --test --test-reporter=tap tests/*.test.mjs 2>&1) || ui_status=$?
    printf '%s\n' "$ui_out"
    [ "$ui_status" = 0 ] || return "$ui_status"
    ui_count=$(printf '%s' "$ui_out" | sed -n 's/^# tests \([0-9][0-9]*\).*/\1/p' | tail -1)
    if [ "${ui_count:-0}" -lt 4 ]; then
        echo "desktop behavior checks are incomplete: expected at least 4 scenarios, got ${ui_count:-0}" >&2
        return 1
    fi
}

gate_site() {
    step "website tests"
    npm run test:site
}

# The mobile prototype is separate from the desktop release. Check it explicitly
# when editing or distributing it; no skipped device build is called a pass.
gate_mobile() {
    step "mobile prototype typecheck and lint"
    (cd kriko-mobile && npm run typecheck && CI=1 EXPO_NO_TELEMETRY=1 npm run lint)
}

gate_tauri() {
    CRATE="kriko-ui/src-tauri"
    # Set by every path that could not run a real check. The stage then exits 3,
    # and the summary prints *skipped* rather than *passed* — three distinct
    # skips used to report as `passed` here (no cargo, a cold --offline
    # registry, a missing cross target), so a green tick could mean "never ran",
    # which is the one thing this file exists to prevent.
    skipped=0
    CARGO="$(command -v cargo || true)"
    if [ -z "$CARGO" ]; then
        CARGO_BIN="${CARGO_HOME:-$HOME/.cargo}/bin/cargo"
        [ -x "$CARGO_BIN" ] && CARGO="$CARGO_BIN"
    fi

    if [ -z "$CARGO" ]; then
        step "cargo check (kriko-ui/src-tauri)"
        echo "no cargo on this machine — skipping. pytest's test_the_shell_is_valid_rust.py still reads the shell's sources above; a real compile needs a Rust toolchain (rustup.rs) or the Windows host that builds the installer."
        skipped=1
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
        _shell_cargo() {
            local desc="$1"; shift
            local out status
            out=$(cd "$CRATE" && cargo "$@" --locked --offline 2>&1)
            status=$?
            printf '%s\n' "$out"
            [ "$status" = 0 ] && return 0
            if printf '%s' "$out" | grep -qiE "failed to get |spurious network error|unable to get packages from source|offline mode|no matching package named|attempting to make an HTTP request"; then
                echo "skipping $desc — the cargo registry cache is not warm and this gate runs --offline; run \`cargo fetch --locked\` once in $CRATE (needs network), then re-run"
                return 2
            fi
            return 1
        }

        step "cargo check (kriko-ui/src-tauri)"
        result=0
        _shell_cargo "the cargo check" check "${cargo_profile_args[@]}" || result=$?
        [ "$result" = 1 ] && exit 1
        [ "$result" = 2 ] && skipped=1

        if [ "$result" = 0 ]; then
            step "cargo test (kriko-ui/src-tauri)"
            result=0
            _shell_cargo "the cargo tests" test "${cargo_profile_args[@]}" || result=$?
            [ "$result" = 1 ] && exit 1
            [ "$result" = 2 ] && skipped=1
        fi

        # The Windows-only code (tray, single instance, window sizing, the
        # failure box) compiles only for Windows, and the reader is on
        # Windows. Off a Windows host it is checked by cross-compiling when
        # the target is installed; otherwise the gate says it was not.
        case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) win_host=1 ;; *) win_host=0 ;; esac
        if [ "$result" = 0 ] && [ "$win_host" = 0 ]; then
            step "cargo check --target x86_64-pc-windows-gnu (kriko-ui/src-tauri)"
            if command -v rustup >/dev/null 2>&1 && rustup target list --installed 2>/dev/null | grep -qx x86_64-pc-windows-gnu; then
                result=0
                _shell_cargo "the Windows cargo check" check --target x86_64-pc-windows-gnu "${cargo_profile_args[@]}" || result=$?
                [ "$result" = 1 ] && exit 1
            else
                echo "not checked for Windows: the x86_64-pc-windows-gnu target is not installed (\`rustup target add x86_64-pc-windows-gnu\` adds it)"
                skipped=1
            fi
        fi
    fi
    [ "$skipped" = 1 ] && exit 3
    return 0
}

summary() {
    local wall="$1" n
    local -a failed=() skipped=()
    printf '\n\033[1m── gate summary\033[0m\n'
    for n in py wheel node ui site tauri; do
        [ -n "${verdict_of[$n]:-}" ] || continue
        printf '  %-7s %-16s %s\n' "$n" "${verdict_of[$n]}" "$(fmt_ms "${took_ms[$n]}")"
        # 3 is "this stage could not run a real check" — reported, and never a
        # green tick. See `gate_tauri`.
        if [ "${exit_of[$n]}" = 3 ]; then
            skipped+=("$n")
        elif [ "${exit_of[$n]}" != 0 ]; then
            failed+=("$n")
        fi
    done
    printf '  %-7s %-16s %s\n' "wall" "" "$(fmt_ms "$wall")"
    if [ "${#failed[@]}" -gt 0 ]; then
        printf '\n\033[31mgate FAILED in: %s\033[0m\n' "${failed[*]}" >&2
        exit 1
    fi
    if [ "${#skipped[@]}" -gt 0 ]; then
        printf '\n\033[33mgates passed, but SKIPPED in: %s — nothing was verified there\033[0m\n' "${skipped[*]}"
        return 0
    fi
    printf '\n\033[32mall gates passed\033[0m\n'
}

# All four stages at once. Each runs in a background subshell with its own log;
# whichever finishes first is printed first, as one block.
run_all_concurrently() {
    local -a stages=(py wheel node ui site tauri)
    local -A name_of=() started=()
    local n rc done_pid remaining t0 verdict
    t0=$(now_ms)
    tmp_dir=$(mktemp -d)
    for n in "${stages[@]}"; do
        started[$n]=$(now_ms)
        ( trap - EXIT; "gate_$n" ) >"$tmp_dir/$n.log" 2>&1 &
        name_of[$!]=$n
    done
    echo "running ${stages[*]} at once; each stage prints as one block when it finishes"
    remaining=${#stages[@]}
    while [ "$remaining" -gt 0 ]; do
        rc=0
        wait -n -p done_pid || rc=$?
        n=${name_of[$done_pid]}
        unset "name_of[$done_pid]"
        remaining=$((remaining - 1))
        took_ms[$n]=$(( $(now_ms) - ${started[$n]} ))
        exit_of[$n]=$rc
        if [ "$rc" = 0 ]; then verdict=passed
        elif [ "$rc" = 3 ]; then verdict=skipped
        else verdict="FAILED (exit $rc)"; fi
        verdict_of[$n]=$verdict
        printf '\n\033[1m════ %s: %s after %s\033[0m\n' "$n" "$verdict" "$(fmt_ms "${took_ms[$n]}")"
        cat "$tmp_dir/$n.log"
    done
    summary $(( $(now_ms) - t0 ))
}

# The stages one after another, output streamed as it is produced. This is the
# order the gate always ran in, and it stops at the first failing stage.
run_all_in_order() {
    local n t0 s rc
    t0=$(now_ms)
    for n in py wheel node ui site tauri; do
        current_stage=$n
        s=$(now_ms)
        # The exit code was being dropped here (`verdict_of[$n]=passed` whatever
        # happened), which is how a skipped stage read as a pass in the order
        # this gate ran in before the concurrent one existed.
        rc=0
        "gate_$n" || rc=$?
        took_ms[$n]=$(( $(now_ms) - s ))
        exit_of[$n]=$rc
        if [ "$rc" = 0 ]; then verdict_of[$n]=passed
        elif [ "$rc" = 3 ]; then verdict_of[$n]=skipped
        else verdict_of[$n]="FAILED (exit $rc)"; fi
        [ "$rc" != 0 ] && [ "$rc" != 3 ] && exit "$rc"
    done
    current_stage=""
    summary $(( $(now_ms) - t0 ))
}

case "$only" in
    all)
        if [ "$jobs" = 1 ]; then
            run_all_in_order
        elif [ "$concurrent_ok" = 1 ]; then
            run_all_concurrently
        else
            echo "bash is older than 5.1, so the stages run one after another"
            run_all_in_order
        fi
        ;;
    *)
        current_stage=$only
        rc=0
        "gate_$only" || rc=$?
        current_stage=""
        if [ "$rc" = 3 ]; then
            printf '\n\033[33m%s was SKIPPED: nothing was verified\033[0m\n' "$only"
        elif [ "$rc" != 0 ]; then
            exit "$rc"
        else
            printf '\n\033[32mall gates passed\033[0m\n'
        fi
        ;;
esac
