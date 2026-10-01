---
title: District Reference Model (Hierarchy, Cadres and Roles)
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-01
---

# District Reference Model

A worked picture of how one district is set up: the unit tree, the cadres at
each level, what each cadre may be given, and the roles people typically hold.
It is a **reference**, not a rule: every project defines its own levels,
cadres and grants ([Organization Model Policy](organization-model.md)). The
binding rules stay in that policy and in the
[Access Control Model](access-control-model.md).

Status: active, accepted by the owner 2026-10-01 (parts marked proposed below, such as `death_reporter`, remain proposals). The `TST001` test project
(`flask seed test-project`, bead `digitva-5mo`) is built from the default
template in code, with its village level deactivated (it has no villages).

## How rights are decided

Three layers, in order. Only the last one gives anyone access.

1. **Level x cadre grid** (per project). Says which cadres exist at a level and
   what they **may be given**: *Fill VA*, *Code VA*, *Supervise interviews*.
   It is a ceiling, checked when a grant is written; nobody gets a role from
   it.
2. **Grant** (per person). One role at one scope: the whole project, a site,
   or an organization unit. A unit grant covers that unit and everything
   below it, never anything above. A unit grant carries the person's cadre;
   `coder` and `interview_supervisor` grants are refused unless the cadre has
   the matching flag at that level.
3. **Union.** A person's rights are all their active grants added together.
   Roles are additive; there is no "deny" grant. To withhold a role from one
   person, do not grant it (or deactivate the grant).

After a grant is written the application reads only its role and scope. The
cadre on it is a description and is not consulted again.

## Hierarchy

```
Project
├── DH    District Hospital               (district, depth 1)
│   ├── SDH  Sub-divisional Hospital      (taluka, depth 2, optional)
│   └── CHC  Community Health Centre      (chc, depth 3)
│       └── PHC-AAM                       (phc, depth 4)
│           └── SC-AAM                    (subcentre, depth 5)
│               └── Village               (village, depth 6)

Mentoring institute (e.g. a medical college): not in this tree at all; a
standalone entity attached to districts, see "Mentoring institutes" below.
```

Level codes are the default template's (`district`, `taluka`, `chc`, `phc`,
`subcentre`, `village`), so existing projects keep working; only the labels
reflect the AAM naming. A level may be skipped only when it is optional
(SDH).

The worked example district: DH01 > CHC01 > PHC01 (SC01-SC03) and PHC02
(SC04-SC06).

## Cadres and what they may be given

This is the default template in code (`DEFAULT_LEVEL_TEMPLATE`,
`DEFAULT_CADRE_TEMPLATE`, `DEFAULT_LEVEL_CADRE_TEMPLATE` in
`app/services/organization_service.py`). *Populate district defaults* on the
Organization page (`flask org seed-template`) adds whatever of it a project is
missing and never changes an existing level, cadre or grid row, so flags an
administrator set are kept. The page shows this table, with the typical roles,
under *District reference model*.

| Level code | Level label | Depth |
|---|---|---|
| `district` | District / District Hospital (DH) | 1 |
| `taluka` | Sub-divisional Hospital (SDH) | 2, optional |
| `chc` | Community Health Centre (CHC) | 3 |
| `phc` | PHC-AAM | 4 |
| `subcentre` | SC-AAM / Sub-centre | 5 |
| `village` | Village | 6 |

| Level code | Cadre | Fill VA | Code VA | Supervise interviews |
|---|---|---|---|---|
| `district` | CS Civil Surgeon | – | – | ✓ |
| `district` | DPM District Programme Manager | – | – | – |
| `district` | DEPI District Epidemiologist | – | – | – |
| `district` | MO Medical Officer | – | ✓ | – |
| `district` | SN Staff Nurse | ✓ | – | – |
| `chc` | SMO Senior Medical Officer | – | ✓ | ✓ |
| `chc` | MO Medical Officer | – | ✓ | – |
| `chc` | BPM Block Programme Manager | – | – | – |
| `chc` | SN Staff Nurse | ✓ | – | – |
| `phc` | MO Medical Officer | – | ✓ | ✓ |
| `phc` | CHO Community Health Officer | ✓ | – | – |
| `subcentre` | CHO Community Health Officer | ✓ | – | – |
| `subcentre` | MPW Multipurpose Worker | ✓ | – | – |
| `subcentre` | ANM Auxiliary Nurse Midwife | ✓ | – | – |
| `village` | ASHA Accredited Social Health Activist | ✓ | – | – |

## Typical roles by cadre

Advisory. These are the grants an administrator would normally give; each
person's grants are still chosen one by one. In code: `DEFAULT_TYPICAL_ROLES`
(display only, never read for authorization).

| Where | Cadre / person | Typical roles | Covers |
|---|---|---|---|
| Project | Project PI | `project_pi` | whole project |
| Project | Project data manager | `data_manager` | whole project |
| DH | CS | `interview_supervisor` | whole district. No `site_pi` at a unit: in an organizational project the site PI duty is the project PI's, who covers every district |
| DH | DPM | `data_manager` | whole district: supervising the worklist, data (registering deaths is interviewer-only) |
| DH | DEPI | `collaborator_pii` | read-only with personal details |
| DH | MO | `coder`, or `reviewer` | whole district |
| DH | SN | `interviewer` | facility deaths at the DH |
| CHC | SMO | `interview_supervisor`, `reviewer` | the block |
| CHC | MO | `coder` | the block |
| CHC | BPM | `data_manager` | the block |
| CHC | SN | `interviewer` | facility deaths at the CHC |
| PHC-AAM | MO | `interview_supervisor`, `coder` | its SC-AAMs |
| SC-AAM | CHO | `interviewer` | own SC-AAM: register deaths and interview |
| SC-AAM | ANM, MPW | none yet; `death_reporter` proposed | report deaths only |
| Village | ASHA | none yet; `death_reporter` proposed | report deaths only |
| Mentoring institute | Faculty, residents | `coder`, `reviewer`, `coding_tester`, `collaborator_pii` | only the districts the institute is attached to, through ordinary unit grants at those districts |

## Who manages accounts and grants

| Who | Create accounts | Give roles | Limits |
|---|---|---|---|
| Admin | ✓ | every role, every scope | none |
| Project PI | existing users only | every role except `admin` and `project_pi`, unit grants included | own project only |
| Data manager | ✓ | `coder`, `coding_tester`, `data_manager` | project or site scope only; refuses unit grants |
| Everyone else | – | – | – |

So interviewer grants for CHOs at SC-AAMs are given by an admin or the
project PI, not by a district or block data manager.

## Mentoring institutes

A medical college (or similar) that gives technical support sits outside the
service tree and is not a unit. It is a standalone, cross-project entity (the
mentoring institute) that an administrator attaches to district units, and
whose staff receive **ordinary unit grants** at or below those districts. See
[Organization Model Policy](organization-model.md), "Mentoring institutes",
for the entity, the guard and who manages it. Mentor staff are not counted in
the district's staff headcount; they are listed separately as the district's
mentoring institute.

## Proposed, not built

- **`death_reporter` role** (`digitva-t6q`): ANM, MPW and ASHA register deaths
  but never start an interview. A unit-scope role gated by a new *Report
  deaths* grid flag, like `interview_supervisor`.
- **Default roles per cadre** (`digitva-vjt`): the "Typical roles" column
  stored on the grid and pre-ticked when a person is added at a unit; saved
  as ordinary grants.
