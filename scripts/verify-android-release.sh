#!/usr/bin/env bash
# Verify the release APK before it can become a downloadable application.
set -euo pipefail

usage() {
  echo "usage: $0 APK EXPECTED_CERT_SHA256 EXPECTED_API_BASE_URL EXPECTED_VERSION_CODE [EXPECTED_PACKAGE]" >&2
  exit 2
}

[[ $# -eq 4 || $# -eq 5 ]] || usage
apk=$1
expected_cert=$2
expected_api=$3
expected_version_code=$4
# Collect Plus has its own package id (com.causeofdeathindia.digitvacollect.plus); the release app is the default.
expected_package=${5:-com.causeofdeathindia.digitvacollect}
[[ "$expected_package" =~ ^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$ ]] || {
  echo "expected package must be an Android package id" >&2
  exit 1
}

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
app_label=$(sed -n "s/^application-label:'\([^']*\)'.*/\1/p" <<<"$badging" | head -n 1)
[[ "$package_name" == "$expected_package" ]] || {
  echo "unexpected Android package: ${package_name:-missing}" >&2
  exit 1
}
expected_label="DigitVA"
[[ "$expected_package" == *.plus ]] && expected_label="DigitVA Collect Plus"
[[ "$app_label" == "$expected_label" ]] || {
  echo "unexpected Android application label: ${app_label:-missing}" >&2
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

bundle_member=$(unzip -Z1 "$apk" | awk '$0 ~ /(^|\/)index\.android\.bundle$/ && !found { print; found = 1 }')
[[ -n "$bundle_member" ]] || { echo "APK does not contain an embedded Android JavaScript bundle" >&2; exit 1; }
bundle_file=$(mktemp)
trap 'rm -f -- "$bundle_file"' EXIT
unzip -p "$apk" "$bundle_member" >"$bundle_file"
grep -Fq "$expected_api" "$bundle_file" || {
  echo "embedded JavaScript does not contain the configured HTTPS API origin" >&2
  exit 1
}
# src/enrolment.ts keeps its debug origins behind __DEV__, so a release bundle
# must not contain them anywhere (Hermes packs strings without code context).
for dev_origin in 'http://localhost:8051' 'http://10.0.2.2:8051'; do
  if grep -Fq "$dev_origin" "$bundle_file"; then
    echo "embedded JavaScript contains a development API origin: $dev_origin" >&2
    exit 1
  fi
done

echo "verified signed APK: package=$package_name versionCode=$version_code cert=$actual_cert"
