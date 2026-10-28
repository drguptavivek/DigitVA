---
title: App Performance Telemetry and Internal Workflow Timelines
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-28
---

# App performance telemetry and workflow timelines

Owner decisions 2026-10-28, `digitva-yv2n`: enable minimal first-party app
telemetry, include approximate foreground use, and retain row-level interview
and coding timelines in internal submission data. Analytics runs on DigitVA's
own server. No third-party analytics service or row-level clinical sharing.

## Internal submission timelines

Reuse existing interview start/completion metadata and coding audit records.
Add only missing phase milestones. Interview milestones include start,
identity/early section saved, midpoint, review, submission start and server
receipt. Offline coding milestones include opened, DORIS processed and saved/submitted.
Online coding reuses durable server allocation, processing-audit and assessment
save timestamps, exposed as an additive `codingTimelineV1` on the existing
authorized case workspace. Its start is explicitly `coding_allocated`, not a
claimed editor-open timestamp; no extra client request is needed.
Store timestamped events in existing submission/draft metadata or coding
audit/provenance JSON; preserve them on offline retry, resume and import.
Use timezone-offset timestamps and bounded elapsed durations where available;
server receipt is distinguished from client submission attempt time.

Timeline metadata is separate from clinical answers and their integrity hash.
Validate fixed event names, timestamps, bounds and total event count; merge
idempotently. It remains row level inside DigitVA, under existing project and
case authorization, and never enters the performance telemetry payload.

## Minimal first-party performance collection

Enabled by owner request. Settings provides a visible off switch; turning it
off clears pending local performance batches and stops future collection and
upload. Already aggregated cells cannot be subtracted. Collection does not
block startup, form saves, coding or synchronization.

Collect daily aggregate foreground duration, launch count and sanitized
crash/error counts, with app/OS/build and coarse hardware dimensions: device
type, RAM/core buckets and bounded known manufacturer categories. Unknown
hardware values remain unknown. Use a lightweight native stats module independent
of ICD-11, so ordinary collectors do not load the coding engine.

General location is coarse country/state from existing authorized project or
profile context when it can be mapped to canonical codes; otherwise unknown.
Do not request GPS, infer precise position or call IP-geolocation services.

Never include interview answers, case identifiers, names, contacts, account or
stable device identifiers, attachments, certificates, recordings, raw logs,
request bodies, stack-local values or arbitrary exception messages. Clinical
phase timings remain exclusively in the internal timeline above. Crash codes
are a fixed allowlist; no error payload is copied to analytics.

## Own-server API and reports

Use an authenticated, bounded batch API on the enrolled DigitVA server. Seal a
small daily aggregate with a fresh random batch UUID for idempotent retries;
this UUID is not a persistent device identifier. Keep at most two daily batches
locally. Standalone use with no server stays local until a normal authenticated
server context exists; no public collector endpoint or third-party destination.

The server validates an exact low-cardinality schema and rejects clinical,
free-text or unknown fields. Redis stores aggregate counters and deduplication
keys with a 90-day TTL. Bound per-day cell cardinality and report scans. This is
best-effort performance data: a Redis flush can lose its history, never clinical
records or internal workflow timelines.

Admin-only performance API returns aggregates, not per-device/event rows.
Release/shared performance reports suppress groups with fewer than 20 accepted
batches. Reports label this as batch counts, not unique people or devices.
Release info, privacy wording and store Data Safety disclosures describe these
actual measurements and the off control.

## Non-blocking submissions

Save locally before enqueueing native submissions. Network uploads run in the
background with bounded timeouts and existing idempotency/acknowledgement rules.
Show saved/queued/sent states accurately; only a matching server acknowledgement
permits deletion. Preserve open editors and concurrent changes through upload
leases and snapshot checks. Telemetry failures never delay or fail clinical work.
