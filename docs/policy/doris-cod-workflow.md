---
title: DORIS COD Workflow Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-26
---

# DORIS COD Workflow Policy

## Project modes

Existing projects remain masked and simple. A project may use one of three
combinations: masked/simple, unmasked/simple, or unmasked/DORIS. DORIS requires
`icd_classification='icd11'`; `icd10` and `selectable` are invalid for this
mode. A project's settings do not rewrite completed assessments.

Masked/simple retains the current two-step coder and reviewer workflow.
Unmasked/simple has one final assessment with an independently validated
immediate COD, underlying COD and optional associated-condition free text.
The underlying COD alone controls final authority and VA bucket reporting.

## DORIS entry and confirmation

The MO enters an ordered Part I/II certificate. One interval applies to each
line and is copied onto every condition on that line in the WHO request.
New blank editors show three Part I lines. Unused blank lines are omitted
from the processed certificate; filled lines retain their visible order.
A blank line between filled lines must be filled or removed before processing.
After a line's condition codes, the editor asks for the interval from onset
to death as a value and time unit. It serializes the answer as the WHO
certificate's ISO 8601 `Interval`, while existing saved durations remain
lossless on load and resubmission. Changing either interval control
invalidates current processor results and the final UCOD.
The server rejects nonempty intervals that are not valid ISO 8601 durations;
an empty interval and WHO unknown-duration markers remain valid.
Unknown fetal or infant measurements are omitted, rather than represented
by `9`. Every selected code/URI pair is checked against the pinned WHO
release before processing. DORIS computes guidance; CoDEdit findings are
advisory. Neither automatically sets the MO's final underlying COD.

The certificate picker may start with an ICD-11 stem, show its location in
the WHO hierarchy, and show matching terms, related maternal/perinatal
categories, and extension axes and choices supplied by the pinned WHO release.
Required postcoordination is identified before selection. A selected
extension or additional stem produces one complete condition expression
and WHO URI expression, using WHO's `&` or `/` separator as applicable;
the UI must not split it into separate certificate conditions or lines.
The same picker is available for coder, reviewer and synthetic Help entry.
The completed expression goes through the existing server selection check
before it is added. Changing a chosen extension has the same invalidation
effect as any other certificate edit.

Editing any certificate input clears the displayed processor results and
the MO's final UCOD choice. Save remains disabled until the edited form is
processed and the MO confirms a final UCOD again. A clinical Process response
includes a short-lived signed token binding certificate and result digests
to the case, allocation, payload version, WHO release and image. At final
save, the server checks the submitted certificate and processor outputs
against that token. If the certificate changed, it reprocesses it, returns
`409 DORIS_CERTIFICATE_CHANGED` with fresh results, saves nothing and asks
for reconfirmation. If the token and data match, it saves the final
certificate, verified DORIS/CoDEdit outputs and the MO's separate final UCOD
atomically. It does not store drafts or intermediate Process responses.

A DORIS or CoDEdit failure does not by itself bar a human final UCOD when
independent WHO codeinfo validation works. A whole WHO API outage blocks
ICD-11 final-code provenance validation and final save. Coder and reviewer
assessments remain separate; the reviewer may start from the coder's saved
certificate but never changes it.

## Public Help proof

The public Help proof uses six synthetic certificates and stores no clinical
record. Its Help page and APIs run on a dedicated same-origin service so
public WHO calls do not occupy clinical Flask request workers. Application
POSTs require CSRF; only the read-only WHO ECT proxy POST is exempt because
ECT cannot attach the token. Release validation must show five parallel
public Process submissions while clinical requests remain responsive.
Input, output, time and access-log limits apply before public release.
