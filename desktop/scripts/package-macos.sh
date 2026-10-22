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
res="$(cd "$(dirname "$0")/../Resources" && pwd)"
data="$HOME/Library/Application Support/DigitVA"
mkdir -p "$data"
port="${DIGITVA_PORT:-18430}"
url="http://127.0.0.1:$port/app/"
if curl -fs -o /dev/null "$url"; then open "$url"; exit 0; fi
DIGITVA_DB_PATH="$data/digitva-offline-phc.sqlite" \
DIGITVA_WEB_DIST_DIR="$res/web-dist" \
DIGITVA_PORT="$port" \
  "$res/digitva-server" >>"$data/station.log" 2>&1 &
pid=$!
for _ in $(seq 1 50); do curl -fs -o /dev/null "$url" && break; sleep 0.2; done
open "$url"
wait "$pid"
LAUNCH
chmod +x "$app/Contents/MacOS/DigitVA"
echo "$app"
