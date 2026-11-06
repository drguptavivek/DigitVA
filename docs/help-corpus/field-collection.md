---
title: How-Do-I Corpus - Field Collection
doc_type: help-corpus
status: draft
owner: engineering
last_updated: 2026-11-06
---

# How-Do-I Corpus - Field Collection

Death reporting, registration, interviews, consent, narratives, attachments,
revisions and field supervision. Format and truth rules:
`docs/policy/help-chatbot.md` ("How-Do-I corpus"). Phone entries are checked
against `mobile/digitva-collect/src/strings/en.json` and `theme-en.json`;
questionnaire control labels against `vendor/who-va-2022/src/i18n.ts`.

Label note: the same action is named differently per screen. The web
navigation item is "Deaths"; its button is "Register a death"; the web form
title is "Add a Death to List"; the phone screen title is "Register a death"
and its bottom tab is "Register".

## Registering a death

### How do I register a death in the web app?

- id: hdi-field-001
- roles: interviewer, death_reporter
- surfaces: web
- steps:
  1. Open **Deaths** in the left menu (or the bottom bar on a phone browser).
  2. Choose **Register a death**.
  3. If you work in more than one project or site, pick it under **Site and unit**, then pick the unit under **Choose the unit**.
  4. Fill in **Name of the deceased**, **Date of death**, **Sex** and the date of birth or estimated age.
  5. Add place of death, address, informant name and phone, and **Remarks** if you have them.
  6. Choose **Save and start interview** if you are with the family now. Choose **Save** to register the death only (the **Save** button is shown only if you also hold the interviewer role).
- notes: A death reporter registers and stops; reporters cannot start an interview. In a project where deaths are registered first, **VA Interview** also has a **Record death** button. If **Register a death** is missing, your account has no registration access in any project. Ask the person who manages your project access.
- sources: data-collection; mobile/digitva-collect/src/web/DeathRegistrationScreen.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/web-intake.md
- checked: 2026-11-06

### How do I register a death on the phone?

- id: hdi-field-002
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Tap **Register** in the bottom bar (or **Register a death** on Home).
  2. If you work in several projects, choose the project, then choose the site and unit.
  3. Fill in the sections Deceased, Place, Identifiers, Informant and Notes. Required fields are marked.
  4. Tap **Save** to register the death, or **Save and start interview** to go straight into the questionnaire.
- notes: What you type is kept in the encrypted store on the phone while you work, so leaving the screen does not lose it; only **Save** or a confirmed **Discard** removes it. An interviewer's registration saved without a connection is sent later from the Sync tab. A death reporter's registration is sent at once and needs a connection ("Registering a death needs an internet connection. Connect and try again."). If you see "Sync project settings before starting a new death registration or interview.", open Sync and tap Send now (or pull down on Interviews) while online.
- sources: data-collection; mobile/digitva-collect/src/nativeRoutes/register.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/field-data-collection.md
- checked: 2026-11-06

### Can I register a death without an internet connection?

- id: hdi-field-003
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Make sure you have synced at least once while online, so the project settings and your sites are on the phone.
  2. Open **Register**, fill in the details and tap **Save**.
  3. When you are online again, open **Sync** and tap **Send now**.
- notes: This works for an interviewer. The registration waits as "Waiting to send" and is counted as unsent work. A death reporter (without the interviewer role) cannot register offline. The browser app always needs a connection.
- sources: mobile/digitva-collect/src/nativeRoutes/register.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/expo-client.md
- checked: 2026-11-06

### Which details are required to register a death?

- id: hdi-field-004
- roles: interviewer, death_reporter
- surfaces: both
- steps:
  1. Enter **Name of the deceased**.
  2. Choose **Sex**: Male, Female, Undetermined or Unknown.
  3. Enter **Date of death** (not in the future).
  4. Under **Birth-date precision** choose how much of the birth date you know, and enter it. If you do not know it, choose **Not known** and enter **Estimated age**.
- notes: Everything else (address, informant, phones, ABHA, parents' names, remarks, registration numbers) is optional unless your project's registration numbers are marked required. The informant's name, phone and address open only after the respondent's consent decision is recorded.
- sources: data-collection; mobile/digitva-collect/src/registrationRules.ts; mobile/digitva-collect/src/web/DeathRegistrationScreen.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### What do I do when the date of birth is not known, or only the month or year is known?

- id: hdi-field-005
- roles: interviewer, death_reporter
- surfaces: both
- steps:
  1. Under **Birth-date precision** choose **Exact date**, **Month and year**, **Year only**, or **Not known**.
  2. For **Month and year** or **Year only**, enter only what you know. Do not invent a day or month.
  3. For **Not known**, enter **Estimated age** (a whole number of years).
- notes: After you enter the date of death and a birth date, the form shows the calculated age ("Calculated age at death: ..."). With a partial date it shows an estimated range. If you see "Enter the date of death to estimate age", fill the date of death first. A birth date after the date of death is refused: "Date of birth cannot be after the date of death."
- sources: data-collection; mobile/digitva-collect/src/registrationRules.ts; mobile/digitva-collect/src/strings/en.json; docs/policy/web-intake.md
- checked: 2026-11-06

### What do I do when the app says the age appears to be over 85?

- id: hdi-field-006
- roles: interviewer, death_reporter
- surfaces: both
- steps:
  1. Check the date of birth or estimated age and the date of death.
  2. If they are correct, choose **Confirm and save** (the message reads "The age appears to be over 85 years. Confirm before saving this record.").
  3. If they are wrong, choose **Cancel**, correct the dates and save again.
- notes: Ages above 125 are not accepted ("Age must be a whole number from 0 to 125.").
- sources: mobile/digitva-collect/src/registrationRules.ts; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### What format do phone numbers, ABHA number and ABHA address need?

- id: hdi-field-007
- roles: interviewer, death_reporter
- surfaces: both
- steps:
  1. Informant phone and Second phone: enter 10 digits, for example 987 654 3210. A +91 or leading 0 is dropped. Use **Add another number** for a second phone.
  2. **ABHA number**: 14 digits, optionally grouped 2-4-4-4.
  3. **ABHA address**: looks like name@abdm.
- notes: Messages when wrong: "Enter a 10-digit phone number, for example 987 654 3210", "ABHA number must be 14 digits (optionally grouped 2-4-4-4)." and "ABHA address must look like name@abdm."
- sources: mobile/digitva-collect/src/registrationRules.ts; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### How do I add a registration number (for example an ID number) to a death?

- id: hdi-field-008
- roles: interviewer, death_reporter, interview_supervisor, data_manager
- surfaces: both
- steps:
  1. On the registration form, fill the **Registration numbers** section if your project defines any.
  2. To add one later, open the death's details and choose **Add registration number**.
  3. Follow the example shown under the field ("Example: ...").
- notes: Formats are set per project; errors name the field (for example "use exactly N characters", "digits only"). "Not yet issued" marks a number that does not exist yet. A closed case shows "This case is closed; its registration numbers can no longer be changed." If "Registration numbers could not be loaded. Try again later." appears, reconnect and reopen the form. If the section is absent, your project has none configured.
- sources: docs/policy/death-registration-identifiers.md; mobile/digitva-collect/src/IdentifierFields.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### How do I capture the GPS location of the house?

- id: hdi-field-009
- roles: interviewer, death_reporter
- surfaces: web
- steps:
  1. On the web registration form, under the address, choose **Capture location**.
  2. Allow location access in the browser when asked.
  3. Wait for "Location captured, accurate to about N m". Use **Retake** to try again or **Clear** to remove it.
  4. Save the registration.
- notes: Optional. Location is read once each time you press the button, never in the background. If you see "Location permission was denied. You can still save without it." or "Location took too long. Try again or save without it.", save without it or retry. The phone app does not capture location yet; it shows the saved location as a map-pin button (see the map entry).
- sources: mobile/digitva-collect/src/web/LocationCapture.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/web-intake.md
- checked: 2026-11-06

### How do I find the house on a map?

- id: hdi-field-010
- roles: interviewer, death_reporter
- surfaces: both
- steps:
  1. Open the death's card or details.
  2. If a location was captured, tap the map-pin button or the **Open in Maps** link.
  3. The map opens (browser map on the web, your maps app on the phone).
- notes: Shown only where a location exists and your account may see the household details; otherwise nothing appears. Also read **Remarks**: landmarks and other numbers help find the house.
- sources: mobile/digitva-collect/src/web/LocationCapture.tsx; mobile/digitva-collect/src/ui/CaseCard.tsx; docs/policy/web-intake.md
- checked: 2026-11-06

### How do I edit a death I already registered?

- id: hdi-field-011
- roles: interviewer, death_reporter, interview_supervisor
- surfaces: both
- steps:
  1. Open the death from the list (Deaths on the web; Interviews or **My registered deaths** on the phone).
  2. Choose **Edit registration**.
  3. Change the fields, then choose **Save**.
- notes: Registration details can be changed until an interview of that case has been completed; after that the completed interview is the more up-to-date record. A case that only has a started direct interview ("details pending") cannot be edited here; its interview captures the details. If the case changed meanwhile, the form reloads the latest values; check them and save again. On the phone, editing a death that is already on the server needs a connection.
- sources: data-collection; mobile/digitva-collect/src/nativeRoutes/RegisteredDeaths.tsx; mobile/digitva-collect/src/web/DeathsList.tsx; docs/policy/web-intake.md ("Correcting a registered death")
- checked: 2026-11-06

### Why can't I edit a registered death, or why does saving the edit fail?

- id: hdi-field-012
- roles: interviewer, death_reporter
- surfaces: both
- steps:
  1. Check the case status on its details. If an interview was completed, the registration is locked.
  2. If you only need to add a registration number, use **Add registration number** instead; that stays possible after completion.
  3. If the message is "Check the highlighted fields and try again.", correct the marked field (an old free-text phone number must be fixed in the same edit).
  4. For anything else, ask your interview supervisor.
- notes: You can only change deaths that are within your grant's area and that you may see. A death outside it reads as not found ("This death record is unavailable or outside your access.").
- sources: docs/policy/web-intake.md; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### How do I discard a registration on the phone?

- id: hdi-field-013
- roles: interviewer
- surfaces: android
- steps:
  1. Open the registration (from **Interviews**, or **My registered deaths**).
  2. If it is still waiting to send, or the server did not accept it ("Not accepted: edit or discard"), choose **Edit** to correct it or **Discard**.
  3. Confirm: "Discard this registration? What you entered will be deleted from this phone."
- notes: Discard removes it from this phone only. Once the server has the registration, it is not removed this way.
- sources: mobile/digitva-collect/src/nativeRoutes/case.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### Where do I see the deaths I registered?

- id: hdi-field-014
- roles: interviewer, death_reporter
- surfaces: both
- steps:
  1. Web: open **Deaths**. Keep the **Mine** filter on to see deaths you registered or worked on.
  2. Phone: open **Interviews** for your cases, or **My registered deaths** (shown for accounts that may register).
  3. Use the search box (name, ID or area) and the status chips.
- notes: A death reporter sees only the deaths they registered. An interviewer sees every death within their granted area, not just their own.
- sources: mobile/digitva-collect/src/web/DeathsList.tsx; mobile/digitva-collect/src/nativeRoutes/RegisteredDeaths.tsx; docs/policy/web-intake.md
- checked: 2026-11-06

### What can a death reporter do, and what can't they do?

- id: hdi-field-015
- roles: death_reporter
- surfaces: both
- steps:
  1. Register deaths in your unit and its subtree (**Register a death** on the web; **Register** on the phone).
  2. Correct a death you registered until an interview of it is completed (**Edit registration**).
  3. See your registered deaths in the list.
- notes: A death reporter cannot start or resume an interview, save or submit a questionnaire, log contact attempts or visits, or see other people's cases. For those, you need the interviewer role; ask your project's data manager. The reporter role is granted on an organization unit and needs a cadre that is allowed to report deaths at that level.
- sources: user-roles; docs/policy/web-intake.md ("Death reporters"); mobile/digitva-collect/src/web/roleHome.ts
- checked: 2026-11-06

### How do I find a particular death in the Deaths list?

- id: hdi-field-016
- roles: interviewer, interview_supervisor
- surfaces: web
- steps:
  1. Open **Deaths**.
  2. Type in **Search cases** (name, ID or area).
  3. Use the status chips **All**, **To visit**, **In progress**, **Submitted** and (where it applies) **Ready to code**.
  4. Use **Mine** / **All** and **Last 30 days** / **All**, and **Advanced filters** for dates, sex and age.
  5. Under the area filter choose **All areas**, **My field areas** or **One unit**.
- notes: Filtering applies to the cases already loaded. If you see "Filtering loaded cases: N of M. Load more to search further.", choose **Load more**. Use **Clear all** to reset.
- sources: data-collection; mobile/digitva-collect/src/web/DeathsList.tsx; mobile/digitva-collect/src/web/caseFilters.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

## Interviews and assignment

### How do I start an interview for a death that is already registered?

- id: hdi-field-017
- roles: interviewer
- surfaces: both
- steps:
  1. Web: open **Deaths**, find the death and choose **Start interview** (or open **View details** first). Phone: open **Interviews**, find the case and tap **Start**, or open its details and tap **Start interview**.
  2. Read "Before you begin" and choose **Start questionnaire**.
  3. Answer the questions; answers are saved as you go.
- notes: The questionnaire opens with the death's name, sex and dates already filled in from the registration. On the phone the case must be on the phone; if the list is empty, connect and tap **Refresh**.
- sources: data-collection; mobile/digitva-collect/src/web/DeathsList.tsx; mobile/digitva-collect/src/nativeRoutes/case.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### How do I start an interview without registering the death first?

- id: hdi-field-018
- roles: interviewer
- surfaces: both
- steps:
  1. Web: open **VA Interview**, find the **Direct VA interview** panel, pick the **Project** and **Site or unit**, then choose **Start interview**.
  2. Phone: open **Interviews**, tap **New interview**, choose the site and unit, then start.
  3. Fill in the questionnaire. The deceased's name, sex and date of death come from your answers.
- notes: Direct start is available only in projects whose intake mode allows it (direct, or both direct and register). In a project where a death must be registered first, the **Direct VA interview** button is not offered; use **Record death** or **Register a death** instead. The message "Deaths are not registered in this project; start interviews from VA Interview." means the opposite: this project has no registration step. A direct interview shows as "New interview · details pending" (phone supervision list) until the name, date of death and sex are answered.
- sources: mobile/digitva-collect/src/web/DirectInterviewPanel.tsx; mobile/digitva-collect/src/web/CollectionScreen.tsx; docs/policy/web-intake.md
- checked: 2026-11-06

### Can a supervisor assign an interview to me?

- id: hdi-field-019
- roles: interviewer, interview_supervisor
- surfaces: both
- steps:
  1. You do not wait for an assignment. Open your list (Deaths on the web, Interviews on the phone).
  2. Any death within the area of your interviewer grant is open to you.
  3. Choose **Start interview**.
- notes: DigitVA has no assign or reassign action. A case belongs to the person who registered it until an interview starts, then to the interviewer who started it. Agree with your colleagues which of you visits which family. Supervisors can view cases, resolve flags, cancel, reopen and mark duplicates, but never assign.
- sources: docs/policy/web-intake.md ("Ownership and visibility", "Supervisors")
- checked: 2026-11-06

### What do I do when another interviewer has already started or finished this case?

- id: hdi-field-020
- roles: interviewer
- surfaces: both
- steps:
  1. Read the notice on the case: "Another interviewer started this interview on ...", or "Another complete interview of this case is with the supervisor."
  2. Check with your supervisor or colleague before continuing, so the family is not interviewed twice.
  3. If you do go ahead, your interview is saved as your own copy.
- notes: Each interviewer edits only their own copy. The first complete interview the server accepts becomes the case's interview; a later one is kept as history ("Another interview of this case is with the coder; yours was saved as history."). On the phone the warning reflects the last successful sync.
- sources: mobile/digitva-collect/src/strings/en.json; docs/policy/web-intake.md ("Parallel interviews")
- checked: 2026-11-06

### How do I resume an interview I did not finish?

- id: hdi-field-021
- roles: interviewer
- surfaces: both
- steps:
  1. Web: open **VA Interview** (**My interviews**) or **Deaths** and choose **Resume interview**.
  2. Phone: on Home tap **Resume draft**, or open **Interviews**, choose the **Drafts** chip and tap the interview.
  3. Continue where you stopped.
- notes: A draft belongs to the person who started it; sign in with the same account. Do not start a second draft to get around an unfinished one. The phone shows "Saved <time>" and the number of sections saved.
- sources: data-collection; mobile/digitva-collect/src/strings/en.json; mobile/digitva-collect/src/nativeShell/faq.ts
- checked: 2026-11-06

### How do I delete an interview draft I never sent?

- id: hdi-field-022
- roles: interviewer
- surfaces: android
- steps:
  1. Open **Interviews** and find the draft.
  2. Use **Delete draft** on the card or in the interview's menu.
  3. Confirm "Delete this draft?"
- notes: "This interview was never sent. Deleting it removes its answers, recordings and photographs from this phone. This cannot be undone." If the card says the saved form details are damaged, ask your supervisor before deleting it.
- sources: mobile/digitva-collect/src/nativeRoutes/worklistParts.tsx; mobile/digitva-collect/src/nativeRoutes/form.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### How do I change the language of the questions?

- id: hdi-field-023
- roles: interviewer
- surfaces: both
- steps:
  1. Open the interview.
  2. Web: use **Form language**. Phone: tap the three-dot menu at the top, then **Questionnaire language**.
  3. Choose the language.
- notes: This is separate from the language of the app screens. The choices are the languages your project enabled. "This questionnaire language is not available offline" means the translation is not on the phone yet: connect and sync project settings. If the questions show in English, the message "Questionnaire translations are unavailable. Questions are shown in English; your selected language is retained." explains it.
- sources: mobile/digitva-collect/src/strings/en.json; mobile/digitva-collect/src/nativeShell/faq.ts; docs/policy/expo-client.md
- checked: 2026-11-06

### How do I complete and submit an interview?

- id: hdi-field-024
- roles: interviewer
- surfaces: both
- steps:
  1. Answer all required questions. Fix anything listed under "Problems to fix" (use **Go** to jump to it).
  2. Use **Preview answers** to review what you entered.
  3. In the last section choose **Complete**.
  4. Phone: the interview now shows **Ready to send**. Open **Sync** and tap **Send now** (see the sending entry).
- notes: On the web the message "Interview submitted successfully" confirms it. The typed narrative and the narration language are required; audio and photographs are optional. A submitted interview goes to coding.
- sources: data-collection; vendor/who-va-2022/src/i18n.ts; mobile/digitva-collect/src/nativeRoutes/form.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### How do I finish an interview that could not be completed?

- id: hdi-field-025
- roles: interviewer
- surfaces: both
- steps:
  1. In the **Outcome of the interview** question choose **Partially completed** or **Respondent unavailable**.
  2. Phone: open the three-dot menu and choose **Finish as incomplete**, then confirm "Finish as incomplete?".
  3. Web: complete the form with that outcome.
- notes: The phone warns "It will be queued to send and can no longer be edited here." If you see "The questionnaire is not complete. Answer the flagged questions, or record the interview outcome as partially completed or respondent unavailable.", either answer the flagged questions or choose one of those outcomes. A refusal (no consent) sets the outcome to **Refused**. An incomplete outcome does not close the case; a later complete interview wins. A refusal with no identity at all also needs a visit note (address and visit date).
- sources: data-collection; mobile/digitva-collect/src/nativeRoutes/form.tsx; app/data/who-va-2022.composed.json (interview_outcome); docs/policy/web-intake.md
- checked: 2026-11-06

### How do I send a finished interview from the phone?

- id: hdi-field-026
- roles: interviewer
- surfaces: android
- steps:
  1. Connect to Wi-Fi or mobile data.
  2. Open the **Sync** tab and tap **Send now** (or use **Send now** on Home, or pull down on Interviews).
  3. Check "Sent N. Not accepted N. Still on this phone N."
- notes: Only finished interviews are sent; a draft in progress stays on the phone until you finish it. Interviews with photos or audio upload their files first; an interview is never sent with a file missing. Offline, **Send now** shows "You're offline. Your work is saved and will send when you're back online." and the app sends on reconnect.
- sources: mobile/digitva-collect/src/nativeShell/sheets.tsx; mobile/digitva-collect/src/nativeShell/faq.ts; docs/policy/expo-client.md ("Offline gate"); docs/policy/phone-attachments.md
- checked: 2026-11-06

### How do I find the interviews I already submitted?

- id: hdi-field-027
- roles: interviewer
- surfaces: both
- steps:
  1. Phone: tap **Interviews** at the bottom, then the **Sent** chip.
  2. Web: open **VA Interview** and use the **Submitted** chip, or open the death in **Deaths** and choose **View submitted answers**.
- notes: Each sent interview shows its name and ID. The phone keeps only unsent work and recent submitted interviews.
- sources: mobile/digitva-collect/src/nativeShell/faq.ts; mobile/digitva-collect/src/web/newCaseDetailScreen.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

## Consent

### How do I record the respondent's consent?

- id: hdi-field-028
- roles: interviewer, death_reporter
- surfaces: both
- steps:
  1. When the project requires consent, the consent screen ("Respondent consent") appears before the informant's details or before the interview.
  2. Read the notice to the respondent in their language.
  3. Mark each purpose they agree to (**Select all** / **Clear all** are available).
  4. Choose **How the respondent gave their decision**: **Spoken**, **Tapped on the device** or **Signed**. Tick **A witness was present** if one was.
  5. Choose **Respondent agrees** or **Respondent refuses**.
- notes: To record agreement, every required purpose must be marked. Once recorded you see "Consent recorded: the respondent agreed." and can use **Change decision**. A consent recorded at registration is reused by the interview. If you see "This project requires respondent consent but has no consent notice yet. Ask the project's data manager to add one in Project Setup.", the notice is missing and you cannot record consent until it is added.
- sources: mobile/digitva-collect/src/strings/en.json; docs/policy/web-intake.md ("Respondent consent"); docs/policy/respondent-consent-notice-draft.md
- checked: 2026-11-06

### What happens when the respondent refuses consent?

- id: hdi-field-029
- roles: interviewer, death_reporter
- surfaces: both
- steps:
  1. Choose **Respondent refuses**.
  2. The registration or interview carries on without the respondent's name, phone and address; questions covered by consent stay empty.
  3. Send or submit as usual.
- notes: "The respondent refused consent. The interview will stop, and the questions about their name, family and address will stay empty." Answers already given about the respondent are removed ("Consent changed to refused. The answers about the respondent's name, family and address were removed.") and cannot be restored. A refused case is not closed: any team member may start it again later. If the phone says "Held: consent was refused. Open the interview to review or change consent.", open it and use **Change consent decision**.
- sources: mobile/digitva-collect/src/strings/en.json; docs/policy/web-intake.md; docs/policy/phone-attachments.md
- checked: 2026-11-06

### Why are the informant's name, phone and address locked?

- id: hdi-field-030
- roles: interviewer, death_reporter
- surfaces: both
- steps:
  1. Record the respondent's consent decision first (see the consent entry).
  2. After a decision of agreement, the informant fields open.
- notes: The text on screen is "The informant's name, phone and address open once the respondent's consent decision is recorded." On the phone, "Informant details are recorded after the next sync" or "Consent settings for this project are not on this phone yet" means the project's consent notice has not synced: connect, tap **Send now**, and reopen.
- sources: mobile/digitva-collect/src/strings/en.json; mobile/digitva-collect/src/nativeRoutes/register.tsx
- checked: 2026-11-06

## Narrative, audio and photographs

### Which narrative questions are required?

- id: hdi-field-031
- roles: interviewer
- surfaces: both
- steps:
  1. Choose the **Narration language**: English, Hindi, Marathi, Kannada, Malayalam or Bangla (required).
  2. Type the respondent's account of the events that led to the death in the narrative question (required).
  3. Optionally add an audio recording and a photograph of a written narrative.
- notes: The typed narrative stays required even when audio or an image is present. Medical documents and death-certificate images are optional; no attachment is mandatory. Which of these questions appear depends on your project's setup.
- sources: data-collection; app/data/who-va-2022.composed.json (narr_language, Id10476); docs/policy/va-form-project-configuration.md
- checked: 2026-11-06

### How do I record the audio narration?

- id: hdi-field-032
- roles: interviewer
- surfaces: both
- steps:
  1. Open the narrative question in the interview.
  2. Choose **Record audio**. Allow the microphone if asked.
  3. Use **Pause** and **Resume** if needed (phone), then **Stop and save recording**.
  4. To redo it, choose **Replace audio**; to remove it, **Delete recording**.
- notes: On the phone a recording is at most 30 minutes and is kept encrypted until the interview is sent. It stops by itself at the limit and pauses if the app leaves the foreground. The web recorder has no pause. Still type the narrative; audio does not replace it.
- sources: vendor/who-va-2022/src/i18n.ts; docs/policy/phone-attachments.md; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### What do I do when the app says the microphone or camera is off?

- id: hdi-field-033
- roles: interviewer
- surfaces: both
- steps:
  1. Phone: choose **Open settings** in the message, allow **Microphone** (or **Camera**), return to the app and try again.
  2. Or open Settings, the Permissions section, and tap the **Camera** or **Microphone** row (its action reads "Enable camera" / "Enable microphone", or **Open phone settings** if the phone has blocked it).
  3. Web: allow microphone access for the site in the browser's address bar and try again.
- notes: Messages: titled "Microphone is off" ("Recording needs the microphone. Open the app's settings and allow Microphone, then try again. You can also type the narrative instead.") and "Camera is off". Android 12 and older may ask for photo access to choose from the gallery; the camera is another way to attach a picture.
- sources: mobile/digitva-collect/src/strings/en.json; mobile/digitva-collect/src/devicePermissions.native.ts; docs/policy/phone-attachments.md
- checked: 2026-11-06

### How do I photograph a written narrative?

- id: hdi-field-034
- roles: interviewer
- surfaces: both
- steps:
  1. If the narrative was written on paper, open the question "Photograph of the written narrative, if the narrative was recorded on paper".
  2. Choose **Camera** to take the photo, or **Choose image** to use one from the device.
  3. Check it with **View image**; replace with **Replace image** or delete with **Remove image**.
- notes: Optional. Still type the narrative. Use clear light and keep the page flat.
- sources: app/data/who-va-2022.composed.json (imagenarr); vendor/who-va-2022/src/i18n.ts
- checked: 2026-11-06

### How do I attach medical records or the death certificate?

- id: hdi-field-035
- roles: interviewer
- surfaces: both
- steps:
  1. Find "Are there any medical documents available related to the deceased?" and answer it.
  2. Enter "How many medical document pages will you photograph?" and photograph or choose each page.
  3. For the death certificate or summary, answer "Is there any death summary / certificate document (images) available for the deceased?" and add its pages the same way.
- notes: Optional. Images are shrunk automatically on the device. A picture over 10 MB is refused ("Choose an image smaller than 10 MB."), a PDF over 5 MB is refused, and a PDF may have at most 10 pages. If "This image could not be reduced below 2 MB. Retake it at a lower resolution." appears, retake the photo. Only JPEG, PNG and PDF are accepted. These questions appear only if your project enabled them.
- sources: app/data/who-va-2022.composed.json (md_available, ds_available); vendor/who-va-2022/src/i18n.ts; docs/policy/phone-attachments.md
- checked: 2026-11-06

### Why does the interview say attached files are still waiting to be sent?

- id: hdi-field-036
- roles: interviewer
- surfaces: both
- steps:
  1. Wait for the files to upload, keeping the connection on. Phone: **Sync**, **Send now**.
  2. Web: after "Attached files still waiting to be sent: N. Submit again once they have been sent.", wait, then submit again.
  3. If a file was refused ("the server refused this file"), record or attach it again.
- notes: An interview is never submitted with a file missing. On the web, files not sent within 7 days are deleted from the browser ("These files were not sent within 7 days ... record or attach them again"), and signing out deletes unsent files ("Unsent files will be deleted"). A file for an interview that was already submitted or discarded is held on the device and can be removed with **Delete from this device**.
- sources: mobile/digitva-collect/src/strings/en.json; docs/policy/phone-attachments.md; docs/policy/web-intake.md
- checked: 2026-11-06

## Revisions

### How do I correct an interview I already submitted?

- id: hdi-field-037
- roles: interviewer
- surfaces: both
- steps:
  1. Web: open **VA Interview**, find the submitted interview and choose **Revise** (or **Correct interview** on the death's details). Phone: **Interviews**, **Sent** chip, open the interview and tap **Revise**.
  2. Choose the **Reason for revision (required)**: **Correct an interviewer entry**, **Correct information from the respondent**, **Add more information** or **Finish a partially completed interview**.
  3. Change only the answers that need correcting.
  4. Submit. On the phone, send it from **Sync**.
- notes: The corrected interview is sent as a new version; the coder gets it. Messages: "Revision saved." or "Revision saved. The coding answers did not change." If the revision is refused you see "The server refused this request. Correct the interview or reason, then submit again to create a new revision request." Revising on the phone needs a connection to open the interview ("Revisions need a connection.").
- sources: mobile/digitva-collect/src/nativeRoutes/revision.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/interview-revisions.md
- checked: 2026-11-06

### Why can't I revise an interview ("This interview is locked")?

- id: hdi-field-038
- roles: interviewer, interview_supervisor
- surfaces: both
- steps:
  1. Read the message: "This interview is locked. Ask the coder to send it back for revision." or "Coding has finished; only a send-back or reopen can change the coder's version."
  2. Ask the coder to send it back, or ask your interview supervisor to use **Reopen for revision** on the case.
  3. Once reopened, revise as usual.
- notes: Other refusals: "This case is closed and cannot be revised.", "This submitted interview is unavailable or has been superseded." and "A complete interview for this case was already submitted."
- sources: mobile/digitva-collect/src/strings/en.json; mobile/digitva-collect/src/web/SupervisionCase.tsx
- checked: 2026-11-06

## Following up with families

### How do I log a contact attempt or set the next visit?

- id: hdi-field-039
- roles: interviewer
- surfaces: both
- steps:
  1. Open the death's details.
  2. Choose **Log contact attempt** and pick the outcome: **Reached**, **No answer**, **Wrong number**, **Moved** or **Refused**.
  3. To plan a revisit, choose **Set next visit** and enter the **Next visit date** (from today up to a year ahead).
- notes: On the phone the action is saved ("Saved. It is sent with the next sync.") and shown as "Waiting to send". Only the outcome and date are recorded; do not write names or numbers in free text. Case statuses include Registered, Scheduled, Not reachable, Paused, Refused and In progress. If the case is closed you see "No follow-up actions are available in this status."
- sources: mobile/digitva-collect/src/nativeRoutes/case.tsx; mobile/digitva-collect/src/web/newCaseDetailScreen.tsx; docs/policy/web-intake.md ("Contact data and attempts")
- checked: 2026-11-06

### How do I call the informant?

- id: hdi-field-040
- roles: interviewer
- surfaces: both
- steps:
  1. Open the death's details; the section "Family and informant" shows the contact details.
  2. Choose **Call informant**.
- notes: Lists show masked phone numbers; the full number is shown only on the details. The dialler opens only after you tap. If you see "Contact and address details are not available for this record.", your account does not have access to them for this case.
- sources: mobile/digitva-collect/src/nativeRoutes/case.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/web-intake.md
- checked: 2026-11-06

## Saving problems in the browser

### What do I do when the web app says "Your session ended" while I am filling an interview?

- id: hdi-field-041
- roles: interviewer
- surfaces: web
- steps:
  1. Do not close the page. Your answers are kept: "Your session ended. Your answers are kept on this device and are not lost."
  2. Choose **Sign in again** (it opens a new tab) and sign in.
  3. Return to the interview tab and choose **Resume saving**.
- notes: If you see "You are still signed out. Sign in again, then press Resume saving." the sign-in did not finish. The web app signs you out after 30 minutes without activity (a warning appears at 28 minutes: **Stay signed in**) and after 12 hours in total.
- sources: mobile/digitva-collect/src/web/InterviewScreen.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/expo-client.md ("Idle sign-out")
- checked: 2026-11-06

### What do I do when saving is paused ("the server did not accept the last save")?

- id: hdi-field-042
- roles: interviewer
- surfaces: web
- steps:
  1. Read the reason shown. Your answers are still on the page.
  2. Choose **Try saving again**.
  3. If it is refused again, send your supervisor the Ref line shown under the message.
- notes: Keep the page open until it saves.
- sources: mobile/digitva-collect/src/web/InterviewScreen.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### What do I do when the interview was changed somewhere else ("Keep the newer version" / "Use my answers")?

- id: hdi-field-043
- roles: interviewer
- surfaces: web
- steps:
  1. Read who changed it and when (for example "You changed this interview on your phone at 10:15.").
  2. Choose **Keep the newer version** to load what is on the server.
  3. Or choose **Use my answers** to replace the newer version with the answers on this page.
- notes: After a consent refusal only **Keep the newer version** is offered, because answers given before a refusal cannot be restored.
- sources: mobile/digitva-collect/src/web/InterviewScreen.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/web-intake.md ("Stale browser saves")
- checked: 2026-11-06

### What do I do when the server did not accept my interview ("This interview was not accepted")?

- id: hdi-field-044
- roles: interviewer
- surfaces: both
- steps:
  1. Read the reason on the banner ("Not accepted: ...").
  2. Choose **Go to the question** to jump to the problem answer and correct it.
  3. Send again: **Send again** on the phone, or submit again on the web.
  4. If the message says "Held: the server cannot take this interview (its case is closed, already submitted or changed)", send once more or ask your supervisor.
- notes: Give your supervisor the Ref code from the Sync tab if you need help. Other holds: "This interview's saved form details are damaged, so it cannot be sent. Ask your supervisor before deleting it." and "This interview could not be verified. Open it, review the answers, and try sending it again."
- sources: mobile/digitva-collect/src/strings/en.json; mobile/digitva-collect/src/nativeShell/sheets.tsx; docs/policy/expo-client.md
- checked: 2026-11-06

## Supervisors

### How do I see the cases that need my decision as an interview supervisor?

- id: hdi-field-045
- roles: interview_supervisor, data_manager
- surfaces: web
- steps:
  1. Open **Deaths**. If you also register or interview, choose **Needs my attention**; otherwise the supervision view opens directly. **All deaths** shows every case in your area.
  2. Use the **State** filter and, if needed, **Visit notes**.
  3. Open a case with **View details**.
- notes: You see cases in the area of your supervisor grant (a unit grant covers the unit and everything below it). Rows show who registered and who started the case; informant phones and addresses are not shown. "Nothing waiting for your decision." means no flags are pending. The older Supervision page redirects here when the new app is installed.
- sources: mobile/digitva-collect/src/web/SupervisionPanel.tsx; mobile/digitva-collect/src/strings/en.json; app/routes/intake.py
- checked: 2026-11-06

### How do I mark a case as a duplicate, cancel it, or reopen it?

- id: hdi-field-046
- roles: interview_supervisor, data_manager
- surfaces: web
- steps:
  1. Open the case from **Deaths** (supervision view).
  2. Choose **Mark duplicate**, **Cancel case** or **Reopen**.
  3. For a duplicate, choose the case to keep under "Choose the case to keep".
  4. Enter the reason (the field says "Reason" when it is required and "Reason (optional)" when it is not) and confirm.
- notes: The reason must not contain names, phone numbers or addresses. A flag raised by an interviewer shows "Duplicate flag waiting" or "Cancel flag waiting" and is settled with **Confirm flag** or **Reject flag**. A duplicate of a case already coded waits for a supervisor who is also its data manager. If you see "This case changed while you were working on it. Reload the list and try again.", reload.
- sources: mobile/digitva-collect/src/web/SupervisionActions.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/web-intake.md ("Duplicate and cancel flags")
- checked: 2026-11-06

### How do I choose between two complete interviews of the same case?

- id: hdi-field-047
- roles: interview_supervisor, data_manager
- surfaces: web
- steps:
  1. Open the submitted case; the section "Other complete interviews" lists the candidates.
  2. Choose **Choose interview** beside the one to use.
  3. Pick the reason: **Better quality**, **More complete**, **Original incorrect** or **Switch back**, then confirm.
- notes: The chosen interview replaces the coder's copy and coding restarts. This is refused while a reviewer's coding session is live. If there is no other complete interview you see "No other complete interview."
- sources: mobile/digitva-collect/src/web/SupervisionCase.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/web-intake.md ("Supervisors")
- checked: 2026-11-06

### How do I send a submitted interview back to the interviewer for revision?

- id: hdi-field-048
- roles: interview_supervisor, data_manager
- surfaces: web
- steps:
  1. Open the submitted case in the supervision view.
  2. Choose **Reopen for revision**.
  3. Pick the reason ("Reason for reopening for revision"): for example **Data correction**, **New information** or **COD review requested**, then confirm.
- notes: You see "Reopened for the interviewer to revise." Interviews that came from ODK are revised in ODK, not here ("This interview came from ODK, so it is revised in ODK, not here.").
- sources: mobile/digitva-collect/src/web/SupervisionCase.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### How do I check possible duplicates of a case?

- id: hdi-field-049
- roles: interview_supervisor, data_manager
- surfaces: web
- steps:
  1. Open the case details in the supervision view.
  2. Read **Possible duplicates**.
  3. If one is the same death, use **Mark duplicate** and keep the case that is further along.
- notes: Only cases within your area are shown, with limited fields (no informant details). "No possible duplicates." means nothing matched on date of death within 3 days, sex and a similar name in a nearby unit.
- sources: mobile/digitva-collect/src/web/SupervisionActions.tsx; docs/policy/web-intake.md ("Possible duplicates and visit notes")
- checked: 2026-11-06
