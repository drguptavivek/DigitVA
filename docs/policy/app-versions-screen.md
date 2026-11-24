---
title: App Versions Screen
doc_type: policy
status: active
owner: engineering
last_updated: 2026-11-24
---

# App versions screen

Owner request 2026-11-24 (`digitva-jrzd`): a screen showing which people run
which collection app version in a project, so old APKs in the field are
visible before a deploy or a release. Phones running 0.3.15 to 0.3.28 are in
field use, so the screen is additive only: it changes no existing route,
reply or phone-facing API.

## Who may see it

- The same callers, and the same refusal, as the project's People roster
  (`_guard(project_id, roster=True)`, access-control-model.md "Project
  membership"): an admin for any project, the project's PI, and a
  project-scope data manager of that project. Anyone else, including a data
  manager of another project, gets the roster's 403. An unknown project is
  404.
- Coders, interviewers and other roles are refused.

## What it shows

Read-only. It changes nothing and records nothing.

1. **Summary**, one row per `(platform, app_version)` over the project's
   active devices (`auth_devices.project_id` is the project and
   `revoked_at` is empty): active devices, devices seen in the last 7 days,
   devices seen in the last 30 days (`auth_devices.last_seen_at` within that
   many days of now), the latest last-seen time, and `behind_latest`.
2. **People**, one row per person and device: a person with a device
   session last seen in the last 30 days (live or expired: an old app whose
   session lapsed is the one to find) on an active device of this project, who is on the project's roster
   (`on_project_roster`: member, active grant in the project, or worker in
   it). Fields: display name, the person's active roles in this project,
   platform, app version, the person's last-seen time on that device (the
   session's), the device's enrolment time, and `behind_latest`. A person
   taken off the roster is left out even if seen on a project device. The list is filtered by version on the server and capped at 500
   rows, newest activity first, with the total given.

So the summary counts devices (a shared phone counts once) and the people
list counts people seen in the last 30 days; the two need not add up.

Never shown: email, phone, device id, device name, device secret, signing
keys, IP address.

## Behind the latest release

- The latest release is the APK the server hosts for download
  (`hosted_android_apk`, the source `/api/v1/app/android/latest` serves);
  there is no second version pin.
- A version is compared numerically as `major.minor.patch`
  (`0.3.9` is behind `0.3.10`). A version ending `-plus` is compared with
  the hosted Collect Plus release; any other version with the normal one.
  The app today reports Plus builds without the suffix, so those are
  compared with the normal release.
- `behind_latest` is `true` when the version is lower than that release,
  `false` when equal or higher, and `null` (unknown) when the platform is
  not Android, the version is missing or does not start with
  `major.minor.patch`, or the server hosts no release for that variant.
