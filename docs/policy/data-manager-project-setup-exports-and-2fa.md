---
title: Data Manager Project Setup, Exports, Second Factor and Consent Placeholders
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-11-27
---

# Data Manager Project Setup, Exports and Mandatory Second Factor

## Purpose

Owner decisions of 2026-11-27 (Vivek Gupta) on three linked matters:

1. which parts of a project's setup a data manager may change;
2. which exports a data manager may download;
3. which roles must hold a second factor.

This is a baseline written before implementation. Beads: `digitva-vg9c`
(setup and exports), `digitva-8wct` (second factor). Nothing here is built.
Where it differs from another policy it supersedes that text once the work
lands; the documents to update then are listed under "Documents to update".

## 1. Data manager access to Project Setup

Today the Project Setup page (`/admin/panels/project-setup/<project_id>`) and
every panel it hosts are admin-only (`digitva-r1p`, owner note 2026-10-06).
In an organizational (unit-tree) project a data manager gets a limited view of
it, reached from the Admin Console, Projects, that project.

The data manager's page is a separate, read-mostly screen with its own
endpoints. It does not reuse the admin shell, which carries every panel's
write API. Each write is authorized per endpoint through `authz`, never by the
page being reachable.

### What a data manager may change

| Area | Rule |
| --- | --- |
| Coding gates | Per site and per unit: on or off, window, daily coder limit. Only inside the data manager's subtree. |
| Unit tree | Add and edit units inside the data manager's subtree. Project-scope data managers only. |
| Workers and scope | Project-scope data managers only. A unit-level data manager has no worker editing. |
| People and grants | Through `authz.can_grant`, unchanged: no privilege escalation. |

Privilege escalation stays closed by the existing rules, not by new ones. A
data manager grants only inside their own subtree, other data managers only
strictly below their own level, and never In-charge, `site_pi`, `project_pi`
or `admin`. They cannot revoke their own grant, and cadre validation and the
mentoring-institute guard apply to every grant they write.

### What stays admin-only

Every other setting, including:

- Basics: name, nickname, project id and code, structure, welcome note, target
  completion, timezone, retention, recode window, country, demo or training,
  KPI inclusion, questionnaire type, enabled extensions, languages, interviewer
  guidance;
- the web intake switch, master project status, narrative QA and live ODK
  attachment fetch;
- coding intake mode, ICD classification, COD entry, masked COD workflow, coder
  social autopsy, reviewer social autopsy, self-coding;
- registration identifier types, respondent consent, project forms, ODK
  connections;
- levels, cadres, cadre permissions, mentoring and scientists, ODK form fields;
- VA presets (`Id10002`, `Id10003`).

VA presets stay with the project PI and admin, as today (owner 2026-11-27);
data managers do not edit them.

## 2. Data manager exports

A data manager is a person who builds reports and presentations. They need
operational status and coding results, not the raw record.

### Allowed

| Export | Scope | Notes |
| --- | --- | --- |
| Case key details (new) | Data manager's scope | Columns below. |
| Organization export | Data manager's scope | Units, levels, cadres, workers. |
| Worker lists | Data manager's scope | Names and phones are personal data. |

### Not allowed

SmartVA input, SmartVA results, SmartVA likelihoods, the submissions CSV with
payload, the coded COD snapshot, the COD buckets export, and the XLSForm
download. The XLSForm download and organization import stay with the project
PI and admin.

### Case key details

One row per death, no payload.

| Group | Columns |
| --- | --- |
| Identity | Submission ID (`va_sid` or the masked ID, never the payload `unique_id`), project, site, unit |
| Demographics | Age, sex, date of death, date of birth |
| Interview | Date of interview, interview status, interviewed by, village |
| Coding | Coding status and date, coded by, coder ICD code and label |
| Review | Reviewing status and date, reviewed by, reviewer final ICD |
| Result | Final ICD code and label, VA code (the WHO 2022 VA COD bucket code), VA code label |

Personal data is shown by tier:

| Column | Org-tree data manager (`org_unit` scope, PII) | Project or site data manager (Non-PII) |
| --- | --- | --- |
| Interviewed by, coded by, reviewed by | Names | Empty column |
| Village | Shown | Empty column |
| Date of birth | Shown | Empty column |
| All other columns | Shown | Shown |

Rules that apply to the export:

- A redacted column is emptied, never dropped, so the file keeps its shape.
- A mentor data manager without a cadre is Non-PII.
- Age, sex and date of death are never sealed fields and are plain for every
  data manager.
- Rows are limited to the data manager's scope: the whole project for a
  project-scope grant, the subtree for a unit grant.

### Logging and limits

Every download of every export above is audited before the first byte: who,
scope, filters, row count and time. One running export per user at a time and a
row cap apply to each, as for the cases export.

### Organization export and worker lists

`organization-model.md` restricts the organization export and import to admins
and project PIs of that project. This baseline lets data managers export, not
import, within their scope. The logging rule above applies.

## 3. Mandatory second factor

Reverses, for named roles, the 2026-10-11 policy in
`authentication-factors.md` (password or passkey for every role, no TOTP, no
mandatory factor).

- Mandatory second factor, passkey or TOTP, for: `admin` (sysadmin),
  `project_pi`, `site_pi`, In-charge, and every `data_manager` at any scope
  (org-tree, project and site).
- Any other role (coder, reviewer, interviewer, collaborator and the rest)
  keeps password or passkey, with a passkey optional.
- Existing encrypted TOTP secrets and recovery-code records are reusable
  (`app/services/totp_service.py`, `digitva-sn1.2`).

### Existing holders: 14-day grace

A holder of a covered role with no second factor is prompted at every sign-in
for 14 days from the day the rule is switched on, then blocked until a factor
is enrolled. A grant created after that day requires the factor from the first
sign-in. The grace window and the block are audited.

### Lost device

Another admin removes the user's factor and the user enrols again. There are
no recovery codes. A sole admin recovers through a command-line reset on the
server, which is audited. Every reset is logged with who did it and for whom.

### Mixed roles

A user who holds both a covered and an uncovered role (for example a coder who
is also a data manager) is covered (owner 2026-11-27).

### Open questions

None.

## 4. Editable, saved consent placeholders per project

Owner 2026-11-27. The respondent consent notice
(`respondent-consent-notice-draft.md`) carries bracketed placeholders. Today
several are filled from server-wide `PUBLIC_*` settings
(`app/services/consent_service.py`), so every project on a server shares one
organisation name, grievance officer and contact email. Each placeholder
becomes a value the project stores and edits itself, in the "Respondent
consent" section of Project Setup (`mas_project_consent_settings`).

| Placeholder | Stored per project as | Fallback when empty |
| --- | --- | --- |
| `[ORGANISATION]` | organisation (data fiduciary) name | `PUBLIC_ORG_NAME`, then the DIGITVA Team |
| `[PROJECT AREA]` | project area | none: left for the project to edit |
| `[DELETION AND EXCLUSION EMAIL]`, phone | `contacts.deletion` | `PUBLIC_CONTACT_EMAIL` |
| `[EMAIL, PHONE]` (central team) | `contacts.central_team` | `PUBLIC_CONTACT_EMAIL` |
| `[DATA PROTECTION OFFICER]` | `contacts.dpo` (name, email, phone) | `PUBLIC_GRIEVANCE_OFFICER`, then the DIGITVA Team |
| `[INSTITUTION NAME, EMAIL, PHONE]` | `contacts.mentor_institution` | the existing central-team sentence |
| `[DISTRICT NAME]`, `[DISTRICT CONTACT NAME, EMAIL, PHONE]` | per district unit | the health-worker sentence |
| `[RETENTION PERIOD AND WHAT HAPPENS AFTER]` | the retention and expiry settings | one year, then erase |
| `[PROJECT NAME]` | the project's name, not edited here | n/a |

Rules:

- Each value is editable and saved with an audit entry (who, when, old and new
  value). Values may be given in English and Hindi where the wording differs.
- Saving a value changes the printed notice, so it creates a new notice
  version, as contact changes already do. A saved consent record keeps the text
  and hash the respondent heard; an edit never rewrites it.
- The fill order is the project's value, then the `PUBLIC_*` setting, then the
  default, so existing projects and deployments behave as before until a
  project saves a value.
- Editing these is admin-only, like the rest of the consent section. Data
  managers do not edit them.
- The project's DPO must reach the respondent as printed. Check that the fill
  reads `contacts.dpo`; the function read on 2026-11-27 uses only
  `PUBLIC_GRIEVANCE_OFFICER`.

## Documents to update when implemented

- `docs/policy/authentication-factors.md`: the mandatory-factor roles.
- `docs/policy/access-control-model.md`: `data_manager` role section, Project
  Setup access, export rights.
- `docs/policy/organization-model.md`: organization export and worker lists
  line, `interview_supervisor` in the data manager grant list (currently out of
  step with `access-control-model.md`).
- `docs/policy/web-intake.md`: "Area VA presets" permission line, if the
  project PI loses them.
- `docs/policy/respondent-consent-notice-draft.md`: "Contact variables" and the
  placeholder fill order.
- `docs/current-state/`: authentication, workflow and permissions, and the
  admin panels, as each part lands.
