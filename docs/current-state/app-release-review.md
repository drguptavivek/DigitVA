---
title: Unified App Release Review Information
doc_type: runbook
status: active
owner: engineering
last_updated: 2026-10-28
---

# DigitVA 0.3.12 release review information

Tracks `digitva-6rxf`, `digitva-a770`, `digitva-65m5`, `digitva-yv2n`,
`digitva-et16` and `digitva-6o4b`. This is preparation, not a store submission.

## User-visible changes

- Shared online coding workspace and Local cases / Online cases navigation.
- Local ICD-11/DORIS only for authorized self-coding projects in experimental
  Plus; the public engine-free variant uses the server for online coding.
- One local profile form, with optional details collapsed at first run.
- Background queued native submissions with timeouts, exact acknowledgements
  and protections for open coding editors and concurrent changes.
- Three active device logins per account; self-service, admin and scoped
  data-manager decommissioning preserves encrypted unsent work.
- Settings permission checks, account deletion/request and privacy links.
- Internal submission interview/coding timelines; optional minimal first-party
  performance diagnostics with approximate foreground use and off switch.

## Reviewer paths

Use the dedicated demo environment and synthetic examples only. Sign in to
Demo, collect a synthetic interview, inspect queued/sent state, and code the
online case when the demo project grants coding access. Settings contains
permissions, devices, diagnostics and Delete my account. Demo deletion asks
for the password; staff accounts file a request for the programme to confirm.
The signed-in website Profile also exposes deletion and device management.
External deletion information: `/data-requests` on the configured server.

## Privacy and distribution

Diagnostics go only to the enrolled DigitVA server's own analytics API.
Internal phase timelines remain row-level submission data under existing case
access. Performance reports contain aggregates only, with small-cell suppression.
No external analytics SDK, raw logs, clinical payloads or stable device IDs are
sent as diagnostics. Privacy and Data Safety text must match the final artifact;
see `docs/policy/app-performance-telemetry.md` and the Play listing package.

Play AAB is the store path; APK downloads remain supported. The offline engine
bundle stays experimental and is not newly published until the recorded WHO
licence boundary is resolved. Existing installed APKs keep their server contract.
Local debug builds/HMR are for emulator testing and do not authorize a deploy,
Play upload, or release publication. Signing/upload choices remain with owner.

Sources: [Play Data Safety](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en)
and [account deletion](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en),
checked 2026-10-28. Store review can recur for later releases; this package does
not guarantee a one-time approval.
