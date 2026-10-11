# Coder workspace visual verification

Reference: current HTMX coding workspace and its configured render modes,
using the same signed-in demo submission. The Expo browser implementation
now carries the full coding evidence presentation into a mobile-first layout.

## Final behavior checked

- A 52px icon rail selects categories directly at phone, tablet and desktop
  widths. Names/counts open in an optional slide-out. The rail stays reachable
  while scrolling; the slide-out scrolls when its contents exceed the viewport.
- Measured 390px and 768px CSS viewports had no horizontal overflow. Phone
  query/response cards use independent automatic-height rows without overlap.
  Desktop keeps the source hierarchy and grouped history columns.
- Disease history groups explicit Yes/No responses; other values remain visible.
  Configured reversed response colours and informational badges retain answers.
- Narration/Documents renders authenticated media, then narrative quality,
  then the consolidated interview summary. Social Autopsy retains its editor.
- COD Assessment renders summary, narration/documents, grouped disease history,
  saved Notes and the existing coding editor.
- The image lightbox opens, zooms, rotates, closes on Escape and restores focus.
  Keyboard focus no longer resets to Close after each action. Touch handlers,
  PDF downloads and audio cleanup have focused automated coverage.
- Notes opens as a phone sheet or desktop panel. Escape dismissal and focus
  return work. Quality-save refresh preserves the selected category and Notes
  drafts in automated tests.
- SmartVA shows status and existing actions. Masked Step 1 retains result
  withholding and explains that the result is not displayed in that step.

## Automated validation

Frontend: 66 suites, 741 tests; TypeScript check, web export and Android export
passed. Backend: 4,238 tests and 2,318 subtests passed; Ruff passed. Jest used `--runInBand --modulePaths` with the Expo node_modules path
to resolve the linked instrument vendor runtime. Backend regression and
attachment-count coverage use dedicated test databases.

## Corrections made during review

The first mobile table implementation overlapped responses; replaced intrinsic
row layout with explicit responsive rows. The initial rail appeared only on
narrow screens; it now appears at every width. Added focus trapping for phone
modals, scrollable navigation, PDF links, media detach cleanup and truthful
bounded-gallery notices. Attachment-count cache freshness is covered separately.

No clinical assessment, private note, or SmartVA run was submitted during
browser verification. This demo has no audio sample; actual browser audio
playback and physical-device touch acceptance were not performed. Temporary
viewport overrides were cleared. Screenshots are retained with this chat.

Prior visual QA result: passed.

## Component audit, 11 October

Yes/No badges were measured in the rebuilt maternal table: 16px text,
8px vertical padding, 16px horizontal padding, and 40px total badge height.
At 652px the document had no horizontal overflow. The compact form header
showed Age 74, Female, DEMO in that order.

Quality, social-autopsy, simple-COD and DORIS choices now import the actual
WHO VA native interview controls; the existing shared certificate component
retains its WHO structure. Full component inventory is in
`docs/current-state/coder-component-inventory.md`.

The browser account changed to Test CHO SC01 during verification and cannot
open the coding case. Final questionnaire visual checks and final sticky-rail
checks on that rebuilt case could therefore not be repeated. Existing focus,
selection and payload regression tests remain required.

Sign-out verification: the existing action issued POST logout (302), the
access API returned 401, and the sign-in landing persisted after reload. No
authentication code was changed. No clinical writes were submitted.

Final component checks: 67 suites / 746 tests, typecheck, web and Android
exports passed. Read-only quality audit found no material defects. Remaining
case visual verification is tracked as `digitva-uoe5`.
