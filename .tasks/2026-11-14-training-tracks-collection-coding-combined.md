# Training split by audience: collection, coding, combined (phone practice)

- Status: plan, not started (owner: "don't implement - just plan", 2026-11-14)
- Priority: owner to rank
- Created: 2026-11-14
- Goal: separate training tracks because the people differ: collection (interviewers, death
  reporters, supervision), coding (coders, reviewers), and interview + coding for self-coding.
  Interviews practised in the phone app; coding possible in the phone app too.

## Context (verified)

- docs/policy/training-demo-project.md: one project TRN01, Expo-web only, one role per
  participant per session, 200 pseudonymised pre-coded cases per session, `training=1` scope;
  the native app sends no `training` and the server excludes TRN01 from every other request
  (app/services/training_scope.py). Native app/training/* routes redirect to /worklist.
- Staging (read-only check 2026-11-14): Himachal field training (29 Oct - 6 Nov) used the dummy
  project DEMOHP "Hamirpur Demo" with ordinary grants (~107 phone interviews; ~170 interviewer
  grants since deactivated). TRN01 S001 (active since 22 Oct): 6 coders, 3 reviewers,
  5 interviewers, zero interviews sent into TRN01. S002 closed, no participants.

## Owner decisions (2026-11-14, supersede the design below where they differ)

- Creating a session always asks its type: interviewer, coder, or self-coding interviewer.
  The session type decides which functions exist in it.
- Interviewer session: collects interviews; supervision takes place; interviewers can review
  what they collected. No case copies needed.
- Coder session: no interviews. Coders work only on the 200 pseudonymised training forms.
- Self-coding session (the trainees are coders): they do their own interviews and code them,
  and they also code the pseudonymised set. The trainer report is generated only on the
  pseudonymised set.
- Self-coding trainees see two buttons, on the web and the phone alike: "Code from my
  interviews" (only their own synced interviews in this session) and "Code from standard
  training set" (their share of the pseudonymised set). Only the second counts in the report.
  The coding page shows their counts, per set: "My interviews coded: X of Y" and "Standard
  training set coded: X of Y" (coder-only sessions show only the second).
- No reviewer role in training: reviewers are experienced coders. A coder looking back over
  their own coded forms is part of coding (My coded cases, recode window), self-coded or not.
- Self-coding sessions run entirely on the phone: interview and coding, no browser. Online
  coding works in both Collect and Collect Plus; Collect Plus is only for offline self-coding.
  Once a trainee's interview has synced, they can code it online in either app.
- Every session type works on both the phone and the web; the trainee chooses. The phone app is
  Android (APK) only, so iOS users train on the web for both interviewing and coding. The web
  must therefore keep full parity for all three session types (including self-coding: interview
  on the web, then code "My interviews to code" and the training set).
- DigitVA Collect is the default app for training and general use. Collect Plus is heavy (data,
  memory) and only for real offline coding and offline interviewing needs. Design, test and pilot
  training on Collect first.
- Interview languages on TRN01: every interview language the platform has, not English or
  Hindi only. Trainees interview in whatever language they are proficient in (Bengali in
  Bengal, Tamil in Tamil Nadu). Self-coding trainees code their own interviews in that
  language. New Hindi UI strings still need owner approval.
- The 200-case pseudonymised training set must have English-only narratives. Conflict to
  resolve: today's corpus narratives are Hindi (199 of 200 from UNSW01NC0101, policy
  training-demo-project.md:22-23), so the corpus source or its narratives must change.
  Staging count 2026-11-14 (read-only; cases with an active final COD, by recorded narration
  language): English 466 (ICMR01 245, UNSW01 219, HP0001 2), so 200 English cases exist without
  translation. Unchecked: whether "english" narratives are real English or Romanised Hindi, and
  whether the final COD is reliable enough to be the answer key (e.g. reviewed cases only).
- Onboarding pain (creating users, then granting real access): the trainee's real unit is
  often unknown before training. So:
  - Session import takes only identity: username, email, phone, name. The import asks once
    whether the rows are coders, interviewers, or both (limited to what the session type allows).
    It creates missing accounts and adds everyone to the session.
  - After training, the trainer opens the session: a list of all trainees with their role
    (coder, interviewer, both). At the top, "Select organisational project"; that project's unit
    tree then becomes a searchable dropdown per user. "Save" per row or "Save all" writes the real
    grants through the ordinary grant rules (preview first, refusals shown per row).
  - Replaces the graduation.csv export/import round trip.
  - Cadre: chosen once at the top and applied to all rows, then changeable per row.
  - Coding languages: coders set their own in their profile; the graduation list may also set
    them per row.
  - Coders see their coding languages: the coding home screen shows "Your coding languages: ..."
    and, when none are set (or none match the project's narration languages), a prompt linking
    to the profile to set them. Applies to real projects and training alike, web and phone.
  - The coding home screen also shows, for the project the coder is working in, how many forms
    are available to code within the coder's current scope, per narration language of those
    forms, counted regardless of the coder's own languages. Owner wording, two plain lines:
    "Your languages: English, Hindi" and "Forms pending coding: Hindi 42, Tamil 5, Telugu 3".
    No per-language advice text; the profile link sits next to "Your languages". Not the project's enabled languages: only
    languages that have available forms appear. One grouped count query, no N+1; counts only.
  - Saved real grants are active immediately; the project's coding and interview gates limit
    what a new user can actually do there.
- Training mode (owner, 2026-11-14, after Fable plan review): the app has a training mode. On the
  phone the trainee picks the training project in the existing post-PIN project selection; while
  it is selected the app exposes only training access and shows a "Training mode" banner at the
  top. Training and real work never mix because the scope follows the selected project.
- Session close: successful trainees normally get real project access at graduation, so they keep
  device access. Graduate before closing. After close the training project is revoked/hidden from
  the project selection; a training-only (not graduated) trainee loses access, which is acceptable
  (practice data only). Find a clean way to hide the closed session from Home.
- Graduation gives only coder and interviewer roles (never reviewer or data_manager).
- Standard training set: REVISED from English-only to a mixed English + Hindi set; the coder's
  languages decide which forms they get. Needs language-aware allocation (today fixed 10-case
  slots spread languages; a coder missing a slot's language is refused).
  SUPERSEDED again (owner, 2026-11-14): English only, keep it simple. The pool is 200 coded
  English forms; coders code only in English. Each coder gets a random 10 from the pool; sets may
  overlap between coders as long as each coder's 10 is its own random draw. Implementation note:
  give each coder their own copies of their 10 (as slots do today) so two coders never share one
  case's coding workflow. No language-aware allocation needed.
  (Previous, superseded:) the pool holds 200 coded English + 200 coded Hindi forms. Each coder gets 10
  random forms: a random English/Hindi mix if their languages include both, English only if only
  English, Hindi only if only Hindi. (A coder with neither is refused with the existing
  language message.) The trainer report still scores each coder's 10.
- Consequence: self-coding is per session type, not project-wide on TRN01 (a coder session
  must not get interviewing), so the plan's per-session exemption replaces decision 1's
  recommendation.

## Options (planning agent, before owner decisions; superseded where they differ)

The recommendations below (project-wide self-coding on TRN01, track role lists, reviewer
roles) are SUPERSEDED by the owner decisions above and by docs/policy/training-session-types.md.


| Option | Phone | Separation | Cost |
|---|---|---|---|
| A. Dummy project + ordinary grants (DEMOHP way) | works today, old APKs too | none: practice in real lists/KPIs/exports; no report or answer key; manual grant cleanup | no code, manual each time |
| **B. `track` on the TRN01 session + phone sends `training=1` for the training project only** | new APK | existing server scope unchanged | 1 small migration, a few service lines, ~6 Expo modules |
| C. One training project per track (TRN01/02/03) | new APK | works | training id becomes a set everywhere; `training.project` shape change old APKs parse |

Recommended: **B**. Keep A as the fallback for trainees who cannot install the new APK.

## Design (B)

- Tracks: `mas_training_sessions.track` TEXT NULL, check `collection|coding|combined`; NULL =
  legacy mixed (S001 unchanged). Roles per track checked in add/bulk add (`role_not_in_track`):
  collection = death_reporter, interviewer, interview_supervisor (+ reviewer_data_manager as
  trainer assistant?); coding = coder, reviewer_data_manager; combined = coder (implies
  interviewer under self-coding), reviewer_data_manager, interview_supervisor. Collection
  sessions may have `coder_slots = 0` (no case copies). `/me/access` `training` gains `tracks`
  (new key only).
- Phone scope: no new enrolment. When `access.training.project` is present the phone adds it to
  reference data, collectible and retained sets. One helper `scopeFor(access, projectId)` adds
  `training=1` only for the exact training project id, derived from the draft's own project,
  never a screen toggle. Old APKs never send it: unchanged behaviour.
- Phone UI: a separate Training block on the worklist (Training badge), one-time onboarding
  notice ("made-up details only"), then `POST /api/v1/training/me/start` (bearer CSRF unverified).
- Leaving: session closed or participant removed -> server answers 403 `training_ended` to
  `training=1` callers (instead of a forever-retried `forbidden`); the phone marks that
  project's drafts "practice, not sent", discardable without the unsent-work guard and kept out
  of real counts. Trainer checklist: everyone syncs before close.
- Supervision: web only (Training > Interview supervision); supervisor-only accounts cannot sign
  in on a phone today. Phone supervision = new scope (decision 3).
- Self-coding (combined): set `self_coding_enabled = true` on TRN01 (setup + data migration like
  `c8e4a2f6b1d3`). Coder grant then implies interviewer on the same slot; "Code this case now"
  works with no new code paths. Side effects: every TRN01 coder can also interview; submitter
  name / PII tier rules change for TRN01; Collect Plus offline coding turns on for TRN01.
  Alternative: per-session exemption (~4 call sites, costlier).
- Phone coding: online Code tab with `scopeFor`. Offline coding of training cases out of phase 1.
- PII: corpus unchanged; practice interviews are typed by trainees, "made-up details only";
  consent still required.
- Trainer report: track on list/header; interviewer rows add phone vs web and completed vs
  refused; combined adds a self-coded count; aggregate queries only.
- Graduation: unchanged CSV; closing the session replaces DEMOHP-style grant cleanup.

## Changes

- Schema (one additive reversible migration): `track` column + check; `coder_slots` 0..100 with
  `(coder_slots > 0) OR track = 'collection'`; data step TRN01 self-coding (decision 1);
  optional `web_intake_available_locales = ["en","hi"]` (decision 4).
- API (additive): `track` on admin session create/list/get and `flask training-demo create
  --track`; `tracks` in `/training/me` and `/me/access`; 403 `training_ended`; `role_not_in_track`.
- Expo: src/training.ts (`scopeFor`, selector, `training_ended`), src/sync.ts, src/cases.ts,
  src/attachmentUpload.ts, src/consent.ts, worklist Training block, Code/Review queue training
  segment, native onboarding and discard, admin Track picker. Native-only modules via
  src/nativeRouteScreens.
- Hindi strings needing owner approval: Training block title, "Practice: use made-up details
  only", onboarding body, "Training has ended. These practice interviews were not sent.",
  "Discard practice interviews" + confirmation, track names.

## Docs first

docs/policy/training-demo-project.md (tracks, zero-slot sessions, phone scope replacing "native
app sends no training", leaving/discard, self-coding, locale, report);
docs/policy/field-data-collection.md; docs/policy/coding-workflow-state-machine.md (TRN01
self-coding); docs/current-state data model, API v1 `training`, admin panels.

## Tests

- pytest: track refusal (single, bulk; NULL accepts all); zero-slot rules; bearer intake for
  TRN01 with/without `training=1` (409 `training_scope` pins old APKs); bearer reads with
  `training=1`; `training_ended` vs `forbidden`; Code-now own TRN01 interview allowed and real
  non-self-coding project still refused; `/me/access` keeps old keys; report counts bounded.
- Jest: `scopeFor` exact-id only; reference pack includes training project; training-only
  account no `no_collection_access`; purge keeps drafts; `training_ended` leaves real drafts;
  web-bundle-boundary; `make check-web`.
- Maestro: 96-training-interview-send (+ web supervisor), 97-training-code-now,
  98-training-ended-discard; rerun 70, 82, 83 as regressions.

## Phases

0. Verify: bearer CSRF on `/training/me/start`; `client_draft_id` marks phone drafts;
   `interviewer_context` and TRN01 grants at sign-in/refresh, and store wipe of a training-only
   account on close; offline-coding import under `training=1`; `/me/access` bearer filtering
   (app/routes/api/me.py:37) vs `training.project`. Then policy docs and owner decisions; bead.
1. Server: migration, tracks, self-coding flag, `training_ended`, report. Old APKs unaffected;
   no data loss.
2. Expo native collection track; APK; pilot collection session on staging.
3. Phone coding and combined track; Maestro 97.
4. Retire DEMOHP-style practice for new-APK trainees (DEMOHP data kept).

Risks: a `scopeFor` bug sending `training=1` on a real draft holds it as `case_conflict` (not
lost, stuck); old-APK trainees see nothing; training-only accounts lose device access on close;
project-wide self-coding blurs the coding track.

## Open owner decisions

1. TRN01 self-coding project-wide (recommended) or combined-only exemption.
2. Discard unsent practice drafts after close without the unsent-work guard; sync-before-close rule.
3. Supervision web-only for now, or a phone supervision screen.
4. Hindi interview forms on TRN01, and the Hindi strings above.
5. reviewer_data_manager allowed in the collection track as trainer assistant.
6. Collect Plus offline coding of training cases out of phase 1.
