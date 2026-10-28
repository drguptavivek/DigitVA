#!/usr/bin/env bash
# Build the packaged arm64 Android scoring library with embedded SmartVA reference data.
# Usage: scripts/build-smartva-android.sh [OUT_DIR]; requires an installed Rust Android target and NDK 28.
set -euo pipefail

[[ $# -le 1 ]] || { echo "usage: $0 [OUT_DIR]" >&2; exit 2; }
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
out_dir=${1:-"$repo_root/private/generated/smartva-android"}
sdk_root=${ANDROID_HOME:-"$HOME/Library/Android/sdk"}
ndk_root=${ANDROID_NDK_HOME:-"$sdk_root/ndk/28.2.13676358"}
case "$(uname -s)" in
  Darwin) host_tag=darwin-x86_64 ;;
  Linux) host_tag=linux-x86_64 ;;
  *) echo "unsupported NDK build host" >&2; exit 1 ;;
esac
ndk_bin="$ndk_root/toolchains/llvm/prebuilt/$host_tag/bin"
linker="$ndk_bin/aarch64-linux-android33-clang"
[[ -x "$linker" ]] || { echo "Android API 33 NDK linker missing: $linker" >&2; exit 1; }
rustup target list --installed | grep -qx aarch64-linux-android || {
  echo "install the Rust target first: rustup target add aarch64-linux-android" >&2
  exit 1
}

# The library's API 33 floor is independent of the host app's older collection-only minimum.
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$linker"
export CARGO_TARGET_DIR="$repo_root/private/generated/smartva-android-target"
export CARGO_TARGET_AARCH64_LINUX_ANDROID_RUSTFLAGS="-C link-arg=-Wl,-soname,libsmartva_rust.so -C link-arg=-Wl,-z,max-page-size=16384 -C link-arg=-Wl,-z,common-page-size=16384"
cargo build --manifest-path "$repo_root/vendor/smartva-analyze/rust/Cargo.toml" \
  --locked --release --lib --target aarch64-linux-android --no-default-features --features mobile-core

library="$out_dir/arm64-v8a/libsmartva_rust.so"
mkdir -p "$(dirname "$library")"
cp "$CARGO_TARGET_DIR/aarch64-linux-android/release/libsmartva_rust.so" "$library"
"$ndk_bin/llvm-strip" --strip-unneeded "$library"
"$ndk_bin/llvm-readelf" --program-headers --wide "$library" | awk '
  $1 == "LOAD" { found = 1; if ($NF != "0x4000") bad = 1 }
  END { if (!found || bad) { print "library lacks 16 KiB LOAD alignment" > "/dev/stderr"; exit 1 } }
'
echo "library: $library"
echo "bytes: $(wc -c < "$library" | tr -d ' ')"
shasum -a 256 "$library"
