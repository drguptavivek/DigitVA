---
title: Coder Workspace Component Inventory
doc_type: reference
status: active
owner: engineering
last_updated: 2026-11-17
---

# Coder workspace component inventory

The active HTMX coding workspace uses config-driven category templates rather
than the older category-specific templates. The Expo browser retains their
layout and evidence presentation. Editable questions reuse
`WhoVaQuestionControls` from the existing WHO VA native interview package.
The shared DORIS certificate editor remains authoritative for both clients.

| HTMX component or primitive | Expo counterpart |
| --- | --- |
| Roboto, blue headings, white cards, Hints, form details | `mobile/digitva-collect/src/workspace/WorkspaceLayout.web.tsx` |
| Form ID, age, sex, DEMO and project/site metadata | Same layout; compact metadata stays visible above categories |
| Category icons, counts and active selection | Same layout; persistent 52px rail and optional names drawer |
| Previous/Next and blocked explanation | Same layout; existing workflow gate |
| ICD classification browser link | Same layout drawer; classification-specific WHO link |
| SmartVA status and run actions | `mobile/digitva-collect/src/workspace/SmartvaStatusPanel.tsx` |
| Category and section headings, Query/Response tables | `mobile/digitva-collect/src/workspace/CategoryPanel.web.tsx` |
| Yes/No, informational badges and reversed emphasis | Same category renderer; numeric badge padding and retained answer semantics |
| Positive/negative disease history | Same category renderer; explicit Yes and No groups |
| Consolidated symptom summary and COD evidence | Same category renderer; source category provenance retained |
| Narration and attachments, image slider, thumbnails, rotation, lightbox, audio and PDF | `mobile/digitva-collect/src/workspace/media/AttachmentGallery.web.tsx` |
| Narration and attachments on the phone (Android/iOS): the same `media_gallery` items as web (narration image `imagenarr`, document images, PDFs, narration audio, wrapped or bare values), one at a time with previous/next and rotate for images; online media loads through the bearer `AttachmentMedia.native.tsx`, offline draft attachments through `LocalAttachmentMedia.native.tsx`. No thumbnails or pinch lightbox | `mobile/digitva-collect/src/workspace/media/AttachmentGallery.native.tsx` |
| Private Notes and panel shell | `mobile/digitva-collect/src/workspace/PrivateNotePanel.tsx` and browser layout |
| Narrative quality and social autopsy | `mobile/digitva-collect/src/workspace/QualityPanels.tsx`; WHO interview single/multiple choices |
| Simple COD conditions and not-codeable reasons | `mobile/digitva-collect/src/workspace/SimpleCodPanel.tsx`; WHO interview choices |
| DORIS certificate and not-codeable choices | `mobile/digitva-collect/src/workspace/doris/DorisPanel.tsx`; existing shared certificate and WHO interview choices |
| ICD search | Existing workspace ICD selectors; search results remain action buttons |
| Loading, error and empty content | Existing workspace screen and layout states |

## Source boundaries

The source chain starts at `app/templates/va_frontpages/va_coding.html`.
Its category includes are `category_table_sections`,
`category_health_history_summary`, `category_attachments` and
`category_va_cod_assessment`, plus their table/value, attachment/workflow,
summary and COD evidence partials. Navigation, SmartVA and Notes belong to
the workspace shell. The original badge colors and configured reversals
change emphasis only; missing answers never become negative history.

DORIS is the existing shared `DorisPanel`, used by browser and native routes.
The WHO interview vendor provides reusable question controls and collection
support questions, not a separate coding certificate editor. Its Part I/II,
administrative and certificate context fields, processing proof, masked steps
and conflict handling stay in this component.

## Phone category answers

On the phone (`CategoryPanel.tsx`) each non-gallery subcategory item is a
two-column row, question left and answer right, both wrapping, as the web
Query/Response table. Question text is the Petrol ink token, not the muted
grey. Yes/No badges follow the web `ResponseValue` decision, shared as
`answerTone` (`src/workspace/answerTone.ts`): `info` wins (primary badge); a
Yes is red and a No green, swapped when `flip` is set. Red and green are the
Petrol `destructive` and `success` fills. The text lines "Flipped" and "More
information" are not shown. Offline categories (`localCategories.ts`) use the
same shape and so the same rows.

## Validation boundaries

Component tests cover metadata, badge styles, quality scoring and choices,
COD selections and DORIS processing. Browser checks measure real badge
padding, responsive overflow, rail scrolling and form grouping. Export and
typecheck are separate checks from physical-device acceptance. Real audio
playback and hardware touch gestures still require device acceptance.

## Category layout rules (phone and web)

Shared by `CategoryPanel.tsx` and `CategoryPanel.web.tsx` through
`mobile/digitva-collect/src/workspace/categoryLayout.ts`:

- "Symptoms on VA Interview" shows only in `workflow_panel` (first) and
  `attachments`/Narration (after the narrative and the quality panel). The
  server, and offline `localCategories.ts`, send `summary_items` on every
  category; the panel gates by render mode.
- Subcategories with the placeholder heading `default` show no heading; raw
  keys (`risk_factors`) are humanized.
- Disease / Co-morbidity splits answers into Diagnosed by Health Professional
  (Yes), Absent (No) and the remaining answers as a question/answer grid.

## Phone category pager and Notes

`WorkspaceLayout.tsx` (native, also offline coding) ends every category page
with Previous / Next, as the web layout does. Next is disabled while the
category's `blocked_by` holds (e.g. "Complete the Narrative Quality Assessment
before proceeding.") and the reason shows under it. A Notes button follows on
every page and toggles `PrivateNotePanel`, kept mounted so a draft survives
category changes. Phone only; `WorkspaceLayout.web.tsx` is unchanged.

## Browser workspace colours and audio (9cll.22.16)

- The Expo browser coding pages (`src/workspace/*.web.tsx`, the web gallery
  and DORIS web fields) take every colour from `webPalette.ts`, which reads
  only Petrol `ui` tokens (`src/theme.ts`). Yes/No badges and the Diagnosed /
  Absent panels use the phone's fills: Yes `destructive` with
  `destructiveForeground`, No `success` with `primaryForeground` (light
  `#b3261e` / `#1f7a4d` on white; dark `#b3261e` on `#e8edf0`, `#6cc796` on
  `#0f1418`). `__tests__/ui-token-contrast.test.ts` holds each text pair at
  4.5:1 or more in both modes.
- AMR narration plays in the browser `<audio>` player. Sync stores an AMR
  recording as its MP3 derivative and the attachment routes serve it as
  `audio/mpeg`, so the client no longer treats `.amr` as download-only; a
  file the browser cannot decode still falls back to a download link.
