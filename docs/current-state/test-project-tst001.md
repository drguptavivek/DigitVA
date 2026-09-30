---
title: Test Project TST001 (Intake Test)
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-01
---

# Test Project TST001 (Intake Test)

`flask seed test-project` builds TST001 for testing the organization model and
both web-intake methods with a user in every role. Source:
`app/commands/seed.py`; test: `tests/test_seed_test_project.py`.

- Dev/staging only: it refuses unless the app is in debug or testing mode, or
  `--staging` is passed. It is not part of `flask seed run`.
- Idempotent: rows are found by natural key (project id, level code, unit code,
  cadre code, level x cadre, email, worker code, user x role x scope) and
  reactivated, never deleted. Existing users keep their password and profile.
- Project: organization mode, `web_intake_mode=both`, web defaults as the
  Projects panel applies them (WHO_2022_VA, pick-and-choose coding). The
  automatic site and its web form come from `ensure_organization_site`.
- Grants go through `project_user_import_service` (the admin import path), so
  the level x cadre rules are enforced and each write lands in `grants.log`.
- Every unit-placed user also has a `mas_org_unit_worker` row (worker code =
  email local part, upper-cased, dots as underscores).
- It passes `flask web-intake readiness TST001`; `geography_fields` warns
  because the bundled WHO questionnaire has no `org_<level>_code` fields.

## Tree

All four levels are mandatory (depth 1-4).

```
DH01  District Hospital            (dh)
└─ CHC01  Community Health Centre  (chc)
   ├─ PHC01  PHC-AAM 1             (phc)
   │  └─ SC01, SC02, SC03  SC-AAM 1-3   (sc)
   └─ PHC02  PHC-AAM 2             (phc)
      └─ SC04, SC05, SC06  SC-AAM 4-6   (sc)
```

## Level x cadre grid

| Level | Cadre | Fill | Code | Supervise |
| --- | --- | --- | --- | --- |
| dh | CS Civil Surgeon | | | Y |
| dh | DPM District Programme Manager | | | |
| dh | DEPI District Epidemiologist | | | |
| dh | MO Medical Officer | | Y | |
| dh | SN Staff Nurse | Y | | |
| chc | SMO Senior Medical Officer | | Y | Y |
| chc | MO Medical Officer | | Y | |
| chc | BPM Block Programme Manager | | | |
| chc | SN Staff Nurse | Y | | |
| phc | MO Medical Officer | | Y | Y |
| sc | CHO Community Health Officer | Y | | |
| sc | ANM Auxiliary Nurse Midwife | Y | | |
| sc | MPW Multipurpose Worker | Y | | |

## Roster

Every account is `<name>@digitva.com`, password `Aiims@123`, email verified,
onboarded, Asia/Kolkata, English. Unit-scoped grants carry the cadre.

| User | Unit / cadre | Roles | Landing |
| --- | --- | --- | --- |
| testadmin | project | admin (existing), project_pi | admin |
| test.pi | project | project_pi | admin |
| test.dm | project | data_manager | data_manager |
| test.faculty, test.resident | project | collaborator_pii, coding_tester | data_manager |
| test.cs.dh01 | DH01 CS | site_pi, interview_supervisor | sitepi |
| test.dpm.dh01 | DH01 DPM | data_manager | data_manager |
| test.depi.dh01 | DH01 DEPI | collaborator_pii | data_manager |
| test.mo.dh01 | DH01 MO | coder | coder |
| test.rev.dh01 | DH01 MO | reviewer | reviewer |
| test.sn.dh01 | DH01 SN | interviewer | intake |
| test.smo.chc01 | CHC01 SMO | interview_supervisor, reviewer | reviewer |
| test.mo.chc01 | CHC01 MO | coder | coder |
| test.bpm.chc01 | CHC01 BPM | data_manager | data_manager |
| test.sn.chc01 | CHC01 SN | interviewer | intake |
| test.mo.phc01, test.mo.phc02 | PHC01 / PHC02 MO | interview_supervisor, coder | coder |
| test.cho.sc01 .. sc06 | SC01 .. SC06 CHO | interviewer | intake |
| test.anm.sc01 | SC01 ANM | none (worker only) | intake |
| test.mpw.sc04 | SC04 MPW | none (worker only) | intake |

ANM and MPW have an account and a worker row but no grant; a future
`death_reporter` role is meant to cover them.
