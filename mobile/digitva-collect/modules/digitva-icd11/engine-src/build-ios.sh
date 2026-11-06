#!/usr/bin/env bash
# Builds DigitvaIcd11Engine.xcframework, the Collect Plus offline ICD-11 engine for iOS: the same Bridge.cs and WHO
# ICD-API 2.6.0 / DORIS assemblies as build.sh (Android), compiled with .NET NativeAOT for ios-arm64 (devices) and
# iossimulator-arm64 (Apple Silicon simulators), both supported NativeAOT targets, so no DisableUnsupportedError here.
#
# Each RID is published as a self-contained dynamic library (Bridge.csproj: NativeLib=Shared) and wrapped as
# DigitvaIcd11Engine.framework (install name @rpath/..., the C header digitva_icd11.h and a module map, so Swift can
# `import DigitvaIcd11Engine`); xcodebuild joins the two into one xcframework. A dynamic framework rather than a static
# library: the engine keeps its own copy of the .NET native runtime (System.Native, the GC, Apple crypto shims) inside
# one image, so nothing in it can clash with the app's other static code, and the app links one framework instead of a
# dozen runtime archives and their system flags.
#
# Inputs, none of them in git: ICDAPI_DIR (WHO's /usr/share/icdapi of whoicd/icd-api:2.6.0, as for build.sh), the .NET
# SDK pinned in global.json with its ASP.NET Core shared framework (ASPNET_DIR overrides), and Xcode. macOS only.
# build.sh regenerates rd_gen.xml from the same assemblies; this script checks the committed file instead of rewriting it.
#
# usage: ICDAPI_DIR=/path/to/icdapi mobile/digitva-collect/modules/digitva-icd11/engine-src/build-ios.sh OUT_DIR
set -euo pipefail
[[ "$(uname)" == Darwin ]] || { echo "build-ios.sh needs macOS and Xcode" >&2; exit 1; }
mkdir -p "$1" && out="$(cd "$1" && pwd)"
here="$(cd "$(dirname "$0")" && pwd)"
: "${ICDAPI_DIR:?set ICDAPI_DIR to the WHO portable assemblies}"
if [[ -z "${ASPNET_DIR:-}" ]]; then
  ASPNET_DIR="$(cd "$here" && dotnet --list-runtimes | awk '$1 == "Microsoft.AspNetCore.App" {v = $2; d = $3} END {gsub(/[][]/, "", d); print d "/" v}')"
fi
aspnet=$ASPNET_DIR
[[ -d "$aspnet" ]] || { echo "ASP.NET Core shared framework not found: $aspnet (set ASPNET_DIR)" >&2; exit 1; }
name=DigitvaIcd11Engine
# Own work folder: build.sh owns /tmp/icdapi_portable, and the two may run at once.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp -R "$ICDAPI_DIR" "$work/icdapi"
for f in "$aspnet"/*.dll "$(dirname "$aspnet")"/../Microsoft.NETCore.App/*/*.dll; do rm -f "$work/icdapi/$(basename "$f")"; done
(cd "$here" && dotnet run --file gen_rd.cs -- "$work/icdapi" "$aspnet" "$work/rd_gen.xml")
cmp -s "$work/rd_gen.xml" "$here/rd_gen.xml" || { echo "rd_gen.xml is stale for these assemblies: run build.sh and commit it" >&2; exit 1; }

frameworks=()
for rid in ios-arm64 iossimulator-arm64; do
  # --artifacts-path keeps bin/ and obj/ out of the source folder.
  (cd "$here" && dotnet publish Bridge.csproj -c Release -r "$rid" -o "$work/pub-$rid" --artifacts-path "$work/artifacts" \
    -p:IcdApiDir="$work/icdapi" -p:AspNetDir="$aspnet" -p:PublishAotUsingRuntimePack=true)
  fw="$work/$rid/$name.framework"
  mkdir -p "$fw/Headers" "$fw/Modules"
  cp "$work/pub-$rid/digitva_icd11.dylib" "$fw/$name"
  install_name_tool -id "@rpath/$name.framework/$name" "$fw/$name"
  cp "$here/digitva_icd11.h" "$fw/Headers/"
  printf 'framework module %s {\n  header "digitva_icd11.h"\n  export *\n}\n' "$name" > "$fw/Modules/module.modulemap"
  platform=iPhoneOS; [[ $rid == iossimulator-* ]] && platform=iPhoneSimulator
  cat > "$fw/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>$name</string>
  <key>CFBundleIdentifier</key><string>com.causeofdeathindia.digitva.icd11engine</string>
  <key>CFBundleName</key><string>$name</string>
  <key>CFBundlePackageType</key><string>FMWK</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleSupportedPlatforms</key><array><string>$platform</string></array>
  <key>MinimumOSVersion</key><string>15.1</string>
</dict></plist>
PLIST
  frameworks+=(-framework "$fw")
done
rm -rf "$out/$name.xcframework"
xcodebuild -create-xcframework "${frameworks[@]}" -output "$out/$name.xcframework"
find "$out/$name.xcframework" -type f -name "$name" -exec shasum -a 256 {} \;
