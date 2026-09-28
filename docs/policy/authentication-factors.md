---
title: Login Factors, Passkeys and TOTP
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-28
---

# Login Factors, Passkeys and TOTP

Baseline for the two-step login, passkeys (WebAuthn), TOTP, recovery codes,
enrolment enforcement and factor recovery. Owner decisions of 2026-09-28;
design record `.tasks/2026-09-28-passkey-login.md`; epic `digitva-sn1`,
feature `digitva-sn1.1`.

## 1. Login flow

1. **Email step.** The user enters an email. The browser solves a local
   proof-of-work challenge (section 5) in the background and submits it with
   the email. The server verifies the challenge and stores a pre-authentication
   state in the server-side session. It never creates a Flask-Login session or
   remember cookie at this step.
2. **Second page.** Every email, known or unknown, active or not, gets the same
   page: a "Use a passkey" button and a password form. The response, its
   timing and its content must not depend on whether the account exists or
   has passkeys. Conditional (autofill) passkey UI is an optional enhancement;
   the explicit button is always shown.
3. **Passkey path.** A verified passkey for the pre-auth email's account
   completes sign-in. The WebAuthn request carries no `allowCredentials` (the
   browser offers discoverable credentials), so it cannot reveal which
   accounts have passkeys. The server then checks that the credential belongs
   to the account named in the pre-auth state.
4. **Password path.** A correct password completes sign-in unless the user
   must also give a second factor (section 3). Then a third page asks for a
   TOTP code or a recovery code.
5. Every path keeps the existing checks: verified email, `user_status` active
   (inactive accounts get the wrong-credentials message), site maintenance,
   per-IP and per-account rate limits, CSRF (forms and `X-CSRFToken` on JSON
   posts), and the safe `next` redirect (`_safe_next_url`).

**Pre-authentication state** is bound to one email, allows one outstanding
WebAuthn challenge at a time, is replaced by a new email step, is cleared on
success, and expires five minutes after the email step. A second-factor page
after a correct password is also bound to that state and expires with it.

**Rate limits.** Email step: 10 per minute per IP and 20 per hour per email.
Password, passkey and TOTP/recovery attempts: 10 per minute per IP and 20 per
hour per account. Five failed second-factor attempts clear the pre-auth state
and send the user back to the email step.

## 2. Passkeys (WebAuthn)

- Standard W3C WebAuthn (`navigator.credentials.create()` / `get()`) with
  FIDO2 authenticators, through the `webauthn` (py_webauthn) library. No
  operating-system-specific code. Platform authenticators, synced passkeys,
  roaming security keys and cross-device (hybrid) use are all accepted.
- **User verification is required** (`userVerification: "required"`) at
  registration and sign-in for every user. PIN, device password or screen
  unlock satisfy it; a biometric sensor is never required.
- Registration asks for a discoverable credential (`residentKey: "required"`)
  so the passkey path works without `allowCredentials`.
- **Relying party.** RP ID is the host of `MAIL_BASE_URL` and the expected
  origin is its scheme and host (with port if present). `WEBAUTHN_RP_ID` and
  `WEBAUTHN_ORIGIN` may override them, for development only. Production uses
  RP ID `digitva.causeofdeathindia.com`. **Changing the RP ID invalidates every
  registered passkey**, so it is fixed before the first production
  registration and never changed afterwards.
- A user may register several passkeys, name and rename them, and revoke any
  of them. Each stores a unique credential ID, public key, signature counter,
  backup-eligible/backed-up flags, transport hints, name, created and last-used
  times.
- **Signature counter.** Updated atomically on each sign-in. A counter of zero
  on both sides (synced passkeys) is not a replay. A non-zero stored counter
  that the new counter fails to exceed is a possible clone: the sign-in is
  refused and a security event recorded.
- After a password sign-in by a user with no passkey, a dismissible banner
  says "Sign on faster using passkeys next time." and links to the Profile
  passkey section.

## 3. Who must give a second factor

- **Privileged users** are those holding an active `admin` or `data_manager`
  grant. They must enrol a passkey or TOTP.
- **Coders and every other role** may sign in with password alone. They may
  register passkeys, and may enrol TOTP.
- **Password sign-in needs a second factor** when the user has TOTP enrolled
  (any role), or is a privileged user with any factor enrolled. The second
  factor is a current TOTP code or an unused recovery code. A privileged user
  with only passkeys signs in with a passkey, or with password plus a recovery
  code.
- A passkey sign-in satisfies both factors; nothing further is asked.

## 4. TOTP and recovery codes

- TOTP (RFC 6238, 30-second step, 6 digits, SHA-1 for authenticator-app
  compatibility) through `pyotp`, accepting one step of clock drift either
  way. Enrolment shows a QR code and the secret once and needs a valid code to
  complete.
- Secrets are stored encrypted (Fernet) under `AUTH_FACTOR_ENCRYPTION_KEY`.
  Production must set that key; development derives one from `SECRET_KEY`.
  Losing the key makes every TOTP secret unreadable, so it is backed up with
  the other deployment secrets.
- **Replay protection:** the last accepted time step is stored; a code for
  that step or an earlier one is refused.
- **Recovery codes:** ten codes are issued when a user enrols their first
  factor, shown once, and stored only as keyed hashes (HMAC-SHA256 under the
  factor key). Each works once. The user can regenerate them, which voids the
  old set.

## 5. Proof-of-work CAPTCHA

- Local only: no third-party service, no external script, no visitor data
  leaving the server, so no outage elsewhere can block sign-in.
- The server issues a challenge (random salt, difficulty, expiry) signed with
  HMAC-SHA256 under `CAPTCHA_HMAC_KEY` (development derives it from
  `SECRET_KEY`). The browser finds a number whose SHA-256 with the salt meets
  the difficulty, in a Web Worker, and submits it with the email.
- The server checks signature, expiry (five minutes), solution and single use
  (the challenge is recorded in the cache until it expires). A failed check
  returns the email page with a generic message.
- Difficulty is set by `CAPTCHA_DIFFICULTY` and should take about a second on
  a modest phone.

## 6. Enrolment window and enforcement

- `AUTH_FACTOR_ENFORCE_FROM` (an ISO date, set at release to launch + 30 days)
  starts enforcement. Unset means no enforcement.
- Before that date, a privileged user without a factor sees a banner on every
  sign-in asking them to enrol, with the deadline.
- From that date, such a user can still sign in with a password, but every
  page except the factor setup page, logout and static assets redirects to
  setup until a passkey or TOTP is enrolled. There is no lock-out.

## 7. Reauthentication for factor changes

Adding, renaming or revoking a passkey, enrolling or removing TOTP, and
regenerating recovery codes need a sign-in or reauthentication (password or
passkey) within the last ten minutes. A user cannot remove their last factor
while privileged and past the enforcement date.

## 8. Sessions and factor reset

- **Session version.** Each user has an integer session version. Flask-Login
  identifies the session by user ID plus version; a version mismatch logs the
  user out. Sessions issued before this change carry no version and are
  treated as version 0, so they stay valid until the first bump. A factor
  reset, a password reset and a break-glass reset bump the version, ending
  every session and remember cookie for that user.
- **Admin reset.** An admin can reset another user's factors, including
  another admin's; nobody resets their own. It needs a reason, clears the
  user's passkeys, TOTP and recovery codes, bumps the session version, records
  a security event and emails the user. The user then sets up a factor at next
  sign-in if privileged.
- **Break-glass CLI.** `flask auth reset-factors <email> --reason "..."`, run in
  the app container (shell access is the safeguard), does what an admin reset
  does, then emails a magic link. The link is single-use and expires in one
  hour: it carries a fingerprint of the password hash and session version, so
  its first use invalidates it. It leads into onboarding: verify email, set a
  password, then enrol a passkey or TOTP (required for privileged users,
  offered to others). The command prints the link only if mail delivery fails,
  never shows existing secrets, and never creates users or changes roles.

## 9. Audit

Security events are written to `auth_security_events`: passkey registered,
renamed, revoked; TOTP enrolled or removed; recovery codes regenerated or
used; factor reset (admin or CLI, with actor and reason); counter regression;
second-factor lockout. Each records the subject user, the actor (null for
CLI), event type, time and a small non-secret detail. Never credential IDs in
full, public keys, TOTP secrets, codes, challenges or IP addresses.

## 10. Coordination

Per-project SSO (`digitva-roq`, `.tasks/2026-09-26-project-sso-oauth2.md`)
will hook into the email step: once a project uses an external identity
provider, the email step hands off to it instead of showing the second page.
That decision must keep the second page identical for unknown emails.

## 11. Verification

Server-side rules are covered by focused tests. The browser flow is checked
with Chrome's virtual authenticator. Real-device checks (Chrome/Edge on
Windows, Safari and Chrome on macOS, Safari on iOS, Chrome on Android; a
platform passkey, a synced or cross-device passkey and a security key where
available) are recorded with exact OS and browser versions; a passing unit
test is not evidence of platform support.
