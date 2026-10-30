#!/usr/bin/env bash
# Builds libdigitva_icd11.so, the Collect Plus offline ICD-11 engine: WHO's unmodified ICD-API 2.6.0 / DORIS
# assemblies plus Bridge.cs, compiled together with .NET NativeAOT for Android (linux-bionic-arm64).
#
# Inputs, none of them in git:
#   ICDAPI_DIR   WHO's portable assemblies, copied from /usr/share/icdapi of whoicd/icd-api:2.6.0
#                (pinned by digest; vendor/who-icd11-api's bootstrap fetches and checks the same files)
#   .NET 10 SDK, pinned in global.json (the one place; the workflow reads it too) with the ASP.NET Core 10 shared framework
#   it ships with, and the Android NDK (28.2). Runs on macOS and on Linux x64 (the host picks the NDK's prebuilt folder).
#   Optional: ANDROID_NDK (default: the Mac SDK's 28.2.13676358), ASPNET_DIR (default: the shared framework of the
#   installed SDK, found from `dotnet --info`).
# Bridge.csproj reads WHO's assemblies from /tmp/icdapi_portable (property IcdApiDir) and ASP.NET Core from AspNetDir.
# rd.xml (hand-written) and rd_gen.xml keep the generic types that protobuf-net, Newtonsoft.Json and System.Text.Json
# reach by reflection; NativeAOT would trim them otherwise. rd_gen.xml is generated from the WHO assemblies by gen_rd.cs
# (a .NET 10 file-based app that reads their metadata; see its header for the rules). This script runs it before every
# publish, so the committed rd_gen.xml is always what the assemblies in ICDAPI_DIR produce: commit it when it changes.
# To regenerate without a full build: dotnet run --file gen_rd.cs -- /tmp/icdapi_portable <ASP.NET shared framework dir> rd_gen.xml
#
# linux-bionic is outside .NET's supported NativeAOT targets, hence DisableUnsupportedError and the runtime pack.
# The output is packaged with WHO's data by scripts/package-icd11-engine.sh and pinned by SHA-256 in
# .github/workflows/collect-plus-release.yml.
#
# usage: ICDAPI_DIR=/path/to/icdapi mobile/digitva-collect/modules/digitva-icd11/engine-src/build.sh OUT_DIR
set -euo pipefail
mkdir -p "$1" && out="$(cd "$1" && pwd)"  # absolute: dotnet publish runs from the source folder
here="$(cd "$(dirname "$0")" && pwd)"
ndk="${ANDROID_NDK:-$HOME/Library/Android/sdk/ndk/28.2.13676358}"
bin="$ndk/toolchains/llvm/prebuilt/$(uname | tr '[:upper:]' '[:lower:]')-x86_64/bin"
[[ -x "$bin/aarch64-linux-android29-clang" ]] || { echo "NDK clang not found in $bin: set ANDROID_NDK" >&2; exit 1; }
: "${ICDAPI_DIR:?set ICDAPI_DIR to the WHO portable assemblies}"
if [[ -z "${ASPNET_DIR:-}" ]]; then
  # The SDK's own host version is the runtime it ships with; its ASP.NET Core shared framework has the same version.
  host_version="$(cd "$here" && dotnet --info | awk '/^Host:/ {h=1} h && $1 == "Version:" {print $2; exit}')"
  ASPNET_DIR="${DOTNET_ROOT:-$(dirname "$(readlink -f "$(command -v dotnet)")")}/shared/Microsoft.AspNetCore.App/$host_version"
fi
aspnet=$ASPNET_DIR
[[ -d "$aspnet" ]] || { echo "ASP.NET Core shared framework not found: $aspnet (set ASPNET_DIR)" >&2; exit 1; }
rm -rf /tmp/icdapi_portable && cp -R "$ICDAPI_DIR" /tmp/icdapi_portable
# The container's /usr/share/icdapi is self-contained: drop the runtime and ASP.NET assemblies, which the build takes from the SDK.
for f in "$aspnet"/*.dll "$(dirname "$aspnet")"/../Microsoft.NETCore.App/*/*.dll; do rm -f "/tmp/icdapi_portable/$(basename "$f")"; done
(cd "$here" && dotnet run --file gen_rd.cs -- /tmp/icdapi_portable "$aspnet" rd_gen.xml.new && mv rd_gen.xml.new rd_gen.xml)
(cd "$here" && dotnet publish Bridge.csproj -c Release -r linux-bionic-arm64 -o "$out" \
  -p:IcdApiDir=/tmp/icdapi_portable -p:AspNetDir="$aspnet" \
  -p:DisableUnsupportedError=true -p:PublishAotUsingRuntimePack=true \
  -p:CppCompilerAndLinker="$bin/aarch64-linux-android29-clang" -p:ObjCopyName="$bin/llvm-objcopy")
if command -v sha256sum >/dev/null; then sha256sum "$out/digitva_icd11.so"; else shasum -a 256 "$out/digitva_icd11.so"; fi
