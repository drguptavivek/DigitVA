#!/usr/bin/env bash
set -euo pipefail

MOBILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "$MOBILE_DIR/../.." && pwd)"
SDK_DIR="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}}"
APK="$MOBILE_DIR/android/app/build/outputs/apk/debug/app-arm64-v8a-debug.apk"
PACKAGE="com.causeofdeathindia.digitvacollect.plus"
AVD="${2:-DigitVA_Pixel_7}"

usage() {
  cat <<'EOF'
Local Android Plus debug build and Metro helper (no release or upload modes).

Usage:
  scripts/android-debug-hmr.sh build              Build the arm64 Plus debug APK
  scripts/android-debug-hmr.sh install [AVD]       Install on a booted AVD with app data preserved
  scripts/android-debug-hmr.sh reverse             Map device port 8081 to host port 8082
  scripts/android-debug-hmr.sh launch              Open the installed Plus app
  scripts/android-debug-hmr.sh metro               Start Docker Metro on host port 8082 in the foreground

Start Metro, then launch the app in another terminal. The app accepts the local
emulator backend at http://10.0.2.2:8051 through a local enrolment payload.
EOF
}

connected_device() {
  local devices
  devices="$("$SDK_DIR/platform-tools/adb" devices | awk 'NR > 1 && $2 == "device" { print $1 }')"
  if [[ -z "$devices" || "$devices" == *$'\n'* ]]; then
    echo "Expected exactly one connected Android device; found: ${devices:-none}" >&2
    return 1
  fi
  printf '%s\n' "$devices"
}

case "${1:-help}" in
  help|-h|--help)
    usage
    ;;
  build)
    cd "$MOBILE_DIR"
    APP_VARIANT=plus npx expo prebuild --platform android --clean --no-install
    (cd android && APP_VARIANT=plus ./gradlew assembleDebug -PreactNativeArchitectures=arm64-v8a)
    printf 'Built %s\n' "$APK"
    ;;
  install)
    ADB="$SDK_DIR/platform-tools/adb"
    if [[ ! -f "$APK" ]]; then
      echo "Debug APK not found; run '$0 build' first." >&2
      exit 1
    fi
    if ! "$ADB" devices | awk 'NR > 1 && $2 == "device" { found = 1 } END { exit !found }'; then
      if ! "$SDK_DIR/emulator/emulator" -list-avds | grep -Fxq "$AVD"; then
        echo "AVD '$AVD' is not installed." >&2
        exit 1
      fi
      echo "Boot '$AVD' in a separate terminal first: $SDK_DIR/emulator/emulator -avd $AVD" >&2
      exit 1
    fi
    DEVICE="$(connected_device)"
    for _ in {1..60}; do
      [[ "$("$ADB" -s "$DEVICE" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]] && break
      sleep 2
    done
    if [[ "$("$ADB" -s "$DEVICE" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" != "1" ]]; then
      echo "Android emulator did not finish booting." >&2
      exit 1
    fi
    ABI="$("$ADB" -s "$DEVICE" shell getprop ro.product.cpu.abi | tr -d '\r')"
    if [[ "$ABI" != "arm64-v8a" ]]; then
      echo "Plus includes the ICD engine for arm64-v8a; connected device reports $ABI." >&2
      exit 1
    fi
    "$ADB" -s "$DEVICE" install -r "$APK"
    printf 'Installed %s on %s (%s); existing app data was preserved.\n' "$PACKAGE" "$DEVICE" "$ABI"
    ;;
  reverse)
    ADB="$SDK_DIR/platform-tools/adb"
    DEVICE="$(connected_device)"
    "$ADB" -s "$DEVICE" reverse tcp:8081 tcp:8082
    printf 'Device %s localhost:8081 now reaches host Metro on port 8082.\n' "$DEVICE"
    ;;
  launch)
    ADB="$SDK_DIR/platform-tools/adb"
    DEVICE="$(connected_device)"
    "$ADB" -s "$DEVICE" shell monkey -p "$PACKAGE" 1
    ;;
  metro)
    cd "$REPO_DIR"
    exec docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.hmr.yml \
      run --rm --no-deps -p 127.0.0.1:8082:8082 digitva_web_hmr \
      ./node_modules/.bin/expo start --port 8082 --host lan
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
