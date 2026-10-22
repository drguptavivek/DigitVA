#!/usr/bin/env bash
# Install a published Expo web export release into mobile/digitva-collect/dist
# so hosts never run Node (digitva-r2tj). The pin (tag + SHA-256) lives in
# deploy/expo-web-release.env; the download is verified before anything is
# replaced, and the previous export is kept as dist.prev for rollback.
# Run from the repository root, then rebuild the app image (the export is
# copied into it) or restart the app if it serves the checkout directly.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=/dev/null
. deploy/expo-web-release.env
: "${EXPO_WEB_TAG:?EXPO_WEB_TAG missing in deploy/expo-web-release.env}"
: "${EXPO_WEB_SHA256:?EXPO_WEB_SHA256 missing in deploy/expo-web-release.env}"

asset="${EXPO_WEB_TAG}.tar.gz"
url="https://github.com/drguptavivek/DigitVA/releases/download/${EXPO_WEB_TAG}/${asset}"
target=mobile/digitva-collect/dist
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

curl -fsSL --retry 3 -o "$tmp/$asset" "$url"
echo "${EXPO_WEB_SHA256}  $tmp/$asset" | sha256sum -c -

mkdir "$tmp/dist"
tar -xzf "$tmp/$asset" -C "$tmp/dist"
[ -f "$tmp/dist/index.html" ] || { echo "ERROR: $asset has no index.html" >&2; exit 1; }

rm -rf "$target.prev"
[ -d "$target" ] && mv "$target" "$target.prev"
mv "$tmp/dist" "$target"
echo "Installed $EXPO_WEB_TAG into $target (previous export in $target.prev)."
