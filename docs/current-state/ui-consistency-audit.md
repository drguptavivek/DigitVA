---
title: Expo UI Consistency Audit
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-12
---

# Expo UI Consistency Audit

Audit of `mobile/digitva-collect/src` taken before the token unification
(`docs/current-state/doris-ui-tokens.md`, section "ui-consistency"). Values
are the distinct literals found by scanning `StyleSheet.create`, inline styles
and the theme files; the right-hand column says where they come from.

## Three styling systems that disagreed

| System | Source | Used by |
| --- | --- | --- |
| 1. Original palette | `palette` (`src/theme.ts`), `createStyles` / `useUiStyles` / `Button` / `styles.card` / `styles.input` (`src/ui.tsx`), `webPalette` (`src/workspace/webPalette.ts`) | queue, workspace shell, category panels, QualityPanels, SimpleCodPanel, supervision, registration, native routes |
| 2. shadcn-named `ui` tokens + DORIS kit | `ui`, `uiRadius` (`src/theme.ts`), `src/workspace/doris/ui/index.tsx`, `compact.tsx` | DORIS certificate editor |
| 3. WHO package choice control | `--who-2022-web-*` CSS variables from `src/whoWebTheme.ts` | interview, Narrative quality (NQA), Social autopsy panels |

## Radii (px)

| Value | Where | Source |
| --- | --- | --- |
| 3 | workspace cards, category card, buttons, detail items (13 uses) | `WorkspaceLayout.web.tsx`, `CategoryPanel.web.tsx` literals |
| 4 | section-bar buttons, WebButton, ICD link, gallery chips, notes tab | literals, `uiRadius.sm` |
| 6 | account menu items; DORIS controls | `uiRadius.md`, literal |
| 8 | DORIS cards, WHO choice rows (`--who-2022-web-radius-control` default), language options | `uiRadius.lg`, WHO default, literals |
| 10, 11, 22 | count badges, DORIS badge, notes pill | literals |
| 12 | native `Button`, `styles.input`, `styles.card`, nav links, language popover | `radius.md` (theme.ts), literals |
| 16 | legacy `radius.lg` (unused by most) | `radius.lg` |
| 999 / 9999 | pills, badges | `radius.full`, `uiRadius.full` |

Two scales (`radius` 8/12/16 and `uiRadius` 8/6/4) coexisted.

## Control heights (px)

32 (`CONTROL_HEIGHT - 4` chip, small button), 34 (search box input), 36
(`CONTROL_HEIGHT`, DORIS button/input/radio row), 40 (WHO secondary button,
logo), 44 (WebButton, section-bar button, drawer, WHO inputs and buttons),
46, 48 (`controls.minHeight`, native `Button`, `styles.input`, nav links, WHO
choice row), 52, 54, 68, 72, 76. The same "button" was 36, 44 and 48 depending
on the screen.

## Font sizes (px)

10, 11, 12, 13, 14, 15, 16, 17, 18, 22, 24, 28, 30. Sources: `typography`
(body 17, subhead 15, caption 13, headline 18, title 24, largeTitle 30),
the DORIS `font` (14/12/16) plus a literal 15 section title, the WHO control
(16 choice text), and 32 literals in `WorkspaceLayout.web.tsx` (10, 11, 12, 13,
14, 15, 17, 18, 24, 28), 13 in `CategoryPanel.web.tsx`, 9 in `web/common.tsx`.
Body text was 14 (DORIS), 15 (subhead), 16 (WHO), 17 (`typography.body`).

## Border widths

1 everywhere (33 uses), plus 1.5 (DORIS radio ring), 2 (native `Button` focus,
WHO choice indicator), and left accent bars of 3 and 4.

## Spacing steps

`spacing` 4/8/12/16/24/32/48 (theme.ts) and `gap` 4/8/12/16/24 (DORIS kit) agree.
Literals outside both: 2, 5, 6, 9, 10, 14, 18 (padding/gap in
`WorkspaceLayout.web.tsx`, `CategoryPanel.web.tsx`, `web/common.tsx`). Card
padding: 12 (`styles.card`), 14 (web main card), 16 (DORIS card), 24 (hints card).

## Colours

Surface / border / muted tones were defined four times:

| Role | `palette` (system 1) | `webPalette` | `ui` (system 2) | WHO vars (system 3) |
| --- | --- | --- | --- | --- |
| Light page | `#F6F8FB` | `#f7f7f7` | `#FFFFFF` | `palette.background` |
| Light text | `#10233F` | `#333333` | `hsl(240 10% 3.9%)` | `palette.text` |
| Light border | `#D9E2EC` | `#e1e5ea` | `#CBD5E1` | `palette.border`; control border `#6B7C93` |
| Light brand | `#1D4ED8` | `#004687` bar, `#0d6efd` selected | `#1D4ED8` | `palette.accent` |
| Dark page | `#0B1220` | `#0B1220` | `#131E2E` | `#0B1220` |
| Dark surface/card | `#131E2E` | `#131E2E` | `#1B2A3D` | `#131E2E` |
| Dark border | `#314157` | `#314157` | `#3E5068` | `#314157`; control border `#7C90AB` |

So the same dark card was `#131E2E` in the queue and `#1B2A3D` in DORIS.

## Variants

| Component | Variants found |
| --- | --- |
| Button | native `Button` (primary / secondary / danger, 48 high, radius 12, 2px focus border); DORIS `Button` (default / secondary / outline / ghost / destructive, sm 32 / default 36 / icon, radius 6, focus outline 2px offset 2); inline `WebButton` and `<button>` elements in `WorkspaceLayout.web.tsx` (radius 4, 44 high, 13px) |
| Input | `styles.input` (48 high, radius 12, 17px); DORIS `Input` (36 / 44 phone, radius 6, 14px); WHO input (44 high, radius 8, 16px) |
| Card | `styles.card` (12 padding, radius 12); `webStyles.mainCard` (14 padding, radius 3); DORIS `Card` (16 padding, radius 8) |
| Badge | DORIS `Badge` (pill, 12px); workspace `categoryBadge` / `attachmentBadge` (radius 10, 11px) |
| Alert | DORIS `Alert` (default / warning / destructive, radius 6); native error `Text` |
| Choice | WHO choice row (22px indicator, radius 8, 48 high, 16px); DORIS `RadioRow` (16px indicator, 36 high, 14px) and pill `Chip` |

## Literal colours outside the theme files (before)

`web/InterviewScreen.tsx` (5), `web/common.tsx` (2), `workspace/AccountMenu.web.tsx` (2),
`workspace/QueueScreen.tsx` (1), `workspace/WorkspaceLayout.web.tsx` (8),
`workspace/doris/IcdPickerModal.tsx` (1), `workspace/doris/DorisPanel.tsx` (1),
`workspace/media/AttachmentGallery.web.tsx` (2). Most are scrims, shadows, the
logo plate and the lightbox, which stay as a documented allow-list in the guard
test (`mobile/digitva-collect/__tests__/ui-token-guard.test.ts`).
