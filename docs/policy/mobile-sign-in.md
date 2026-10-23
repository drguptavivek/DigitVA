---
title: Sign-in by Mobile Number
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-24
---

# Sign-in by Mobile Number

Field staff such as ANM and ASHA often have no email address of their own.
Owner decision 2026-10-03 (digitva-l7c2): such a person signs in with their
mobile number, so long as that number is present and unique. This page is
the baseline for the mobile-number details; onboarding and passwords for
every account are in
[account-onboarding-and-passwords.md](account-onboarding-and-passwords.md),
and [authentication-factors.md](authentication-factors.md) still governs
everything not said here.

## 1. Identity

- An account has an email, a mobile number, or both. One of the two is
  required; an account with neither cannot be created.
- **Mobile number form.** A 10-digit Indian mobile number. On input, keep
  digits only and drop a leading `0` (11 digits) or `91` (12 digits); what is
  left must be exactly 10 digits. The stored and compared value is that
  canonical number (the rule the DM lookup already uses, digitva-i0zb).
- **Creation forms.** Admin Users and Add worker accept exactly ten digits
  for a supplied mobile, checked in the browser and again on submission. A
  new account without email requires the same number entered twice. The
  sign-in and import canonicalization rules above remain available.
- **Unique.** No two accounts may hold the same canonical number. Creating
  an account, importing users or editing a phone number refuses a number
  another account holds, with a plain message.
- **Existing data.** Accounts that already share a number, or hold a number
  that is not 10 digits, keep signing in by email and cannot sign in by
  mobile until a data manager or admin corrects the number. Dev and
  production (identical) have two shared numbers (each looks like one
  person with two accounts) and four 9-digit numbers; these are listed for
  correction, never changed automatically.

## 2. Sign-in

- The first login step takes "Email or mobile number". A value containing
  `@` is an email; anything else is read as a mobile number.
- Everything else in authentication-factors.md section 1 applies unchanged:
  the same second page for every value (known or not), passkey or password,
  no additional factor, rate limits per IP and per account, and CAPTCHA. The
  native app's device sign-in (field-data-collection.md) takes the same email
  or mobile number with the same rules and the same indistinguishable answer
  (digitva-kmoy).
  A mobile number that matches no account, or matches a number shared by
  two accounts, gets the same page and the wrong-credentials result, never a
  message saying which.
- A mobile number becomes usable for sign-in when its holder first redeems
  a code (section 3), or when the account's email is verified (onboarding
  policy section 5.1).

## 3. Server-generated password, released by a one-time code

Owner decision 2026-10-03: mobile-only accounts never choose their own
password. The server generates it, so every such password meets the
hygiene rules by construction. There is no SMS provider; the data manager
passes a short numeric code to the person instead.

- **Issuing a code.** When a data manager, In-charge or admin creates a
  mobile-only account (on the web page, the project user import or as
  mentoring-institute staff), or later from the person's details panel --
  for an account without a verified email (mobile-only, or an email never
  verified; an admin may issue for any account, digitva-kmoy) -- the page
  shows a **one-time numeric code** (6 digits) once. The issuer gives it to
  the person in person or by phone. It expires after 72 hours, is stored
  only as a hash, and issuing a new one voids the old. Who may issue: an admin,
  or someone who may manage **every** active grant the person holds
  (`can_grant`); nobody but an admin issues a code for an admin, a project
  PI, a data manager, an In-charge (`site_pi`), or anyone holding a grant
  the issuer could not write. An admin may issue a code for an administrator
  or data-manager account. A code lets its
  redeemer sign in as the person, so partial authority over them is not
  enough. When a code is redeemed for an account with any email on file,
  that address is sent a short notice ("your password was changed using a
  sign-in code; if this wasn't you, contact your administrator") carrying
  no password and no code.
- **Redeeming it.** On the sign-in page the person chooses "I have a code",
  enters their email or mobile number and the code. If both match, the server
  generates a new password and shows it **once**, on that screen only, with
  a prompt to write it down or save it. The code then stops working. After
  signing in, a web user may add a passkey from Profile.
- **The generated password**: words and digits that are easy to read aloud
  and type on a phone keypad (for example three short words and a 4-digit
  number), at least 16 characters, from a cryptographic random source,
  checked against the breach list (password-breach-checks.md). It is never
  stored in clear, logged, or shown to the data manager; an account with a
  verified email gets later passwords by email
  (account-onboarding-and-passwords.md section 6).
- **Changing or forgetting it.** The person cannot set a password of their
  own. When signed in they may ask for a new generated password (after
  reauthentication); if they forget it, their data manager issues a new
  code. Either way the old password stops working and existing sessions
  end.
- **Guessing.** Code attempts are rate-limited per IP and per identifier;
  five wrong codes void the code (a new one must be issued). A wrong email
  or number and a wrong code give the same answer.
- **Audit** records who issued a code and when, and when it was redeemed,
  never the code or the password.

- **Changing the email of a mobile account.** A data manager may set or
  change the email only on an account that has never signed in. After
  that only an admin can, and any email change clears verification, ends
  the person's sessions and sends a verification link to the new address.
  Otherwise an issuer could point the account at their own mailbox and
  take it over through "Forgot password".

## 4. Not changing

Email accounts sign in exactly as today. Mobile numbers are not shown to
unit data managers in search or lookup results
([dm-user-grant-management.md](dm-user-grant-management.md)). A mobile
number is personal data: kept out of logs, exports and URLs.

A mobile number signs in on the app like an email. The app accepts any
account that holds an interviewer, coder, coding_tester or reviewer grant that
opens its gate in at least one project, not only interviewers (owner,
2026-10-05; [Field Data Collection](field-data-collection.md), "Who may sign
in on a device").

## 5. App distribution

The signed-in Help page's **Get the Mobile App** guide links to the approved
Android APK only when the deployment supplies a credential-free HTTPS release
URL. Until a release is published, it directs users to the browser application
and tells them to obtain the approved link from an administrator. DigitVA does
not guess a GitHub release URL or publish an APK from the application server.

## 6. Enrolment email for new data collectors (digitva-o0nq)

Owner decision 2026-10-22: when Add worker gives a person (new or linked) a
new or reactivated `interviewer` or `death_reporter` grant, the server emails
that person the app enrolment QR, so the data manager need not be beside
them. Coders and other roles get no such email.

- **Same QR as the Devices page.** The email carries the same QR the
  project's Devices page shows (owner decision): a project enrolment code
  issued through the same service, with the same payload, plus the code as
  text. Each email gets its own code, valid for **24 hours and one device**
  (within the Devices page's 5 minutes to 7 days). The QR enrols a device;
  the person still signs in with their own email or mobile number and
  password and then sets the device PIN.
- **Contents.** The QR as an inline image, the code text, the approved
  Android APK link (section 5; when no valid link is configured the email
  says the supervisor will share the app), and steps: install from the link,
  allow installs from that source, open the app, scan the QR from another
  screen (a computer, or a second phone; the phone being enrolled cannot
  scan its own screen), sign in, set a PIN. English only: email templates
  have no language selection.
- **When.** After the save is committed, never inside it, and synchronously,
  never through the task queue, because the code is a credential (like the
  password emails, account-onboarding-and-passwords.md section 4). A failed
  send never fails the save: the save reports "Enrolment email could not be
  sent" and logs the project and user ids only. A re-save that adds no new
  data-collector grant sends nothing. An account with no email gets no
  email; use the Devices page QR. `MAIL_SUPPRESS_SEND` and
  `EMAIL_DELIVERY_ENABLED` apply as to every email.
- **Resend.** An admin, or a project PI who may manage the project, may
  resend from the worker row; each resend issues a fresh code. This is also
  the owner's decision that a project PI may cause an enrolment code to be
  issued, which the Devices page still limits to admins.
- **Users page (owner, 2026-10-22, digitva-75wn).** The web app's Users
  page offers **Issue enrolment code** on a listed user who holds an active
  `interviewer`, `death_reporter`, `coder`, `coding_tester` or `reviewer`
  grant (the device roles; coders for the coder app to come) in the chosen
  project. Owner decision: besides admins and project PIs, a **data
  manager** (the In-charge included) may issue it, for a user whose such
  grant lies inside their own subtree, so a district data manager need not
  ask the PI. The target account must be active. Two deliveries:
  - **Show**: a project enrolment code with the Devices page's rules
    (default 60 minutes and one device; 5 minutes to 7 days, up to the
    Devices page's use limit), shown once in a dialog as code and QR; the
    server keeps its hash only. Only an admin may widen it: a PI or data
    manager gets one device within at most 60 minutes, since the code
    enrols any phone into the whole project (`code_too_wide` otherwise).
  - **Email**: the section above's email (its own 24-hour, one-device code).
  Every issue is audited as `device_enrolment_code_created` with the actor
  and the user it was issued for. 10 requests a minute.
- **Risk.** Anyone who reads the email can enrol a device to the project
  within the 24 hours. Enrolment alone gives no data: every session still
  needs the person's password. An admin can revoke any device on the
  Devices page, which ends its sessions.

## 7. Enrolment server (digitva-k4jt)

Owner decision 2026-10-22. The enrolment QR names the server; the Android app
checks it against a rule compiled into the build (`src/enrolment.ts`,
`acceptedServerOrigin`), so a forged QR cannot point the phone at a server
that would collect an interviewer's password.

- **Release builds** accept an `https` origin whose host is exactly
  `causeofdeathindia.com` or ends with `.causeofdeathindia.com`, matched by
  whole DNS labels after lower-casing: production
  (`digitva.causeofdeathindia.com`), staging
  (`digitvav3.causeofdeathindia.com`) and any other host the organisation
  puts under its domain. Refused: `http`, a non-default port, user
  information, a path, query or fragment, look-alikes such as
  `evilcauseofdeathindia.com` or `causeofdeathindia.com.evil.io`, a trailing
  dot or empty label, and Unicode look-alike hosts (they parse to `xn--`
  labels that do not match). The build's `EXPO_PUBLIC_API_BASE_URL`, when
  set, is one more exact origin accepted.
- **Debug builds** also accept exactly `http://10.0.2.2:8051` and
  `http://localhost:8051`.
- **Before redeeming**, the enrol screen shows the server host and project
  and waits for the user to confirm.
- The server pages the app opens (code redemption, forgotten password) use
  the same rule.
- **Changing server is re-enrolling.** Settings shows the enrolled server
  read-only. **Change server / re-enrol** is refused while any interviewer on
  the phone has unsent work (drafts, registrations, queued case actions,
  revisions) or a locked store whose contents cannot be counted; the refusal
  names each interviewer and says to unlock and sync. When nothing is unsent
  it asks once, signs every interviewer out (the ordinary sign-out wipe) and
  drops the enrolment, then opens the enrol screen for the new server's QR.

## 8. Sign-in QR (owner decision 2026-10-23; server and phone scan built, Users-page screens pending)

**Approved by the owner 2026-10-23; server built** (digitva-3g19: tables,
issue, redeem, revoke, status and audit; the phone scan screen and the Users
page controls follow). Sections 1 to 7 stay authoritative.

Today a new data collector needs two things: the enrolment QR (a device
credential, section 6) and then their own password. This proposal lets one
scan do both for the least-privileged accounts.

- **Who.** A user holding an active `interviewer` or `death_reporter` grant.
  Never for an admin, project PI, data manager, In-charge, coder, coding
  tester, reviewer or any other privileged account. If the person also holds
  any such other grant, in any project, no sign-in QR is offered or redeemable
  (checked at issue and again at redeem); they get the enrolment QR and
  password sign-in only.
- **What one scan does.** It enrols the device (as `enrol_device` does today)
  and opens the normal device session for that one user: same device API
  scope only, same 15-minute access and sliding refresh lifetimes, same
  `has_device_access` check, pending-terms behaviour, reuse detection and
  revocation as a password sign-in. The app then runs PIN setup and the
  biometric / screen-lock prompt as after any sign-in. No password is typed
  or created.
- **Token.** `secrets.token_urlsafe(32)`, stored only as its SHA-256 hash,
  never logged, never shown again after issue. Single use; bound to one user
  and to the user's `auth_session_version` at issue (sign out everywhere, a
  password or factor reset voids a pending QR), and to the one device that
  redeems it first (that enrolment records the
  token as `enrolled_via`). Expires after **6 hours**. Issuing a new one voids the previous. Redeem is rate-limited per
  IP, per device and per token, and a wrong token gives one indistinguishable
  answer. Revocable from the Users page.
- **Delivery.** Emailed only to a **verified** email address of that user, as
  QR and code text; the email says it signs them in on the phone and to report
  it if they did not expect it. Or shown on screen once to an admin, with the
  person present, on the same Users page rules as section 6. An account
  without a verified email (mobile-number-only included) gets the on-screen,
  in-person delivery only. Who may issue: an admin, a project PI, or a data
  manager who may manage every active grant the person holds (the section 3
  `can_grant` rule), 10 requests a minute.
- **Audit** (security events, never the token): `sign_in_qr_issued` (actor,
  user), `sign_in_qr_redeemed` (device id), `sign_in_qr_expired` and
  `sign_in_qr_revoked` (actor). A redeem also sends the user's email address
  a notice ("this phone was signed in with a sign-in QR; if this wasn't you,
  tell your supervisor"), no token in it, sent only to a **verified** address.
  A redeem refused because the person is no longer eligible, or because their
  sessions were reset since issue, audits `sign_in_qr_refused` (reason, no
  token).
- **Threat model.** Whoever holds an unredeemed token becomes that person on
  a phone: a compromised mailbox, a forwarded email or a photographed QR
  grants device-API access to the user's cases until redeemed or expired.
  Mitigations: single use; short expiry; one device binding; notification on
  redeem; the user and supervisors can see and revoke devices (revoking ends
  the sessions); the phone still demands the PIN and screen lock on every
  unlock; the credential reaches only the device API, never web pages,
  account-security APIs or any admin or supervisory power; privileged roles
  are excluded outright. Residual risk: the window before redeem, and a
  stranger redeeming first. This is weaker than password sign-in, which
  needs something the person knows.
- **Show-QR needs no verified sign-in.** Redeem does not require the person's
  `sign_in_verified` flag: the issuer hands the on-screen QR over in person and
  so verifies who is holding the phone. The email route is limited to a
  verified address for the same reason.
- **What stays.** Password sign-in (email or mobile, section 2) and the
  one-time code (section 3) are unchanged. The enrolment QR (device only,
  sections 6 and 7) continues for everyone else, including all roles above.
  The app's server-origin rule (section 7) applies to this QR too.
- **Owner decisions (2026-10-23).** Expiry 6 hours; delivery by verified
  email or on screen in person; one scan, no second code at redeem; issued by
  an admin, a project PI or a data manager under the section 3 `can_grant`
  rule; first-time accounts (no password set yet) are the main use.

Shipped endpoints, fields, rate limits and error codes: [Authentication, Login and Onboarding](../current-state/authentication-and-onboarding.md).

## 9. Phone unlock: PIN boxes, fingerprint, phone screen lock (owner 2026-10-23, digitva-mhjg)

The device PIN (6 to 16 digits in `src/vault.ts`; the entry and setup screens
take **six digits**, one per box) keys the interviewer's encrypted store. The
rules of sections 1 to 8, the 3-wrong-PIN warning and the wipe on the 5th wrong
PIN in a row are unchanged.

- **Entry.** PIN entry and PIN setup use six separate boxes: one digit each,
  moving on as a digit is typed, backspace stepping back, the numeric keypad
  opening at once, masked with a Show / Hide toggle, and a pasted six-digit
  PIN filling every box. A wrong PIN clears the boxes and shakes them.
- **Unlock options**, per account on this phone, all optional; the app PIN is
  always the fallback (cancelled or failed prompt, a lost option such as a new
  fingerprint enrolment or a removed screen lock):
  - **Fingerprint** (existing): the PIN is kept behind a Keystore key usable
    only after a strong biometric.
  - **Use phone screen lock** (new): `expo-local-authentication` asks the
    phone's own lock (fingerprint, face, pattern, PIN or password, as the
    phone allows, device-credential fallback). On success the app releases
    the PIN it holds in Keystore-backed SecureStore. Weaker than the
    fingerprint option, which binds the key itself to the biometric: the PIN
    sits in Keystore without per-use authentication and the prompt is an app
    check, so a rooted phone running modified code could skip it. It is
    offered only when the phone has a screen lock set.
  Turning an option on needs the PIN (or the first-run PIN just set) and one
  successful prompt. Wipe, sign-out and re-enrolment erase both entries.
- **First-run prompt.** After the first PIN setup the app offers, once and
  skippably, fingerprint and phone screen lock (whichever the phone supports).
  If skipped it is offered **once more** on a later PIN unlock, then never
  again; nothing is offered when an option is already on or the phone
  supports neither. Settings can turn either option on or off at any time.
