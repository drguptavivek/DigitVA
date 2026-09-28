# Two-step login and passkeys

- Status: All owner decisions made 2026-09-28; next step is the policy baseline in `docs/policy`
- Priority: P1
- Created: 2026-09-28
- Bead: `digitva-sn1.1` (child of `digitva-sn1`)

## Goal

Ask for email and CAPTCHA first. On a second page, offer browser-mediated passkey sign-in with password fallback. After a password login by a user without a passkey, show a dismissible banner: “Sign on faster using passkeys next time.” Link to passkey setup in Profile.

## Security contract

- Use the W3C WebAuthn browser API (`navigator.credentials.create()` and `get()`) and FIDO2 authenticators, with no operating-system-specific login code. The same relying-party ID and verified origin must work across supported browsers on Windows, macOS, iOS, and Android.
- Support platform authenticators (for example Windows Hello and phone/computer screen unlock), synced passkeys, roaming security keys, and browser-mediated use of a passkey from another device. Never require a biometric sensor: the platform may verify with a PIN or device password.
- Show an explicit “Use a passkey” action on the second page on every platform. Treat conditional/autofill prompts as an enhancement because their availability varies by browser and passkey provider. Keep password fallback accessible when WebAuthn is unavailable or canceled.
- The second page must look the same for known and unknown email addresses. A site cannot silently determine whether a passkey is on this device; the browser presents available local, synced, or hardware credentials.
- A successful CAPTCHA creates a short-lived, one-use pre-authentication session state. Do not create a Flask-Login session or remember cookie until every required factor succeeds.
- Preserve verified-email, active-user, maintenance, rate-limit, CSRF, and safe `next` redirect checks.
- A verified passkey completes sign-in. Password remains a fallback. Per the existing `digitva-sn1` decision, admin and data-manager password login must also complete TOTP; coders may use password alone.
- Registration, authentication, renaming, and revocation must support multiple passkeys. Store unique credential IDs, public keys, signature counters, backup state, transport hints, and timestamps in dedicated records. Update counters atomically and audit security changes without recording credential payloads.
- TOTP needs encrypted secrets, replay protection, one-use hashed recovery codes, and a privileged-account recovery procedure. Require recent reauthentication for factor changes.
- The CAPTCHA is a local proof-of-work challenge verified server-side (signature, expiry, single use). Its HMAC key and the production WebAuthn RP ID/origin belong in deployment configuration.

## Owner decisions (2026-09-28)

1. **Migration allowed.** One additive migration adds the credential, TOTP, recovery-code and security-event tables. This supersedes the earlier no-migrations instruction for this task only.
2. **Same second page for everyone.** Every email gets "Use a passkey" plus the password form. This replaces the 22 September note that showed a passkey prompt only to users who have one (that version revealed which accounts have passkeys).
3. **Local CAPTCHA only.** No third-party service (no reCAPTCHA, hCaptcha or Turnstile). Use a self-hosted proof-of-work challenge (ALTCHA-style: server issues an HMAC-signed challenge, the browser solves it in the background, the server verifies signature, expiry and single use). No external outage can lock out sign-in, and no visitor data leaves the server. Because it needs no user action, it can run on every email step.
4. **Rollout and recovery:** see below.

## Rollout and recovery (decision 4)

- **Who must enrol.** Admins and data managers must register a passkey or TOTP. Coders are exempt: they may sign in with password alone and are offered a passkey through the post-login banner.
- **Enrolment window: 30 days** from launch, with a banner on every login until the user enrols. After the deadline, a privileged user who has not enrolled can still sign in with their password but is sent to the setup page and cannot reach the rest of the app until a factor is added. No lock-out.
- **Factor reset by an admin.** An admin (central admin) can reset any user's factors, including another admin's; nobody resets their own. A reset clears that user's passkeys, TOTP and recovery codes, ends their sessions and forces setup at next login. It is audited (actor, target, time, reason; no credential data) and the user is emailed.
- **Break-glass CLI.** `flask auth reset-factors <email> --reason "..."`, run from a shell in the app container (shell access is the safeguard). It does what an admin reset does, then emails the user a one-time magic link that starts the existing onboarding flow: verify email, set a password, then register a passkey or TOTP (mandatory for privileged roles, offered to coders). The link is single-use and expires in one hour; the command prints the link only if mail delivery fails. It is audited as a CLI action, never shows existing secrets, and never creates users or changes roles.
- **Single-use links.** Today's reset links are stateless and reusable within their hour (bead `digitva-0l9`). The magic link reuses `app/services/token_service.py` and must be single-use: sign a fingerprint of the password hash and factor state into the token, so the first successful use invalidates it.

## Required fixes found in review

- Safe `next` redirect: reuse the fix from bead `digitva-018`; the current empty-netloc check lets `/\evil.com` and `///evil.com` through.
- Active-user check: reuse the fix from bead `digitva-aye`; login today ignores `user_status`.
- Require WebAuthn user verification (`userVerification: "required"`) for admins and data managers; PIN or device unlock is enough.
- Per-account rate limits on the email step and on each passkey or TOTP attempt, in addition to the per-IP limits. Pre-authentication state is bound to the email, allows one challenge, and expires within five minutes.
- Signature counter: a counter of 0 on both sides (synced passkeys) is not a replay; only a non-zero counter that fails to increase is.
- Fix the production RP ID before the first registration; changing the domain later invalidates every passkey.
- Coordinate with per-project SSO (`.tasks/2026-09-26-project-sso-oauth2.md`): the email step decides whether to hand off to the project's identity provider.
- Libraries: `webauthn` (py_webauthn) and `pyotp`; `altcha` if its Python package fits, otherwise a few lines of HMAC code. Rebuild the images after `uv add`.
- CI browser test with Chrome's virtual authenticator for registration and sign-in; real devices only for the cross-platform check.

## Why implementation was paused (historical)

`va_users.other` is general account metadata and already stores `created_by_user_id`. It does not enforce credential ID uniqueness or independent revocation and makes concurrent credential/counter updates fragile. A safe passkey/TOTP implementation needs additive credential and recovery tables, which conflicts with the user's explicit instruction not to write migrations. The repository also has no CAPTCHA provider or credentials configured; the provider choice is pending.

## Proposed work once decisions are made

1. Record the approved authentication, recovery, CAPTCHA, RP ID, and rollout policy in `docs/policy`.
2. Add the credential, TOTP, recovery-code, and minimal security-event schema with one additive migration; add WebAuthn/TOTP dependencies and deployment configuration.
3. Implement the local proof-of-work CAPTCHA (server-issued, signed, one-use challenges); no third-party CSP changes are needed.
4. Implement WebAuthn and TOTP services, then the two-step login and profile enrollment/revocation controls.
5. Add the post-login passkey nudge and user guidance. Verify in a real browser with a passkey-capable authenticator.

Run focused and combined authentication tests only in a dedicated disposable database, not the Doris test database. Preserve the unrelated Doris, organization CSV, and other agents' edits. This agent must not commit or push.

## Cross-platform acceptance

Exercise registration, sign-in, cancellation, and password fallback in current Chrome/Edge on Windows, Safari and Chrome on macOS, Safari on iOS, and Chrome on Android. Include a platform passkey, a synced or cross-device passkey, and a FIDO2 security key where available. Verify each against the same server-side origin, challenge, credential ownership, and user-verification rules. Record exact OS/browser versions and any provider-specific limitation; do not infer support from a passing server-side unit test alone.
