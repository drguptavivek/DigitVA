#!/usr/bin/env bash
# Build an unsigned DigitVA.app that runs the offline PHC station locally and
# opens it in the default browser. Trial packaging only (digitva-33f8): no
# code signing, no OS keystore; the Tauri app replaces it.
# ponytail: browser launcher, swap for a Tauri window when packaging lands.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
repo="$(cd "$here/.." && pwd)"
app="$here/target/DigitVA.app"

(cd "$here" && OPENSSL_DIR="${OPENSSL_DIR:-/opt/homebrew/opt/openssl@3}" cargo build --release -p digitva-server)
[ -f "$repo/mobile/digitva-collect/dist/index.html" ] || {
  echo "Missing Expo web export: run 'npm run export:web' in mobile/digitva-collect" >&2
  exit 1
}

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$here/target/release/digitva-server" "$app/Contents/Resources/"
cp -R "$repo/mobile/digitva-collect/dist" "$app/Contents/Resources/web-dist"
cp -R "$repo/app/static" "$app/Contents/Resources/static"

cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>DigitVA</string>
  <key>CFBundleDisplayName</key><string>DigitVA Offline PHC</string>
  <key>CFBundleIdentifier</key><string>org.digitva.station</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleExecutable</key><string>DigitVA</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
</dict></plist>
PLIST

cat > "$app/Contents/MacOS/DigitVA" <<'LAUNCH'
#!/bin/bash
# Start the station (data in Application Support) and open it in the browser.
set +x
set -euo pipefail
umask 077
res="$(cd "$(dirname "$0")/../Resources" && pwd)"
data="$HOME/Library/Application Support/DigitVA"
mkdir -p "$data"
port="${DIGITVA_PORT:-18430}"
if [[ ! "$port" =~ ^[0-9]{1,5}$ ]] || (( 10#$port < 1 || 10#$port > 65535 )); then
  echo "Invalid DigitVA station port." >&2
  exit 1
fi
launch="$(mktemp -d "$data/.launch.XXXXXXXX")"
trap 'rm -f "$launch/ready"; rmdir "$launch"' EXIT
token="$(/usr/bin/openssl rand -hex 32)"
[[ "$token" =~ ^[0-9a-f]{64}$ ]] || exit 1
DIGITVA_DB_PATH="$data/digitva-offline-phc.sqlite" \
DIGITVA_WEB_DIST_DIR="$res/web-dist" \
DIGITVA_STATIC_DIR="$res/static" \
DIGITVA_LAUNCH_TOKEN="$token" \
DIGITVA_READY_FILE="$launch/ready" \
DIGITVA_PORT="$port" \
  "$res/digitva-server" >>"$data/station.log" 2>&1 &
pid=$!
for _ in $(seq 1 50); do
  [[ -f "$launch/ready" ]] && break
  kill -0 "$pid" 2>/dev/null || break
  sleep 0.2
done
if [[ ! -f "$launch/ready" ]] || ! kill -0 "$pid" 2>/dev/null; then
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  echo "DigitVA station did not start. Check station.log." >&2
  exit 1
fi
# Pass the fragment on stdin so the launch token stays out of process arguments.
if ! printf 'open location "http://127.0.0.1:%s/app/#digitva-launch=%s"\n' "$port" "$token" |
    /usr/bin/osascript >/dev/null 2>&1; then
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  echo "Could not open the DigitVA station in the browser." >&2
  exit 1
fi
unset token
wait "$pid"
LAUNCH
chmod +x "$app/Contents/MacOS/DigitVA"
echo "$app"
