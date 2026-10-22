import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "../..");
const workflow = readFileSync(resolve(root, ".github/workflows/android-release.yml"), "utf8");
const verifier = readFileSync(resolve(root, "scripts/verify-android-release.sh"), "utf8");

assert.doesNotMatch(workflow.split("    steps:")[0], /\$\{\{\s*runner\./,
  "job configuration cannot use the step-only runner context");
assert.match(workflow, /export ANDROID_RELEASE_STORE_FILE="\$RUNNER_TEMP\//);
assert.match(workflow, /ANDROID_RELEASE_STORE_FILE=%s\\n.*\$GITHUB_ENV/);
assert.doesNotMatch(workflow, /cache: gradle/,
  "Gradle files do not exist until Expo prebuild, after JDK setup");

for (const action of [
  "actions/checkout",
  "actions/setup-node",
  "actions/setup-java",
  "actions/upload-artifact",
  "actions/download-artifact",
]) {
  assert.match(workflow, new RegExp(`uses: ${action}@[0-9a-f]{40}`), `${action} must be SHA pinned`);
}

for (const variable of [
  "EXPO_PUBLIC_API_BASE_URL",
  "DIGITVA_ANDROID_RELEASE_BUILD",
  "ANDROID_RELEASE_STORE_FILE",
  "ANDROID_RELEASE_KEYSTORE_PASSWORD",
  "ANDROID_RELEASE_KEY_ALIAS",
  "ANDROID_RELEASE_KEY_PASSWORD",
  "ANDROID_RELEASE_KEYSTORE_BASE64",
  "ANDROID_RELEASE_CERT_SHA256",
]) {
  assert.match(workflow, new RegExp(variable), `${variable} is part of the release contract`);
}

assert.match(workflow, /pnpm --dir vendor\/who-va-2022 install --frozen-lockfile/);
assert.match(workflow, /npm ci/);
assert.doesNotMatch(workflow, /npm install/);
assert.match(workflow, /assembleRelease/);
assert.match(workflow, /gh release create/);
assert.match(workflow, /permissions:\n\s+contents: write/);
assert.match(workflow, /workflow_dispatch:/);
assert.doesNotMatch(workflow, /push:\s*\n\s+tags:/);
assert.match(workflow, /if: github\.ref == 'refs\/heads\/main'/);
assert.match(workflow, /environment: android-release/);
assert.match(workflow, /npm run typecheck/);
assert.match(workflow, /npm test -- --runInBand/);
assert.match(workflow, /DIGITVA_ANDROID_VERSION_CODE=%s.*major \* 10000 \+ minor \* 100 \+ patch.*GITHUB_ENV/,
  "the base versionCode follows the app version so per-ABI codes keep increasing");
assert.match(workflow, /verify-android-release\.sh .*\$\(\(DIGITVA_ANDROID_VERSION_CODE \* 10 \+ /);
for (const abi of ["armeabi-v7a", "arm64-v8a"]) {
  assert.match(workflow, new RegExp(`${abi}`), `${abi} APK is verified and published`);
}
assert.match(workflow, /EXPO_PUBLIC_API_BASE_URL: https:\/\/digitva\.causeofdeathindia\.com\n/);
assert.match(workflow, /needs\.build\.result == 'success' && github\.ref == 'refs\/heads\/main' && inputs\.publish == true/);
assert.match(workflow, /expected_tag="android-v\$\{APP_VERSION\}"/);
assert.match(workflow, /--title "DigitVA \$\{APP_VERSION\}"/);

for (const check of [
  "apksigner",
  "Android Debug",
  "certificate SHA-256 digest",
  "com.causeofdeathindia.digitvacollect",
  "application-label:'\\([^']*\\)'",
  "DigitVA",
  "index\\.android\\.bundle",
  "EXPECTED_VERSION_CODE",
  "https://",
  "http://localhost:8051",
  "http://10.0.2.2:8051",
]) {
  assert.ok(verifier.includes(check), `${check} is verified before publication`);
}

const listingSelector = verifier.match(/bundle_member=\$\(unzip -Z1 "\$apk" \| (awk .*)\)/);
assert.ok(listingSelector, "archive bundle selection must be testable");
const listing = spawnSync("bash", ["-c", `set -o pipefail\n{ printf 'assets/index.android.bundle\\n'; seq 1 100000; printf 'other/index.android.bundle\\n'; } | ${listingSelector[1]}`], { encoding: "utf8" });
assert.equal(listing.status, 0, "large archive listings must not terminate the producer with SIGPIPE");
assert.equal(listing.stdout.trim(), "assets/index.android.bundle", "select only the first bundle member");

console.log("android release workflow and verifier checks passed");
