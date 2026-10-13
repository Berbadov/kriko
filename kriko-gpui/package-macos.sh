#!/usr/bin/env bash
# Build the native macOS app bundle, drag-and-drop disk image and portable zip.
#
#     kriko-gpui/package-macos.sh arm64
#     kriko-gpui/package-macos.sh x86_64
#
# Run on Apple Silicon for arm64 and Intel for x86_64. PyInstaller and
# OpenSERP are architecture-specific, so one bundle is built per native host.
set -euo pipefail

CRATE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$CRATE/.." && pwd)
cd "$ROOT"

if [ "$#" -ne 1 ]; then
    echo "usage: $0 {arm64|x86_64}" >&2
    exit 2
fi

MAC_ARCH="$1"
HOST_ARCH=$(uname -m)
case "$MAC_ARCH:$HOST_ARCH" in
    arm64:arm64)
        RUST_TARGET=aarch64-apple-darwin
        ;;
    x86_64:x86_64)
        RUST_TARGET=x86_64-apple-darwin
        ;;
    *)
        echo "requested $MAC_ARCH on host $HOST_ARCH; build each artifact on its matching native runner" >&2
        exit 2
        ;;
esac
export MACOSX_DEPLOYMENT_TARGET=12.0
SIGN_IDENTITY=${KRIKO_MACOS_SIGN_IDENTITY:-}
NOTARY_PROFILE=${KRIKO_MACOS_NOTARY_PROFILE:-}
# Make the selected identity explicit for the PyInstaller spec, which signs
# the onefile executable and each embedded binary before the bundle is built.
export KRIKO_MACOS_SIGN_IDENTITY="$SIGN_IDENTITY"
if [ -n "$NOTARY_PROFILE" ] && [ -z "$SIGN_IDENTITY" ]; then
    echo "KRIKO_MACOS_NOTARY_PROFILE requires KRIKO_MACOS_SIGN_IDENTITY" >&2
    exit 2
fi

for tool in cargo rustc sips iconutil hdiutil ditto lipo shasum plutil; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "$tool is required to build the macOS application" >&2
        exit 1
    fi
done
if [ -n "$SIGN_IDENTITY" ] && ! command -v codesign >/dev/null 2>&1; then
    echo "codesign is required when KRIKO_MACOS_SIGN_IDENTITY is set" >&2
    exit 1
fi
if [ -n "$NOTARY_PROFILE" ]; then
    for tool in xcrun stapler; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            echo "$tool is required when KRIKO_MACOS_NOTARY_PROFILE is set" >&2
            exit 1
        fi
    done
fi

if [ -z "${PYTHON:-}" ]; then
    if [ -x "$ROOT/.venv/bin/python" ]; then
        PYTHON="$ROOT/.venv/bin/python"
    else
        PYTHON=python3
    fi
fi
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python 3.13+ is required; create the repo environment with tools/setup.sh or set PYTHON" >&2
    exit 1
fi

"$PYTHON" - <<'PY'
import sys

if sys.version_info < (3, 13) or sys.version_info.releaselevel != "final":
    raise SystemExit(f"Python 3.13+ final is required, found {sys.version.split()[0]}")
PY

"$PYTHON" tools/bump.py --show --strict
VERSION=$("$PYTHON" -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')

echo "Installing the locked Python runtime and PyInstaller"
if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$PYTHON" -r requirements.lock
    uv pip install --python "$PYTHON" -e . pyinstaller
else
    if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
        "$PYTHON" -m ensurepip --upgrade
    fi
    "$PYTHON" -m pip install --upgrade pip
    "$PYTHON" -m pip install -r requirements.lock
    "$PYTHON" -m pip install -e . pyinstaller
fi

echo "Checking the committed Rust dependency graph"
cd "$CRATE"
cargo metadata --locked --format-version 1 > /dev/null

if [ -n "${CARGO_TARGET_DIR:-}" ]; then
    CARGO_OUTPUT=${CARGO_TARGET_DIR%/}
    case "$CARGO_OUTPUT" in
        /*) ;;
        *) CARGO_OUTPUT="$CRATE/$CARGO_OUTPUT" ;;
    esac
else
    CARGO_OUTPUT="$CRATE/target"
fi
BIN="$CARGO_OUTPUT/$RUST_TARGET/release"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "Building the $MAC_ARCH desktop executable"
cargo build --release --locked --target "$RUST_TARGET"
cd "$ROOT"

echo "Fetching the pinned OpenSERP $MAC_ARCH binary"
"$ROOT/packaging/fetch_openserp_macos.sh" "$MAC_ARCH" "$WORK/openserp"
cp "$CRATE/third-party/OpenSERP-LICENSE.txt" "$WORK/OpenSERP-LICENSE.txt"

echo "Freezing and smoke-checking the engine sidecar"
PYTHON="$PYTHON" "$ROOT/packaging/freeze.sh"
install -m 755 "$ROOT/dist/kriko-sidecar" "$BIN/kriko-sidecar"

for binary in "$BIN/kriko" "$BIN/kriko-sidecar" "$WORK/openserp"; do
    binary_arch=$(lipo -archs "$binary")
    if [ "$binary_arch" != "$MAC_ARCH" ]; then
        echo "$binary contains architecture(s) '$binary_arch'; expected only $MAC_ARCH" >&2
        exit 1
    fi
done

APP="$WORK/Kriko.app"
CONTENTS="$APP/Contents"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"
install -m 755 "$BIN/kriko" "$CONTENTS/MacOS/kriko"
install -m 755 "$BIN/kriko-sidecar" "$CONTENTS/MacOS/kriko-sidecar"
install -m 755 "$WORK/openserp" "$CONTENTS/MacOS/openserp"
install -m 644 "$WORK/OpenSERP-LICENSE.txt" "$CONTENTS/MacOS/OpenSERP-LICENSE.txt"
install -m 644 "$CRATE/macos/Info.plist.in" "$CONTENTS/Info.plist"
sed -i '' "s/@VERSION@/$VERSION/g" "$CONTENTS/Info.plist"
printf 'APPL????' > "$CONTENTS/PkgInfo"
"$PYTHON" "$ROOT/packaging/macos_icon.py" "$WORK/Kriko.iconset" "$CONTENTS/Resources/kriko.icns"
plutil -lint "$CONTENTS/Info.plist"

if [ -n "$SIGN_IDENTITY" ]; then
    echo "Signing the app with the configured Developer ID identity"
    for binary in "$CONTENTS/MacOS/kriko" "$CONTENTS/MacOS/kriko-sidecar" "$CONTENTS/MacOS/openserp"; do
        codesign --force --options runtime --timestamp --sign "$SIGN_IDENTITY" "$binary"
    done
    codesign --force --options runtime --timestamp --sign "$SIGN_IDENTITY" "$APP"
    codesign --verify --deep --strict "$APP"
fi

if [ -n "$NOTARY_PROFILE" ]; then
    echo "Submitting the signed app for notarization"
    NOTARY_ZIP="$WORK/Kriko-notary.zip"
    ditto -c -k --keepParent "$APP" "$NOTARY_ZIP"
    xcrun notarytool submit "$NOTARY_ZIP" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$APP"
    xcrun stapler validate "$APP"
fi

echo "Checking the app bundle starts and supervises its engine"
"$PYTHON" "$ROOT/packaging/smoke_app.py" "$CONTENTS/MacOS/kriko"

BUILDS="$CRATE/builds"
mkdir -p "$BUILDS"
DMG="$BUILDS/kriko-$VERSION-macos-$MAC_ARCH.dmg"
ZIP="$BUILDS/kriko-$VERSION-macos-$MAC_ARCH-portable.zip"
SUMS="$BUILDS/SHA256SUMS-$MAC_ARCH.txt"
rm -f "$DMG" "$ZIP" "$SUMS"

STAGE="$WORK/dmg-root"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/Kriko.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Kriko $VERSION ($MAC_ARCH)" -srcfolder "$STAGE" -ov -format UDZO "$DMG" > /dev/null
if [ -n "$SIGN_IDENTITY" ]; then
    codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG"
    codesign --verify --strict "$DMG"
fi
ditto -c -k --keepParent "$APP" "$ZIP"
if [ -n "$NOTARY_PROFILE" ]; then
    echo "Submitting the disk image for notarization"
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
    xcrun stapler validate "$DMG"
fi
# Store basenames in the per-architecture manifest so the same file verifies
# after upload/download into the release asset directory.
(
    cd "$BUILDS"
    shasum -a 256 "$(basename "$DMG")" "$(basename "$ZIP")" > "$(basename "$SUMS")"
)

if [ -n "$NOTARY_PROFILE" ]; then
    BUILD_MODE="signed and notarized"
elif [ -n "$SIGN_IDENTITY" ]; then
    BUILD_MODE="signed"
else
    BUILD_MODE="unsigned"
fi
echo "Built $BUILD_MODE macOS artifacts:"
ls -lh "$DMG" "$ZIP" "$SUMS"
