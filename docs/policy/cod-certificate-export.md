---
title: Cause-of-Death Certificate Export
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-11-20
---

# Cause-of-death certificate export

Owner decision 2026-11-20. Each coded case of an organization (tree) project
has a printable page laid out like the WHO International Form of Medical
Certificate of Cause of Death, showing the coding result. The user saves it
as a PDF with the browser's print dialog; the server adds no PDF dependency.

## Who and when

- Route: `GET /coding/area/<va_sid>/certificate` (browser session, Flask page,
  not an Expo route). Allowed exactly where the read-only case view
  (`/coding/area/<va_sid>`) is: `Action.VIEW` through `authz`, same role list.
- Available only when all hold; otherwise **404**, whatever the reason, so the
  page never reveals which one failed: the case is coded (workflow coding
  bucket `coded`: coder final, or reviewer final); the project has an active
  organization level (`authz.grants.has_tree_condition`); the case is in the
  caller's scope; the case is not a confirmed duplicate and not
  consent-withdrawn (the shared exclusion; for admins too, because issuing a
  certificate is a use of the data that withdrawal stops). Site (non-tree)
  projects have no certificate.
- Every successful view writes one `va_submissions_auditlog` row (operation
  `r`, action `cod_certificate_viewed`, ids only, no content).

## Content

- Source: the **final** result: the reviewer's final assessment when the case
  was reviewed, else the coder's (`final_cod_authority_service`). Part I
  lines (a) to (d) and Part II come from that final's DORIS certificate
  (`Part1[].Conditions[]` with `Text`, `Code`, `Interval`; `Part2.Conditions`).
  A masked DORIS project keeps its certificate on the Step 1 row, so the
  final's own source Step 1 row is the fallback (same role only, never the
  coder's certificate under a reviewer's final).
- When the final has no Part I structure (an ICD-10 or simple final, or a
  masked final with no Step 1 certificate) lines (a) to (d) are printed blank
  and the underlying cause is still printed from the final's conclusive COD.
- Underlying cause is the final's stored conclusive COD text, code and title,
  as saved. No WHO API call is made when the page opens.
- Case details: masked case id, age, sex, date of death when the certificate
  records it.
- Coding: date coded, review outcome (not reviewed, reviewer agreed, reviewer
  changed the cause), coder and reviewer names.
- Footer: "Cause of death assigned through verbal autopsy. Not a legal death
  certificate.", project name, generated-at in the viewer's timezone.

## PII

One gate: `viewer_pii_service.should_redact_pii(user, project_id=...)`.
Not redacted: deceased name, exact address, place of death, respondent
(informant) name, the real case identifier, and the coder and reviewer names
(staff identity is redacted by the same gate elsewhere). Redacted: each of
those prints "—" and nothing identifying is in the HTML. Sex, age and the
certificate's date of death print for every viewer, as DORIS already shows
them to every coder (`doris-cod-workflow.md`).

## Out of scope

- The Collect native app has no web pages and does not offer the certificate
  (follow-up).
- No stored PDF, no email, no bulk export.
