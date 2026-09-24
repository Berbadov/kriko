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
PYTHON="${PYTHON:-.venv/bin/python}"
PORT="${KRIKO_WALK_PORT:-8799}"
OUT="${KRIKO_WALK_OUT:-.walk}"
HOME_DIR="$(mktemp -d)"
trap 'kill "$server" 2>/dev/null || true; rm -rf "$HOME_DIR"' EXIT

# The first-party packs, built fresh, so every screen has knowledge to show.
# An empty store renders half the app as empty states and walks nothing.
"$PYTHON" packaging/build_packs.py >"$HOME_DIR/build.log" 2>&1 || { cat "$HOME_DIR/build.log"; exit 1; }

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
