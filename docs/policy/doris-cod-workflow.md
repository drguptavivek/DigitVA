---
title: DORIS COD Workflow Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-27
---

# DORIS COD Workflow Policy

## Project modes

**ICD-11 means DORIS (implemented, `digitva-0n3` phase 1).** Choosing
`icd_classification='icd11'` always sets `cod_entry_mode='doris'`; choosing
`icd10` always means simple entry. The `selectable` classification (ICD-10
or ICD-11 chosen per death) is retired; the migration moved every dev
project on it to `icd10`. Masked and DORIS may now combine at the settings
level (`masked_cod_required` no longer forbids `cod_entry_mode='doris'`);
masked ICD-11 has its own Step 1/Step 2 flow (below). A project's settings
do not rewrite completed assessments.

Masked/simple retains the current two-step coder and reviewer workflow.
Unmasked/simple has one final assessment with an independently validated
immediate COD, underlying COD and optional associated-condition free text.
The underlying COD alone controls final authority and VA bucket reporting.
Unmasked/DORIS keeps today's one-step DORIS final assessment. Masked
ICD-11 is described below.

### Masked ICD-11 (`digitva-0n3`: coder and reviewer flows implemented)

Owner decision in docs/policy/doris-cod-workflow.md; design record
`.tasks/2026-09-27-icd11-means-doris.md`. DigitVA is not deployed anywhere,
so no production data is affected.

- **Masked ICD-11** keeps the two steps. Step 1 is the DORIS certificate,
  entered and processed without SmartVA. Step 2 only confirms the final
  underlying COD, which may be the DORIS result, the SmartVA result or the
  coder's own judgement; its code entry is the DORIS picker's ICD-11 search
  (the shared `digitva_icd11_picker.js` module), with no second certificate.
- **The masked ICD-11 reviewer** does the same. Their Step 1 certificate
  starts as a copy of the coder's Step 1 certificate (or their own saved
  one); they process it with DORIS themselves and confirm their own
  underlying cause. The coder's records never change. Their Step 2 confirms
  the final underlying COD with the same three choices.
- **SmartVA for the masked reviewer.** The masked reviewer sees SmartVA in
  Step 2 (never in Step 1) for every masked project, ICD-10 included.
- The local ICD-11 catalogue search (`search_icd11_mms`) remains for the
  admin ICD-11 browser and Help pages, not for ICD-11 coding.

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

Extension axes follow WHO's presentation: required axes come first, each
axis is its own section in WHO order with WHO's instruction wording, and
each axis offers a search limited to that axis's WHO subtree. A final
"Other postcoordination?" search over the extension-code chapter appears
only for MMS category stems outside that chapter, as WHO's coding tool
does. Uncoded WHO folders can be expanded to their coded children but are
never selectable themselves. Related maternal or perinatal panels present
WHO's exact composite category first, before the broader category list.

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

DORIS never fills the final UCOD on its own. A "Use DORIS result" button in the
final UCOD step copies DORIS's suggested code into the field only when the MO
clicks it; the code is checked through WHO `codeinfo` and the selection check
like a searched code, and the MO may replace it before saving.

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
