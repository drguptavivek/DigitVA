---
title: Local WHO ICD-11 API Runtime
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-26
---

# Local WHO ICD-11 API Runtime

The optional `icd_api_service` runs the WHO ICD API 2.6.0 with the ICD-11 MMS
2026-01 English release. It includes the Coding Tool (`/ct`), Browser
(`/browse`), and DORIS endpoints.

Owner decision 2026-10-22: the server hosts the unmodified WHO assemblies
in-process through the Rust binary `digitva-icd11-server` instead of running
the `whoicd/icd-api` container. Incorporating the unmodified WHO assemblies is
allowed; they are never decompiled, disassembled or modified. They are
downloaded on first start from WHO's pinned image and CDN and verified against
SHA-256 pins. Runtime details and the rollback to the container:
[Runtime And Operations](../current-state/runtime-and-operations.md#who-icd-11-service).

The offline PHC station (`digitva-server`) loads the same assemblies into its
own process. The WHO bundle's runtimeconfig asks .NET for server GC (one heap
per core): measured 2.1 GB resident against 654 MB with workstation GC. A
station serves one computer, so `digitva-server` sets `DOTNET_gcServer=0` at
startup, before any thread or the engine starts, unless the operator has set
`DOTNET_gcServer` already (that value is kept).

For local evaluation, its port is bound to `127.0.0.1:8382` only. Start it with
`docker compose up -d icd_api_service`; open `http://localhost:8382/ct` or
`http://localhost:8382/browse`. The production assessment integration uses a
same-origin DigitVA route to reach the service by its Compose name; coder and
reviewer browsers do not use this loopback address. Start the `icd11` Compose
profile wherever ICD-11 assessments are enabled. See
[ICD-11 Embedded Coding Tool in Assessments](icd11-ect-production.md).

`acceptLicense=true` (set by the bridge, as in the WHO container command)
reflects the owner's acceptance of the WHO licence.
`saveAnalytics=false` prevents search analytics being sent to WHO. The API has
no application authentication at the local port; production search is routed
through DigitVA authorization, and every selected code is checked again on
save. Avoid sending identifiable records with a terminology query.

The Coding Tool finds ICD-11 concepts. DORIS separately applies mortality
selection rules to coded conditions. Neither replaces DigitVA's VA coding
policy or workflow without an explicit design and clinical review.

## ICD-11 licence obligations

WHO ICD-11 is licensed CC BY-ND 3.0 IGO (bead `digitva-zde8`). What the code does:

- **Citation (licence 2.6).** One wording: `app/services/icd11_licence.py`
  (`ICD11_CITATION`, Jinja global `icd11_citation`) for server pages and
  exports, and `icd11Citation` in `mobile/digitva-collect/src/strings/en.json`
  (identical English copy in `hi.json`) for the Expo app. A test keeps them
  equal. Shown under the DORIS panel and simple ICD-11 coding panel (web and
  station), the Settings screen, the DORIS editor partials, `/help/doris-demo`
  (and the public demo), the ICD-11 and ICD code help pages, the coded-COD
  snapshot CSV and public ICD-11 state CSV (final `#` row), and the station
  certificate PDF footer (ICD-11 certificates only).
- **Code plus URI (1.2.2).** Saved ICD-11 finals keep `linearization_uri` in
  `icd11_provenance`; the DORIS certificate keeps `LinearizationURI`. The
  coded-COD snapshot CSV exports `*_icd11_stem_uri` beside each ICD code and
  the public ICD-11 state CSV carries `linearization_uri`.
- **DigitVA additions (1.2.4).** VA cause definitions are labelled
  "DigitVA addition - not from WHO" in the web panels and the Expo details
  sheet, and `/api/v1/va-definitions` payloads carry `source: "digitva"`.
- **Mappings and translations (1.2.3).** Inventory for the owner's decision on
  a WHO agreement: `docs/kb/icd11-licence-inventory.md`.
- The engine must keep `saveAnalytics=false` (`docker-compose.yml`) and never
  phone home from Android or the station.

## WHO correspondence on offline use

On 2026-10-21 the owner asked the WHO ICD team (icd@who.int) to confirm four
points for the offline desktop (in-process .NET host) and Android (NativeAOT)
engines: (1) permission under licence 2.3 to incorporate the ICD-API 2.6.0 /
DORIS 1.2.0 assemblies and data, (2) that NativeAOT compilation of the
unmodified assemblies is not a modification under 2.4, (3) any WHO-preferred
Android or offline method, (4) an attribution format for offline use.

WHO replied (Carine, ICD team) recommending that DigitVA use the components
that fit its architecture and call the ICD-11, DORIS and CodEdit API
endpoints directly, with no need to reproduce the desktop tools, and offered
a technical call with WHO colleagues. The reply does not answer points 1-4,
so it is not a written licence confirmation.

The correspondence does not establish written confirmation of points 1 and 2.
The server architecture and follow-up remain:

- Servers use the official `whoicd/icd-api` container. This is settled
  (owner 2026-10-26), not a stopgap: it is what WHO recommends.
- The offline engines (desktop host, Collect Plus `.so` bundle) stay
  experimental. On 2026-10-28 the owner explicitly overrode the earlier public
  publication hold for the latest signed Collect Plus APK, alongside Collect
  (`digitva-hs7e.17`). Publish the app package with its notices; do not describe
  that owner decision as WHO permission or separately publish the engine bundle.
- After the call, ask WHO for one written line covering points 1 and 2 and
  record it here.
