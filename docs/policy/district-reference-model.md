---
title: District Reference Model (Hierarchy, Cadres and Roles)
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-26
---

# District Reference Model

A worked picture of how one district is set up: the unit tree, the cadres at
each level, what each cadre may be given, and the default roles each cadre is given.
It is a **reference**, not a rule: every project defines its own levels,
cadres and grants ([Organization Model Policy](organization-model.md)). The
binding rules stay in that policy and in the
[Access Control Model](access-control-model.md).

The page that shows who holds which role where is specified in [People and
Roles Page](people-and-roles-page.md).

Status: active, accepted by the owner 2026-10-01 (`death_reporter` was decided 2026-10-06, `digitva-t6q`). The `TST001` test project
(`flask seed test-project`, bead `digitva-5mo`) is built from the default
template in code, with its village level deactivated (it has no villages).

## How rights are decided

Three layers, in order. Only the last one gives anyone access.

1. **Level x cadre grid** (per project). Says which cadres exist at a level and
   what they **may be given**: *Fill VA*, *Code VA*, *Supervise interviews*,
   *Report deaths*.
   It is a ceiling, checked when a grant is written; nobody gets a role from
   it.
2. **Grant** (per person). One role at one scope: the whole project, a site,
   or an organization unit. A unit grant covers that unit and everything
   below it, never anything above. A unit grant carries the person's cadre;
   `coder`, `interview_supervisor` and `death_reporter` grants are refused
   unless the cadre has the matching flag at that level.
3. **Union.** A person's rights are all their active grants added together.
   Roles are additive; there is no "deny" grant. To withhold a role from one
   person, do not grant it (or deactivate the grant).

After a grant is written the application reads only its role and scope. The
cadre on it is a description and is not consulted again.

## Hierarchy

```
Project
└── State / Province                        (state, optional when single-district; a State/Province has multiple Districts)
    ├── DH    District / District Hospital  (district)
    │   ├── Block / Taluka / SDH            (taluka, optional)
    │   └── CHC  Community Health Centre    (chc)
    │       └── PHC / UPHC (PHC-AAM)        (phc)
    │           └── SC-AAM / Sub-centre     (subcentre)
    │               └── Village             (village, optional)
    └── DH    District 2 ...

Mentoring institute (e.g. a medical college): not in this tree at all; a
standalone entity attached to districts, see "Mentoring institutes" below.
```

A **State / Province** unit sits at the top of the health-system hierarchy and
can contain multiple **District** units beneath it
(`State/Province > District > Block/Taluka/SDH (optional) > CHC > PHC/UPHC (PHC-AAM) > SC-AAM > Village`).
`state` is optional (`is_optional = true`) so a single-district project that
does not create a State/Province unit continues to work without one, while any
state/province or multi-district deployment places its Districts under their
State/Province unit (and grants at the State/Province unit automatically cover
every District, Block/Taluka, CHC, PHC/UPHC, Sub-centre and Village beneath it).

Level codes are `state`, `district`, `taluka`, `chc`, `phc`, `subcentre`,
`village`; only the labels reflect the AAM and urban/rural naming (`Block / Taluka / SDH`, `PHC / UPHC (PHC-AAM)`). A level may be skipped only
when it is optional (State/Province, Block/Taluka/SDH, Village). Village is optional because villages often have no code.
Where a project records villages, ASHAs sit at their village with the
`death_reporter` role, so they report from, and are scoped to, their own
village; a project without village units leaves the level empty, and an
optional level with no active units is left out of the project's generated
ODK form. Existing projects keep the village flag they were seeded with (the
template never changes an existing level); an administrator can mark it
optional.

In the generated ODK form no level filters on an optional one: each level's
choices filter on the nearest required level above it, and each unit's
`parent_code` there is its nearest required ancestor. A CHC under an SDH and a
CHC directly under the DH both appear once the district is chosen. A required
level with no units blocks the form download with one error naming every such
level. See [Organization Model Policy](organization-model.md).

The worked example district: DH01 > CHC01 > PHC01 (SC01-SC03) and PHC02
(SC04-SC06).

## Cadres and what they may be given

This is the default template in code (`DEFAULT_LEVEL_TEMPLATE`,
`DEFAULT_CADRE_TEMPLATE`, `DEFAULT_LEVEL_CADRE_TEMPLATE` in
`app/services/organization_service.py`). *Populate district defaults* on the
Organization page (`flask org seed-template`) adds whatever of it a project is
missing and never changes an existing level, cadre or grid row, so flags an
administrator set are kept. The page shows this table, with the default roles,
under *District reference model*.

| Level code | Level label | Notes |
|---|---|---|
| `state` | State / Province | Top of the health-system tree; optional when a project covers a single district without a State/Province node; holds multiple Districts |
| `district` | District / District Hospital (DH) | Attached under `state` (or root when `state` is unused) |
| `taluka` | Block / Taluka / Sub-divisional Hospital (SDH) | Optional level after District |
| `chc` | Community Health Centre (CHC) | CHC / Block facility level |
| `phc` | PHC / UPHC (PHC-AAM) | Primary Health Centre / Urban Primary Health Centre |
| `subcentre` | SC-AAM / Sub-centre | Sub-centre |
| `village` | Village | Optional |

| Level code | Cadre | Fill VA | Code VA | Supervise interviews | Report deaths |
|---|---|---|---|---|---|
| `state` | SNO State Nodal Officer | – | – | ✓ | – |
| `state` | SPM State Programme Manager | – | – | – | – |
| `state` | SEPI State Epidemiologist | – | – | – | – |
| `district` | CS Civil Surgeon | – | – | ✓ | – |
| `district` | DPM District Programme Manager | – | – | – | – |
| `district` | DEPI District Epidemiologist | – | – | – | – |
| `district` | MO Medical Officer | – | ✓ | – | – |
| `district` | SN Staff Nurse | ✓ | – | – | – |
| `chc` | SMO Senior Medical Officer | – | ✓ | ✓ | – |
| `chc` | MO Medical Officer | – | ✓ | – | – |
| `chc` | BPM Block Programme Manager | – | – | – | – |
| `chc` | SN Staff Nurse | ✓ | – | – | – |
| `phc` | MO Medical Officer | – | ✓ | ✓ | – |
| `phc` | CHO Community Health Officer | ✓ | – | – | – |
| `subcentre` | CHO Community Health Officer | ✓ | – | – | – |
| `subcentre` | MPW Multipurpose Worker | ✓ | – | – | ✓ |
| `subcentre` | ANM Auxiliary Nurse Midwife | ✓ | – | – | ✓ |
| `village` | ASHA Accredited Social Health Activist | – | – | – | ✓ |

ASHA has no *Fill VA*: ASHAs report deaths and do not interview. ANM and MPW
may fill VAs (owner, 2026-10-12, reversing the 2026-10-06 rule that they must
not interview); their default role stays `death_reporter`, and an
`interviewer` grant is added where they interview. The template applies to
projects populated after that date; an existing project's grid rows are never
rewritten, so its administrator changes *Fill VA* in the grid editor if
wanted.

## Default roles by cadre

Owner decision 2026-10-06 (`digitva-vjt`). Each grid row (level x cadre)
carries **default roles**: the roles an administrator would normally give a
person of that cadre at a unit of that level. They are stored on the grid row
(`map_org_level_cadre.default_roles`), edited in the grid editor, and carried
by the level_cadres sheet of the organization export and import
(`default_roles`, role names separated by `|`).

- **Pre-ticked, never granted.** When a person of that cadre is granted at a
  unit of that level, the admin grant form and the data manager grant form
  pre-tick the defaults; the operator may untick any of them. The project
  user import applies them only to a row that leaves `role` blank (and names a
  unit and a cadre): such a row stands for one grant per default role. A row
  that names a role gets that role only. Nothing grants a default on its own:
  the grants written are the ones submitted, ordinary per-person grants.
- **Editing a default later changes nothing already granted.** Existing
  grants are rows of their own; a default only shapes the next grant form.
- **Unit-scope roles only**, `death_reporter` included: the roles a unit grant
  may carry (see [Organization Model Policy](organization-model.md),
  "Unit-scoped grants").
- **A default can only name roles the row allows**, by the same rule the grant
  write uses: *Code VA* for `coder`, *Supervise interviews* for
  `interview_supervisor`, *Report deaths* for `death_reporter`; `interviewer`
  and the other unit roles have no flag. Saving defaults that break the rule
  is refused; clearing a flag drops the stored defaults that relied on it.
- **Seed.** A new project's grid takes the table below as its defaults
  (`DEFAULT_TYPICAL_ROLES` in `app/services/organization_service.py`). An
  existing project's grid rows are never rewritten: their defaults start empty
  until an administrator sets them.
- Blank `default_roles` in an import keeps the row's current defaults, like
  the other optional columns; clear them in the grid editor.

The table is the seed. Access still comes only from each person's grants.

### Three-tier PII boundary (owner decision 2026-10-26, `digitva-ewa5`)

- **Tier 1 — Project level (Project PI, Project Scientist/Viewer, Project Data Manager):** sits above multiple districts/sites and mentoring institutions $\implies$ **Outside the health system (Non-PII / Blinded)**.
- **Tier 2 — Mentoring institution (Site PI `site_pi`, faculty/scientist `coder`, `reviewer`, `coding_tester`, `collaborator`):** sits outside the health-system tree and attaches to districts $\implies$ **Outside the health system (Non-PII / Blinded)**.
- **Tier 3 — Health-system tree (`DH` $\to$ `SDH` $\to$ `CHC` $\to$ `PHC-AAM` $\to$ `SC-AAM` $\to$ `Village`):** every person placed inside the health system (**In-charge**, unit **Data Manager**, **Interview Supervisor**, **Interviewer**, **Death Reporter**, and in-system doctors holding **Coder** or **Reviewer**) is **inside the health system $\implies$ All PII**, whether working within their home unit subtree (**within-tree**) or assigned across sibling units (**cross-tree**). In-system unit leaders are always called **In-charge** (never `Site PI`).
- **Exceptional PII access for an external person:** if someone from outside the system genuinely requires PII access, they are made part of the health system (Tier 3) and granted `data_manager` at the District (`DH`) level.

| Tier | Where | Cadre / person | Default roles | PII Visibility | Covers |
|---|---|---|---|---|---|
| Tier 1 (Outside) | Project | Project PI | `project_pi` | **Non-PII** | whole project (above sites & mentoring institutes) |
| Tier 1 (Outside) | Project | Project scientist / viewer | `collaborator`, `coder`, `reviewer` | **Non-PII** | whole project |
| Tier 1 (Outside) | Project | Project data manager | `data_manager` (at `project` scope) | **Non-PII** | whole project |
| Tier 2 (Outside) | Mentoring institute | Institute PI / Nodal Lead | `site_pi` | **Non-PII** | districts the mentoring institute is attached to |
| Tier 2 (Outside) | Mentoring institute | Faculty, scientists, residents | `coder`, `reviewer`, `coding_tester`, `collaborator` | **Non-PII** | only the districts the institute is attached to, through unit grants at those districts |
| Tier 3 (Inside) | State / Province | SNO (or State/Province Director) | State/Province **In-charge** (`in_charge`) | **PII** | all districts and units in the state/province |
| Tier 3 (Inside) | State / Province | SPM, SEPI | `data_manager` (at `org_unit` scope) | **PII** | all districts and units in the state/province |
| Tier 3 (Inside) | DH | CS (or CMO) | District **In-charge** (`in_charge`, *stored as unit `site_pi` prior to enum split*) | **PII** | whole district, with every data manager power in it plus field supervision and unit reporting |
| Tier 3 (Inside) | DH | DPM, DEPI | `data_manager` (at `org_unit` scope) | **PII** | whole district: supervising the worklist, data & epidemiology (also used when an external person exceptionally needs PII at district level) |
| Tier 3 (Inside) | DH | MO | `coder`, or `reviewer` | **PII** (in-system doctor, within-tree or cross-tree) | whole district |
| Tier 3 (Inside) | DH | SN | `interviewer` | **PII** | facility deaths at the DH |
| Tier 3 (Inside) | CHC | SMO | Block **In-charge**, `reviewer` | **PII** | the block |
| Tier 3 (Inside) | CHC | MO | `coder` | **PII** (in-system doctor, within-tree or cross-tree) | the block |
| Tier 3 (Inside) | CHC | BPM | `data_manager` (at `org_unit` scope) | **PII** | the block |
| Tier 3 (Inside) | CHC | SN | `interviewer` | **PII** | facility deaths at the CHC |
| Tier 3 (Inside) | PHC-AAM | MO | PHC **In-charge**, `coder` | **PII** (within-tree & cross-tree) | its SC-AAMs (and any cross-tree PHCs assigned) |
| Tier 3 (Inside) | SC-AAM | CHO | `interviewer` | **PII** | own SC-AAM: register deaths and interview |
| Tier 3 (Inside) | SC-AAM | ANM, MPW | `death_reporter` | **PII** | own SC-AAM: register deaths and correct their details until an interview is completed; interview only with an added `interviewer` grant |
| Tier 3 (Inside) | Village | ASHA | `death_reporter` | **PII** | own village: as the ANM and MPW |

## Who manages accounts and grants

| Who | Create accounts | Give roles | Limits |
|---|---|---|---|
| Admin | ✓ | every role, every scope | none |
| Project PI | existing users only | every role except `admin` and `project_pi`, unit grants included; `data_manager` at any level | own project only |
| In-charge (district, block, PHC) | ✓ | `data_manager` on their own unit and below; the data manager's roles anywhere in their area | their own unit and units beneath it |
| Data manager | ✓ | `interviewer`, `death_reporter`, `coder`, `reviewer`, `coding_tester`, `collaborator` at any level of their subtree, own level included; `data_manager` only strictly below their own level | own subtree only; never In-charge, `interview_supervisor`, `site_pi`, `project_pi` or `admin` |
| Everyone else | – | – | – |

Decision 2026-10-02 (see [Access Control Model](access-control-model.md),
"Who creates which grants", district projects), implemented in digitva-0wc
stage 6: a block data manager gives interviewer grants for CHOs at SC-AAMs
from the data-manager users page. Cadre validation and the mentor guard apply
to every grant.

## Mentoring institutes

A medical college (or similar) that gives technical support sits **outside the
health-service tree (Tier 2 — Non-PII)** and is not a unit. It is a standalone,
cross-project entity (the mentoring institute) that an administrator attaches
to district units, and whose lead (`site_pi`) and scientists (`coder`,
`reviewer`, `coding_tester`, `collaborator`) receive unit grants at or below
those districts without PII visibility. If an external person exceptionally
requires PII access, they are placed inside the health system (Tier 3) and
granted `data_manager` at the District level. See
[Organization Model Policy](organization-model.md), "Mentoring institutes",
for the entity, the guard and who manages it. Mentor staff are not counted in
the district's staff headcount; they are listed separately as the district's
mentoring institute.
