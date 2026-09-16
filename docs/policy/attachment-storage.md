---
title: Attachment Storage and Delivery Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-17
---

# Attachment Storage and Delivery Policy

This is the implementation baseline for submission attachments (images,
documents, audit media, narration audio). It governs who may receive an
attachment, how presence is decided, how bytes are delivered, and what a
failed derivative looks like. The migration that this baseline prepares for is
described in [the Central S3 attachment plan](../planning/s3-attachment-plan.md).

## Source of truth

- ODK Central is the source of truth for original attachment content.
- DigitVA stores attachment identity and metadata in
  `va_submission_attachments`; today it also stores a local copy under
  `APP_DATA/<form_id>/media/` and, for `.amr` narration, an MP3 derivative in
  place of the original.
- The opaque `storage_name` token is an **identifier, never a capability**.
  Legacy backfilled tokens are deterministically derivable from `va_sid` and
  filename, so possession of a token grants nothing on its own.

## Module boundary

All attachment decisions live in
[`app/services/attachment_service.py`](../../app/services/attachment_service.py):

| Concern | Function |
|---|---|
| Resolve a token to its owning submission | `resolve_attachment_record()` |
| Authorization matrix | `can_access_submission_attachment()` |
| Local presence for one row | `resolve_local_attachment_path()` |
| Bulk presence per submission (repair, admin telemetry) | `present_attachment_files_by_submission()` |
| Visibility check without submission identity | `is_attachment_present_for_form()` |
| Filesystem inventory for the integrity script | `scan_local_media_files()` |
| Delivery with path guard and cache policy | `deliver_local_attachment()` |

Rules:

- No module outside the attachment service performs a filesystem existence
  check for an attachment. Routes, render code, sync tasks, admin telemetry,
  and `scripts/check_attachment_integrity.py` call the service.
- Callers learn nothing about where bytes live. Replacing the local-disk
  implementation with Central-backed delivery is a change to this module's
  internals, not to its callers.
- The serving-route cache (`att:<storage_name>`, 3600 s) holds the attachment
  **record** — ownership, path, MIME — never a locator that can expire, and
  never an authorization decision. Cache entries lacking ownership are treated
  as misses.

## Authorization matrix

Both attachment routes (`/vaform/attachment/<storage_name>` and the deprecated
`/vaform/media/<form_id>/<filename>`) apply the same matrix, evaluated fresh on
every request after `@role_required` has established authentication, active
status, and role. Ownership (`va_sid`, `va_form_id`) must resolve first; an
unknown attachment is `404`, never served by filename.

| Role | Rule |
|---|---|
| `admin` (global grant) | Allowed. |
| `data_manager` | Allowed when the form is within the data-manager project or project-site scope. |
| `site_pi` | Allowed when the form is within the site-PI project-site scope. |
| `reviewer` | Allowed when the form is within the reviewer scope. Reviewer section views are read-only per form (the reviewer `vaview` validator requires form access only), so attachment delivery follows the same scope rather than an allocation. |
| `coder` / `coding_tester` | Allowed only for a submission the user **holds**: an active allocation to that user, or the user's own active coder outcome (`va_final_assessments` or `va_coder_review`). This mirrors the coder `vaview` rule in `va_permission_ensureviewable`. Form-level coder access alone is refused. |
| `project_pi` | No submission-view surface exists for this role; attachment delivery is refused unless another scope above applies. |
| Legacy `permission` dict | Keys other than `coder`, `reviewer`, `sitepi` grant access to the listed forms, matching `VaUsers.has_va_form_access`. The scoped keys are ignored here because their grants are evaluated through access grants. |

The decision is never cached, never inferred from a token, and never moved
into templates. Denials are logged with user id, submission id, and form id;
tokens, paths, and payloads are not logged.

Tests: [`tests/routes/test_serve_attachment.py`](../../tests/routes/test_serve_attachment.py),
[`tests/services/test_attachment_service.py`](../../tests/services/test_attachment_service.py).

## Delivery

- Attachment responses carry `Cache-Control: private, no-store, max-age=0`
  and `X-Content-Type-Options: nosniff`. PHI image and audio bytes must not be
  written to the browser disk cache, consistent with the `no-store` policy on
  the partials that reference them.
- Delivery stays under `APP_DATA/<form_id>/media/`; a path outside it or a
  missing file is `404`, and a missing file evicts the record cache.
- The stored `mime_type` is copied from upstream and is not authoritative. A
  missing, malformed, or literal `"null"` value is discarded and the type is
  derived from the storage name. Sync applies the same validation before
  writing the row.

## Presence and completeness

Presence for a row resolves in this order and is the single definition used by
repair maps, admin backfill telemetry, and the integrity script:

1. `APP_DATA/<form_id>/media/<storage_name>` when `storage_name` is set;
2. the legacy `local_path` otherwise;
3. `audit.csv` never counts as an attachment blob unless the caller asks for
   it explicitly (admin telemetry reports it separately).

Category visibility checks that run without a submission identity use the
form-level presence check; `.amr` fields are visible when the `.mp3`
derivative is present. These semantics are unchanged by the module extraction
and are the disk-backed baseline that the Central-backed implementation must
redefine deliberately (see the plan's **Availability and Completeness
Semantics**).

## Audio derivatives

- `.amr` narration is converted to MP3 with SoX at sync time and the MP3 is
  stored under the opaque storage name.
- A failed conversion is an explicit error: `_convert_amr_to_mp3` raises
  `AmrConversionError`, no partial `.mp3` is kept, the temporary source is
  removed by the caller, the attachment is counted as a sync error, and the
  existing row is left untouched. A failed conversion is never recorded as a
  `.mp3` storage name pointing at a non-MP3 blob.
- Conversion is retried by ordinary attachment repair because the row remains
  incomplete.

## Non-goals of this baseline

- No Central or S3 retrieval, redirect handling, or remote source state yet.
- No image derivatives or stored thumbnails.
- No change to the deprecated `/media` route beyond ownership resolution, the
  shared matrix, and the cache policy.
