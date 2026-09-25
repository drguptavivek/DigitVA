---
title: WHO ICD-11 Embedded Coding Tool Demo
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-26
---

# WHO ICD-11 Embedded Coding Tool Demo

The `/help/icd-codes/search-demo` page may show the WHO Embedded Coding Tool
(ECT) 1.8 beside DigitVA's existing ICD-11 coding search. ECT uses the local
WHO ICD API with `source=mms`, `minorVersion=2026-01`, and `language=en`.
Full coding mode retains related words, flexible search, details, hierarchy,
and postcoordination exploration. The JavaScript and CSS are served from this
repository rather than a remote CDN.

This is a read-only comparison. An ECT selection may display `code`, `title`,
`linearizationUri`, `foundationUri`, `selectedText`, and `searchQuery`. The
older `uri` and `bestMatchText` callback fields are deprecated and are not the
demo's data contract. A selected code can be checked against DigitVA's
existing age/sex/selectability search for the chosen demo context. A missing
local result is not proof that the WHO entity is invalid; it means DigitVA
does not offer that code as a selectable option in the current context.

The demo does not write an assessment, alter a coding policy, or select an
underlying cause of death. Production coding-screen integration requires an
authenticated same-origin API path and server-side validation of each ECT
selection. DORIS use is a separate mortality-selection workflow.
