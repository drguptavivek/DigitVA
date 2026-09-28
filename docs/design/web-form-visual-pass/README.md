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

## Vendoring (one-command follow-up, after approval)

The DigitVA bundle is built by `tooling/who-va-2022/build.mjs` from
`vendor/who-va-2022/src` and committed under `app/static/vendor/who-va-2022/`:

```sh
cd tooling/who-va-2022 && npm install && node build.mjs && node check.mjs
```

- Output: `app/static/vendor/who-va-2022/who-va-2022.web-component.js`
  (minified ESM) and `app/static/vendor/who-va-2022/manifest.json`
  (`vendored_version`, `bytes`, `sha256`), both rewritten by `build.mjs`.
- Commit both files together; `manifest.json` is what pins the artifact.
- Caveat found while checking: `tooling/who-va-2022/package-lock.json` is
  behind its `package.json` (vite/esbuild entries missing), so `npm ci`
  refuses; `npm install` regenerates the lock. Commit the lock change with
  the bundle or fix it first.
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
