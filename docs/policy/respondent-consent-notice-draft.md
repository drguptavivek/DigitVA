---
title: Respondent Consent Notice, Draft Text
doc_type: policy
status: proposed
owner: Vivek Gupta
last_updated: 2026-10-22
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
config, never from values built into the app. See
[offline-bundle-and-transfer.md](offline-bundle-and-transfer.md).

Fixed 2026-10-21 in [offline-api-contract.md](offline-api-contract.md)
section 5: the hash is over the notice text string exactly as served, not the
rendered Markdown; the consent is keyed by the case (`client_draft_id` null
for a registration consent); every purpose of the version is answered; no
witness name; informant name, phone or address are entered only once a
granted record exists; withdrawal is recorded on the web only and reaches
the station as a `purge` list of consent ids.
