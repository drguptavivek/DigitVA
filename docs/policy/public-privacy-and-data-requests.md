---
title: Privacy Policy, Contact Us, and Consent and Data Requests Pages
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-10-27
---

# Privacy policy, contact us, and consent and data requests pages

Tracked in `digitva-gyfj`. Status is draft: the wording below is derived from
existing policy and must be approved by the owner and legal review before the
pages are published. The same URLs serve app store listings (for example
Google Play) that require a public privacy policy and deletion page.

## 1. Pages

Served by Flask with no sign-in, HTML (not PDF), reachable signed out and not
geofenced. Routes in `app/routes/public_pages.py`. `/privacy` and
`/data-requests` are GET only with no form; `/contact` also carries the
contact form (section 7), a normal POST with CSRF.

| URL | Meets |
| --- | --- |
| `/privacy` | Privacy policy, including a Consent section (why consent is asked, purposes required and optional, how it is given and recorded, refusal, withdrawal; from `docs/policy/respondent-consent-notice-draft.md`): who we are, data collected, purposes, sharing, retention, deletion, security, contact |
| `/data-requests` | Consent and data requests: how a respondent withdraws or changes consent, how a user asks for deletion of their account and data, what is deleted, what is kept and for how long |
| `/contact` | Contact us: contact email, grievance officer, postal address, and the contact form (section 7) |

Footer links to all three appear on the front page and the login page. The
in-app link (DigitVA Collect and Collect Plus) is a later change; store
listings use the production host, for example
`https://causeofdeathindia.com/privacy` (demo: `demodigitva.causeofdeathindia.com`).

## 2. Where the content comes from

Nothing is invented; each statement traces to a policy:

- Respondent data, purposes, withdrawal: [respondent-consent-notice-draft.md](respondent-consent-notice-draft.md).
- On-device storage (SQLCipher, one encrypted store per interviewer, purge after
  server acknowledgement, Path C standalone exception, remote wipe on revoke):
  [field-data-collection.md](field-data-collection.md).
- Accounts, sign-in, device sessions: [mobile-sign-in.md](mobile-sign-in.md),
  [account-onboarding-and-passwords.md](account-onboarding-and-passwords.md).
- Narrative AI runs on an operator-controlled workstation in India, no third-party
  service: [narrative-ai-processing.md](narrative-ai-processing.md).
- AI analytics questions: aggregates only, no individual rows, questions go to
  an external AI service, kept under audit-log retention:
  [ai-analytics-questions.md](ai-analytics-questions.md).
- Encryption of personal fields, Aadhaar reduced to last 3 digits:
  [pii-encryption-at-rest.md](pii-encryption-at-rest.md).

Statements the app makes: it does not sell data, show advertising, or track
users across apps or sites; it requests no location, contacts, SMS or
advertising identifier.

## 3. Android permissions the apps request

From `mobile/digitva-collect/app.json` and its Expo plugins:

- `CAMERA`: scan the enrolment QR; photograph the written narrative and documents.
- `RECORD_AUDIO`: record the respondent's account of the death.
- Biometric (`USE_BIOMETRIC` / `USE_FINGERPRINT`, added by `expo-local-authentication`):
  optional fingerprint unlock of the app PIN; the fingerprint never leaves the
  phone's operating system.
- `INTERNET` / network state: sync with the DigitVA server.
- Explicitly blocked: `WRITE_EXTERNAL_STORAGE`, `SYSTEM_ALERT_WINDOW`. Android
  backup is off (`allowBackup: false`). No location permission.

## 4. Deletion and retention wording

Accounts are created and managed by administrators, so deletion is requested by
email to the contact address or through the project administrator.

Deleted on request: the account, sign-in credentials, device sessions and the
profile (name, contact details). Where policy has a fixed rule it is stated on
the page: unsent work on a phone is encrypted and removed when the server
confirms receipt, or when the device is revoked.

Kept: verbal autopsy records of deceased persons, held for the programme under
the respondent's consent, and audit records of who did what. These are
de-linked from the account where policy says so (owner to confirm the exact
mechanism, see placeholders).

Where policy is silent the page uses neutral wording ("for the period required
by the programme and applicable law") and the item is listed below.

## 5. Configuration

Read from `app.config`, env fallback, in `config.py`; documented in `.env.example`:
`PUBLIC_ORG_NAME`, `PUBLIC_CONTACT_EMAIL`, `PUBLIC_GRIEVANCE_OFFICER`,
`PUBLIC_POSTAL_ADDRESS`. Unset values render neutral text ("the DigitVA
programme team"); a section whose value is unset is omitted, never shown with a
placeholder. The owner's personal email is never hardcoded.

## 6. Owner and legal placeholders (open)

1. **Legal entity name** of the developer (`PUBLIC_ORG_NAME`).
2. **Contact email** monitored for privacy and deletion requests (`PUBLIC_CONTACT_EMAIL`).
3. **Grievance officer** name and designation (`PUBLIC_GRIEVANCE_OFFICER`; DPDP).
4. **Postal address** (`PUBLIC_POSTAL_ADDRESS`).
5. **Respondent data retention period** and what happens after: the consent
   notice leaves `[RETENTION PERIOD AND WHAT HAPPENS AFTER]` open.
6. **Deletion request response time** (days to complete after a verified request).
7. **De-linking rule:** whether deleting a coder or interviewer account
   anonymises their authorship on records and audit entries, or keeps it.
8. **Audit-log and backup retention periods.**
9. **Data Protection Officer / Board of India complaint contact** wording.
10. Legal review of the whole text.

## 7. Contact form

Owner request 2026-10-27, tracked in `digitva-gyfj.1`. The form on `/contact`
lets someone without an account write to the programme team.

**Shown only when `PUBLIC_CONTACT_EMAIL` is set.** Unset, the form is hidden
and a POST is refused with a neutral message telling the person to contact
their project administrator.

**Collected:** name (max 100 characters), email address, topic (general
question, consent change or withdrawal, data deletion request, technical
problem) and message (max 4000 characters). Nothing else; no account is
looked up or created. `/data-requests` links to the form with the topic
preselected (`?topic=deletion` or `?topic=consent`); the URL carries no
personal data.

**Email confirmation (double opt-in).** A valid submission is held server
side in the application cache (Redis) for 24 hours under a random 32-byte
token, keyed by the token's SHA-256 so the store never holds a live link. A
confirmation email goes to the given address with a link
`/contact/confirm/<token>`; the link carries only the token, never the
message or the address. Opening the link shows a confirm button (POST with
CSRF), so a mail scanner prefetching the link does not send the message.
Confirming delivers the message once to `PUBLIC_CONTACT_EMAIL` with Reply-To
set to the sender, and deletes the pending entry. A second confirm, or an
expired or unknown link, gets the same neutral "no longer valid" page.

**Retention.** Pending messages expire from the cache after 24 hours and are
then gone. A delivered message lives only in the receiving mailbox, under that
mailbox's retention.
While being sent, the message also passes through the Celery broker (Redis)
as the mail task's arguments (the confirmation task carries the live
confirmation link), removed when the task runs; accepted, since the broker
is the same private Redis as the cache. The per-sender limit folds
plus-tags, and dots for Gmail, so one inbox shares one bucket. Mail logs show
recipients masked (`a***@example.org`). The form is shown only when
`PUBLIC_CONTACT_EMAIL` is set and outgoing mail is configured.

**Neutral responses.** Every valid submission gets the same reply ("if the
address can receive email, a confirmation link is on its way"), whether or not
a send was attempted, so the form does not reveal anything about an address.

**Anti-abuse.**

- CSRF (Flask-WTF) on both POSTs.
- A hidden honeypot field; a filled one gets the neutral reply and nothing is
  stored or sent.
- The proof-of-work CAPTCHA of the sign-in page
  (`app/services/pow_captcha_service.py`,
  [authentication-factors.md](authentication-factors.md) section 5).
- A visible slide-to-slot puzzle (`app/services/slide_captcha_service.py`):
  an animal silhouette with a slot cut out and a slider that moves a piece
  along the track. The challenge is short lived (5 minutes) and single use;
  its id is opaque and the target position stays server side in the cache.
  Any attempt, right or wrong, spends the challenge, so the position cannot
  be found by repeated guesses. Accepted when the piece lands within the
  tolerance of the slot after a plausible drag (minimum duration and number
  of moves). The slider is a native range input, so it works with arrow keys
  and touch. People who cannot use it are told to write to their project
  administrator instead.
- Rate limits per client address on submission (5 per minute, 20 per hour),
  per email address on submission (3 per hour) and on confirmation.

**No personal data in URLs or logs.** URLs carry only the confirmation token
and the topic code. The event log line records the event, the topic and a
keyed hash of the sender's address; never the name, address or message.
