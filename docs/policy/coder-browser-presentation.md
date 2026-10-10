---
title: Coder Browser Presentation
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-10
---

# Coder browser presentation

The Expo browser coding workspace reproduces the existing HTMX coding
workspace's visual hierarchy: Hints, VA Form Details, category navigation,
Query/Response sections, assessment controls, and a persistent Notes panel.
The HTMX templates are the visual reference, including Roboto typography,
blue headings, white panels, category count badges and response emphasis.
Narrow screens collapse category navigation without hiding the case content.
Disease/Co-morbidity uses the HTMX history columns: diagnoses answered Yes
under "Diagnosed by Health Professional", and explicit No answers under
"Absent". Unknown or other answers remain visible separately; missing
answers never imply absent disease. Narrow screens stack the columns.

Presentation continues to consume the shared allocation-scoped API. It does
not change coding steps, masking, authorization, COD validation, workflow
transitions, or the meaning of category counts. Notes remain private to their
author and case, keep unsaved content while changing categories, and retain
the existing visibility and allocation-loss protections. Read-only case
views do not expose editing controls.

Display metadata is additive: project/site codes, age, gender, demo status,
configured category icons and category counts. Clients tolerate absent
presentation fields; no database migration or payload backfill is required.
The native application retains its existing layout.
