#!/usr/bin/env bash
# Verify the release APK before it can become a downloadable application.
set -euo pipefail

usage() {
  echo "usage: $0 APK EXPECTED_CERT_SHA256 EXPECTED_API_BASE_URL EXPECTED_VERSION_CODE" >&2
  exit 2
}

[[ $# -eq 4 ]] || usage
apk=$1
expected_cert=$2
expected_api=$3
expected_version_code=$4

[[ -s "$apk" ]] || { echo "APK does not exist or is empty: $apk" >&2; exit 1; }
[[ "$expected_api" == https://* ]] || {
  echo "release API base URL must use HTTPS" >&2
  exit 1
}
[[ "$expected_version_code" =~ ^[1-9][0-9]*$ ]] || {
  echo "expected versionCode must be a positive integer" >&2
  exit 1
}
[[ "$expected_cert" =~ ^([[:xdigit:]]{2}:?){32}$ ]] || {
  echo "expected certificate must be a SHA-256 fingerprint" >&2
  exit 1
}

find_tool() {
  local name=$1
  local candidate
  if command -v "$name" >/dev/null 2>&1; then
    command -v "$name"
    return 0
  fi
  if [[ -n "${ANDROID_HOME:-}" && -d "$ANDROID_HOME/build-tools" ]]; then
    candidate=$(find "$ANDROID_HOME/build-tools" -type f -name "$name" -perm -111 -print 2>/dev/null | sort -V | tail -n 1)
    if [[ -n "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi
  echo "required Android tool not found: $name" >&2
  exit 1
}

apksigner=$(find_tool apksigner)
aapt=$(find_tool aapt)

cert_output=$("$apksigner" verify --verbose --print-certs "$apk")
if grep -Fqi 'CN=Android Debug' <<<"$cert_output"; then
  echo "release APK is signed with the Android debug certificate" >&2
  exit 1
fi

normalise_digest() {
  tr -d '[:space:]:\r' | tr '[:lower:]' '[:upper:]'
}

actual_cert=$(sed -n 's/.*certificate SHA-256 digest: //p' <<<"$cert_output" | head -n 1 | normalise_digest)
expected_cert_normalised=$(printf '%s' "$expected_cert" | normalise_digest)
[[ -n "$actual_cert" ]] || { echo "APK certificate digest was not reported" >&2; exit 1; }
if [[ "$actual_cert" != "$expected_cert_normalised" ]]; then
  echo "APK certificate fingerprint does not match ANDROID_RELEASE_CERT_SHA256" >&2
  exit 1
fi

badging=$("$aapt" dump badging "$apk")
package_name=$(sed -n "s/^package: name='\([^']*\)'.*/\1/p" <<<"$badging" | head -n 1)
version_code=$(sed -n "s/^package:.*versionCode='\([^']*\)'.*/\1/p" <<<"$badging" | head -n 1)
[[ "$package_name" == org.digitva.collect ]] || {
  echo "unexpected Android package: ${package_name:-missing}" >&2
  exit 1
}
[[ "$version_code" =~ ^[1-9][0-9]*$ ]] || {
  echo "APK has no positive versionCode" >&2
  exit 1
}
if [[ "$version_code" != "$expected_version_code" ]]; then
  echo "APK versionCode $version_code does not match expected $expected_version_code" >&2
  exit 1
fi

bundle_member=$(unzip -Z1 "$apk" | awk '$0 ~ /(^|\/)index\.android\.bundle$/ { print; exit }')
[[ -n "$bundle_member" ]] || { echo "APK does not contain an embedded Android JavaScript bundle" >&2; exit 1; }
bundle_file=$(mktemp)
trap 'rm -f -- "$bundle_file"' EXIT
unzip -p "$apk" "$bundle_member" >"$bundle_file"
grep -Fq "$expected_api" "$bundle_file" || {
  echo "embedded JavaScript does not contain the configured HTTPS API origin" >&2
  exit 1
}
# Metro may retain development-only strings used by the debug QR flow. Inspect
# the allowlist's local bundle context instead of rejecting unrelated RN text.
expected_offset=$(grep -abo -F "$expected_api" "$bundle_file" | head -n 1 | cut -d: -f1)
context_start=$((expected_offset > 2048 ? expected_offset - 2048 : 0))
allowlist_context=$(dd if="$bundle_file" bs=1 skip="$context_start" count=4096 2>/dev/null)
for dev_origin in 'http://localhost:8051' 'http://10.0.2.2:8051'; do
  if grep -Fq "$dev_origin" <<<"$allowlist_context"; then
    echo "embedded JavaScript contains a development API origin: $dev_origin" >&2
    exit 1
  fi
done

echo "verified signed APK: package=$package_name versionCode=$version_code cert=$actual_cert"
