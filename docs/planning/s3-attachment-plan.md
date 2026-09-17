---
title: ODK Central S3 Attachment Integration Plan
doc_type: planning
status: proposed
owner: engineering
last_updated: 2026-09-17
---

# ODK Central S3 Attachment Integration Plan

## Decision Summary

ODK Central remains the source of truth and the only interface DigitVA uses to
retrieve original ODK attachments. Central may serve an attachment directly
from PostgreSQL or redirect the request to a short-lived S3 URL after the object
has moved to external storage. DigitVA must support both responses without
assuming that an S3 object already exists.

Support both deployment modes as first-class configurations: Central without
external storage (database-backed originals) and Central with S3-compatible
storage (potentially mixed database/S3 backing during offloading). Enabling S3
on Central is optional, not a prerequisite for DigitVA's attachment service.
Resolve each response at request time; do not infer backing storage from a
global deployment flag. DigitVA's own MP3 storage configuration is independent
of whether Central uses S3 for originals.

Central's default offload job runs every 24 hours. Therefore even an S3-enabled
deployment routinely serves newer attachments from PostgreSQL while older ones
redirect to S3; failed offloads remain database-backed. The same attachment may
return `200` today and `307` after the next job, without a filename or content
change. Both outcomes must remain supported throughout normal operation, not
just during an initial migration. No per-attachment backend flag or completion
gate may assume that enabling S3 means all originals are already offloaded.
See [Central's documented offload schedule and failure handling](https://docs.getodk.org/central-install-digital-ocean/#using-s3-compatible-storage).

Human coders and reviewers must continue to see authorized images and play
authorized audio in the DigitVA interface. The S3 bucket remains private, and
DigitVA's existing opaque attachment route remains the authorization boundary.

Central documents the requirement to follow redirects in its
[S3 setup guide](https://docs.getodk.org/central-install-digital-ocean/#using-s3-compatible-storage).
Exact status codes and signing details were verified against source. See
**Central API Verification** before relying on any statement in this plan about
status codes, ETag handling, or signed-URL lifetime.

## Implementation Status

Updated 2026-09-17. Policy baseline:
[Attachment Storage and Delivery Policy](../policy/attachment-storage.md).

| Item | Status | Notes |
|---|---|---|
| Phase 0.1 — submission-level authorization (Finding 1) | Done | `can_access_submission_attachment()` in `app/services/attachment_service.py`; both routes; matrix tests in `tests/routes/test_serve_attachment.py`. Reviewer access is form-scoped to match the read-only reviewer section view (commit 5beaaf1); coder access requires an allocation or the coder's own outcome. |
| Phase 0.2 — policy doc | Done | `docs/policy/attachment-storage.md` |
| Finding 5 — AMR failure state | Done | `AmrConversionError`; no partial output, no row change |
| Finding 9 — literal `"null"` MIME | Done | `safe_mime_type()` at sync and delivery |
| Finding 11 — `no-store` on attachment bytes | Done | `apply_no_store_policy()` on both routes |
| Phase 3 — `AttachmentService` extraction | Done | All six Finding 2 call sites converge on the service; admin duplicate deleted; render sentinel decided by the service. `readiness()` is currently `present_attachment_files_by_submission()`; the richer state vocabulary arrives with Phase 2 columns. |
| Phase 0.4 — Central version record | Done | One mapped connection (`MINERVA`, minerva.causeofdeathindia.com): Central server `v2026.2.2`, frontend `v2026.2.4` (recorded 2026-09-17). Post-`v2026.1` line, so JPEG/PNG/GIF are `Content-Disposition: inline`; above the `v2024.2.0` S3 floor. Storage mode (database-only vs S3) still to confirm. |
| Deployment mode | Decided 2026-09-17 | **Central without S3.** Originals stay in Central's PostgreSQL; MP3 derivatives stay under DigitVA `APP_DATA`. Bucket/IAM/retention/recovery-drill gates (Phase 0.5, 0.7, Phase 1 S3 steps, Phase 6 bucket restore) do not apply. The resolver still handles a Central `307` so S3 can be enabled on Central later without a DigitVA change. |
| Retired submissions | Decided 2026-09-17 | Source state `retired`; their attachments are **never deleted** ([policy](../policy/odk-retired-submissions.md)). They *are* uploaded into the DigitVA S3 store — that object is the archive — and the quarantine of their now-redundant local file is opt-in (`--include-retained`). |
| Phase 2 — source/derivative state | Done | Migration `b7e4c2a91d38`: additive `source_*`, `derivative_*`, `local_fallback_state` columns on `va_submission_attachments`, backfilled from `exists_on_odk`/AMR rows/retired submissions. Sync writes them; `readiness()` and `mark_audio_derivative_stale()` exist in the service. Nothing decides on the state until Phase 4. |
| Storage direction | Decided 2026-09-17 | **DigitVA-owned store, two copies.** DigitVA keeps its own permanent copy of every attachment — originals and MP3 derivatives — and serves from it; Central keeps its own copy and stays the source of truth for existence/content but is not the primary read path. The DigitVA store is local files under `APP_DATA` today and a DigitVA-owned bucket next phase. This supersedes the "proxy Central on every request" framing in **Delivery Design → Transport** and the Goal 3 aim of avoiding permanent DigitVA copies of ordinary images; Central is now the *ingest and repair* path, not the read path. |
| Phase 4a — Central-backed source and store-first delivery | Done | Migration `c9a4e17b0f52`: `va_project_master.attachment_central_fetch_enabled` (default false), the per-project switch for self-healing a store miss from Central. `app/services/attachment_source_central.py` resolves the owning connection (fail-closed), fetches with `allow_redirects=False`, bounded timeouts and a request-path `guarded_odk_call` policy, classifies the response, and records `source_*` state. `attachment_service.deliver()` reads DigitVA's store first through `_store_exists`/`_store_open`/`_store_write` and tees a Central fetch into the store. Flag surfaces: `flask attachments central-fetch`, `PUT /admin/api/projects/<id>/attachment-central-fetch`, admin Projects panel. Server side only. |
| DigitVA S3 store | Done | Migration `a4f1c07b62d9`: `va_submission_attachments.store_state` (`local`/`s3`/`absent`, default `local`, indexed). `app/services/attachment_store.py` holds the backend interface (`key_for`/`exists`/`open_local_path`/`put`/`presigned_url`/`delete`) with a local and an S3 implementation, selected once from `ATTACHMENT_STORE` and validated fail-closed at startup. Delivery serves a store hit as a `302` to a 5-minute presigned GET with the response type, disposition and cache policy fixed inside the signature; the redirect itself is `no-store`. Sync and the Central self-heal tee upload through a bounded temp file and leave `local_path` NULL. `boto3` added; tests run against `moto`. |
| Attachment management — service owns the lifecycle | Done | `attachment_service` is now a deep module over the whole lifecycle, not just serving. Ingest moved in (`new_ingest_temp_path()`, `ingest_download()` — AMR→MP3 conversion, store write, `storage_name`, readiness state, temp cleanup on every path —, `mark_removed_on_odk()`, `attachment_present()`, `cleanup_superseded()`); repair moved in (`repair_attachment()`, `repair_candidates()`); completeness moved in (`attachment_state_by_submission()`); the operator surface added (`attachment_management_overview()`, `local_integrity_check()`/`s3_integrity_check()`/`integrity_check_summary()`); and the CLI/cutover/integrity script are now thin wrappers (`s3_upload_backlog()`, `quarantine_local_copies()`, `set_project_central_fetch()`). `va_odk_07_syncattachments.py` is left with listing, the conditional GET, the temp write and the DB apply — no `os`/`subprocess`/`tempfile`/`pathlib` import, no media directory, no store call, enforced by `tests/test_sync_attachments_boundary.py`. |
| Attachment Management admin panel | Done | `/admin/panels/attachments`; `GET /admin/api/attachments/overview` (+`?project_id=`), `POST /admin/api/attachments/forms/<form_id>/repair` (returns the run id), `POST /admin/api/attachments/integrity-check`; the per-project Central-fetch switch reuses `PUT /admin/api/projects/<id>/attachment-central-fetch`. Admin-only, CSRF, counts only. CLI mirror: `flask attachments overview`. |
| Request-path retry hygiene (deferred from Phase 4a) | Done | A request-path fetch goes through a no-retry clone of the connection's session (`HTTPAdapter(max_retries=0)`), so a `503` is classified after one attempt instead of ~14 s of pyODK backoff. The shared session sync relies on is never mutated. |
| Phase 4b — frontend | Open | Preview tier, bounded client byte cache, lightbox hydration. |
| Phase 5 | Partly done | Done: derivative rebuild from the original through Central (`repair_attachment()` on a `pending`/`stale`/`error` MP3), and readiness-based completeness for canonical repair, on-open repair and the admin backfill map (plan Finding 4 plus the retired-submission rule). Still open: stopping the download of ordinary images for enabled forms (item 1), verifying source availability from Central's list without a download (item 2), and MP3 idempotency through a conditional GET at the final content endpoint (items 3 and 5 — Finding 6). Item 6 (no background image freshness probes) holds by construction. |
| Phase 6 — cutover | Ready | Rewritten below as the `s3-upload` / `local-quarantine` pair. Tools exist and are tested; the operational run has not happened. |
| `admin_sync_legacy_attachment_stats` per-row uuid5 scan | Open | Noted under **Performance Constraints**; not touched |

**Queued after the S3 store (agreed 2026-09-17), in order:** (1) attachment
management — ingest, repair and retirement pulled into the service, admin
panel; (2) SmartVA run archival to S3 (`smartva_runs/` prefix); (3) DB dumps to
S3 (`db-backups/` prefix, own IAM statement); (4) exports to S3. Goal: after
these, the only stateful thing on the VM is the Postgres volume.

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

### Connection and project/form/site scope

Resolve the owning submission and local form first, then that form's project,
site, mapped ODK connection, `odk_project_id`, and `odk_form_id`. Never use a
global/default Central connection just because an attachment token resolves.
The current schema maps connection credentials at project level through
[MapProjectOdk](../../app/models/map_project_odk.py#L8); the local
[VaForms record](../../app/models/va_forms.py#L9) supplies site and remote
project/form identity. Multiple projects may share a
[connection](../../app/models/mas_odk_connections.py#L9). Preserve this routing
model; this plan does not add a separate site-level credential schema.

Central version, storage mode, redirect allowlist, session pool, pacing, and
health belong to the resolved connection. Rollout flags remain scoped to the
owning local project/form/site context. Two connections can simultaneously use
database-only and S3-backed Central, or different Central versions. Even on
one S3-enabled connection, each content request can take either backing path.

Namespace source identity and audio validators by connection, remote project,
remote form, submission, and attachment name; include local ownership and
variant in caches. Resolve project/site/form authorization independently of
remote identifiers, which may collide across servers. A mapping change must
invalidate cached resolution and affected audio derivative freshness before
reuse. Do not silently remap existing attachment ownership or reuse validators
from the previous source.

The existing [client setup](../../app/utils/va_odk/va_odk_01_clientsetup.py#L18)
has a legacy TOML fallback. Phase 0 must inventory legacy-only projects and
explicitly bind/validate their connection before enabling the new remote path;
retain their existing local delivery until then. The new service must fail
closed on absent, inactive, or ambiguous mapped connections rather than contact
an unrelated default server. This does not change unrelated legacy sync paths.

### Authorized delivery

The existing DigitVA URL must remain the entry point presented in HTML. For
each request, DigitVA must:

1. authenticate the current user;
2. look up the attachment using the opaque local token;
3. enforce current role, project, site, form, submission, and allocation rules;
4. request the exact attachment from the configured Central connection;
5. handle one of these outcomes:
   - Central returns `200`: stream/proxy the response to the browser;
   - Central returns an approved redirect (`307`): validate scheme and host,
     then stream the signed URL's bytes to the browser. The browser is not sent
     to S3 — see **Finding 10** for why;
   - Central returns not-found: show a controlled unavailable state;
   - Central has a transient failure: allow migration fallback only under the
     explicit outcome table in Phase 4.

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
4. The database records the derivative object reference, source content validator,
   conversion status, and verification timestamp.
5. Temporary local material is removed only after upload and integrity checks
   succeed.

Ordinary images are not duplicated into the DigitVA derivative area, and
thumbnails are **not** a derivative: they are generated on the fly and discarded.
See **Delivery Design** for the access-pattern reasoning and for why audio is the
only stored derivative.

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
- validated MIME type and size when available. The existing `mime_type` column
  is copied from upstream and is not independently authoritative: reject a
  literal `"null"` value and record the MP3 derivative's output MIME type
  separately from the original AMR type (Finding 9);
- source state such as `unknown`, `available`, `missing`, or `error`;
- last source verification time and last error category;
- local fallback state/path during migration;
- derivative state, object reference, source content identifier, and verified
  time — **for audio only**. Thumbnails are generated per request and persist no
  state (see **Delivery Design**), so no image derivative columns are added.
  Derivative state must be able to record an explicit failure so a failed AMR
  conversion is distinguishable from a successful one (Finding 5), rather than
  being written as a mismatched `local_path`/`storage_name` pair.

Persist source validators only where needed for stored MP3 freshness. Use the
ETag supplied by the final content response, whether Central or S3, as an opaque
validator (Finding 6). Images require identity and availability metadata, but
no persistent content-version tracking or scheduled ETag probes.

For audio validators, record the validator's backing context (Central database
or approved object-store endpoint) so values are not assumed interchangeable.
On a backing transition, safely retrieve/revalidate the source and refresh the
MP3 if necessary; an occasional extra conversion is acceptable. Do not infer a
content change solely from movement to S3 or decode an S3 key as an identifier.

Exact columns should follow the existing attachment model's conventions after
implementation discovery. All timestamps must be timezone-aware. An attachment
must not be coupled to a guessed Central S3 key.

## Availability and Completeness Semantics

Current local-file checks must be replaced deliberately. The target meanings
are:

- **Source available:** a successful content response was observed through
  Central, including its approved S3 destination. A signed redirect alone proves
  resolution, not that the destination object can be read. Listing availability
  and the time/outcome of the last observed delivery must remain distinguishable;
  no background image probes are required.
- **Display ready:** an authorized browser request can obtain the original or
  required derivative.
- **Derivative ready:** the current derivative exists and corresponds to the
  current audio source content validator.
- **Repair needed:** Central reports the attachment missing, metadata is
  incomplete, or a required derivative is absent/stale.

Admin coverage, repair tasks, workflow handoffs, and KPI queries must adopt
these definitions together. A response served directly by Central before its
S3 migration is complete counts as available.

Adopting them together is not optional. `attachments_complete` in
`app/tasks/sync_tasks.py:865-869` still counts files on disk and feeds
`WORKFLOW_ATTACHMENT_SYNC_PENDING`; if it is not changed in the same change as
the new semantics, submissions whose expected attachments lack local copies
can incorrectly acquire `needs_attachments=True`. See Finding 4.

## Current-Code Findings

These were confirmed by reading the live attachment path and they change the
sequencing below. They are recorded here so the plan is not re-derived later.

### Finding 1 — the opaque attachment route is weaker than the route it replaced

`serve_attachment` (`app/routes/va_form.py:1335`) authorizes with a single
form-level check, `current_user.has_va_form_access(va_form_id)`
(`app/models/va_users.py:252`). The deprecated `serve_media` it supersedes does
strictly more: it resolves the attachment to its `va_sid` and requires an active
allocation for coder and reviewer roles (`app/routes/va_form.py:1420-1455`,
marked `OW-002`).

A coder with form access can therefore retrieve attachments for submissions they
were never allocated, if they hold the token. New tokens are `uuid4`
(`app/utils/va_odk/va_odk_07_syncattachments.py:51`) and are not guessable, but
tokens written by the legacy backfill are
`uuid5(RFC-4122 DNS namespace, f"{va_sid}:{filename}")`
(`app/services/attachment_storage_name_service.py:12`) — derivable from two
values a coder already sees. `app/routes/admin.py:5761` counts rows matching that
deterministic value, so such rows are expected to exist.

`tests/routes/test_serve_attachment.py` already contains seven route tests for
authentication, token validation, record/file presence, form access, and delivery.
Submission-allocation coverage is missing; several existing tests mock form
access. Extend this suite rather than treating the route as untested.

This is a live gap independent of S3, and it becomes materially worse once the
response is a shareable signed URL. It is fixed in Phase 0, not during rollout.

### Finding 2 — attachment availability is re-derived from disk in six places

The same "does this attachment exist" rule is implemented independently at:

| Location | Current mechanism |
|---|---|
| `app/routes/va_form.py:1391` | `os.path.isfile` |
| `app/utils/va_render/va_render_06_processcategorydata.py:160` | `os.path.exists` in the `va_sid=None` branch |
| `app/tasks/sync_tasks.py:59` | `_resolve_present_attachment_file_path` |
| `app/routes/admin.py:5340` | `resolve_attachment_file_path` — a near-verbatim duplicate of the above |
| `app/utils/va_odk/va_odk_07_syncattachments.py:196` | `os.path.exists` gating 304 self-heal |
| `scripts/check_attachment_integrity.py` | independent check |

This plan redefines that rule. Introducing a resolver alongside these copies
leaves five shallow implementations of a definition that must change together.
Phase 3 therefore converges them first, before Central is involved.

### Finding 3 — the client already follows Central's redirect

`client.session.get(...)` in `app/utils/va_odk/va_odk_07_syncattachments.py:184`
relies on the `requests` default `allow_redirects=True`. Central's S3 redirect
will be followed transparently and no `3xx` will ever be observed, so redirect
validation and browser-redirect delivery require an explicit
`allow_redirects=False` plus caller-side host validation. `Session.rebuild_auth`
does strip `Authorization` across hosts, so a followed redirect does not leak the
ODK credential.

Turning redirects off is not sufficient on its own: Central also issues a
non-S3 `redirect(301)` to the canonical submission-version URL for deprecated
instance IDs (`lib/resources/submissions.js:450-462`). The resolver must
distinguish "redirect back to Central, follow it" from "redirect to S3, hand it
to the browser" rather than treating every `3xx` as an S3 handoff. See
**Central API Verification**.

### Finding 4 — completeness flips to incomplete at cutover

`attachments_complete` (`app/tasks/sync_tasks.py:865-869`) is
`present_count >= AttachmentsExpected and legacy_rows == 0`, where
`present_count` counts files on disk. When Phase 5 stops downloading ordinary
images, new remote-only attachments no longer contribute to `present_count`.
Affected submissions can acquire `needs_attachments=True`, and that drives
`WORKFLOW_ATTACHMENT_SYNC_PENDING`
(`app/services/open_submission_repair_service.py:62-70`). This is the single
highest-risk edit of the cutover and must land in the same change as the new
semantics.

Retained local files and submissions expecting zero attachments are exceptions;
the cutover does not make every submission incomplete immediately.

### Finding 5 — the AMR conversion failure path writes a corrupt row

`_convert_amr_to_mp3` returns the *source* path on failure
(`app/utils/va_odk/va_odk_07_syncattachments.py:698`) while the caller sets
`tmp_path = None` immediately afterwards, so the `finally` cleanup is skipped.
The result is a `.tmp_<uuid>` AMR blob recorded as `local_path` against a `.mp3`
`storage_name`: wrong extension, never cleaned up, and indistinguishable from a
successful conversion. Under this plan that must become an explicit derivative
error state.

## Central API Verification

The [attachment API reference](https://docs.getodk.org/central-api-submission-management/#downloading-an-attachment) documents
the attachment download endpoint as returning `200` with `ETag` support and
`304` on `If-None-Match`, and says nothing about S3 or redirects. The
`central-api-changelog` records `ETag headers on all Blobs` (v2024.1) and the
`Content-Disposition: inline` change for images (v2026.1), but has no S3 entry.

The [official S3 setup guide](https://docs.getodk.org/central-install-digital-ocean/#using-s3-compatible-storage)
does document redirects, Central frontend CORS, daily offloading, and the lack
of an automated migration back to PostgreSQL. Exact redirect status, signing
lifetime, and conditional handling below were read from versioned source; pin
the deployed version and reverify those details on upgrade.

### Versions verified

| Fact | Value |
|---|---|
| Latest Central release at time of writing | `v2026.3.0`, published 2026-09-11 |
| External S3 blob storage first available | `v2024.2.0` (`lib/external/s3.js` does not exist at `v2024.1.0`) |
| Minimum version for Central external S3 storage | `v2024.2.0`; not a new requirement for database-only delivery |
| Deployed line for this project | Reported as 2025.x; not verified against the live deployment in this review |

The `307`-plus-skip-ETag behaviour and the 60-second expiry were read at
`v2024.2.0`, `v2025.1.0` and `v2026.3.0` and are **identical in all three** — the
contract has not changed since S3 support landed. It is undocumented but stable,
which lowers but does not remove the upgrade risk.

### Finding 10 — the 2025 line forces `Content-Disposition: attachment` on both branches

**The deployment this plan targets is on the 2025 line.** On that line the
`disposition` argument does not exist at all: `getRespHeaders` calls
`contentDisposition(filename)` with no type (`lib/external/s3.js:120` at
`v2025.1.0`), and the DB-backed branch sets the same header directly in
`lib/util/blob.js`. Every attachment Central serves is therefore
`Content-Disposition: attachment`, whether it comes from PostgreSQL or from S3.
Verified identical at `v2025.1.0`, `v2025.2.1`, `v2025.3.0` and `v2025.4.2`.

The `disposition` parameter is introduced in `v2026.1.0`, where JPEG, PNG, and
GIF submission attachments become `inline`; this is not all image MIME types.
See [the versioned implementation](https://github.com/getodk/central-backend/blob/v2026.1.0/lib/util/blob.js#L48).

This does **not** affect rendering: `<img>` and `<audio>` ignore
`Content-Disposition` on subresource loads, which is all DigitVA's templates
perform. It affects top-level navigation only — on the 2025 line, opening an
image in a new tab downloads it instead of displaying it.

### Consequence: proxy by default, redirect as a later optimisation

Supporting both the 2025 line and `v2026.1+` from one code path is
straightforward if DigitVA streams the bytes rather than redirecting. Proxying
lets DigitVA set `Content-Type` from validated original/derivative metadata and
`Content-Disposition` to its own choice, which:

- makes delivery behaviour **identical on every Central version**, removing
  version branching from the request path entirely;
- neutralises the 60-second expiry (Finding 7) for the browser;
- corrects a literal `"null"` content type (Finding 9);
- fixes new-tab download behaviour on the 2025 line without waiting for an
  upgrade.

The cost is bandwidth and worker occupancy on the DigitVA app server, which must
be measured rather than assumed — see **Performance Constraints**.

Browser redirects are outside this implementation. They require a separate
design review of cross-origin fetch, CORS, cache policy, MIME handling, and
expiry; upgrading Central alone does not make them an invisible service switch.

Either way the resolver must accept **both** a `200` and a `307` from Central for
the same attachment, since Central's migration cron moves blobs asynchronously
and DigitVA cannot know which branch will answer.

### Finding 11 — attachment bytes lack an explicit no-store policy

`_apply_partial_cache_policy` (`app/routes/va_form.py:90-98`) sets
`Cache-Control: private, no-store, max-age=0` for the media-bearing partials —
`_response_contains_user_specific_artifacts` (`:85-87`) matches exactly
`vanarrationanddocuments` and `social_autopsy`. Other partials get
`private, max-age=300`, annotated "PHI data".

`serve_attachment` sets no explicit no-store policy: `send_file`
(`app/routes/va_form.py:1401`) falls through to the Flask default. The partial is
therefore `no-store` while the PHI image and audio bytes it references may be
written to the browser's disk cache. This is an existing inconsistency,
independent of S3, and it must be resolved before any caching design is layered
on top of it.

## Delivery Design

This supersedes the earlier framing in **Decisions to Confirm** item 1.

### Transport: proxy, not redirect

DigitVA streams attachment bytes for both Central outcomes — the `200` body and
the `307` target alike. Rationale in Finding 10: it removes Central-version
branching from the request path, lets DigitVA set validated `Content-Type`
and choose its own `Content-Disposition`, and keeps the
browser away from a 60-second expiry it cannot control.

The service always proxies in this plan. Future browser redirects would change
the client contract and require their own review and verification.

### Cache policy: `no-store`, with the cache in memory

Attachment responses carry `Cache-Control: private, no-store`, extending the
existing stance on the partials that reference them (Finding 11). PHI image and
audio bytes must not reach the browser's disk cache.

Caching for responsiveness therefore happens in JavaScript memory, not in the
HTTP cache:

- fetch is **same-origin** against DigitVA's own route, so no S3 bucket CORS is
  required — see Finding 8. A design where JavaScript fetches S3 directly *would*
  require CORS on a bucket DigitVA does not own, and is rejected;
- cached objects are **bytes, never locators**. This design does not cache
  signed URLs; every new DigitVA content request resolves Central server-side;
- the cache is a **bounded LRU with an explicit byte budget**, not a TTL map. A
  submission may carry up to 35 images — `md_im1`–`md_im30` plus `ds_im1`–`ds_im5`
  (`app/utils/va_render/va_render_06_processcategorydata.py:14-18`) — so an
  unbounded blob cache is a browser memory failure, not a theoretical one;
- object URLs are revoked on eviction;
- a five-minute working window is the target, chosen to absorb the repeats that
  actually occur: HTMX partial swaps, back navigation, and reopening the gallery
  within one coding session.

Cache keys include user/session, submission, attachment token, and preview/full
variant. Clear bytes, revoke object URLs, detach media, and cancel pending
fetches on logout, account/session change, submission change, or an observed
authorization failure/revocation. Prevent a late response from repopulating a
cleared cache. Bound reuse to five minutes since the last successful server
authorization, then require reauthorization before further cached reuse. This
permits up to five minutes of unobserved revocation delay; it cannot retract
bytes already delivered or user-saved copies. Cache expiry is an authorization
boundary, not a background image-content freshness check.

Use `no-store` for HTTP responses and do not persist attachment bytes in Cache
Storage, IndexedDB, or service-worker caches. Verify supported browser HTTP-cache
behaviour; do not describe this as a guarantee against OS swap or user downloads.

### Two tiers, and the rule that separates them

| Tier | Content | Cached | Used by |
|---|---|---|---|
| Preview | Server-downscaled | Yes, bounded | Gallery and 60px carousel thumbnails |
| Full | Original bytes, unmodified | One or two deep, evicted hard | Lightbox, zoom, rotate |

**Anything a coder can zoom into must be the original.** The lightbox exposes
zoom (`app/templates/va_formcategory_partials/category_attachments.html:91-96`)
and rotate (`:83-88`), and these images are medical certificates and death
documents read to assign an ICD code. Compression artefacts on handwritten text
are a clinical accuracy risk that no test in this plan would detect. Downscaled
or re-encoded bytes must never reach the zoom path.

Note also that DigitVA carries its own rotation state per `rotationKey`
(`:157-159`). Any server-side image handling must preserve or normalise EXIF
orientation deliberately rather than letting the two rotate independently.

### Thumbnails: generated on the fly, never stored

Thumbnails are generated per request and discarded. They are **not** a stored
derivative, and the line in **Audio derivatives** deferring a future thumbnail
feature to "the same derivative pattern" is explicitly rejected.

The access pattern decides this. A submission is coded once and reviewed or
recoded at most a few times, so a stored thumbnail would be written once, read
one to three times, and retained indefinitely. That buys a handful of reads in
exchange for the full derivative machinery: ETag keying, staleness detection,
regeneration, repair, and a separate recovery obligation under
**Backup and Recovery**. On-the-fly generation costs CPU per request and carries
no stored bytes, no lifecycle, no state columns, no staleness, and nothing to
back up.

The cost that must be sized is CPU, not storage. See
**Performance Constraints**.

Today's templates make this worse than it needs to be:
`app/templates/va_formcategory_partials/_attachments_section.html:66` renders
carousel thumbnails as a full-resolution `<img>` constrained to `height: 60px`
by CSS, so the browser downloads every full image to display a 60-pixel strip.
Server-side downscaling for the preview tier fixes this directly.

### Why audio diverges

The AMR to MP3 derivative remains **stored**, as described in
**Audio derivatives**. The reasoning above does not generalise to it:

| | Thumbnails | MP3 derivative |
|---|---|---|
| Generation cost | Bounded in-process resize | SoX subprocess |
| Reuse within a session | Low | High — replayed repeatedly while coding a narration |
| Correct choice | On the fly | Stored |

This split is deliberate. Do not "simplify" the audio path later by
generalising the thumbnail decision to it.

### Image freshness and the small existing dataset

Images are fetched through Central on demand; previews are generated for the
request and discarded. Do not add persistent image freshness tracking,
background content probes, or image-version reconciliation machinery. The
bounded browser byte cache may retain the displayed image for the working
session; immediate propagation of an upstream replacement is not required.

The existing dataset is small. Reconcile the existing attachment inventory and
verify image delivery once at cutover, then retire local image copies through
the existing quarantine procedure. This does not require an ongoing local-image
freshness service. Source-change detection below applies to stored MP3s only.

`central-backend/lib/util/blob.js:66-90` at `v2026.3.0` is the authority:

```js
if (blob.s3_status === 'uploaded') {
  // > A server MUST ignore all received preconditions if its response ...
  // I.e. don't check the ETag header if the alternative is a 307.
  return redirect(307, await s3.urlForBlob(filename, blob, disposition));
} else {
  return withEtag(blob.md5, () => ...);   // DB-backed branch only
}
```

### Finding 6 — conditional GET remains usable through the S3 redirect

Central deliberately skips its own `If-None-Match` check for S3-backed blobs
and returns `307`. That does not disable conditional GET at the destination:
Requests preserves `If-None-Match` across the redirect, and S3 can return `304`.
DigitVA's sync already stores the final response's ETag and handles `304`
(`app/utils/va_odk/va_odk_07_syncattachments.py:174-233`).

Reverification used Requests 2.32.3 and pyODK 1.2.1 in the running Docker
environment. A synthetic transport confirmed `307` followed by `304`, preserved
`If-None-Match`, and stripped cross-host authorization. This was not a live S3
test; the selected provider must pass integration tests.

For stored MP3s, explicitly resolve and validate redirects, then send the saved
content validator to the approved content endpoint. A `304` plus an existing
valid derivative permits reuse; a changed source requires download/conversion.
A missing derivative requires retrieval even when the source is unchanged.
Treat ETags as opaque and allow a fresh transfer when backing-store migration
changes the validator or the provider supplies no usable validator.

Do not use `name`/`exists` or submission version alone to infer unchanged audio:
Central permits overwriting an attachment within the same submission version.
No attachment version history is required. Images are fetched on demand and do
not participate in this persistent freshness mechanism.

Sources: [Central blob response implementation](https://github.com/getodk/central-backend/blob/v2025.1.0/lib/util/blob.js#L47),
[S3 conditional GET](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html),
and [Central version attachment semantics](https://docs.getodk.org/central-api-submission-management/#downloading-a-version-s-attachment).

### Finding 7 — the signed URL lifetime is 60 seconds and is not configurable

`central-backend/lib/external/s3.js:185` hardcodes `const expiry = 60;`. The
plan's "initially targeted at one to five minutes" is not a setting that exists.
Every timing decision — retry windows, any locator cache TTL, the acceptable gap
between page render and image load — must be built against 60 seconds.

Where a browser holds a resolved S3 URL across a longer session and issues later
range requests against it, that URL will be expired and S3 will answer `403`.
DigitVA-owned derivatives are served from DigitVA's own storage, so DigitVA
controls that expiry independently; the constraint above applies to Central
originals.

### Finding 8 — CORS is not required for the current markup

Attachments render as plain `<img src>`
(`app/templates/va_formcategory_partials/_attachments_section.html:42,66,121`)
and `<audio><source src>` (`:97-98`). Those elements are not governed by CORS:
browsers load cross-origin images and media through them without a preflight and
follow redirects normally. The lightbox copies `img.src`
(`app/templates/va_formcategory_partials/category_attachments.html:241`) and
rotation is a CSS `transform: rotate()` (`:159`, `:223`), so no canvas pixel
read occurs and no tainted-canvas failure is possible.

DigitVA's same-origin proxy fetch needs no bucket CORS. Cross-origin JavaScript
fetch would require CORS even when its initial URL is same-origin but redirects
to S3; not every such fetch requires a preflight. Separately, Central's own
frontend needs the bucket CORS configuration required by its official setup
guide. Do not remove that configuration on the strength of DigitVA's markup.

### Finding 9 — Central may sign a literal `"null"` content type

`central-backend/lib/external/s3.js:170-172` sets
`'response-content-type': contentType || 'null'`, annotated in Central's own
source as "a questionable content-type, but matches current central behaviour".
A redirected response can therefore arrive with `Content-Type: null`. DigitVA
already stores `mime_type` per attachment row, but sync copies upstream values
without validation. The proxy must validate MIME metadata and distinguish MP3
output from AMR source metadata before it can correct this reliably.

## Module Boundary

The complexity this plan introduces — Central versus S3 versus local fallback,
redirect validation, feature flags, derivative freshness — must not be pushed
into route handlers, render code, or KPI queries. It belongs behind one module
with a narrow interface:

```text
AttachmentService
    deliver(storage_name, user, variant="original") -> Response   (proxy only)
    url_for_field(va_sid, form_id, name, variant="original") -> str | None
    readiness(va_sids)                   -> dict[va_sid, Readiness]   (bulk)
    mark_audio_derivative_stale(va_sid, filename) -> None
```

Callers learn nothing about where bytes live. The route becomes a single
delegation. `app/routes/admin.py` and `app/tasks/sync_tasks.py` both call
`readiness()`, and the duplicate helper at `app/routes/admin.py:5340` is deleted
rather than ported. The `va_sid=None` disk branch and the
`__attachment_present__` sentinel in
`app/utils/va_render/va_render_06_processcategorydata.py` exist only because no
readiness call is available today; both are removed once it is.

Authorization stays in this module and in the route layer. It is never inferred
from possession of a token or a signed URL.

`variant` accepts only original or a fixed configured preview profile; arbitrary
client-selected dimensions are not supported. Phase 3 implements original/local
delivery only; preview behaviour ships in Phase 4 with its frontend changes.
The extraction is behaviour-neutral relative to the Phase 0 security fixes.

`readiness()` is a bounded bulk metadata read with no Central/S3 calls. Its result
distinguishes unknown, listed-present, observed-available, missing, retired, and
error source states. `retired` applies to submissions retired from ODK
([policy](../policy/odk-retired-submissions.md)): Central has purged the source, so
no probe or repair is attempted and the local copy, if present, is served; audio additionally has pending, ready, stale, and error derivative
states. Return observation timestamps and error categories so old observations
are not presented as a current probe. Phase 3 preserves existing disk-backed
decisions inside the service; Phase 4 uses recorded remote state. Rendering and
dashboards do not initiate downloads or derivative generation.

Retain separate tests for external behaviour and filesystem integrity; do not
replace them solely with mocks of the new service interface. The integrity
script's orphan inventory remains available during quarantine, behind the
storage service where it needs attachment filesystem operations.

## Implementation Phases

### Phase 0 — Authorization fix, policy, and inventory

1. Fix Finding 1 before any other work: enforce submission-level allocation in
   `serve_attachment` for coder and reviewer roles. Define the scoped role matrix
   explicitly, including PI and administrative roles; do not blindly copy
   `serve_media`, whose missing-record branch skips allocation checks and whose
   positive allocation cache lasts 300 seconds. Reject unresolved ownership and
   enforce current authorization on every server delivery. Extend existing tests
   covering cross-project, cross-site, cross-form, and unallocated access, plus
   a deterministic-token derivation attempt against a legacy-backfilled row.
2. Add `docs/policy/attachment-storage.md` as the implementation baseline.
3. Inventory attachment MIME types, sizes, AMR usage, legacy rows, and all local
   file existence checks listed in Finding 2.
4. Record each mapped Central connection's exact version and storage configuration. If
   enabling Central S3, confirm it is at least `v2024.2.0`. Verify the attachment
   contract for the deployed database-only version too. Note whether it is
   pre- or post-`v2026.1`, since
   that determines the `Content-Disposition` behaviour described in Finding 10,
   and confirm external-storage configuration requirements for that version.
5. Record selected bucket/region, endpoint hostname allowlist, retention,
   encryption, versioning, and recovery objectives.
6. Decide the local fallback retention window; the recommended starting point
   is 30 days after verified cutover.
7. If enabling Central S3, establish bucket versioning, independent recovery copies, and a verified
   pre-offload database/configuration backup before Phase 1. Record that Central
   has no automated S3-to-database rollback. Keep the combined restore drill as
   a mandatory gate before local retirement.

### Phase 1 — Verify Central storage; optionally enable external storage

For Central without S3, verify database-backed attachment delivery and existing
database recovery, then proceed to Phase 2. Do not create a Central attachment
bucket or enable offloading merely to use the new DigitVA service.

Only when Central S3 is selected, perform the following steps after Phase 0's
recovery prerequisites. Existing S3 deployments must verify these safeguards.

1. Configure Central with its private S3 credentials and bucket settings.
2. Apply least-privilege IAM and required Central frontend CORS settings.
3. Verify new and existing attachments through each scoped connection while objects are in
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

### Phase 3 — Extract the attachment module (no Central involved)

This phase ships on its own and changes no behaviour. It exists so that Phase 4
is a change to one module's internals rather than a coordinated edit across
eight files.

1. Create the `AttachmentService` interface described under **Module Boundary**,
   implemented entirely over today's local-disk semantics.
2. Converge all six call sites from Finding 2 onto it. Delete the duplicate
   helper at `app/routes/admin.py:5340` rather than porting it.
3. Remove the `va_sid=None` disk branch and the `__attachment_present__`
   sentinel from `app/utils/va_render/va_render_06_processcategorydata.py` in
   favour of a `readiness()` call.
4. Pin the existing behaviour with tests before the implementation changes.
   `tests/test_check_attachment_integrity.py` and
   `tests/test_sync_tasks_attachment_repair.py` currently encode disk semantics
   and must be rewritten against the new interface, not merely extended.

Exit criterion: no module outside `AttachmentService` performs a filesystem
existence check for an attachment.

### Phase 4 — Central-backed implementation and dual-read rollout

Swap source delivery inside `AttachmentService` without exposing storage choice
to callers. Preview/full frontend changes explicitly use the variant contract;
they are not part of the behaviour-neutral Phase 3 extraction.

The Central-facing implementation must:

- resolve the correct Central connection and attachment endpoint;
- perform bounded-timeout, streamed requests through `guarded_odk_call`
  (`app/services/odk_connection_guard_service.py:357`) under a request-path
  policy distinct from the sync-path one — see **Performance Constraints**;
- set `allow_redirects=False` so Central's redirect is observable at all
  (Finding 3), and classify the target: a redirect back to Central is followed
  server-side, and an approved S3 target is fetched server-side and proxied;
- explicitly support the verified Central `301` canonical-version redirect and
  `307` S3 redirect; reject unrecognised redirects rather than accepting every
  `3xx`. Resolve relative locations and validate every hop, with a finite limit;
- distinguish Central `200`, approved redirect, not-found, authentication,
  throttling, and transient failures;
- validate redirect scheme and host against the configured allowlist;
- keep ODK credentials on the configured Central origin only; issue S3 requests
  without ODK credentials or inherited session authentication;
- preserve valid audio `Range` semantics through the derivative proxy, including
  `206`, `Content-Range`, `Accept-Ranges`, and `416`; define bounded retries before
  headers are sent, and close upstream responses on completion/disconnect;
- never log credentials, signed query strings, or raw sensitive payloads.

Authorization stays in the route and service layer. Permission decisions are
never moved into templates and never inferred from possession of a signed URL.

Rollout:

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

| Outcome | Migration response after user authorization |
|---|---|
| Central timeout, rate limit, transient 5xx | Permit a retained, reconciled local copy; record fallback use |
| Central/S3 authentication failure | Report configuration failure; no silent fallback |
| Confirmed absent/deleted source (submission still in ODK) | Show unavailable; do not resurrect a local copy |
| Submission retired from ODK | Source state `retired`: no probe, no repair; serve the retained local copy if present, else unavailable |
| S3 403 | Classify the provider error; refresh an expired signature once, otherwise report error rather than assuming absence |
| Invalid redirect or denied DigitVA access | Reject; no fallback |

The one-time cutover inventory is sufficient for existing local images. No
ongoing image-version service is required; temporary fallback may serve the
reconciled copy during an outage. Close that fallback window at cutover.

### Phase 5 — Change sync and repair behavior

1. Stop downloading permanent local copies of ordinary images for enabled
   forms.
2. Sync attachment lists and metadata through Central and verify source
   availability without assuming S3 placement.
3. Generate/reuse MP3 derivatives using the final content endpoint's validator.
4. Update canonical repair, admin backfill, on-open repair, and KPI logic to use
   source availability plus derivative readiness.
5. Preserve MP3 idempotency with conditional GET at the final content endpoint
   (Finding 6). Forward the validator only after redirect validation; reuse a
   valid MP3 on `304`, and retrieve the source if the derivative is missing.
   Test unchanged, replaced, missing-derivative, and backing-store-transition
   cases against the selected provider.
6. Do not add background image freshness probes or persistent image validators.
   Listing/availability metadata remains distinct from content-change tracking.

### Phase 6 — Cutover to the DigitVA S3 store

Rewritten 2026-09-17. The earlier framing retired local files in favour of
Central; the decided direction is the opposite — DigitVA keeps its own
permanent copy, in its own bucket. No step deletes anything, and the only
removal in the whole sequence is a manual one by an operator.

1. Provision the bucket: private, Block Public Access on, versioning on,
   SSE-S3, **no lifecycle expiry on current versions**, least-privilege IAM
   scoped to the bucket and prefix. Checklist and policy JSON in
   [runtime and operations](../current-state/runtime-and-operations.md#attachment-delivery).
2. Set the `S3_*` keys, then `ATTACHMENT_STORE=s3`, and restart the app and
   both Celery services. A missing key is a hard startup failure; there is no
   silent fallback to local disk. New sync downloads now go to the bucket.
3. `flask attachments s3-upload --dry-run`, then for real. It streams each
   local blob into the bucket with the right content type, verifies size and
   (for single-part uploads) ETag against the local MD5, and only then sets
   `store_state='s3'`, `local_path=NULL`. Idempotent, resumable, keyset-paged,
   non-zero exit on any failure, and it never deletes a local file. Retired
   submissions' attachments are uploaded too.
4. `python scripts/check_attachment_integrity.py --store s3` must report zero
   missing objects and zero rows awaiting the cutover. The check lists the
   bucket and reports orphan keys; it never deletes.
5. `flask attachments local-quarantine` moves each verified row's local file to
   `APP_DATA/<form_id>/media/.s3-uploaded/` and marks it `quarantined`. A row
   whose object is not in the bucket is left alone. `retained` archival copies
   are skipped unless `--include-retained` is given.
6. Retention: leave the quarantined files for an agreed window — at least one
   full backup cycle — while watching delivery outcomes and counters.
7. Remove them by hand, after a verified backup. Deliberately not a command in
   the application.
8. Update backup scope: the bucket is now a primary data store and belongs in
   the backup plan alongside the database. An app-server disk backup no longer
   covers attachments.

## Failure and Rollback Strategy

- Before local downloads stop, the remote-backed feature flag can return an
  affected project/form to its preserved local path. Afterwards, verify local
  coverage and retrieve missing files through Central before using local-only
  delivery. With the small dataset this is a bounded operational check, not a
  new background reconciliation service.
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

- Repair, then preserve, attachment authorization. Preserving today's checks is
  not sufficient: `serve_attachment` currently enforces only form-level access
  and must regain the submission-level allocation check (Finding 1). Test
  against cross-project, cross-site, cross-form, and unallocated-submission
  access.
- Treat the opaque token as an identifier, never as a capability. Legacy tokens
  are deterministically derivable from `va_sid` and filename, so possession of
  a token must grant nothing on its own.
- Signed URL lifetime is Central's, not ours: 60 seconds, hardcoded at
  `central-backend/lib/external/s3.js:185` (Finding 7). Do not design around a
  configurable expiry for Central originals. DigitVA-owned derivatives are
  served from DigitVA storage, where the expiry is ours to choose and must cover
  a realistic playback or viewing session.
- Do not persist or log signed URLs, authorization headers, ODK credentials, S3
  credentials, or attachment payloads.
- Use bounded streaming; do not load large media into application memory.
- Validate MIME behavior and set safe content-disposition/content-type headers.
- Reject unexpected redirect hosts, non-HTTPS targets, redirect loops, and
  excessive redirect chains.
- Review browser referrer policy and cache headers so signed query strings are
  not leaked to unrelated origins.
- CORS: DigitVA's same-origin proxy needs no bucket CORS. Preserve the bucket
  CORS configuration required by Central's frontend when Central uses S3.
  Browser-to-S3 redirects or fetches require a separate design review.
- Audio range behaviour is a property of whichever store serves the bytes.
  Verify `Range`/`Accept-Ranges` on the DigitVA derivative path, which is the
  path that actually serves playback.

## Backup and Recovery

ODK Direct Backup does not include attachments stored in external S3-compatible
storage. Enabling Central S3 therefore creates a separate recovery obligation.

For Central without S3, preserve and test database/configuration recovery;
original attachment bytes remain in the database. When Central uses S3, the
bucket safeguards below must exist before enabling offloading, and the combined
restore must pass before local-file retirement. DigitVA's stored derivatives
need their own recovery procedure in either deployment mode:

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
- a permanently database-only Central works without S3 configuration; a
  mixed/S3 Central works through both `200` and validated `307` outcomes;
- the same image works before and after the daily job changes its response from
  database `200` to S3 `307`, without changing its DigitVA URL or metadata flag;
- one submission with mixed database/S3 attachments renders successfully, and
  failed offloads continue to work from the database;
- stored MP3 freshness handles the database-to-S3 validator transition without
  mistaking storage movement for missing content or requiring all blobs to move;
- concurrent requests for two differently mapped project/form/site contexts use
  their own connection, credentials, remote IDs, allowlist, and pacing, including
  one database-only Central and one mixed/S3 Central;
- colliding remote submission IDs/filenames across connections do not share
  cache entries, validators, derivatives, or authorization decisions;
- missing/inactive mappings fail closed on the new remote path; mapping changes
  invalidate source resolution and audio freshness without remapping ownership;
- the same attachment is delivered correctly whether Central answers `200` or
  `307`, with no caller-visible difference;
- delivery is verified against both a 2025-line Central and a `v2026.1+`
  Central, confirming that `Content-Disposition` and `Content-Type` seen by the
  browser are DigitVA's own and do not vary by Central version (Finding 10);
- a submission-version `301` from Central is followed server-side and never
  handed to the browser as an S3 target;
- missing/literal `null` MIME values are handled safely, and an MP3 derivative
  is served as MP3 rather than with its original AMR source type;
- attachment responses carry `Cache-Control: private, no-store` and PHI bytes do
  not appear in the browser disk cache after a coding session (Finding 11);
- the lightbox, zoom, and rotate paths receive original bytes; no downscaled or
  re-encoded image is reachable from the zoom path;
- EXIF orientation is preserved or normalised so server-side handling does not
  fight DigitVA's own rotation state;
- the client byte cache respects its budget, evicts under pressure, and revokes
  object URLs on eviction;
- a 35-image gallery renders within the agreed latency and CPU budget with
  thumbnail concurrency bounded;
- expired signed URLs are refreshed through a new authorized request;
- signed URLs and secrets are absent from logs and persisted records;
- stored MP3 checks reuse valid derivatives on `304` from either the database
  endpoint or the approved S3 endpoint, retrieve missing derivatives, and
  handle replacement content under an unchanged filename/submission version;
- image sync/rendering performs no background content-validation requests;
- unknown attachment ownership is denied on both routes, and server delivery
  rejects revoked allocation even when attachment metadata is cached;
- client caches clear on lifecycle changes, reject late responses, and require
  reauthorization after the five-minute reuse window;
- fallback follows the outcome table, and rollback checks local coverage;
- readiness batches metadata without network calls and distinguishes observation
  timestamps from current availability;
- thumbnail size/pixel/time limits reject oversized or corrupt inputs safely;
- missing objects, timeouts, throttling, redirect loops, and invalid MIME types
  produce controlled outcomes;
- AMR conversion generates a current MP3 derivative once and regenerates it
  when the source ETag changes;
- legacy `storage_name IS NULL` and existing local-path rows remain usable;
- repair and workflow advancement use the new completeness semantics;
- a coder holding a valid token for an unallocated submission is refused, and a
  deterministically derivable legacy token grants no access (Finding 1);
- `tests/test_check_attachment_integrity.py` and
  `tests/test_sync_tasks_attachment_repair.py` are rewritten against the
  `AttachmentService` interface rather than disk state.

### Integration tests

Use a mock Central service and S3-compatible test storage to cover:

- DB-backed Central streaming;
- Central-to-S3 redirects;
- same-origin browser image display and, where applicable, Central frontend CORS;
- audio byte-range requests;
- Central or S3 outage;
- concurrent coder requests;
- large-file streaming and bounded memory use.

### User and operational verification

- coders can view multiple and large images on assigned submissions;
- reviewers and data managers retain their correct scoped access;
- copied signed URLs expire and do not grant durable access;
- revoking allocation prevents new server delivery; already delivered client
  bytes follow the documented cache lifecycle and reuse window;
- browser refresh/back behavior and audio seeking work;
- dashboards distinguish unavailable source from missing derivative;
- backup/restore drill successfully reconstructs a sample submission and its
  attachments.

## Performance Constraints

- Route Central calls through `guarded_odk_call`
  (`app/services/odk_connection_guard_service.py:357`), but define a separate
  request-path policy. `reserve_odk_request_slot` currently resolves contention
  with `time.sleep()` (line 370); in a coder's image request that stalls a
  worker. The request path needs a bounded wait and a fast controlled failure,
  not sync-path pacing.
- Avoid one Central authentication handshake per attachment; reuse the existing
  connection/session safely.
- Avoid N+1 database queries when rendering a page containing multiple media
  items.
- Do not prefetch binaries merely to render attachment links.
- Cache the attachment *record*, never the locator. The existing `att:` cache
  (`app/routes/va_form.py:1397`) holds `local_path` for 3600s; this is 60 times
  Central's 60-second signed-URL lifetime and must
  not be reused for a remote locator.
- Do not introduce a server-side signed-URL cache in this implementation.
- `admin_sync_legacy_attachment_stats` (`app/routes/admin.py:5750-5763`) scans
  every non-null `storage_name` row and recomputes a uuid5 per row in Python on
  each request. Replace it with a stored marker or a bounded query while the
  surrounding code is being changed.
- Measure page latency and Central request volume before deciding whether
  batching or proxy caching is necessary.
- Proxy delivery is the default (Finding 10), so attachment bytes traverse the
  DigitVA app server. Measure worker occupancy and egress on a page with many
  large images before expanding the rollout, and treat a sustained regression as
  the trigger for evaluating redirect delivery on `v2026.1+` rather than as a
  surprise.
- On-the-fly thumbnailing trades storage for CPU, and a 35-image gallery fires
  its requests near-simultaneously. Decode at reduced scale rather than
  decoding then resizing — Pillow's `img.draft('RGB', (w, h))` before `load()`
  uses JPEG DCT scaling and is several times cheaper — and bound the concurrency
  so one gallery render cannot saturate the workers.
- Before preview implementation, record concrete limits for compressed input
  bytes, decoded pixels, processing time, output size, concurrent work, and queue
  wait. Reduced JPEG decoding is an optimisation, not a safety bound for all
  formats. Reject corrupt/decompression-bomb inputs; use bounded temporary
  storage and a controlled unavailable-preview state for unsupported formats.
- Define connect/read/total request deadlines and conversion subprocess timeouts;
  close streams and remove temporary files on errors and browser disconnects.
  A streaming original response and a decoded preview have different memory
  profiles and must be measured separately.
- On-the-fly generation does not reduce Central-to-DigitVA traffic; the full
  image is still fetched to produce the preview. At one to three views per
  submission this is accepted deliberately, and the in-memory client cache
  absorbs within-session repeats.

## Expected Repository Scope

### Verified code references

Repository-relative links below refer to the code inspected on 2026-09-17.
Line numbers are navigation aids and should be refreshed when implementation
changes these files. These observations are source review, not a claim that the
full application suite or a live Central/S3 deployment was tested.

| Concern | Existing implementation / test evidence |
|---|---|
| Opaque route and form-only permission check | [serve_attachment](../../app/routes/va_form.py#L1335), [permission check](../../app/routes/va_form.py#L1378), [form access semantics](../../app/models/va_users.py#L252) |
| Legacy unresolved-owner branch and cached allocation | [serve_media](../../app/routes/va_form.py#L1424), [300-second allocation cache](../../app/routes/va_form.py#L1440) |
| Deterministic legacy token | [legacy_attachment_storage_name](../../app/services/attachment_storage_name_service.py#L12) |
| Existing seven route tests; allocation cases to add | [test_serve_attachment.py](../../tests/routes/test_serve_attachment.py#L1), [mocked access on happy path](../../tests/routes/test_serve_attachment.py#L221) |
| Partial cache policy and byte delivery | [partial policy](../../app/routes/va_form.py#L83), [attachment record cache / send_file](../../app/routes/va_form.py#L1395) |
| Conditional headers, redirects, 304 self-heal | [attachment download](../../app/utils/va_odk/va_odk_07_syncattachments.py#L174) |
| Unvalidated source MIME / derivative metadata | [response metadata and AMR conversion](../../app/utils/va_odk/va_odk_07_syncattachments.py#L231), [row update](../../app/utils/va_odk/va_odk_07_syncattachments.py#L336) |
| AMR failure leaves source path / skips caller cleanup | [caller](../../app/utils/va_odk/va_odk_07_syncattachments.py#L248), [converter](../../app/utils/va_odk/va_odk_07_syncattachments.py#L654) |
| Duplicate disk presence rules | [sync helper](../../app/tasks/sync_tasks.py#L59), [admin helper](../../app/routes/admin.py#L5340) |
| Disk-based completeness and repair decision | [attachments_complete](../../app/tasks/sync_tasks.py#L861) |
| Render sentinel and disk visibility branch | [attachment rendering](../../app/utils/va_render/va_render_06_processcategorydata.py#L158) |
| Local integrity and orphan inventory | [integrity script](../../scripts/check_attachment_integrity.py#L83) |
| Full-image thumbnails and audio markup | [60px thumbnail](../../app/templates/va_formcategory_partials/_attachments_section.html#L63), [audio source](../../app/templates/va_formcategory_partials/_attachments_section.html#L95) |
| pyODK session construction | [client setup](../../app/utils/va_odk/va_odk_01_clientsetup.py#L111) |
| Project connection and form/site routing | [project mapping](../../app/models/map_project_odk.py#L8), [local/remote form identifiers](../../app/models/va_forms.py#L9), [connection master](../../app/models/mas_odk_connections.py#L9) |

### Implementation areas

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
| Existing project connection and form/site mappings | Preserve scoped resolution; connection-specific allowlists, caches, and validation |
| `app/services/attachment_service.py` (new) | The module boundary; all source/readiness decisions |
| `app/routes/va_form.py` | Submission-level authorization fix, then delegation |
| `app/services/coding_service.py` | `_count_attachments_per_category` gallery counts vs source availability |
| `app/services/payload_enrichment_backfill_service.py` | Attachment stages reuse the module |
| `scripts/check_attachment_integrity.py` | Integrity check against source, not disk |
| `tests/routes/test_serve_attachment.py` and legacy media tests | Extend existing coverage for allocation, ownership, cache, and connection scope |
| `app/utils/va_render/va_render_06_processcategorydata.py` | Render based on records, not local-file existence |
| `app/services/open_submission_repair_service.py` | Remote-aware completeness/repair |
| `app/tasks/sync_tasks.py` | Bounded derivative/repair work |
| `app/routes/admin.py` and KPI services | Revised availability telemetry |
| `app/templates/va_formcategory_partials/_attachments_section.html` | Preview-tier thumbnails instead of CSS-constrained full images |
| `app/templates/va_formcategory_partials/category_attachments.html` | Lightbox hydration against the full tier |
| attachment client-side cache (new JS) | Bounded LRU, object-URL lifecycle, preload |
| focused unit/integration/browser tests | Security, behavior, and rollout gates |

## Decisions to Confirm Before Implementation

Recommended defaults are included so implementation can proceed after review:

1. **Browser delivery:** settled in **Delivery Design** — streaming proxy for
   both Central responses, `Cache-Control: private, no-store`, a bounded
   in-memory JavaScript byte cache, a preview/full tier split, and on-the-fly
   thumbnails. What remains to confirm is the byte budget for the client cache
   and the downscale target for the preview tier.
2. **Storage isolation:** where configured, separate ODK-original,
   DigitVA-derivative, and backup buckets; strict prefixes and IAM if one bucket
   is operationally required. Database-only Central needs no original bucket.
   **Settled 2026-09-17: database-only Central; no buckets.** MP3 derivatives
   remain local under `APP_DATA/<form_id>/media/` with the existing recovery
   (file backup) procedure.
3. **Local fallback:** retain for the staged rollout, then quarantine for 30 days
   after verified cutover.
4. **Audio:** retain original AMR under Central and store an MP3 derivative under
   DigitVA control.
5. **Source health:** evaluate through Central, never by probing or guessing an
   S3 object key.
6. **Sequencing:** the Phase 0 authorization fix and the Phase 3 module
   extraction each ship independently before Phase 4's DigitVA integration.
   Phase 1's optional Central offloading requires recovery safeguards first.
7. **Freshness scope:** settled — images are fetched on demand with no persistent
   freshness tracking. Stored MP3s use conditional GET at the final content
   endpoint; verify provider behaviour as described in Finding 6. Reconcile the
   small existing dataset once at cutover.
8. **Pinned Central version:** the version whose redirect contract was verified,
   and the re-verification step on upgrade.
9. **Deployment modes:** settled — support Central with and without S3. External
   storage setup and Central bucket recovery gates apply only to the S3 mode;
   the delivery and MP3 tests must cover both.
10. **Connection scope:** settled — resolve each attachment through its owning
    project/form/site mapping. No global Central endpoint or global S3-mode
    assumption; preserve existing project-level credential mapping and form/site
    routing, with isolation tests across connections.

## Completion Criteria

The migration is complete only when:

- submission-level authorization is enforced on every attachment route and
  covered by tests;
- no module outside `AttachmentService` performs a filesystem existence check
  for an attachment;
- authorized human coders can reliably see all required images and play audio;
- both Central DB-backed and S3-redirected attachments have passed tests;
- ordinary original images are no longer permanently duplicated by DigitVA;
- required derivatives are reproducible and independently recoverable, and audio
  is the only stored derivative;
- PHI attachment bytes are not written to the browser disk cache;
- remote-aware repair and dashboard semantics are deployed;
- a database/configuration restore drill has succeeded, including original
  attachment objects when Central uses S3 and DigitVA derivative recovery in
  either mode;
- local originals have completed the approved quarantine period; and
- documentation, monitoring, and operational runbooks reflect the deployed
  behavior.
