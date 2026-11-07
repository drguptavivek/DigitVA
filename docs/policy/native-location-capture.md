---
title: Native Location Capture (Collect and Collect Plus)
doc_type: policy
status: active
owner: engineering
last_updated: 2026-11-07
---

# Native location capture

Scope: the optional "Capture location" control on the native death
registration form of DigitVA Collect and Collect Plus (Android and iOS),
bead `digitva-b3hl`. It is the phone counterpart of the web control
described in `docs/policy/web-intake.md` ("Death-site GPS location"). The
WHO VA 2022 instrument has no geopoint question; none is added to it.

## Rules

- **Permission only on a tap.** The app asks for location permission only
  when the user presses "Capture location", never on launch or on opening
  the form. It asks for when-in-use (foreground) permission only. Background
  location is never requested and is blocked in the Android manifest.
- **One reading per tap.** The position is read once, never watched or
  tracked. A denied permission, a timeout or no fix shows a short message;
  the registration still saves without a location.
- **Coarser fix allowed.** If the high-accuracy read fails (for example the
  Android "Location Accuracy" dialog is declined, or iOS is not ready right
  after the first grant), the app retries once at balanced accuracy without
  the settings dialog, then accepts a cached fix no older than 2 minutes
  with accuracy of 500 m or better. Such a fix is stored with its real
  `accuracy_m` and shown to the user, who may retake or clear it. "Not
  available" appears only when all three reads fail.
- **Warmup.** While the registration screen is focused and foreground
  permission is already granted (checked without prompting, never asked on
  open), the app watches the position to keep the best recent fix ready. The
  fix lives in memory only: never stored, logged or sent. The watch stops
  when the screen loses focus, unmounts or the app goes to the background. A
  fix of 100 m or better, no older than 60 seconds, answers a tap at once
  (its accuracy still shown); otherwise the tap reads as above. Nothing is
  saved to the registration until the user taps "Capture location". A first
  grant from the tap starts the warmup too. The warmup never shows the
  Android "Location Accuracy" dialog (`mayShowUserSettingsDialog: false`);
  if the watch fails, warmup stops silently without retry. Only the tap's
  first High read may show that dialog, once.
- **Android fallback.** If the "Location Accuracy" dialog is declined, the
  read falls back to the balanced read, then to a High read without the
  dialog (15 s), which the fused provider serves from the GPS provider when
  network location is off, then to a recent cached fix, instead of failing.
- **What is stored.** Only the fields the server already has: `latitude`,
  `longitude` and `accuracy_m` (metres, when the device gives one). The
  accuracy is shown to the user beside the captured fix. `captured_at` is
  server time at save, never a client claim.
- **Offline.** GPS needs no network. An offline registration queues the fix
  with the rest of the registration and sends it when the queue syncs.
- **Sensitive data.** Coordinates locate a household and are treated as PII
  with the same audience as the address. They are never logged, never put
  in telemetry or error reports, and leave the phone only inside the
  registration payload (`POST /api/v1/intake/deaths`, or the correction
  `PATCH /api/v1/intake/deaths/<death_id>`), the same fields the web sends.
- **Consent.** The fix is withheld from a new registration when address
  consent is not granted: it shares the address's audience.
- **Deletable.** While a registration may be edited, "Clear" removes the fix
  and the correction sends `null` for all three fields.
