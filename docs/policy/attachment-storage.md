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

## Source of truth, and the two copies

- ODK Central is the source of truth for whether an original attachment exists
  and what its content is.
- DigitVA keeps its **own permanent copy** of every attachment — originals and
  the MP3 derivatives it makes from `.amr` narration — in a DigitVA-owned
  store, and that store is the read path. Central is consulted only to fill a
  store miss, never on every request.
- The store is either local files under `APP_DATA/<form_id>/media/` or a
  private DigitVA-owned S3 bucket, selected once by `ATTACHMENT_STORE` and
  implemented in `app/services/attachment_store.py`. Nothing outside the
  attachment module knows which.
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
| Bulk stored readiness state (Phase 4 contract) | `readiness()` |
| Mark an audio derivative as needing a rebuild | `mark_audio_derivative_stale()` |
| Visibility check without submission identity | `is_attachment_present_for_form()` |
| Filesystem inventory for the integrity script | `scan_local_media_files()` |
| Bulk presence identity for one row | `resolve_attachment_presence()` |
| Store backend interface | `attachment_store.get_attachment_store()` |
| Store lookup / read / tee-write | `_store_exists()` / `_store_open()` / `_store_write()` |
| Store-backed delivery of a legacy `/media` row | `deliver_legacy_media()` |
| Delivery, store first and Central self-heal | `deliver()` |
| Store-only delivery (never reaches Central) | `deliver_local_attachment()` |
| Temp path for one download | `new_ingest_temp_path()` / `discard_ingest_temp_file()` |
| Ingest one downloaded file (convert, store, state) | `ingest_download()` |
| Row values for an attachment ODK no longer holds | `mark_removed_on_odk()` |
| Single-row store presence (sync's 304 self-heal) | `attachment_present()` |
| Remove blobs a fresh ingest replaced | `cleanup_superseded()` |
| Repair one attachment from ODK Central | `repair_attachment()` |
| Rows a repair could fix, bounded | `repair_candidates()` |
| Readiness-based completeness input | `attachment_state_by_submission()` |
| Operator overview (admin panel, CLI) | `attachment_management_overview()` |
| Integrity against the store | `local_integrity_check()` / `s3_integrity_check()` / `integrity_check_summary()` |
| Orphan quarantine (local store only) | `quarantine_orphan_files()` |
| Local -> S3 cutover | `s3_upload_backlog()` / `quarantine_local_copies()` |
| Per-project Central self-heal switch | `set_project_central_fetch()` |

Rules:

- The attachment service is a deep module: it owns the whole lifecycle —
  ingest, storage, derivatives, repair, retirement and migration — not just
  serving. **No module outside `attachment_service` performs a filesystem,
  store or ODK Central operation for an attachment.** Routes, render code,
  sync (`app/utils/va_odk/va_odk_07_syncattachments.py`), sync tasks, admin
  telemetry, `app/commands/attachments.py` and
  `scripts/check_attachment_integrity.py` all call the service; the CLI and the
  script hold no logic of their own.
- Attachment sync lists attachments from Central, issues the conditional GET,
  writes the body to the temp path the service hands it, calls
  `ingest_download()`, and applies the returned state with its PK-safe upsert.
  It imports no `os`, `subprocess`, `tempfile` or `pathlib`, knows nothing
  about a media directory, and never calls the store. A test enforces this
  (`tests/test_sync_attachments_boundary.py`).
- Callers learn nothing about where bytes live. Replacing the local-disk
  implementation with Central-backed delivery is a change to this module's
  internals, not to its callers.
- The serving-route cache (`att:<storage_name>`, 3600 s) holds the attachment
  **record** — ownership, path, MIME — never a locator that can expire, and
  never an authorization decision. Cache entries lacking ownership are treated
  as misses.

## Store backends

`ATTACHMENT_STORE` selects one backend for the process. It is validated at
startup: with `s3`, every one of `S3_SERVER`, `S3_BUCKET`, `S3_REGION`,
`S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` must be present or **the app refuses
to start**. There is no silent fallback to local disk — that would scatter PHI
across app servers that are expected to hold nothing. Secrets come from the
environment and are never logged, echoed by a command, or sent to a client.

Both backends implement the same interface in
[`app/services/attachment_store.py`](../../app/services/attachment_store.py):

| Operation | Meaning |
|---|---|
| `key_for(record)` | `<S3_PREFIX><form_id>/media/<storage_name>` (the prefix is empty for the local store, whose key is the path relative to `APP_DATA`). `None` for a row with no `storage_name`. |
| `exists(record)` | Local: the file resolves inside the form's media directory. S3: `head_object` on the key. |
| `open_local_path(record)` | The file's path for the local store; always `None` for S3. |
| `put(record, source, *, content_type)` | Store one object from a file path, a readable stream, or an iterable of chunks. |
| `presigned_url(record, *, content_type, filename)` | S3 only; `None` for the local store and `None` for any row without a `storage_name`. |
| `delete(record)` | **Explicit tooling and superseded-object cleanup only.** Never called by delivery, and never by sync for anything but a key the row no longer points at. |

### Key layout

`<S3_PREFIX><form_id>/media/<storage_name>` — the same shape as the local
directory layout, so an object and a file are addressed identically. The
`storage_name` is the opaque serving token, never the original ODK filename.
A row without a `storage_name` (legacy, pre-token) has no key and **is never
presigned**.

### Object metadata

Every uploaded object carries:

- `Content-Type` — DigitVA's validated MIME. `derivative_mime_type` for an
  `.amr` row (whose blob is the MP3), `source_mime_type` otherwise, then the
  stored `mime_type`, then a guess from the storage name's extension, then
  `application/octet-stream`. A literal `"null"` from upstream is never stored.
- `Cache-Control: private, no-store` — so the policy holds even for a fetch
  this process did not sign.
- `Content-Disposition: inline`.
- `ServerSideEncryption: AES256` (SSE-S3), in addition to the bucket default.

### Never delete

- No object is ever deleted by delivery, by presence checks, by readiness, or
  by the integrity check.
- Sync deletes only a *superseded* object — the key under an old
  `storage_name`, and only after the row already points at the new key and no
  other live row references the old one. A failed delete is logged and becomes
  an orphan key the integrity check reports; it never fails a sync.
- Attachments of submissions retired from ODK are uploaded like any other:
  their object **is** the archive.
- `flask attachments s3-upload` and `local-quarantine` never delete anything.
  The retention removal of quarantined local files is a manual step, taken by
  an operator after a verified backup.

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

`deliver()` is the single entry point. Authorization has already happened in
the route; delivery only decides where the bytes come from.

| Step | Condition | Result |
|---|---|---|
| 1 | The store holds the object | Serve it. Central is not contacted. Outcome `local`. Local store: `send_file`. S3 store: `302` to a presigned GET. |
| 2 | Store miss, submission retired ([policy](odk-retired-submissions.md)) | `404`. Central is never contacted for a retired submission. |
| 2 | Store miss, the row is an MP3 derivative (`.amr` original) | `404`. Central holds the AMR, not DigitVA's MP3; sync rebuilds it. |
| 2 | Store miss, `attachment_central_fetch_enabled` is false | `404`, exactly as before the flag existed. |
| 3 | Store miss, flag on | Fetch the original from the project's own connection, stream it to the browser, write it into the store. Outcome `central_stream`, or `central_redirect_followed` when a same-origin Central redirect was followed. |

Outcomes of a failed fetch:

| Fetch outcome | Response | `source_state` written |
|---|---|---|
| Central `200` | `200`, streamed and stored | `available`, `source_verified_at` now, error cleared |
| Central `404`/`410` | `404` | `missing`, `source_error_code='not_found'` |
| Timeout, connection error, `5xx`, cooldown | `503` + `Retry-After` | error code `transient`; an `available` row stays `available` |
| `429`, or the request-path pacing slot is busy | `503` + `Retry-After` | error code `throttled`; an `available` row stays `available` |
| `401`/`403` | `502` | error code `auth` |
| No active mapped connection | `502` | error code `auth` |
| Redirect off the Central origin, an unhandled `3xx`, or more than three hops | `502` | error code `invalid_redirect` |
| Any other status | `502` | error code `unknown` |

A failure never downgrades a row that has already been proved `available`: a
timeout does not unprove an earlier successful delivery. `source_verified_at`
moves only on an observed content response, so an old observation is never
restamped as current. State is written and committed **before** any byte is
streamed; no transaction is held open across a response body.

Headers on every attachment response:

- `Cache-Control: private, no-store, max-age=0` and
  `X-Content-Type-Options: nosniff`. PHI image and audio bytes must not be
  written to the browser disk cache, consistent with the `no-store` policy on
  the partials that reference them;
- for a Central-fetched original, `Content-Type` is DigitVA's validated MIME,
  `Content-Disposition: inline; filename="<storage_name>"`, and `Content-Length`
  when Central supplied one. These are DigitVA's own headers, so delivery does
  not vary with the Central version;
- store reads keep `send_file`'s `Range` support, which is what audio playback
  uses.

Other rules:

- Delivery stays under `APP_DATA/<form_id>/media/`; a path outside it or a
  missing object is `404`, and a store miss evicts the record cache.
- The stored `mime_type` is copied from upstream and is not authoritative. A
  missing, malformed, or literal `"null"` value is discarded and the type is
  derived from the storage name or from the row's validated
  `source_mime_type`. Sync applies the same validation before writing the row.
- A store write is a temporary file in the same directory plus an atomic
  rename, so an abandoned or failed fetch can never leave a partial object or
  one that looks complete.
- One structured log line per delivery records the outcome and latency; URLs,
  query strings, headers, credentials, and payloads are never logged.
  In-process counters are available through `delivery_counters()`.

### Presigned delivery (S3 store)

The DigitVA route stays the **only** URL that appears in any page. After
authentication and the authorization matrix, delivery issues a `302` to a URL
signed for that one request:

- expiry `ATTACHMENT_PRESIGN_EXPIRY_SECONDS`, default **300 seconds**;
- `ResponseContentType`, `ResponseContentDisposition`
  (`inline; filename="<storage_name>"`) and `ResponseCacheControl`
  (`private, no-store`) are fixed **inside the signature**, so a signed URL
  cannot be replayed with a different type or disposition;
- the signed URL is never rendered into a page, stored, cached, or logged. It
  exists for the duration of one redirect;
- the redirect response itself carries `Cache-Control: private, no-store,
  max-age=0`, so a browser re-runs the authorized DigitVA request rather than
  replaying a stale signature;
- `Range` requests — what audio playback uses — are answered by S3 natively;
- the bucket's origins are added to the `img-src` and `media-src` content
  security policy directives when the S3 store is selected, because the browser
  applies them to the final URL of a redirect.

A row with no `storage_name` is never presigned: it has no key, `exists()` is
false, and delivery is a `404`.

## Central self-heal

`va_project_master.attachment_central_fetch_enabled` (default false) is the
per-project rollout switch, set with
`flask attachments central-fetch <project_id> --enable/--disable/--status`, with
`PUT /admin/api/projects/<project_id>/attachment-central-fetch`, or from the
admin Projects panel. Because the store is read first, disabling it is a
complete rollback with no data change.

The fetch itself:

- resolves the connection through the attachment's own project mapping
  (`va_submissions` -> `va_forms` -> `map_project_odk` -> `mas_odk_connections`,
  active only). There is **no** global or default connection: an unmapped,
  inactive, or ambiguous mapping fails closed;
- reuses one pyODK client per connection per thread, so an attachment request
  does not pay for an authentication handshake;
- issues the request through a **no-retry clone** of that connection's session.
  pyODK mounts `Retry(total=3, backoff_factor=2,
  status_forcelist=(429, 500, 502, 503, 504))`, which is right for a sync
  worker and wrong for a caller that must answer now: one `503` would cost
  roughly fourteen seconds of backoff before classification. The clone shares
  the credentials, cookies and TLS settings and mounts
  `HTTPAdapter(max_retries=0)`; the shared session sync depends on is never
  mutated;
- streams with bounded connect/read timeouts
  (`ATTACHMENT_FETCH_CONNECT_TIMEOUT_SECONDS`,
  `ATTACHMENT_FETCH_READ_TIMEOUT_SECONDS`) and never buffers a body whole;
- runs through `guarded_odk_call` under a **request-path policy**: it passes
  `max_wait_seconds`, so pacing contention raises `OdkRequestSlotBusyError`
  instead of sleeping in a web worker, and the declined call reserves no slot;
- sets `allow_redirects=False` so Central's redirect is observable. A
  `301`/`302`/`303`/`307`/`308` whose resolved `Location` is on the same Central
  origin is followed server-side, at most three hops, with relative locations
  resolved against the URL actually requested. Anything else — another host, an
  unhandled `3xx`, a missing `Location` — is rejected as `invalid_redirect`.
  This deployment runs Central without S3, so there is no redirect allowlist and
  a `307` to a bucket is a rejection, not a handoff. Because only same-origin
  redirects are followed, the ODK credential never leaves the Central origin.

## Repair

`repair_attachment(record)` restores one attachment's bytes without a client
waiting. It shares the store-write tee (`_store_write`) with request-path
delivery, so both fill the store the same way, and reports one outcome:

| Outcome | When |
|---|---|
| `retired` | the submission is gone from ODK. Nothing is probed. |
| `not_needed` | the object is present and, for audio, the derivative is `ready`. |
| `central_disabled` | the project's `attachment_central_fetch_enabled` is off. No request is made. |
| `repaired` | a missing original was fetched from Central and written into the store. |
| `derivative_rebuilt` | a `pending`/`stale`/`error` MP3 was rebuilt from the AMR original under the row's existing `storage_name`. |
| `missing` | Central reports not-found. |
| `transient` | a timeout, throttle, or `5xx`; retry later. |
| `error` | auth, configuration, an invalid redirect, or a failed conversion — never reported as "missing". |
| `unknown_row` | no attachment row for that record. |

Every attempt records what it proved about the source through
`attachment_source_central.record_fetch_state()`, so a run that repairs nothing
still moves the row's observation forward. `repair_candidates(form_id)` is the
bounded list a batch works from, and it excludes retired submissions before any
store probe.

## Presence and completeness

Presence for a row is routed through the store and is the single definition
used by repair maps, admin backfill telemetry, and the integrity check.

Completeness is **readiness**, not a file count.
`attachment_state_by_submission(form_id)` is the single input: one bounded
query per form, no filesystem walk and no per-row store probe. For each
submission it reports

- `retired` — the submission is gone from ODK
  ([policy](odk-retired-submissions.md)). Its attachments never make it
  incomplete, because no repair may ever run for them;
- `ready_count` — attachment rows whose blob is present in DigitVA's store
  and, for audio, whose MP3 derivative is `ready`. `audit.csv` is excluded, as
  it always has been;
- `unready` — the rows that are not ready. A row whose source Central reports
  gone (`missing`/`retired`) is in neither list: it can never be satisfied.

A submission's attachments are complete when it is retired, or when
`ready_count >= AttachmentsExpected`, nothing is `unready`, and it has no
legacy rows still lacking an opaque `storage_name`.

For a `store_state='local'` row:

1. `APP_DATA/<form_id>/media/<storage_name>` when `storage_name` is set;
2. the legacy `local_path` otherwise;
3. `audit.csv` never counts as an attachment blob unless the caller asks for
   it explicitly (admin telemetry reports it separately).

For a `store_state='s3'` row, presence **is** the stored `store_state`, and the
identity is the object key. The bulk readiness paths deliberately trust
`store_state` and issue **no per-row `HEAD`**: one dashboard render would
otherwise become thousands of network calls. Object-level truth is the job of
`scripts/check_attachment_integrity.py --store s3`, which lists the bucket once
and reports missing objects and orphan keys without ever deleting.

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
  incomplete. `repair_attachment()` rebuilds a `pending`, `stale` or `error`
  derivative by fetching the AMR original from Central and converting it again
  under the row's existing `storage_name`, so no delivery token rotates.

## Source and derivative state

`va_submission_attachments` carries the readiness state the service will decide
on from Phase 4 (migration `b7e4c2a91d38`; column reference in
[the data model](../current-state/data-model.md#va_submission_attachments)). The
vocabularies are constants in
[`app/services/attachment_service.py`](../../app/services/attachment_service.py)
and no surface may re-derive them:

| `source_state` | Meaning |
|---|---|
| `unknown` | never observed |
| `listed` | named by Central's attachment list; no content response seen |
| `available` | a successful content response was observed, whether Central served it from its database or from its approved S3 destination |
| `missing` | Central reports not-found; repair may be queued |
| `retired` | the submission is gone from ODK ([policy](odk-retired-submissions.md)) — do not probe, do not repair, serve the local copy if present |
| `error` | the last observation failed; see `source_error_code` |

`source_error_code` records a category only — `not_found`, `auth`, `throttled`,
`transient`, `invalid_redirect`, `unknown`. Upstream free text is never stored.
`source_verified_at` is the time of the last observed content response, so an old
observation is never presented as a current probe. `source_mime_type` is the
validated MIME of the **original**; the pre-existing `mime_type` keeps its
meaning and is not repurposed.

`derivative_state` applies to audio only and is NULL for every other row:
`pending` (no MP3 yet), `ready` (current MP3 matches
`derivative_source_validator`, the opaque source ETag it was built from),
`stale` (the source validator moved on), `error` (conversion failed —
`derivative_error_code='conversion_failed'`, the explicit failure state the
plan's Finding 5 requires).

`local_fallback_state` describes the copy under `APP_DATA`: `present`,
`retained` (archival copy of a submission retired from ODK — never quarantined
and never retired), `quarantined`, `absent`.

### What each phase writes

| Phase | Writes |
|---|---|
| Phase 2 (done) | The migration backfills `listed`/`missing` from `exists_on_odk`, `ready`/`pending` plus `audio/mpeg` and the stored ETag for AMR rows, and `retained` for attachments of retired submissions. Sync then writes `available`/`missing`, the original's validated MIME, the AMR derivative columns, and `derivative_state='error'` on a failed conversion. |
| Phase 3 (done) | Nothing. Presence remains disk-backed through `present_attachment_files_by_submission()`. |
| Phase 4a (done) | The Central-backed source writes `available`/`missing`/`error` with `source_verified_at` and `source_error_code` on every fetch, and a self-healed object sets `local_path` and `local_fallback_state='present'`. |
| Phase 4b | Frontend preview tier, client byte cache, and lightbox. |
| Phase 5 | Sync stops downloading ordinary images and maintains derivative freshness through `mark_audio_derivative_stale()`. |
| S3 store (done) | `store_state` records which store holds each row's blob. Sync uploads to the bucket and writes `store_state='s3'`, `local_path=NULL`, `local_fallback_state='absent'`; the Central self-heal tee does the same. |
| Cutover (Phase 6, rewritten) | `flask attachments s3-upload` moves the backlog into the bucket and flips `store_state`; `flask attachments local-quarantine` moves the verified local files to `media/.s3-uploaded/` and marks them `quarantined`. Neither deletes; `retained` rows are skipped by the quarantine unless `--include-retained` is given. |

`readiness(va_sids)` in the attachment service is the bulk read of this state:
one bounded query per batch of submissions, no filesystem, no Central or S3
call. It is additive in Phase 2 and becomes the presence definition in Phase 4.

## Non-goals of this baseline

- No S3 **at ODK Central**. This deployment runs Central without object
  storage; the resolver handles a Central `307` only so that enabling it later
  is not a code change, and rejects one in the absence of an allowlist.
  DigitVA's own bucket is a separate thing and is never reached through
  Central.
- No change to sync downloads or to repair and KPI completeness semantics yet
  (Phase 5).
- No image derivatives or stored thumbnails.
- No change to the deprecated `/media` route beyond ownership resolution, the
  shared matrix, and the cache policy.
