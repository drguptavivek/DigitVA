#!/usr/bin/env bash
# Local iOS build of DigitVA Collect on a Mac with Xcode: the same steps as .github/workflows/ios-build.yml, plus the
# ICD-11 engine that CI cannot build yet (digitva-nujw.8). For development and verification only: unsigned, simulator.
#
# usage: scripts/ios-local-build.sh [plain|plus-smartva|plus] [--run]
#   plain         DigitVA Collect, no offline engines (default)
#   plus-smartva  Collect Plus with SmartVA only (DIGITVA_IOS_SKIP_ICD11=1), as CI builds it
#   plus          Collect Plus with SmartVA and the ICD-11/DORIS engine (needs .NET 10 and WHO's assemblies)
#   --run         boot an iOS Simulator, install the app and launch it
#
# Builds Release for the simulator so the JS bundle is inside the app and it runs without Metro.
# Inputs for `plus` (none in git):
#   ICDAPI_DIR                    WHO's /usr/share/icdapi; if unset it is copied once out of the pinned whoicd/icd-api image
#                                 with Docker, into private/generated/icdapi-<digest>
#   DIGITVA_ICD11_ENGINE_ARCHIVE  the Android engine archive icd11-engine-<version>.tar.gz (WHO data for the app); if unset
#                                 the pinned release is downloaded with gh and checked against collect-plus-release.yml's sha256
# Tools: Xcode, CocoaPods, Node 22, pnpm 11.9 (corepack), Rust with aarch64-apple-ios(-sim) for plus*, .NET 10 for plus.
set -euo pipefail

variant=plain run=0
for arg in "$@"; do
  case "$arg" in
    plain|plus-smartva|plus) variant=$arg ;;
    --run) run=1 ;;
    *) echo "usage: $0 [plain|plus-smartva|plus] [--run]" >&2; exit 2 ;;
  esac
done

repo="$(cd "$(dirname "$0")/.." && pwd)"
app="$repo/mobile/digitva-collect"
gen="$repo/private/generated"
derived="$gen/ios-derived-$variant"
die() { echo "ios-local-build: $*" >&2; exit 1; }

# --- 1. tools ----------------------------------------------------------------------------------------------------
[[ "$(uname -s)" == Darwin ]] || die "needs macOS with Xcode"
need=(xcodebuild xcrun pod node npm corepack)
[[ $variant == plain ]] || need+=(cargo rustup)
[[ $variant == plus ]] && need+=(dotnet)
missing=()
for tool in "${need[@]}"; do command -v "$tool" >/dev/null || missing+=("$tool"); done
(( ${#missing[@]} == 0 )) || die "missing tools: ${missing[*]}"
[[ "$(node -v)" == v22.* ]] || echo "warning: CI uses Node 22, this is $(node -v)" >&2
xcodebuild -version | head -1

# --- 2. JS dependencies, as CI installs them -----------------------------------------------------------------------
corepack enable >/dev/null 2>&1 || true
corepack prepare pnpm@11.9.0 --activate >/dev/null
pnpm --dir "$repo/vendor/who-va-2022" install --frozen-lockfile
pnpm --dir "$repo/vendor/who-va-2022" run build
(cd "$app" && npm ci)

# --- 3. engines ----------------------------------------------------------------------------------------------------
export APP_VARIANT=""
unset DIGITVA_IOS_SKIP_ICD11
if [[ $variant != plain ]]; then
  export APP_VARIANT=plus
  git -C "$repo" submodule update --init --depth 1 vendor/smartva-analyze
  rustup target add aarch64-apple-ios aarch64-apple-ios-sim >/dev/null
  "$repo/scripts/build-smartva-ios.sh"
fi
if [[ $variant == plus-smartva ]]; then
  export DIGITVA_IOS_SKIP_ICD11=1
elif [[ $variant == plus ]]; then
  wf="$repo/.github/workflows"
  if [[ -z "${ICDAPI_DIR:-}" ]]; then
    image="$(grep -o 'ICD11_IMAGE: *[^ ]*' "$wf/icd11-engine-build.yml" | head -1 | sed 's/ICD11_IMAGE: *//')"
    [[ $image == *@sha256:* ]] || die "could not read the pinned ICD11_IMAGE from icd11-engine-build.yml; set ICDAPI_DIR"
    ICDAPI_DIR="$gen/icdapi-$(echo "${image##*@sha256:}" | cut -c1-12)"
    if [[ ! -s $ICDAPI_DIR/ICD-API.dll ]]; then
      command -v docker >/dev/null && docker info >/dev/null 2>&1 || die "Docker is needed once to copy WHO's assemblies; or set ICDAPI_DIR"
      echo "copying /usr/share/icdapi out of $image"
      docker pull --platform linux/amd64 -q "$image" >/dev/null
      id="$(docker create --platform linux/amd64 "$image")"
      rm -rf "$ICDAPI_DIR" "$ICDAPI_DIR.tmp"
      docker cp "$id:/usr/share/icdapi" "$ICDAPI_DIR.tmp" && mv "$ICDAPI_DIR.tmp" "$ICDAPI_DIR"
      docker rm "$id" >/dev/null
    fi
  fi
  [[ -s $ICDAPI_DIR/ICD-API.dll ]] || die "WHO assemblies missing in $ICDAPI_DIR"
  # The iOS build declares only OS crypto (docs/policy/ios-client.md): a bundled managed crypto library would break that.
  crypto_libs="$(ls "$ICDAPI_DIR" | grep -iE 'bouncy|crypt|identitymodel|sodium|openssl' || true)"
  [[ -z $crypto_libs ]] || die "WHO assemblies include a crypto library; re-check ITSAppUsesNonExemptEncryption first: $crypto_libs"
  export ICDAPI_DIR
  "$app/modules/digitva-icd11/engine-src/build-ios.sh" "$gen/icd11-ios"

  if [[ -z "${DIGITVA_ICD11_ENGINE_ARCHIVE:-}" ]]; then
    tag="$(sed -n 's/^ *ICD11_ENGINE_TAG: *//p' "$wf/collect-plus-release.yml" | head -1)"
    sha="$(sed -n 's/^ *ICD11_ENGINE_SHA256: *//p' "$wf/collect-plus-release.yml" | head -1)"
    version="${tag#icd11-engine-v}"
    name="icd11-engine-$version.tar.gz"
    DIGITVA_ICD11_ENGINE_ARCHIVE="$gen/$name"
    if [[ ! -s $DIGITVA_ICD11_ENGINE_ARCHIVE ]]; then
      command -v gh >/dev/null || die "set DIGITVA_ICD11_ENGINE_ARCHIVE, or install gh to download $tag"
      gh release download "$tag" --repo drguptavivek/DigitVA --pattern "$name" --dir "$gen" --clobber
    fi
    got="$(shasum -a 256 "$DIGITVA_ICD11_ENGINE_ARCHIVE" | cut -d' ' -f1)"
    [[ $got == "$sha" ]] || die "$name sha256 $got does not match the pin $sha in collect-plus-release.yml"
  fi
  export DIGITVA_ICD11_ENGINE_ARCHIVE
fi

# --- 4. native project and build -----------------------------------------------------------------------------------
cd "$app"
npx expo prebuild --platform ios --clean --no-install --non-interactive
cd ios
pod install
lock_has() { grep -Eq "^  - $1 " Podfile.lock; }
case $variant in
  plain) ! lock_has 'Digitva(Icd11|Smartva)' || die "an engine pod is in the plain build" ;;
  plus-smartva) lock_has DigitvaSmartva && ! lock_has DigitvaIcd11 || die "expected SmartVA only" ;;
  plus) lock_has DigitvaSmartva && lock_has DigitvaIcd11 || die "expected both engine pods" ;;
esac
workspace="$(ls -d ./*.xcworkspace | head -1)"
scheme="$(basename "$workspace" .xcworkspace)"
xcodebuild -workspace "$workspace" -scheme "$scheme" -configuration Release -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' -derivedDataPath "$derived" \
  ARCHS=arm64 ONLY_ACTIVE_ARCH=NO CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO build
built="$(find "$derived/Build/Products/Release-iphonesimulator" -maxdepth 1 -name '*.app' | head -1)"
[[ -d $built ]] || die "no .app in $derived"
echo "built: $built"

# --- 5. optional: run in a simulator -------------------------------------------------------------------------------
if (( run )); then
  device="$(xcrun simctl list devices booted -j | node -e 'const d=JSON.parse(require("fs").readFileSync(0)).devices;for(const l of Object.values(d))for(const x of l)if(x.state==="Booted"){console.log(x.udid);process.exit(0)}')"
  if [[ -z $device ]]; then
    device="$(xcrun simctl list devices available -j | node -e 'const d=JSON.parse(require("fs").readFileSync(0)).devices;for(const [r,l] of Object.entries(d).reverse())if(r.includes("iOS"))for(const x of l)if(x.name.startsWith("iPhone")){console.log(x.udid);process.exit(0)}')"
    [[ -n $device ]] || die "no available iPhone simulator: add one in Xcode > Settings > Components"
    xcrun simctl boot "$device"
  fi
  open -a Simulator
  bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$built/Info.plist")"
  xcrun simctl install "$device" "$built"
  xcrun simctl launch "$device" "$bundle_id"
  echo "launched $bundle_id on simulator $device"
fi
