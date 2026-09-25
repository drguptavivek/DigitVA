---
title: Local WHO ICD-11 API Runtime
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-26
---

# Local WHO ICD-11 API Runtime

The optional `icd_api_service` runs the WHO ICD API 2.6.0 with the ICD-11 MMS
2026-01 English release. It includes the Coding Tool (`/ct`), Browser
(`/browse`), and DORIS endpoints. The image is pinned by digest in Compose.

For local evaluation, its port is bound to `127.0.0.1:8382` only. Start it with
`docker compose up -d icd_api_service`; open `http://localhost:8382/ct` or
`http://localhost:8382/browse`. The production assessment integration uses a
same-origin DigitVA route to reach the service by its Compose name; coder and
reviewer browsers do not use this loopback address. Start the `icd11` Compose
profile wherever ICD-11 assessments are enabled. See
[ICD-11 Embedded Coding Tool in Assessments](icd11-ect-production.md).

`acceptLicense=true` reflects the owner's requested WHO container command.
`saveAnalytics=false` prevents search analytics being sent to WHO. The API has
no application authentication at the local port; production search is routed
through DigitVA authorization, and every selected code is checked again on
save. Avoid sending identifiable records with a terminology query.

The Coding Tool finds ICD-11 concepts. DORIS separately applies mortality
selection rules to coded conditions. Neither replaces DigitVA's VA coding
policy or workflow without an explicit design and clinical review.
