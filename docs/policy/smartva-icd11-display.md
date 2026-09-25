---
title: SmartVA ICD-11 Display
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-26
---

# SmartVA ICD-11 Display

For `digitva-p11`, retain SmartVA's original cause text and ICD-10 code. Beside
each primary, secondary, and tertiary ICD-10 code, display the WHO
`10To11MapToOneCategory` target translated to the locally used ICD-11 2026-01
release. A target may contain `/` alternatives or `&` postcoordination; show
the complete expression, not a selected single ICD-11 code. Label it as a
mapping rather than a coded diagnosis. If the ICD-10 code has no crosswalk
entry, show "unavailable". No SmartVA or coder value is changed or saved.
