---
title: Coder Browser Presentation
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-11
---

# Coder browser presentation

The Expo browser coding workspace reproduces the existing HTMX coding
workspace's visual hierarchy: Hints, VA Form Details, category navigation,
Query/Response sections, assessment controls, and a persistent Notes panel.
The HTMX templates are the visual reference, including Roboto typography,
blue headings, white panels, category count badges and response emphasis.
A persistent icon rail at every screen width selects categories directly; an
optional slide-out shows category names and counts without hiding case content.
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

## Complete experience and mobile-first layout

The browser workspace carries over the complete existing HTMX coding
experience: category navigation, response emphasis and configured colour
reversals, grouped disease history, narrated and documentary evidence,
image browsing/rotation, audio playback, consolidated assessment context,
private notes, narrative quality and social-autopsy actions. The source
templates and configured render modes define the presentation semantics;
an ordinary table is not a substitute for a specialized source view.

Design starts with a phone viewport. A compact left icon rail offers direct
category selection; an optional slide-out exposes names and counts. Each
icon has an accessible category name and selected state. Case context stays
compact, full metadata and hints remain available, and controls support
touch and keyboard input. Desktop space expands the same content and
navigation rather than changing its workflow meaning.

Media stays behind the existing authenticated attachment boundary. Images
fit the viewport, can be browsed and rotated without changing stored files,
and audio uses explicit user playback. Category/case changes release active
media. Existing authorization, masking and workflow gates remain authoritative.


The category API includes additive `source_category` provenance so consolidated
COD evidence can retain its configured narration and disease grouping. Workspace
metadata includes status-only `smartva_status` and `smartva_can_run`; masked
Step 1 still withholds result content. SmartVA buttons use the existing coding
submission action and its authorization and CSRF protections. Read-only views
never offer execution. No schema or stored clinical data changes are needed.

## Component presentation

Reusable visual elements in the HTMX coding workspace guide the surrounding
Expo browser layout, badges, alerts and evidence panels. Editable questions
reuse the Expo native controls already used in the VA collection interview.
DORIS reuses the existing WHO-standard certificate component and structure.
Response badges must retain readable text and real inner padding; informational
responses must not collapse into tiny circles. Questionnaires group each
question with its choices, distinguish selected answers, and use compact
responsive layouts with touch targets at least 44 pixels high.

The compact case header shows form ID, age, sex and the DEMO marker in that
order when demo metadata is true, at every viewport width. The category rail
remains independently scrollable with no scrollbar obscuring its icons.
Presentation changes preserve scoring, save payloads and workflow gates.
