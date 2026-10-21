---
title: Message to the offline PHC session, 2026-10-21
doc_type: kb
status: active
owner: Vivek Gupta
last_updated: 2026-10-21
---

Plain text to send as is. The contract is docs/policy/offline-api-contract.md.

```text
To the offline PHC session, from the main DigitVA session, 2026-10-21.

The backend contract is final: all owner decisions are resolved (contract
section 12). Read docs/policy/offline-api-contract.md first; bundle bytes are
in docs/policy/offline-bundle-and-transfer.md. Both, and the code they cite,
are in the main checkout and land in commit <hash to follow>.

DROP from your current design
- Federation (phase 5), POST /federation/ingest and the .digitva-export
  envelope: one sealed format (.dvb, contract 4) and our ingest only.
- Device-side consent withdrawal: withdrawal is web only; you get purge ids.
- Standalone "all roles, no accounts" as real work: it is a sandbox only,
  never ingestable, never remapped into a project.
- Plain SQLite: SQLCipher, one store per roster user, per-user PIN.
- Hardcoded consent contacts, purposes, notice text or sealed field lists:
  read them from the signed station config; no fallback.
- identifier_warnings, matching_death_ids, consent_status, "phone only if
  granted", a "provisional" MCCD PDF watermark.

LATER DECISIONS (same day, in contract 12.8-12.11)
- Station supervisors correct death details only until the interview
  completes; after it, identifiers only. Closed cases: web only.
- station_supervisor can be issued only to someone who already holds a server
  interview_supervisor grant at that site; the server re-checks on each edit.

ADD
- Onboarding: a station is ingestable only when enrolled with a custodian
  (responsible person) recorded; the signed station config carries
  custodian, designations and roster (contract 4.1). Never-online stations:
  the signed roster is the attestation, no per-user online sign-in.
- Roster: [{user_id, name, designation, roles: [{role, project_id, site_id,
  org_unit_id}], active}], role in death_reporter|interviewer|
  station_supervisor|coder. Provisioned: read-only, server user ids.
  Sandbox: local editable roster (designations Medical Officer, Health
  Supervisor, Health Worker / ANM / MPW, Other; ticks; active), no
  passwords, "who am I now" picker, local change log, local UUIDs.
- Acting role per task; every record carries actor_user_id and
  acting_role; coder acting role = masked view even for an interviewer.
- station_supervisor is a roster role, not a device grant: never in
  /me/access. It may send death_correction (until an interview is complete)
  and identifiers_set (any time), in a bundle or by PATCH /intake/deaths/<id>
  and PUT /intake/cases/<id>/identifiers with acting_role, reason, client_id;
  if_updated_at or base_client_id for stale; closed cases refused (web only).
  Other roles' corrections stay HTTPS only ("Sent only when online").
- Consent at REGISTRATION (as web/Expo): informant name/phone/address only
  after a granted record; death_registration.consent_client_id; consent
  client_draft_id null; the interview reuses it, re-ask only for a
  different informant.
- Purge: list of client ids (withdrawn consent ids, closed case ids) in the
  station config (GET /intake/station-config on the device bearer, at
  sign-in and daily) and in receipts; same format on both paths.
- MCCD PDF from an offline coded result: print normally, no watermark.

UNCHANGED (from the earlier message)
- identifiers is a LIST [{code,label,value}] or [{code,label,present}];
  warnings [{code:"identifier_in_use", field, message}]; absent
  can_edit_identifiers = false. Refusals: POST 422 invalid_registration,
  PATCH 422 invalid_death, PUT 400 invalid_request, fields
  ["identifiers.<code>"]; body {error, code, fields}, no reason key.
- Anchored regex full match; phones 10 ASCII digits; Id10073 XXXXXXXXX123 or
  XXXXXXXXXXXX only; no partial digits anywhere.
- Consent object fields (contract 5.3); integer version compare.
- Local server rules (contract 9); no server case list; coder views omit
  sealed_field_ids.

WHAT WE BUILD (server): digitva-gb8w.2 ingest, corrections, receipts; .3
consent; .4 station config (roster, custodian, purge); .5 signing key; .6
vectors; .7 tests; .8 roster; digitva-athy web consent and withdrawal.

Open check: Id10476 narrative parity for SmartVA.
Please reply with where this does not fit before building.
```
