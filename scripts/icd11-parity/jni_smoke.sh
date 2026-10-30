#!/usr/bin/env bash
# JNI smoke check of the Collect Plus shim on a phone over adb, without an APK (see jni_smoke.c for what it checks).
# Compiles shim.c unchanged into libdigitvaicd11shim.so and jni_smoke.c with the Android NDK, then runs the shim's JNI functions
# against each engine library given: the old pinned one (no digitva_icd11_call), which load must refuse with 3, and the new one, which must pass every check. Nothing is installed or cleared:
# everything lives under /data/local/tmp/icd11-jni-smoke, which this script recreates.
#
# Engine libraries are 130-150 MB: a value starting with /data/ is a path already on the phone, anything else a local file that is pushed.
# STAGED is a phone folder from an earlier run_phone.sh with lib/ (libssl.so, libcrypto.so, libc++_shared.so), bundle_min/ and data/.
#
# usage: ENGINE_OLD=/data/local/tmp/DIR/lib/libdigitva_icd11.so ENGINE_NEW=/path/or/phone/libdigitva_icd11.so STAGED=/data/local/tmp/DIR \
#        scripts/icd11-parity/jni_smoke.sh WORK_DIR
# Exit status: 0 when every check of every library passed.
set -euo pipefail
work=$1
: "${ENGINE_OLD:?}" "${ENGINE_NEW:?}" "${STAGED:?}"
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
ndk="${ANDROID_NDK:-$HOME/Library/Android/sdk/ndk/28.2.13676358}"
clang="$ndk/toolchains/llvm/prebuilt/$(uname | tr '[:upper:]' '[:lower:]')-x86_64/bin/aarch64-linux-android29-clang"
device=/data/local/tmp/icd11-jni-smoke
proxy=http://127.0.0.1:9   # nothing listens here: the engine's start-up downloads fail fast, as in the app

mkdir -p "$work"
"$clang" -shared -fPIC -O2 -Wall -Wl,-z,max-page-size=16384 -o "$work/libdigitvaicd11shim.so" \
  "$repo/mobile/digitva-collect/modules/digitva-icd11/android/src/main/cpp/shim.c" -ldl
"$clang" -O2 -Wall -o "$work/jni_smoke" "$here/jni_smoke.c" -ldl

adb shell "rm -rf $device && mkdir -p $device"
adb push -q "$work/libdigitvaicd11shim.so" "$work/jni_smoke" "$device/"
adb shell "chmod 755 $device/jni_smoke"

status=0
run() {  # name engine expect_load (0 accepted, 3 refused)
  local name=$1 engine=$2 expect=$3 lib
  case "$engine" in /data/*) lib=$engine ;; *) adb push -q "$engine" "$device/$name.so"; lib=$device/$name.so ;; esac
  # A fresh copy of the data for each library: the engine writes derived files into it.
  adb shell "rm -rf $device/data_$name && cp -r $STAGED/data $device/data_$name"
  echo "=== $name: $engine (load expected to return $expect)"
  adb shell "cd $device && LD_LIBRARY_PATH=$STAGED/lib HTTPS_PROXY=$proxy HTTP_PROXY=$proxy https_proxy=$proxy http_proxy=$proxy DOTNET_gcServer=0 \
    ./jni_smoke $device/libdigitvaicd11shim.so $lib $STAGED/bundle_min $device/data_$name/ $expect > $device/$name.out 2> $device/$name.err; echo exit=\$? >> $device/$name.out" || true
  adb pull -q "$device/$name.out" "$work/$name.out"
  adb pull -q "$device/$name.err" "$work/$name.err"
  cat "$work/$name.out"
  # The engine's error text for the bad directories names them; none of it may reach the process's output.
  # grep on the files themselves: a pipe would let grep -q's early exit SIGPIPE cat and, under pipefail, read as "no match".
  if grep -q 'no_such_bundle_dir_zz\|no_such_data_dir_zz' "$work/$name.out" "$work/$name.err"; then
    echo "FAIL $name: engine error text reached stdout or stderr"; status=1
  else
    echo "ok $name: no engine error text on stdout or stderr"
  fi
  grep -q '^PASS' "$work/$name.out" || status=1
}
run old "$ENGINE_OLD" 3
run new "$ENGINE_NEW" 0
exit $status
