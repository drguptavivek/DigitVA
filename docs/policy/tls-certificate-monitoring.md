---
title: TLS Certificate Monitoring
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-14
---

# TLS Certificate Monitoring

Baseline for how DigitVA watches the TLS certificates of a split production
deployment, and the S3 attachment store's credentials and bucket access. Procedure
for renewal: `docs/current-state/split-production-tls.md` (section "Renewal").
Code: `app/services/tls_health_service.py`, `app/tasks/tls_health_tasks.py`.

## What is checked

| Row | Source | Check |
| --- | --- | --- |
| App HTTPS | `APP_TLS_CERT_FILE`, the first certificate in the file | Read from disk. |
| PostgreSQL as presented | `DATABASE_URL` host and port | Only when `sslmode` is `verify-ca` or `verify-full`. Sends the PostgreSQL SSLRequest, then reads the certificate without credentials. Must match a certificate in the trust bundle. |
| PostgreSQL trust bundle | `sslrootcert` file | One row per certificate. More than one means a rotation is in progress. |
| Public HTTPS | host of `PUBLIC_BASE_URL`, port 443 | Verifying TLS handshake against the system trust store. |
| S3 attachment store | `S3_BUCKET`, `S3_PREFIX`, the store's own client | Only when `ATTACHMENT_STORE` is `s3`. Four steps, in order, stopping at the first failure. |

A deployment without one of these reports `not_configured` for that row. Dev
and single-host production have none of them.

## S3 attachment store check

The steps reuse the attachment store's client, so no second credential path
exists. Each step is one S3 call:

1. `s3_access`: list one object under `S3_PREFIX` (`MaxKeys=1`). Proves the
   key is valid, the bucket exists and ListBucket is allowed. A listing error
   carries S3's error code, so a bad key reads `credentials rejected`.
2. `s3_write`: put an empty probe object at `<S3_PREFIX>health/probe-<random>`
   with the upload encryption (SSE-S3), HEAD it, then delete it. The delete runs
   in a `finally`, so the probe is removed even when the HEAD fails. A probe
   that cannot be deleted is an `error` ("probe object could not be deleted").

3. `s3_public`: objects are reachable only through a presigned link (owner,
   2026-10-14). Against a fresh probe object: its presigned URL must return
   200; the same URL without the signature must be refused; an unsigned
   listing of the bucket must be refused. It proves behaviour, so it needs no
   extra IAM action and catches public access from any source (bucket policy,
   ACL, a disabled Block Public Access). Failures: `objects are publicly
   readable`, `bucket is publicly listable` and `presigned link did not return
   the object` are `error` (banner and email); a network failure is
   `unreachable`. Keep S3 Block Public Access on (all four settings) for the
   bucket and the account; presigned links keep working with it.

Each run writes and deletes uniquely named probe objects under
`<S3_PREFIX>health/`. On a versioned bucket every run leaves a noncurrent
version and a delete marker there: add a lifecycle rule on `<S3_PREFIX>health/`
that expires noncurrent versions and expired delete markers after a day. The
panel runs the probe on every visit (admin only); the daily task once a day.
A stalled (not unreachable) endpoint can hold a step for the store client's
60 s read timeout x 3 attempts per call.

Required IAM actions on the bucket and prefix: `s3:ListBucket`, `s3:PutObject`,
`s3:GetObject`, `s3:DeleteObject`. `s3:GetObject` is needed for the attachment
read path; the probe HEAD uses it.

Failures show a fixed phrase, never the provider's message or a key id:

- `credentials rejected` (invalid key, signature, expired or invalid token): `error`.
- `access denied (check the IAM policy for this bucket and prefix)`: `error`.
- `bucket not found`: `error`.
- `server clock is out of sync`: `error`.
- `S3 endpoint unreachable`: `unreachable`, not emailed, as for the TLS rows.
- `S3 check failed` for anything else: `error`.

A step after a failure is listed as `not_configured` with the detail
"skipped after an earlier failure". The store client connects with a 5 s
timeout and 3 attempts, so an unreachable endpoint costs about 15 s, not
minutes.

## Thresholds

- `TLS_EXPIRY_WARN_DAYS` (default 30): `due` at or below this many days left.
- `TLS_EXPIRY_URGENT_DAYS` (default 7): `urgent` at or below this many days left.
- `expired` once the certificate is past its end date.
- `error`: the presented database certificate is not in the trust bundle, the
  public certificate does not verify, or an S3 step fails for credentials,
  access, clock skew or an unexpected reason.
- `unreachable`: the probe could not connect (TLS probes: 3 s; S3: 5 s connect x 3 attempts, or a dropped connection or read timeout).

Only `due`, `urgent`, `expired` and `error` need attention.

## Renewal timing

Rotate about 30 days before expiry, the day the warning first appears. Rotate
immediately on suspected key exposure, whatever the days left. For database
rotation, add the new CA to the trust bundle before the server switches to it;
the `error` row is the signal that this order was broken.

## Who is told, and how often

- Admin panel: "System health" reads the certificates and the S3 store live on
  each visit.
- Admin index banner: appears when the stored report needs attention. It reads
  the cache only and never probes the network on a page load.
- Daily task (`TLS_HEALTH_DAILY_TIME`, default 06:30 UTC): refreshes the stored
  report and, while anything needs attention (an `error` S3 row counts), emails
  every active admin. It mails once per day for as long as the condition holds.
- The stored report expires after 26 hours, so a missed daily run clears the
  banner rather than leaving a stale warning.

## No secrets in output

Panel, banner, email and logs show labels, source (a file path, `host:port`, or
`s3://<bucket>/<prefix>`), subject name, subject alternative names, expiry, days
left, status and a fixed detail phrase. They never show a database URL, a
password, a key id, an endpoint with credentials, or raw exception text from the
TLS or S3 libraries. The task logs one line per run with counts by status.
