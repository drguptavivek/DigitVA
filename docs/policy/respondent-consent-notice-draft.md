---
title: Respondent Consent Notice, Draft Text
doc_type: policy
status: proposed
owner: Vivek Gupta
last_updated: 2026-10-21
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
