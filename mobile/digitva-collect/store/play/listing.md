# DigitVA Collect: Google Play listing

Bead `digitva-91f2`. Applies only to the plain Collect app
(`com.causeofdeathindia.digitvacollect`). Collect Plus (`.plus`) is adb-only
and never goes on Play. Paste each section into the Play Console page with
the same name.

## Files in this folder

| Play Console field | File | Play requirement |
| --- | --- | --- |
| App icon | `icon-512.png` | 512×512, 32-bit PNG with alpha, ≤1 MB |
| Feature graphic | `feature-graphic-1024x500.png` | 1024×500, JPG or 24-bit PNG, no alpha |
| Phone screenshots | `screenshots/*.png` | 2–8 images, no alpha, 320–3840 px, long side ≤ 2× short side. 1080×1920 also qualifies for promotion |

## App details

- **Package name:** `com.causeofdeathindia.digitvacollect`. It cannot change after the first upload.
- **App name (≤30):** `DigitVA` (owner, 2026-10-27; matches the launcher label).
- **Default language:** English (United Kingdom) – en-GB, or English (India) if offered.
- **App or game:** App
- **Free or paid:** Free
- **Category:** Medical
- **Tags:** Health research, Data collection
- **Contact email:** info@causeofdeathindia.com
- **Website:** https://digitvav3.causeofdeathindia.com
- **Privacy policy URL:** https://digitvav3.causeofdeathindia.com/privacy

## Short description (≤80)

```
Offline, encrypted WHO verbal autopsy interviews for enrolled field teams.
```

(74 characters)

## Full description (≤4000)

```
DigitVA Collect is the field app of DigitVA, a verbal autopsy platform for finding out the causes of deaths that happen outside hospitals. Trained field workers use it to register deaths in their area and to interview the family using the WHO 2022 verbal autopsy questionnaire.

Project staff enrol with a QR code and an account from their DigitVA administrator. Reviewers can use the built-in demo with synthetic data.

WHAT YOU CAN DO
• Register a reported death and the household's contact details
• See your assigned cases and schedule follow-up visits
• Conduct the WHO VA 2022 interview, section by section, with built-in skip logic and checks
• Record the respondent's narrative as audio, or photograph a written narrative and documents
• Save drafts and resume interviews later
• Save completed interviews locally and send them in the background to your project's DigitVA server
• Authorized coders can work on online cases in the app
• Multilingual: interview in any language your project enables (English and Hindi today)

WORKS OFFLINE
Interviews are often done in places with poor or no network. DigitVA Collect keeps your cases, drafts and attachments on the phone and sends them when you are back online. Unsent work stays encrypted on the phone through sign-out and device decommissioning; sign back into the same account to resume sending it.

PRIVACY AND SECURITY
• All data on the phone is kept in an encrypted database
• A PIN, or your fingerprint or face, unlocks the app
• Data travels only over HTTPS, and only to your project's DigitVA server
• Android backup is turned off, so interview data is not copied to cloud backups
• No advertising or third-party tracking; optional minimal performance diagnostics on the programme server

ABOUT DIGITVA
DigitVA is run by the Centre for Community Medicine, AIIMS, New Delhi, for public-health research on mortality. Trained, authorized coders can use the shared online coding workspace from the app or website. The public app uses the programme server for coding; it does not include the experimental offline coding engine.

Need help? Contact your project administrator, or visit https://digitvav3.causeofdeathindia.com/contact
```

Organisation and contact match `PUBLIC_ORG_NAME` / `PUBLIC_CONTACT_EMAIL` on staging (2026-10-27).

## App content (Policy → App content)

| Section | Answer |
| --- | --- |
| Privacy policy | URL above |
| Ads | No, the app contains no ads |
| App access | **All or some functionality is restricted.** See "App access instructions" below |
| Content rating | Questionnaire category "Utility, Productivity, Communication or Other". Answer No to violence, sexual content, language, controlled substances, gambling. The app discusses death in a clinical survey context; no graphic content. Users can't interact with each other; no location sharing; no purchases. Expected rating: Everyone / IARC 3+ |
| Target audience | 18 and over only. Not designed for children |
| News app | No |
| COVID-19 contact tracing/status | No |
| Data safety | See below |
| Government app | Owner decides. Yes only if the app is published on behalf of a government body (e.g. ICMR) |
| Financial features | None |
| Health apps declaration | Declare health features: choose the human-subjects / health research and medical/clinical data-collection options where offered. Also assess the clinical decision-support declaration for the authorized online coding workspace against the final distributed artifact |
| Account deletion | Yes, users can create accounts (demo self-signup). In-app path: Settings → "Delete my account" (`digitva-et16`; demo accounts delete themselves after re-entering the password, staff accounts send a request the team confirms; audit history is kept). Web link: https://digitvav3.causeofdeathindia.com/data-requests |

### App access instructions (for Google's reviewers)

Preferred: give Play a kept demo account. The owner creates one on https://digitvademo.causeofdeathindia.com via "Try the demo", marks it kept in Admin → Users (`digitva-xfxb`, landed in 81729c869, so the purge and cap eviction skip it), and enters its username and password in Sign-in details. Reviewers then use "Try the demo" → sign in. Fallback, if no account is given: name `Self-service demo account`, no credentials, and the steps below.

```
No credentials are needed. Field workers' accounts are issued by their project administrator via a QR code, so reviewers should use the built-in public demo:
1. Open the app. On "Enrol this device", tap "Try the demo".
2. Choose any username (lower-case, starting with a letter) and a password of 12+ characters, tick the notice, and tap "Create account and start".
3. Set any PIN of 6 or more digits.
All collection features (register a death, interview, consent, drafts, sync) work on the demo with practice data.
```

Owner decision 2026-10-27: the kept flag is for the Play review account only. A self-registered reviewer account is not kept, so with the fallback keep the demo up during reviews and the account cap high enough that it is not evicted mid-review.

## Data safety form

Checked against Google's Data safety help (support.google.com/googleplay/android-developer/answer/10787469, read 2026-10-27). "Collect" means the app sends the data off the phone; "share" means passing it to a third party. Data the field worker enters about the deceased and the respondent is sent to the server, so it counts as collected even though it is not about the app user (the help page is silent on third-party data; declaring it is the conservative reading).

### Overview answers

- Does the app collect or share any of the required user data types? **Yes**
- Is all of the user data collected by your app encrypted in transit? **Yes** (HTTPS only; release builds refuse a non-HTTPS server, `app.config.js`, `src/enrolment.ts`)
- Do you provide a way for users to request that their data is deleted? **Yes**: https://digitvav3.causeofdeathindia.com/data-requests (no automatic deletion within 90 days, so no auto-delete badge)
- Independent security review (MASA): **No**

### Sharing: answer No for every type

Each outward flow fits an exemption on the help page:

| Flow | Why it is not "sharing" |
| --- | --- |
| Hosting and storage (AWS servers, S3) | Service provider acting on the developer's instructions |
| Government and statistical reports | Counts and summaries only: anonymous data |
| AI analytics questions (Gemini on Vertex AI) | Model sees aggregates only, never a submission (`docs/policy/ai-analytics-questions.md`) |
| Narrative AI | Runs on systems the operator controls in India; no third-party AI service (`docs/policy/narrative-ai-processing.md`) |
| Research repositories | Only if fully anonymised. **Owner check:** if shared records are de-identified but not anonymised, declare Health info as shared, or rely on the respondent's recorded in-app consent and say so |

### Data types collected

"Optional" only where every user can skip it (help page rule); everything else is "Required". None is processed ephemerally; all is stored on the server.

| Data type (Play name) | Required / optional | Purposes | What it is |
| --- | --- | --- | --- |
| Personal info → Name | Required | App functionality | Deceased, respondent and field-worker names |
| Personal info → Email address | Optional | Account management | Field worker's sign-in identifier, when they sign in by email |
| Personal info → User IDs | Required | App functionality, Account management | Field-worker account and username |
| Personal info → Address | Required | App functionality | Household address of the deceased |
| Personal info → Phone number | Optional | App functionality, Account management | Respondent contact for follow-up; field worker's sign-in by mobile number |
| Personal info → Race and ethnicity | Optional | App functionality | Social group (caste category) asked when a project enables the `equity` layer; has "Prefer not to say" |
| Personal info → Other info | Required | App functionality | Age, sex, dates of birth and death; optional Aadhaar (last 3 digits) and ABHA |
| Health and fitness → Health info | Required | App functionality | The WHO VA questionnaire: illness and events before death |
| App activity → Other user-generated content | Required | App functionality | Typed narrative and remarks |
| Audio files → Voice or sound recordings | Optional | App functionality | Respondent's spoken narrative |
| Photos and videos → Photos | Optional | App functionality | Photo of the written narrative and documents |
| Device or other IDs | Required | App functionality; Fraud prevention, security and compliance | Server-issued device ID from enrolment (`src/auth.ts`) |

Not collected: location (no location permission; place of death is part of Address), financial info, messages, files and docs, calendar, contacts, web browsing, installed apps, installed-app lists or third-party tracking. First-party app performance diagnostics are collected as described below.

## Release notes (first release)

```
First Google Play release: offline collection, authorized online coding, queued submissions, account/device controls and optional first-party performance diagnostics (Settings off switch).
```

## Before upload

1. Build the signed AAB with `android-play-bundle.yml`; downloadable APKs remain supported by the separate APK workflow. The Play flag hides hosted APK updates and uses a versionCode above the same version's APKs. These workflows prepare artifacts only.
2. Owner must choose Play App Signing/upload keys and verify continuity with existing installed APKs. Changing the app-signing certificate can prevent updates; never require uninstalling a phone with unsent work.
3. Deploy the matching privacy, deletion and app/server changes only after owner approval. Listing URLs must describe the deployed artifact; code preparation does not update the live site.
4. Recheck target API, merged-manifest permissions, health-app declarations and current developer-account testing requirements at submission time.
5. Prepare a synthetic kept reviewer account and complete demo consent/grievance contact details. Keep the demo available throughout review. Review artwork and screenshots separately (`digitva-91f2`).
6. Verify Data Safety against all distributed versions and final payloads. Minimal telemetry is enabled with a Settings off switch; internal clinical timelines follow existing programme-data access.

## 2026-10-28 release and Data Safety update

This release adds optional first-party performance diagnostics, enabled by
default with an off switch in Settings. Update the Play form for App info and
performance (crash/diagnostic counts and other performance data), and App
activity (approximate aggregate foreground use). Purpose: analytics/application
improvement; optional collection because the app works with diagnostics off.
No third-party analytics SDK or third-party telemetry destination is used.
No interview/coding rows, case identifiers, raw logs, stable device identifiers
or GPS measurements enter this diagnostic payload. Country context, when
available, is derived from the programme's existing project setting.

Internal interview/coding phase timestamps are part of submission data and
follow existing health/programme data declarations and authorization; they
are separate from diagnostics. Update the privacy URL before distributing
this version. Diagnostics aggregates/random retry keys expire after 90 days.
Turning diagnostics off deletes pending local batches; previously combined
aggregate counters cannot be subtracted individually.

Google's form treats transmission to the developer's own server as collection;
review the completed form against all distributed versions, not just the new
build. Source checked 2026-10-28:
[Play Data Safety guidance](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en).
[Account deletion guidance](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en).

Release formats: signed Play AAB and downloadable APKs. Local emulator debug
APKs use HMR and are not store artifacts. No store upload is performed by
preparing this package.
