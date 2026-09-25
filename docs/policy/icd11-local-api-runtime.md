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
`http://localhost:8382/browse`. It does not change DigitVA's coding search,
saved assessments, or cause-of-death selection.

`acceptLicense=true` reflects the owner's requested WHO container command.
`saveAnalytics=false` prevents search analytics being sent to WHO. Do not put
clinical text or identifiable records into this evaluation service until a
deployment and data-protection review is complete. The API has no application
authentication at this local port; any production integration needs a
same-origin authenticated route and DigitVA's existing server-side coding
policy checks before a selection can be saved.

The Coding Tool finds ICD-11 concepts. DORIS separately applies mortality
selection rules to coded conditions. Neither replaces DigitVA's VA coding
policy or workflow without an explicit design and clinical review.
