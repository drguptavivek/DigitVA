---
title: DORIS COD Workflow
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-09-26
---

# DORIS COD Workflow

## Project setting and storage

`va_project_master.masked_cod_required` defaults to true and
`cod_entry_mode` defaults to `simple`. The accepted combinations are
masked/simple, unmasked/simple, and unmasked/DORIS. DORIS requires an ICD-11
project. Existing projects therefore keep their historical two-step coder and
reviewer flow. The additive migration is `c7a4e2d9f1b6`.
It also adds unique indexes for active coder and reviewer finals by submission
and non-null payload version. Before applying it to an existing database,
check for duplicate active rows on those keys; the migration stops if any
exist rather than discarding or choosing a clinical record automatically.

An unmasked/simple coder or reviewer submits one final assessment with an
immediate COD, an underlying COD and optional associated-condition text. In
unmasked/DORIS, the MO enters a Part I/II certificate, processes it, reviews
the DORIS and CoDEdit outputs, and independently confirms a final underlying
COD. The reviewer has a separate editor and final row; the coder certificate
can be copied into it without changing the coder's record.

Both final-assessment tables store the final certificate, independent DORIS
and CoDEdit envelopes, human final COD, and a snapshot of project mode, ICD
release and WHO image digest. The final COD remains the value used by final
authority and COD bucket reporting. No intermediate Process call writes a
draft or assessment row.

## Process and final save

The public Help certificate and the clinical coder/reviewer certificate now
share a small JavaScript postcoordination picker. Search results with WHO
postcoordination availability offer a stem builder, while complete expressions
remain directly selectable. The builder obtains the pinned WHO release's axes
through DigitVA's CSRF-protected public or clinical POST API, labels required
axes, and lazily loads bounded child choices. The hierarchy view shows the
ancestor path and nearby nodes. Uncoded WHO folders can be expanded but are
not selectable. The browser previews `&` extensions and `/` additional stem
codes as one condition, then calls the existing server selection check before
adding one chip. The clinical editor's existing edit path invalidates current
processor results, process proof, and final UCOD after a chip changes. The
vendored WHO ECT remains available from the editor.

The shared normalization and traversal service is
`app/services/icd11_postcoordination.py`. Public routes are under
`/api/v1/doris-demo/`; clinical routes with case authorization are under
`/api/v1/doris-clinical/`. Both expose `postcoordination`,
`postcoordination-options`, and `hierarchy`. WHO's exact multiple-value rule
is preserved, including the restriction against two choices from the same
block. A two-slot guidance limit and bounded call budget protect request
capacity. When a root or child option list has more than 12 choices, the response
marks it truncated and the guided picker disables selection; coders can
search for a complete expression or use WHO ECT. No schema change or new
stored data is involved.

The authenticated `/api/v1/doris-clinical/process/<va_sid>` endpoint checks
form access, role, active allocation, active submission payload and project
mode. It validates the certificate and its selected ICD-11 code/URI pairs
against the pinned local WHO release, then calls DORIS and CoDEdit
independently. The response has separate processor statuses and a short-lived
signed token binding certificate and result digests to the case, actor,
allocation, payload version, release and WHO image.

Every certificate edit clears the browser's processor results and human UCOD
choice. At final save, the server normalizes the submitted certificate and
checks both processor envelopes and the signed token. A changed certificate
is reprocessed and returned as `409 DORIS_CERTIFICATE_CHANGED` with fresh
results; no row is saved until the MO reviews and confirms a UCOD again. An
expired or mismatched token also requires fresh processing. An exact match
saves the final certificate, processor outputs and independently validated
human UCOD in the same transaction as the existing workflow and audit changes.
WHO processor failure is advisory when codeinfo verification still works;
codeinfo failure blocks final ICD-11 provenance validation.

## Public training service

The synthetic Help demonstration is served by `doris_public_service`, a
database-free Flask process reached through `digitva_ingress`. The ingress
sends `/help/doris-demo` and `/api/v1/doris-demo/*` to the public process and
other paths to the clinical app. The public process uses six Gunicorn request
threads, five bounded Process slots, a separate session cookie, CSRF on its
application POSTs, and a 12-second response deadline. Its read-only ECT
proxy is the sole CSRF-exempt POST. Both ingress and Gunicorn omit query
strings from access logs. Direct access to the clinical app does not serve
the public DORIS demonstration; the public hostname must point to the ingress.

The pinned WHO image is `whoicd/icd-api:2.6.0` with MMS `2026-01` and image
digest `sha256:1b77eb6dc43e0c65a12e9e9340ad178493c93488e728d0d936507cc57ada1b7c`.
Changing that digest requires a fresh contract and fixture review.
The clinical process refuses a `DORIS_WHO_IMAGE_DIGEST` environment override
that differs from this pinned digest. Before routing a production hostname to
the ingress, configure a secure public cookie for TLS and verify the deployed
WHO image digest and ingress log format against this release.

Policy: [DORIS COD Workflow Policy](../policy/doris-cod-workflow.md).
