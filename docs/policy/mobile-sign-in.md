---
title: Sign-in by Mobile Number
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-03
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
  second factor where required, rate limits per IP and per account, CAPTCHA.
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
  mobile-only account, or later from the person's details panel, the page
  shows a **one-time numeric code** (6 digits) once. The issuer gives it to
  the person in person or by phone. It expires after 72 hours, is stored
  only as a hash, and issuing a new one voids the old. Who may issue: an admin,
  or someone who may manage **every** active grant the person holds
  (`can_grant`); nobody but an admin issues a code for an admin, a project
  PI, a data manager, an In-charge (`site_pi`), or anyone holding a grant
  the issuer could not write. Privileged accounts (authentication-factors.md
  section 3) get their codes from an admin. A code lets its
  redeemer sign in as the person, so partial authority over them is not
  enough.
- **Redeeming it.** On the sign-in page the person chooses "I have a code",
  enters their mobile number and the code. If both match, the server
  generates a new password and shows it **once**, on that screen only, with
  a prompt to write it down or save it. The code then stops working. The
  same screen offers to add a passkey.
- **The generated password**: words and digits that are easy to read aloud
  and type on a phone keypad (for example three short words and a 4-digit
  number), at least 16 characters, from a cryptographic random source,
  checked against the breach list (password-breach-checks.md). It is never
  stored in clear, emailed, logged, or shown to the data manager.
- **Changing or forgetting it.** The person cannot set a password of their
  own. When signed in they may ask for a new generated password (after
  reauthentication); if they forget it, their data manager issues a new
  code. Either way the old password stops working and existing sessions
  end.
- **Guessing.** Code attempts are rate-limited per IP and per mobile
  number; five wrong codes void the code (a new one must be issued). A wrong
  number and a wrong code give the same answer.
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
