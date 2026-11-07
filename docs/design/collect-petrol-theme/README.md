---
title: DigitVA Collect Petrol theme (design references)
doc_type: design
status: active
owner: engineering
last_updated: 2026-11-07
---

# DigitVA Collect Petrol theme

Design references for the Expo app (Android and iOS, one design). The sheets
below are mockups, not screenshots. The owner chose the direction on
2026-11-05 and approved building it on 2026-11-06.

## Direction

- Modern Cupertino style: native system fonts (SF Pro on iOS, Roboto on
  Android), grouped inset lists, a back chevron with the screen title in the
  top bar, and bottom sheets for pickers.
- Colour tokens written in OKLCH, converted to hex for React Native.
- Petrol primary with an amber accent. Red means error and green means
  success, and nothing else uses those colours.
- **Cards have no borders.** A card stands apart from the canvas by tone and
  a faint shadow (no shadow in dark mode). Rows inside a card are split by an
  inset hairline. Selected and error states use a tint fill, and secondary
  buttons are tint-filled, so a line is never drawn inside a line. The only
  outline is the focus ring on the field being typed in.
- Native icons: SF Symbols on iOS and Material Symbols on Android, mapped to
  the same meaning for each icon (`10-icons-sf-symbols.png` shows the iOS set).
- Frosted (blurred) bars on iOS only. Android uses a 92% opaque bar, because
  blur over long forms drops frames on mid-range phones.

## Tokens

| Token | Light | Dark | Notes |
| --- | --- | --- | --- |
| primary | `#1f4d60` oklch(39.7% 0.059 228) | `#6fb6d6` | white on light primary 9.2:1; dark-mode buttons use ink text |
| primary tint | `#d2e5ec` | `#1f3a47` | selected rows, chips, secondary buttons |
| accent | `#d6a24a` oklch(74.4% 0.121 78) | same | filled badges only, always ink text (6.9:1); never white text, never accent-coloured text |
| accent tint | `#fbe7c6` | `#3a2f1c` | attention row (Unsent) |
| canvas | `#e8edf0` | `#0f1418` | |
| card | `#ffffff` | `#1a2127` | |
| text | `#1b232a` | `#e8edf0` | |
| secondary text | `#5c6872` | `#9aa6af` | about 5.5:1; never used for Hindi or answer labels |
| error | `#b3261e` | `#f08a80` | error tint `#fbe9e7` / `#3a1f1d` |
| success | `#1f7a4d` | `#6cc796` | success tint `#dcefe2` / `#1b3326` |

## Rules taken from the design review

These came from a review of the five candidate palettes
(`00-palette-options-*.png`: Dusk, Lichen, Petrol, Heather, Graphite):

- **Why Petrol.** It is the same hue family as the logo's dark stroke.
- **Why not the others.**
  - Coral was dropped as Petrol's accent: it sits next to error red and fails
    for colour-blind users.
  - Lichen's green primary makes every button look like success.
  - Graphite cannot tell the active tab from the inactive ones.
- **Hindi.** Hindi questions and options use the same ink colour as English,
  at 16 pt; weight, not grey, makes the Hindi line secondary. Rows are at
  least 48 pt tall, or 56 pt with a Hindi line.
- **Required fields and errors.** A field shows "Required" in grey until Next
  is tapped, then a red message directly under that field and a red tint on
  the field.
- **Coding.** Part 1 shows a time interval for each line, Part 2 is present,
  and a whole cause line is tappable. ICD-11 codes are monospace chips.
  SmartVA's ICD-10 cause is plain grey text, never a chip.
- **DORIS.** The underlying cause is the only filled code chip on the screen,
  and the rule that selected it is shown. Search results have a fixed 64 pt
  code column.
- **Labels and Home.** Inactive tab labels are 12 pt in secondary text. The
  logo sits in the Home top bar, so the unsent count stays above the fold.

## Sheets

| File | Shows |
| --- | --- |
| `01-home-report-form-nqa-light.png` | Home, Report a death, WHO VA form, Narrative QA |
| `02-social-coding-doris-components-light.png` | Social Autopsy, coding view, DORIS result, components |
| `03-field-types-light.png` | short and long single choice, number with unit, stepper, out of range, multiple choice, date, list picker, text, long text |
| `04-bilingual-questions-*.png` | English and Hindi questions and options |
| `05-calendar-month-recording-location-*.png` | calendar sheet, month and year wheels with "not known", narrative recording, GPS capture |
| `06-camera-viewer-qr.png` | document camera, image viewer, QR scanner (always dark) |
| `07-document-photo-edit.png` | capture, corner adjust (straighten to a rectangle), Original / Document / Black & white, viewer with rotate and flip |
| `08-site-picker-filters-*.png` | hierarchical site drill down and search, filter menu, applied filter chips |
| `09-home-form-doris-fields-dark.png` | dark mode |
| `10-icons-sf-symbols.png` | iOS icon set in theme colours |

## Frozen screens

Owner 2026-11-06: each built screen is checked on the emulator, reviewed by a
design reviewer, the agreed changes are applied, and then the screen is frozen.
A frozen screen changes only for a bug or with the owner's approval. Its
reference screenshots live in `frozen/`.

| Screen | Frozen on | Reference |
| --- | --- | --- |
| Sign in | 2026-11-06 | `frozen/sign-in.png` |
| Home | 2026-11-06 | `frozen/home.png` |
| Interviews (empty) | 2026-11-06 | `frozen/interviews-empty.png` |
| Profiles on this phone | 2026-11-06 | `frozen/profiles.png` |
| Unlock | 2026-11-06 | `frozen/unlock.png` (ink gaps 12.2 / 24.0 / 24.4 dp) |
| Sync sheet | 2026-11-06 | `frozen/sync-sheet.png` |
| Register a death | 2026-11-06 (refrozen 2026-11-07) | `frozen/register.png`, `frozen/register-2.png`; with the location control (Android, Test CHO SC01, project chooser shown): `frozen/register-multi-project.png`, `frozen/register-location.png`, `frozen/register-location-captured.png`; light, dark, high contrast and Large text (in-app Large) each in `frozen/dark/`, `frozen/high-contrast/`, `frozen/large-text/` as `register-multi-project.png` and `register-location.png`; iOS (Test ALL): `frozen/ios/register*.png`, `frozen/ios/high-contrast/register*.png` |
| Account sheet | 2026-11-06 | `frozen/account-sheet.png` |
| Settings | 2026-11-06 | `frozen/settings.png` to `frozen/settings-5.png` |
| Public demo gate | 2026-11-06 | `frozen/demo-gate.png` |
| Sign in (mobile number) | 2026-11-06 | `frozen/sign-in-mobile.png` |
| Large text (Settings, Home, Interviews, Register, Account sheet) | 2026-11-06 | `frozen/large-text/` |
| High contrast (same five) | 2026-11-06 | `frozen/high-contrast/` (every measured pair at least 8.8:1) |
| Register date picker (light) | 2026-11-06 | `frozen/register-date-picker.png` |
| Home with a draft | 2026-11-06 | `frozen/home-with-draft.png` |
| Interviews list with cases | 2026-11-06 | `frozen/interviews-list.png` |
| Local cases, case view | 2026-11-06 | `frozen/cases/` |
| Coding and Review queues (iOS, Test ALL, SADEMO) | 2026-11-07 | `frozen/ios/coding/` (`code-random-available.png`, `code-my-coded.png`, `review-queue.png`, `tabbar-6.png`); light, with `dark/` and `large-text/` variants |
| Help sheet, Common questions | 2026-11-06 | `frozen/help/` |
| Try DORIS, Offline engine check | 2026-11-06 | `frozen/collect-plus/` |
| Dark mode (Sign in, Profiles, Unlock, Home, Interviews, Register, Account sheet, Settings) | 2026-11-06 | `frozen/dark/` |
| WHO VA form pages and its sheets (more actions, questionnaire language, Sections) | 2026-11-06 | `frozen/form/` |
| Coding queue (Pick a case, My coded cases) | 2026-11-06 | `frozen/coding/` |
| Offline profile (light and dark) | 2026-11-06 | `frozen/collect-plus/offline-profile*.png`, `frozen/dark/offline-profile*.png` |
| Register date picker (dark) | 2026-11-06 | `frozen/dark/register-date-picker.png` (header year 5.5:1) |
| Consent dialog | 2026-11-06 | `frozen/form/form-consent-dialog.png` |
| Interviews list with a registration-only card | 2026-11-06 | `frozen/interviews-list-2.png` |
| Home and Interviews list (iOS, Test CHO SC01, TST001; More sheet not refrozen) | 2026-11-07 | `frozen/ios/home-interviews/` (`home.png`, `interviews-list.png`); `dark/` and `large-text/` variants |
| Case view: SmartVA and workflow history (light and dark) | 2026-11-06 | `frozen/cases/case-view-4.png`, `-5.png`; `frozen/dark/case-view-4.png`, `-5.png` |
| Tab bar with Code and Review | 2026-11-07 | Test ALL, five tabs (iOS only; no Test ALL profile on the Android emulator): `frozen/ios/tabbar-coder.png`, `frozen/ios/high-contrast/tabbar-coder.png`. Test CHO SC01, four tabs: `frozen/tabbar-cho.png`, `frozen/dark/tabbar-cho.png`, `frozen/high-contrast/tabbar-cho.png`, `frozen/large-text/tabbar-cho.png`, `frozen/ios/tabbar-cho.png` |
| iOS dark (Register top, Place card idle and captured, tab bars) | 2026-11-07 | Test CHO SC01 (project chooser shown): `frozen/ios/dark/register-multi-project.png`, `register.png`, `register-location.png`, `register-location-captured.png`, `tabbar-cho.png`; Test ALL five tabs: `frozen/ios/dark/tabbar-coder.png` |

| Android Place card, location captured (Test CHO SC01, Site and unit stays visible), light, dark, high contrast, Large text | 2026-11-07 | `frozen/register-location-captured.png`, `frozen/dark/register-location-captured.png`, `frozen/high-contrast/register-location-captured.png`, `frozen/large-text/register-location-captured.png` |
| Android five-tab bar (Test ALL: Home, Register, Code, Review, Sync), light, dark, high contrast, Large text | 2026-11-07 | `frozen/tabbar-test-all.png`, `frozen/dark/tabbar-test-all.png`, `frozen/high-contrast/tabbar-test-all.png`, `frozen/large-text/tabbar-test-all.png` |
| iOS Large text (accessibility-large; Test ALL: Home, five-tab bar, Register, Place card), light and dark | 2026-11-07 | `frozen/ios/large-text/{home,tabbar-coder,register,register-location}.png`, `frozen/ios/large-text/dark/` (same four); Debug banner wraps in full, DEMO chip and avatar initials fit, tab labels fit |
| Coding tab: Available / My coded cases segmented control, Review queue, six-tab bar (Test ALL, SADEMO: Home, Interviews, Register, Code, Review, Sync), light, dark, high contrast, Large text | 2026-11-07 | `frozen/coding/code-random-available.png`, `frozen/coding/code-my-coded.png`, `frozen/review-queue.png`, `frozen/tabbar-6.png`; the same four names in `frozen/dark/`, `frozen/high-contrast/`, `frozen/large-text/` |

## Owner decisions (2026-11-06)

- **Register fields stay 44 dp.** They are the WHO form package's own
  controls, shared with the interview form and the web form; every other app
  field is 48 dp. 44 dp meets the touch-target minimum. Recorded exception.
- **WHO hint text stays.** The hints on Id10002 and Id10003 keep WHO's
  wording; only their colour follows the app (muted, never error red).
- **Sign-in code and the full guide open in the system browser.** "I have a
  sign-in code" and "Open the full guide" hand off to Chrome (or the phone's
  browser) by design; the app never handles the sign-in page itself.

## Regenerating

The generators are in `scripts/design-mockups/`:

- **Phone sheets:** `petrol.py <light|dark> <screen,screen,...> <n>` writes
  `p-<mode>-<n>.html`.
  - Run it in a scratch folder holding a copy of
    `mobile/digitva-collect/assets/icon.png`.
  - Render the HTML with headless Chrome (`--screenshot`,
    `--force-device-scale-factor=2`, `--window-size=1560,800`).
- **Icon sheet:** `swift icons.swift out.png` draws the SF Symbols sheet. It
  needs macOS.

The names, places and clinical details in the mockups are made up.
