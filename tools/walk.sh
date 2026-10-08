#!/usr/bin/env bash
# Open the app in a real browser and press every button on every screen.
#
#     tools/walk.sh                 # every screen, report in .walk/
#     tools/walk.sh agents          # only routes whose address contains "agents"
#     KRIKO_WALK_REAL_CLIS=1 tools/walk.sh   # this machine's own claude/agy/opencode
#
# **Why this exists.** The suite is 537 vitest cases and a thousand pytest
# ones, and "the whole app feels low quality" was still true, because none of
# them has ever pressed a button in a browser against the real server: they
# render one component with a stubbed fetch. A 6-second Agents screen, a
# dropdown that saves in 6 seconds, a loading line that never clears — none
# of those is visible to a test that mocks the request that is slow.
#
# It runs the server on a throwaway home (never `~/.kriko`), with stand-in
# CLIs from tools/walk/bin ahead of PATH so no button can spend a real
# subscription's quota; the stand-ins are as slow as the real `models`
# commands, which is the delay worth catching. Buttons that would end the
# process or throw data away are listed and never pressed.
#
# Needs Playwright and a Chromium. On the Windows host:
#     npm i -g playwright && npx playwright install chromium
set -euo pipefail
cd "$(dirname "$0")/.."
# `bin/` on POSIX, `Scripts/` on Windows: the same probe tools/gate.sh makes,
# for the same reason — this script hardcoded the first and could not start
# on the Windows host the app ships from.
if [ -z "${PYTHON:-}" ]; then
    for candidate in .venv/bin/python .venv/Scripts/python.exe; do
        if [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
    done
fi
PYTHON="${PYTHON:-.venv/bin/python}"
# The stand-ins are bash scripts. On Windows the server finds them through
# tools/walk/bin/*.cmd, which need to be told which bash is this one: a bare
# `bash` from cmd.exe can be WSL's.
if command -v cygpath >/dev/null 2>&1; then
    KRIKO_WALK_BASH="$(cygpath -w "$(command -v bash)")"
    export KRIKO_WALK_BASH
fi
PORT="${KRIKO_WALK_PORT:-8799}"
OUT="${KRIKO_WALK_OUT:-.walk}"
HOME_DIR="$(mktemp -d)"
server=""
# Anything the walk's buttons launched with this home — the Extension screen
# opens a real browser on a profile under it — outlives the server, holds its
# files open, and on Windows is a window left on the reader's desktop.
cleanup() {
    [ -z "$server" ] || kill "$server" 2>/dev/null || true
    if command -v powershell.exe >/dev/null 2>&1 && command -v cygpath >/dev/null 2>&1; then
        # The venv's python.exe is a launcher that re-execs the real one, so
        # `kill` above ends the launcher and leaves the server serving.
        powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*$(cygpath -w "$HOME_DIR")*' -or \$_.CommandLine -like '*app.web --port $PORT*' } | ForEach-Object { taskkill /PID \$_.ProcessId /T /F *> \$null }" 2>/dev/null || true
    fi
    rm -rf "$HOME_DIR" 2>/dev/null || true
}
trap cleanup EXIT

# The first-party packs, built fresh, so every screen has knowledge to show.
# An empty store renders half the app as empty states and walks nothing.
HOME="$HOME_DIR" USERPROFILE="$HOME_DIR" "$PYTHON" packaging/build_packs.py >"$HOME_DIR/build.log" 2>&1 || { cat "$HOME_DIR/build.log"; exit 1; }

path="$PATH"
[ -n "${KRIKO_WALK_REAL_CLIS:-}" ] || path="$PWD/tools/walk/bin:$PATH"
HOME="$HOME_DIR" USERPROFILE="$HOME_DIR" PATH="$path" KRIKO_BUNDLED_PACKS="$PWD/dist" \
    "$PYTHON" -m app.web --port "$PORT" >"$HOME_DIR/server.log" 2>&1 &
server=$!
for _ in $(seq 1 100); do
    curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
    sleep 0.2
done
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null || { cat "$HOME_DIR/server.log"; exit 1; }

KRIKO_WALK_ONLY="${1:-}" node tools/walk/walk.mjs "http://127.0.0.1:$PORT" "$OUT"
