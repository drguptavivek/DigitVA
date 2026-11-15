---
title: Training Session Types, Phone Training and Graduation
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-11-15
---

# Training session types, phone training and graduation

Draft baseline from owner decisions of 2026-11-14. Session types, per-coder
copies, grants and areas by type, and per-session self-coding with its two
queues are implemented on the server (plan phases 1 and 2,
`.tasks/2026-11-14-training-session-types-implementation-plan.md`); so are the
admin import, graduation and the close checklist (server and admin panel,
phase 3) and the languages line's server side (`/coding/stats` `languages`,
`PATCH /api/v1/profile/languages`, phase 4). The web and phone clients are not.
Once approved it amends [Training and Demo Project](training-demo-project.md)
where the two differ; until then that document is the rule. Design notes and
options: `.tasks/2026-11-14-training-tracks-collection-coding-combined.md`.

## Why

The people trained differ, and so does the work they practise:

- Interviewers practise interviews (and are supervised); they do not code.
- Coders practise coding; they do not interview.
- Self-coding interviewers do both: they interview, then code their own
  interviews.

The Himachal field training (29 October to 6 November 2026) did not use the
training project: interviewers practised on the phone in a dummy project
(DEMOHP) with ordinary grants, which mixed practice with real lists and needed
access removed by hand. Training session S001 in TRN01 had coders, reviewers and
interviewers, and no interviews were sent into it. Training must therefore work
on the phone, separate from real work.

## Session types

Creating a session always asks its type. The type decides what exists in it.
There is no fourth type; existing sessions (S001) keep today's mixed behaviour.

| Type | Trainees | What they can do | Case copies |
| --- | --- | --- | --- |
| Interviewer | interviewers (how supervisors join is open; supervisors are web only) | Collect interviews; review what they collected; supervision on the web | none |
| Coder | coders | Code the standard training set only; no interviewing | the standard training set |
| Self-coding | coders who also interview | Interview, code their own interviews, and code the standard training set | the standard training set |

- **No reviewer role in training.** Reviewers are experienced coders on the
  platform. A coder looking back over their own coded forms (My coded cases and
  the recode window) is part of coding, whether the form is their own interview
  or from the standard set.
- **Self-coding is per session type**, not a project-wide setting on TRN01: a
  coder session must not gain interviewing. Coding one's own interview is
  allowed only in a self-coding session.
- The server enforces the session type on every request; the phone and the web
  only follow it.

## The standard training set

- Pseudonymised copies of real coded cases, as today.
- **English narratives only.** Today's set (199 of 200 Hindi narratives from
  `UNSW01NC0101`) does not meet this and is replaced for new sessions;
  existing sessions keep their copies. A staging count on
  2026-11-14 found 466 coded cases recorded as English (ICMR01 245, UNSW01 219,
  HP0001 2), so 200 can be chosen without translation.
- Open before choosing: confirm the "English" narratives are English and not
  Romanised Hindi (a sample read by someone authorised to see them), and decide
  which final causes may be the answer key (for example reviewed cases only)
  and the mix of causes, ages and projects.
- The trainer report scores only the standard set.
- Coders code the standard set in English only. Each coder gets a random 10 of
  the 200; different coders' sets may overlap, but each coder's 10 is their own
  random draw. Each coder gets their own copies of their 10, so two coders never
  share one case's coding.

## Coding in a self-coding session

Self-coding trainees see two buttons, on the web and the phone alike:

- **Code from my interviews**: only their own interviews in this session, once
  synced. Practice only; not scored.
- **Code from standard training set**: their share of the standard set. Scored.

The two queues never mix. The coding page shows a count for each:
"My interviews coded: X of Y" and "Standard training set coded: X of Y".
Coder sessions show only the second button and count.

## Phone and web

- Every session type works on both the phone and the web; the trainee chooses.
  Exception: interview supervisors are web only.
- The phone app is Android. iOS users train on the web (until an iOS build is
  available) for both interviewing and coding, so the web keeps full parity for
  all three session types.
- On the phone, training runs in **DigitVA Collect**. Collect Plus is only for
  real offline coding and interviewing needs. Online coding works in both apps:
  once a trainee's interview has synced, they code it online.
- Offline coding of training cases is out of scope for the first phase.
- Phones on older app versions keep today's behaviour: they never see training.

## Interview languages

- Trainees interview in any interview language the platform has, in the
  language they are proficient in (for example Bengali in Bengal, Tamil in
  Tamil Nadu). This replaces "English forms only" for TRN01.
- Self-coding trainees code their own interviews in that language.
- The standard training set stays English only (above).

## Adding trainees

- Admins create trainee accounts, as today: an email account gets a
  verification invite by email; a mobile-only account gets a one-time sign-in
  code shown once to the admin; a phone can also be signed in with a sign-in QR
  code. The session import takes identity only (email or phone, and name) and
  adds the accounts to the session. The admin-run import also creates any
  missing accounts in the same step (owner, 2026-11-15), using the same rules
  and sign-in delivery as the organisation users import, so account creation
  and session enrolment are one step.
- The import asks once whether the rows are coders, interviewers, or both,
  limited to what the session type allows (interviewer session: interviewers;
  coder session: coders; self-coding session: both). Supervisors and death
  reporters are not import choices.
- The trainee's real unit is often unknown before training, so the import does
  not ask for it.

## Graduation

After the training an admin (admins only) opens the session:

- A list of every trainee with their role (coder, interviewer, both).
- At the top, **Select organisational project**. That project's unit tree then
  becomes a searchable dropdown on each row.
- **Cadre** is chosen once at the top and applied to every row, and can be
  changed per row.
- Coding languages can be set per row; coders can also set them in their own
  profile.
- Graduation grants only the coder and interviewer roles (a self-coding
  trainee gets both), never reviewer or data manager, and never to the training
  project or a demo project.
- **Save** per row or **Save all** writes the real grants through the ordinary
  grant rules, with a preview and a reason on any refused row. The preview shows
  separately any change to a cadre the user already holds and any revoked grant
  it would reactivate, and these need confirmation. A saved row is
  marked as granted; saving again changes nothing.
- Real grants are **active immediately**. The project's coding and interview
  gates limit what a new user can actually do there.
- This replaces the `graduation.csv` export and re-import.

## Coder languages on the coding home screen

Applies to every project, not only training, on the web and the phone:

> **Your languages:** English, Hindi ✎
> **Forms pending coding:** Hindi 42 · Tamil 5 · Telugu 3

- "Your languages" lists the coder's coding languages, with an edit link to the
  profile; with none set it reads "none set".
- "Forms pending coding" counts the forms available to this coder to code now,
  in the project they are working in and within their current scope, grouped by
  each form's narration language, regardless of the coder's own languages. Only
  languages with available forms appear; it is not the project's list of
  enabled languages.
- Counts only, from one grouped query; no case detail.

## Privacy

- The standard set stays pseudonymised; photos, documents and audio are
  original and must not be copied or shared (as today).
- Practice interviews are typed by trainees and are not pseudonymised. Trainees
  use made-up details only; the onboarding notice and the training script say
  so, including for role play between trainees.
- Respondent consent stays required in training.

## Decisions on the review items (owner, 2026-11-14)

- **Accounts.** Admins create trainee accounts (email invite, one-time mobile
  code, or sign-in QR). The admin-run session import creates missing accounts
  and enrols everyone in one step. This amends "No generated accounts" in the
  current training policy: accounts are still created only by an admin, through
  the ordinary import rules.
- **Coders' languages.** The standard set is English only, and coders code it
  in English; an imported coder defaults to English.
- **Interviewer sessions** import interviewers only. Supervisors and death
  reporters are not import choices. Supervisors stay web-only.
- **Trainer report:** admins only.
- **Graduation:** admins only; it grants coder and interviewer roles only.
- **Standard set:** 200 English cases; each coder gets their own random 10,
  as their own copies; sets may overlap between coders. Data-use clearance is
  given. (Checking that the chosen narratives are real English, not Romanised
  Hindi, remains a step when the 200 are picked.)
- **Training mode.** On the phone the trainee picks the training project in the
  post-PIN project choice; while it is selected only training work shows, with a
  "Training mode" banner. Graduate before closing; after close the training
  project leaves the project choice.
- **Practice interviews are never discarded.** They stay after the session
  closes so results can be audited. Only sent interviews reach the server, so
  every trainee syncs before the admin closes the session (trainer checklist).
  Admins see practice interviews in the training project's intake views; the
  trainer report scores only the standard set.
- **Hindi wording** for the new strings is approved.

Still to verify before implementation: a just-sent interview becoming codeable
without waiting for the hourly sweep; per-session self-coding grants and the
queue default (standard set unless "my interviews" is asked for); that project
gates limit a newly graduated user; and that "Forms pending coding" uses the
same rule as allocation (this section moves to the coding policy when approved;
the server rule is in coding-workflow-state-machine.md, "Coder coding
languages").
Coders setting their own coding languages in their profile changes a manager-set
control in every project and needs its own baseline in the coding policy first.
