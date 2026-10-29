#!/usr/bin/env bash
# Builds libdigitva_icd11.so, the Collect Plus offline ICD-11 engine: WHO's unmodified ICD-API 2.6.0 / DORIS
# assemblies plus Bridge.cs, compiled together with .NET NativeAOT for Android (linux-bionic-arm64).
#
# Inputs, none of them in git:
#   ICDAPI_DIR   WHO's portable assemblies, copied from /usr/share/icdapi of whoicd/icd-api:2.6.0
#                (pinned by digest; vendor/who-icd11-api's bootstrap fetches and checks the same files)
#   .NET 10 SDK with the ASP.NET Core 10 shared framework, and the Android NDK (28.2)
# Bridge.csproj reads the assemblies from /tmp/icdapi_portable (property B) and ASP.NET Core from the SDK.
# rd.xml (hand-written) and rd_gen.xml (generated from the WHO assemblies) keep the generic types that
# protobuf-net, Newtonsoft.Json and System.Text.Json reach by reflection; NativeAOT would trim them otherwise.
# The rd_gen.xml generator is not yet in the repository: regenerate it when WHO's assemblies change.
#
# linux-bionic is outside .NET's supported NativeAOT targets, hence DisableUnsupportedError and the runtime pack.
# The output is packaged with WHO's data by scripts/package-icd11-engine.sh and pinned by SHA-256 in
# .github/workflows/collect-plus-release.yml.
#
# usage: ICDAPI_DIR=/path/to/icdapi mobile/digitva-collect/modules/digitva-icd11/engine-src/build.sh OUT_DIR
set -euo pipefail
out=$1
here="$(cd "$(dirname "$0")" && pwd)"
ndk="${ANDROID_NDK:-$HOME/Library/Android/sdk/ndk/28.2.13676358}"
bin="$ndk/toolchains/llvm/prebuilt/$(uname | tr '[:upper:]' '[:lower:]')-x86_64/bin"
: "${ICDAPI_DIR:?set ICDAPI_DIR to the WHO portable assemblies}"
rm -rf /tmp/icdapi_portable && cp -R "$ICDAPI_DIR" /tmp/icdapi_portable
(cd "$here" && dotnet publish Bridge.csproj -c Release -r linux-bionic-arm64 -o "$out" \
  -p:DisableUnsupportedError=true -p:PublishAotUsingRuntimePack=true \
  -p:CppCompilerAndLinker="$bin/aarch64-linux-android29-clang" -p:ObjCopyName="$bin/llvm-objcopy")
shasum -a 256 "$out/digitva_icd11.so"
