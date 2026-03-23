---
title: Final COD Authority Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-03-23
---

# Final COD Authority Policy

## Purpose

DigitVA may contain multiple COD-related records for the same submission over
time:

- initial COD assessment
- finalized coder COD
- recode attempts
- finalized reviewer COD after reviewer secondary coding

This policy defines which COD is considered the operative final COD for the
submission at any given time.

## Design Rule

The system must distinguish between:

- COD records that exist historically
- the single COD outcome that is currently authoritative for the submission

The presence of multiple COD-related records must not make the current final COD
ambiguous.

## Business Question

For any submission, DigitVA must be able to answer:

- what is the current authoritative COD?
- who established it?
- when did it become authoritative?
- was it superseded later?

## Current Authority Order

The intended authority order is:

1. reviewer finalized COD, if an active reviewer final COD exists
2. coder finalized COD, if active and not superseded by reviewer final COD
3. no final COD yet

Initial COD is never the authoritative final COD.

It is an intermediate working assessment only.

## Coder Finalized COD

A coder-finalized COD becomes authoritative when:

- final COD has been successfully submitted
- no active reviewer final COD supersedes it

The authoritative record should identify:

- submission SID
- coder user
- finalized COD value
- effective timestamp

## Reviewer Final COD

Reviewer is not an accept/reject QA overlay. Reviewer is an optional secondary
coding path that opens only after the coder's 24-hour recode window closes.

If reviewer workflow later records a reviewer final COD, that reviewer final
COD becomes authoritative.

This reviewer finalization must:

- preserve the original coder-finalized COD in history
- clearly identify that the coder COD was superseded
- make the reviewer COD the current operative COD

## Recode Rule

During recode:

- the existing authoritative final COD remains authoritative until replacement
  final COD is successfully saved
- incomplete recode work must not replace the existing authoritative final COD

Once replacement final COD is successfully saved:

- the previous authoritative coder COD becomes superseded
- the replacement coder COD becomes authoritative unless a reviewer final COD
  later supersedes it

## Not Codeable Rule

If a submission is marked Not Codeable:

- the submission has no authoritative final COD
- the authoritative business outcome is the Not Codeable status itself

This applies to:

- coder Not Codeable
- data-manager Not Codeable

## Reporting Rule

Dashboards, exports, and APIs that expose a submission's final COD must use the
authoritative COD only.

They must not expose:

- initial COD as if it were final
- stale superseded finalized COD as current
- an incomplete recode draft as current

## Audit Expectations

The system should preserve enough information to reconstruct:

- original finalized coder COD
- superseded finalized coder CODs
- reviewer finalized CODs
- timestamps and actors for every authority change

## Migration Implication

Current implementation may infer final COD from active rows in
`va_final_assessments`.

Current implementation note:

- `va_reviewer_review` is a legacy reviewer QA/quality-review artifact
- it is not the target reviewer final-COD artifact
- additive reviewer final-COD storage now exists in
  `va_reviewer_final_assessments`
- reviewer runtime can now create reviewer final-COD rows in that table
- `va_final_cod_authority` now has reviewer-pointer support and service-level
  precedence can resolve reviewer final COD over coder final COD
- coder and reviewer final-COD rows are now stamped with the submission's
  current `payload_version_id`
- authority resolution ignores stale coder/reviewer final-COD rows from older
  payload versions and prefers only artifacts from the current active payload
  lineage
- remaining cutover is downstream reader parity across analytics/reporting and
  any direct artifact readers

The workflow-state migration should introduce an explicit way to identify the
single authoritative COD for each submission so reporting and downstream
workflow do not depend on fragile inference alone.
