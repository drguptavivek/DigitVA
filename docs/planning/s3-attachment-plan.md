---
title: ODK Central S3 Attachment Integration Plan
doc_type: planning
status: proposed
owner: engineering
last_updated: 2026-09-16
---

# ODK Central S3 Attachment Integration Plan

## Decision Summary

ODK Central remains the source of truth and the only interface DigitVA uses to
retrieve original ODK attachments. Central may serve an attachment directly
from PostgreSQL or redirect the request to a short-lived S3 URL after the object
has moved to external storage. DigitVA must support both responses without
assuming that an S3 object already exists.

Human coders and reviewers must continue to see authorized images and play
authorized audio in the DigitVA interface. The S3 bucket remains private, and
DigitVA's existing opaque attachment route remains the authorization boundary.

## Goals

1. Store one canonical copy of each original ODK attachment under Central's
   management, using private S3-compatible storage when Central has moved it.
2. Preserve uninterrupted image and audio access for human coders, reviewers,
   data managers, and administrators with the appropriate scope.
3. Avoid permanent DigitVA copies of ordinary original images after a safe,
   reversible migration.
4. Retain DigitVA-owned derivatives where required, especially MP3 files made
   from AMR narration audio.
5. Preserve recovery, auditability, privacy, and backward compatibility during
   rollout.

## Non-Goals

- DigitVA will not read or derive meaning from Central's S3 object keys.
- DigitVA will not make the attachment bucket public.
- DigitVA will not store presigned URLs in the database.
- This plan does not change SmartVA scoring inputs. Medical/death-document
  images remain review material rather than SmartVA inputs.
- This plan does not immediately delete existing local attachment files.

## Target Architecture

### Original attachments

Original images, documents, audit media, and AMR files are owned by ODK
Central. DigitVA stores attachment identity and metadata, but retrieves the
binary through Central's attachment API.

```text
Coder browser
    |
    | GET /attachment/<opaque DigitVA token>
    v
DigitVA
    | 1. authenticate user
    | 2. authorize project/site/form/submission access
    | 3. request attachment from ODK Central
    v
ODK Central
    |-- attachment not moved yet --> streams bytes from PostgreSQL
    `-- attachment in S3 ---------> returns short-lived signed redirect
```

DigitVA must treat either successful Central response as source availability.
The absence of a known S3 location is not an error and must not mark an
attachment missing.

### Coder display path

The existing DigitVA URL must remain the entry point presented in HTML. For
each request, DigitVA must:

1. authenticate the current user;
2. look up the attachment using the opaque local token;
3. enforce current role, project, site, form, submission, and allocation rules;
4. request the exact attachment from the configured Central connection;
5. handle one of these outcomes:
   - Central returns `200`: stream/proxy the response to the browser;
   - Central returns an approved redirect: validate it, then redirect the
     browser to the short-lived signed URL;
   - Central returns not-found or unavailable: use the local fallback during
     migration and otherwise show a controlled unavailable state.

The application must never expose the ODK service credential to the browser.
Signed URLs must be short-lived, must not be persisted, and must not appear in
application logs. Redirect targets must use HTTPS and match an explicit
allowlist of expected S3 endpoint/bucket hosts to prevent open-redirect and
SSRF-style failures.

### Audio derivatives

Central remains authoritative for the original AMR file. Where browser playback
requires MP3:

1. DigitVA retrieves the AMR through Central, regardless of whether Central
   currently serves it from PostgreSQL or S3.
2. Conversion uses a bounded temporary file/stream and the existing SoX-based
   behavior.
3. DigitVA uploads the MP3 to a DigitVA-controlled private S3 prefix or separate
   bucket.
4. The database records the derivative object reference, source ETag/version,
   conversion status, and verification timestamp.
5. Temporary local material is removed only after upload and integrity checks
   succeed.

Ordinary images are not duplicated into the DigitVA derivative area. A future
thumbnail feature may use the same derivative pattern, but is outside this
phase.

## Storage and IAM Boundaries

Preferred layout:

| Storage area | Owner | Contents | DigitVA permission |
|---|---|---|---|
| ODK original-attachment bucket | ODK Central | Original attachments | No raw bucket credentials; read through Central |
| DigitVA derivative bucket/prefix | DigitVA | MP3 and any approved derivatives | Narrow read/write, no access to ODK originals |
| Backup bucket/prefix | Operations | Independent recovery copies | Backup/restore role only |

Separate buckets are preferred because policy, retention, access logging, and
recovery are easier to reason about. If one bucket is used, the three areas must
have separate prefixes, IAM policies, lifecycle rules, and encryption policy.
Bucket count is not the cost-saving mechanism; avoiding duplicate image objects
is.

The bucket must remain private, use encryption at rest, block public access,
and have access logging/CloudTrail coverage appropriate to the deployment.
Credentials belong in restricted runtime configuration, not Git. Central and
DigitVA should use separate IAM principals with least privilege.

## Data Model Plan

Use an additive migration. Existing rows and `local_path` values remain valid
during rollout.

Attachment records need enough information to resolve the source through
Central without storing an S3 key or signed URL:

- ODK connection/project/form identity;
- stable submission identity and original attachment filename;
- MIME type, size when available, and source ETag;
- source state such as `unknown`, `available`, `missing`, or `error`;
- last source verification time and last error category;
- local fallback state/path during migration;
- derivative state, object reference, source ETag, and verified time where
  applicable.

Exact columns should follow the existing attachment model's conventions after
implementation discovery. All timestamps must be timezone-aware. An attachment
must not be coupled to a guessed Central S3 key.

## Availability and Completeness Semantics

Current local-file checks must be replaced deliberately. The target meanings
are:

- **Source available:** Central can serve the attachment or issue an approved
  redirect. It does not mean that DigitVA has a local file.
- **Display ready:** an authorized browser request can obtain the original or
  required derivative.
- **Derivative ready:** the current derivative exists and corresponds to the
  current source ETag/version.
- **Repair needed:** Central reports the attachment missing, metadata is
  incomplete, or a required derivative is absent/stale.

Admin coverage, repair tasks, workflow handoffs, and KPI queries must adopt
these definitions together. A response served directly by Central before its
S3 migration is complete counts as available.

## Implementation Phases

### Phase 0 — Policy and inventory

1. Add `docs/policy/attachment-storage.md` as the implementation baseline.
2. Inventory attachment MIME types, sizes, AMR usage, legacy rows, and all local
   file existence checks.
3. Confirm the Central version and external-storage configuration requirements.
4. Record selected bucket/region, endpoint hostname allowlist, retention,
   encryption, versioning, and recovery objectives.
5. Decide the local fallback retention window; the recommended starting point
   is 30 days after verified cutover.

### Phase 1 — Enable and verify Central external storage

1. Configure Central with its private S3 credentials and bucket settings.
2. Apply least-privilege IAM and required Central frontend CORS settings.
3. Verify new and existing attachments through Central while objects are in
   both possible backing states: PostgreSQL-backed and S3-backed.
4. Confirm clients correctly follow Central redirects.
5. Record Central's migration status and failure telemetry. Do not require all
   existing objects to have moved before DigitVA integration begins.

### Phase 2 — Add source and derivative state

1. Add the migration and model fields required for remote source state and
   derivatives.
2. Backfill identity/metadata from existing rows without rewriting or deleting
   local files.
3. Add indexes for request-path lookups and repair candidate selection.
4. Make the migration safe to rerun and provide downgrade/rollback guidance.

### Phase 3 — Introduce an attachment resolver

Create a focused service that:

- resolves the correct Central connection and attachment endpoint;
- performs bounded-timeout, streamed requests;
- distinguishes Central `200`, approved redirect, not-found, authentication,
  throttling, and transient failures;
- validates redirect scheme and host;
- never logs credentials, signed query strings, or raw sensitive payloads;
- exposes a small result contract to the route, sync, repair, and derivative
  workers.

Keep authorization in the DigitVA route/service layer. Do not move permission
decisions into templates or rely on possession of a signed URL.

### Phase 4 — Dual-read coder rollout

1. Add a per-project/form feature flag for the remote-backed path.
2. After authorization, try Central first and retain existing local files as a
   fallback for controlled failure cases.
3. Record metrics for Central-streamed, Central-redirected, local-fallback,
   unavailable, latency, and expired-URL outcomes without logging PII or URLs.
4. Verify images, documents, and audio in coder, reviewer, and data-manager
   views.
5. Expand the flag gradually after operational review.

Local fallback is a migration safety mechanism, not the final source of truth.
It must not mask persistent Central or IAM failures indefinitely; fallback use
needs visible telemetry and alerts.

### Phase 5 — Change sync and repair behavior

1. Stop downloading permanent local copies of ordinary images for enabled
   forms.
2. Sync attachment lists and metadata through Central and verify source
   availability without assuming S3 placement.
3. Generate/reuse MP3 derivatives keyed to the current source ETag/version.
4. Update canonical repair, admin backfill, on-open repair, and KPI logic to use
   source availability plus derivative readiness.
5. Preserve idempotency: unchanged sources and valid derivatives cause no
   transfer or conversion.

### Phase 6 — Cutover and local-file retirement

1. Require a successful observation period with no unexplained local-fallback
   dependence.
2. Run a restore drill that combines the Central database/configuration and
   external attachment storage.
3. Move legacy local originals into a dated quarantine area; do not delete
   them during the initial cutover.
4. After the approved retention window and reconciliation, remove quarantined
   originals through a separately reviewed operational action.
5. Update laptop/server backup scope only after remote source and derivative
   recovery are verified.

## Failure and Rollback Strategy

- Disable the remote-backed feature flag for an affected project/form to return
  to the preserved local path during rollout.
- Keep schema changes additive; rollback does not require discarding metadata.
- If Central is available but S3 is degraded, Central's response is
  authoritative; DigitVA must not invent a direct bucket fallback for originals.
- If a signed URL expires, repeat the authorized DigitVA request and obtain a
  fresh response from Central.
- If an original is genuinely absent, retain an auditable unavailable/error
  state and queue bounded repair; never silently drop the field from the coder
  view.
- Rebuild missing derivatives from the original through Central.
- Do not delete local originals until the cutover and recovery gates pass.

## Security and Privacy Requirements

- Preserve all existing attachment authorization checks and test them against
  cross-project, cross-site, cross-form, and unallocated-submission access.
- Signed URLs must have the shortest practical lifetime, initially targeted at
  one to five minutes.
- Do not persist or log signed URLs, authorization headers, ODK credentials, S3
  credentials, or attachment payloads.
- Use bounded streaming; do not load large media into application memory.
- Validate MIME behavior and set safe content-disposition/content-type headers.
- Reject unexpected redirect hosts, non-HTTPS targets, redirect loops, and
  excessive redirect chains.
- Review browser referrer policy and cache headers so signed query strings are
  not leaked to unrelated origins.
- Permit only the required CORS origin, methods, headers, and exposed response
  headers. Audio playback may require `Range`/`Accept-Ranges` support.

## Backup and Recovery

ODK Direct Backup does not include attachments stored in external S3-compatible
storage. Enabling Central S3 therefore creates a separate recovery obligation.

Before cutover:

1. enable bucket versioning;
2. define lifecycle retention deliberately, without expiring current originals;
3. configure an independent backup or replication strategy appropriate to the
   recovery objective;
4. retain Central database, encryption keys, configuration, and exact software
   version needed for restore;
5. test restoration of database metadata and attachment objects together;
6. document restoration of DigitVA derivatives separately.

The primary Central bucket must not be treated as its own backup. If originals,
derivatives, and backup copies share one AWS account, protect backup deletion
with a distinct role and consider Object Lock where required.

## Verification Gates

### Automated tests

- authorization succeeds only for users currently entitled to the submission;
- Central `200` responses stream without buffering the entire object;
- approved S3 redirects pass and unexpected schemes/hosts are rejected;
- an attachment not yet moved to S3 still displays through Central;
- expired signed URLs are refreshed through a new authorized request;
- signed URLs and secrets are absent from logs and persisted records;
- conditional/ETag behavior is idempotent;
- missing objects, timeouts, throttling, redirect loops, and invalid MIME types
  produce controlled outcomes;
- AMR conversion generates a current MP3 derivative once and regenerates it
  when the source ETag changes;
- legacy `storage_name IS NULL` and existing local-path rows remain usable;
- repair and workflow advancement use the new completeness semantics.

### Integration tests

Use a mock Central service and S3-compatible test storage to cover:

- DB-backed Central streaming;
- Central-to-S3 redirects;
- CORS and browser image display;
- audio byte-range requests;
- Central or S3 outage;
- concurrent coder requests;
- large-file streaming and bounded memory use.

### User and operational verification

- coders can view multiple and large images on assigned submissions;
- reviewers and data managers retain their correct scoped access;
- copied signed URLs expire and do not grant durable access;
- revoking allocation prevents creation of a new authorized attachment URL;
- browser refresh/back behavior and audio seeking work;
- dashboards distinguish unavailable source from missing derivative;
- backup/restore drill successfully reconstructs a sample submission and its
  attachments.

## Performance Constraints

- Avoid one Central authentication handshake per attachment; reuse the existing
  connection/session safely.
- Avoid N+1 database queries when rendering a page containing multiple media
  items.
- Do not prefetch binaries merely to render attachment links.
- If a short server-side locator cache is introduced, it must be bounded by the
  signed URL expiry and must not weaken authorization or persist URLs.
- Measure page latency and Central request volume before deciding whether
  batching or proxy caching is necessary.

## Expected Repository Scope

Implementation discovery should confirm exact names, but expected areas are:

| Area | Expected change |
|---|---|
| `docs/policy/attachment-storage.md` | Policy baseline |
| `docs/current-state/odk-sync.md` | New source/completeness behavior |
| `docs/current-state/odk-repair-workflow.md` | Remote-aware repair semantics |
| `docs/current-state/runtime-and-operations.md` | S3, IAM, monitoring, and recovery |
| `app/models/va_submission_attachments.py` | Additive source/derivative state |
| `migrations/` | Additive migration and indexes |
| `app/utils/va_odk/va_odk_07_syncattachments.py` | Metadata-first sync and derivative trigger |
| ODK client/service layer | Central retrieval and safe redirect handling |
| `app/routes/va_form.py` | Authorized attachment delivery |
| `app/utils/va_render/va_render_06_processcategorydata.py` | Render based on records, not local-file existence |
| `app/services/open_submission_repair_service.py` | Remote-aware completeness/repair |
| `app/tasks/sync_tasks.py` | Bounded derivative/repair work |
| `app/routes/admin.py` and KPI services | Revised availability telemetry |
| focused unit/integration/browser tests | Security, behavior, and rollout gates |

## Decisions to Confirm Before Implementation

Recommended defaults are included so implementation can proceed after review:

1. **Browser delivery:** validated redirect for Central's signed S3 response;
   streaming proxy when Central itself returns bytes.
2. **Storage isolation:** separate ODK-original, DigitVA-derivative, and backup
   buckets; strict prefixes and IAM if one bucket is operationally required.
3. **Local fallback:** retain for the staged rollout, then quarantine for 30 days
   after verified cutover.
4. **Audio:** retain original AMR under Central and store an MP3 derivative under
   DigitVA control.
5. **Source health:** evaluate through Central, never by probing or guessing an
   S3 object key.

## Completion Criteria

The migration is complete only when:

- authorized human coders can reliably see all required images and play audio;
- both Central DB-backed and S3-redirected attachments have passed tests;
- ordinary original images are no longer permanently duplicated by DigitVA;
- required derivatives are reproducible and independently recoverable;
- remote-aware repair and dashboard semantics are deployed;
- a combined Central database/configuration/S3 restore drill has succeeded;
- local originals have completed the approved quarantine period; and
- documentation, monitoring, and operational runbooks reflect the deployed
  behavior.
