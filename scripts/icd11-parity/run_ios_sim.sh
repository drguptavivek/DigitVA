#!/usr/bin/env bash
# iOS Simulator twin of run_phone.sh: the same request list (build_inputs.py), the same harness (phone_harness.c, built for
# arm64-apple-ios-simulator) and the same container and compare steps, against the iOS engine DigitvaIcd11Engine.xcframework
# (engine-src/build-ios.sh). The harness runs inside the booted simulator through `xcrun simctl spawn`; simulator processes see the host
# filesystem, so the work directory is used in place. No app is installed and no app data is touched.
#
# Engine and data come from the spike folder, as stage-engine.js --ios stages them for the app: the ios-arm64-simulator slice of the
# xcframework and exactly the files engineFiles() lists (bundle_min/, the two WHO tables and DORIS's files). IOS_XCFRAMEWORK and
# ENGINE_DATA override the two. The data folder is a fresh copy per run (the engine writes derived files into it), TMPDIR points into it
# and the four proxy variables are the dead proxy, as EngineHost.swift sets them.
#
# Leaves in WORK_DIR what run_phone.sh leaves (requests.tsv, phone.tsv, container.tsv, counts.txt, summary.txt, provenance.env);
# exits with compare.py's status. Usual entry point: IOS_SIM=<udid> scripts/icd11-parity/eval.sh quick|full.
#
# usage: IOS_SIM=<udid> [OURS=FILE.jsonl CERTIFICATES=200 IOS_XCFRAMEWORK=... ENGINE_DATA=<spike dir>] run_ios_sim.sh WORK_DIR SUITE_FIXTURES_DIR|- [SECTIONS]
set -euo pipefail
work=$1 suite=$2 sections=${3:-}
udid=${IOS_SIM:?set IOS_SIM to a booted simulator UDID}
certificates="${CERTIFICATES:-10000}" prepared="${OURS:+$(cd "$(dirname "$OURS")" && pwd)/$(basename "$OURS")}"
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
spike="${ENGINE_DATA:-$repo/private/icd11-offline-spike}"
xcf="${IOS_XCFRAMEWORK:-$spike/bridge-aot/pub-ios/DigitvaIcd11Engine.xcframework}"
lib="$xcf/ios-arm64-simulator/DigitvaIcd11Engine.framework/DigitvaIcd11Engine"
proxy=http://127.0.0.1:9   # nothing listens here: the engine's start-up downloads fail fast, as in the app
[ -f "$lib" ] || { echo "no simulator slice at $lib" >&2; exit 2; }

mkdir -p "$work"
work="$(cd "$work" && pwd)"
cd "$work"
rm -rf engine && mkdir -p engine
node "$repo/mobile/digitva-collect/modules/digitva-icd11/scripts/stage-engine.js" --list "$spike" | grep -v '^bridge-aot/' |
  while IFS= read -r f; do mkdir -p "engine/$(dirname "$f")"; cp "$spike/$f" "engine/$f"; done
data_sha="$(cd engine && find bundle_min data -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256 | shasum -a 256 | cut -d' ' -f1)"
cp -R engine/data engine/work
read -r sim_model sim_runtime < <(xcrun simctl list devices -j | UDID="$udid" python3 -c '
import json, os, sys
for runtime, devices in json.load(sys.stdin)["devices"].items():
    for d in devices:
        if d["udid"] == os.environ["UDID"]:
            if d["state"] != "Booted": sys.exit("simulator is not booted")
            print(d["name"].replace(" ", "_"), runtime.rsplit(".", 1)[-1])
            sys.exit(0)
sys.exit("simulator not found")')
printf 'IOS_SIM_UDID=%s\nIOS_SIM_MODEL=%s\nIOS_SIM_RUNTIME=%s\nIOS_XCFRAMEWORK=%s\nIOS_FRAMEWORK_SHA256=%s\nENGINE_DATA=%s\nENGINE_DATA_SHA256=%s\n' \
  "$udid" "${sim_model//_/ }" "$sim_runtime" "$xcf" "$(shasum -a 256 "$lib" | cut -d' ' -f1)" "$spike" "$data_sha" > provenance.env

if [ -n "$prepared" ]; then cp "$prepared" ours.jsonl; else python3 "$here/make_certificates.py" "$work/ours.jsonl" "$certificates"; fi
python3 "$here/build_inputs.py" "$work/requests.tsv" "$work/ours.jsonl" "$suite" "$sections" | tee counts.txt
xcrun --sdk iphonesimulator clang -target arm64-apple-ios15.1-simulator -O2 -Wall -o phone_harness "$here/phone_harness.c"

SIMCTL_CHILD_TMPDIR="$work/engine/work/" SIMCTL_CHILD_DOTNET_gcServer=0 \
SIMCTL_CHILD_HTTPS_PROXY=$proxy SIMCTL_CHILD_HTTP_PROXY=$proxy SIMCTL_CHILD_https_proxy=$proxy SIMCTL_CHILD_http_proxy=$proxy \
  xcrun simctl spawn "$udid" "$work/phone_harness" "$lib" "$work/engine/bundle_min" "$work/engine/work/" "$work/requests.tsv" > phone.tsv

python3 "$here/run_container.py" requests.tsv container.tsv
python3 "$here/compare.py" phone.tsv container.tsv | tee summary.txt
