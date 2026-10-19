---
title: Android Release Builds
doc_type: runbook
status: active
owner: engineering
last_updated: 2026-10-19
---

# Android release builds

DigitVA Collect is built by [`.github/workflows/android-release.yml`](../../.github/workflows/android-release.yml).
The workflow builds a signed APK for the production server
`https://digitvav3.causeofdeathindia.com`, verifies its certificate, package,
embedded JavaScript bundle and checksum, and uploads the APK as a short-lived
workflow artifact. A missing signing key, password, alias or certificate
fingerprint stops the build before Gradle runs. No debug-signed APK is
published. Signing runs only from a manually dispatched workflow on `main` and
requires approval of the protected `android-release` environment. Each run
uses its monotonically increasing GitHub Actions run number as Android's
`versionCode`, so future updates can be installed over earlier releases.

## Signing material

Create one release keystore and keep its password, alias and backup in the
team's encrypted offline key store. Never commit the keystore, its base64
payload, or a password to this repository. Configure these secrets and the
certificate variable in the protected GitHub Actions environment
`android-release` on `drguptavivek/DigitVA`:

| Secret or variable | Kind | Value |
| --- | --- | --- |
| `ANDROID_RELEASE_KEYSTORE_BASE64` | Secret | Base64 of the release keystore, with no line breaks |
| `ANDROID_RELEASE_KEYSTORE_PASSWORD` | Secret | Keystore password |
| `ANDROID_RELEASE_KEY_ALIAS` | Secret | Signing key alias |
| `ANDROID_RELEASE_KEY_PASSWORD` | Secret | Signing key password |
| `ANDROID_RELEASE_CERT_SHA256` | Environment variable | SHA-256 certificate fingerprint, with or without colons |

For example, prepare the base64 payload locally and send it directly to
GitHub without writing it to the repository:

```sh
base64 < digitva-release.keystore | tr -d '\n' > /private/tmp/digitva-release.keystore.b64
gh secret set ANDROID_RELEASE_KEYSTORE_BASE64 --env android-release < /private/tmp/digitva-release.keystore.b64
gh secret set ANDROID_RELEASE_KEYSTORE_PASSWORD --env android-release
gh secret set ANDROID_RELEASE_KEY_ALIAS --env android-release
gh secret set ANDROID_RELEASE_KEY_PASSWORD --env android-release
gh variable set ANDROID_RELEASE_CERT_SHA256 --env android-release --body 'AA:BB:CC:...'
```

Replace the example fingerprint with the SHA-256 fingerprint printed by
`keytool -list -v`. Delete the temporary payload after setting the secret and
retain the original keystore in the encrypted offline backup.

## Build and publish

From the Actions tab, select the `main` branch and run **Android release APK**
with the default `publish: false` to produce a signed APK artifact for review.
The workflow installs the
vendored WHO package with its frozen pnpm lockfile, installs the mobile app
with `npm ci`, generates the Android project, and runs
`assembleRelease`. The artifact contains `digitva-collect.apk` and its
`digitva-collect.apk.sha256` checksum.

Publishing is explicit. A manual run may set `publish: true` and provide a
tag such as `android-v0.1.0`; the tag must exactly match the Expo app version
in that commit. Only the publish job has `contents: write` permission after
the signed build succeeds. It creates a
GitHub release containing both stable asset names:

```text
https://github.com/drguptavivek/DigitVA/releases/latest/download/digitva-collect.apk
https://github.com/drguptavivek/DigitVA/releases/latest/download/digitva-collect.apk.sha256
```

These URLs are usable only after a real release has been published. Until
then, workers should use the browser application or obtain the approved APK
link from an administrator; the application server does not guess or host a
release APK.

## Verification boundary

The workflow's verifier uses Android's signing tools to reject debug signing,
compare the APK certificate to `ANDROID_RELEASE_CERT_SHA256`, require package
`org.digitva.collect` and the run's expected positive version code, and inspect the embedded
`index.android.bundle`. The bundle must contain the configured HTTPS API
origin and must not contain the development origins
`http://localhost:8051` or `http://10.0.2.2:8051` in the release allowlist
context. This confirms build-time configuration; it does not replace physical
Android installation, login,
offline, PIN, biometric or background-lock acceptance.
