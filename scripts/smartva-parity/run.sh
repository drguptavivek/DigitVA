#!/usr/bin/env bash
# SmartVA parity run: the Collect Plus SmartVA engine on a phone vs the server's stored result for every case the dev
# server scored. Everything derived from a case stays under private/smartva-parity/ (git-ignored); only the aggregate
# summary.txt and run.json are written to scripts/smartva-parity/results/<date>-<platform>/.
#
#   scripts/smartva-parity/run.sh corpus    export the cases from the dev DB (read-only) into private/smartva-parity/corpus
#   scripts/smartva-parity/run.sh ios       run on the iOS Simulator (SIM_UDID, default the iPhone 17 below)
#   scripts/smartva-parity/run.sh android   run on the adb phone (ANDROID_SERIAL as usual), in /data/local/tmp/smartva-parity,
#                                           removed afterwards
# COMPARE_ONLY=1 skips the device run and compares the replies already in private/smartva-parity/runs/<date>-<platform>/
# (HOST_NOTE then records the phone's load during that run).
# corpus also rescores every case with the server's current engine (rescore_server.py, nothing stored).
# A platform run compares with the server (stored results, then the current engine) and, when the other platform has replies of the same date, with them byte
# for byte. Exits with compare.py's status.
#
# Libraries: Android private/generated/smartva-android/arm64-v8a/libsmartva_rust.so (scripts/build-smartva-android.sh,
# the file stage-engine.js copies into the app); iOS the ios-arm64-simulator slice of
# private/generated/smartva-ios/SmartvaRust.xcframework (scripts/build-smartva-ios.sh).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
private="$repo/private/smartva-parity"
corpus="$private/corpus"
day="$(date -u +%Y-%m-%d)"
platform=${1:?usage: run.sh corpus|ios|android}
sim=${SIM_UDID:-12536057-9452-418C-AFEE-5DFDD85CE2CC}
android_lib="$repo/private/generated/smartva-android/arm64-v8a/libsmartva_rust.so"
ios_lib="$repo/private/generated/smartva-ios/SmartvaRust.xcframework/ios-arm64-simulator/libsmartva_rust.a"
ndk="${ANDROID_NDK:-$HOME/Library/Android/sdk/ndk/28.2.13676358}/toolchains/llvm/prebuilt/$(uname | tr '[:upper:]' '[:lower:]')-x86_64/bin"
device=/data/local/tmp/smartva-parity
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }

git -C "$repo" check-ignore -q "$private" || { echo "private/smartva-parity is not git-ignored" >&2; exit 2; }

if [ "$platform" = corpus ]; then
  # The app's own input.ts, compiled; the raw payloads go through the pipe only.
  rm -rf "$private/build" "$corpus"
  "$repo/mobile/digitva-collect/node_modules/.bin/tsc" "$repo/mobile/digitva-collect/src/smartva/input.ts" \
    --outDir "$private/build" --rootDir "$repo/mobile/digitva-collect/src" --module commonjs --target es2022 --skipLibCheck
  (cd "$repo" && docker compose exec -T minerva_app_service uv run --no-sync python scripts/smartva-parity/export.py) \
    | INPUT_JS="$private/build/smartva/input.js" node "$here/build_requests.js" "$corpus"
  # The same cases through the server's pipeline and current engine, nothing stored: tells an older stored engine apart.
  (cd "$repo" && docker compose exec -T minerva_app_service uv run --no-sync python scripts/smartva-parity/rescore_server.py \
    /app/private/smartva-parity/corpus)
  exit 0
fi

[ -f "$corpus/requests.tsv" ] || { echo "no corpus: run.sh corpus first" >&2; exit 2; }
run="$private/runs/$day-$platform"
results="$here/results/$day-$platform"
mkdir -p "$run" "$results"
case "$platform" in
  ios)
    other=android
    lib="$ios_lib"
    # -dead_strip as Xcode links the app (DEAD_CODE_STRIPPING): without it ld refuses the slice's duplicate symbols.
    xcrun --sdk iphonesimulator clang -target arm64-apple-ios16.4-simulator -O2 -Wall -o "$run/harness" \
      "$here/harness.c" "$lib" -framework CoreFoundation -Wl,-dead_strip 2>/dev/null
    device_model="$(xcrun simctl list devices | sed -n "s/^ *\(.*\) ($sim) .*/\1/p") simulator"
    device_os="$(xcrun simctl list devices -j | SIM="$sim" python3 -c 'import json, os, sys
print(next(k.rsplit(".", 1)[-1] for k, v in json.load(sys.stdin)["devices"].items() for d in v if d["udid"] == os.environ["SIM"]))')"
    host="$(sysctl -n machdep.cpu.brand_string)"
    if [ -z "${COMPARE_ONLY:-}" ]; then
      xcrun simctl spawn "$sim" "$run/harness" "$corpus/requests.tsv" > "$run/replies.tsv"
      # The app cleaner's own spelling of the same cases (requests-phone.tsv), on the fast platform only.
      xcrun simctl spawn "$sim" "$run/harness" "$corpus/requests-phone.tsv" > "$run/replies-phone.tsv"
    fi
    ;;
  android)
    other=ios
    lib="$android_lib"
    "$ndk/aarch64-linux-android33-clang" -O2 -Wall -o "$run/harness" "$here/harness.c" -L"$(dirname "$lib")" -lsmartva_rust
    device_model="$(adb shell getprop ro.product.model | tr -d '\r')"
    device_os="Android $(adb shell getprop ro.build.version.release | tr -d '\r') (API $(adb shell getprop ro.build.version.sdk | tr -d '\r'))"
    host="${HOST_NOTE:-load average before the run: $(adb shell cat /proc/loadavg | tr -d '\r')}"
    if [ -z "${COMPARE_ONLY:-}" ]; then
      trap 'adb shell "rm -rf $device"' EXIT
      adb shell "rm -rf $device && mkdir -p $device"
      adb push -q "$run/harness" "$lib" "$corpus/requests.tsv" "$device/"
      adb shell "cd $device && chmod 755 harness && LD_LIBRARY_PATH=$device ./harness $device/requests.tsv > replies.tsv"
      adb pull -q "$device/replies.tsv" "$run/replies.tsv"
    fi
    ;;
  *) echo "usage: run.sh corpus|ios|android" >&2; exit 2 ;;
esac

other_args=()
[ -f "$private/runs/$day-$other/replies.tsv" ] && other_args=(--other "$private/runs/$day-$other/replies.tsv")
# Two comparisons (three on iOS), one summary: with the stored results, and with the server's current engine (rescore_server.py).
status=0
python3 "$here/compare.py" "$corpus" "$run/replies.tsv" ${other_args[@]+"${other_args[@]}"} --label "$platform" \
  --examples "$run/mismatch-examples.jsonl" --stats "$run/stats.json" > "$results/summary.txt" || status=1
printf '\n----\n\n' >> "$results/summary.txt"
python3 "$here/compare.py" "$corpus" "$run/replies.tsv" --expected "$corpus/server-now.jsonl" --label "$platform" \
  --examples "$run/mismatch-examples-now.jsonl" --stats "$run/stats-now.json" >> "$results/summary.txt" || status=1
if [ -f "$run/replies-phone.tsv" ]; then
  # Not part of the verdict: shows what the app cleaner's number spelling ("5" for the payload's 5.0) does to a result.
  printf '\n----\n\napp-cleaned input (requests-phone.tsv), informational, not in the exit status:\n' >> "$results/summary.txt"
  python3 "$here/compare.py" "$corpus" "$run/replies-phone.tsv" --expected "$corpus/server-now.jsonl" \
    --other "$run/replies.tsv" --label "$platform, app-cleaned input" --examples "$run/mismatch-examples-app-cleaned.jsonl" \
    >> "$results/summary.txt" || true
fi
cat "$results/summary.txt"

commit="$(git -C "$repo" rev-parse HEAD)"
dirty="$(git -C "$repo" status --porcelain -- scripts/smartva-parity | grep -q . && echo true || echo false)"
RUN="$run" PLATFORM="$platform" MODEL="$device_model" OS="$device_os" HOST="$host" LIB_SHA="$(sha "$lib")" \
  LIB="${lib#"$repo/"}" REQ_SHA="$(sha "$corpus/requests.tsv")" EXP_SHA="$(sha "$corpus/expected.jsonl")" NOW_SHA="$(sha "$corpus/server-now.jsonl")" \
  COMMIT="$commit" DIRTY="$dirty" STATUS="$status" python3 - > "$results/run.json" <<'EOF'
import json, os
from datetime import datetime, timezone
e = os.environ
stats = json.load(open(os.path.join(e["RUN"], "stats.json")))
stats["vs_server_current_engine"] = json.load(open(os.path.join(e["RUN"], "stats-now.json")))
print(json.dumps({
    "date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "platform": e["PLATFORM"],
    "device": e["MODEL"], "os": e["OS"], "host": e["HOST"],
    "library": e["LIB"], "library_sha256": e["LIB_SHA"],
    "corpus_requests_sha256": e["REQ_SHA"], "corpus_expected_sha256": e["EXP_SHA"],
    "corpus_server_now_sha256": e["NOW_SHA"],
    "kit_commit": e["COMMIT"], "kit_dirty": e["DIRTY"] == "true", "compare_exit": int(e["STATUS"]), **stats,
}, indent=1))
EOF
exit "$status"
