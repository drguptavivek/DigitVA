# Collect: upload unsent work from the Android background task (digitva-bxff)

Status: superseded 2026-11-09 — owner chose the simple path: send queued work when the app goes to the background, in the 60 s before the store locks (src/AppState.tsx sendOnLeave). Outbox not built.
Priority: P1
Created: 2026-11-08

## Goal
Upload queued interviews, registrations, refusals, contact attempts/visits and attachments
from the Android WorkManager task (src/notificationTask.ts) while the app is closed and
every interviewer store is PIN-locked.

## Context (facts from code)
- Per-interviewer SQLCipher stores keyed by a data key held in Keystore SecureStore
  (WHEN_UNLOCKED_THIS_DEVICE_ONLY): one copy wrapped by PIN + store secret, one reset copy
  released only after a password sign-in (src/vault.ts, src/interviewerDb.ts).
- Stores lock after 5 min idle or 60 s in background (src/autoLock.ts). The headless task
  starts a fresh JS context, so every store is locked there.
- Tokens and refresh live in SecureStore and need no PIN; the task already calls
  refreshAccessSummary and authedRequest per account.
- Attachments are BLOB rows inside the encrypted store (src/attachmentStore.ts).
- The server deduplicates on client_draft_id / client_death_id / client_attempt_id, with
  received_sha256 acknowledgement (field-data-collection.md "Upload integrity").

## Options
a) Upload only while a store is unlocked in memory: no coverage once the process is gone or
   60 s in background have passed. Rejected as the main path.
b) Outbox (RECOMMENDED): at queue time also write the exact outgoing request (path, body,
   answers_sha256, client ids, attachment bytes) to a separate SQLCipher file keyed by a random
   device key in SecureStore (no PIN). The background task sends each row and deletes it on a
   matching acknowledgement. The main store is untouched; the next foreground sync resends and
   the server returns the first result.
c) A SecureStore copy of the store key for the background task: unlocks the whole store
   (history, roster, coding cache) without a PIN and contradicts "unwrapped key only in memory
   while unlocked". Rejected.

## Design (b)
- New src/outbox.ts: openOutbox() reuses openKeyed from interviewerDb.ts with key `outbox.key`
  (32 random bytes, SecureStore options as vault.ts). Table outbox(client_id PK, user_id_hash,
  server, kind, method, path, body, expect_sha256, depends_on, attachment BLOB NULL, created_at,
  tries, last_error, claimed_at).
- Write: after the main-store commit at each queue point, outbox.put (upsert by client_id). A
  failed put only logs; the main store still holds the work.
- Dependencies: an interview whose death id is still a client id is sent only after its
  registration is acknowledged in the same pass, else left. Revisions stay foreground-only.
- Send: runNativeNotificationTask calls drainOutbox(userId) for eligible accounts, with the same
  authedRequest. Delete only on a matching acknowledgement. 401/403/revoked: stop that account,
  keep rows. Other 4xx: keep, stop retrying, leave to foreground. 5xx/timeout: keep, tries++.
- Foreground: after uploadQueuedWork deletes an item, outbox.delete(client_id). Account wipe or
  revoke deletes that user's rows. Unsent counts stay from the main store.
- Locking: claim rows with claimed_at (5 min lease); double sends are harmless (server dedupe).
- Limits: network-connected constraint if expo-background-task exposes it; at most ~20 rows or
  ~25 s per run; attachments last, one at a time; outbox capped (e.g. 200 MB), over the cap the
  attachment bytes are left to the foreground.
- iOS: best effort, drain the outbox at app launch before the unlock screen.
- Old servers: same endpoints and bodies as the foreground.
- Telemetry: counts and error codes only.
- User view: before unlock the profiles list may show "Sent in background: N" (counts only).

## Migration-free check
No main-store schema change (new file on first use); no server schema/API change, pending the
attachment idempotency check. Old APKs never see the outbox. Work queued before the release is
backfilled on next unlock (optional; the foreground sends it anyway).

## Files to change
mobile/digitva-collect/src/outbox.ts (new), notificationTask.ts, sync.ts (and/or drafts.ts,
deathRegistrationApi.ts, attachmentStore.ts queue points), interviewerDb.ts (keyed-open helper),
auth.ts (wipe); docs/current-state/expo-client.md; docs/policy/field-data-collection.md after D1.

## Tests
outbox put/claim/delete and cap; drainOutbox ack/mismatch/401/422/5xx; dependency ordering;
foreground resend after background send; wipe removes only that user's rows; the background
drain never opens an interviewer DB.

## Open checks
- Attachment upload endpoint idempotent on attachment id (fix server first if not).
- expo-background-task network constraint support.
- Exact queue-write call sites.

## Risks
- PII at rest without the PIN until acknowledged (D1).
- Disk doubling for attachments (cap).
- Edited after queueing: upsert by client_id; server last-completed-wins.

## Owner decision
D1: accept unsent work at rest under a device-only Keystore key (no PIN) until the server
acknowledges it? yes / yes-without-attachments / no (then option a only).

## PROPOSED policy baseline (not in docs/policy yet)
> ### Background upload outbox (PROPOSED, `digitva-bxff`)
> - On Android the app may upload unsent work while closed. When work is queued, an exact copy
>   of each outgoing request is written to a separate encrypted outbox, keyed by a random device
>   key in hardware-backed storage that does not need the PIN.
> - The outbox holds only unsent requests (answers, registrations, refusals, contact attempts,
>   attachments), never sent history, rosters, coding or reference data. A row is deleted after
>   a matching acknowledgement and wiped with the account or store.
> - The PIN-locked store remains the only source of truth; background upload never opens,
>   unlocks or changes it. The next foreground sync resends and the server returns the first
>   result.
> - Background upload uses the account's own tokens and server, stops on sign-in-required or
>   revocation, and never refuses or drops work.
> - Logs and telemetry carry counts and error codes only.
> - Accepted risk: between queueing and acknowledgement, unsent work is protected by the device
>   key but not by the PIN.
> - iOS: best effort, the outbox is drained at app launch.
