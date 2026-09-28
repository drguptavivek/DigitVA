---
title: Web VA questionnaire visual pass (before/after)
doc_type: design
status: proposed
owner: engineering
last_updated: 2026-09-29
---

# Web VA questionnaire visual pass

Bead `digitva-cbn`. Screenshots are of the vendored package's own Vite demo
(`vendor/who-va-2022`, `pnpm dev:vite`) with the demo chrome hidden, at phone
width (390 px, 2x) and desktop (1280 px). The Hindi views apply the package's
bundled `src/languages/hi.ts` draft with `show-english` on, which is how a
translated form looks in DigitVA. Nothing under `app/static/vendor/` has been
rebuilt yet: the owner approves these screenshots first (see "Vendoring").

## Before / after

| View | Before | After |
| --- | --- | --- |
| First section, tabs, nav (phone) | `before-section1-phone.png` | `after-section1-phone.png` |
| First section, tabs, nav (desktop) | `before-section1-desktop.png` | `after-section1-desktop.png` |
| Single choice, answered (phone) | `before-single-choice-phone.png` | `after-single-choice-phone.png` |
| Single choice, answered (desktop) | `before-single-choice-desktop.png` | `after-single-choice-desktop.png` |
| Multiple choice, two selected (phone) | `before-multiple-choice-phone.png` | `after-multiple-choice-phone.png` |
| Multiple choice, two selected (desktop) | `before-multiple-choice-desktop.png` | `after-multiple-choice-desktop.png` |
| Number question (phone) | `before-number-phone.png` | `after-number-phone.png` |
| Number question (desktop) | `before-number-desktop.png` | `after-number-desktop.png` |
| Date question (phone) | `before-date-phone.png` | `after-date-phone.png` |
| Date question (desktop) | `before-date-desktop.png` | `after-date-desktop.png` |
| Validation errors after Next (phone) | `before-validation-phone.png` | `after-validation-phone.png` |
| Validation errors after Next (desktop) | `before-validation-desktop.png` | `after-validation-desktop.png` |
| Hindi with English alongside (phone) | `before-hindi-phone.png` | `after-hindi-phone.png` |
| Hindi with English alongside (desktop) | `before-hindi-desktop.png` | `after-hindi-desktop.png` |

## What changed, and why

All changes are in `vendor/who-va-2022/src/ui` (plus the theme, the
web-component attribute list and the UI message templates). Questionnaire
logic, validation and the engine are untouched; every `testID`, role and
accessibility label is kept.

1. **Section tabs.** The "started" dot floating over the tab's corner and the
   "✓" badge are gone. Each tab is now a label over a thin progress track:
   half-filled when the section is started, full plus a leading "✓" when its
   required answers are complete, red-tinted when it has issues, brand-filled
   when active. `section-status-<name>` still identifies the status element
   (the "✓" glyph on complete, the fill bar on started).
2. **Radio and checkbox affordances.** Single-choice rows carry a 22 px
   radio circle, multiple-choice rows a checkbox square, filled in brand on
   selection; the row stays the touch target (min 48 px tall). The
   `Pressable` keeps `role="radio"`/`"checkbox"`, the indicator is
   `aria-hidden`.
3. **"English (English)" twice.** Root cause: the language picker
   (`SearchableSingleChoice`) put the selected choice's label into the search
   box as its *value* and also listed it, tinted, in the always-open option
   list. Not a duplicate option, not a locale-label bug. The box is now a
   filter only; the selection shows once, as the marked row.
4. **WHO codes.** `(Id10010b) Sex of VA interviewer` renders as a small muted
   monospace chip `Id10010b` above the plain label (`question-code-<name>`),
   in the form, the English-alongside line and the answer preview. Codes are
   untouched in data, in accessibility labels and in validation messages. A
   host can drop the chip with `showQuestionCodes={false}` (React) or the
   `hide-question-codes` attribute (web component); the default keeps it.
5. **One surface per section.** Questions are separated by a rule inside a
   single section card instead of each being its own bordered card; an
   invalid question gets a red left bar. Type scale is 16/24 labels, 14/20
   hints, 13/19 English, 22/30 section title, 16/24 choices, with explicit
   line heights everywhere so Indic matras are not clipped.
6. **Draft status line.** "Draft saved · <uuid>" came from the package
   (`src/i18n.ts` `draftSaved`/`draftId` templates, rendered at the end of
   `create-who-va-form.tsx`), not from `va_intake_form.html`, whose own
   `#wv-save-state` never showed the id. The English, French and Hindi
   templates now read "Draft saved" / "Draft not saved yet"; the
   `(id) => string` message signatures are unchanged so a host template may
   still interpolate `{id}`.
7. **Bottom nav.** Save and Preview are icon *plus* label ("Save draft",
   "Preview answers"); Back is secondary, Next primary, all 44 px tall,
   right-aligned. Existing `aria-label`s are kept.
8. **Accent and motion.** Theme defaults move to the host's blue
   (`--who-2022-web-color-brand` #1b4f9c, `-brand-deep` #004687,
   `-brand-soft` #eaf1fa; `app/static/css/base.css` uses #004687/#005a9c).
   White on #1b4f9c is 7.9:1, muted #667085 on white 4.6:1. Section and
   issue scrolling honour `prefers-reduced-motion` (`animated: false`,
   `scrollIntoView` behaviour `auto`).
9. **Demo CSS.** `demo/style.css` no longer re-cards every question or
   forces the old 112 px tab width, so the demo shows what the package draws.

## Round 2: section navigation redesign (`after-v2-*`)

Owner-approved round 1, then asked for a stepper in the style of the
reference designs, laid out by the form's own width. Round 2 supersedes the
`after-*` captures above; the `after-*` files are kept as the approved
round-1 state.

| View | File |
| --- | --- |
| First section, fresh form (phone 390 / tablet 820 / desktop 1280) | `after-v2-section1-phone.png`, `after-v2-section1-tablet.png`, `after-v2-section1-desktop.png` |
| After consent + adult, on section 4 of 15 (statuses, nesting) | `after-v2-progress-phone.png`, `after-v2-progress-tablet.png`, `after-v2-progress-desktop.png` |
| Phone drawer open | `after-v2-drawer-phone.png` |
| Validation errors after Next | `after-v2-validation-phone.png`, `after-v2-validation-desktop.png` |
| Hindi with English alongside | `after-v2-hindi-phone.png`, `after-v2-hindi-desktop.png`, `after-v2-hindi-drawer-phone.png` |

### The section count is not fixed

Measured with the real engine; to reproduce, from `vendor/who-va-2022`
(`pnpm exec tsx` on this, with each scenario's `initialData`):

```ts
import { createWhoVaSession } from "./src/engine/session.ts";
import { createWhoVa2022Instrument } from "./src/instrument.ts";
import { ALL_DIGITVA_EXTENSIONS } from "./src/digitva-extension.ts";
const consent = { Id10013: "yes", Id10020: "yes", Id10022: "yes", Id10023_a: "2026-07-17" };
const core = createWhoVa2022Instrument([]); // (g): createWhoVa2022Instrument(ALL_DIGITVA_EXTENSIONS)
const session = createWhoVaSession(core, { initialData: { ...consent, Id10019: "male", Id10021: "1980-01-01" } });
console.log(session.getSnapshot().visibleSections.map((s) => s.name));
// (a) {}  (c) female, born 1996-01-01  (d) born 2022-07-17  (e) born 2026-06-20  (f) (b) + Id10077: "yes"
```


| Scenario | Visible sections | Names |
| --- | --- | --- |
| (a) fresh form | 3 | Interviewer, presets, respondent_backgr |
| (b) consent yes + adult male (born 1980) | 15 | + info_on_deceased, narrat, med_hist_final_illness, injuries_accidents, illhistory, illdur, signs_symptoms_final_illness, risk_factors, health_service_utilization, vital_reg_certif, deathcert, consented |
| (c) consent + adult female, 30 | 18 | (b) + pregnancy_women, group_maternal, deliverytype |
| (d) consent + child (born 2022) | 15 | (b) minus risk_factors, plus neonatal_childA |
| (e) consent + neonate (27 days) | 18 | (b) minus med_hist_final_illness/risk_factors, plus stillbirth, neonatal_childC, neonatal_childA, neonatal_childB, mother_deliv |
| (f) adult male + injury yes | 16 | (b) + injuries_accidents_yes |
| (g) all DigitVA extensions + adult male | 17 | (b) + digitva_documents, socioeconomic (social autopsy; reachinghealthcare and eventchronology are gated further) |

The WHO core has 30 sections, 4 top-level, nesting to depth 5; 26 carry
questions (1 to 164, median 7) and are the pages the engine steps through
(`deceased_CRVS` and `neonatal_child` hold no questions and never page).
Symptom-gated pages (breathdur, paindur, abdominal_pain) appear mid-interview.

### What the stepper does about it

- Items are keyed by section name, so a section appearing or vanishing does
  not move the current one; the total is always the current visible count
  ("Section 4 of 15" means 15 now). While fewer than a third of the
  instrument's pages are visible (the pre-consent state: 3 of ~32) a muted
  "More sections appear as you answer" note sits under the list; it goes
  away once consent and age group have opened the form up. A section that
  has just appeared fades in over 400 ms, 0 ms under `prefers-reduced-motion`.
- **Wide (form >= 900 px):** vertical stepper rail beside the questions
  (`section-rail`, sticky). Circles: empty ring = not started, half-filled
  ring = in progress, ring + tick = complete, red ring + "!" = has issues,
  filled brand circle + white dot = current; the line is brand-coloured up
  to the current step. Names wrap, never truncate. Nested sections are
  indented under their parent page (Health history > Duration of illness,
  Signs and symptoms, ...); a parent that is not a page (WHO
  `deceased_CRVS`, DigitVA `socialautopsy`) becomes a small uppercase
  heading; WHO's "Interview completion" (`consented`) is such a heading
  too, because the engine pages its own three questions after all of its
  children. Collapsible groups were considered and not built: the list peaks
  at about 20 items, fits the rail without scrolling, and folding a group
  would hide the per-section status the stepper exists to show.
- **Medium and narrow (< 900 px):** horizontal stepper across the top; the
  current section's name starts under its circle. When the circles would
  need a pitch under 34 px (phone: more than ~11 sections) it collapses to
  "N done" - brand line - current circle - grey line - "M left" with
  "Section x of y . name" beneath, rather than shrinking. The whole strip is
  the drawer toggle (`section-drawer-toggle`, `aria-haspopup="dialog"`);
  the drawer (`section-drawer`, `role="dialog"`, `aria-modal`) holds the
  full vertical stepper, traps Tab, closes on Escape and on the scrim,
  and returns focus to the strip. It appears in place, so there is no
  motion to reduce. Verified in the rebuilt bundle with Playwright: focus
  lands on the close button, Shift+Tab wraps to the last item, Escape
  closes and focus returns to the toggle.
- **Controls kept and removed.** The "<" ">" arrows and the scrolling tab
  strip are removed: Back / Next in the footer already step sequentially,
  and the rail / drawer are the random-access controls, so labelled
  Previous/Next section buttons up top would have been a second copy of the
  footer. Footer: Back (secondary), Save draft and Preview answers
  (secondary, icon + label, smaller on phones), Next with an arrow
  (primary). On phones (< 600 px) Save/Preview sit on a small row above a
  full-width Back | Next row.
- **Validation messages** drop the leading WHO code in the form
  ("Name of VA interviewer is required"); `onValidation` / `who-va-validation`
  payloads and `validate()` results keep the engine's full message.
- **Label-left on wide forms:** label, code chip, hint and English sit in a
  left column (36 %, max 300 px) with the control on the right, as in the
  references; notes stay full width. WHO's longer labels wrap to three or
  four lines in that column (see `after-v2-progress-desktop.png`,
  Id10487) but the control column gains width for choice lists, so it
  reads better than stacked; below 900 px everything stacks.
- **Paging proposal (not implemented, engine-level):** the 1-2 question
  pages (`consented` with 3, `injuries_accidents` with 2, `paindur` with 3,
  `deliverytype` with 3, `mother_deliv` with 3) could be merged into their
  parent page presentationally; the WHO XLSForm groups them for skip logic,
  not for pacing. That changes `session.next()` and the draft's
  `currentSection`, so it is for a separate bead.
- Kept: `section-slider-item` on every rail/drawer item, `section-status-<name>`
  on the circle once a section is touched (tick "✓", "!" for issues, half
  ring for started), accessibility labels ", completed" / ", started" /
  ", has issues". New: `section-rail`, `section-drawer-toggle`,
  `section-progress`, `section-drawer`, `section-drawer-close`,
  `section-drawer-scrim`, `section-drawer-overlay`.
- New UI strings (English, French, Hindi): `sections`, `close`,
  `sectionsDone`, `sectionsRemaining`, `moreSectionsNote`.
- Theme tokens added in `web-theme.ts`: `overlayPosition` (fixed),
  `stickyPosition` (sticky), `entryTransition` (opacity fade, honours
  reduced motion). `--who-2022-web-form-max-width` default 48rem -> 64rem
  to fit the rail; the host page sets none of these variables.

### Vendored bundle

Rebuilt on this branch with `tooling/who-va-2022` (`npm install`, then
`node build.mjs && node check.mjs`); the tooling lock file is updated in the
same commit. `check.mjs` reports the same figures as before (524 questions,
35 sections, ABHA constraints, two relevant image slots at count 2). The
built file was smoke-tested in Chromium under the tooling's react 18 /
react-native-web 0.19 pins: sticky rail on desktop, fixed drawer with focus
trap on phone, stripped validation message, no console errors.

## Round 3: field controls, drawer above the host, performance (`after-v3-*`)

Owner requests after the round-2 merge (`409459d`, main `1df15ec`). All
captures are of the **built bundle** on a static host page carrying a
fixed 56 px navbar with `z-index: 1000` (the DigitVA case), at phone 390,
tablet 820 and desktop 1280, plus 375 for the drawer bug; the Hindi ones
use the package demo with the bundled Hindi draft.

| Change | Files |
| --- | --- |
| Drawer above the host navbar (phone 375 / 390 / tablet 820) | `after-v3-drawer-under-navbar-{phone375,phone,tablet}.png` |
| Rail at desktop, and at a short 1280x720 viewport with 17 sections | `after-v3-rail-desktop.png`, `after-v3-rail-short-viewport-1280x720-desktop.png` |
| Header shows only "Section x of y" | `after-v3-section1-header-{phone,tablet,desktop}.png` |
| Horizontal stepper with 17 sections (collapsed on phone, full on tablet) | `after-v3-stepper-17-sections-{phone,tablet}.png` |
| Next scrolls the new section's top under the navbar | `after-v3-next-scrolls-to-top-{phone,tablet,desktop}.png` |
| Number field: 99 typed, then "-" pressed; unit "years" | `after-v3-number-99-*`, `after-v3-number-step-*`, `after-v3-number-unit-years-*`, `after-v3-hindi-number-*` |
| Choice grid: 3 options (Id10020, Id10022), 4 options (Id10487), long labels stay single-column (Id10058) | `after-v3-grid-3-options-*`, `after-v3-grid-3-options-b-*`, `after-v3-grid-4-options-*`, `after-v3-grid-long-labels-single-column-*`, `after-v3-hindi-grid-3-options-*` |
| Interviewer instructions (age_group, age_adult) | `after-v3-instruction-age-group-*`, `after-v3-instruction-age-adult-*` |
| Date as DD-MMM-YYYY, and an impossible date | `after-v3-date-*`, `after-v3-date-invalid-*`, `after-v3-hindi-date-*` |

### What changed

1. **Drawer above the host.** Every react-native-web `View` is
   `position: relative; z-index: 0`, so nothing inside the form could rise
   above DigitVA's fixed navbar. The drawer now renders through
   react-native's `Modal` (a new optional `Modal` primitive; web passes
   react-native-web's, which portals to `document.body`; native passes
   React Native's), `transparent`, `animationType="none"`. Focus trap,
   Escape, scrim, focus return, `aria-modal` and the testIDs are unchanged;
   the panel still opens from the right. Theme variables must be on `:root`
   (the demo's are, DigitVA sets none): a portal is outside any wrapper.
2. **Rail scrolls on its own.** `position: sticky; top:
   var(--who-2022-web-sticky-top, 64px); max-height: calc(100vh - top - 8px);
   overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin`
   (`stickyRail` theme token). The current item is kept in view inside the
   rail only (`scrollTo` on the rail, never the page). The questions keep
   scrolling with the window. Hosts set `--who-2022-web-sticky-top` to their
   fixed bar's height.
3. **Header strip** shows only "Section x of y"; the section name stays in
   the strip's accessible name ("Sections: Section 4 of 15 · Information on
   the Deceased"). The strip now measures its own width and collapses to
   "N done - line - current - line - M left" whenever
   `20 + (n-1) * (20 + 2*6 + 12)` px would exceed it (`stepperFits`, tested
   at 788 / 568 px with 17 and 30 sections), so it never overflows; before
   the first layout a list longer than 8 is drawn collapsed. The row is
   `overflow: hidden` as a belt.
4. **Section change scrolls to the top** of the form (`scrollIntoView` on
   the form shell, `block: "start"`, `behavior: "auto"` under reduced
   motion; `scroll-margin-top` = the sticky-top variable so the stepper and
   heading land below the navbar) and moves focus to the section heading
   (`role="heading"`, `aria-level=2`, `tabIndex=-1`, `section-heading`).
   Applies to Next, Back, rail, drawer and history alike, since it keys off
   the current section, not the control that changed it. Window scroll on
   the web; the ScrollView on native.
5. **Number fields** (`NumberField` around Integer and Decimal): a box sized
   to the constraint's digit count between "-" and "+" (44 px, `Decrease` /
   `Increase`, `question-<name>-decrease/-increase`), `inputMode`
   numeric/decimal, autocorrect/capitalize/spellcheck off, Indic digits
   (Devanagari through Malayalam) normalised to ASCII on input
   (`asciiDigits`; the stored value stays the engine's number), non-digits
   stripped for integers. "-" never goes below the constraint's literal
   minimum, "+" stops at its literal maximum, typing is never blocked, so
   "99 if you do not wish to disclose" still goes in; a bound on another
   answer (`${ageInDaysNeonate}`) leaves the button open. Decimal boxes show
   "0.0". Units come from the English label/hint only when exactly one unit
   word occurs (`numericUnit`: days, months, years, hours, minutes, weeks,
   grammes; localized), so "How many (months/years)" gets none and "Age of
   VA interviewer" gets none. There is no decimal question in the WHO core
   or the DigitVA layers, so the decimal placeholder is covered by tests only.
6. **Choice grid.** A single or multiple choice list with at most six
   options, every label at most 24 code points in the shown locale, no
   explicit column appearance and no search becomes a row-major grid of
   equal-width cells: as many columns as options up to the form's cap
   (2 compact, 3 medium, 4 wide, passed as `choiceColumns`), reduced while
   a cell would be under 96 px; the last odd cell keeps the same width,
   left-aligned. The wrapper measures its own width once (`onLayout`).
   Indicators, roles, order and testIDs are unchanged.
7. **Interviewer instructions.** A label wrapped in `[...]` in the shown
   locale (7 WHO questions) loses its brackets, gets a small "Interviewer"
   tag and an italic, guidance-coloured style, and its accessible name is
   "Interviewer instruction: ..." (`instructionLabel`, tested with
   whitespace, Hindi and a translation without brackets). Data, translations
   and payloads untouched.
8. **Dates as DD-MMM-YYYY.** Day box, month select (localized short names
   via `Intl`, a numeric box without a `Select` primitive), year box in one
   field, auto-advancing, plus a calendar button that opens the native
   picker through a hidden `<input type="date">` (`showPicker()`), which
   also carries the constraint's `min`/`max` (`dateBounds`: `today()` and
   literal dates). The stored value is still ISO `YYYY-MM-DD`; a partial
   entry stores nothing and shows nothing; an impossible date (31-Feb)
   stores nothing and shows "Enter the date as DD-MMM-YYYY, for example
   16-Jul-1986". `role="group"` labelled by the question, each part named
   Day / Month / Year, the format hint under the field always visible and
   linked with `aria-describedby`. Preview and the native `pickDate` button
   show DD-MMM-YYYY too (`formatDdMmmYyyy`). Time and datetime boxes are
   sized compactly; there is no datetime question in the instrument, so the
   three-part pattern was not extended to them.
9. **Inline messages** never restate the label: a required-empty issue
   shows "This question is required." and any other message loses the
   leading label the engine puts there (`inlineIssueMessage`). Payloads
   (`onValidation`, `who-va-validation`, `validate()`), the section list and
   the summary keep the full message.
10. **Attachment controls without a host service** (DigitVA passes none
    yet) keep their disabled button and add a muted note under it
    ("Recording isn't available here yet — capture it in the ODK app or
    note it in the narrative.", image and file equivalents, en/hi/fr),
    linked with `aria-describedby`; no note once the service exists.
11. **Date input styling.** The web date input now runs through the theme
    (control-border, radius, 12 px padding, 44 px, ink, surface) and is
    12 rem wide, not the column.

New UI strings (en/hi/fr): `requiredShort`, `day`, `month`, `year`,
`openCalendar`, `dateFormatHint`, `decrease`, `increase`, `unit*`,
`interviewer`, `interviewerInstruction`, `audioUnavailable`,
`imageUnavailable`, `fileUnavailable`. New theme tokens: `stickyRail`,
`scrollMargin`; new CSS variable `--who-2022-web-sticky-top`.

### Performance on low-end devices

Measured with Playwright + CDP on the **built bundle** (production, minified)
on the static host page, Chromium, 390 px mobile viewport,
`Emulation.setCPUThrottlingRate(4)`, garbage collected before each reading
(`Performance.getMetrics`). Taps: 20 alternating radio taps, tap-to-painted
(two animation frames). Section change: drawer item click to the drawer
closed, all 17 sections in order, twice. Script in the session scratchpad;
numbers are one run each, so treat +-10 % as noise.

| Measure | Before round 3 (`07df3a2` bundle) | After round 3 |
| --- | --- | --- |
| Bundle (minified, uncompressed) | 939 KB | 958 KB |
| Load to first render | 263 ms | 278 ms |
| Script execution at load (parse+compile+run) | 150 ms | 160 ms |
| JS heap, section 1 | 5.3 MB | 5.5 MB |
| DOM nodes, section 1 | 166 | 174 |
| Tap to paint, section 1 (p50 / p95) | 16 / 26 ms | 16 / 18 ms |
| JS heap, 164-question section | 11.1 MB | 10.8 MB |
| DOM nodes, 164-question section | 1283 | 1329 |
| **Tap to paint, 164-question section (p50 / p95)** | **65 / 81 ms** | **18 / 26 ms** |
| Section change via drawer, 17 sections (p50 / p95) | 85 / 152 ms | 91 / 173 ms |
| JS heap after all 17 sections, pass 1 / pass 2 | 7.2 / 7.3 MB | 7.2 / 7 MB |
| DOM nodes / listeners after pass 2 | 573 / 308 | 449 / 284 |

Budgets: tap-to-paint p95 on the largest section 26 ms
(< 100 ms met, from 81 ms); heap flat across two passes
over every section (7.2 -> 7 MB, listeners
285 -> 284: no leak from the drawer portal,
the rail or the fade timers); only the current section's questions are in
the DOM. The bundle grew 19 KB
(2.0 %) for the new controls and strings; nothing in it is
lazy-loadable (no other locale is bundled, month names come from `Intl`), so
that budget is not met and is reported as such. Section change is within
noise of before (the drawer now mounts through a portal).

What cost, and what was done (all presentation, no engine or validation
change, no behaviour change):

- **Every answer re-rendered every question row** (164 on the largest
  page): `renderQuestion` built fresh JSX and a fresh `onAnswer` closure per
  row per render. Rows are now `QuestionRow`, memoised with a comparator
  that ignores the whole-answer `data` prop except for the six controls
  that hand it to a platform service, compares issues by message, and gets
  one stable `onAnswer` per question. This is the tap-time win.
- **Section status recomputed the calculated fields once per section** on
  every answer (`applyCalculations` x 17); it is computed once per pass.
  The status map and the issue-section set keep their identity while their
  contents are unchanged, and the rail, header strip and drawer are
  `React.memo`, so an ordinary answer does not re-render the stepper.
- Only the current section's questions are in the DOM (the engine's
  `snapshot.questions`); the node count on the 164-question page is that
  page, and it drops back after leaving it.
- The bundle carries the English instrument once and no other locale
  (`hi`/`fr` are not in the bundle; DigitVA serves translations from its
  API); the Hindi month names come from `Intl` at runtime, no tables.
- Attachments already live in IndexedDB and are shown through object URLs
  that are revoked on release; nothing is held as a data URL.
- Drafts are handed to the store as the live data object; DigitVA's page
  debounces the PATCH. No serialisation happens in the form on change.
- The entry fade on newly visible sections is a single opacity transition
  on those rows only, `0ms` under reduced motion.

Remaining recommendations (not done, engine or host territory):

- `sectionStatuses` still validates every answered question of every
  visible section per answer (cheap, ~1 ms unthrottled, but it scales with
  answers); an incremental per-section cache keyed on that section's
  answers would remove it.
- The 164-question page could be windowed (render only rows near the
  viewport) if a target device still shows tap p95 above 100 ms; this
  changes `scrollToIssue` and focus handling, so it is a separate piece.
- The bundle (957 KB, 190 KB gzipped) is dominated by react-native-web +
  React; a react-dom-only renderer would roughly halve parse time but is a
  rewrite of `ui/`.

### Round-3 vendoring

Rebuilt on this branch with `tooling/who-va-2022` (`node build.mjs && node
check.mjs`); manifest updated. Verified in Chromium under the tooling pins
(react 18 / react-native-web 0.19) through the static host page: drawer
above a `z-index: 1000` navbar, sticky rail, number/date controls, grid,
no console errors.

## Vendoring

The DigitVA bundle is built by `tooling/who-va-2022/build.mjs` from
`vendor/who-va-2022/src` and committed under `app/static/vendor/who-va-2022/`:

```sh
cd tooling/who-va-2022 && npm install && node build.mjs && node check.mjs
```

- Output: `app/static/vendor/who-va-2022/who-va-2022.web-component.js`
  (minified ESM) and `app/static/vendor/who-va-2022/manifest.json`
  (`vendored_version`, `bytes`, `sha256`), both rewritten by `build.mjs`.
- Commit both files together; `manifest.json` is what pins the artifact.
- `tooling/who-va-2022/package-lock.json` was behind its `package.json`
  (vite/esbuild entries missing), so `npm ci` refused; `npm install`
  regenerated it and the lock is committed with the round-2 bundle.
- The intake page `app/templates/va_frontpages/va_intake_form.html` needs no
  change: the chip is on by default. To hide codes for interviewers, set
  `el.setAttribute("hide-question-codes", "")` where the element is built.

## Not done here

- `src/languages/hi.ts` is stale against the instrument model check
  (`validation.constraintMessage must match constraintMessage`):
  `withInstrumentTranslation` translates `constraintMessage` but not its
  `validation` mirror. The screenshot script mirrored it for the Hindi
  capture; DigitVA serves translations through
  `app/static/js/intake/translations.js` and is not affected. Engine
  territory, left alone.
- Two pre-existing lint errors (`complexity` on `Date` and `ImagePicker` in
  `question-controls.tsx`) and the 351 pre-existing
  `tests/question-by-question.test.ts` failures (bead `digitva-19l`) remain.
- A host-supplied instrument (`el.instrument = ...`, which is how DigitVA
  applies its translations) renders the form with English UI strings: the
  web component only loads a language's UI strings for the built-in
  instrument, and the built-in loader knows English alone. The "Sections",
  "Save draft", date-format and required-message strings therefore show in
  English on a Hindi DigitVA form. Fix belongs in `web-component.tsx`
  (accept `uiTranslations` from the host) and the intake page; not done here.
- There is no decimal or datetime question in the instrument; the decimal
  placeholder and the compact datetime box are covered by tests only.
