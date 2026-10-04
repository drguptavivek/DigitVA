# Expo handoff: field collection integrity

For the Expo session (owns `mobile/` and `vendor/`). The backend session
builds the server half of each bead and records the exact contract here.
Policy: `docs/policy/field-data-collection.md`, `docs/policy/web-intake.md`
("Parallel interviews"), `docs/policy/interview-revisions.md`. Each section
names its bead; the app half is its child bead (e.g. `digitva-2bxa.1`); the server bead stays open until its app half lands. The backend session
rewrites this file as beads land; the Expo session closes the app beads.

## 1. Answers hash on upload (`digitva-2bxa`, server built)

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
