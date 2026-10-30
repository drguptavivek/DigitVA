#!/usr/bin/env bash
# Phone vs WHO container parity run for the Collect Plus ICD-11 engine. Deterministic: every input is fixed
# (conditions.json, queries.json, make_certificates.py's hash-driven choices) and every binary is pinned by
# SHA-256, so two runs see identical bytes.
#
# Needs: a phone on adb (arm64, 6 GB or more), the Android NDK, gh, python3, the official WHO container on
# 127.0.0.1:8382 (docker compose up -d icd_api_service), and our earlier DORIS suite's tests/fixtures
# (ICD11-DORIS-kotlin-rust-source.zip, icd-offline-0.3, 2026-10-24) unpacked into SUITE_FIXTURES_DIR.
#
# Targeted run of a library built locally (engine-src/build.sh), without downloading the published archive: set ENGINE_SO to the
# built digitva_icd11.so, STAGED to a phone folder that an earlier run left (lib/ with libssl.so, libcrypto.so and libc++_shared.so,
# bundle_min/, data/), SUITE_FIXTURES_DIR to "-" and CERTIFICATES to a count (200 is enough to see a break); the 10,010 suite inputs are
# then left out. The comparison is the same.
#
# SUITE_FIXTURES_DIR may be the committed datasets/clinical-variants-10k. OURS=FILE.jsonl uses a prepared certificate file (as
# eval.sh does, from datasets/hash-synthetic-10k) instead of generating CERTIFICATES of them.
# Leaves in WORK_DIR: requests.tsv, phone.tsv, container.tsv, counts.txt (requests per section), summary.txt (compare.py's output) and
# provenance.env (engine and library sources); exits with compare.py's status. scripts/icd11-parity/eval.sh is the usual entry point.
#
# SECTIONS (third argument, optional) names the extra request sections build_inputs.py adds: golden, sweep or golden,sweep (eval.sh: quick
# golden, full golden,sweep). Without it the list is the earlier one (the certificates, the malformed requests, queries.json and calls.json).
#
# usage: [OURS=FILE.jsonl ENGINE_SO=... STAGED=/data/local/tmp/DIR CERTIFICATES=200] scripts/icd11-parity/run_phone.sh WORK_DIR SUITE_FIXTURES_DIR|- [SECTIONS]
set -euo pipefail
work=$1 suite=$2 sections=${3:-}
local_so="${ENGINE_SO:-}" staged="${STAGED:-}" certificates="${CERTIFICATES:-10000}" prepared="${OURS:+$(cd "$(dirname "$OURS")" && pwd)/$(basename "$OURS")}"
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
: > provenance.env
if [ -n "$local_so" ]; then
  : "${staged:?set STAGED with ENGINE_SO}"
  rm -rf lib && mkdir -p lib && cp "$local_so" lib/libdigitva_icd11.so
  printf 'ENGINE_LOCAL_SO_SHA256=%s\nSTAGED=%s\n' "$(shasum -a 256 lib/libdigitva_icd11.so | cut -d' ' -f1)" "$staged" >> provenance.env
else
gh release download "$engine_tag" -R drguptavivek/DigitVA -p "icd11-engine-${ICD11_ENGINE_VERSION}.tar.gz" --clobber
echo "$engine_sha  icd11-engine-${ICD11_ENGINE_VERSION}.tar.gz" | shasum -a 256 -c
gh release download "$plus_tag" -R drguptavivek/DigitVA -p "$plus_apk" --clobber
echo "$plus_sha  $plus_apk" | shasum -a 256 -c
rm -rf engine lib && mkdir -p engine lib
tar -xzf "icd11-engine-${ICD11_ENGINE_VERSION}.tar.gz" -C engine
unzip -q -j -o "$plus_apk" lib/arm64-v8a/libssl.so lib/arm64-v8a/libcrypto.so lib/arm64-v8a/libc++_shared.so -d lib
cp engine/bridge-aot/pub-bionic/digitva_icd11.so lib/libdigitva_icd11.so
printf 'ENGINE_TAG=%s\nENGINE_ARCHIVE_SHA256=%s\nLIBS_PLUS_TAG=%s\nLIBS_PLUS_APK=%s\nLIBS_PLUS_APK_SHA256=%s\n' \
  "$engine_tag" "$engine_sha" "$plus_tag" "$plus_apk" "$plus_sha" >> provenance.env
fi

if [ -n "$prepared" ]; then cp "$prepared" ours.jsonl; else python3 "$here/make_certificates.py" "$work/ours.jsonl" "$certificates"; fi
python3 "$here/build_inputs.py" "$work/requests.tsv" "$work/ours.jsonl" "$suite" "$sections" | tee counts.txt
"$clang" -O2 -Wall -o phone_harness "$here/phone_harness.c" -ldl

if [ -n "$local_so" ]; then
  adb shell "rm -rf $device && mkdir -p $device/lib && cp $staged/lib/libssl.so $staged/lib/libcrypto.so $staged/lib/libc++_shared.so $device/lib/ && cp -r $staged/bundle_min $staged/data $device/"
  adb push -q lib/libdigitva_icd11.so "$device/lib/"
  adb push -q phone_harness requests.tsv "$device/"
else
  adb shell "rm -rf $device && mkdir -p $device/lib"
  adb push -q lib/. "$device/lib/"
  adb push -q engine/bundle_min engine/data phone_harness requests.tsv "$device/"
fi
adb shell "cd $device && chmod 755 phone_harness && cp -r data work && \
  LD_LIBRARY_PATH=$device/lib HTTPS_PROXY=$proxy HTTP_PROXY=$proxy https_proxy=$proxy http_proxy=$proxy DOTNET_gcServer=0 \
  ./phone_harness $device/lib/libdigitva_icd11.so $device/bundle_min $device/work/ $device/requests.tsv > phone.tsv"
adb pull -q "$device/phone.tsv" phone.tsv

python3 "$here/run_container.py" requests.tsv container.tsv
python3 "$here/compare.py" phone.tsv container.tsv | tee summary.txt
