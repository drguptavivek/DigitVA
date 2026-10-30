---
title: DORIS Validation Checks
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-30
---

# DORIS Validation Checks

Every check a DORIS cause-of-death certificate meets, from the first search to
the final save, on the web and in Collect Plus. It lists what exists and where;
the rules themselves are owned by
[DORIS COD Workflow Policy](../policy/doris-cod-workflow.md) and
[DORIS Certificate Field Rules](../policy/doris-certificate-rules.md). The
workflow is described in [DORIS COD Workflow](doris-cod-workflow.md).

Severity words: **refuse** means the action does not happen and a message
says why; **warn** means a message shows and the coder may go on;
**confirm** means the coder must confirm before the save goes through.

## 1. Picker: search and staging

| Check | Where | Severity |
| --- | --- | --- |
| A line's search box and the picker's own box start a search on their own at 3 characters after a 500 ms pause ("Search auto-start" in the field rules); a manual search needs 2 characters ("Type at least 2 characters."). The builder's axis boxes search at 2 characters after 250 ms. Each search asks for 20 results. | `compact.tsx`, `IcdPicker.tsx`, `ScopedSearch.tsx`, `digitva_icd11_picker.js` | - |
| A stem whose postcoordination is mandatory is never staged alone: Use is hidden, its pill reads "+ Build (required)", and a pick opens the builder. Use shows when the code is complete or postcoordination is optional (the web's rule). | `needsBuild` and `stage()` in `IcdPicker.tsx`; row rules in `ResultRow.tsx` and `digitva_icd11_picker.js` | refuse |
| **Final codes only** (`digitva-9cll.12`). An extension code (WHO chapter X) alone shows an "Extension" marker and no Use; a pick shows "XK8G is an extension code. It cannot be used alone: add it to a stem through + Build." A category with children shows "Choose specific ▸", which opens its hierarchy. The hierarchy card disables "Use this code" and hides "Build expression" on such nodes. Every staging path (row, hierarchy, related terms, auto-builder) goes through `stage()`. Absent `leaf`/`extension` flags pass, and the selection check decides. | `notFinal` in `expression.ts`; `stage()` in `IcdPicker.tsx` and `digitva_icd11_picker.js`; `HierarchyCard.tsx` | refuse |
| Builder axis search ("Search in axis", "Other postcoordination?") is limited to the axis's WHO subtrees. A refused pick shows its message under the box, above the matches. | `ScopedSearch.tsx` | refuse |
| An extension code stays choosable inside the builder as part of an expression. | builder | - |

## 2. Selection check on OK

Each code the coder confirms is posted to `selection-check` (doris-clinical and
doris-demo routes). The server:

1. reads WHO `codeinfo` for the expression and verifies that the posted URI is
   the one WHO gives for that code. A tampered or stale pair is refused with
   `422 INVALID_SELECTION`, "The selected code does not match its WHO URI.";
2. then calls `selection_refusal` in `app/services/icd11_postcoordination.py`,
   which refuses an extension stem or a stem with children, for the first stem
   and every stem after `/`, with `422 INVALID_SELECTION` and the messages in
   section 1. A single code or an `&` expression costs no extra WHO call; each
   further `/` stem costs one codeinfo and one entity read.

Collect Plus offline runs the same rule from `selectionRefusal` in
`dorisTerminology.ts`. The phone also re-checks at OK that a mandatory stem was
built (`IcdPicker.tsx`); the web picker has no such re-check (gap G3).

Older APKs show "The selected code does not match its WHO URI." for every
`INVALID_SELECTION`, including the new refusals, because they show that fixed
line for the error code.

## 3. Certificate before Process

- **Field rules V1 to V12** (hide, disable, N/A note, warn) are in
  [DORIS Certificate Field Rules](../policy/doris-certificate-rules.md). They
  warn only; V12 says nothing in them blocks Process or Save.
- **Server structure** (`normalize_certificate` in
  `app/services/doris_certificate.py`) refuses: no Part I line ("Enter at
  least one Part I line."), more than 5 Part I lines, a line with no
  condition ("Enter at least one condition."), more than 8 conditions on a
  line, more than 20 conditions in all, empty or over-500-character condition
  or free text, a certificate over 32 KB, keys other than `Conditions` in a
  line, and coded values outside the code lists. Process answers
  `422 INVALID_INPUT` ("The DORIS certificate is invalid.") with the field
  errors (doris-clinical and doris-demo routes); the final save, reviewer and
  bundle-ingest paths answer `422 invalid_doris`.
- **Blank Part I line** between filled ones: the web editors and the phone
  refuse Process with the same words ("Fill or remove Part I line N before
  processing; blank lines cannot separate causes.", `doris_clinical.js`,
  `doris_demo.js`, `process` in `DorisPanel.tsx`). Only trailing empty lines
  are dropped before the certificate is sent (`processCertificate`).
- **Server value ranges** in the same file refuse, rather than warn:
  `DeathWithin24h` 0 to 24, `BirthWeight` 1 to 9999, `PregnancyWeeks` 1 to 50,
  `AgeMother` 10 to 80 (gap G4).
- **Inapplicable sections** are dropped, not refused: `drop_inapplicable_sections`
  removes the fields V1 to V6 hide, so a stale client cannot send them.

## 4. Process: DORIS and CoDEdit

Process sends the certificate to WHO's DORIS and CoDEdit and shows both reports.

- **DORIS** picks the underlying cause and may recode it (for example a
  category to its `.Z` code). Its warnings are translated through the warning
  catalogue (`scripts/generate_doris_messages.py`); an unknown warning is shown
  as DORIS wrote it.
- **CoDEdit** flags certificate errors, among them FER-CE-883 for an extension
  code used alone and "*code* is not a terminal code in the MMS linearization"
  (BER-CE-10) for a category. The final-code rule in section 2 keeps both from
  arising.
- **Proof of processing.** The final save carries the process token and result
  digest. A stale or mismatched proof is refused with `409 DORIS_PROCESS_EXPIRED`
  or `409 DORIS_PROCESS_MISMATCH` (`reviewer_coding_service.py`,
  `app/routes/va_form.py`); the coder processes again.

## 5. Final save

`submit_coder_final_cod` in `app/services/coder_cod_service.py` (the reviewer and
bundle-ingest paths refuse with the same `final_blocked` code) collects every blocking message and refuses
with `422 final_blocked`, listing them all:

- the underlying cause must be a selectable ICD-11 code for this death
  (`validate_icd11_mms_coding_value_for_submission`): its primary stem is an
  active category with `is_coding_selectable` (chapter 22 and non-selectable
  items are refused), the sex policy allows it, and a `/` cluster is valid at
  WHO. "*code* is not selectable for this submission.";
- the submission has an active payload version;
- Narrative Quality Assessment is done when the project enables it;
- Social Autopsy Analysis is done when the project requires it.

Before those, a code that fails only its age restriction is
`422 AGE_RESTRICTION_CONFIRMATION_REQUIRED`: the coder confirms and the
confirmation (who, when, DORIS warning) is stored in the provenance. Age warns,
sex blocks. "Causing condition not known" on a value that is not one ICD-11 stem
is `422 INVALID_CAUSING_CONDITION_FLAG`.

## 6. Collect Plus offline

The phone runs DORIS through the on-device engine and must not accept a code the
server would refuse ([policy](../policy/doris-cod-workflow.md), "Collect Plus
offline parity").

- The selection check runs locally (`selectionRefusal`), including the
  final-code rule.
- The allowability pack (chapter 22, non-selectable items, sex block, age
  confirmation) is applied when the final is saved (`judgeUnderlyingCause` in
  `offlineDoris.ts`), not in search or at OK (gap G1).
- The server re-applies the rules when the result is imported and flags a
  disagreement; it does not re-run DORIS.

## 7. Compared with WHO's DORIS workspace

Checked against https://icd.who.int/doris/workspace/en and the WHO API on
2026-10-30.

| Case | WHO workspace | DigitVA |
| --- | --- | --- |
| Extension code alone (XK8G) | Not offered in search. | Marked "Extension", refused. |
| Category with children (NC72, MG52.0) | Selectable, code shown grey. CoDEdit flags "not a terminal code"; DORIS recodes to NC72.Z. | Refused at selection; "Choose specific" opens the hierarchy. |
| Category as a `/` cluster part (`DB93.1/1E51`) | CoDEdit flags 1E51; DORIS recodes it to 1E51.Z. | Refused at selection. |
| Mandatory stem alone (DB93.1) | Selectable, no CoDEdit flag. | Must be built ("+ Build (required)"). |
| Field order | Estimated age after date of birth and date of death. | Same (Sex, DOB, DOD, Age). |

DigitVA is stricter than WHO on categories and bare mandatory stems, by owner
decision: WHO either flags them only after processing or recodes them silently.

## Known gaps

| Id | Gap | Bead |
| --- | --- | --- |
| G1 | Policy says the offline pack refuses in search and in save; the code applies it only at save. | `digitva-2j57` |
| G2 | No age or sex policy runs in the DORIS picker before save; the `age_restricted` tag is set only by `search_icd11_mms`, so DORIS terms never carry it. | `digitva-o16a` |
| G3 | The web `stage()` has no mandatory-stem guard and no OK re-check; only the hidden Use button keeps a bare mandatory stem out. | `digitva-l0ey` |
| G4 | The server refuses the four value ranges in section 3, which V11 only warns about, with different bounds. | `digitva-e505` |
| G5 | V9 "line above": the web compares with the nearest line above that has an interval, the phone only with the line directly above. | `digitva-giym` |
| G6 | The age-confirmation wording differs: the phone adds DORIS's plausibility sentence. | `digitva-37gr` |
| G7 | The WHO ECT assessment's `/api/v1/icd11/selection-check` still allows 2,077 non-leaf categories through the local catalogue. Owner decision pending. | `digitva-dn15` |
