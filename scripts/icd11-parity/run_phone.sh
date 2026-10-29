#!/usr/bin/env bash
# Phone vs WHO container parity run for the Collect Plus ICD-11 engine. Deterministic: every input is fixed
# (conditions.json, queries.json, make_certificates.py's hash-driven choices) and every binary is pinned by
# SHA-256, so two runs see identical bytes.
#
# Needs: a phone on adb (arm64, 6 GB or more), the Android NDK, gh, python3, the official WHO container on
# 127.0.0.1:8382 (docker compose up -d icd_api_service), and our earlier DORIS suite's tests/fixtures
# (ICD11-DORIS-kotlin-rust-source.zip, icd-offline-0.3, 2026-10-24) unpacked into SUITE_FIXTURES_DIR.
#
# usage: scripts/icd11-parity/run_phone.sh WORK_DIR SUITE_FIXTURES_DIR
set -euo pipefail
work=$1 suite=$2
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
# shellcheck source=../icd11-engine.env
. "$repo/scripts/icd11-engine.env"
engine_tag="icd11-engine-v${ICD11_ENGINE_VERSION}"
engine_sha="$(sed -n 's/^ *ICD11_ENGINE_SHA256: *//p' "$repo/.github/workflows/collect-plus-release.yml" | tr -d '"' | head -n 1)"
# The engine runs with the OpenSSL the app ships; take it from the published Plus APK.
plus_tag="collect-plus-v0.3.14-plus.1"
plus_apk="digitva-collect-plus-0.3.14-arm64-v8a.apk"
plus_sha="a6fc8a2b5b4e2869dbcb7adab5c28dad864d703039823698674d177b4596e41c"
ndk="${ANDROID_NDK:-$HOME/Library/Android/sdk/ndk/28.2.13676358}"
clang="$ndk/toolchains/llvm/prebuilt/$(uname | tr '[:upper:]' '[:lower:]')-x86_64/bin/aarch64-linux-android29-clang"
device=/data/local/tmp/icd11-parity
proxy=http://127.0.0.1:9   # nothing listens here: the engine's start-up downloads fail fast, as in the app

mkdir -p "$work"
cd "$work"
gh release download "$engine_tag" -R drguptavivek/DigitVA -p "icd11-engine-${ICD11_ENGINE_VERSION}.tar.gz" --clobber
echo "$engine_sha  icd11-engine-${ICD11_ENGINE_VERSION}.tar.gz" | shasum -a 256 -c
gh release download "$plus_tag" -R drguptavivek/DigitVA -p "$plus_apk" --clobber
echo "$plus_sha  $plus_apk" | shasum -a 256 -c
rm -rf engine lib && mkdir -p engine lib
tar -xzf "icd11-engine-${ICD11_ENGINE_VERSION}.tar.gz" -C engine
unzip -q -j -o "$plus_apk" lib/arm64-v8a/libssl.so lib/arm64-v8a/libcrypto.so lib/arm64-v8a/libc++_shared.so -d lib
cp engine/bridge-aot/pub-bionic/digitva_icd11.so lib/libdigitva_icd11.so

python3 "$here/make_certificates.py" "$work/ours.jsonl"
python3 "$here/build_inputs.py" "$work/requests.tsv" "$work/ours.jsonl" "$suite"
"$clang" -O2 -Wall -o phone_harness "$here/phone_harness.c" -ldl

adb shell "rm -rf $device && mkdir -p $device/lib"
adb push -q lib/. "$device/lib/"
adb push -q engine/bundle_min engine/data phone_harness requests.tsv "$device/"
adb shell "cd $device && chmod 755 phone_harness && cp -r data work && \
  LD_LIBRARY_PATH=$device/lib HTTPS_PROXY=$proxy HTTP_PROXY=$proxy https_proxy=$proxy http_proxy=$proxy DOTNET_gcServer=0 \
  ./phone_harness $device/lib/libdigitva_icd11.so $device/bundle_min $device/work/ $device/requests.tsv > phone.tsv"
adb pull -q "$device/phone.tsv" phone.tsv

python3 "$here/run_container.py" requests.tsv container.tsv
python3 "$here/compare.py" phone.tsv container.tsv
