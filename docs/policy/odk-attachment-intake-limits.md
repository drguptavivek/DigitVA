---
title: ODK Attachment Intake Limits
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-14
---

# ODK Attachment Intake Limits

## Purpose

Web intake already caps uploads and sniffs their type from the leading bytes.
ODK sync stored Central's attachments as they came: no size cap, and the
upstream `Content-Type` trusted. This policy brings the ODK path under the same
limits and says what happens to a file that is refused, so nothing is dropped
silently.

Implementation: `app/utils/va_odk/va_odk_07_syncattachments.py`, with the caps
and refusal vocabulary in `app/services/attachment_service.py`. Current-state
detail: [ODK Sync And Attachments](../current-state/odk-sync.md).

## Decisions (owner, 2026-10-14)

1. **Caps.** 50 MB per ODK-synced attachment and 5 MB for `.amr` (owner decision
   2026-10-14, superseding 2026-10-06). The Expo app is meant to share the 50 MB
   cap; it has no size check of its own today. The values are the same as web
   intake. Both live in `attachment_service` (`MAX_BYTES`,
   `AMR_MAX_BYTES`); intake and sync import them. Do not copy the numbers.
2. **Over the cap: not stored.** The stream stops as soon as the running byte
   count passes the cap, so the whole body is never downloaded. A Content-Length
   over the cap is refused before any body is read. Each refusal is recorded on
   the attachment row (`refused_reason = too_large`, `refused_size_bytes`, and
   Central's ETag). Each one logs a single warning carrying the submission id
   and filename, never content.
3. **Retry only on a changed ETag.** A 304 for a refused row is skipped. It does
   not trigger the "ETag 304 but local file missing" forced re-download. A 200
   with a changed ETag tries again, and a copy that fits clears the refusal.
4. **Never drop data silently.** The row keeps `exists_on_odk` and its metadata.
   Refusals are counted in the submission result, in the sync run
   (`va_sync_runs.attachment_refused`), and on the Attachment Management panel,
   by reason and largest size seen.
5. **Stored MIME.** No ODK file is rejected on type. If the leading bytes match
   an accepted signature, that detected MIME is stored. Otherwise Central's
   label is kept after `safe_mime_type`, except active or scriptable labels
   (`text/html`, `application/xhtml+xml`, `image/svg+xml`, `text/xml`,
   `application/xml`, any JavaScript type, and any type containing `+xml` or
   `script`), which are stored as `application/octet-stream`. The head comes
   from the temp file already written; nothing is downloaded twice.
6. **Central self-heal and repair use the same cap.** Delivery's fallback fetch
   and background repair refuse a file over `max_bytes_for(filename)` exactly as
   sync does: a declared Content-Length over the cap is refused before any body
   is read (delivery answers 404), a body that passes the cap mid-stream is cut
   off and nothing past the cap is stored, and the refusal is recorded on the
   row. Repair reports `refused`, which is not an error and is not re-queued.

## Consequences

- An over-cap file is absent from DigitVA until Central's copy changes or the
  cap is raised. Raising the cap does not retry by itself: the next ETag change
  or a forced re-download does.
- A refused row that already had a stored copy keeps that copy and its
  `storage_name`. Only the ETag and refusal fields move.
- A file Central sends without an ETag has no ETag to compare, so it is fetched
  again on each sync while it stays over the cap. The count and the warning
  make that visible.
- A refused file is accounted for, not missing: attachment completeness counts
  it alongside ready files, so the repair pass does not re-queue its submission
  on every run. Coders see the submission without that file.
- A refused row that already had a stored copy serves that older copy, not
  Central's newer over-cap version, until the newer one fits.
- A file removed from Central loses its refusal along with its
  `exists_on_odk` flag; the admin count covers only files Central still holds.
- Central self-heal checks the row first: a file already refused for size is a
  404 without contacting Central. When Central declares no length, the first
  over-cap view is cut off mid-stream (the response had already started); the
  refusal is recorded then, and later views take the 404 path.
- Every proxy in front of the app must allow the cap: the public reverse proxy
  and `deploy/doris-public-nginx.conf` set `client_max_body_size 55m`, or nginx
  answers a 20-50 MB upload with its own 413 before the app sees it.
