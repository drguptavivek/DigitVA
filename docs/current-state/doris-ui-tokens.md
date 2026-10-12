---
title: DORIS Editor UI Tokens
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-12
---

# DORIS Editor UI Tokens

## Rule

The DORIS certificate editor and the ICD-11 picker use **native components
only** and **shadcn/ui design tokens**. No UI library, no new dependency: no
Astryx, shadcn/Radix, NativeWind or Tailwind.

- Expo app: React Native core components (`View`, `Text`, `Pressable`,
  `TextInput`, `Modal`, `ScrollView`), wrapped in a tiny kit owned in the repo.
- Flask editor and picker: native HTML elements (`input`, `select`,
  `textarea`, `input type=date|number`, radio inputs, `button`,
  `fieldset/legend`, `details`). Bootstrap classes stay as the structure;
  the look comes from CSS custom properties.

shadcn's philosophy applies: small composable primitives, 1px `border`
instead of heavy fills, 40px controls (44px on phones), 14px body, 12px helper text,
`muted-foreground` for labels and helper text, spacing 4/8/12/16/24, 2px ring
with offset on focus, disabled = 50% opacity and `not-allowed`, `destructive`
only for remove/delete.

## Where the tokens live

| Place | File |
| --- | --- |
| Expo tokens (`ui`, `uiRadius`, `hsl()`) | `mobile/digitva-collect/src/theme.ts` |
| Expo primitives | `mobile/digitva-collect/src/workspace/doris/ui/index.tsx` |
| Expo composites (SearchBox, ChipChoice, IntervalField, Warn) | `mobile/digitva-collect/src/workspace/doris/compact.tsx` |
| Flask editor and picker | `app/static/css/doris_demo.css` (custom properties scoped to `.doris-clinical-editor`, `#doris-demo-app`, `.doris-search-modal-open`, `.doris-search-backdrop`, `.doris-related-window`) |
| Picker in the Expo iframe/WebView | `app/static/doris_picker_host.html` (`?theme=dark|light` sets `data-bs-theme`) |

Dark mode: Expo follows `useTheme().mode`; Flask follows
`[data-bs-theme="dark"]` on `<html>` or on the editor element.

## Brand decision

`primary` and `ring` are the DigitVA brand blue taken from the Expo app
(`ui.primary` `#1D4ED8` light, `#78A9FF` dark; focus `#2563EB` / `#9CC0FF`),
used identically in the Flask editor so both apps match. The Flask site chrome
navy (`--color-accent-primary: #004687` in `app/static/css/base.css`) is left
to the host page. Neutrals, borders and muted are shadcn "zinc".

## Token table

Expo values are the hex of shadcn's HSL numbers (`hsl()` helper in `theme.ts`);
Flask uses the same numbers as CSS `hsl()`.

| Token | Light | Dark |
| --- | --- | --- |
| `background` (outer panel, inputs, choice-row fill) | hsl(0 0% 100%) `#FFFFFF` | `#131E2E` (was `#09090B`) |
| `page` (extension: app page behind the cards) | `#F6F8FB` | `#131E2E` (was `#0B1220`) |
| `foreground` | hsl(240 10% 3.9%) `#09090B` | `#F4F7FB` (was `#FAFAFA`) |
| `card`, `popover` | = background | `#1B2A3D` (one step lighter than `background`; was `#09090B`) |
| `card-foreground`, `popover-foreground` | = foreground | `#F4F7FB` |
| `primary` (brand blue) | `#1D4ED8` | `#78A9FF` |
| `primary-foreground` | `#FFFFFF` | `#081429` |
| `secondary`, `muted` | `#EEF3F8` (was `#F4F4F5`) | `#243449` (was `#27272A`) |
| `accent` (brand-soft: selected row / chip fill) | `#E8F0FF` | `#1C3764` |
| `secondary-foreground` | hsl(240 5.9% 10%) `#18181B` | `#F4F7FB` |
| `accent-foreground` | `#10233F` | `#F4F7FB` |
| `muted-foreground` | `#53657A` (app `textMuted`; was `#71717A`) | `#B5C2D1` (app `textMuted`; was `#A1A1AA`) |
| `destructive` | hsl(0 72.2% 50.6%) `#DC2626` (see deviations) | hsl(0 62.8% 30.6%) `#7F1D1D` |
| `destructive-foreground` | hsl(0 0% 98%) | hsl(0 0% 98%) |
| `destructive-text` (extension) | `#B42318` | `#FF8A80` |
| `warning` / `warning-foreground` / `warning-border` | `#FEF3C7` / `#3B2200` / `#B45309` | `#38280B` / `#FFF3D1` / `#FBBF24` |
| `border` (card and divider hairline) | `#CBD5E1` (was `#E4E4E7`) | `#3E5068` (was `#27272A`) |
| `input` (edge of every control, outline button and choice row, >= 3:1) | `#6B7C93` (was `#CBD5E1`) | `#7C90AB` (was `#3E5068`) |
| `build-tint` / `build-border` / `build-bar` / `build-foreground` (extension: guided-build card fill, 1px border, 4px left bar, text on a selected axis chip; text on tint >= 4.5:1) | `#EEF0FF` / `#A5B4FC` / `#4338CA` / `#FFFFFF` | `#22264F` / `#3B418D` / `#A5B4FC` / `#0F1033` |
| `ring` (brand focus) | `#2563EB` | `#9CC0FF` |
| `radius` | 0.5rem (8px); lg = radius, md = radius - 2px, sm = radius - 4px | same |
| `success-text` (Flask only, engine status) | `#146C43` | `#75D5A4` |

Chart tokens (per certificate line, each with bar, `-tint`, `-soft`,
`-foreground`; Flask names `--chart-N`, `--chart-N-tint` ...):

| Token | Line | Light bar / tint / soft / foreground | Dark bar / tint / soft / foreground |
| --- | --- | --- | --- |
| `chart-1` | A, pink | `#C2185B` `#FCE4EC` `#F8BBD0` `#4A0A24` | `#F48FB1` `#3B1A27` `#6A2540` `#FFE4EE` |
| `chart-2` | B, amber | `#B45309` `#FEF3C7` `#FCD34D` `#3B2200` | `#FBBF24` `#38280B` `#6B4A0C` `#FFF3D1` |
| `chart-3` | C, teal | `#0F766E` `#CCFBF1` `#99F6E4` `#032F2B` | `#2DD4BF` `#0E3330` `#145C55` `#D9FFF8` |
| `chart-4` | D, indigo | `#4338CA` `#E0E7FF` `#C7D2FE` `#1B1670` | `#A5B4FC` `#22264F` `#3B418D` `#EEF0FF` |
| `chart-5` | E, violet | `#7E22CE` `#F3E8FF` `#E9D5FF` `#3B0764` | `#D8B4FE` `#2E1A47` `#5B2A8C` `#F7ECFF` |
| `chart-part2` | Part II, slate | `#475569` `#F1F5F9` `#E2E8F0` `#1E293B` | `#94A3B8` `#1E2733` `#334155` `#F1F5F9` |

Lines cycle past five. The letter on the bar uses `background` as text colour.

### Deviations from stock shadcn

- Light `destructive` is hsl(0 72.2% 50.6%), not hsl(0 84.2% 60.2%): the stock
  value gives 3.8:1 with its foreground, below the 4.5:1 rule for button and
  badge text.
- `destructive-text`, `warning*`, `success-text` and `chart-*` are extensions.
  Dark `destructive` is a fill (too dark to read as text on `background`), so
  error text uses `destructive-text`.
- `muted-foreground` on `muted` is 4.35:1 in light mode, so it is never used
  as text on a `muted` fill (reports on `muted` use `foreground`).

## Primitives (Expo kit)

`Card`, `CardHeader`, `CardTitle`, `CardDescription`, `Body`, `Muted`,
`SectionTitle`, `Label`, `FieldHint` (12px), `FieldError` (12px, alert role),
`FieldWarning`, `Separator`, `Alert` (`default` | `warning` | `destructive`),
`Badge` (`default` | `secondary` | `outline` | `destructive`), `Button`
(`default` | `secondary` | `outline` | `ghost` | `destructive`; sizes `sm`,
`default`, `icon`), `Input`, `Textarea`, `FieldButton` (date /
select trigger), `RadioGroup` + `RadioRow`, `Chip`, `ReportBox`. Variants are
small style maps (the cva idea, no library). Controls are 40px high (44px
under 768px width, `useUi().controlHeight`); buttons and chips add `hitSlop` 4
so the touch target is at least 44px. Focus: 2px `ring` outline with 2px offset on the web, `ring`
border on native. Disabled: 50% opacity (and `not-allowed` on the web).

Flask equivalents: `.form-control`/`.form-select`/`textarea` (40px, `input`
border, 6px radius, ring focus), `.btn-primary` (default), `.btn-secondary`,
`.btn-outline-primary` and `.btn-outline-secondary` (outline),
`.btn-outline-danger` (destructive, remove only), `.btn-link` (ghost/link),
`.alert-warning`, `.badge`, `.card`, `.list-group`. Under 768px, buttons and
fields are 44px with 16px text. The editor uses `<select>` for its choices, so
they are restyled with the tokens above; a radio group written as
`<label class="doris-choice"><input type="radio">text</label>` inside
`.doris-choices` gets the same row look as the Expo `RadioRow`.

## Tests

- `mobile/digitva-collect/__tests__/ui-token-contrast.test.ts`: 4.5:1 for every
  text/background pair the unified tokens put on screen (kit, old palette,
  `webPalette`, WHO row variables), 3:1 for control edges and the focus ring.
- `mobile/digitva-collect/__tests__/ui-token-guard.test.ts`: fails with
  `file:line` for a literal colour, `borderRadius` or `fontSize` off the scales in
  `src/workspace`, `src/web`, `src/nativeRoutes` and `src/ui.tsx` (allow-list of
  scrims, shadows, logo plate and lightbox is in the test).
- `mobile/digitva-collect/__tests__/workspace-doris-kit.test.tsx`: token
  conversion, 4.5:1 for every text/background token pair in both modes,
  3:1 for ring/primary/warning edge, variant style maps, sizes, hit-slop,
  disabled state, focus ring.
- The existing line-shade and editor contrast tests in
  `workspace-doris-picker.test.ts` stay.

## Surfaces and spacing

- Dark DORIS surfaces are never darker than the app page surface: page, outer
  panel and inputs `#131E2E`, cards `#1B2A3D`, borders `#3E5068` (lighter than both).
  Light: white cards on the `#F6F8FB` page, borders `#CBD5E1`.
- Cards use 16px inner padding and 12px gaps. On phones the Expo panel cancels
  the page card's 14px padding (web) and keeps an 8px gutter.
- The editor title is one centred h2 (24px phones, 26px desktop, weight 700)
  under a full-width top rule, with a muted step subtitle; a rule closes the
  Process/Save button block (`doris-heading-separator`,
  `doris-actions-separator`; Flask `.doris-editor-heading`, `.doris-actions-separator`).

## ui-consistency

Audit that led to this section: `docs/current-state/ui-consistency-audit.md`.
Owner rule: the same app has consistent styles.

**One token source.** The `ui` table in `mobile/digitva-collect/src/theme.ts` is
the only place raw colours live. `palette` (queue, shells, native routes),
`webPalette` (browser workspace) and `whoWebThemeVars` (the WHO package's
`--who-2022-web-*` variables) are derived from it, so every screen reads the
same values. The brand blue is `primary` / `ring`; `accent` is its soft tint.

**One scale each.**

| Scale | Values (old to new where changed) |
| --- | --- |
| Radius (`uiRadius`, alias `radius`) | lg 8 cards, md 6 controls (was 12 on native buttons, inputs, nav links; 3 on web cards), sm 4, full pills and dots |
| Control height (`controls`, `useUi().controlHeight`) | 40; 44 on phones (was 32/34/36/44/46/48) |
| Text (`fontSize`) | 12 caption (was 10/11/13), 14 body and labels (was 15), 16 inputs and choice rows (was 17), 18/20/24/26 headings (was 22/28/30) |
| Border | 1px (choice-row circle 2px, focus ring 2px with 2px offset) |
| Spacing | 4/8/12/16/24; card padding 16; gaps 12 |
| Button min width | 72 (`BUTTON_MIN_WIDTH`) |

**Buttons.** One family: `default`, `secondary`, `outline`, `ghost`,
`destructive`; sizes `sm`, `default`, `icon` (`buttonTone` in `theme.ts`). The
shared `Button` in `src/ui.tsx` and the DORIS kit `Button` read the same table;
`kind` (`primary`, `secondary`, `danger`) stays as an alias (`default`,
`outline`, `destructive`). `styles.card`, `styles.input`, `styles.headline`,
`styles.muted` map to the same tokens.

**Choice rows.** Every single-choice in the DORIS editor (`ChipChoice`) renders
`RadioRow`, the look of the WHO choice row of Narrative quality: input fill
(`background`), 1px `input` edge, 6px radius, 48px minimum height, 12px/11px
padding, a 22px radio circle (2px border) with a 10px dot, 16px text, 12px gaps.
Selected: `primary` border and dot, `accent` fill. The WHO control reads the same
tokens through `whoWebThemeVars` (`surface`, `control-border`, `brand`,
`brand-soft`, `ink-subtle`, `radius-control` = 6px), so the two look identical
(computed styles compared in the browser, light and dark). One difference
remains: the WHO package hard-codes an 8px gap between its rows, DORIS uses 12px.
Columns (`choiceColumns`): phones 2, or 1 when a label is over 28 characters or
a word cannot fit a two-column cell; wide screens one column per option for up to
four short options, else 3 (short labels) or 2 (long labels). `Not stated` stays
first; role `radio`, selected state, `Label: Option` accessibility labels and
`question-<name>-choice-<n>` test ids are unchanged.

**Small controls** (unit chips, `Add line`, date buttons) stay chips or buttons: 72px minimum width, 40px (44 phones) minimum
height, 12px side padding, centred text, 6px radius, not pills.

**Date precision select and clear button (Flask editor).** The precision select
(`Date`, `Year-Month`, `Year`) sits left of its input in an `input-group`,
`width: auto`, 8.75 to 10rem wide, never wrapping. The clear cross
(`.doris-clear`) is a transparent button in `--muted-foreground` with a 2.75rem
(44px) hit area overhanging a 2rem label row, `--destructive-text` and
`--muted` on hover, a 2px `--ring` outline on focus, hidden while the question
is empty; the inline variant (2rem) sits inside the input's right edge (left of
the number spinner) or the textarea's top right corner. All colours are tokens,
so light and dark need no extra rules.

**Focus ring.** The 2px ring plus 2px offset reaches 4px outside a control. Groups
of rows (`RadioGroup`) pad by that much (`RING_ROOM`, cancelled by a negative
margin), and cards keep at least 16px padding, so the ring is never clipped by
an `overflow: hidden` ancestor or touches a card edge.

## Picker footer and build card (Flask)

The modal footer (`.doris-selection-footer`) is tinted `accent` with a 2px
`primary` top border. It shows a 12px uppercase caption (`SELECTED` or
`BUILDING`), the code in a bold 20px monospace chip (`primary` fill,
`primary-foreground` text), and the title at 18px semibold. With nothing staged
it reads "No code selected" in `muted-foreground`; OK is disabled. The actions
row wraps (`flex-wrap`, 8px gap); on phones the footer is capped at 28vh with
the text scrolling and each button at least 48px tall. The guided-build card
(`.doris-build-card`) uses the `build-*` tokens; the neutral details card and
result rows stay `muted` / `card`. On phones, opening Build, Details or a
related term scrolls the card to the top of the results pane, focuses its
heading and offers "Back to results".
