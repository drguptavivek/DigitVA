#!/usr/bin/env bash
# Build SmartvaRust.xcframework, the iOS twin of scripts/build-smartva-android.sh: the same vendor/smartva-analyze/rust
# crate and features (mobile-core: in-memory scoring and the C ABI, reference data embedded), as a static library for
# aarch64-apple-ios (devices) and aarch64-apple-ios-sim (Apple Silicon simulators). The crate declares cdylib, which
# iOS would have to embed as a signed framework; `cargo rustc --crate-type staticlib` links it into the app instead.
# Each slice carries the crate's include/smartva_rust.h and a module map, so Swift can `import SmartvaRust`.
# Usage: scripts/build-smartva-ios.sh [OUT_DIR]; macOS with Xcode and `rustup target add aarch64-apple-ios aarch64-apple-ios-sim`.
# SMARTVA_SRC overrides the crate checkout (default: this repo's vendor/smartva-analyze submodule).
set -euo pipefail

[[ $# -le 1 ]] || { echo "usage: $0 [OUT_DIR]" >&2; exit 2; }
[[ "$(uname -s)" == Darwin ]] || { echo "build-smartva-ios.sh needs macOS and Xcode" >&2; exit 1; }
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
out_dir=${1:-"$repo_root/private/generated/smartva-ios"}
crate=${SMARTVA_SRC:-"$repo_root/vendor/smartva-analyze"}/rust
[[ -f "$crate/Cargo.toml" ]] || { echo "SmartVA crate not found at $crate: git submodule update --init vendor/smartva-analyze, or set SMARTVA_SRC" >&2; exit 1; }
targets=(aarch64-apple-ios aarch64-apple-ios-sim)
for target in "${targets[@]}"; do
  rustup target list --installed | grep -qx "$target" || { echo "install the Rust target first: rustup target add $target" >&2; exit 1; }
done

export CARGO_TARGET_DIR="$repo_root/private/generated/smartva-ios-target"
# Expo's iOS floor; rustc's own default (10.0 / 14.0 sim) would only warn at link time.
export IPHONEOS_DEPLOYMENT_TARGET=15.1
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/include"
cp "$crate/include/smartva_rust.h" "$work/include/"
printf 'module SmartvaRust {\n  header "smartva_rust.h"\n  export *\n}\n' > "$work/include/module.modulemap"

libraries=()
for target in "${targets[@]}"; do
  cargo rustc --manifest-path "$crate/Cargo.toml" --locked --release --lib --target "$target" \
    --no-default-features --features mobile-core --crate-type staticlib
  lib="$work/$target/libsmartva_rust.a"
  mkdir -p "$(dirname "$lib")"
  cp "$CARGO_TARGET_DIR/$target/release/libsmartva_rust.a" "$lib"
  # Local symbols and debug info only; the smartva_* exports stay.
  strip -S -x "$lib"
  libraries+=(-library "$lib" -headers "$work/include")
done

xcframework="$out_dir/SmartvaRust.xcframework"
rm -rf "$xcframework"
mkdir -p "$out_dir"
xcodebuild -create-xcframework "${libraries[@]}" -output "$xcframework"
for target in "${targets[@]}"; do
  # A variable, not a pipe: grep -q would exit early and pipefail would read nm's SIGPIPE as a failure.
  symbols="$(nm -gU "$work/$target/libsmartva_rust.a" 2>/dev/null)"
  grep -q ' _smartva_score_json$' <<<"$symbols" || { echo "$target: smartva_score_json not exported" >&2; exit 1; }
done
echo "xcframework: $xcframework"
find "$xcframework" -name libsmartva_rust.a -exec shasum -a 256 {} \;
