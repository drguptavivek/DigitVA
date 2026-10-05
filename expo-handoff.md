# Expo handoff: field collection integrity

For the Expo session (owns `mobile/` and `vendor/`). The backend session
builds the server half of each bead and records the exact contract here.
Policy: `docs/policy/field-data-collection.md`, `docs/policy/web-intake.md`
("Parallel interviews"), `docs/policy/interview-revisions.md`. Each section
names its bead; the app half is its child bead (e.g. `digitva-2bxa.1`); the server bead stays open until its app half lands. The backend session
rewrites this file as beads land; the Expo session closes the app beads. Section 10 (self-coding) added 2026-10-05.

## 1. Answers hash on upload (`digitva-2bxa`, server built)

Frontend implemented (`digitva-2bxa.1`): exact JSON/hash upload, matching
acknowledgement and snapshot purge, persistent conflict handling, one hash
retry, immediate superseded notices, request deadlines and atomic case refresh.
Verified with section 2: 271 tests, TypeScript, web/Android JS exports and
independent code-quality audit passed. Physical-device acceptance is separate.
Frontend commit `bcdd4983` is pushed; both app child beads are closed.

The server refuses the old request shape, so ship this with the next build.

`POST /api/v1/intake/submissions`, request adds:

- `answers_json`: string, the exact JSON text of the answers object. Build it
  once with `JSON.stringify(data)` and keep that string; never re-serialise.
- `answers_sha256`: SHA-256 hex of the UTF-8 bytes of `answers_json`
  (`expo-crypto` `digestStringAsync(SHA256, answers_json)`).
- `draft` is still sent, for its meta keys only; `draft.data` is no longer read.

Responses:

| Status | When | Body |
| --- | --- | --- |
| 201 | first upload | result |
| 200 | resend, same `client_draft_id`, same hash | result |
| 409 `hash_mismatch` | gone: see section 8 (a resend with other answers is a 200 with `kept`) | |
| 409 `conflict` | another interviewer's `client_draft_id` | `{error, code}` |
| 422 `answers_hash_required` | `answers_json`/`answers_sha256` missing or malformed | `{error, code}` |
| 422 `answers_hash_invalid` | hash does not match the text received | `{error, code}` |
| 422 `invalid_interview` | text over 1 MB, not a JSON object, too deep | `{error, code}` |

Result: `{va_sid, case: {death_id, unique_id, status}, outcome, superseded, answers_sha256}`.
The echoed `answers_sha256` is lower-case hex.

App must:

1. (Section 8: compare `received_sha256`, not `answers_sha256`, on an upload.)
   Delete the local copy only when the reply's `answers_sha256` equals the
   hash it sent (compare lower-case) and `case.death_id` matches.
2. (Superseded by section 8: there is no `hash_mismatch` now.) On 409 `hash_mismatch`: stop retrying that draft, keep it, and tell the
   interviewer "This interview was already uploaded; your later edits were not
   applied." Show `stored.case.unique_id`. (The revise action arrives with
   `digitva-bhpl`; until then just keep the copy.) Today `sync.ts` retries
   every 409; handle by `code`.
3. On 422 `answers_hash_invalid`: retry once with a freshly computed hash of
   the same stored string; if it repeats, mark the draft needs attention.
4. Show `superseded: true` to the interviewer ("a teammate's interview of this
   case was submitted first; yours is kept").
5. Every request gets a timeout (suggest 30 s, uploads 120 s), so a dead
   connection fails the run with everything kept instead of hanging.
6. Write the downloaded case list in one SQLite transaction, so a kill
   mid-write leaves the old list.

## 2. Interview times and clock skew (`digitva-latk`, server built)

Frontend implemented (`digitva-latk.1`): local-offset start/completion times
survive autosave; each HTTP upload attempt, including an authentication retry,
gets a fresh device clock reading. Unknown legacy completion times are omitted.
Verified with section 1 as recorded above.

`POST /api/v1/intake/submissions`, in the `draft` envelope (each optional,
each ISO 8601 with a UTC offset, e.g. `2026-10-01T10:45:00+05:30` or `...Z`):

- `startedAt`: device time the interview was opened.
- `completedAt`: device time it was marked complete; marking it complete
  again updates it.
- `deviceClockAt`: device clock at the moment of the upload request (take it
  just before sending, not at completion).

Present but not a string, unparsable or without an offset (an explicit `null`
included): 422 `invalid_interview`, message names the field; nothing stored.
Leave a field out rather than sending `null`.

Server: payload `start`/`end` come from `startedAt`/`completedAt`;
`SubmissionDate` stays server receipt; `today()` in the server re-check is
`completedAt` read in its own offset (send the device's local offset, not
`Z`, so the date matches what the interviewer saw). Skew is stored as
`clockSkewSeconds` (server receipt minus `deviceClockAt`); it never alters the
times.

App must: record `completedAt` in `markCompleted` (`src/drafts.ts`), update it
on a repeat completion, record `startedAt` when a draft is created, and send
all three. Same rules apply to `POST /intake/drafts/sync` (section 3).

## 3. Parallel interviews, part A (`digitva-xz83`, server built)

Frontend implemented (`digitva-xz83.1`): native and browser case rows/details
show nonblocking warnings without interviewer identity; cached native warnings
state their last-sync freshness. Open in-progress cases can start with server
prefill. Browser superseded submissions return to collection with a notice.
Verified: 30 Jest suites, 287 tests, TypeScript, web and Android JS exports;
independent quality audit found no material issues. Physical-device acceptance
remains separate. Part B completion is recorded in section 4 below.
Frontend commit `78346d82` is pushed; the app child bead is closed. The local
Flask-hosted web export has been refreshed from the verified build.

Case rows (`GET /api/v1/intake/cases`) and case detail (`GET /cases/<id>`
and every case reply) gain:

- `other_draft_active`: bool, another interviewer holds an open draft.
- `other_draft_started_at`: ISO time or `null`, when the earliest such draft
  started. The other person is never named.

Show a warning on the row and in detail ("Another interviewer started this
interview on <date>"); it is only as fresh as the last sync.

Other changes the app sees:

- `prefill` is on case detail for every interviewer who can see an open case,
  even when someone else holds a draft.
- `va_sid` on rows/detail is shown only to the interviewer whose interview
  became the submission (not the case starter). `started_by_me` is unchanged.
- `POST /drafts` never answers 409 for another interviewer's draft; the same
  interviewer always gets their one open draft back.
- An upload (`POST /submissions`) for a case where this interviewer has an
  open server draft (started in the browser) completes that draft: one
  interview, not two.
- `POST /drafts/<id>/submit` on a case a teammate already submitted: 200
  `{va_sid: null, draft, superseded: true, validation_err: null}` (normal
  submit is 201 with `superseded: false`).

Part B (phone in-progress draft sync, newer-save-wins) follows in section 4.

## 4. Phone in-progress draft sync, part B (`digitva-xz83`, server built)

Frontend implemented (`digitva-xz83.2`): separate Luna writers delivered native
draft storage/transport, case/form continuation and browser revision guards.
Unsynced phone edits go through the server conflict resolver before download;
every local replacement is snapshot-guarded. Clean server mirrors refresh by
GET rather than interpreting server timestamps as device save times. Local
IDs, start times, answers and questionnaire language survive continuation.
Verified: 31 Jest suites, 314 tests, TypeScript, web and Android JS exports;
independent quality audit found no material issues. The initial Jest package
loading failures are fixed. Physical-device acceptance remains separate.
Frontend commit `6c5ff8cc` is pushed; the app child bead is closed. The local
Flask-hosted web export is refreshed and its served index matches the verified
build. Sections 1–4 are complete on the frontend.

One draft per interviewer per case, continued on the phone or in the browser.
At each sync the phone uploads every unfinished draft of a registered case:

`POST /api/v1/intake/drafts/sync` (bearer):

- `project_id`, `site_id`, `death_id` (required), `org_unit_id`
- `client_draft_id` (the phone draft's UUID; the same id later goes on the
  final `POST /submissions`)
- `answers_json`, `answers_sha256` (exactly as section 1)
- `draft`: envelope meta (`startedAt`, `currentSection`, ...)
- `savedAt`: device time of the last local save; `deviceClockAt`: device
  clock now (both ISO with offset, required)
- `base_updated_at`: the server draft's `updated_at` the phone last
  downloaded, or `null` if never

Reply 200 `{draft, kept: "incoming"|"server", conflict, answers_sha256, message, envelope}`:

- `kept: "incoming"`: the phone's version is now the draft. Store
  `draft.updated_at` as the next `base_updated_at`.
- `kept: "server"`: a newer browser save won. Replace the local draft with
  `envelope.data`; the phone version is kept on the server as history.
- `conflict: true`: show `message` ("This interview was also edited on
  another device; the newer version was kept.").
- Errors: 422 as section 1 plus bad times (`invalid_interview`); 400 without
  `death_id`; 409 `conflict` when the case is closed (stop syncing that draft
  and keep it; it uploads as a superseded copy at completion).

Opening a case: if the case row has `my_draft_id`, fetch
`GET /api/v1/intake/drafts/<my_draft_id>` and continue from its `envelope`
(newer than local by `draft.updated_at` vs your last `base_updated_at`).
Resends are safe: the same version twice writes nothing.

## 5. Revising a submitted interview (`digitva-bhpl`, part A server built)

Frontend implemented (`digitva-bhpl.1`, closed): separate Luna
writers delivered browser revisions and the encrypted native revision queue
and screens. The submitted list shows the server's newest 200 records as
recent interviews. Direct interviews with no death-register ID are supported.
Verified: 34 Jest suites, 358 tests, TypeScript and web/Android JS exports;
the consumed backend revision API passed 19 tests and 15 subtests in an isolated
database. Independent quality audit and re-audit passed after fixing revoked
metadata and browser loading races. Commit `dc70dc49` is pushed, and the local
Flask-served web index matches the refreshed verified build. Physical-device
acceptance is separate. Send-back/reopen remains outside this part.

Frontend recovery complete (`digitva-bhpl.2`, closed), pushed in `5176e7c3`.
The list, Revise screen and upload already shipped under `.1`. A retained phone
revision refused with `revision_locked` can now resume through explicit manual
Revise after server unlock, preserving corrections and form identity. The server
still enforces editability; attention rows never retry automatically. Independent
review passed. Final validation: 43 Jest suites / 504 tests, TypeScript and
Android JavaScript export passed. Physical-device acceptance remains
`digitva-p6fs.5`. Both app revision child beads are complete.

Only the interviewer whose interview became the submission may revise it,
while coding has not been finalised (send-back and reopen come in part B).

List to revise from: `GET /api/v1/intake/drafts?status=submitted` (own,
newest first, metadata only). On Revise, fetch `GET /drafts/<draft_id>`:
`envelope.data` is the complete raw answers as submitted, plus top-level
`answers_sha256`. Keep it on the device only while revising; purge after.

`POST /api/v1/intake/submissions/<va_sid>/revisions` (bearer):

- `reason_code`: `interviewer_correction` | `respondent_correction` |
  `more_information` | `finish_partial` (no free text)
- `answers_json`, `answers_sha256` (as section 1), `completion {valid, issues}`
- `draft`: envelope meta (`startedAt`, `completedAt` as section 2)

Reply 200 `{changed, va_sid, payload_version_id, answers_sha256, outcome, workflow_state}`.
`changed: false` means nothing coded changed (no new version, coding kept).
Idempotent: resending the same revision is `changed: false`. Delete the local
copy when `answers_sha256` matches what you sent.

Errors: 404 not yours (or a superseded copy); 409 `revision_locked` (coding
finalised; show "locked, ask the coder"); 409 `case_already_submitted`
(finishing a partial after a teammate's complete one won); 409 `case_state_conflict` (an outcome change the case can no longer take); 409 `case_closed`;
422 `invalid_reason`, and the section 1 answer/hash codes.

A partial interview (case paused) is finished by revising it with
`reason_code: finish_partial`, not by starting a new draft.

## 6. Form versions and the server-served form (`digitva-xuf9`, `digitva-6pwq`, server built)

Frontend implemented (`digitva-6pwq.1`, closed): current and exact historical
form verification, encrypted native and browser-memory caches, immutable draft
and revision pins, engine compatibility and app-version handshake are pushed
in `f7e4b4da`. Final validation passed 40 Jest suites (472 tests), TypeScript,
web and Android JS exports, and independent audit/re-audit. Mounted revocation,
regrant, full translation identity and legacy-provenance regressions are covered.
The local Flask-served web index matches the refreshed verified export.
Historical recovery is built on the backend (`digitva-6pwq.2`); see below.
Unknown historical definitions preserve answers and fail visibly; unpinned
browser drafts without saved extension provenance also preserve server answers
and cannot silently adopt current settings. Native historical translations use
original English when exact identity cannot be established. Native transport
materializes `response.text()` before its decoded UTF-8 size check. Vendor build
and engine test passed; pre-existing vendor TypeScript errors remain tracked in
`digitva-i793`. Physical Android acceptance is separate.

- `GET /api/v1/organization/<project>/form-options`: `instrument_version` is
  now the composed version (e.g. `2026081401-3833e95fb5`, not the bundle
  hash) and new `definition_sha256` is the SHA-256 of this project's served
  definition. Both are null for a non-WHO-2022 project.
- `GET /api/v1/instruments/WHO_2022_VA/definition?project_id=<p>`: the
  project's composed definition JSON (WHO + its enabled extensions), top-level
  `version` and `engineVersion` (1). Headers: `X-Definition-SHA256` (over the
  uncompressed JSON; verify it), `ETag`, `Cache-Control: private, no-cache`.
  Send `If-None-Match` with the stored ETag -> 304. Send
  `Accept-Encoding: gzip` (about 1 MB plain). Errors: 400 no project_id, 403,
  404 unknown project or other instrument, 503 `unavailable`.
- `GET /api/v1/instruments/WHO_2022_VA/versions`: `{current, versions:
  [{version, activated_at}]}` newest first.
- Every body also carries top-level `extensions`: the sorted conditional
  extensions in the slice. The slice identity is (`version`, `extensions`);
  the SHA-256 verifies it.
- Historical slice: `GET /api/v1/instruments/WHO_2022_VA/definition?project_id=<p>&version=<v>&extensions=a,b`
  (both or neither; `extensions=` empty = none). Same body, headers, gzip and
  304 as above. 404 `version_unknown` (version never recorded), 422
  `invalid_extensions` (names outside that version's tags), 400 `invalid_request`
  (only one param). Authorization is the project access check; the project need
  not enable those extensions today. Current version with the project's current
  extensions returns the same bytes as the default call.
- Envelope meta (`draft` object on `/drafts/sync`, PATCH `meta`, `/submissions`,
  revisions) now accepts `definitionSha256` (64 lowercase hex) and
  `definitionExtensions` (at most 16 names, `[a-z][a-z0-9_]{0,31}`); malformed
  is 422. `GET /drafts/<id>` and the sync reply's `envelope` echo them when set.

App must:

0. Send `app_version` on `POST /auth/sessions` and `/auth/sessions/refresh` (the server records it each time).
1. Add an engine constant `ENGINE_VERSION = 1` in `vendor/who-va-2022`
   (the package exports none). Refuse a definition whose `engineVersion` is
   higher and ask for an app update.
2. At sign-in and sync: if `definition_sha256` differs from the cached one,
   download, verify the SHA, cache per `version`. Keep a version cached until
   every draft started on it has uploaded.
3. A draft stays on the version it started with; send that version as the
   envelope `instrumentVersion` (the server re-checks the upload against that
   version's rules).
   Store the slice with it in the envelope: `definitionSha256` (the
   `X-Definition-SHA256` you verified) and `definitionExtensions` (the body's
   `extensions`). On cache loss fetch by `version` + `extensions`, verify the
   SHA-256 against the stored `definitionSha256`, and never substitute the
   current or bundled form: on failure keep the answers and fail visibly.
4. Bundled form stays the fallback until the first download. Block **new**
   interviews (never uploads) when no current definition the engine can run
   is available: "update the app".
5. Keep narrowing `narr_language` choices to form-options
   `narration_languages` (the served definition carries the full list).

## 7. Notifications (`digitva-hdrv`, server built)

Frontend complete and pushed in `46d9dbf7` (`digitva-hdrv.1` closed).
Final validation: 43 Jest suites / 502 tests, typecheck, web and Android
JavaScript exports, Android module autolinking and isolated Android/iOS prebuild
passed. Independent re-audit is ready after fixing failed-refresh retries and
removing iOS background-processing configuration. Served web refreshed and its
index verified against the validated export. Foreground polling uses
account-scoped cursors and normal authoritative refresh; periodic refresh runs
at least every 15 minutes even with an empty inbox. Locked Android tasks record
only cursor/pending-sync metadata; full sync waits for unlock. Browser revision
checks preserve nudges during requests and retry failures on subsequent polls.
Native modules need a rebuilt binary. APK compilation and physical WorkManager
acceptance remain in `digitva-p6fs.5`; no Java/Gradle/Android SDK was available in
the validation container. Verified server behavior allows an empty cursor to
rewind after a DB restore; the parser accepts that bounded rewind. Continue
monitoring for new actionable sections; backend instructions below are retained.

No Google FCM and no Expo push: the app polls. The inbox is a nudge to run the
normal sync; sync stays the source of truth, so a missed poll costs nothing.

`GET /api/v1/me/notifications?after=<id>` (cookie or bearer, any signed-in
user, own rows only; 120/min). `after` defaults to 0; anything but a
non-negative integer is 400 `invalid_request`; signed out is 401.

```json
{"notifications": [{"id": 17, "kind": "revision_requested",
  "created_at": "2026-10-05T09:30:00+00:00", "project_id": "ABC01",
  "death_id": "<uuid>|null", "draft_id": "<uuid>|null", "va_sid": "<sid>|null"}],
 "next_cursor": 17}
```

Rows with `id > after`, oldest first, at most 100. `next_cursor` is the last
returned id, or `after` when nothing is newer: store it (per signed-in user) and
send it as the next `after`. Exactly 100 rows means there may be more: poll
again at once.

| `kind` | Meaning | Fields set |
|---|---|---|
| `revision_requested` | a coder, reviewer or supervisor sent your submitted interview back | `va_sid`, `death_id`, `draft_id` |
| `other_draft_started` | another interviewer started a draft on a case where you hold one | `death_id`, your `draft_id` |
| `case_submitted_by_other` | a teammate's complete submission closed a case where you hold a draft | `death_id`, your `draft_id` |
| `case_reopened` | a supervisor reopened a case you started or hold a draft on | `death_id`, `draft_id` if you hold one |

An unknown `kind` is ignored (new kinds may appear). Not built:
`case_registered_in_my_unit` and `form_version_available` (the form-options
`definition_sha256` already tells you at each sync).

Polling rules:

1. Poll on app foreground, then about every 60 s while the app is open (never
   faster than every 30 s). An empty poll costs the server no database query.
2. On Android also poll from a WorkManager task (`expo-background-task`); no
   Google push. iOS polls on foreground only.
3. A non-empty reply, or any doubt, means run the normal `/api/v1` sync and
   re-read the data; never change local state from a notification alone. Show
   at most a local nudge ("A case needs your attention"); never put names,
   phones or answers in it (the rows hold none).
4. Keep the cursor per user; clear it on sign-out or when a different user
   signs in. Rows live 30 days: a cursor older than that just returns what is
   left, so a long-absent app should sync regardless.
5. Rows can, rarely, commit out of id order and one can be passed; this is why
   the notification is only a nudge and a periodic sync still runs.
6. A revoked session needs no notification: any call answers 401
   `session_revoked`.

## 8. Last completed version wins (`digitva-xpqm`, server built)

Expo status, 2026-10-05: `digitva-xpqm.1` and duplicate app bead `digitva-xpqm.2` completed and pushed in `cc5adee8`. Native and browser changes were written by separate Luna code-writer tasks. Final validation: 43 Jest suites / 522 tests, TypeScript, web and Android JavaScript exports, and served web index match. Independent code-quality re-audit returned READY after fixing nullable direct-upload acknowledgements; strict bound-case identity and snapshot guards remain. Public revisions retain their separate `answers_sha256` acknowledgement. Physical-device acceptance remains `digitva-p6fs.5`.

Owner, 2026-10-05. For one interviewer's own interview of a case the coder
always gets the **last completed version, by completion time**. This replaces
the `hash_mismatch` rows in section 1 and the `outcome_regression` error in
section 5: neither code exists any more. Drafts and syncs never compete with a
completion.

**Completion time** is `completedAt` corrected by `deviceClockAt`
(`min(now, now - (deviceClockAt - completedAt))`, as the draft sync). Always
send both on `POST /submissions` and on a revision. Without both the server
uses its receive time, which makes the upload look newest. A browser submit
counts at the server's time.

**Reply to `POST /api/v1/intake/submissions` (every case):**

```json
{
  "va_sid": "...", "case": {"death_id": "...", "unique_id": "...", "status": "..."},
  "outcome": "completed", "superseded": false,
  "answers_sha256": "<hash of the coder version's answers>",
  "received_sha256": "<hash of the answers this request sent, as received>",
  "kept": "incoming" | "server",
  "locked": false
}
```

| Status | When |
| --- | --- |
| 201 | first upload of a `client_draft_id` (also a second upload of a case you already submitted, a correction) |
| 200 | resend of a `client_draft_id`: same hash, or other answers (no 409) |

`kept: "incoming"`: the coder now has the answers you sent. `kept: "server"`:
the coder keeps a newer completed version; the answers you sent are stored as
history. `locked: true`: coding is final (or the case is closed or won by a
teammate), so no upload can change the coder's version; only a send-back or a
supervisor's reopen can. A superseded copy of a case closed by a teammate is
`kept: "server"`, `locked: true`, `superseded: true`.

The server never refuses a resend for a different hash. A later version
applies when its completion time is not older than the stored one (a tie goes
to the one received later); the server decides, not the app.

**The app must change:**

1. Drop all `hash_mismatch` handling (`sync.ts`, `drafts.ts`, the worklist
   card's disabled state and the `upload_issue` value). A resend with other
   answers is now a normal 200.
2. Delete the local copy when the reply's **`received_sha256`** equals the
   hash it sent (lower-case) and `case.death_id` matches, whatever `kept` is.
   `kept: "server"` is an acknowledgement. Do not compare `answers_sha256`
   for this: it is the coder version's hash and differs when `kept` is
   `server`.
3. When `kept` is `"server"`, show "A newer completed version is already with
   the coder; yours was saved as history." When `locked` is also true add
   that coding has finished and only a send-back or reopen can change it.
4. A completed interview revised (public revision or a later upload) to a
   refusal or partial one is accepted: the case leaves coding and its
   `case.status` becomes `refused`, `paused` or `not_reachable`, with no
   `va_sid` in the worklist row until it is completed again. Remove the
   `outcome_regression` message; the 409 `case_state_conflict` message stays
   (a teammate's complete interview overtook yours).
5. A phone completion is submitted even when the interviewer has newer
   unfinished browser saves of the same case; those saves are kept on the
   server as history. Nothing to do in the app.
6. The browser's `POST /drafts/<id>/submit` of an already submitted draft
   (stale tab) is now a 200 correction with `kept` and `locked`, not a 409.

No new endpoints. Revision reasons stay the four public codes; the server's
own `resubmitted` is rejected from clients (422 `invalid_reason`).

## 9. Supervisor chooses between interviews (`digitva-bqzm`, server built)

Expo status, 2026-10-05: `digitva-bqzm.1` and duplicate app half `digitva-bqzm.2` completed in pushed commit `46ebe43c`. Native/browser lists and case details show the neutral localized note only when the optional boolean is true; superseded wording no longer assumes submission order. Existing generic notifications and authoritative case replacement remain the ownership sync path. Validation: 43 Jest suites / 528 tests, TypeScript, web export, Android JavaScript export, served web-build match, and independent code-quality audit READY. Physical-device acceptance remains pending under `digitva-p6fs.5`.

When a different interviewer completes a case another interviewer already
submitted, both interviews are kept. The first keeps coding; the later one is
a **candidate**. A supervisor, data manager or admin may choose the candidate
at any stage (after final COD too) and may switch back. Policy:
`docs/policy/web-intake.md`, "Parallel interviews" and "Supervisors".

**What the interviewer's app sees:**

1. **`other_complete_interview`** (bool) on every case row and on the case
   detail (`GET /intake/cases`, `GET /intake/cases/<id>`, and every
   single-case reply that uses the detail shape). True when a second complete interview of the submitted case exists. Never
   whose, never its answers. Show a neutral note ("Another complete interview
   of this case is with the supervisor"); do not act on it. Default false when
   absent.
2. **`interview_chosen` notification** (`GET /me/notifications`): `death_id`,
   the recipient's own `draft_id`, and `va_sid` only for the interviewer whose
   interview was chosen. Run the normal sync on it: the case row's `va_sid`
   now follows the chosen interviewer (the previous winner's row loses it,
   exactly as after a regression). Not sent to the supervisor who chose.
3. **The chosen interviewer** now owns the case's submission. Their later
   uploads of that interview, or a public revision, are corrections as in
   section 8, on the same `va_sid`.
4. **The previous winner's** later upload of the same interview (same
   `client_draft_id`) is kept as history: 200 with `kept: "server"` and
   `locked: true`. A new `client_draft_id` for the case is stored as another
   superseded copy (201, `superseded: true`), which is a candidate again when
   complete. The upload reply never says which interview the coder has beyond
   `kept` and `locked`.
5. Switching back moves the `va_sid` back the same way; the notification and
   the row are the whole contract.

No new interviewer endpoint. The supervisor endpoints
(`GET /intake/supervision/cases/<id>`, `POST .../choose-interview`,
`GET /intake/supervision/cases?candidates=true`) are for the web supervision
page; interviewers never see the other interviewer's name.

## 10. Self-coding: "Code this case now" (`digitva-xuxk`, server built)

Expo status, 2026-10-05: hint-only `digitva-xuxk.1.1` completed and pushed in `7bedb4bb`. Server readiness hints appear after acknowledged uploads and on case lists/details; fresh case flags take precedence, while refresh failures preserve the acknowledged hint. Validation: 43 Jest suites / 538 tests, TypeScript, web and Android JS exports passed; independent re-audit READY. Served web index matches the export. `digitva-xuxk.1` remains open: coding action/release are held by `digitva-xl43` / `digitva-p6fs.4`; no allocation endpoint is called. Physical device acceptance remains pending (`digitva-p6fs.5`).

App half: `digitva-xuxk.1`. Policy: `docs/policy/web-intake.md`
("Self-coding projects"), `docs/policy/coding-workflow-state-machine.md`
("Self-coding"), `docs/policy/coding-allocation-timeouts.md` ("Coder
release"). Route detail: `docs/current-state/api-v1.md`, "Code this case now"
and "Coder release".

A project setting, off by default. In a self-coding project a Coder grant
also lets its holder interview (same scope; derived by the server, so
`me/access` and the interviewer routes simply start working for them). A
completed interview goes into the normal coding pool: any coder may take it.
The submitter is offered it first, if still free. One coding allocation per
coder at a time.

**What the app sees:**

1. **`can_code_now`** (bool) on the device upload result
   (`POST /intake/submissions`, also on a resend). True when the caller may
   be offered "Code this case now": a completed interview with valid consent,
   in a self-coding project, and the caller holds a coder grant that codes.
   Grants only; the action re-checks. Default false when absent.
2. **`code_now`** (bool) on every case row and the case detail
   (`GET /intake/cases`, `GET /intake/cases/<id>`): the caller's own
   submission is `ready_for_coding` (a confirmed duplicate never is), so the
   action will work now. Default false when absent.
3. **`POST /coding/submissions/<va_sid>/code-now`**, no body, bearer token
   works. 201 `{va_sid, actiontype}`; 200 when the caller already holds it.
   Errors `{error, code}`: 409 `not_ready` (attachments or SmartVA still
   running, usually seconds: retry a few times, about 2 s apart, then say
   "Still preparing, try again from the worklist"), 409 `held_by_another`
   (another coder took it: hide the button), 403 `allocation_exists` (the
   user holds another case: offer Release), 403 `forbidden`, 404
   `not_found`, 409 `not_available` / `conflict`. A 409 also carries
   `workflow_state`.
4. **`POST /coding/allocation/release`**, no body: drops the caller's own
   active coding allocation. 200 `{va_sid, workflow_state}`; 409
   `no_allocation`. Unfinished Step 1 work on that case is discarded, as on
   the 1-hour timeout; say so before releasing.

**Blocked:** the app cannot code yet (the coding workspace is server HTML
until `digitva-xl43`, app `digitva-p6fs.4`). Until then, show `can_code_now`
/ `code_now` as a hint only ("Ready for you to code on the web"); do not call
`code-now` from the app, since it would hold a case the user cannot open
there. Build the button with `p6fs.4`.

## 11. Coders and reviewers sign in to the app (`digitva-xl43.1`, server built)

Expo status, 2026-10-05: `digitva-p6fs.4.1` is implemented but not landed or closed. Collection gates, intake context and native/browser cache reconciliation now use authoritative `actions.interview`; inactive projects are purged without eligibility probes. Latest frozen frontend checks passed 45 Jest suites / 573 tests, TypeScript, web and Android JS exports, and served web index match. Independent re-audit: client READY. One server contract defect blocks landing: `web_intake_service.interviewer_context` initializes broad project/site reach with `org_units: []` but then appends narrower unit grants for the same pair (lines 301-337), while `reachable_unit_ids` correctly treats the broad grant as whole-tree (lines 443-446). Please preserve empty roots for broadly authorized pairs and test overlapping broad-plus-unit grants so the app does not restrict valid units. Section 12 implementation follows this gate; DORIS contract planning is being updated. Physical-device acceptance remains pending.

Server answer, 2026-10-05 (overlapping grants): fixed in
`web_intake_service.interviewer_context`. A (project, site) a project or
site interviewer grant reaches keeps `org_units: []` (the whole tree) even
when the user also holds a unit grant in that project; unit grants add units
only to pairs no wide grant reaches. This now agrees with
`reachable_unit_ids` (`None` for the pair) and flows unchanged into
`/me/access` `actions.interview`. Test:
`tests/services/test_web_intake_service.py`,
`test_a_wide_grant_keeps_the_whole_tree_when_a_unit_grant_overlaps`.

Server answer, 2026-10-05 (`digitva-ntct.3`): `/me/access` (and the
`access` on sign-in and refresh) is now the complete statement of what the
user may do, every value from the check the server enforces; additive, no
existing key changed type. Full body: `docs/current-state/api-v1.md`, "GET
/api/v1/me/access (body)". What the app needs:

- **Gate collection on `projects[].actions.interview`**, not on
  `sites[].roles`: one entry per site where the intake routes accept an
  interview (web intake on, active project-site, an active form for a project
  or site grant), with `web_intake_mode` and the interviewer's units. Empty in
  every project: no collection screens. This replaces the form-options probe
  in `hasEffectiveIntakeAccess`.
- `sites[].roles` and `units[].roles` now count only grants that work
  (`grants[].active`), and list derived `data_manager` / `interview_supervisor`
  (an In-charge on their subtree, a tree-project PI everywhere). `interviewer`
  appears at a site only where `actions.interview` lists it, and on no unit
  when web intake is off. `units[].can_code` also counts active grants only.
- Top-level `roles`: the screens that open (explicit grants only; demo stays
  under `demo_coding`). Show coding or review only when `coder` /
  `coding_tester` / `reviewer` is there.
- `grants[]` lists every grant with `active` and `source` (`assigned`, or
  `self_coding` for the interviewer grant a self-coding coder gets).
- Per project: `settings` (`web_intake_mode`, `coding_scope`), `self_coding
  {enabled, code_now}`, `actions` (reach per server action: `project`,
  `site_ids`, `org_unit_ids`; the server still decides per case).
- `account {privileged, second_factor, pii_visible, device_access, mentor}`,
  `user.landing_page`, `user.coding_languages`, `admin_actions`.

Owner 2026-10-05. Device sign-in and refresh now accept an active `coder`,
`coding_tester` or `reviewer` grant as well as an interviewer one
(`docs/policy/field-data-collection.md`, "Who may sign in on a device"). No
new route; every route still checks its own role, so a coder-only user gets
403 on `/intake/*`.

1. **A user may have no interviewer access.** `access` on the sign-in reply
   and `GET /me/access` list their coder/reviewer grants (`codes` per coding
   grant); there may be no interviewer project. The app must not assume
   collection: show no collection screens when no interviewer project exists
   and say coding and review come with `digitva-p6fs.4`.
2. **Refusal text.** The code stays `no_interviewer_grant` (the app matches
   on it, `src/ui.tsx`), now meaning "no access in any project". The app's
   `errNoGrant` string in `en.json` and `hi.json` ("no interviewer access in
   this project") is wrong for the new rule; reword it.
3. **Revocation** follows the wider rule: the session ends when the user holds
   none of interviewer, coder, coding tester or reviewer.

The coding and review workspace routes are in section 12.

## 12. Coding and review workspace (`digitva-xl43` phases 1-3, server built)

Expo status, 2026-10-05: ICD catalogue and Narrative QA / Social Autopsy metadata are verified in `b0c91950`; DORIS seed and processing are now served in `86a74164`. The read-only planner updated the complete simple/DORIS workspace plan: shared contract/transport first, independent queue, simple COD/quality/note, DORIS React form and media packages next, platform/lifecycle integration last. The existing WHO interview vendor package has no DORIS editor; Expo will implement the served certificate state/API contract using shared React UI. Implementation waits on section 11 landing and its remaining broad-plus-unit server scope defect. Finished-case view and physical-device media acceptance remain pending; no allocation is acquired by the app yet.

App half: `digitva-p6fs.4`. Full bodies and every error code:
`docs/current-state/api-v1.md`, "Coder COD writes", "Reviewer COD routes",
"Reviewer queue", "Reviewer release", "Workspace content", "Media" and
"Private note".
Either credential; errors are `{error, code}`. Every route below needs the
caller's own active allocation on the case (403 `no_allocation` otherwise);
the existing allocation routes get one (`GET/POST /coding/allocation`,
`POST /coding/submissions/<va_sid>/code-now`, `POST /coding/recode/<va_sid>`,
`POST /coding/allocation/release`; reviewers `GET /reviewing/allocation`,
`POST /reviewing/allocation/<va_sid>`).

1. **Open a case:** `GET /api/v1/va/<va_sid>/workspace?mode=coding|reviewing`
   gives the case header, the ordered category list (`categories`,
   `default_category`), which COD step is due (`step`: `initial`, `final`,
   `done`) and what blocks the final save (`blocked_by`: `narrative_qa`,
   `social_autopsy`), the saved assessments (Step 1 prefill included), the
   SmartVA result (null at masked Step 1: Step 1 is blind) and the Step 1
   other-conditions list. Do not cache it (`no-store`).
2. **Show a category:** `GET /api/v1/va/<va_sid>/categories/<code>?mode=`
   gives ordered `subcategories[].items[] {label, value, flip, info}`; keep
   the server's order. The COD panel category `vacodassessment` carries the
   narration, documents and health history shown beside the COD form.
3. **Save COD (coders):** `POST /api/v1/coding/initial/<va_sid>` (masked
   projects, when `step` is `initial`), `POST /api/v1/coding/finalize/<va_sid>`
   (when `step` is `final`), `POST /api/v1/coding/not-codeable/<va_sid>`.
   Reviewers: `POST /api/v1/reviewing/initial/<va_sid>` and
   `/reviewing/finalize/<va_sid>`. After a save,
   reload the workspace for the next step; 422 `final_blocked` lists the
   blocking gates in `messages`. Reviewing, narrative QA and Social Autopsy
   refusals are now flat `{error, code}` too (a DORIS conflict adds
   `processing`).
4. **Not yet served** (do not build against the web routes): no read-only
   view of a finished case or of a case the caller does not hold. DORIS
   prefill is now served (item 9).
5. **Media:** attachment `value`s in the category bodies are
   `/api/v1/attachments/<token>` (or `/attachments/legacy/<form>/<file>`)
   paths, the same for every client, ending in the original extension (sniff
   image or audio by it). Gate and bodies: `api-v1.md`, "Media". Native:
   `source={{uri, headers: {Authorization: 'Bearer ...'}}}`. Expo web on the
   cookie loads the URL directly; a bearer-only web client fetches with the
   header and uses a blob URL. Audio seeks by `Range` (206); on the S3 store
   the reply is a 302 to a presigned URL. Errors are `{error, code}`: 403
   `forbidden` (a plain collaborator never gets media), 404 `not_found`, 502
   `upstream_error`, 503 `unavailable` with `Retry-After`. Device risk, check
   on hardware (`digitva-p6fs.5`): a player that forwards `Authorization` to
   the S3 redirect is refused by S3; if so, fetch the bytes yourself.
6. **Private note:** `GET|PUT /api/v1/va/<va_sid>/note?mode=coding|reviewing`
   (own allocation only). `GET` gives `{va_sid, content, updated_at}` (nulls
   when none); `PUT {"content": text}` saves and answers the same. Empty or
   whitespace-only content is 400 `invalid_request`, over 20,000 characters
   422, a body over 64 KB 413 `payload_too_large`. One note per user per case, shared
   by the coding and reviewing sessions and by the web note box. Do not
   cache it (`no-store`).
7. **Reviewer queue and release:** `GET /api/v1/reviewing/stats`
   (`{in_scope, completed, available, allocation}`), `/reviewing/available`
   and `/reviewing/history` (paged: `limit` 1-200, default 50, `offset`,
   `has_more`; optional `project_id`). `/available` lists exactly the cases
   `POST /reviewing/allocation/<va_sid>` accepts. `POST
   /api/v1/reviewing/allocation/release` (no body) gives the case back: 200
   `{va_sid, workflow_state}`, 409 `no_allocation` / `wrong_state`; the
   reviewer's saved Step 1 is kept and their NQA and Social Autopsy analysis
   are cleared, as on a timeout.
8. **ICD catalogue, Narrative QA and Social Autopsy** (`digitva-xl43.6`,
   `digitva-xl43.7`, server built 2026-10-05 in `b0c91950`; this closes the
   two gaps in the Expo status line above). Full shapes: `api-v1.md`,
   "Workspace content". The workspace now carries:
   - `case.icd_classification`, `icd10` or `icd11`. Search with
     `GET /api/v1/icd10/2019-2/coding-search/<va_sid>?q=` or
     `GET /api/v1/icd11/coding-search/<va_sid>?q=` to match; the other one
     answers 400. Both take the bearer.
   - `narrative_qa`: null when the project has it off, else
     `{fields: [{key, label, options: [{value, label}]}], max_score: 10,
     saved}`. `saved` is null or the caller's own
     `{cannot_grade, values: {key: int}, score, rating}` on the current
     payload (a cannot-grade save returns its stored zeros). Render the
     fields in the server's order; `key` is the save body key.
   - `social_autopsy`: null when the role's switch is off, else
     `{questions: [{delay_level, title, options: [{option_code, label,
     description}]}], saved}`; `saved` is null or the caller's own
     `{selected_options: [{delay_level, option_code}], remark}`.
   Save with the existing `POST /api/v1/va/<va_sid>/narrative-qa`
   (`{va_actiontype, cannot_grade, length, pos_symptoms, neg_symptoms,
   chronology, doc_review, comorbidity}`) and
   `POST /api/v1/va/<va_sid>/social-autopsy`
   (`{va_actiontype, selected_options, remark}`). `va_actiontype` decides the
   role: a reviewer must send `varesumereviewing`, a coder `varesumecoding`;
   a reviewer save without it is checked as a coder save and refused. Social
   Autopsy needs every delay level answered, and `none` is exclusive within a
   level. After a save, reload the workspace: `blocked_by` drops the gate.
9. **DORIS projects** (`digitva-xl43.3`, server built 2026-10-05; this
   lifts the DORIS hold in the Expo status line above). The workspace
   carries `doris`: null unless `case.project_mode` is `masked_doris` or
   `unmasked_doris`, else the certificate editor's seed, from the same
   service the web screens use (full shape: `api-v1.md`, "Workspace
   content", `doris` row):
   - `initial_certificate` and `prefill_provenance`: the certificate to open
     the editor with. A saved certificate (own Step 1, or for unmasked the
     reviewer's own final, else the authoritative coder final) wins over the
     interview prefill; `prefill_provenance` marks prefilled fields and is
     empty for a saved certificate.
   - Masked projects add `saved_processing` (`{certificate, doris, codedit,
     final_choice}`: the caller's own processed Step 1, display-only; null
     without one) and `step1_certificate` / `step1_processing` (the own
     Step 1 that Step 2 confirms; null until there is one). A masked coder
     gets these at both steps, so Step 1 can be reopened after it is saved.
   - Reading the seed mints no process token: run
     `POST /api/v1/doris-clinical/process/<va_sid>` before saving a changed
     certificate, then send `doris_certificate`, `doris_result`,
     `codedit_result`, `doris_process_token`, `doris_result_digest`,
     `doris_client_revision` to the existing `/coding/initial|finalize` or
     `/reviewing/initial|finalize` routes (masked Step 2 takes no
     certificate). Other editor routes: `/api/v1/doris-clinical/{terms,
     codeinfo,selection-check}/<va_sid>`.
   - Masked Step 1 carries no SmartVA and never another coder's Step 1 or
     final.
   - Errors: `/api/v1/doris-clinical/*` is the one `/api/v1` family that
     does not answer flat `{error, code}`. It answers
     `{"schema_version": 1, "error": {"code": "INVALID_INPUT", "message":
     "..."}}` (upper-case codes), tied to the DORIS editor and the WHO
     DORIS model (owner 2026-10-05). Read `error.code` there. The COD save
     routes stay flat (a DORIS conflict adds `processing`).

## 13. Correcting a death, and the read-only case view (server built 2026-10-06)

App halves: build in the Expo app (web and native); the server ships no web
form for these (owner, 2026-10-06).

1. **Correcting a registered death** (`digitva-uq6v`). `PATCH
   /api/v1/intake/deaths/<death_id>` with only the register fields to change
   and optional `if_updated_at` (the `case.updated_at` last seen). Anyone who
   can see the death (or supervises it) may correct it until an interview of
   the case is completed. 200 `{"case": <detail>}`; 409 `case_completed`,
   `details_pending` (identity not captured yet), `death_stale` (reload and
   retry); 422 `invalid_death` (same validation as registration). Build the
   edit screen from the registration form. Once an interview is completed,
   its identity becomes the case's (follow-up in progress: date of birth and
   age too, shown in the death list).
2. **Read-only case view** (`digitva-xl43.8`). `GET
   /api/v1/va/<sid>/workspace?mode=view` and `/categories/<code>?mode=view`:
   open any case the user may view, without holding it (finished cases, a
   colleague's case). Nothing editable: `step: "view"`, no DORIS, NQA or
   Social Autopsy forms; final COD, reviewer final, coder Step 1 and SmartVA
   are reference. Workflow history: `GET /api/v1/workflow/events/<sid>`.
   Full shape: `docs/current-state/api-v1.md`, "Workspace content". This
   lifts the finished-case-view hold in section 12.

