#!/usr/bin/env bash
# The one recipe that builds everything a Mac reader can install, on macOS.
#
#     kriko-ui/package-macos.sh                  # this machine's architecture
#     kriko-ui/package-macos.sh --arch arm64     # Apple Silicon (M chips)
#
# Output, in kriko-ui/builds/:
#
#     kriko-<version>-arm64.dmg        the disk image: Kriko.app and Applications
#     SHA256SUMS-macos.txt             the digest of the disk image
#
# Tauri and PyInstaller do not cross-compile, so a macOS package is built on a
# Mac of its own architecture: arm64 on an arm64 machine, x86_64 on an Intel
# one. The script refuses a mismatch rather than making a bundle that would run
# under emulation. `.github/workflows/desktop.yml` runs this same script on a
# macOS arm64 runner; there is one recipe, and this is it.
#
# In order: preflight (versions agree), the Python side, the pinned OpenSERP for
# this architecture, the frozen engine and its handshake, the web interface, the
# app bundle, one signature over the whole bundle, the app's own start-up check,
# and the disk image.
#
# The engine ships as ONE file on macOS (PyInstaller's default), so there is no
# `_internal` folder to place beside it. The app looks for `kriko-sidecar` and
# `openserp` beside its own executable, in `Kriko.app/Contents/MacOS`, which is
# where Tauri puts external binaries. One file unpacks itself on every start,
# which costs a few seconds on the first one and removes the folder-placement
# problem the Windows package solves with a resource.
#
# The result is ad-hoc signed unless KRIKO_MACOS_SIGN_IDENTITY names a Developer
# ID identity; it is not notarized. Gatekeeper holds a downloaded copy on first
# open: right-click > Open, or `xattr -dr com.apple.quarantine Kriko.app`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UI="$ROOT/kriko-ui"
CRATE="$UI/src-tauri"

die() {
    echo "package-macos: $*" >&2
    exit 1
}

arch=""
version=""
python=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --arch) arch="${2:-}"; [ -n "$arch" ] || die "--arch needs a value"; shift 2 ;;
        --version) version="${2:-}"; [ -n "$version" ] || die "--version needs a value"; shift 2 ;;
        --python) python="${2:-}"; [ -n "$python" ] || die "--python needs a value"; shift 2 ;;
        -h|--help) sed -n '2,34p' "$0"; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

# ---------------------------------------------------------------- the machine

[ "$(uname -s)" = "Darwin" ] || die "this recipe builds macOS packages, on macOS."
host_arch="$(uname -m)"
arch="${arch:-$host_arch}"
case "$arch" in
    arm64)   triple="aarch64-apple-darwin"; serp_arch="arm64" ;;
    x86_64)  triple="x86_64-apple-darwin";  serp_arch="x86_64" ;;
    *) die "unknown architecture: $arch (arm64 or x86_64)" ;;
esac
if [ "$arch" != "$host_arch" ]; then
    die "asked to build $arch and this Mac is $host_arch. Tauri and PyInstaller cannot cross-compile, so build each package on a Mac of its own architecture."
fi

for tool in cargo node npm codesign hdiutil lipo shasum; do
    command -v "$tool" >/dev/null 2>&1 || die "$tool is not on PATH."
done

cd "$ROOT"

# ------------------------------------------------------------ the interpreter

# A dedicated environment by default, the way the Windows recipe makes one: a
# Homebrew or system Python refuses `pip install` into itself, and freezing from
# it would put this machine's own packages in every reader's engine.
if [ -z "$python" ]; then
    if [ ! -x "$ROOT/.venv/bin/python" ]; then
        base=""
        for candidate in python3.13 python3; do
            if command -v "$candidate" >/dev/null 2>&1; then base="$candidate"; break; fi
        done
        [ -n "$base" ] || die "no Python 3.13 found. Install one, or pass --python."
        echo "no .venv here; creating one with $base"
        "$base" -m venv "$ROOT/.venv"
    fi
    python="$ROOT/.venv/bin/python"
fi

"$python" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 13) else 1)' \
    || die "$python is older than 3.13 (pyproject.toml's floor)."
"$python" -c 'import sys; raise SystemExit(0 if sys.version_info.releaselevel == "final" else 1)' \
    || die "$python is a pre-release. A sidecar frozen on it can fail on its first request."

"$python" --version
cargo --version
node --version

# ------------------------------------------------------------------ preflight

# The four committed version strings: the disk image's name and contents both
# come from the tree, so a disagreement is not a build.
"$python" tools/bump.py --show \
    || die "the version strings in pyproject.toml, src-tauri/Cargo.toml, src-tauri/Cargo.lock and package.json disagree. \`python tools/bump.py <version>\` sets all four."

tree="$("$python" -c 'import pathlib, tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"
if [ -n "$version" ]; then
    want="${version#v}"
    if [ "$want" != "$tree" ]; then
        die "asked for $want and this checkout is $tree. The disk image's name and contents both come from the tree; \`git pull\`, or \`python tools/bump.py $want\`, then build again."
    fi
fi

echo ""
echo "=== The app's crate graph is the one that was committed"
(cd "$CRATE" && cargo metadata --locked --format-version 1 > /dev/null)

echo ""
echo "=== Configure shared access for this build"
"$python" packaging/configure_share_pepper.py

echo ""
echo "=== Install the Python side"
"$python" -m pip install --upgrade pip
"$python" -m pip install -r requirements.lock -e "." pyinstaller

# The install has to be *this* tree: the engine is frozen from the installed
# distribution, so another checkout installed here would be frozen under this
# one's name.
installed="$("$python" -c 'from app.version import app_version; print(app_version())')"
[ "$installed" = "$tree" ] || die "the install reports $installed and this tree is $tree. Check that $python has no other checkout installed, then re-run."

# Where cargo puts this build, whoever set CARGO_TARGET_DIR.
target="$(
    cd "$CRATE"
    cargo metadata --no-deps --format-version 1 \
        | "$python" -c 'import json, sys; print(json.load(sys.stdin)["target_directory"])'
)"

staged="$CRATE/binaries"
mkdir -p "$staged"

echo ""
echo "=== Fetch the pinned OpenSERP release for $arch"
rm -f "$staged/openserp-$triple"
"$ROOT/packaging/fetch_openserp_macos.sh" "$serp_arch" "$staged/openserp-$triple"

echo ""
echo "=== Freeze the engine"
work="$(mktemp -d)"
dmg_stage=""
trap 'rm -rf "$work"; [ -z "$dmg_stage" ] || rm -rf "$dmg_stage"' EXIT
KRIKO_FREEZE=onefile "$python" -m PyInstaller --noconfirm --distpath "$ROOT/dist" --workpath "$work" \
    packaging/kriko-sidecar.spec

# One identity on every executable in the bundle: the frozen engine is built
# here, so it is signed here, before Tauri embeds it.
identity="${KRIKO_MACOS_SIGN_IDENTITY:--}"
codesign --force --sign "$identity" "$ROOT/dist/kriko-sidecar"

echo ""
echo "=== The frozen engine answers"
"$python" packaging/smoke_sidecar.py "$ROOT/dist/kriko-sidecar"

echo ""
echo "=== Place the engine beside where the app will be"
rm -f "$staged/kriko-sidecar-$triple"
install -m 755 "$ROOT/dist/kriko-sidecar" "$staged/kriko-sidecar-$triple"

echo ""
echo "=== Install the web interface's packages"
(cd "$UI" && npm ci)

# A stale bundle from an earlier build of this version must not be reported as
# this build's.
rm -rf "$target/release/bundle"

echo ""
echo "=== Build the app"
(cd "$UI" && npx --no-install tauri build --config src-tauri/tauri.macos.bundle.conf.json -- --locked)

app="$target/release/bundle/macos/Kriko.app"
[ -d "$app" ] || die "tauri build reported success and made no app at $app"
for name in Kriko kriko-sidecar openserp; do
    [ -x "$app/Contents/MacOS/$name" ] || die "$name is not executable inside $app/Contents/MacOS, so the app cannot start it."
done
[ -f "$app/Contents/Resources/OpenSERP-LICENSE.txt" ] || die "the OpenSERP license is missing from the bundle."
for name in Kriko kriko-sidecar openserp; do
    built="$(lipo -archs "$app/Contents/MacOS/$name")"
    [ "$built" = "$arch" ] || die "$name is built for '$built' and this package is $arch."
done

echo ""
echo "=== Sign and check the bundle"
codesign --force --deep --sign "$identity" "$app"
codesign --verify --deep --strict --verbose=2 "$app"

# Building the bundle is not the app starting. v0.2.4 built green and panicked
# before its first window, so the app is launched here, held, and asked whether
# it is still up.
echo ""
echo "=== The app opens"
"$python" packaging/smoke_app.py "$app/Contents/MacOS/Kriko"

echo ""
echo "=== The disk image"
builds="$UI/builds"
mkdir -p "$builds"
disk_image="$builds/kriko-$tree-$arch.dmg"
rm -f "$disk_image"
dmg_stage="$(mktemp -d)"
cp -R "$app" "$dmg_stage/Kriko.app"
ln -s /Applications "$dmg_stage/Applications"
hdiutil create -volname "Kriko" -srcfolder "$dmg_stage" -ov -format UDZO "$disk_image" > /dev/null

( cd "$builds" && shasum -a 256 "$(basename "$disk_image")" > SHA256SUMS-macos.txt )

echo ""
echo "=== Done"
ls -lh "$disk_image" "$builds/SHA256SUMS-macos.txt"
echo ""
echo "Ad-hoc signed and not notarized: Gatekeeper holds the first open of a downloaded copy."
echo "Right-click > Open, or: xattr -dr com.apple.quarantine /Applications/Kriko.app"
