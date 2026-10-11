---
title: Coder Workspace Component Inventory
doc_type: reference
status: active
owner: engineering
last_updated: 2026-10-11
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

## Validation boundaries

Component tests cover metadata, badge styles, quality scoring and choices,
COD selections and DORIS processing. Browser checks measure real badge
padding, responsive overflow, rail scrolling and form grouping. Export and
typecheck are separate checks from physical-device acceptance. Real audio
playback and hardware touch gestures still require device acceptance.
