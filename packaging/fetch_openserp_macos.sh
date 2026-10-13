#!/usr/bin/env bash
# Fetch the pinned OpenSERP build for the native macOS architecture.
#
#     packaging/fetch_openserp_macos.sh arm64 /path/to/openserp
#     packaging/fetch_openserp_macos.sh x86_64 /path/to/openserp
#
# The release asset digests below come from OpenSERP's v0.8.12 GitHub release
# metadata. PyInstaller and GPUI are also built on the matching native runner;
# no cross-architecture bundle is assembled.
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "usage: $0 {arm64|x86_64} DESTINATION" >&2
    exit 2
fi

requested_arch="$1"
destination="$2"
version=0.8.12
case "$requested_arch" in
    arm64)
        asset_arch=arm64
        expected_host=arm64
        digest=00c9a5ea3dbc0286f5469a660faa3ce65f19850a3ed12643076a061063258853
        ;;
    x86_64)
        asset_arch=amd64
        expected_host=x86_64
        digest=3916ea85fbe9abd7ca7df57f3a4ce4b5dd8debc666c0979a59a55f8d96416952
        ;;
    *)
        echo "unsupported macOS architecture: $requested_arch" >&2
        exit 2
        ;;
esac

host_arch=$(uname -m)
if [ "$host_arch" != "$expected_host" ]; then
    echo "requested $requested_arch but this host is $host_arch; build each macOS artifact on its native runner" >&2
    exit 2
fi

if [ -e "$destination" ]; then
    echo "refusing to trust an existing OpenSERP binary at $destination; remove it before fetching the pinned release" >&2
    exit 1
fi

parent=$(dirname "$destination")
mkdir -p "$parent"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
archive="$work/openserp-darwin-$asset_arch-$version.tgz"
extract="$work/extract"
mkdir -p "$extract"
url="https://github.com/karust/openserp/releases/download/v$version/openserp-darwin-$asset_arch-$version.tgz"

curl -fsSL "$url" -o "$archive"
printf '%s  %s\n' "$digest" "$archive" | shasum -a 256 -c -
tar -xzf "$archive" -C "$extract"

binary_count=$(find "$extract" -type f -name openserp -print | wc -l | tr -d ' ')
if [ "$binary_count" != 1 ]; then
    echo "expected one openserp binary in the verified archive, found $binary_count" >&2
    exit 1
fi
binary=$(find "$extract" -type f -name openserp -print)
binary_arch=$(lipo -archs "$binary")
if [ "$binary_arch" != "$requested_arch" ]; then
    echo "verified archive contains architecture(s) '$binary_arch'; expected only $requested_arch" >&2
    exit 1
fi
install -m 755 "$binary" "$destination"
echo "Downloaded and verified OpenSERP $version ($requested_arch)."
