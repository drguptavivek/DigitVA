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

- Three explicit setup modes: server enrolment by QR or manual server/password,
  local-only standalone, and the separate demo server. Standalone setup/use
  requires explicit logout of every server account in both slots. Retained
  records are preserved; expiry alone does not enable standalone.
- Persistent standalone/server-disabled and demo mode banners, including forms
  and local unlock screens. Standalone shell actions never invoke server sync.
- Packaged WHO engine/data only; no first-setup, repair or explicit WHO update
  download. Eligible accounts have an account-scoped engine diagnostic.
- ICD-11/DORIS coding is off by default, with the first-run choice repeated in
  Settings. Online cases use their server; eligible local cases use the bundled
  engines. Enabling the choice does not grant project permissions or start engines.
- Plus bundles SmartVA in a separate native process. It runs after valid local
  completion and fills missing/stale results on coding entry; manual rerun remains.
  Its local
  advisory results use frozen project/profile options and are tied to the answers
  and engine version. Older drafts require an explicit settings repair.
- Either WHO interview refusal or data-processing refusal stops the interview.
  Only broad deceased age group and sex plus consent/system audit metadata remain.
  Fresh consent can reopen an unsent draft; version barriers prevent stale copies
  from restoring removed answers. Registration-only users can save minimal
  refusals, including through the encrypted offline queue.
- Standalone Settings edits English and Hindi consent notices locally. Existing
  draft consent records retain the rendered wording and hash they were shown.
- Settings includes offline software notices and project/profile access details.
  Active and Demo accounts with colliding identifiers fail closed before token or
  encrypted-store access; their data is never merged.
- Play builds open their own package listing for updates. Experimental sideload
  Plus remains a separate APK distribution.
- Manual password enrolment needs the new `/auth/password-enroll` server
  endpoint; no staging deployment is implied by the phone build. An older server
  returns a clear unsupported-enrolment response without a fallback endpoint.

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

The owner-approved temporary screenshot allowance also covers normal builds and
expires at `2026-11-25T08:12:11Z`, with foreground and timer checks. Recheck the
final artifact and its privacy declaration before distribution. Bundled Hindi
questionnaire review/redistribution and WHO offline software permission remain
open; a private test APK is not public release approval.

A submitted refusal that holds other open attempts remains held. There is no
in-app authorized release for that exceptional shared-case state yet
(`digitva-hs7e.15.2`); prior lawful submissions and identity remain intact.

Sources: [Play Data Safety](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en)
and [account deletion](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en),
checked 2026-10-28. Store review can recur for later releases; this package does
not guarantee a one-time approval.
