# Maestro end-to-end scenarios (digitva-xjpk)

Owner 2026-11-12. Collect Plus debug build, dev server, run locally on the
emulator and the Samsung (never CI). Every run: `flask seed e2e-users create`
-> enrol -> flows -> `flask seed e2e-users teardown` (always, even on failure).

Each scenario asserts the Drafts and To do counts on Home before and after, and
that answers, images and audio are unchanged. P1 = data-loss risk, run every time.

Expected results are grounded in decisions and commits since 2026-10-29 (Source
column: commit sha, bead id or doc path). "OPEN: ..." = no decided behaviour;
owner to answer before the flow is written. Doc paths are under `docs/`.

E2E users (`current-state/test-project-tst001.md`, 9ca1b2d46): `all` (coder,
reviewer, data_manager at project; death_reporter + interviewer at SC01 ANM;
interview_supervisor at PHC01 MO), `interviewer` (SC01 CHO), `coder` (project).
Roster being extended by the owner (2026-11-12) with single-role users: death_reporter, interviewer x2, interview_supervisor, coder x2, reviewer, data_manager, and `all`; the User column on sections 1, 6, 7, 7b names the user to run each row with.

## 0. Setup and identity
| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| S01 | Enrol (QR, or "Log in without a QR code" with email + password), set a PIN of at least 6 digits, land on Home with the right project; a person with several projects is asked to choose the home project | P1 | policy/mobile-sign-in.md (manual enrolment, home project), digitva-kspl, policy/field-data-collection.md |
| S02 | "I have a sign-in code" opens the server page; email + code shows a new generated password once, the code then stops working; five wrong codes void it; a wrong email and a wrong code give the same answer | P2 | policy/mobile-sign-in.md section 3 |
| S03 | Wrong PINs: five free (warning from the third); after the fifth the store refuses any PIN for 1 min, after the sixth 5, seventh 15, eighth and later 60; a PIN tried while locked is not counted; the wait survives app kill; nothing is erased; correct PIN after the wait works | P2 | policy/field-data-collection.md "Wrong PINs and PIN reset", digitva-kfi, 2d78e9660 |
| S04 | (see K01-K08) | - | - |
| S05 | Fourth phone on one account -> 409 `device_limit`, message "Up to 3 phones can be signed in at once. Manage devices from Profile or another signed-in phone."; no phone is evicted; the refused QR stays usable; after the owner frees a slot on web, sign-in works | P2 | policy/mobile-sign-in.md "Account device limit", digitva-65m5, src/strings deviceLimit |
| S06 | Device revoked on server while signed in (401 `session_revoked`): with unsent work the tokens are dropped, the store is kept and Home says "Access removed - N items not sent. Contact your supervisor."; sign in again sends it; with nothing unsent the store is wiped | P1 | src/auth.ts header, policy/field-data-collection.md, digitva-tnr6 |
| S07 | Language switch English <-> Hindi from the 文A menu on Home, and the form's own language menu inside a form, then back; answers unchanged; the switch is refused while the last save failed (draftNotSaved) | P2 | 8ac748ed4, 5f6fe16ff |
| S08 | Password reset or deactivation on the server (401 `session_ended`), or `refresh_reused` / 409 `refresh_retry_race` / `session_expired`: the account shows "sign in again", local work kept, unsent work sent after sign-in | P1 | src/auth.ts header, current-state/device-collection-api.md |
| S09 | Account with terms pending: sign-in succeeds with `terms_required`; every call except accept answers 403 `terms_required`; the app shows the terms gate; after accept work continues | P2 | current-state/device-collection-api.md, digitva-9an9 |
| S10 | Project with collection switched off: sign-in names `project_intake_off` with its own message, not "no access" | P2 | policy/mobile-sign-in.md (digitva-7amd.24), 2d78e9660 |
| S11 | Screenshots on Android are allowed until the end of 31 December 2026 (India), blocked after; an installed older build keeps its 25 November expiry | P2 | 940b798f8 |
| S12 | Plain Collect never asks "enable coding" at first launch (missing preference = on); an explicit Off in Settings is kept. Collect Plus still asks | P2 | 157dbf65e, digitva-qfji |
| S13 | Home loads for an ANM (death reporter + interviewer) and for a CHO; Home and Interviews show no coder links and no zero-count rows | P2 | d024b5ad0, policy/field-data-collection.md "Collect Home and Interviews by role" |
| S14 | Public demo is in Maestro scope (owner 2026-11-12): "Try the demo" on enrol opens the demo slot against the demo server (debug build may point EXPO_PUBLIC_DEMO_SERVER at a test demo); demo work never mixes with real profiles | P2 | owner 2026-11-12; S/nativeRoutes/enrol.tsx:318; S/enrolment.ts:110 |

## 1. Register a death (death reporter)
| ID | Scenario and expected result | User | Pri | Source |
| --- | --- | --- | --- | --- |
| R01 | Register a death with all required fields -> appears in My registered deaths; Register asks for the project (no silent default); "today" follows the project time zone | death_reporter | P1 | d024b5ad0, 87fff09cd |
| R02 | Missing or bad required field -> 422 `invalid_registration`, the field named | death_reporter | P2 | current-state/device-collection-api.md |
| R03 | Register offline -> queued -> sync online -> server has it once (retry with the same `client_death_id` creates no duplicate) | death_reporter | P1 | current-state/device-collection-api.md, policy/field-data-collection.md "Idempotent upload" |
| R04 | Leave registration half done, Home, return -> fields kept: the draft is stored as `registration-in-progress`, flushed on hide, blur and lock, restored when Register reopens; only Save or a confirmed Discard removes it; no Home row | death_reporter | P1 | S/nativeRoutes/register.tsx:222,552,567,583,641 |
| R05 | Collection gate paused, outside its dates or at the daily limit: online with a gate answer under 15 minutes old, a new registration or unregistered interview is refused with the notice shown on Register; continuing drafts, registered deaths and uploads are never refused; offline or stale gate allows | death_reporter | P1 | b8732d608, edf8b1375, 0e1a5e308, policy/project-clock-and-gates.md |
| R06 | Registration edited while its send is in flight -> the edit is kept and sent | death_reporter | P1 | 7e7007766 (D14) |
| R07 | GPS capture when Death Report opens: warm-up, then High, Balanced, High-without-dialog, last-known chain; works indoors without timing out | death_reporter | P2 | d024b5ad0, policy/native-location-capture.md |

## 2. Interview (interviewer)
| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| I01 | Start from To do, consent Yes, complete, send -> server receives, To do -1 | P1 | policy/field-data-collection.md |
| I02 | Consent No -> dialog asks once before wiping -> Cancel -> Yes restored, other answers kept; No is not saved while the dialog is open | P1 | a3e383895, efb539594 (digitva-9xn9.22), b4deba337 |
| I03 | Consent No -> Cancel twice, leave, reopen draft -> consent Yes, answers kept (the hold ends only on the first change or save without the No, or on Confirm) | P1 | a3e383895 |
| I04 | Consent No -> Confirm -> covered fields wiped, refusal recorded and sent; re-consent later brings the interview back with its prefill rebuilt from current sources (HIV/malaria presets, interviewer, deceased block); a refused interview does not offer Start | P1 | efb539594, 0ace5b17e (digitva-lgzl), d024b5ad0, current-state/device-collection-api.md |
| I05 | Change an answer that hides later questions, change it back -> the engine keeps hidden answers while editing, so un-hiding shows them again; Complete prunes irrelevant answers (only relevant ones are submitted) | P2 | vendor/who-va-2022/src/engine/session.ts:244-262,437-441, engine/validation.ts:245-248 |
| I06 | Validation refused (422 `invalid_interview`) -> interview reopens as in progress, "Not accepted: <message>" on its card, one problems row per question named with a Go button; fix -> can send | P2 | policy/expo-client.md "Refused uploads", digitva-3nui, digitva-man7 |
| I07 | Save draft, leave, reopen from Drafts -> same page and answers | P1 | policy/field-data-collection.md "Unsent work is never purged" |
| I08 | Case started by another interviewer -> case screen shows "As of the last sync ({time}), {name} started this interview on {date}." (no warning box; English and Hindi); you may still start | P2 | 275155702, 0ace5b17e, 176093dd1 |
| I09 | Fill and send fully offline -> queued -> online sync sends once | P1 | policy/field-data-collection.md "Idempotent upload" |
| I10 | Network off during send -> stays unsent, retry sends once; a non-JSON 200 (captive portal) is retried, not counted as sent | P1 | 273a4f2e4 |
| I11 | Finish and press Home -> one upload pass runs inside the 60 s the store stays unlocked | P1 | 40ee1a528 |
| I12 | Local save fails (access removed, draft conflict, storage error), then Finish -> stays on the form with "Your latest answers could not be saved. They are still on this screen. Try again."; Back shows the unsaved prompt; Save now never says "saved" | P1 | 5f6fe16ff (digitva-9xn9.8) |
| I13 | Server lost a file the phone marked uploaded (409 `attachments_pending`) -> phone clears the mark and resends; if the file is also gone from the phone, the interview is held as `attachment_missing` until the interviewer replaces or removes it | P1 | 2582c138e (digitva-9xn9.6) |
| I14 | Interview started outside the collection period, or site off at upload -> phone sends, server accepts and holds it (out of coding, review, KPIs, exports) until a data manager releases or rejects | P1 | b8732d608 |
| I15 | Complete but unsent interview can be reopened on the phone | P2 | 2d78e9660 |
| I16 | 422 `consent_*` after upload -> stored decision dropped, form asks consent again; 409 `refusal_stale` -> fresh consent requested, the stale copy not retried | P1 | current-state/device-collection-api.md, current-state/api-v1.md |
| I17 | 409 `conflict` (already submitted by a teammate, or case closed) -> held as `case_conflict`, message says which, not resent until "Send again", never deleted | P1 | current-state/device-collection-api.md |
| I18 | Edit a sent interview from Revise -> sent as a correction (reason fixed list); later completion wins, older kept as history; refused once coding is final (`locked`) | P2 | policy/web-intake.md (digitva-xz83), policy/interview-revisions.md |

## 3. Media (image, audio, other attachments)
| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| M01 | Attach image (camera) -> thumbnail shown | P1 | policy/phone-attachments.md |
| M02 | Attach image or file from "Choose image" / "Choose file"; PDFs open in the viewer | P2 | 1b2f37d4b, 2d78e9660 |
| M03 | Record audio -> playable; finished recording stops and rewinds (no loop) | P1 | 1b2f37d4b |
| M04 | Replace image / audio -> asks first; only the new one kept | P2 | 1b2f37d4b, d024b5ad0 |
| M05 | Remove image / audio -> asks first; gone, rest of draft kept | P2 | 1b2f37d4b |
| M06 | Media survives Home + return, app kill + relaunch, lock + unlock, profile switch + back, reopen draft | P1 | policy/phone-attachments.md |
| M07 | Send with media -> server has every file, correct sizes | P1 | 2582c138e |
| M08 | Media attached offline -> sent later | P1 | policy/phone-attachments.md |
| M09 | Draft reopened from server after a store reset: answers whose files the server holds say "Saved on server" (no re-record asked); sent read-only media viewable | P2 | 5c567811c (digitva-n3ec) |
| M10 | Medical certificate upload offers Camera and previews a saved image | P2 | 1b2f37d4b |

## 4. Stop and resume (on a draft with answers + media)
| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| P01 | Home, wait, return: same page, answers, media; no skeleton flash, list shows last count | P1 | 7d238868f, 0e1a5e308 |
| P02 | Force-stop / swipe away, relaunch, unlock: draft intact | P1 | policy/field-data-collection.md |
| P03 | Lock now, unlock with PIN: draft intact | P1 | same |
| P04 | Auto-lock after 5 minutes idle, unlock: draft intact | P2 | src/autoLock.ts (IDLE_LOCK_MS) |
| P05 | Rotate screen mid-form: phones (under 600 dp) are locked portrait at runtime, so the form does not rotate; tablets rotate; answers kept | P2 | app/_layout.tsx:88-93 |
| P06 | Another app on top mid-form: returns to the same page, answers kept | P2 | policy/field-data-collection.md |

## 5. Profiles
| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| U01 | Add a second profile on the same phone | P1 | policy/field-data-collection.md "Sign-out keeps the data" |
| U02 | Switch A -> B -> A (lock, profiles list): each sees only its own drafts, nothing lost | P1 | same |
| U03 | Sign out with nothing unsent -> confirmation asks once; profile stays listed as "Signed out" with its data; sign in again and PIN shows the data. (Old text "profile removed" was wrong) | P1 | digitva-dxgj (2026-10-27) |
| U04 | Sign out with unsent work -> confirmation lists unsent items by kind (not shown if the store is locked); Cancel keeps everything | P1 | same |

## 6. Coding (coder)
| ID | Scenario and expected result | User | Pri | Source |
| --- | --- | --- | --- | --- |
| C01 | ICD-11 code online: search, pick a leaf, save -> server has it | coder1 | P1 | policy/doris-cod-workflow.md |
| C02 | Non-leaf (e.g. BA41) refused on every surface: "<CODE> is a category, not a final code. Choose a more specific code under it." (Hindi pending review) + searchable child list; pick a child -> accepted; server answer 422 `non_leaf_category` | coder1 | P1 | digitva-dn15, efb539594, current-state/api-v1.md |
| C03 | C02 offline (airplane mode) -> same refusal and child list from the phone's data pack | coder1 | P1 | digitva-dn15, policy/doris-cod-workflow.md "Collect Plus offline parity" |
| C04 | ICD-10 project coding online: Step 1/Step 2 as on the web, Not Codeable its own screen, final save forwards search id and rank | coder1 | P1 | 273a4f2e4, digitva-tk7j (phone check still open) |
| C05 | Code offline -> sent when online; a code saved while DORIS never answered is still sent as the final (no DORIS result) | coder1 | P1 | digitva-9cll.14, policy/doris-cod-workflow.md |
| C06 | Interview answers changed after coding (stale) -> the older code is sent marked stale with the new interview data, held unapplied; the phone asks the coder to recode | coder1 | P1 | digitva-9cll.14 |
| C07 | Recode after the server already holds a code (pending, applied or refused) -> the newer code replaces it; older kept in audit history; an earlier final is superseded, not deleted; recode inside the window as often as needed | coder1 | P1 | digitva-9cll.14, 87fff09cd |
| C08 | Coding refused or DORIS rejected -> interview is never held for its coding; refused coding kept as a notice and the interview is not resent every sync | coder1 | P1 | digitva-9cll.14, efb539594 |
| C09 | Case list: coder sees only cases of forms and sites they are granted; another site's case not listed | coder1 | P1 | policy/access-control-model.md, policy/case-list-views.md |
| C10 | Open a case: the full workspace (category counts, yes/no history, narrative, attachments, SmartVA, DORIS certificate, private note) is readable before coding, offline too | coder1 | P2 | policy/doris-cod-workflow.md "Offline coding workspace" (digitva-9cll.22.8) |
| C11 | New DORIS certificate has non-cause fields prefilled from the interview as suggestions, each labelled with its source question, editable; causes and intervals not prefilled; whether the coder changed a value is recorded | coder1 | P1 | policy/doris-cod-workflow.md "Prefill" (digitva-hln) |
| C12 | DORIS rejects the coder's code -> coder may still save; saved code is sent as their final with the DORIS data (DORIS is advisory) | coder1 | P1 | digitva-9cll.14 |
| C13 | DORIS engine slow or unavailable -> coder can save a code manually; spinner with progress while it starts; no hang; sent with no DORIS result | coder1 | P1 | digitva-9cll.14, 1b2f37d4b |
| C14 | CODEEDIT warning on a flagged edit -> shown; coder can still save (advisory) | coder1 | P1 | digitva-9cll.14 |
| C15 | Certificate chain (immediate, antecedent, underlying, contributing, intervals) saved in the order shown; only final ICD-11 codes allowed on the certificate | coder1 | P1 | 159e7402d, policy/doris-cod-workflow.md |
| C16 | Remove or reorder a cause line before saving -> Part I lines reorder up/down, Part II is a single line; saved chain matches the screen | coder1 | P2 | S/workspace/doris/DorisPanel.tsx:712-714,1013 |
| C17 | `&` / `/` cluster: selection line shows every part's title (e.g. BD1Z); an expression repeating a part (BD1Z/BA01/BD1Z) is refused; pickers do not append a part already present | coder1 | P1 | 0ace5b17e (digitva-iae8) |
| C18 | Sex-incompatible code refused; age-restricted code asks the same confirmation as the web (DORIS warning stored) | coder1 | P1 | policy/doris-cod-workflow.md "Collect Plus offline parity" |
| C19 | ICD-11 chapter 22 / non-selectable refused in search and save; KD3B.Z allowed; picker offers "Causing condition not known" | coder1 | P2 | 210ea326e, policy/who-2022-icd11-coding-allowability.md |
| C20 | Search by English text and by code prefix -> results; no Hindi search (no language parameter); empty results show "No matching conditions." / "No matches in this axis." (hard-coded English, expected: translated) | coder1 | P2 | S/workspace/doris/picker/IcdPicker.tsx:204, ScopedSearch.tsx:82; BUG digitva-gvlq: empty-result strings untranslated |
| C21 | Offline search returns the same leaf results as online for a sample (flat MMS list filtered by the pack) | coder1 | P1 | 574545617 (golden sets replay), policy/doris-cod-workflow.md |
| C22 | Required certificate fields (incl. manner of death) missing -> refused with required markers and hints, as on the web | coder1 | P2 | 273a4f2e4, policy/doris-cod-workflow.md |
| C23 | Half-coded case: leave, Home, kill app, reopen -> coding draft restored exactly | coder1 | P1 | policy/field-data-collection.md (unsent work), digitva-9cll.5 (still to prove) |
| C24 | Lock / profile switch mid-coding -> coding draft restored | coder1 | P1 | same |
| C25 | Save code, edit before sync -> only the latest coding row is sent (it keeps the answers hash from coding time) | coder1 | P1 | current-state/device-collection-api.md (sync.ts sentAnswers) |
| C26 | Mark a case not codeable -> a reason is required ("others" needs text); decision kept through Central's review-state round-trip (case does not return to the pool) | coder1 | P2 | S/workspace/doris/DorisPanel.tsx:501-507, SimpleCodPanel.tsx:255-320, 8b11109b4 (digitva-9xn9.2) |
| C27 | Case held by another coder is not in the pick pool; taking it -> 409 `held_by_another` -> "Another coder took this case. Refresh the worklist."; no read-only view | coder1 + coder2 | P2 | app/routes/api/coding.py:668-703, app/services/coder_workflow_service.py:972-985, S/workspace/CodeNowButton.tsx:123-126 |
| C28 | A coder's own collected case is excluded from their pool outside self-coding projects (server blocks coding it) | coder1 | P1 | digitva-9xn9.22, b4deba337, bd memory owner-decision-2026-10-20 |
| C29 | 200 new cases per coder per project per day cap (project clock); recode, demo, tester allocations not counted | coder1 | P2 | 87fff09cd |
| C30 | Web (Select2) on an ICD-11 project: Select2 hidden, non-leaf refused on save, leaf accepted; values already saved still re-validate | coder1 | P2 | digitva-dn15, efb539594 |
| C31 | Phone shows the VA cause bucket while coding, by the analytics rule | coder1 | P2 | 8c270b051 |
| C32 | Standalone one-step coding: "Save cause of death", View summary, Revise; no Step 1/2 wording | coder1 | P2 | 2d78e9660, policy/doris-cod-workflow.md |
| C33 | Standalone phone codes a stale case: sent marked stale, draft kept until recode taken (as enrolled) | coder1 | P1 | 7e7007766 |
| C34 | Changed coding on a case the server holds: server replaces the held coding, the older one goes to `result.history`; phone shows "Sent - waiting for the server's DORIS" or "Refused by the server: {reason}". Expected on an old server's 409 `coding_conflict`: a clear reason, not "a reason this app does not know" | coder1 | P2 | policy/offline-api-contract.md:1169, S/workspace/QueueScreen.tsx:147-156, S/sync.ts:386,650-665; BUG digitva-4dly: no codingRefused_coding_conflict string |

Dropped from section 6: former C28 (independent second coder) and C29
(reviewer adjudication): no such workflow (one coder; reviewer samples; see
Dropped list).

## 7. Review (reviewer)
| ID | Scenario and expected result | User | Pri | Source |
| --- | --- | --- | --- | --- |
| V01 | Review tab opens the online review list; open a case, save review (list-valued other_conditions accepted) | reviewer | P2 | d024b5ad0 |
| V02 | Send a case back to the interviewer: fixed reason code only (missing_information, inconsistent_answers, wrong_respondent_or_case, needs_clarification), no free note; interviewer sees the case as sent back and can revise | reviewer | P2 | policy/interview-revisions.md |
| V03 | Reviewer releasing a started review keeps their saved Step 1 | reviewer | P2 | bd memory reviewer-release-keeps-step1 |

## 7b. Interview supervisor (PHC MO)
| ID | Scenario and expected result | User | Pri | Source |
| --- | --- | --- | --- | --- |
| SV01 | Supervisor sees only cases in the units below their PHC; another PHC's cases not listed | interview_supervisor | P1 | policy/web-intake.md "Supervisors" |
| SV02 | Tiles (Needs my decision, Overdue revisits, Stuck 30 days, Total in scope) match the lists behind them; overdue on the project clock | interview_supervisor | P2 | src/strings supervision*, edf8b1375 (digitva-at68) |
| SV03 | Confirm or reject a duplicate/cancel flag; mark duplicate; cancel; reopen; each with a reason (no names, phones or addresses in it); confirmed duplicate leaves every coding queue | interview_supervisor | P1 | policy/web-intake.md, policy/coding-workflow-state-machine.md |
| SV04 | Two complete interviews on a case: supervisor chooses one with a fixed reason (better_quality, more_complete, original_incorrect, switch_back); both interviewers notified; the loser's later upload is kept as history | interview_supervisor + interviewer1 + interviewer2 | P1 | policy/web-intake.md (digitva-bqzm) |
| SV05 | "Reopen for revision" with a fixed reason (cod_review_requested, new_information, data_correction) -> interviewer sees it, revises and resends; coding restarts at once; earlier coding kept as inactive history | interview_supervisor | P1 | policy/interview-revisions.md |
| SV06 | Supervisor reopens while the interviewer has a newer local draft: if the draft is based on the reopened version it becomes the revision (interviewer sees the supervisor note before sending; earlier version kept in history); if based on an older version it is kept as a separate copy marked for review and the reopened version is the base. Nothing on the phone is discarded | P1 | owner 2026-11-12 (A, fallback B); digitva-1b50 |
| SV07 | Refused-consent case: supervisor sees the refused state and the age group and sex only (no reason recorded); cannot edit answers | interview_supervisor | P2 | S/RefusalPanel.tsx:5-22, policy/respondent-consent-notice-draft.md "Refusal profile" |
| SV08 | Supervisor names and PII follow per-project rules: unit grants in the org see names; project/site-scope grants and mentoring institutes do not | interview_supervisor + data_manager | P1 | digitva-9xn9.22, b4deba337 |
| SV09 | Supervisor never assigns or reassigns cases; no Assign action shown | interview_supervisor | P2 | policy/web-intake.md "Supervisors" |
| SV10 | Interview-supervisor-only user cannot code or see coder screens (Code tab and coder links absent; coding endpoints refused) | interview_supervisor | P1 | policy/web-intake.md "Supervisors", e2e roster extension (owner 2026-11-12; supervisor-only user exists) |
| SV11 | `all` user (interviewer + supervisor + coder): each tab (Code, Review, supervision) shows only its own role's lists | all | P2 | d024b5ad0 |
| SV12 | Supervisor offline: supervision is online only; lists fail with "Could not reach the server. Check the connection and try again."; no actions queued | interview_supervisor | P1 | S/supervision/api.ts, S/network.ts:10-14, S/ui.tsx:891 |

## 8. Sync
| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| Y01 | Nothing to send: "Send now" disabled on Home and in the Sync sheet; refresh updates the sync time | P2 | 1b2f37d4b |
| Y02 | Several queued items -> all sent once, counts update | P1 | policy/field-data-collection.md |
| Y03 | Server down or 5xx during sync -> clear error with Ref, everything kept, later sync succeeds | P1 | src/auth.ts header |
| Y04 | Refresh stores the collection gate even if the answer arrives while the PIN lock is up | P2 | edf8b1375 |

## 9. Hand-offs and concurrency (two users / two phones)
Two e2e users on the emulator and the Samsung at once (`all` as SC01 ANM and `interviewer`).

| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| H01 | Reporter A registers a death -> interviewer B syncs -> case in B's To do | P1 | policy/web-intake.md |
| H02 | A starts the interview, sends nothing; B opens the same case -> "As of the last sync ({time}), {A} started this interview on {date}." | P1 | 275155702, 0ace5b17e |
| H03 | A starts and stops; B resumes -> both drafts reach the server; first complete wins, the other is kept as a superseded copy (a candidate if complete) for the supervisor; neither discarded | P1 | policy/web-intake.md (digitva-bqzm) |
| H04 | A and B both send -> server keeps both, a late sender's files move to the superseded copy (one `draft_files_moved_to_copy` action); no orphaned data, case never waits for attachments forever | P1 | 9abf7afdf (digitva-9xn9.5) |
| H05 | A's interview already complete on server; B opens the case -> "another complete interview" notice (`other_complete_interview`); B's work is kept as a superseded copy | P1 | current-state/device-collection-api.md |
| H06 | Same user, two phones, same draft -> later completed version becomes the coder's, older kept as `replaced` history; a draft sync from the other device answers 409 `conflict` | P1 | policy/web-intake.md, current-state/device-collection-api.md |
| H07 | Two coders push offline coding for one case: the first import applies; the second is refused with the allocation code -> "Refused by the server: another coder is working on this case"; both kept in history | P1 | app/services/offline_coding_import_service.py:546-590 |
| H08 | (merged into H07) | - | - |
| H09 | Stale coding: coder codes offline, interview data changes on server, coder syncs -> code sent marked stale, held unapplied; recode replaces it, history kept | P1 | digitva-9cll.14 |
| H10 | Stale code on a case another coder already finalised: stale coding is refused `coded_version_superseded` and never applied; a changed coding over a final only via the recode rules, else `recode_not_allowed`; a replaced final is deactivated, not deleted | P1 | policy/offline-api-contract.md:1172, offline_coding_import_service.py:576-586,720-728 |
| H11 | Recode after server received a code -> replaces it, history shows both | P1 | digitva-9cll.14 |
| H12 | Coder codes while a reviewer sends the case back: the phone checks payload version, draft context and step before save and throws `workspace_stale`; expected a clear "case changed, reload" message, not the generic one | P2 | S/workspace/CaseWorkspaceScreen.tsx:393-410; BUG digitva-nm7s: no string for workspace_stale |
| H13 | Interviewer revises and resends after coding started -> server releases coding; coder's phone code becomes stale after sync | P1 | policy/interview-revisions.md, 87fff09cd |
| H14 | Device of A revoked with unsent work -> A keeps the work, "Access removed - N items not sent", cannot send until signed in again; B's work and the case are unaffected | P1 | src/auth.ts header, policy/field-data-collection.md |
| H15 | Web interview first save over a phone-won draft after the interviewer cleared an answer -> the cleared answer stays cleared on reload (browser sends an explicit null, only for loaded keys, once) | P2 | 43ea80c00 (D22), digitva-k00b, 7e7007766 |
| H16 | Phone sends an interview whose attachment the server lost -> 409 `attachments_pending`, nothing stored (same for device and browser paths) | P1 | 2582c138e |
| H17 | Teammate wins the case after B's draft was open -> B's draft files are not lost to the 30-day stale-draft purge | P1 | 9abf7afdf |
| H18 | Interviewer A and B edit their own drafts of one case at once (both online): each edits only their own copy (own draft per interviewer); the first completed submit wins the case, the other becomes a superseded copy (candidate if complete); every saver is recorded; nothing is merged field by field | P1 | policy/web-intake.md "Own draft per interviewer", "Parallel interviews" (digitva-xz83, digitva-xpqm) |
| H19 | Same, one or both offline: both send on reconnect in any order; first completion wins the case, the later one is kept as a superseded copy with its files; both phones' items clear on the 2xx; case detail on each phone after sync names the other interviewer. Same field vs different fields makes no difference (whole-interview copies) | P1 | policy/web-intake.md, 9abf7afdf, current-state/device-collection-api.md |
| H20 | One interviewer sends while the other is mid-edit: the mid-edit phone sees "As of the last sync ... {name} started/completed this interview" only after its next sync; its own draft stays editable and sends later as superseded copy; nothing is overwritten or discarded | P1 | 275155702, policy/web-intake.md, current-state/device-collection-api.md (`case_submitted_by_other`) |
| H21 | Same interviewer, phone and browser edit one draft: phone draft sync with a stale `base_updated_at` -> `conflict: true`, "This interview was also edited on another device; the newer version was kept." (`kept: incoming` or `server`); browser save with a stale `if_updated_at` -> 409 `draft_stale`, nothing written, tab asks to reload; the replaced content stays as history | P1 | current-state/device-collection-api.md (draft sync reply, Browser guard) |
| H22 | Phone completion while the browser draft has newer saves: the phone completion is submitted, the browser draft's content kept first as `replaced` history; a later browser completion is a correction that wins | P1 | current-state/device-collection-api.md, policy/web-intake.md |
| H23 | Same or different fields edited on two devices: sync is draft-level, not field-level; a newer server draft wins whole with "This interview was also edited on another device; the newer version was kept."; a local change made during the sync keeps local; 409 `conflict` -> `draft_sync_blocked`; the replaced content is kept as history; an explicit browser null of a loaded key wins (D22) | P1 | S/draftSync.ts:24-25,483-541, 43ea80c00, current-state/device-collection-api.md |
| H24 | Interviewer sends a correction while a supervisor reopens or sends the case back: send-back/reopen unlocks revision (state `finalized_upstream_changed`); the correction arrives, coding restarts, nothing overwritten; if coding is final and no send-back is open the later version is kept as history `locked: true` | P1 | policy/interview-revisions.md, current-state/device-collection-api.md |
| H25 | Same as SV06 with the interviewer offline mid-edit: on next sync the A/B rule applies; no local edit lost | P1 | owner 2026-11-12; digitva-1b50 |
| H26 | Supervisor chooses between two complete interviews while one interviewer is still editing: choice becomes a new payload version (`supervisor_choice`), coder's copy replaced and coding restarts with earlier coding kept inactive; refused 409 while a reviewer's coding session is live; the loser's later upload kept as history | P1 | policy/web-intake.md (digitva-bqzm) |
| H27 | Coder A and coder B on one case online: allocation is exclusive (one active allocation per case); B sees "Another coder took this case" / is refused; no double coding | P1 | policy/coding-workflow-state-machine.md "One active allocation", src/strings codeNowHeldByAnother |
| H28 | Coder A offline, coder B finalises first: A's stale code is refused `coded_version_superseded` and never applied; a recode over a final only through the recode rules, else `recode_not_allowed`; history keeps both | P1 | policy/offline-api-contract.md:1172, offline_coding_import_service.py:576-586 |
| H29 | Coder finalising while interview data changes (interviewer correction, ODK edit): server releases coding (`release_coding_for_changed_payload`); coder's allocation released; the code already saved stays as inactive history; phone shows stale / recode | P1 | policy/interview-revisions.md, 87fff09cd, digitva-9cll.14 |
| H30 | Coder and reviewer: reviewer coding opens only after the coder's recode window closes; a coder recode inside the window blocks reviewer start; reviewer release keeps their saved Step 1; reviewer save does not require NQA | P2 | policy/access-control-model.md line 464, bd memory reviewer-release-keeps-step1, policy/narrative-quality-assessment.md |
| H31 | Reviewer sends back while the coder is coding: the open workspace throws `workspace_stale` on save; expected a clear reload message; coder's saved work is not discarded | P2 | S/workspace/CaseWorkspaceScreen.tsx:393-410; BUG digitva-nm7s: no string for workspace_stale |
| H32 | Data manager web edit (`PATCH /intake/deaths`, `PUT .../identifiers`) while a phone edits: the phone's draft sync is draft-level (as H23); a PATCH with a stale `if_updated_at` is refused; identifiers change at any time with case state unchanged; the phone sees changes after sync | P1 | current-state/api-v1.md, S/draftSync.ts:24-25,483-541 |
| H33 | Upstream (ODK) change while a phone coder has the case: the case must be recoded with the fresh data; the coder's phone shows the case needs recoding and the stale coding is not applied (sent marked stale, kept in history) | P1 | owner 2026-11-12; contract:1172; BUG digitva-62fa (phone shows nothing today) |
| H34 | Death reporter edits the registration while an interviewer has the draft: the draft's prefill is fixed at creation and is not refreshed from registration edits; register-field edits refused 409 `case_completed` once an interview is complete; identifiers still change | P1 | S/drafts.ts:104,520,618-621, current-state/api-v1.md |
| H35 | Reporter's registration queued offline and edited on web before it syncs: `client_death_id` makes the send idempotent (200 with the current case); the phone's registration edited during its send is kept (D14); a stale `if_updated_at` is refused rather than overwritten | P1 | current-state/device-collection-api.md (death POST), 7e7007766 (D14) |
| H36 | Two reporters register the same death on different phones: both succeed; possible-duplicate hint shows the earlier registrant; supervisor confirms or rejects the duplicate (excludes it from coding); no data deleted | P1 | policy/web-intake.md (possible duplicates, digitva-umc4), policy/coding-workflow-state-machine.md |
| H37 | Consent changes while another interviewer has the case open (refusal recorded by A): B's open draft is cleared to the refusal-only answers and paused until B explicitly resumes after a fresh grant; nothing B collected returns | P1 | policy/respondent-consent-notice-draft.md "Later agreement and shared cases" (digitva-hs7e.15.2) |

## 10. PIN, password and account recovery
| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| K01 | After five wrong PINs "Forgot PIN? Sign in with password" -> password sign-in for the same account -> set new PIN -> every interview, media and unsent work kept; fingerprint/screen-lock entries dropped | P1 | policy/field-data-collection.md, digitva-kfi |
| K02 | Forgot PIN offline: "Forgot PIN?" opens sign-in with the reset flag; offline it shows "Could not reach the server. Check the connection and try again."; nothing wiped | P1 | S/nativeRoutes/unlock.tsx:328-334, S/nativeRoutes/sign-in.tsx:70 |
| K03 | "Forgot password?" opens the server page; people cannot set their own password: a new generated password comes from a sign-in code or "ask for a new one" | P2 | policy/mobile-sign-in.md section 3 |
| K04 | "Forgot PIN?" is not shown before the fifth wrong PIN in a row | P2 | policy/field-data-collection.md |
| K05 | A sign-in not started from "Forgot PIN?", or as a different account, never resets a PIN (deep link cannot set one) | P1 | policy/field-data-collection.md, 2d78e9660 |
| K06 | Forgot PIN on profile B while profile A has unsent work -> A untouched, A's lock counter separate | P1 | policy/field-data-collection.md |
| K07 | Password changed on the server -> phone keeps working until its session ends (`session_ended`), then the new password is needed; local work kept | P2 | src/auth.ts header |
| K08 | Standalone phone: forgot PIN -> "Forgot PIN?" (after five wrong) opens an erase confirmation, typed word required, Cancel deletes nothing | P1 | policy/field-data-collection.md |

Dropped from section 10: former K04 "Change PIN from Settings" (no such screen); desktop station scenarios (owner: out of scope).

## 11. Exports and backup
Collect Plus enrolled: encrypted backup of unsent work only (Settings, passphrase
of at least 12 characters, share sheet), no CSV export. Standalone: CSV/JSON
export of own records and full backup.

| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| E01 | Back up unsent work -> file produced with unsent drafts, attachments, offline coding and consent; no PIN, token, store secret or passphrase inside; read back before sharing; warning shown first | P1 | policy/field-data-collection.md "Export and backup" (digitva-5bzf, digitva-axim), 7e7007766 (D25) |
| E02 | Backup works offline | P1 | same (nothing goes to a cloud service) |
| E03 | Restore on a fresh install or the same account: adds only missing ids (an existing id kept); consent restored with each interview, so restored interviews send; a newer local copy needs a confirmed "replace newer" and the picked file is kept for the retry; sent once (server `kept`/`superseded`) | P1 | ffa623a2e, 7e7007766 (D15), policy/field-data-collection.md |
| E04 | Restore into another account -> "This backup belongs to a different account. Nothing was changed." | P1 | S/standalone/DataActions.tsx:44 |
| E05 | Standalone export: CSV/JSON of own records, "omit identifiers" option, no PIN or keys, file only in private cache and deleted after share | P2 | policy/field-data-collection.md |
| E06 | Server-side after the run (web, data manager): SmartVA input export for Excel (CSV with apostrophes, no BOM), raw variant for processing (no apostrophes, no BOM); other data-manager CSV cells starting with a formula character get a leading apostrophe | P2 | efb539594, digitva-9xn9 |

Dropped: former E04 (share/print interview PDF): no such feature; only PDF
attachments open in a viewer (M02).

## 12. Debug logs and diagnostics
| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| D01 | Settings > Help & support > Export errors; with no entries: "No errors recorded." | P2 | policy/expo-client.md "Local error log", digitva-j6cx |
| D02 | Export errors -> share sheet with text file `digitva-errors-<date>.txt` (app version, device, entries newest first); holds codes and Ref lines only: no answers, names, phones, tokens, URLs, ids | P1 | same |
| D03 | Errors while offline are logged locally (encrypted store, newest 500 / 30 days, never uploaded); entries made while locked wait in memory (up to 50) and move in on unlock; kept through sign-out | P2 | same |
| D04 | After network off mid-send, the log shows status, error code, method and masked route; not the payload; same error on same screen within a minute is one row | P2 | same |
| D05 | Debug build banner "Debug build: do not collect real interviews." shown | P2 | src/strings debugWarning, policy/field-data-collection.md |
| D06 | Usage diagnostics setting On/Off (daily totals only); a failed save stays Off with Retry | P2 | src/strings telemetry*, policy/expo-client.md |

## 13. Standalone (Collect Plus, no server)
| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| T01 | New interview refused until name, age, sex, country and both mortality levels are set; refused before anything is written; the profile locks Id10010/a/b and Id10002/Id10003 | P1 | 747af76d9 |
| T02 | Home tabs (In progress, Pending coding, Coded) refresh after save; rows show "Last edited"/"Completed" with local time; buttons Resume, Code, Revise | P2 | 136a949d0, 1b2f37d4b |
| T03 | Draft started on an older questionnaire version shows read-only; a label-only fix does not strand drafts | P2 | 2d78e9660 |

## 14. Server and script checks around the run (not Maestro)
| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| X01 | `manual-db-restore.sh`: a connection opened during the scratch restore no longer breaks the swap; a truncated dump leaves the target untouched; needs typed confirmation, refuses remote/production targets | P1 | 43ea80c00 (digitva-rbj8), 7e7007766, ff0761757 |
| X02 | Staging backup checker passes on a fresh backup and fails on a stale one | P1 | ff0761757, 43ea80c00 |
| X03 | UI regression: Interviews "More" chip plain at default filter; chips 44 px; card words follow the UI language; Hindi choice labels not wrapped early; tab labels scale with Large text | P2 | 176093dd1, 0e1a5e308, 1b2f37d4b |
| X04 | Screens do not flash on return; only the last-used form language loads after first paint | P2 | 7d238868f |

## 15. Project and form settings that change the phone (enabled / disabled pairs)
Each pair runs on one e2e project by flipping the setting as admin or data manager
on web, then sync or re-open Home (`/me/access` carries the resolved settings).

| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| PS01 | Self-coding ON: a `coder` grant also lets the holder interview (derived, no grant row); after a completed interview with valid consent the submit reply offers "Code this case now"; the worklist shows "Code now" on the user's own completed interviews awaiting coding; the submitter sees the deceased's name on their own cases only | P1 | policy/web-intake.md "Self-coding projects", policy/coding-workflow-state-machine.md "Self-coding", digitva-xuxk |
| PS02 | Self-coding ON, "Code this case now" while the case is still in attachment sync or `smartva_pending` -> server 409 with the workflow state; phone says "This case is still preparing. Checking again shortly..." then "Still preparing. Try again from the worklist."; when ready it allocates to the submitter (scope, language and coding gates still apply; pick mode skipped) | P1 | policy/coding-workflow-state-machine.md, src/strings codeNow* |
| PS03 | Self-coding ON, another coder already holds the case -> refused; "Another coder took this case. Refresh the worklist." | P2 | same |
| PS04 | Self-coding ON, coder already holds another coding case -> "You already hold another coding case."; release offers a confirm that unfinished Step 1 work on it is discarded for good; "Keep my case" leaves both untouched | P1 | same, src/strings codeNowRelease* |
| PS05 | Self-coding OFF: a coder grant gives no interviewing; no "Code this case now" or "Code now"; an interview goes to the normal pool; the interviewer's own collected case is never allocated to them as a coder (random or pick), enforced by the server | P1 | policy/coding-workflow-state-machine.md, digitva-9xn9.22, b4deba337 |
| PS06 | Self-coding switched off with an unsent coder-interviewer interview: the interview is accepted; the coding is refused `self_coding_required`; expected a clear reason, not "a reason this app does not know" | P1 | app/services/offline_coding_import_service.py:401-410; BUG digitva-4dly: no codingRefused_self_coding_required string |
| PS07 | Self-coding cannot be turned on while intake is `off` (server refuses); mentoring institute coders never get the implied interviewer grant | P2 | policy/web-intake.md "Self-coding projects" |
| PS08 | Intake `direct`: Home offers "Start interview" only, no Register a death; interviews start without a registration | P1 | policy/web-intake.md (web_intake_mode, 1338), digitva-7amd.25 |
| PS09 | Intake `death_register`: Register only; an interview starts only from a registered death | P1 | same |
| PS10 | Intake `both`: Register and Start both offered | P2 | same |
| PS11 | Intake `off`: project interviewers cannot collect in the app; sign-in says `project_intake_off` | P1 | same, policy/mobile-sign-in.md (digitva-7amd.24) |
| PS12 | Collection gate ON (paused, outside dates, or daily limit) vs OFF at site or unit: see R05 (refusal only for new starts, online, gate answer under 15 minutes old); gate OFF -> new starts allowed; held interviews released when the gate save covers their start date | P1 | b8732d608, edf8b1375, policy/project-clock-and-gates.md |
| PS13 | Coding gate closed or coding unavailable: profile shows " - Inactive" / " - Coding unavailable"; offline coding is not offered; recode inside its window still works | P2 | S/accessProfile.ts:121-122, S/codingCapabilities.ts:17-22 |
| PS14 | Project ICD-11 (DORIS) vs ICD-10 (simple entry): ICD-11 project shows the DORIS certificate, ICD-10 project the Step 1/Step 2 screens; a code of the other edition is refused with `wrong_classification`. (`selectable` per-death choice is retired) | P1 | policy/doris-cod-workflow.md "Project modes", current-state/api-v1.md, digitva-0n3 |
| PS15 | Masked vs unmasked coding project: masked shows Step 1 then Step 2 with PII hidden; unmasked has one final assessment (immediate COD, underlying COD, associated conditions) or the one-step DORIS final | P2 | policy/doris-cod-workflow.md "Project modes" |
| PS16 | Device coding preference ON vs OFF (Collect Plus first launch, off by default; plain Collect missing = on): OFF hides online ICD-11/DORIS and bundled offline coding tools, preserves all work, ICD-10 coding and collection unaffected; ON grants no permission by itself | P1 | policy/field-data-collection.md (digitva-hs7e.7), 157dbf65e |
| PS17 | Offline coding access = self-coding on + unmasked DORIS + ICD-11 + active coder grant; without all four the offline route is not offered | P1 | app/services/access_summary_service.py:314-320, S/codingCapabilities.ts |
| PS18 | DORIS / CODEEDIT suggestions: advisory in every project; there is no per-project switch to make them blocking (see C12, C14) | P2 | digitva-9cll.14 |
| PS19 | Equity extension ON: the interview shows "Was the place where the deceased usually lived rural, urban or an urban slum?" after Id10055 (optional, English and Hindi); OFF: absent; older drafts stay valid either way. New projects default ON | P2 | policy/digitva-who-form-overrides.md, digitva-7amd.26 |
| PS20 | Narration languages and form extensions (narration language, social autopsy, NQA) follow the project's form options: only the enabled ones are offered in the served form; NQA and Social Autopsy follow the project for enrolled accounts and are off standalone | P2 | policy/field-data-collection.md (line 600, 646), policy/doris-cod-workflow.md (digitva-9cll.22.4) |
| PS21 | UI languages from admin: a removed language falls back to the bundled pack, then the base language, then English; answers unchanged | P2 | S/uiPacks.ts:130-141, S/i18n.ts:140-175 |
| PS22 | Media questions per form: only document photos have project switches (`web_intake_death_summary_enabled`, `web_intake_medical_records_enabled`); no audio or image switch; standalone drafts keep their saved question set | P2 | app/models/va_project_master.py:233-240, 1b2f37d4b |
| PS23 | Two-coder requirement per project: none exists (one coder, sampled reviewer); no scenario | - | policy/coding-workflow-state-machine.md |
| PS24 | Recode window per project (default 24 h, set by the project): recode allowed inside the window from the coder's first final of the round; after it the case is reviewer-eligible | P2 | bd memory owner-decision-2026-10-20-the-coder-recode, 87fff09cd |

## 16. After enrolment (phone and profile lifecycle)
| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| L01 | Enrolment code single use: a used, expired (QR emailed 24 h / Devices page 5 min to 7 days; password-reset QR 6 h), revoked or voided code gives one answer, 404 `enrolment_invalid` ("The enrolment code is invalid, used or expired. Ask for a new one."); a new code voids the previous; a pending QR is voided by a password or factor reset | P2 | current-state/device-collection-api.md, app/services/device_auth_service.py enrol_device, policy/mobile-sign-in.md, src/strings errEnrolInvalid |
| L02 | First sync downloads projects, questionnaires, cases, reference data, translations, consent config, identifier types and UI packs; the offline ICD engine ships in the build and is not downloaded | P1 | S/sync.ts:832-884, S/AppState.tsx:389, S/FirstDownloadModal.tsx |
| L03 | Re-enrol the same phone (same `client_device_uuid`, e.g. second enrolment code or password): one device row per UUID, no second row; idempotent | P2 | policy/field-data-collection.md (Device identity), digitva-5bzf |
| L04 | Change server / re-enrol is refused while any signed-in profile has unsent work or a locked store (names each interviewer, says unlock and sync); otherwise asks once, signs everyone out (stores, PINs kept) and opens the enrol screen; a signed-out profile's data stays encrypted and can be sent only to the old server | P1 | policy/mobile-sign-in.md "Changing server is re-enrolling", digitva-dxgj |
| L05 | Home project is set at enrolment only; the enrol screen shows no "switch project later" hint (hint removed, owner 2026-11-12) | P2 | owner 2026-11-12; BUG digitva-c4n9 |
| L06 | Grant added after enrolment (new site, new role such as coder): next access refresh shows it (new Code/Review tab, new project); no re-enrolment; existing drafts untouched | P1 | policy/field-data-collection.md (multi-project, lines 380-390), d024b5ad0 |
| L07 | Role removed but other grants remain: refresh drops that role's screens and downloads; unsent work of that role kept and still tried first on every sync | P1 | policy/field-data-collection.md "Unsent work is never purged" (digitva-tnr6) |
| L08 | One project leaves the access summary (grant paused/revoked, intake turned off, site form deactivated): its server copies (cases, contacts, settings, forms) deleted from the phone; unsent drafts, registrations, queued actions and revisions kept; worklist says "Project paused - N items waiting to send" with the reason; new work there blocked; sync still sends the unsent rows first | P1 | policy/field-data-collection.md (digitva-tnr6, 2026-10-22), current-state/device-collection-api.md line 540 |
| L09 | Last project/grant removed -> 401 `session_revoked` (same as S06): unsent work keeps the store read-only "Access removed - N items not sent"; none unsent wipes only that profile's store | P1 | src/auth.ts header, policy/field-data-collection.md |
| L10 | User deactivated, or password/factor reset, or sign-out everywhere on the server (session version bumped) -> 401 `session_ended`: data kept, "sign in again" (same as S08); pending QR voided | P1 | src/auth.ts header, policy/mobile-sign-in.md |
| L11 | Device revoked by admin or by the user from Profile ("decommission"): sessions on that device end with a keep-data reason; local work kept; other phones and shared-device users untouched; audited | P1 | policy/mobile-sign-in.md "Account device limit and decommissioning", app/services/device_auth_service.py revoke_device |
| L12 | Device marked compromised (lost/stolen): server refuses the device's signed bundles; no extra phone behaviour beyond revoke. Station-only; no phone scenario | - | app/services/device_auth_service.py; dropped (station out of scope) |
| L13 | Refresh-token problems: `refresh_reused` (an old token presented), 409 `refresh_retry_race` (lost-response within 60 s), `session_expired`, `refresh_invalid`, `device_invalid` -> tokens dropped, "sign in again", data kept; offline and 5xx keep everything. Refresh slides 30 days but never past 90 days from sign-in | P1 | src/auth.ts header, current-state/device-collection-api.md |
| L14 | App upgrade over an enrolled install (old APK -> new, same signing key): profiles, PIN, drafts, media, error log kept; stores created before the PIN-reset change move over at the next correct PIN without a rekey; phones that never unlock on the new version have no reset copy | P1 | policy/field-data-collection.md "Wrong PINs and PIN reset", 2d78e9660, handoff.md (in-place upgrade check, digitva-9l5c) |
| L15 | Old APK against the new server: changed coding gets a receipt, non-leaf gets 422 `non_leaf_category`, `attachments_pending` is already understood; old APK shows the WHO URI text for refusals. Run once with the previous release APK | P1 | handoff.md item 4, 2582c138e, 9a1df01ef |
| L16 | Form updated on the server mid-draft: an enrolled draft stays on the version it started on (cached until uploaded); new interviews use the new version; an app whose engine cannot run the served definition blocks new interviews with "update the app" but never blocks uploads; a draft with no pin moves to the current form with a visible notice (answers to dropped questions kept in `_other`, not submitted) | P1 | policy/field-data-collection.md "Form version" (digitva-xuf9, digitva-oxvt) |
| L17 | Standalone draft after an app update changed the questionnaire version: opens read-only (answers listed, no edit, no complete) with a message; an unchanged version stays editable | P2 | policy/field-data-collection.md "Definition pin", 2d78e9660 |
| L18 | Phone clock 5 minutes to 4 hours off: persistent warning with a button to Date & time; more than 4 hours off: no new registration or interview and no editing of drafts until fixed and re-checked (typed text saved first); view, Send now/Refresh, Settings, Export errors still work; uploads kept with `device_clock_suspect`, never refused; a never-synced phone is not judged | P1 | policy/field-data-collection.md "Phone clock" (digitva-ltqg) |
| L19 | Time zone change: phone local time is used for timestamps; project time only for "today" validation and gates; dates of death are plain dates, not shifted | P2 | S/ui/interviewRows.ts:150-160, S/collectionGate.ts:90-94 |
| L20 | Station signing key / device signing key rotation: station only | - | dropped (station out of scope) |
| L21 | Offline for days: refresh token lifetime keeps the session (30 days sliding, 90 max); after expiry "sign in again", unsent work waits | P2 | policy/field-data-collection.md (C1), src/auth.ts |
| L22 | Terms updated after enrolment: next call 403 `terms_required`, terms gate, work resumes after accept (see S09) | P2 | current-state/device-collection-api.md |
| L23 | Phone stores the access summary offline: with no connection the last known access and gate are used; a gate answer older than 15 minutes does not refuse a new start | P2 | b8732d608, edf8b1375 |

## 17. Failures in the middle of a sync
Expected for all: nothing lost, nothing duplicated (server idempotent on `client_draft_id`, `client_death_id`, `client_attempt_id` and the attachment id), the item shows as unsent with its Ref line, the next sync completes. Run with the interview + media draft, then compare server rows and Drafts / To do counts.

| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| N01 | Network drops during the interview POST -> stays unsent; next sync sends it; server has one submission | P1 | policy/field-data-collection.md "Idempotent upload", current-state/device-collection-api.md |
| N02 | Server stored the interview but the phone never got the 2xx (drop after send, or kill) -> retry returns the first result (`kept`/`superseded`), no second submission; phone then deletes its copy only on that 2xx | P1 | policy/field-data-collection.md, current-state/device-collection-api.md line 675 |
| N03 | Same for a registration (`client_death_id`) and a contact attempt / visit (`client_attempt_id`) | P1 | current-state/device-collection-api.md (422 invalid_attempt, client_attempt_id) |
| N04 | Drop mid-file during attachment PUT -> file stays unconfirmed and the whole file is sent again next Send (no resume: one PUT per file); the interview is never submitted until every file is confirmed; a truncated transfer fails `checksum_mismatch` (X-Content-SHA256) and is retried | P1 | policy/phone-attachments.md section 4, digitva-jkvl (chunked upload not built) |
| N05 | Drop after the server stored a file but before the phone marked it uploaded -> re-PUT with the same id is idempotent, no second file | P1 | policy/phone-attachments.md ("the id makes a retry idempotent") |
| N06 | Some of several files uploaded, then failure -> confirmed files are skipped on retry; interview still not sent | P1 | policy/phone-attachments.md |
| N07 | Batch of queued items, one fails: the pass continues with the others; revisions rethrow only session-revoked, sign-in-needed and 403 | P1 | S/sync.ts:444-533,537-803 |
| N08 | Error classes on upload: timeout, connection refused / offline, 5xx, 429 -> keep and retry on next Send; 400 `checksum_mismatch` / `invalid_request`, 413 without `payload_too_large` -> retry; 413 `payload_too_large`, 415, 422, other 400 -> file held as needing attention with Ref line (replace or delete by reopening); 422 `attachment_limit` -> interview held with the reason, next Send tries again; 404/409 on the attachment draft -> held, interview not sent | P1 | policy/phone-attachments.md section 4 |
| N09 | Error classes on interview: 409 -> held, not retried by Send now, never deleted ("Send again"); 422 -> reopened in progress with "Not accepted" and Go rows; 403 `terms_required` -> terms gate; 401 `session_revoked` / `session_ended` -> S06 / S08 | P1 | policy/expo-client.md "Refused uploads", src/auth.ts header |
| N10 | Flaky network (airplane mode on and off several times during send) -> no duplicates, no lost file, final state sent once | P1 | same as N01-N06 |
| N11 | App killed mid-sync -> on relaunch the interview is unsent or sent, never half-deleted; the upload lease means a send already begun wins over a Reopen; retry is idempotent | P1 | policy/expo-client.md "Reopening a ready interview" (upload lease), 2d78e9660 |
| N12 | Phone locked or screen off mid-sync -> store stays unlocked 60 s after backgrounding, so a send started then finishes; anything left waits for the next sync after unlock | P1 | 40ee1a528 |
| N13 | Wi-Fi to mobile data mid-sync: no connection-type handling; treated as a network error, retry completes | P2 | S/network.ts:58-59 |
| N14 | Server restart or maintenance page (503 HTML): treated as `redirected_response`, kept and retried, nothing deleted; expected the friendly serverUnavailable message (today "Something went wrong. Try again." + Ref, friendly only for JSON `maintenance`) | P1 | S/api.ts:1001-1006, S/ui.tsx:865-893; BUG digitva-ticr: HTML 503 not shown as server unavailable |
| N15 | Non-JSON 200 (captive portal) on a sync call -> `malformed_response`, not counted as sent | P1 | 273a4f2e4, src/api.ts |
| N16 | Network drops mid-download of cases or forms: the partial download is discarded and the stored copy kept; next sync downloads again in full | P1 | owner 2026-11-12; S/sync.ts:979-1043 (cases) |
| N17 | Drop during the access refresh -> sync sends unsent rows first (before the refresh), then retries the refresh; a refresh failure by offline or 5xx keeps everything | P1 | policy/field-data-collection.md line 130, src/auth.ts header |
| N18 | Drop during a coding upload (offline coding result) -> kept; resend is a recode-safe replace, not a duplicate (server keeps older code in history) | P1 | digitva-9cll.14 |
| N19 | Drop during a backup or restore -> restore is one transaction, nothing half-restored; a failed backup leaves existing files | P2 | policy/field-data-collection.md "Encrypted backup", 7e7007766 |
| N20 | Resumable or chunked media upload: not built; no scenario beyond N04 | - | digitva-jkvl |

## 18. Form layers, NQA and Social Autopsy (enabled / disabled)
Definition found (not stated as a glossary entry; OPEN Q1): "The WHO base is a subset; everything else is a layer on top. A project records which layers it collects" (`enabled_extensions`; "A project picks layers; it does not pick a whole form") - `policy/va-form-project-configuration.md` section 1. Layers: `digitva_core` and `doris_support_whova_2022` (always on), `social_autopsy`, `narration_language`, `death_summary`, `medical_records`, `equity`, `intake_screen` and `geography` (no questions, server/client context), `abha` (web intake only). The registry says layers may be "project-enabled or host supplied" (`policy/digitva-who-form-overrides.md`). "Layer" is also used for the 4-layer access model (`policy/auth-decorator-rbac.md`), which is a different meaning.

| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| LY01 | Layer ON vs OFF for each question layer (`social_autopsy`, `narration_language`, `death_summary`, `medical_records`, `equity`): ON -> the served form carries its questions (e.g. death summary `ds_available`..`ds_im5`, medical records `md_im1..30`, narration `narr_language` + `imagenarr`); OFF -> absent in the form and in the submitted answers; core and DORIS-support layers cannot be turned off | P1 | policy/va-form-project-configuration.md section 1, policy/digitva-who-form-overrides.md |
| LY02 | `abha` layer ON: ABHA number/address asked on the web intake only; the phone form does not show them | P2 | policy/va-form-project-configuration.md (`abha`, "web intake only") |
| LY03 | `intake_screen` ON: welcome card from the project's intake note on web; `geography` ON: survey state/district/block and site id filled by the server from the death register and unit (not asked on the phone) | P2 | policy/va-form-project-configuration.md |
| LY04 | Toggle a question layer on the server while an enrolled draft is open: the draft stays on the form version/pin it started with and uploads; new interviews use the new definition after the next sync; answers for a question the new form no longer asks (only for an unpinned older draft) stay in `_other` and are not submitted | P1 | policy/field-data-collection.md "Form version" (digitva-xuf9, digitva-oxvt) |
| LY05 | Toggle `equity` OFF/ON: `residence_type` disappears/appears after Id10055; older drafts stay valid; when ON the equity questions are asked after consent, and under a refusal only two equity fields are recorded | P2 | policy/digitva-who-form-overrides.md |
| LY06 | Layer toggle never makes the server refuse an upload for form version; it flags `FormVersion` != current for QA | P1 | policy/field-data-collection.md "Form version" |
| LY07 | Standalone phone: layers cannot be changed on a server; the bundled questionnaire (with medical-record and death-summary photo questions for new interviews) is used, drafts keep their saved question set | P2 | 1b2f37d4b, policy/field-data-collection.md Path C |
| LY08 | "Layers" means form layers only (enabled_extensions), not app variants or coding tools | P2 | owner 2026-11-12; policy/va-form-project-configuration.md s1 |
| LY09 | Combination matrix on one project: (social_autopsy layer on/off) x (narration_language on/off) x (medical_records on/off) x (death_summary on/off): the form shows exactly the enabled sections, interview completes and sends, coder workspace shows matching categories; run the two extremes (all on, all off) every time. SA coding/reviewing switches are separate (PS32-PS42) | P2 | policy/va-form-project-configuration.md |
| PS25 | NQA ON (`narrative_qa_enabled`, default OFF): coder's final-assessment form does not open until the coder's NQA for the current payload is saved; notice with a link to Narration / Documents; final-COD save is also blocked server-side; reviewers are not required to save NQA | P1 | policy/narrative-quality-assessment.md "Workflow Rules", app/models/va_project_master.py |
| PS26 | NQA OFF: no NQA step, final assessment opens straight away; nothing about NQA sent | P1 | same |
| PS27 | NQA ON, payload changes (upstream edit or interviewer revision): old NQA deactivated on Accept and Recode, rebound on Keep Current; the coder must save NQA again for the new payload; recode timeout keeps NQA, first-pass timeout deactivates it | P1 | policy/narrative-quality-assessment.md, policy/coding-allocation-timeouts.md |
| PS28 | NQA switched ON while a coder has a half-coded case: saved Step 1 is kept; the final save is refused 422 `final_blocked` with the NQA message until NQA is saved | P1 | app/services/coder_cod_service.py:843-846 |
| PS29 | NQA switched OFF: saved NQA rows are kept (no code deletes them); display follows the flag; coding no longer requires it | P2 | policy/narrative-quality-assessment.md; no delete in code |
| PS30 | NQA and SA on Collect Plus offline coding: the phone asks neither NQA nor SA; the server import does not require them | P1 | app/services/offline_coding_import_service.py:695-698 |
| PS31 | NQA online in Collect Code tab (reuses web screens): same required-before-final rule as web | P2 | d024b5ad0, policy/narrative-quality-assessment.md |
| PS32 | Social Autopsy is three independent switches: (a) collection = `social_autopsy` layer in `enabled_extensions` (SA questions in the interview), (b) coding = `social_autopsy_enabled` (default ON, coder's analysis form), (c) reviewing = `reviewer_social_autopsy_enabled` (default ON, reviewer's analysis form). Matrix rows PS33-PS40 run the combinations; each also checks what is sent | P1 | policy/va-form-project-configuration.md section 1, policy/social-autopsy-analysis.md (owner 2026-11-12) |
| PS33 | All ON (a, b, c): interviewer sees and answers SA sections (`sa01`-`sa19`, `sa_tu13`-`sa_tu19`, `sas01`-`sas07`); coder sees the SA answers in the `social_autopsy` category and, after them, the SA analysis form (three delay levels); reviewer sees the analysis form; saves write an audit entry and are stored per payload version | P1 | policy/va-form-project-configuration.md, policy/social-autopsy-analysis.md |
| PS34 | All OFF: no SA questions in the form or `answers_json`; no `social_autopsy` category content and no analysis form for coder or reviewer; nothing about SA sent | P1 | same |
| PS35 | Collection OFF: SA coding and SA reviewing are off too, whatever their own flags say (owner 2026-11-12). Coder and reviewer see no SA category content and no analysis form; project settings refuse (or ignore) coding/reviewing SA ON while the `social_autopsy` layer is off | P1 | owner decision 2026-11-12; enforcement: digitva-sapb |
| PS36 | Collection ON + coding OFF: interviewer answers SA; coder sees the synced SA answers but not the analysis form ("when `social_autopsy_enabled = false` ... must not be shown"); coding is not blocked by SA | P1 | policy/social-autopsy-analysis.md |
| PS37 | Collection ON + coding OFF + reviewing ON (reviewing only): reviewer sees the analysis form although the coder did not; reviewer saves it | P1 | policy/social-autopsy-analysis.md (coder and reviewer flags are independent) |
| PS38 | Collection ON + coding ON + reviewing OFF: coder has the form, reviewer does not and review is not blocked | P2 | same |
| PS39 | SA analysis is required when enabled and present (owner: go by policy): with coding SA on and SA answers collected, the coder's final COD is refused (422 `final_blocked`, "Social Autopsy Analysis must be completed before submitting the final COD.") until the analysis is saved; same for the reviewer with reviewing SA on. Not required when SA is not collected or its switch is off. Phone offline coding asks for neither SA nor NQA | P1 | owner 2026-11-12; policy/social-autopsy-analysis.md "Completion Requirements"; app/services/coder_cod_service.py:698, 849; app/services/offline_coding_import_service.py:695 |
| PS40 | Toggle a switch mid-use (rare in practice, owner 2026-11-12): open drafts stay on their pinned form and send; a saved SA analysis is kept as history bound to its payload version; an open coder/reviewer screen just keeps working until reload (no crash, nothing lost) | P2 | owner 2026-11-12; policy/field-data-collection (pinned form) |
| PS41 | SA and recode: SA analysis persists across recode attempts when the payload is unchanged; deactivated on Accept and Recode after an upstream change, rebound on Keep Current; reviewer release keeps Step 1 | P2 | policy/coding-workflow-state-machine.md lines 979, 1051, 1053, policy/coding-allocation-timeouts.md |
| PS42 | SA on the phone: SA analysis follows the project for enrolled accounts; disabled in standalone mode (SA questions in the questionnaire can still follow the layer) | P2 | policy/doris-cod-workflow.md "Offline coding workspace" (digitva-9cll.22.4) |

## 19. Equity questions (`equity` layer) enabled / disabled
Equity questions (owner 2026-10-27, 2026-10-29): `residence_type`, `social_group`, `vulnerable_group`, `health_coverage` (country choice sets) plus the refusal profile `refusal_age_group` / `refusal_sex`. New projects default ON (`web_intake_equity_enabled`).

| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| EQ01 | Equity ON, consent given: the four questions are asked in the additional-demographic block (social_group after Id10053, residence_type after Id10055, vulnerable_group then health_coverage after Id10066), whether or not WHO's `Id10051` gate is yes | P1 | policy/digitva-who-form-overrides.md "Equity extension: placement and gate", digitva-7amd.26 |
| EQ02 | Equity OFF: none of the four appear in the form, the draft or the submitted answers; WHO's own questions unchanged | P1 | policy/va-form-project-configuration.md, policy/digitva-who-form-overrides.md |
| EQ03 | Every equity question is optional, with "Don't know" and "Prefer not to say", no free text; an interview completes with them blank; older drafts and revisions stay valid after ON | P1 | policy/digitva-who-form-overrides.md "usual equity rules" |
| EQ04 | Age and sex filters (neonatal / child / adult, sex Id10019) hide questions that do not apply; choice labels follow the project's country; English and Hindi labels shown (rural / urban / urban slum or informal settlement) | P2 | policy/digitva-who-form-overrides.md |
| EQ05 | Equity toggled mid-draft: a pinned draft keeps the equity questions and its saved answers are submitted | P1 | app/services/web_intake_service.py:2113-2119,3720-3731 |
| EQ06 | Sent and accepted: equity answers ride in `answers_json` with the interview and the server accepts a blank; `residence_type` feeds reports, falling back to the unit's area type when blank or `dk` | P2 | policy/digitva-who-form-overrides.md |
| EQ07 | Refusal profile: on WHO consent No or respondent data protection refusal, only `refusal_age_group` and `refusal_sex` are recorded (prefilled from the register when registered; "unknown" allowed, nothing required); no name, identifier, clinical answer, note, attachment or coding | P1 | policy/digitva-who-form-overrides.md "refusal profile", policy/respondent-consent-notice-draft.md "Refusal boundary" |
| EQ08 | Equity answers are not personal data except caste/ethnicity, which is PII: exports with names omitted also omit caste/ethnicity; other equity answers export normally | P1 | owner 2026-11-12; BUG digitva-vii1 (not omitted today, data_management_service.py:1179) |
| EQ09 | Reports: equity panels EQ-01 (female share vs peers) and EQ-02 (female-male final cause gap) are aggregate only; cells under 5 shown `<5`; units under 20 cases show a count without share | P2 | policy/kpis.md EQ-01, EQ-02, policy/digitva-who-form-overrides.md |
| EQ10 | Standalone bundled form defaults to medical_records and death_summary; equity is not yet in it | P2 | S/standalone/config.ts:11-14 |

## 20. Respondent consent under DPDP (data protection) vs interview consent
Not the same as WHO `Id10013` (interview consent): the DPDP flow is the respondent's agreement to named purposes against a versioned notice, recorded per case; `Id10013` is the WHO form question. "The two decisions are independent: a data protection refusal does not invent a WHO answer" (policy/respondent-consent-notice-draft.md "Refusal boundary"). Both refusals stop collection in every mode.

| ID | Scenario and expected result | Pri | Source |
| --- | --- | --- | --- |
| CN01 | Project "Require respondent consent" ON: notice shown before informant fields at registration and before an interview that has no decision on file (direct start or registration without one); OFF: no consent screen on the web. On the phone informant details always need a granted consent against a served notice, whatever the switch says | P1 | policy/web-intake.md "Respondent consent (DPDP)", policy/respondent-consent-notice-draft.md "Web flow", "Phone flow" |
| CN02 | Notice shown in the app language (switchable English / Hindi), one toggle per purpose (required: record and interview, contact, cause-of-death coding, statistics; optional: messages, research sharing, narrative automated processing), mode (spoken, tap, signed), witness present yes/no | P1 | policy/respondent-consent-notice-draft.md (purposes table), "Phone flow" |
| CN03 | Accept ("Respondent agrees" needs every required purpose on): informant fields open; decision stored on the phone (id, notice version, language, SHA-256, purposes, mode, witness, time, user) and sent as `consent` with the registration or the interview | P1 | policy/respondent-consent-notice-draft.md "Phone flow" |
| CN04 | Decline ("Respondent refuses"): informant fields stay closed and empty; covered fields (informant register fields, `Id10007`, `Id10055`, `Id10057`, `Id10061`, `Id10062`) locked empty and removed from what is sent, the stored draft and sync; only the broad refusal profile, WHO decision if supplied and consent/audit metadata kept; registration and interview continue | P1 | policy/respondent-consent-notice-draft.md "Phone flow" "Refusal", "Refusal boundary", digitva-wy90 |
| CN05 | Server gate: 422 `consent_required` (covered data without a granted consent) reopens the consent screen for that item; `consent_conflict` (covered data under a refusal); `consent_invalid` (unknown version, hash, language, purposes, mode); phone shows the server message and never retries unchanged; the interview's own decision is dropped, a registration-inherited decision stays and the form asks for an interview-level decision | P1 | policy/respondent-consent-notice-draft.md "What the server checks", "A refused inherited decision" |
| CN06 | Change decision during an interview via the consent chip ("Consent: agreed / refused / not recorded") or "Change consent decision": Agreed to refused strips covered answers and files exactly like a first refusal; refused to agreed reopens them empty; only the new record is sent; server keeps the newest | P1 | policy/respondent-consent-notice-draft.md "Changing a decision during an interview" (digitva-wy90) |
| CN07 | Later agreement: a refused case is not final; any team interviewer may restart it after taking a fresh consent; other interviewers' open drafts cleared to refusal-only and paused until they resume after a fresh grant; prefill rebuilt from current sources, nothing from before the refusal returns | P1 | policy/respondent-consent-notice-draft.md "Refusal boundary", 0ace5b17e (digitva-lgzl) |
| CN08 | Withdrawal of DPDP consent is web only (supervisor or data manager); not on the phone | P2 | policy/offline-api-contract.md:54,236,386, app/routes/api/intake_consent.py:49 |
| CN09 | Server records consent append-only with notice version id, language, SHA-256, decision (`granted` / `refused` / `withdrawn`), every purpose's choice, mode, witness, recorded time and recording user, channel (`device`) | P1 | policy/offline-bundle-and-transfer.md consent record fields, policy/respondent-consent-notice-draft.md "What is recorded" |
| CN10 | DPDP consent is not asked again when the notice version changes; the stored decision keeps the notice_version_id it was taken under; new interviews use the active notice | P2 | owner 2026-11-12; S/consentStore.ts:77-158 |
| CN11 | Offline: consent screen works from the cached config (`GET /intake/consent-config`, every language, purposes, covered fields); a failed fetch keeps the old copy; consent decided offline is stored with the interview/registration and sent with it on sync | P1 | policy/respondent-consent-notice-draft.md "Cached settings", "Phone flow" |
| CN12 | Notice whose `text_sha256` does not match, or an unknown `refusal_behaviour`, or no notice: no usable notice, no fallback text; informant fields stay closed with the reason shown | P1 | policy/respondent-consent-notice-draft.md "Cached settings" |
| CN13 | Consent restored with a backup: consent meta rows restored with the drafts, so the restored interview sends (otherwise `consent_required`) | P1 | ffa623a2e |
| CN14 | Cancelled consent No never saved (see I02/I03); Confirm wipes after the dialog asks once | P1 | a3e383895, efb539594 |
| CN15 | Standalone: bundled notice in English and Hindi, editable only in Settings (stored locally, never sent, not applied to enrolled or Demo); each decision records the exact rendered text, language, hash and hash-derived notice id; server push validates hash, bundled notice identity, language and purposes | P2 | policy/standalone-consent-notice-settings.md, policy/field-data-collection.md line 802 |
| CN16 | Interview consent (`Id10013`) vs respondent data-protection consent: `Id10013` = no stores a server-set `refused`; DPDP refusal does not set `Id10013`; the two can differ and each stops collection; an `interview_outcome` of refused with `Id10013` = yes is refused | P1 | policy/respondent-consent-notice-draft.md "Refusal boundary", policy/web-intake.md (outcome that contradicts consent) |
| CN17 | Narrative automated processing purpose (`narrative_automated_processing`, optional unless the project says required): declined -> the narrative is not sent to the PII/QA/translation pipeline; withdrawal stops processing and deletes that case's derived data | P2 | policy/respondent-consent-notice-draft.md (digitva-sxg9), policy/narrative-ai-processing.md |
| CN18 | Consent state in the interview top bar: chip shows "Consent: agreed / refused / not recorded" (text and accessibility label, not colour alone); absent when the project does not require consent | P2 | policy/respondent-consent-notice-draft.md "Changing a decision" |
| CN19 | The Hindi consent notice is signed off by the admin before field use (notice version activated by admin) | P2 | owner 2026-11-12 |

## Dropped (feature does not exist, or contradicts policy)
- SV03/SV04 (reassign cases): "A supervisor never assigns" (policy/web-intake.md "Supervisors").
- SV05 (supervisor approve): supervisors confirm or reject flags, reopen, choose between interviews; no approve step.
- SV13 (flag missing contact details): no such flag.
- Old SV02 per-interviewer counts: only the four tiles exist.
- Old C28/C29 (second independent coder, adjudication): one coder per case; reviewer samples.
- Desktop station scenarios (K09): owner says ignore.
- L12, L20 (device compromised, signing-key rotation): station-only; no phone behaviour.
- PS23 (two-coder requirement): no such setting.
- Old K04 (Change PIN in Settings): no such screen; PIN only changes through reset.
- Old E04 (interview PDF share): no such feature.
- Old U03 expectation "profile removed": sign-out keeps the profile.
- Old D03 "logs sent later": the error log is never uploaded.
- Old I04 "fresh case only", C11 "source suggestion", C12 "suggestion kept for audit": not in policy.

## Notes
- OPEN Q1 (layers): the only definition found is form layers (extensions) in policy/va-form-project-configuration.md; see section 18 and LY08. Confirm whether the owner also means product variants (plain Collect, Plus, standalone, demo, web) or coding tools (DORIS, CODEEDIT, SmartVA, engine).
- Emulator camera and microphone are virtual; on the Samsung media is real.
  If a capture cannot be driven, the flow reports it rather than skipping.
- I04, S06, S05 and U03 change server or phone state: run them on the fresh e2e
  users only.
- PINs and passwords come from `private/e2e-users.json` via `-e`, never in
  flow files.
- Old APKs show "The selected code does not match its WHO URI." for the
  non-leaf refusal (same 422 `INVALID_SELECTION`); not tested in Maestro.
