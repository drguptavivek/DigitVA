# Expo handoff: field collection integrity

For the Expo session (owns `mobile/` and `vendor/`). The backend session
builds the server half of each bead and records the exact contract here.
Policy: `docs/policy/field-data-collection.md`, `docs/policy/web-intake.md`
("Parallel interviews"), `docs/policy/interview-revisions.md`. Each section
names its bead; the app half is its child bead (e.g. `digitva-2bxa.1`); the server bead stays open until its app half lands. The backend session
rewrites this file as beads land; the Expo session closes the app beads.

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
| 409 `hash_mismatch` | resend, same id, different hash | `{error, code, stored: result}` |
| 409 `conflict` | another interviewer's `client_draft_id` | `{error, code}` |
| 422 `answers_hash_required` | `answers_json`/`answers_sha256` missing or malformed | `{error, code}` |
| 422 `answers_hash_invalid` | hash does not match the text received | `{error, code}` |
| 422 `invalid_interview` | text over 1 MB, not a JSON object, too deep | `{error, code}` |

Result: `{va_sid, case: {death_id, unique_id, status}, outcome, superseded, answers_sha256}`.
The echoed `answers_sha256` is lower-case hex.

App must:

1. Delete the local copy only when the reply's `answers_sha256` equals the
   hash it sent (compare lower-case) and `case.death_id` matches.
2. On 409 `hash_mismatch`: stop retrying that draft, keep it, and tell the
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
remains separate. Part B waits for the section 4 backend contract.
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

Frontend in progress (`digitva-xz83.2`): separate Luna writers own native
storage/transport, native integration and browser revision guards. Local
replacement is snapshot-guarded; unsynced phone edits go through the server
conflict resolver before downloading a newer draft. Combined validation and
quality audit are pending.

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
