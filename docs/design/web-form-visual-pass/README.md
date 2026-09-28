---
title: Web VA questionnaire visual pass (before/after)
doc_type: design
status: proposed
owner: engineering
last_updated: 2026-09-28
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
