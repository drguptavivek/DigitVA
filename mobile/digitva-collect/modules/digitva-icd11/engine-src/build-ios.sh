#!/usr/bin/env bash
# Builds DigitvaIcd11Engine.xcframework, the Collect Plus offline ICD-11 engine for iOS: the same WHO ICD-API 2.6.0 / DORIS
# assemblies and Bridge.cs as build.sh (Android), compiled with .NET NativeAOT for ios-arm64 (devices) and
# iossimulator-arm64 (Apple-silicon simulators). macOS with Xcode only: NativeAOT's iOS link step runs Apple's toolchain.
#
# Linkage: a dynamic framework per slice (NativeLib=Shared, Bridge.csproj's own setting), not a static library.
# Microsoft's "Create and consume custom frameworks for iOS-like platforms" (.NET 9+) builds a .dylib, rewrites its
# install name to @rpath/<name>.framework/<name> and wraps it in a framework; it states that shared libraries are
# preferred over static ones and does not describe how to consume a static NativeAOT library on iOS (that needs the
# runtime's own archives and system frameworks on the app's link line, a list that changes between .NET releases).
# The dylib keeps that list inside the NativeAOT build. `NATIVE_LIB=Static` switches to the static archive for an
# experiment; the podspec then needs the extra link inputs written next to it (see the end of this script).
#
# Inputs (none in git), as for build.sh:
#   ICDAPI_DIR   WHO's portable assemblies from /usr/share/icdapi of whoicd/icd-api:2.6.0 (pinned by digest)
#   .NET 10 SDK pinned in global.json and its ASP.NET Core shared framework (ASPNET_DIR, found like build.sh)
#   Xcode command-line tools (xcrun, install_name_tool, xcodebuild)
# Bridge.csproj is unchanged: the iOS settings are passed as properties here, so build.sh's Android output does not move.
# gen_rd.cs regenerates rd_gen.xml exactly as build.sh does; the result must equal the committed file.
#
# Output (OUT_DIR):
#   ios-arm64/, iossimulator-arm64/          dotnet publish output per RID
#   DigitvaIcd11Engine.xcframework           both slices, each with Headers/digitva_icd11.h and a module map
#   icd11-engine-ios-<version>.tar.gz(.sha256)  the xcframework, archived like scripts/package-icd11-engine.sh does
# The WHO data the app ships is not in this archive: stage-engine.js stageIcd11Ios takes it from the same engine archive
# (or spike folder) as Android, so both platforms ship identical data.
#
# NOT VERIFIED: this script has not been run (it was written on Linux, where the iOS RIDs cannot link). Before relying
# on it, check on a Mac that both publishes succeed, that `nm -gU` lists exactly digitva_icd11_init/_call/_free, and that
# the engine initialises and answers the parity kit's ops in the simulator.
#
# usage: ICDAPI_DIR=/path/to/icdapi mobile/digitva-collect/modules/digitva-icd11/engine-src/build-ios.sh OUT_DIR
set -euo pipefail
[[ $# -eq 1 ]] || { echo "usage: ICDAPI_DIR=... $0 OUT_DIR" >&2; exit 2; }
[[ "$(uname -s)" == Darwin ]] || { echo "build-ios.sh needs macOS with Xcode (NativeAOT links iOS binaries with Apple's toolchain)" >&2; exit 1; }
command -v xcodebuild >/dev/null || { echo "xcodebuild not found: install Xcode" >&2; exit 1; }
mkdir -p "$1" && out="$(cd "$1" && pwd)"
here="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$here/../../../../.." && pwd)"
: "${ICDAPI_DIR:?set ICDAPI_DIR to the WHO portable assemblies}"
native_lib="${NATIVE_LIB:-Shared}"
[[ "$native_lib" == Shared || "$native_lib" == Static ]] || { echo "NATIVE_LIB must be Shared or Static" >&2; exit 1; }
min_ios=16.4

if [[ -z "${ASPNET_DIR:-}" ]]; then
  ASPNET_DIR="$(cd "$here" && dotnet --list-runtimes | awk '$1 == "Microsoft.AspNetCore.App" {v = $2; d = $3} END {gsub(/[][]/, "", d); print d "/" v}')"
fi
aspnet=$ASPNET_DIR
[[ -d "$aspnet" ]] || { echo "ASP.NET Core shared framework not found: $aspnet (set ASPNET_DIR)" >&2; exit 1; }
rm -rf /tmp/icdapi_portable && cp -R "$ICDAPI_DIR" /tmp/icdapi_portable
for f in "$aspnet"/*.dll "$(dirname "$aspnet")"/../Microsoft.NETCore.App/*/*.dll; do rm -f "/tmp/icdapi_portable/$(basename "$f")"; done
(cd "$here" && dotnet run --file gen_rd.cs -- /tmp/icdapi_portable "$aspnet" rd_gen.xml.new && mv rd_gen.xml.new rd_gen.xml)

header='/* The offline ICD-11 engine C ABI (engine-src/Bridge.cs). Calls must be serialized by the caller. */
#ifndef DIGITVA_ICD11_H
#define DIGITVA_ICD11_H
#ifdef __cplusplus
extern "C" {
#endif
/* NULL on success, else an error text (may hold stack traces: never log it) to free with digitva_icd11_free. */
char *digitva_icd11_init(const char *bundleDir, const char *dataDir);
/* One call: an op name and a JSON object of arguments. *status receives the HTTP-like status. Free the result. */
char *digitva_icd11_call(const char *op, const char *json, int *status);
void digitva_icd11_free(char *p);
#ifdef __cplusplus
}
#endif
#endif'

name=DigitvaIcd11Engine
frameworks=()
for rid in ios-arm64 iossimulator-arm64; do
  publish="$out/$rid"
  rm -rf "$publish"
  # PublishAotUsingRuntimePack: the iOS-like RIDs need the runtime pack (Microsoft's iOS-like platforms guide).
  # IPHONEOS/SIMULATOR deployment target: AppleMinOSVersion is NativeAOT's knob for the -mios-version-min it links with.
  (cd "$here" && dotnet publish Bridge.csproj -c Release -r "$rid" -o "$publish" \
    -p:IcdApiDir=/tmp/icdapi_portable -p:AspNetDir="$aspnet" \
    -p:PublishAotUsingRuntimePack=true -p:NativeLib="$native_lib" -p:AppleMinOSVersion="$min_ios")

  framework="$out/frameworks/$rid/$name.framework"
  rm -rf "$framework" && mkdir -p "$framework/Headers" "$framework/Modules"
  if [[ "$native_lib" == Shared ]]; then
    cp "$publish/digitva_icd11.dylib" "$framework/$name"
    install_name_tool -id "@rpath/$name.framework/$name" "$framework/$name"
    # NativeAOT writes an @executable_path rpath; an embedded framework resolves from the app's Frameworks folder.
    install_name_tool -rpath @executable_path @executable_path/Frameworks "$framework/$name" 2>/dev/null || true
  else
    cp "$publish/digitva_icd11.a" "$framework/$name"
  fi
  printf '%s\n' "$header" > "$framework/Headers/digitva_icd11.h"
  printf 'framework module %s {\n  header "digitva_icd11.h"\n  export *\n}\n' "$name" > "$framework/Modules/module.modulemap"
  cat > "$framework/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleExecutable</key><string>$name</string>
  <key>CFBundleIdentifier</key><string>org.digitva.$name</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>$name</string>
  <key>CFBundlePackageType</key><string>FMWK</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>MinimumOSVersion</key><string>$min_ios</string>
</dict>
</plist>
PLIST

  # The app calls exactly these three; anything else named digitva_* is a stale or wrong build.
  exports="$(nm -gU "$framework/$name" | awk '{print $NF}' | { grep '^_digitva_' || true; } | sort -u)"
  expected=$'_digitva_icd11_call\n_digitva_icd11_free\n_digitva_icd11_init'
  [[ "$exports" == "$expected" ]] || { printf '%s: digitva_* exports are not exactly init, call and free:\n%s\n' "$rid" "$exports" >&2; exit 1; }
  frameworks+=(-framework "$framework")
done

xcframework="$out/$name.xcframework"
rm -rf "$xcframework"
xcodebuild -create-xcframework "${frameworks[@]}" -output "$xcframework"

if [[ "$native_lib" == Static ]]; then
  # A static engine also needs the NativeAOT runtime archives and Apple frameworks on the app's link line. They are
  # not listed here on purpose: read them from this publish (`dotnet publish ... -v:d`, the LinkNative target's
  # NativeLibrary and LinkerArg items, typically libbootstrapperdll.o, libRuntime.WorkstationGC.a,
  # libeventpipe-disabled.a, libstandalonegc-disabled.a, libaotminipal.a, libSystem.Native.a,
  # libSystem.Globalization.Native.a, libSystem.IO.Compression.Native.a, libSystem.Net.Security.Native.a,
  # libSystem.Security.Cryptography.Native.Apple.a, with -lz -lc++ and the Foundation, Security, GSS, CryptoKit
  # frameworks: TO VERIFY for .NET 10) and add them to ios/DigitvaIcd11.podspec before using a static build.
  echo "NATIVE_LIB=Static: the xcframework holds the engine archive only; see the comment above for the link inputs." >&2
  exit 0
fi

# Archive the xcframework like scripts/package-icd11-engine.sh: sorted, fixed owner, mode and mtime, no AppleDouble.
# shellcheck source=../../../../../scripts/icd11-engine.env
. "$repo_root/scripts/icd11-engine.env"
archive_name="icd11-engine-ios-${ICD11_ENGINE_VERSION}.tar.gz"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp -R "$xcframework" "$work/"
find "$work/$name.xcframework" -type f -exec chmod 644 {} + -exec touch -t 202601010000 {} +
find "$work/$name.xcframework" -type d -exec chmod 755 {} +
(cd "$work" && find "$name.xcframework" -type f | LC_ALL=C sort > files.txt \
  && COPYFILE_DISABLE=1 tar --no-xattrs --uid 0 --gid 0 --uname root --gname root --format ustar -cf - -T files.txt) \
  | gzip -n > "$out/$archive_name"
(cd "$out" && shasum -a 256 "$archive_name" > "$archive_name.sha256")
echo "xcframework: $xcframework"
echo "archive: $out/$archive_name"
echo "sha256:  $(cut -d' ' -f1 "$out/$archive_name.sha256")"
