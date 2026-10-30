#!/usr/bin/env bash
# Runs INSIDE the toolchain container (run.sh starts it) or, with NATIVE_BUILD=1, directly on the host (run.sh NATIVE=1):
# the Collect Plus arm64 release APK from code and WHO's public
# inputs only, following .github/workflows/collect-plus-release.yml (app steps) and icd11-engine-build.yml (engine steps).
# LOCAL VERIFICATION BUILD, NOT FOR DISTRIBUTION: release APKs come only from CI (owner rule). Without
# DIGITVA_ANDROID_RELEASE_BUILD=1 the APK is signed with the Expo template's debug key, never the release key.
# Paths default to the container's mounts and are overridable so the same script runs on the host: SRC_DIR (source, never
# written), ICDAPI_DIR (WHO's /usr/share/icdapi), CACHE_DIR (WHO downloads in $CACHE_DIR/who, sha-checked every run), OUT_DIR
# (results), WORK_DIR (scratch, emptied on start). Env: SRC_MODE SRC_REF SRC_COMMIT SRC_DIRTY (provenance), SKIP_CHECKS=1 (skip
# typecheck + tests), HOST_UID HOST_GID (owner of the output files), NATIVE_BUILD=1 (host run: ANDROID_HOME, JAVA_HOME and the
# tools are the caller's, and SOURCE.txt records them).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR=${SRC_DIR:-/src}; ICDAPI_DIR=${ICDAPI_DIR:-/icdapi}; CACHE_DIR=${CACHE_DIR:-/cache}; OUT_DIR=${OUT_DIR:-/out}
W=${WORK_DIR:-/work}; R=$W/src; S=$W/engine   # S has the layout stage-engine.js reads (same as private/icd11-offline-spike)
step() { echo; echo "=== $(date -u +%H:%M:%S) (+${SECONDS}s) $*"; }
command -v sha256sum >/dev/null || sha256sum() { shasum -a 256 "$@"; }   # macOS
rm -rf "$W"; mkdir -p "$W" "$OUT_DIR" "$CACHE_DIR/who"

step "1 source (copy to the container's own disk: bind mounts are slow for node_modules and Gradle)"
mkdir -p "$R" && cp -a "$SRC_DIR/." "$R/"
cd "$R"
# shellcheck source=pins.sh
. "$here/pins.sh"
require_pins "$R"
NDK_VERSION=$(pin_ndk "$R")
ENGINE_SRC=mobile/digitva-collect/modules/digitva-icd11/engine-src
export ANDROID_NDK="${ANDROID_NDK:-$ANDROID_HOME/ndk/$NDK_VERSION}" ANDROID_NDK_HOME="${ANDROID_NDK:-$ANDROID_HOME/ndk/$NDK_VERSION}"
# ANDROID_HOME can be a cache volume seeded from the image; reinstall if the pin moved since (the host's SDK is run.sh's check).
[[ -d "$ANDROID_NDK" || ${NATIVE_BUILD:-} == 1 ]] || "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" "ndk;$NDK_VERSION" >/dev/null
ndk_host=$(uname -s | tr '[:upper:]' '[:lower:]')-x86_64   # the NDK ships x86_64 prebuilts only (runs under Rosetta on a Mac)
for f in ICD-API.dll DorisRuleEngine.dll OCT.dll appsettings.json appsettings.container.json Data/languageResources.txt; do
  [[ -s $ICDAPI_DIR/$f ]] || { echo "WHO assembly folder lacks $f" >&2; exit 1; }
done

step "2 compile the engine (.NET NativeAOT, linux-bionic-arm64)"
dotnet --version
ICDAPI_DIR="$ICDAPI_DIR" "$ENGINE_SRC/build.sh" "$W/engine-out"
# build.sh regenerates rd_gen.xml; CI fails when it differs from the commit.
rd_status=same
cmp -s "$SRC_DIR/$ENGINE_SRC/rd_gen.xml" "$ENGINE_SRC/rd_gen.xml" || { rd_status=DIFFERS; echo "WARNING: regenerated rd_gen.xml differs from the source's; commit it (CI would fail)" >&2; }

step "3 WHO data (cached in the volume, sha256-checked every run)"
mkdir -p "$S/data/DORIS_v2.1_1.2.0" "$S/bundle_min/Data" "$S/bridge-aot/pub-bionic"
pin_who_data_sums "$R" > "$W/data.sums"
doris_sha=$(pin_doris_zip_sha "$R")
fetch_checked() {   # URL DEST EXPECTED_SHA256: use the cached copy only if it matches, else download and require a match
  if [[ -f $2 ]] && echo "$3  $2" | sha256sum -c - >/dev/null 2>&1; then echo "cached: $(basename "$2")"; return; fi
  curl --fail --silent --show-error --location --retry 3 --output "$2" "$1"
  echo "$3  $2" | sha256sum -c -
}
while read -r url; do
  name=$(basename "$url")
  case $name in
    DORIS_*.zip) fetch_checked "$url" "$CACHE_DIR/who/$name" "$doris_sha"
                 unzip -q -o "$CACHE_DIR/who/$name" -d "$S/data/DORIS_v2.1_1.2.0" ;;
    *)           want=$(awk -v f="$name" '$2 == f {print $1}' "$W/data.sums")
                 [[ -n $want ]] || { echo "no pinned sha256 for $name" >&2; exit 1; }
                 fetch_checked "$url" "$CACHE_DIR/who/$name" "$want"
                 cp "$CACHE_DIR/who/$name" "$S/data/$name" ;;
  esac
done < <(pin_who_urls "$R")
(cd "$S/data" && sha256sum -c "$W/data.sums")
cp "$ICDAPI_DIR/appsettings.json" "$ICDAPI_DIR/appsettings.container.json" "$S/bundle_min/"
cp "$ICDAPI_DIR/Data/languageResources.txt" "$S/bundle_min/Data/"
cp "$W/engine-out/digitva_icd11.so" "$S/bridge-aot/pub-bionic/"

step "4 WHO form package (pnpm), app dependencies, checks"
pnpm --dir vendor/who-va-2022 install --frozen-lockfile >/dev/null
pnpm --dir vendor/who-va-2022 run build >/dev/null
cd mobile/digitva-collect
npm ci --no-audit --no-fund >/dev/null
if [[ ${SKIP_CHECKS:-} != 1 ]]; then
  npm run typecheck
  npm test -- --runInBand
fi
cd "$R"

step "5 SmartVA scoring library (Rust, aarch64-linux-android)"
RUSTUP_TOOLCHAIN=stable scripts/build-smartva-android.sh

step "6 Android project (expo prebuild, APP_VARIANT=plus)"
cd mobile/digitva-collect
export DIGITVA_ICD11_SPIKE_DIR=$S APP_VARIANT=plus
npx expo prebuild --platform android --clean --non-interactive
# The shim refuses a library without these exports (same check as the release workflow).
lib=modules/digitva-icd11/android/src/main/jniLibs/arm64-v8a/libdigitva_icd11.so
nm="$ANDROID_NDK/toolchains/llvm/prebuilt/$ndk_host/bin/llvm-nm"
[[ -s $lib ]] || { echo "staged engine library missing: $lib" >&2; exit 1; }
symbols=$("$nm" -D --defined-only "$lib")
for symbol in digitva_icd11_init digitva_icd11_call digitva_icd11_free; do
  grep -Eq " T ${symbol}(@.*)?\$" <<<"$symbols" || { echo "the staged engine does not export $symbol" >&2; exit 1; }
done

step "7 Gradle: module unit tests, then the arm64 release APK"
cd android
[[ ${SKIP_CHECKS:-} == 1 ]] || ./gradlew --no-daemon :digitva-icd11:testReleaseUnitTest
./gradlew --no-daemon clean assembleRelease

step "8 results"
version=$(node -p "require('../app.json').expo.version")
apk=app/build/outputs/apk/release/app-arm64-v8a-release.apk
out_apk="digitva-collect-plus-${version}-arm64-v8a-LOCAL.apk"
rm -f "$OUT_DIR"/*.apk "$OUT_DIR"/digitva_icd11.so "$OUT_DIR"/SHA256SUMS "$OUT_DIR"/SOURCE.txt "$OUT_DIR"/SIGNER.txt
cp "$apk" "$OUT_DIR/$out_apk"
cp "$W/engine-out/digitva_icd11.so" "$OUT_DIR/"
apksigner=$(ls -d "$ANDROID_HOME"/build-tools/*/apksigner 2>/dev/null | sort -V | tail -1 || true)
if [[ -n $apksigner ]]; then "$apksigner" verify --print-certs "$apk" > "$OUT_DIR/SIGNER.txt" 2>&1 || true; else echo "apksigner not found" > "$OUT_DIR/SIGNER.txt"; fi
{
  echo "mode: $SRC_MODE${SRC_REF:+ ($SRC_REF)}"
  echo "commit: $SRC_COMMIT"
  echo "dirty: $SRC_DIRTY"
  echo "rd_gen.xml: $rd_status"
  echo "built: $(date -u +%FT%TZ)"
  if [[ ${NATIVE_BUILD:-} == 1 ]]; then   # not the pinned image: record what built it
    echo "build: native, not pinned like the container image; engine bytes differ from a Linux build"
    echo "host: $(uname -srm)"
    echo "node: $(node -v); pnpm: $(pnpm --version); npm: $(npm -v)"
    echo "java: $("${JAVA_HOME:+$JAVA_HOME/bin/}java" -version 2>&1 | head -1)"
    echo "dotnet: $(cd "$R/$ENGINE_SRC" && dotnet --version); ndk: $(basename "$ANDROID_NDK")"
    echo "rustc: $(RUSTUP_TOOLCHAIN=stable rustc --version); cargo: $(RUSTUP_TOOLCHAIN=stable cargo --version)"
    echo "apksigner: ${apksigner:-none}"
  fi
} > "$OUT_DIR/SOURCE.txt"
(cd "$OUT_DIR" && sha256sum "$out_apk" digitva_icd11.so > SHA256SUMS)
[[ -z ${HOST_UID:-} ]] || chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" "$OUT_DIR"
cat "$OUT_DIR/SHA256SUMS" "$OUT_DIR/SOURCE.txt"
echo "signer:"; grep -E "^Signer #1 certificate (DN|SHA-256)" "$OUT_DIR/SIGNER.txt" || cat "$OUT_DIR/SIGNER.txt"
echo BUILD_OK
