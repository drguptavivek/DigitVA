---
title: Offline PHC Desktop Edition Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-20
---

# Offline PHC Desktop Edition Policy

## Purpose

The **DigitVA Field / PHC Edition** enables a Medical Officer (MO) at a remote Primary Health Centre (PHC) to operate completely offline on a desktop workstation (Windows, macOS, Linux) and synchronize completed verbal autopsy (VA) cases with a central DigitVA server either via an encrypted offline export package (`.digitva-export`) or via direct HTTPS push when connectivity is available.

## Scope Boundaries

### Included in the Standalone Desktop Edition

1. **Station Provisioning**:
   - Offline file import of a signed `.digitva-config` provisioning package issued by the central server (`Ed25519` signature verification).
   - Online one-time enrollment code exchange against the central server when initial connectivity is available.
2. **Standardized Forms & Data Collection**:
   - Death registration (intake) and standardized `WHO_2022_VA` + enabled project extensions (`@drguptavivek/who-2022-va`) rendered via the shared React/Expo client (`mobile/digitva-collect`).
3. **Offline SmartVA Automated Scoring**:
   - In-process execution of `vendor/smartva-analyze` + DigitVA transformation (`app/utils/va_smartva`) embedded into the Rust runtime via `PyO3`, with `TariffPrep` validation matrices cached in memory and zero C/Fortran extension dependencies.
4. **Offline ICD-10 / ICD-11 / DORIS / CoDEdit Coding**:
   - Local FTS5 reference catalogs (`mas_icd10_2019_2`, `mas_icd11_mms`, `mas_icd_search_terms`, `mas_va_cause_definitions`, `map_icd_cod_buckets`) stored in SQLite.
   - Managed local sidecar running the official WHO ICD-11 API `2.6.0` (`ICD-API.dll` + `DorisRuleEngine.dll`) against pre-staged offline `2026-01_en` and `DORIS_v2.1_1.2.0` bundles on `127.0.0.1:0` with zero outbound network requests.
5. **Local Results, WHO MCCD PDF Export & Federated Sync**:
   - **WHO Standard Medical Certificate of Cause of Death (MCCD) PDF Export**: Deterministic offline A4 PDF generation (`GET /api/v1/cases/<va_sid>/certificate.pdf`) following the official WHO International Form of Medical Certificate of Cause of Death layout:
     - **Administrative & Identification Header**:
       - **Unique IDs**: Death Registration ID (`death_id`), VA Submission / Case UID (`va_sid` / `instance_id`), and Station ID (`station_id`).
       - **Site & Project**: Project Name & Code (`project_id`), PHC / Facility Site Name & Code (`site_code`, `site_name`).
       - **Deceased Details**: Deceased Name, Sex, Date of Birth, Date of Death, Age at Death, and Place of Death.
     - **Frame A — Medical Data**: Part 1 (Lines `a`, `b`, `c`, `d` causal sequence with condition text, ICD-10/ICD-11 codes, and human-readable time interval from onset to death) and Part 2 (Other significant conditions contributing to death).
     - **Frame B — Other Medical Data**: Surgery within 4 weeks, Autopsy requested/findings used, Manner of death, External cause date/description/place of occurrence, Fetal or infant death details, and Pregnancy/maternal death details (respecting V1–V6 applicability rules in `docs/policy/doris-certificate-rules.md`).
     - **Underlying Cause of Death (UCOD) & Certification Footer**:
       - DORIS-computed UCOD (when applicable) and MO-confirmed Final Underlying Cause of Death (Code + Title + VA Cause Group).
       - **Coded By**: Medical Officer Name, Coder ID / Email, and PHC Site.
       - **Date Coded**: Certification date and timezone-aware timestamp, plus physical Signature/Stamp block and cryptographic certificate verification digest.
   - Local summary table and CSV export of registered deaths, interview status, SmartVA top causes, and physician-assigned underlying causes of death (UCOD).
   - Federated outbox producing AEAD-encrypted (`X25519` + `ChaCha20-Poly1305`) and station-signed (`Ed25519`) `.digitva-export` bundles for offline transfer or direct HTTPS push to `POST /api/v1/federation/ingest`.

### Excluded (Central Server Responsibilities Only)

- Organization hierarchy management (`mas_org_level`, `mas_org_unit`, `ltree`), cadres, and mentoring institutes.
- Multi-user administration, role/grant management, and supervision/reconciliation queues.
- ODK Central synchronization (`pyodk`) and Celery/Redis background workers.
- UI translation dictionary authoring.

## Data Protection & Idempotency Rules

1. **No Raw Sensitive Payloads in Logs**: Local desktop logs and federation logs must never emit raw VA answers, narratives, or tokens.
2. **Cryptographic Envelope**: Every `.digitva-export` package is encrypted to the central server's `X25519` public key from the station's `.digitva-config` and signed by the station's local `Ed25519` key.
3. **Idempotent Central Ingestion**: Every record in a federated export carries a deterministic `(station_id, instance_id, revision_hash)` key so repeated imports or HTTPS retries never duplicate or overwrite newer records on the central server.
