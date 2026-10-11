---
title: Login Passwords and Passkeys
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-11
---

# Login Passwords and Passkeys

This policy applies to web sign-in and to the native collection app. A user
may sign in on the web with either the account password or a registered
WebAuthn passkey. This includes administrators and data managers. There is no
TOTP, recovery-code, or mandatory-factor requirement.

Existing encrypted TOTP and recovery-code records may remain as inert history;
they are not read during sign-in and are not bulk-deleted by this change. Old
factor endpoints and setup gates are removed or disabled. Account verification,
active status, maintenance, access grants, session versions, rate limits and
CSRF protections continue to apply.

## 1. Web login

1. The user enters an email or mobile number. The browser completes the local
   proof-of-work challenge, and the server stores a five-minute pre-auth state
   without creating a login session.
2. The second page is indistinguishable for known and unknown identifiers. It
   offers both the password form and a passkey button. A discoverable passkey
   challenge has no `allowCredentials`, so the page does not reveal whether an
   account exists or has a passkey.
3. A correct password or a verified passkey completes sign-in. Neither path
   asks for another factor.

Unknown, inactive, or incorrectly authenticated accounts receive the existing
generic response. A correctly authenticated but unverified account receives
the existing verification notice. Safe redirects, CAPTCHA, per-IP and
per-identifier limits, maintenance checks, and audit events remain in force.
The server binds a passkey challenge to the pre-auth state, expires it after
five minutes, and atomically claims it once before verification. If the claim
store is unavailable, passkey verification fails closed.

## 2. WebAuthn passkeys

WebAuthn uses the configured relying-party ID and origin through the standard
`webauthn` library. User verification is required, so the browser or platform
authenticator may use a device PIN, device password, or biometric. A biometric
sensor is not required by the server. Production RP ID remains
`digitva.causeofdeathindia.com` with its existing HTTPS origin. Changing the
RP ID invalidates registered passkeys; this change does not alter it.

Passkeys are optional. A user may register, name, rename, and revoke several
credentials from the browser Profile. Registration, renaming and revocation
require recent password or passkey reauthentication and a browser session with
CSRF protection. A bearer device token cannot change account factors.

Credential ownership, signature validation, replay-counter handling, account
verification and status, maintenance, and access grants are checked before a
session is issued. A counter of zero on both sides is accepted for synced
credentials; a non-zero regression is refused and audited.

## 3. Native collection app

Native passkey sign-in is deferred until the signed Android and iOS identity
and domain-association work is complete. The native app signs in with the
account password and an enrolled device, subject to the normal verification,
status, maintenance, and collection-access checks. It has no administrator or
data-manager functionality, even when the account has one of those roles.

After native sign-in, the encrypted local collection store is unlocked with
the user's PIN or optional device biometric. This is a local data-protection
step, not a second-factor request and not a source of server permissions. A
biometric template or image never leaves the operating system.

Device bearer credentials remain limited to supported collection and coding
APIs. They cannot authorize administrator or data-manager web functions.
Device revocation, account status changes, session-version changes, grant
checks, refresh-token rotation, and unsent-data recovery rules remain in
force.

## 4. Reauthentication, recovery and sessions

Security-sensitive Profile changes require recent password or passkey
reauthentication. Password generation and reset continue to use the verified
email or the controlled mobile sign-in-code flow described in
[account-onboarding-and-passwords.md](account-onboarding-and-passwords.md).
An administrator may reset another user's passkey credentials through the
audited reset flow; the reset bumps the user's session version, may clear
inert legacy factor records, and sends the account a reset notice. The
`flask auth reset-factors` recovery command emails a single-use, one-hour link;
GET displays a confirmation and only a CSRF-protected POST signs the user in. The account's generated password remains a
valid alternative after recovery. An administrator may not use the admin reset
action on their own account.

Every completed sign-in records its method (`password` or `passkey`) and the
subject, actor, time, and non-secret result. Failed attempts record only a
safe reason. Credential IDs, public keys, passwords, challenges, biometrics,
and other secrets are never logged.

Completed web sign-ins also record the validated client IP in the security
event, using the existing one-hop trusted proxy configuration. IPs are removed
from those events after 210 days by the daily retention job; the event itself
remains. Other security events and application logs do not gain IP fields.

A password reset, account deactivation, factor-record reset, or explicit
session-version bump ends existing sessions according to the normal session
rules. No destructive migration is required for inert legacy TOTP data.

## 5. Verification

Server tests cover password and passkey success and failure, account gates,
challenge expiry and replay, credential ownership, counter handling, CSRF,
reauthentication, rate limits, and session invalidation. Browser tests with a
virtual authenticator cover the WebAuthn path. Real browser and native-device
testing must record the OS, browser/app version, and the authenticator used;
unit tests do not establish platform support.

Shipped endpoint and response details are in
[Authentication, Login and Onboarding](../current-state/authentication-and-onboarding.md).
