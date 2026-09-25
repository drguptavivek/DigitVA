---
title: ICD-11 Embedded Coding Tool in Assessments
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-26
---

# ICD-11 Embedded Coding Tool in Assessments

## Scope

For a death coded in ICD-11, coder and reviewer assessment fields use WHO's
Embedded Coding Tool (ECT) 1.8 with the locally deployed ICD-11 MMS 2026-01
English API. ICD-10 fields retain their existing search control. The ECT is a
terminology and code-selection aid; selecting a result does not save or approve
it on its own.

## Access and availability

The browser calls the WHO API through an authenticated, same-origin DigitVA
route scoped to the submission. The route checks coding or reviewing access
and the project's ICD classification before relaying bounded ICD API requests
to the Compose service. It does not relay browser credentials or arbitrary
hosts to WHO. The WHO container remains bound to loopback for local evaluation
and is not published as an unauthenticated production endpoint. If the API is
unavailable, ICD-11 search and new cluster validation fail visibly; existing
saved values remain readable.

## Selection and save

The assessment stores the complete WHO `code` expression followed by its
display text in the existing COD text field. A post-coordinated expression is
never shortened to its first stem during save. DigitVA verifies a cluster
against WHO `codeinfo` for the pinned release, then checks the returned first
stem against its active local ICD-11 coding policy and the death's age and sex.
An invalid expression or an unavailable validation service blocks the save.
The assessment also stores nullable `icd11_provenance` JSON with the complete
code expression, the local catalog's canonical title, the selected display
text, the release, and server-verified WHO linearization and codeinfo URIs.
The foundation URI is retained when the catalog has one. Plain stems and
clusters both obtain their URI metadata from the pinned local WHO API at save.
Legacy and ICD-10 rows have no provenance JSON. The original clinical narrative
is not replaced by the selected classification label.

For VA bucket reporting, the already approved rule remains: a cluster maps by
its first stem. The complete expression remains in the assessment for clinical
review and export. The Coding Tool does not select the underlying cause of
death; DigitVA's assessment workflow retains that decision.

## Upgrade boundary

The MMS release used by ECT, `codeinfo`, and the DigitVA local catalogue must
match. Moving to a new release requires review of code changes and policy
before the version is changed; historical COD text is not rewritten.
