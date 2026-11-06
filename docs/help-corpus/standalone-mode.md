---
title: How-Do-I Corpus - Standalone Mode (Collect Plus)
doc_type: help-corpus
status: draft
owner: engineering
last_updated: 2026-11-06
---

# How-Do-I Corpus - Standalone Mode

Standalone mode is DigitVA Collect Plus used on one phone with no server:
interviews and coding stay on the phone. It is offered only in the Plus app on
a supported 64-bit Android phone, on pilot phones. Format and truth rules:
`docs/policy/help-chatbot.md` ("How-Do-I corpus"). Labels are copied from
`mobile/digitva-collect/src/strings/en.json` and `theme-en.json`. Policy:
`docs/policy/field-data-collection.md` ("Path C: standalone Collect Plus").

Not available in standalone mode: server sync, **Send now**, the Sync tab,
sending records to a server, and coding or review on the web. Records stay on
the phone.

### What is standalone mode, and who can use it?

- id: hdi-standalone-001
- roles: interviewer
- surfaces: android
- steps:
  1. Install DigitVA Collect Plus (the plain Collect app does not offer standalone mode).
  2. On the first screen choose **Use on this phone only** ("No server. Interviews stay on this phone").
  3. Complete the standalone setup (see the setup entry).
- notes: The phone shows "Standalone Mode - Server Disabled". It collects interviews and codes them on the device. "Records stay on this phone. Back them up regularly. Uninstalling the app or losing the phone can erase them." Standalone has no server record of what the phone holds, so a lost phone cannot be wiped remotely. It is meant for pilot phones controlled by the project owner.
- sources: mobile/digitva-collect/src/nativeRoutes/enrol.tsx; mobile/digitva-collect/src/strings/en.json; mobile/digitva-collect/src/strings/theme-en.json; docs/policy/field-data-collection.md
- checked: 2026-11-06

### How do I set up standalone mode?

- id: hdi-standalone-002
- roles: interviewer
- surfaces: android
- steps:
  1. On the first screen tap **Use on this phone only**.
  2. In **Standalone setup** ("Enter your details, then set a PIN.") fill in your profile: name, age, sex, designation, facility, country and state, and the HIV and malaria levels (designation, facility and state are optional). All fields are shown at once in setup.
  3. Tap **Create standalone account**.
  4. Set a PIN (at least 6 digits), then choose a fingerprint or phone screen lock if offered.
- notes: "Standalone mode could not be set up on this phone." means setup failed; try again. Name uses letters A to Z and spaces; age is 18 to 89, or 99 if not stated.
- sources: mobile/digitva-collect/src/nativeRoutes/standaloneSetup.tsx; mobile/digitva-collect/src/nativeRoutes/standalone.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### Why is "Use on this phone only" greyed out?

- id: hdi-standalone-003
- roles: interviewer
- surfaces: android
- steps:
  1. Read the notice: "Log out of all server accounts before using Standalone Mode. Your saved work will be kept."
  2. Open the account menu, choose **Sign out** for each server account on the phone.
  3. Return to the first screen and choose **Use on this phone only**.
- notes: The option is not shown at all in the plain Collect app, in the demo slot, or on a phone that cannot run the offline engine (Collect Plus needs a 64-bit phone).
- sources: mobile/digitva-collect/src/nativeRoutes/enrol.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### Why can't I start a new standalone interview ("Complete your profile")?

- id: hdi-standalone-004
- roles: interviewer
- surfaces: android
- steps:
  1. Read the message "Complete your profile before starting an interview. Missing: ...".
  2. Tap **Complete profile** and fill in the missing items: name, age, sex, country, HIV mortality level and malaria endemicity.
  3. Save the profile and tap **New interview** again.
- notes: Name must use letters A to Z and spaces; age must be 18 to 89, or 99 if not stated. These values are filled into new interviews and locked there. Interviews already started are never blocked.
- sources: mobile/digitva-collect/src/nativeRoutes/standalone.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/field-data-collection.md ("Interview start gate")
- checked: 2026-11-06

### How do I start a standalone interview?

- id: hdi-standalone-005
- roles: interviewer
- surfaces: android
- steps:
  1. Unlock the phone with your PIN to open the **Standalone** home.
  2. Tap **New interview**.
  3. Record the respondent's consent, then answer the questionnaire. Answers save on the phone as you go.
  4. Finish the interview (see the questionnaire's **Complete** button).
- notes: The questionnaire runs from the version inside the app. Medical-record and death-summary photographs are included by default. Informant details are saved only after the consent decision. If you see "Consent notice not available in standalone mode yet.", the bundled notice could not be used and the covered fields stay empty.
- sources: mobile/digitva-collect/src/nativeRoutes/standalone.tsx; mobile/digitva-collect/src/standalone/config.ts; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### How do I find, resume or revise standalone interviews?

- id: hdi-standalone-006
- roles: interviewer
- surfaces: android
- steps:
  1. On the **Standalone** home use the three tabs: **In progress**, **Pending coding** and **Coded** (each shows a count).
  2. To continue an interview in progress tap **Resume**.
  3. To see a coded result tap **View**; to change it tap **Revise** there and save the cause of death again.
- notes: Each record is titled with the deceased's name, age and sex. "No interviews on this phone yet." and "No interviews in progress." mean the list is empty.
- sources: mobile/digitva-collect/src/nativeRoutes/standalone.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### How do I code a standalone interview on the phone?

- id: hdi-standalone-007
- roles: interviewer
- surfaces: android
- steps:
  1. Open the **Pending coding** tab and tap **Code** on the interview.
  2. If you see "ICD-11 / DORIS coding is off", tap **Open Settings** and enable coding there, then come back.
  3. Wait while the engine starts ("Starting DORIS. The first start takes about 20 seconds.").
  4. Work through the case and save the cause of death.
- notes: Coding in standalone mode uses the ICD-11 and DORIS tools on the phone and works without a connection. It is not masked, since the same person collects and codes. On-device SmartVA (**Run SmartVA**) gives an advisory result that stays on the phone.
- sources: mobile/digitva-collect/src/nativeRoutes/offlineCoding.native.tsx; mobile/digitva-collect/src/nativeRoutes/standalone.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/field-data-collection.md
- checked: 2026-11-06

### How do I back up my standalone records?

- id: hdi-standalone-008
- roles: interviewer
- surfaces: android
- steps:
  1. Open **Settings** and find **Export and backup**.
  2. Choose **Back up this phone**.
  3. Type a passphrase of at least 12 characters and confirm it.
  4. Save the file through the share sheet to a place you control.
- notes: There is no recovery: if you lose the passphrase, nobody can open the backup. The warning reads: this file contains names, phone numbers, addresses and the stories of real people; do not send it by chat apps or e-mail. The home screen reminds you ("Back up your records. Last backup: N days ago.") after 7 days, with the shortcut **Open Settings to back up**. A record not backed up for more than 30 days shows "More than 30 days old. Back up this record."
- sources: mobile/digitva-collect/src/standalone/DataActions.tsx; mobile/digitva-collect/src/standalone/config.ts; mobile/digitva-collect/src/strings/en.json; docs/policy/field-data-collection.md ("Export and backup")
- checked: 2026-11-06

### How do I restore a backup on this phone or a new one?

- id: hdi-standalone-009
- roles: interviewer
- surfaces: android
- steps:
  1. Install Collect Plus on the phone and set up standalone mode (or open the existing account).
  2. Open **Settings**, **Export and backup**, choose **Restore from a backup**.
  3. Choose the backup file and enter its passphrase.
  4. If asked "Replace newer records?", choose **Replace and restore** only if you want the backup's version.
- notes: Result: "N records restored, N already here and kept." Errors: "Wrong passphrase, or the file is damaged or not a DigitVA backup. Nothing was changed." and "This backup was made by a newer version of the app. Update the app and try again." A restore never deletes records.
- sources: mobile/digitva-collect/src/standalone/DataActions.tsx; mobile/digitva-collect/src/standalone/backup.ts; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### How do I export my standalone records as CSV or JSON?

- id: hdi-standalone-010
- roles: interviewer
- surfaces: android
- steps:
  1. Open **Settings**, **Export and backup**, and choose **Export my records**.
  2. Leave **Omit names, phone numbers, addresses and ID numbers** on unless you really need them.
  3. Choose **Export as CSV** or **Export as JSON** and share the file.
- notes: The file includes interview answers, the consent record, the coding result and your profile snapshot at that time; it never includes audio or photographs. "No records to export." means there is nothing yet. Export is available only for standalone accounts. The file is plain text: keep it where you control access.
- sources: mobile/digitva-collect/src/standalone/DataActions.tsx; mobile/digitva-collect/src/standalone/export.ts; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### Can I send my standalone records to the server?

- id: hdi-standalone-011
- roles: interviewer
- surfaces: android
- steps:
  1. Standalone records cannot be sent from the app. Keep them safe with **Back up this phone** and **Export my records**.
  2. If this phone is later enrolled with a server, the standalone records stay on the phone, kept separate; they are visible again only when every server account is signed out.
- notes: Enrolling a server account does not upload or merge standalone data. Do not rely on the phone as the only copy.
- sources: docs/policy/field-data-collection.md ("Earlier adoption design (superseded 2026-10-28)"); mobile/digitva-collect/src/nativeRoutes/standalone.tsx
- checked: 2026-11-06

### How do I enrol a standalone phone with a server?

- id: hdi-standalone-012
- roles: interviewer
- surfaces: android
- steps:
  1. Open **Settings** and tap **Enrol this phone**, or tap it on the profiles list.
  2. Scan the enrolment QR or sign in with email or mobile (see the mobile app entries).
  3. Use the server account for server work. Switch back to standalone only after signing out of every server account.
- notes: Standalone and server profiles are separate accounts with separate PINs. Nothing from the standalone profile is sent.
- sources: mobile/digitva-collect/src/nativeRoutes/settings.tsx; mobile/digitva-collect/src/nativeRoutes/index.tsx; docs/policy/field-data-collection.md
- checked: 2026-11-06

### How do I edit the consent notice in standalone mode?

- id: hdi-standalone-013
- roles: interviewer
- surfaces: android
- steps:
  1. Open **Settings** and the card **Standalone consent notice**.
  2. Edit the **English consent notice** and the **Hindi consent notice**.
  3. Tap **Save consent notices**.
- notes: Each notice needs non-blank text of at most 20,000 characters ("Each notice needs nonblank text and can be no longer than 20,000 characters."). Changes apply to new consent decisions only; earlier records keep the text they saw. The list of purposes cannot be edited here.
- sources: mobile/digitva-collect/src/standalone/StandaloneConsentNoticeSettings.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/standalone-consent-notice-settings.md
- checked: 2026-11-06

### What does "Check the date and time" mean in standalone mode?

- id: hdi-standalone-014
- roles: interviewer
- surfaces: android
- steps:
  1. Open the phone's Settings and make sure Date and time is set to automatic.
  2. Check the date and time shown on the Standalone home before each interview.
- notes: A standalone phone never talks to a server, so the app cannot measure clock errors. Interview times and date checks (such as "date cannot be in the future") use the phone clock.
- sources: mobile/digitva-collect/src/nativeRoutes/standalone.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/field-data-collection.md ("Phone clock")
- checked: 2026-11-06

### What happens if I enter a wrong PIN too many times in standalone mode?

- id: hdi-standalone-015
- roles: interviewer
- surfaces: android
- steps:
  1. Enter your PIN carefully. After 3 wrong tries a warning counts down the remaining attempts.
  2. After the 5th wrong PIN in a row the saved interviews are erased: "Too many wrong PINs. The interviews saved on this phone were erased and cannot be recovered."
  3. Restore from a backup if you have one (see the restore entry).
- notes: A forgotten PIN cannot be recovered; interviews on the phone cannot be opened again. Keep backups. "This phone's saved interviews were removed (the database file is missing)" has no recovery either; choose **Reset and set a new PIN** and restore a backup.
- sources: mobile/digitva-collect/src/vault.ts; mobile/digitva-collect/src/strings/en.json; docs/policy/field-data-collection.md
- checked: 2026-11-06

### What can I do in the Help guide in standalone mode?

- id: hdi-standalone-016
- roles: interviewer
- surfaces: android
- steps:
  1. Open the account menu and choose **Help**.
  2. Read "What this screen is for" and "What to do now"; search **Common questions**.
- notes: Answers that refer to sending or the Sync tab are hidden in standalone mode, because those do not exist there. Help items are saved in the app and work offline. The Help sheet notes "N items are saved on this phone only."
- sources: mobile/digitva-collect/src/nativeShell/faq.ts; mobile/digitva-collect/src/nativeShell/sheets.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06
