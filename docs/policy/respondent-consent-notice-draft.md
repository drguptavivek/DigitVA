---
title: Respondent Consent Notice, Draft Text
doc_type: policy
status: proposed
owner: Vivek Gupta
last_updated: 2026-10-27
---

# Respondent Consent Notice, Draft Text

Bead `digitva-athy`. A plain-language starting text for the notice shown to
the respondent (the informant) before any of their details are saved. It is a
draft for the project to adapt, translate and put through legal review
against the Digital Personal Data Protection Act 2023. It is not legal
advice. Items in square brackets are project-level variables (see the bead:
notice text per language and version, itemised purposes marked required or
optional, retention, withdrawal contact).

## Notice (version 0.1, English)

**[PROJECT NAME]: information about a death in your family**

We are asking about a death so that the cause can be understood and health
services can improve. Please read this before you answer. You can say no to
any part that is marked optional and still take part.

**What we collect.** About you: your name, your phone number, your address
and how you are related to the person who died. About the person who died:
age, sex, the date and place of death, the illness and events before death,
and, if you choose to give them, identity numbers such as Aadhaar (only the
last three digits are kept) or ABHA.

**Why we collect it, and who sees it.**

1. **To record the death and complete the interview (required).** Trained
   health workers, interviewers and their supervisors at [ORGANISATION] and
   the local health and government offices responsible for [PROJECT AREA] see
   your name, phone and address, so that the interview can be done and
   checked.
2. **To contact you (required if you give a phone number).** We may call you
   or visit to complete or clarify the answers. Your phone number and address
   are used only for this project.
3. **To send you messages (optional).** With your agreement we may send you
   SMS or WhatsApp messages about this interview, such as a reminder or a
   thank-you. You can refuse this and still take part.
4. **To decide the cause of death (required).** Doctors and coders review the
   interview answers. They do not see your name, phone, address or any
   identity number.
5. **For government and statistical reports (required).** The health
   department, the statistical office and the institutions and mentors who
   support [PROJECT NAME] and their staff use counts and summaries. These do
   not name anyone.
6. **For research on verbal autopsy (optional) [project decides whether this
   is required or optional].** The interview answers are stripped of anything
   that could identify you or the person who died. This de-identified data
   may be placed in research repositories where researchers in India and in
   other countries can use it. It includes the district, whether the area is
   rural or urban, the month and year of death, the age group and an
   approximate location. Your name, phone number, the exact address, identity
   numbers, the exact date of death and contact details are never included,
   and are not shown in any registry or repository.

**How we protect it.** Your name, phone number, address and identity numbers
are stored in encrypted form. Only people whose work needs them can see them,
and what they see is recorded.

**How long we keep it.** [RETENTION PERIOD AND WHAT HAPPENS AFTER, for
example erased or locked.]

**Your rights.** You can ask to see the details we hold about you, correct
them, have them erased, or ask that your answers be left out of reports and
research. You can withdraw your agreement at any time by writing to the
deletion and exclusion contact below. After you withdraw we stop using your
contact details and remove them. De-identified data that has already been
shared for research cannot be taken back, because it no longer identifies
you. If you are not satisfied, you can complain to [DATA PROTECTION OFFICER,
if any] and then to the Data Protection Board of India.

**Who to contact.**

- **To ask for deletion or exclusion of your data:** [DELETION AND EXCLUSION
  EMAIL], [PHONE]. Please quote the case number given to you at the
  interview.
- **Your district team:** [DISTRICT NAME]: [DISTRICT CONTACT NAME, EMAIL,
  PHONE]. The district contact is chosen from the district where the death
  was recorded.
- **The mentoring institution:** [INSTITUTION NAME]: [EMAIL, PHONE].
- **The central team for [PROJECT NAME]:** [EMAIL, PHONE].

**Your choice.** Please say yes or no to each numbered item, and tell us how
you gave your agreement (spoken, tapped on the device, or signed).

## Proposed addition: automated processing of the narrative (`digitva-sxg9`, owner 2026-10-27)

**Status:** adopted into the default seed by the owner on 2026-10-27, as item 7
and purpose `narrative_automated_processing`. Like the rest of the notice it
still needs legal and language review. Policy:
`docs/policy/narrative-ai-processing.md`.

Under DPDP section 5, a notice must name each purpose. The narrative
pipeline (PII detection and de-identification, a quality check, translation
and symptom suggestions) is a purpose in its own right, so it gets its own
numbered item. It is optional unless the project decides otherwise. A
project could argue it is part of item 4 (deciding the cause of death), but
a separate item is clearer and lets a respondent refuse it.

**English, notice item 7:**

> 7. **Computer help to check and translate the story you tell (optional)
> [project decides whether this is required or optional].** Your account of
> the illness and death may be checked by computer programs that run on
> systems controlled by [ORGANISATION] in India. These programs:
> - remove names, places and phone or identity numbers from a copy of your
>   account;
> - check whether the account has enough detail;
> - translate it into English;
> - point out symptoms the doctors may want to look at.
>
> The programs do not decide the cause of death; doctors do. Your account is
> not sent to any outside company. Your original words are kept as you gave
> them. You can refuse this and still take part.

**Seed form (plain text, same style as the seed above):**

```text
7. Computer help to check and translate your account (optional). Programs on systems controlled by [ORGANISATION] in India may remove names, places and numbers from a copy of your account, check whether it has enough detail, translate it into English, and point out symptoms for the doctors. They do not decide the cause of death, and your account is not sent to any outside company.
```

**Hindi seed** (a working translation, which needs language review like the
rest):

```text
7. आपके विवरण की जाँच और अनुवाद में कंप्यूटर की मदद (वैकल्पिक)। भारत में [ORGANISATION] द्वारा नियंत्रित प्रणालियों पर चलने वाले प्रोग्राम आपके विवरण की एक प्रति से नाम, स्थान और नंबर हटा सकते हैं, जाँच सकते हैं कि उसमें पर्याप्त जानकारी है या नहीं, उसका अंग्रेज़ी में अनुवाद कर सकते हैं, और डॉक्टरों के लिए लक्षण बता सकते हैं। ये मृत्यु का कारण तय नहीं करते, और आपका विवरण किसी बाहरी कंपनी को नहीं भेजा जाता।
```

**Seed purpose row:**

| Code | Required | English label |
| --- | --- | --- |
| `narrative_automated_processing` | no (project decides) | Computer programs on [ORGANISATION]'s systems in India may de-identify, check, translate and suggest symptoms from my account, without deciding the cause of death |

**How the pipeline honours it:**
- A narrative is leased to the workstation only if its project has narrative
  AI enabled and, when the project requires consent, the case's consent
  record answers this purpose "yes".
- Cases with no answer for this purpose, including notice versions from
  before it existed, are not processed.
- Withdrawing consent stops further processing and deletes that case's
  stored narrative-AI results, the de-identified copy included.

**For the legal review:**
- The wording promises "not sent to any outside company". That holds only
  while the processing stays on the operator's own systems. Moving to an
  external service would need new notice text and fresh consent.
- If a mentoring institution runs the workstation for [ORGANISATION], name
  it as a processor in the notice or the project's data processing
  agreement.

## Refusal profile, for legal review (owner 2026-10-27)

When a respondent refuses, the project records only the deceased's broad age
group and sex, from the death register where available. There is no name,
identifier or other answer. This is for refusal-bias statistics (see
`docs/policy/digitva-who-form-overrides.md`, "Equity extension: refusal
profile"). The legal review should confirm the basis, which is not consent,
and whether the refusal script should say this to the respondent.

## Seed text for Project Setup (owner 2026-10-22)

Project Setup's "Seed from draft" (Respondent consent section) creates notice
version 1 of a project with no notice versions, in English and Hindi, from the
two blocks below: plain text (the consent screen shows the text as written,
not as Markdown), `[PROJECT NAME]` replaced by the project's name, every other
bracketed item left for the project to fill in. Filling them in is an edit,
which saves a new version. The app keeps the same text in
`app/services/consent_notice_seed.py`; a test fails if the two differ. The
Hindi text is a working translation and needs the same legal and language
review as the English.

### English seed

```text
[PROJECT NAME]: information about a death in your family

We are asking about a death so that the cause can be understood and health services can improve. Please listen to or read this before you answer. You can say no to any part marked optional and still take part.

What we collect. About you: your name, phone number, address and how you are related to the person who died. About the person who died: age, sex, the date and place of death, the illness and events before death, and, if you choose to give them, identity numbers such as Aadhaar (only the last three digits are kept) or ABHA.

Why we collect it, and who sees it.
1. To record the death and complete the interview (required). Health workers, interviewers and their supervisors see your name, phone and address so that the interview can be done and checked.
2. To contact you (required if you give a phone number). We may call or visit to complete or clarify the answers.
3. To send you messages (optional). SMS or WhatsApp messages about this interview, such as a reminder or a thank-you.
4. To decide the cause of death (required). Doctors and coders review the answers. They do not see your name, phone, address or any identity number.
5. For government and statistical reports (required). Counts and summaries that do not name anyone.
6. For research on verbal autopsy (optional). De-identified answers may be shared in research repositories in India and other countries. Your name, phone, exact address, identity numbers and the exact date of death are never included.
7. Computer help to check and translate your account (optional). Programs on systems controlled by [ORGANISATION] in India may remove names, places and numbers from a copy of your account, check whether it has enough detail, translate it into English, and point out symptoms for the doctors. They do not decide the cause of death, and your account is not sent to any outside company.

How we protect it. Your name, phone number, address and identity numbers are stored in encrypted form. Only people whose work needs them can see them, and what they see is recorded.

How long we keep it. [RETENTION PERIOD AND WHAT HAPPENS AFTER]

Your rights. You can ask to see, correct or erase the details we hold about you, or ask that your answers be left out of reports and research. You can withdraw your agreement at any time through the contacts below. De-identified data already shared for research cannot be taken back. You can complain to [DATA PROTECTION OFFICER] and then to the Data Protection Board of India.

Who to contact.
- Deletion or exclusion of your data: [DELETION AND EXCLUSION EMAIL], [PHONE]. Quote the case number given to you.
- Your district team: [DISTRICT CONTACT NAME, EMAIL, PHONE].
- The mentoring institution: [INSTITUTION NAME, EMAIL, PHONE].
- The central team: [EMAIL, PHONE].

Your choice. Please say yes or no to each numbered item.
```

### Hindi seed

```text
[PROJECT NAME]: आपके परिवार में हुई मृत्यु के बारे में जानकारी

हम यह मृत्यु के बारे में इसलिए पूछ रहे हैं ताकि मृत्यु का कारण समझा जा सके और स्वास्थ्य सेवाएँ बेहतर हो सकें। उत्तर देने से पहले कृपया इसे सुनें या पढ़ें। "वैकल्पिक" लिखे किसी भी भाग के लिए आप मना कर सकते हैं और फिर भी भाग ले सकते हैं।

हम क्या जानकारी लेते हैं। आपके बारे में: आपका नाम, फ़ोन नंबर, पता और मृत व्यक्ति से आपका संबंध। मृत व्यक्ति के बारे में: आयु, लिंग, मृत्यु की तारीख और स्थान, मृत्यु से पहले की बीमारी और घटनाएँ, और यदि आप देना चाहें तो आधार (केवल अंतिम तीन अंक रखे जाते हैं) या ABHA जैसे पहचान नंबर।

हम यह क्यों लेते हैं और इसे कौन देखता है।
1. मृत्यु दर्ज करने और साक्षात्कार पूरा करने के लिए (आवश्यक)। स्वास्थ्य कार्यकर्ता, साक्षात्कारकर्ता और उनके पर्यवेक्षक आपका नाम, फ़ोन और पता देखते हैं ताकि साक्षात्कार किया और जाँचा जा सके।
2. आपसे संपर्क करने के लिए (फ़ोन नंबर देने पर आवश्यक)। उत्तर पूरे करने या स्पष्ट करने के लिए हम आपको फ़ोन कर सकते हैं या मिलने आ सकते हैं।
3. आपको संदेश भेजने के लिए (वैकल्पिक)। इस साक्षात्कार के बारे में SMS या WhatsApp संदेश, जैसे याद दिलाना या धन्यवाद।
4. मृत्यु का कारण तय करने के लिए (आवश्यक)। डॉक्टर और कोडर उत्तरों की समीक्षा करते हैं। वे आपका नाम, फ़ोन, पता या कोई पहचान नंबर नहीं देखते।
5. सरकारी और सांख्यिकीय रिपोर्टों के लिए (आवश्यक)। गिनती और सारांश, जिनमें किसी का नाम नहीं होता।
6. वर्बल ऑटोप्सी पर शोध के लिए (वैकल्पिक)। पहचान हटाए गए उत्तर भारत और अन्य देशों के शोध भंडारों में साझा किए जा सकते हैं। आपका नाम, फ़ोन, सटीक पता, पहचान नंबर और मृत्यु की सटीक तारीख कभी शामिल नहीं की जाती।
7. आपके विवरण की जाँच और अनुवाद में कंप्यूटर की मदद (वैकल्पिक)। भारत में [ORGANISATION] द्वारा नियंत्रित प्रणालियों पर चलने वाले प्रोग्राम आपके विवरण की एक प्रति से नाम, स्थान और नंबर हटा सकते हैं, जाँच सकते हैं कि उसमें पर्याप्त जानकारी है या नहीं, उसका अंग्रेज़ी में अनुवाद कर सकते हैं, और डॉक्टरों के लिए लक्षण बता सकते हैं। ये मृत्यु का कारण तय नहीं करते, और आपका विवरण किसी बाहरी कंपनी को नहीं भेजा जाता।

हम इसकी सुरक्षा कैसे करते हैं। आपका नाम, फ़ोन नंबर, पता और पहचान नंबर एन्क्रिप्ट करके रखे जाते हैं। केवल वही लोग इन्हें देख सकते हैं जिनके काम के लिए ये ज़रूरी हैं, और वे क्या देखते हैं, यह दर्ज किया जाता है।

हम इसे कितने समय तक रखते हैं। [रखने की अवधि और उसके बाद क्या होगा]

आपके अधिकार। आप हमारे पास रखी अपनी जानकारी देखने, उसे सुधारने या मिटाने के लिए कह सकते हैं, या कह सकते हैं कि आपके उत्तर रिपोर्टों और शोध से बाहर रखे जाएँ। आप नीचे दिए संपर्कों के माध्यम से किसी भी समय अपनी सहमति वापस ले सकते हैं। शोध के लिए पहले से साझा किया गया पहचान-रहित डेटा वापस नहीं लिया जा सकता। आप [डेटा संरक्षण अधिकारी] से और फिर भारतीय डेटा संरक्षण बोर्ड से शिकायत कर सकते हैं।

किससे संपर्क करें।
- अपना डेटा मिटाने या बाहर रखने के लिए: [डेटा मिटाने और बाहर रखने का ईमेल], [फ़ोन]। आपको दिया गया केस नंबर बताएँ।
- आपकी ज़िला टीम: [ज़िला संपर्क का नाम, ईमेल, फ़ोन]।
- मार्गदर्शक संस्थान: [संस्थान का नाम, ईमेल, फ़ोन]।
- केंद्रीय टीम: [ईमेल, फ़ोन]।

आपकी पसंद। कृपया हर क्रमांकित बिंदु के लिए हाँ या ना कहें।
```

### Seed purposes

The same codes and required flags in both languages (a consent record answers
every purpose of the version it names); labels are translated.

| Code | Required | English label |
| --- | --- | --- |
| `record_and_interview` | yes | Record the death and complete the interview |
| `contact_followup` | yes | Contact me by phone or visit to complete or clarify the answers |
| `messages` | no | Send me SMS or WhatsApp messages about this interview |
| `cause_of_death_coding` | yes | Doctors and coders decide the cause of death (without my name, phone or address) |
| `statistics_reports` | yes | Use counts and summaries in government and statistical reports |
| `research_sharing` | no | Share de-identified answers in research repositories |
| `narrative_automated_processing` | no | Computer programs on [ORGANISATION]'s systems in India may de-identify, check, translate and suggest symptoms from my account (they do not decide the cause of death) |

Allowed modes: spoken, tap, signed; a witness may be recorded as present (no
witness name). Covered fields: the service default
(`consent_service.DEFAULT_COVERED_FIELDS`: the informant register fields and
the WHO answers `Id10007`, `Id10055`, `Id10057`, `Id10061`, `Id10062`).

## Web flow (owner 2026-10-22)

- **Project switch.** Project Setup, Data collection, "Respondent consent":
  "Require respondent consent" sets `consent_required`. Off: no consent
  screen anywhere on the web, and the server gate is off. On: needs at least
  one notice version.
- **Notice versions.** The notice is edited per project and per language.
  Saving an edit creates a new version (never an in-place change); every
  consent record keeps the version, language and SHA-256 of the text it was
  shown. Each version is marked "Pending legal review" until an admin
  approves it (once, audited as `consent_notice_approved`). A pending version
  is still usable: the screen works while legal review is open.
- **Registration (web).** When the project requires consent, the death
  registration screen shows the notice before the informant fields. The
  informant name, phone and address cannot be entered until the respondent's
  decision is recorded. Granted: the fields open and the consent travels with
  the registration (`consent` on `POST /intake/deaths`, `client_draft_id`
  null). Refused: the fields stay closed and empty, and the refusal is stored
  with the registration. On an edit, a newly entered informant field needs a
  granted consent recorded on the same screen. The offline station keeps its
  own rule: informant details always need a granted consent, whatever the
  project switch says.
- **Interview (web).** Before a web interview starts, when the project
  requires consent and the case has no consent decision on file (a direct
  start, or a registration made without one), the interview screen shows the
  notice in the questionnaire language and the form opens only after a
  decision is recorded (`POST /api/v1/intake/drafts/<draft_id>/consent`). A
  case whose registration consent is on file opens the form at once: the
  interview reuses it. Refused: the interview goes ahead, and the covered
  questions (the version's `covered_fields`, such as the respondent's name
  `Id10007`) are locked empty; the server refuses covered answers under a
  refused consent (`consent_conflict`).
- **What is recorded.** The notice version id, language and SHA-256, the
  decision, every purpose's choice, the mode (spoken, tap or signed, from
  the version's allowed modes), whether a witness was present, the time on
  the recording device and the recording user. Records are append-only.
- **Later.** Withdrawal (supervisor or data manager, with erasure and audit)
  is not built yet.

## Phone flow (native Expo app; owner 2026-10-22, `digitva-0vgh`)

The phone follows the station rule: **informant details always need a granted
consent against a notice the project serves**, whatever the project's
"Require respondent consent" switch says. A project with no notice cannot
record informant details on the phone.

- **Cached settings.** Each sync fetches `GET /intake/consent-config` per
  project and keeps it, notice texts (every language), purposes, covered
  fields and `consent_required`, in the interviewer's encrypted store with
  the other reference data. A failed fetch keeps the old copy. The consent
  screen needs only that copy, so it works offline. A notice whose
  `text_sha256` does not match its text, or a config with an unknown
  `refusal_behaviour`, is treated as no usable notice; there is no fallback
  to a built-in text (the unprovisioned sandbox project and the standalone notice of "Standalone notice" below excepted).
- **Registration.** The informant name, phone and address fields stay closed
  until a decision is recorded on the registration screen: the notice in the
  app language (switchable), one toggle per purpose, how consent was given
  and whether a witness was present, then "Respondent agrees" (every required
  purpose on) or "Respondent refuses". Granted opens the fields; refused
  keeps them closed and empty. With no usable notice the fields stay closed
  with the reason shown. The decision is stored on the phone (id, notice
  version, language, SHA-256, decision, purposes, mode, witness, time,
  signed-in user) and sent as `consent` (`client_draft_id` null) with the
  registration (`POST /intake/deaths`), whether queued offline or sent at
  once. A newly entered informant field on an edit of a server registration
  needs a granted decision on the same screen.
- **Interview.** Where the project requires consent and the notice is usable,
  a new or resumed interview with no decision on file for it shows the same
  screen before the questionnaire opens; no decision on file means no
  decision stored on the phone for this interview and none for its
  registration (a registration made on this phone with a decision is reused,
  no second asking). A downloaded case's server-side consent is not visible
  to the phone (the case reply carries no consent status), so the phone asks
  once for that interview and the server keeps the newest decision. The
  decision is stored with the interview and sent as `consent` naming the
  interview's `client_draft_id` with `POST /intake/submissions`.
- **Refusal.** The covered fields (the version's `covered_fields`, for example
  the respondent's name `Id10007`) are locked empty in the questionnaire and
  removed from what is sent (the answers and the stored copy of the draft),
  so the answers hash covers only what was sent. Registration informant
  fields are cleared and closed. Where the project requires consent but has no
  usable notice, the same lock applies with the reason shown.
- **In-progress sync.** A refusal on file (the interview's or its
  registration's) also keeps the covered fields out of `POST /drafts/sync`,
  out of a server version stored back on the phone, and out of the stored
  draft and its prefill the moment the refusal is recorded. The server does
  the same on its own: `POST /intake/drafts/sync` carries no `consent`, so it
  runs `consent_service.gate` against the consent on file and, where the gate
  would refuse, **strips** the covered fields from the stored draft instead
  of refusing the sync (a phone saving before its consent is uploaded must
  not fail; the final `/submissions` upload decides again with the phone's
  full answers). Decisions inherited from the registration cover the draft.
- **A refused inherited decision.** On 422 `consent_*` the interview's own
  decision is dropped; a decision inherited from the registration is shared
  and stays, and the draft is flagged so its form asks for a new
  interview-level decision.
- **What the server checks** (`consent_service.gate`): 422 `consent_required`
  (covered data without a granted consent), `consent_conflict` (covered data
  under a refusal), `consent_invalid` (unknown notice version, hash, language,
  purposes or mode). The phone shows the server's message; `consent_required`
  reopens the consent screen for that item; the item is never retried
  unchanged.
- **Not on the phone.** Withdrawal, and any change of a recorded decision
  after it has been sent (web, supervisor or data manager).

## Changing a decision during an interview (owner 2026-10-24, `digitva-wy90`)

Where the project requires consent, the phone interview's top bar shows a
status chip: "Consent: agreed", "Consent: refused" or "Consent: not recorded"
(the state is in the words and the chip's accessibility label, not in colour
alone; theme tokens). It is absent when the project does not require consent.

- Tapping the chip, or "Change consent decision" in the ⋮ menu, saves what is
  typed and opens the same respondent consent screen; the new decision
  replaces the one on file for this interview (`saveDraftConsent`).
- **Agreed to refused** strips the covered answers and their files from the
  stored draft exactly as a first refusal does, and keeps the covered
  questions locked empty. **Refused to agreed** reopens them (empty; the
  earlier answers are gone and are not restored).
- The new record has its own id and time and is the only decision sent with
  the interview (`consent` on `POST /intake/submissions`); the server keeps
  the newest, as it already does for a case asked again. The previous decision
  is not sent and not kept on the phone: `supersedes_client_id` must name a
  consent the server holds, and a decision taken during an unsent interview
  has not reached it.
- A decision inherited from the registration is shown as it stands; changing
  it records an interview-level decision and leaves the registration's
  shared record alone (the same rule as a refused inherited decision).
- Cancelling the consent screen changes nothing. After a send, the decision
  can no longer be changed on the phone (see "Not on the phone").

## In-progress saves (owner 2026-10-24)

No covered data is stored without a granted consent on file, in any save of
an unfinished interview. `consent_service.strip_unconsented_answers` runs the
gate on the consent on file (the attempt's own, else the case's registration
consent) and drops the covered fields instead of refusing the save:

- **Phone** `POST /intake/drafts/sync` and **browser** `PATCH
  /intake/drafts/<id>` (every section of the save) behave the same. The web
  interview records consent before the covered questions open, so a covered
  answer saved after a granted decision is kept; in a project that does not
  require consent nothing is stripped.
- `consent_required` and `consent_conflict` drop every covered field of the
  project. `consent_invalid` (a granted consent whose notice version does not
  cover some fields) drops only the fields it names.
- A phone sync that was stripped is marked `lastSync.stripped`; the same save
  sent again (same answers hash) is not a no-op while the mark is set, so once
  consent is on file it is stored in full and the mark clears.
- The final upload (`/submissions`, `/drafts/<id>/submit`) still refuses
  covered answers without consent (422), as above.

## Contact variables

Project-level consent settings hold: the deletion and exclusion email (and
phone), the mentoring institution (name, email, phone), the central team
(email, phone) and the data protection officer. The **district contact is
set per district** (the organization level that stands for a district in the
project's tree): each district unit carries its own contact name, email and
phone, and the notice picks the one for the district of the case. If a
district has none, the notice falls back to the central team. Every change to
a contact is audited and creates a new notice version, because the printed
text changes. A deletion or exclusion request received by email is recorded
in the case history (who, when, what was asked) and actioned by a supervisor
or data manager, as under "Withdrawal" in the consent bead.

## Notes for the project and legal review

- Purposes 1, 2 and 4 to 5 are shown as required because the interview cannot
  run without them; purposes 3 and 6 are the ones a respondent may refuse.
  Each project sets this in its consent settings.
- Sharing de-identified data with researchers abroad, the research exemptions
  of the Act, and whether the deceased's data falls under the Act are open
  legal questions and are not settled by this text.
- "Cannot be taken back" for de-identified data needs legal confirmation.
- Date of death: the draft promises the exact date is not included in
  repositories. Decided 2026-10-21 (export bead `digitva-fx2c`): the
  repository export carries the month and year of death and the age group,
  the district and rural or urban status, never the village, sub-district or
  street; GPS only as a point displaced at random by up to 2 km (one
  configurable constant), fixed per case from a secret seed, with no
  district-boundary check; location only when the respondent agreed to this
  purpose. The export design must enforce this.
- A Hindi and other-language version is needed before field use. Each
  translation is its own notice version.
- The notice must be shown, and the choices recorded, before any respondent
  personal data is saved. Decided 2026-10-21: on web, Expo and the offline
  station it is taken at registration, before the informant's name, phone or
  address are saved; the interview reuses that record and asks again only
  when the informant is a different person.

## Standalone notice (Collect Plus Path C; owner decision 2026-10-27, `digitva-5bzf`)

A Collect Plus phone used without a server
([Field Data Collection](field-data-collection.md) "Path C") has no consent
config to fetch, so it records consent against a notice bundled in the app.
This is the one exception to "never from values built into the app" (the
Offline app section below) and to
[Offline API Contract](offline-api-contract.md) 5.6, which that section
bounds.

- **Source.** The bundled notice is **generated from
  `app/services/consent_notice_seed.py`**, never written by hand: the same
  purpose codes and required flags, item 7 included, in English and Hindi. A
  drift test keeps the bundle equal to the seed, as `tests/services/test_consent_notice_seed.py`
  keeps the seed equal to this draft.
- **Placeholders.** `[ORGANISATION]`, contacts and the like are filled from
  the offline profile; how an unfilled placeholder is handled is open point 1.
  Because the fills change the text, the hash is per deployment.
- **Item 7 before enrolment.** `narrative_automated_processing` is offered and
  recorded like any purpose, and its toggle **defaults to "no"** while the
  phone is not enrolled. A "yes" is stored but acts only if the project
  later runs the pipeline (see `narrative-ai-processing.md`, which gates on
  the case's consent record). Whether the item-7 wording may name an
  organisation the respondent cannot yet reach is a legal question for
  `digitva-athy` (open point 2).
- **Push.** The consent object (offline contract 5.3) names a notice version
  identifier derived from the text hash (`standalone-<sha>`) and the push
  carries the **full text snapshot** the respondent saw. The server stores it
  as an append-only, source-flagged notice version for the project and checks
  the template hash against the platform allowlist; unknown text is flagged
  (offline contract section 17).
- **Never edited.** The stored text, hash, language, mode, witness flag, time,
  device UUID and profile snapshot are never edited; a correction supersedes.
- **Mobile sandbox alignment (rule).** The sandbox/bundled notice in
  `mobile/digitva-collect/src/consent.ts` must use the **seed's** purpose
  codes. The two codes that differ today are renamed to the seed's:
  `sms_whatsapp_messages` becomes `messages`, and `statistical_reports`
  becomes `statistics_reports`. The sandbox notice also gains the seed's item
  7. A code that exists in the app and not in the seed is a defect, caught
  by the drift test, because a mismatch otherwise fails only at push time.
- **Open points.** (1) Unfilled-placeholder handling; (2) legal review of the
  standalone item-7 wording.

## Offline app

The offline PHC app shows this notice and records the choices at
registration, as a `consent` record in the bundle (named by the
registration's `consent_client_id`) or the `consent` object on
`POST /api/v1/intake/deaths`; the interview reuses it, and a new consent is
taken at the interview start (the `consent` object on
`POST /api/v1/intake/submissions`) only when none is on file or the
informant is a different person. Each record names the notice version,
language and the SHA-256 of the exact text shown, and the station gets the
notice versions, purposes and district contacts from the signed station
config, never from values built into the app (the single exception is the
standalone notice above, for an unenrolled Collect Plus phone). See
[offline-bundle-and-transfer.md](offline-bundle-and-transfer.md).

Fixed 2026-10-21 in [offline-api-contract.md](offline-api-contract.md)
section 5: the hash is over the notice text string exactly as served, not the
rendered Markdown; the consent is keyed by the case (`client_draft_id` null
for a registration consent); every purpose of the version is answered; no
witness name; informant name, phone or address are entered only once a
granted record exists; withdrawal is recorded on the web only and reaches
the station as a `purge` list of consent ids.
