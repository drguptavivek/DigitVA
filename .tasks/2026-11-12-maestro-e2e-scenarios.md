# Maestro end-to-end scenarios (digitva-xjpk)

Owner 2026-11-12. Collect Plus debug build, dev server, run locally on the
emulator and the Samsung (never CI). Every run: `flask seed e2e-users create`
-> enrol -> flows -> `flask seed e2e-users teardown` (always, even on failure).

Each scenario asserts the Drafts and To do counts on Home before and after, and
that answers, images and audio are unchanged. P1 = data-loss risk, run every time.

## 0. Setup and identity
| ID | Scenario | Pri |
| --- | --- | --- |
| S01 | Sign in with email + password, set PIN, land on Home with the right project | P1 |
| S02 | Sign in with a sign-in code | P2 |
| S03 | Wrong PIN several times -> lockout message; correct PIN after wait works | P2 |
| S04 | (see K01-K07) | - |
| S05 | Phone limit reached -> clear message; after revoke, sign in works | P2 |
| S06 | Device revoked on server while signed in -> next sync refuses cleanly, local unsent work kept and explained | P1 |
| S07 | Language switch English <-> Hindi on Home, inside a form, and back; answers unchanged | P2 |

## 1. Register a death (death reporter)
| ID | Scenario | Pri |
| --- | --- | --- |
| R01 | Register a death with all required fields -> appears in My registered deaths | P1 |
| R02 | Missing required field -> refused with the field named | P2 |
| R03 | Register offline -> queued -> sync online -> server has it once (no duplicate) | P1 |
| R04 | Leave registration half done, Home, return -> fields kept | P1 |

## 2. Interview (interviewer)
| ID | Scenario | Pri |
| --- | --- | --- |
| I01 | Start from To do, consent Yes, complete, send -> server receives, To do -1 | P1 |
| I02 | Consent No -> confirm dialog -> Cancel -> Yes restored, other answers kept | P1 |
| I03 | Consent No -> Cancel twice, leave, reopen draft -> consent Yes, answers kept | P1 |
| I04 | Consent No -> Confirm -> refusal recorded and sent (fresh case only) | P1 |
| I05 | Change an answer that hides later questions, change it back -> later answers handled as the form defines, no crash | P2 |
| I06 | Validation error on a field -> message shown; fix -> can continue | P2 |
| I07 | Save draft, leave, reopen from Drafts -> same page and answers | P1 |
| I08 | Case started by another interviewer -> "As of the last sync (...)" message shown, can still proceed per policy | P2 |
| I09 | Fill and send fully offline -> queued -> online sync sends once | P1 |
| I10 | Send fails mid-way (network off during send) -> stays unsent, retry sends once | P1 |

## 3. Media (image, audio, other attachments)
| ID | Scenario | Pri |
| --- | --- | --- |
| M01 | Attach image (camera) -> thumbnail shown | P1 |
| M02 | Attach image from gallery/file | P2 |
| M03 | Record audio -> playable | P1 |
| M04 | Replace image / audio -> only the new one kept | P2 |
| M05 | Remove image / audio -> gone, rest of draft kept | P2 |
| M06 | Media survives Home + return, app kill + relaunch, lock + unlock, profile switch + back, reopen draft | P1 |
| M07 | Send with media -> server has every file, correct sizes | P1 |
| M08 | Media attached offline -> sent later | P1 |

## 4. Stop and resume (on a draft with answers + media)
| ID | Scenario | Pri |
| --- | --- | --- |
| P01 | Home, wait, return | P1 |
| P02 | Force-stop / swipe away, relaunch, unlock | P1 |
| P03 | Lock now, unlock with PIN | P1 |
| P04 | Auto-lock after inactivity, unlock | P2 |
| P05 | Rotate screen mid-form | P2 |
| P06 | Incoming interruption (another app on top) mid-form | P2 |

## 5. Profiles
| ID | Scenario | Pri |
| --- | --- | --- |
| U01 | Add a second profile on the same phone | P1 |
| U02 | Switch A -> B -> A: each sees only its own drafts, nothing lost | P1 |
| U03 | Sign out with nothing unsent -> profile removed, sign back in works | P1 |
| U04 | Sign out with unsent work -> warned, Cancel keeps everything | P1 |

## 6. Coding (coder)
| ID | Scenario | Pri |
| --- | --- | --- |
| C01 | ICD-11 code online: search, pick leaf, save -> server has it | P1 |
| C02 | Non-leaf (e.g. BA41) -> "<CODE> is a category, not a final code. Choose a more specific code under it." + child list -> pick BA41.Z -> accepted | P1 |
| C03 | C02 offline (airplane mode) -> same refusal and child list | P1 |
| C04 | ICD-10 project coding online (tk7j) | P1 |
| C05 | Code offline -> sent when online; DORIS unanswered -> saved code still sent | P1 |
| C06 | Stale coding -> sent marked stale; recode replaces it, history kept | P1 |
| C07 | Recode after the server received a code -> replaces it with history | P2 |
| C08 | Coding rejected/incomplete -> interview data still sent | P1 |
| C09 | Case list: coder sees only cases of forms/sites they are granted; another site's case not listed | P1 |
| C10 | Open a case: narrative, key answers and attachments readable before coding | P2 |
| C11 | DORIS suggestion shown -> accept as is -> saved with source "suggestion" | P1 |
| C12 | DORIS suggestion -> override with own code -> own code saved, suggestion kept for audit | P1 |
| C13 | DORIS unavailable/slow -> coder can code manually; no hang | P1 |
| C14 | CODEEDIT check: edit a code the check flags -> warning shown, coder can still save (suggestion only) | P1 |
| C15 | Full cause chain: immediate, antecedent(s), underlying, contributing, with intervals -> all saved in order | P1 |
| C16 | Remove or reorder a cause line before saving -> saved chain matches the screen | P2 |
| C17 | Same code entered twice in the chain -> handled per policy (warn or refuse), message clear | P2 |
| C18 | Sex- or age-incompatible code (e.g. maternal code for a male) -> warned/refused per policy | P1 |
| C19 | Ill-defined / "unknown cause" code -> allowed with the right flag | P2 |
| C20 | Search by English text, by Hindi text, by code prefix -> results; empty search -> clear "no results" | P2 |
| C21 | Search offline uses the offline index; same leaf results as online for a sample | P1 |
| C22 | Manner of death / place / other coding fields required by the form -> missing one refused with field named | P2 |
| C23 | Half-coded case: leave, Home, kill app, reopen -> coding draft restored exactly | P1 |
| C24 | Lock / profile switch mid-coding -> coding draft restored | P1 |
| C25 | Save code, then edit before sync -> only the edited version sent | P1 |
| C26 | "Cannot code" / insufficient information -> reason required, sent; case returns per policy | P2 |
| C27 | Coding assigned to another coder -> this coder sees it read-only or not listed, per policy | P2 |
| C28 | Second (independent) coding where the project requires two coders -> both saved, disagreement goes to review | P1 |
| C29 | Reviewer adjudicates a disagreement -> final code set, both codings in history | P2 |
| C30 | Coding on web (Select2) for an ICD-11 project -> non-leaf refused on save, leaf accepted (server check) | P2 |

## 7. Review (reviewer / supervisor)
| ID | Scenario | Pri |
| --- | --- | --- |
| V01 | Open review list, open a case, approve | P2 |
| V02 | Return a case with a note -> interviewer sees it | P2 |

## 7b. Interview supervisor (PHC MO)
| ID | Scenario | Pri |
| --- | --- | --- |
| SV01 | Supervisor sees only the sub-centres under their PHC; another PHC's cases not listed | P1 |
| SV02 | Team progress: per-interviewer counts (to do, drafts, sent) match what the interviewers' phones show after sync | P2 |
| SV03 | Assign / reassign a case from interviewer A to B -> B gets it after sync; A's unsent draft for it kept and explained, not deleted | P1 |
| SV04 | Reassign while A is mid-interview offline -> A's work reaches the server on next sync, duplicate visible to supervisor | P1 |
| SV05 | Review a sent interview -> approve -> status updates on server and on the interviewer's phone | P2 |
| SV06 | Return an interview with a note -> interviewer sees the note, edits, resends; history keeps both versions | P1 |
| SV07 | Return while the interviewer has a newer local draft -> local draft not overwritten | P1 |
| SV08 | Supervisor sees a refused-consent (No) interview with its reason; cannot edit answers | P2 |
| SV09 | Overdue / follow-up list: deaths past the follow-up window are flagged | P2 |
| SV10 | Supervisor cannot code (no coder role) and cannot see coder-only screens | P1 |
| SV11 | Supervisor also holding interviewer role (test.all) -> both work lists, actions go to the right role | P2 |
| SV12 | Supervisor offline: lists show last-sync data with the sync time; actions queue and send once | P1 |
| SV13 | Death reporter's registration with missing contact details -> supervisor sees it flagged | P2 |

## 8. Sync
| ID | Scenario | Pri |
| --- | --- | --- |
| Y01 | Manual sync with nothing to send -> "Nothing to send", time updated | P2 |
| Y02 | Sync with several queued items -> all sent once, counts update | P1 |
| Y03 | Server down during sync -> clear error, nothing lost, later sync succeeds | P1 |

## 9. Hand-offs and concurrency (two users / two phones)
Runs with two e2e users on the emulator and the Samsung at once.

| ID | Scenario | Pri |
| --- | --- | --- |
| H01 | Reporter A registers a death -> interviewer B syncs -> case in B's To do | P1 |
| H02 | Interviewer A starts the interview, sends nothing; B opens the same case -> B sees "As of the last sync (...), A started this interview" | P1 |
| H03 | A starts, stops part-way; B resumes the same case -> both drafts reach the server, neither discarded, duplicate flagged for review | P1 |
| H04 | A starts, B starts on the other phone, both send -> server keeps both, marks the duplicate; no orphaned data | P1 |
| H05 | A's interview already complete on server; B opens the case -> "already complete" notice, B's draft not lost if started | P1 |
| H06 | Same user on two phones resumes the same draft -> last send does not silently overwrite the other | P1 |
| H07 | Two coders code the same case: second sees the first's code after sync; both codes kept with history, final per policy | P1 |
| H08 | Two coders code the same case offline at once, both sync -> both reach the server, conflict visible, nothing dropped | P1 |
| H09 | Stale coding: coder codes offline, interview data changes on server, coder syncs -> code sent marked stale; recode replaces it, history kept | P1 |
| H10 | Stale coding on a case another coder already finalised -> stale code kept in history, does not replace the final | P1 |
| H11 | Recode after server received a code -> replaces it, history shows both | P1 |
| H12 | Coder codes while reviewer returns the case -> coder's work kept, return note visible | P2 |
| H13 | Interviewer edits/resends after coding started -> coding marked stale on the coder's phone after sync | P1 |
| H14 | Device of A revoked while A has unsent work, B continues the case -> A's unsent work explained and kept locally, B unaffected | P1 |

## 10. PIN, password and account recovery
| ID | Scenario | Pri |
| --- | --- | --- |
| K01 | Forgot PIN on the lock screen -> sign in with password -> set new PIN -> drafts, media and unsent work still there | P1 |
| K02 | Forgot PIN offline -> clear message that a connection is needed; nothing wiped | P1 |
| K03 | Forgot password on sign-in -> reset flow reaches the server (dev mail catcher), new password signs in | P2 |
| K04 | Change PIN from Settings -> old PIN refused, new PIN works | P2 |
| K05 | PIN lockout after repeated wrong PINs -> wait/recovery path; data kept | P1 |
| K06 | Forgot PIN on profile B while profile A has unsent work -> A untouched | P1 |
| K07 | Password changed on the server -> phone keeps working on PIN until next sign-in; then new password needed; local work kept | P2 |

## 11. Exports and sharing
| ID | Scenario | Pri |
| --- | --- | --- |
| E01 | Export unsent work / backup from the phone (if offered) -> file produced, contains every unsent item with media, no PIN or token inside | P1 |
| E02 | Export while offline works | P1 |
| E03 | Restore/import the export on a fresh install or another profile -> items restored, not duplicated on send | P1 |
| E04 | Share/print the interview PDF (पी.डी.एफ. (PDF) in Hindi) -> opens, right content, language matches | P2 |
| E05 | Export refused or warned for another profile's data | P1 |
| E06 | Server-side exports after the run (web, data manager): SmartVA input CSV (apostrophes), raw SmartVA offline CSV (no apostrophes, no BOM), interview export -> include the e2e cases | P2 |

## 12. Debug logs and diagnostics
| ID | Scenario | Pri |
| --- | --- | --- |
| D01 | Open diagnostics / debug log screen from Settings or Help | P2 |
| D02 | Share/send debug logs -> file produced; contains no PIN, password, token, informant name, phone or address | P1 |
| D03 | Logs captured while offline are kept and sent later | P2 |
| D04 | After a deliberate failure (network off mid-send) the log shows the error with an error code, not the payload | P2 |
| D05 | Debug build banner shown; release-only screens absent | P2 |

## Notes
- Emulator camera and microphone are virtual; on the Samsung media is real.
  If a capture cannot be driven, the flow reports it rather than skipping.
- I04, S06 and U03 change server or phone state: run them on the fresh e2e
  users only.
- PINs and passwords come from `private/e2e-users.json` via `-e`, never in
  flow files.
