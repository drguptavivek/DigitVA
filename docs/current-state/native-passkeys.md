---
title: Native Passkey Status
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-11
---

# Native passkeys

Native passkey sign-in is deferred. The collection app currently signs in
with the account password and an enrolled device. After sign-in, its local
encrypted store is unlocked with the account PIN or optional device biometric;
this local unlock applies to every device-eligible account, including one
that also holds administrator or data-manager roles, and does not provide administrator or data-manager functions.

Web passkeys remain available from the browser Profile. Web sign-in accepts a
password or a registered passkey for every role. The browser flow still
requires recent reauthentication and CSRF protection for passkey management,
and keeps the normal account verification, status, maintenance, access and
session checks.

The native passkey bridge and its Android certificate, Apple Team ID, domain
association, signed-build, and physical-device checks are intentionally
deferred. Do not configure a debug signing certificate as a production trust
identity, and do not describe native passkeys as an active login path until a
signed release has passed those checks.

The existing encrypted-store protections remain: PIN and biometric material
stay in the operating system's protected storage, the server receives no
biometric image or template, and device bearer credentials remain limited to
the supported collection and coding APIs.
