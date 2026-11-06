---
title: How-Do-I Corpus - Administration
doc_type: help-corpus
status: draft
owner: engineering
last_updated: 2026-11-06
---

# How-Do-I Corpus - Administration

Entries for administrators (`admin`), with notes where a project PI
(`project_pi`) can do the same task for their own project. Spec:
`docs/policy/help-chatbot.md`, "How-Do-I corpus". Labels were copied from the
admin panel templates and scripts named in each `sources` line, checked against
the working tree on 2026-11-06. All admin changes are browser actions that need
the signed-in session; none of the steps below needs a password to be typed in
by anyone other than the person who owns the account.

## The admin console and project setup

### How do I open the admin console?

- id: hdi-admin-001
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Open **Projects** in the top bar, or **Manage** then **Admin**.
  2. Pick a panel in the left sidebar under **Manage**.
- notes: Administrators open on the Projects panel. A project PI opens on the Organization panel and sees only the panels for their own project. The sidebar lists Projects, Organization, Access Grants, Project Sites, Training sessions, Mentoring institutes, Project Forms, Project PIs, Sites, Users, Languages, ODK Connections, Field Mapping, COD Buckets, ICD-10 Browser, ICD-11 Browser, ICD Search Vocabulary, VA Definitions, Instrument Translations, UI Strings, Data Sync, Attachments, Activity and System health. Some are admin-only and are hidden from a project PI.
- sources: `app/templates/admin/admin_index.html`; `app/templates/va_intermediate_partials/va_navbar.html`; help page `admin-overview` (its panel list is out of date)
- checked: 2026-11-06

### How do I open the Project Setup page for one project?

- id: hdi-admin-002
- roles: admin
- surfaces: web
- steps:
  1. Open **Projects** in the top bar.
  2. Click the project's ID or name, or its **Project Setup** button in the list.
  3. Use the left menu: under **Live Operations** pick **Overview & Gates**, **People & Grants** or **Sync & activity**; under **One-Time Setup Wizard** pick **1 Basics**, **2 Structure & Cadres**, **3 Data collection** or **4 Coding**.
  4. Use the **Project** list at the top to switch to another project.
- notes: Project Setup is for administrators; a project PI uses the Organization, Access Grants and Project Sites panels. Each section holds the same panels as the sidebar, locked to this project. A saved change shows "Project saved."
- sources: `app/templates/admin/panels/project_setup.html`; help page `projects`
- checked: 2026-11-06

### How do I create a project?

- id: hdi-admin-003
- roles: admin
- surfaces: web
- steps:
  1. Open the **Projects** panel and press **New Project**.
  2. Fill **Project ID**, **Code**, **Name** and **Nickname**; set **Status**.
  3. Choose **Structure**: **Sites (legacy)** or **Organization**.
  4. Choose **Coding Intake Mode**, **ICD Classification** and the other settings described in the entries below.
  5. Press **Save**.
- notes: The project ID is made upper case and cannot repeat an existing one. A new project is a shell: it needs sites or organization units, an ODK connection and form mapping (or web intake), and access grants before anything can be coded. Setting the structure back from Organization to Sites is refused while a live tree exists.
- sources: `app/templates/admin/panels/projects.html`; `app/routes/admin.py` (`POST /api/projects`)
- checked: 2026-11-06

### How do I deactivate or reactivate a project?

- id: hdi-admin-004
- roles: admin
- surfaces: web
- steps:
  1. In the **Projects** panel use the toggle on the project row (tick **Show inactive** to find inactive ones), or open Project Setup, **Overview & Gates**.
  2. Under **Master Project Status** choose **Active (Open for authorized users)** or **Inactive (Closed — suspends all non-admin grants)**.
  3. In Overview & Gates press **Save Switches**; in the Projects panel press **Deactivate** (or **Activate**) in the dialog.
- notes: Deactivating hides the project from sync and coding queues and suspends non-admin grants for it. Data is not deleted.
- sources: `app/templates/admin/panels/projects.html`; `app/templates/admin/panels/project_setup.html`; `app/routes/admin.py` (`admin_toggle_project`)
- checked: 2026-11-06

### How do I choose between masked and unmasked coding for a project?

- id: hdi-admin-005
- roles: admin
- surfaces: web
- steps:
  1. Open the project in the **Projects** panel (Project Setup, **1 Basics**).
  2. Switch **Require masked COD workflow** on for masked coding or off for unmasked.
  3. Press **Save**.
- notes: With masked coding SmartVA is hidden from the coder until Step 2, so Step 1 is the coder's independent assessment. The setting cannot change while the project has active coding allocations or cases at coder Step 1 saved (the save is refused with a 409 message). Switch it before coding starts. On ICD-11 projects masked coding makes Step 1 the DORIS certificate.
- sources: `app/templates/admin/panels/projects.html`; `app/routes/admin.py` (`_project_has_in_progress_coding`); help page `coding-workflow`
- checked: 2026-11-06

### Why can't I change the coding mode or ICD classification of a project?

- id: hdi-admin-006
- roles: admin
- surfaces: web
- steps:
  1. Read the message: "COD settings cannot change while this project has active coding allocations or cases with coder Step 1 saved."
  2. Wait until active allocations end or the Step 1 cases are finalized, then change the setting. Reducing the open work is the only route; the check does not have an override.
- notes: The three settings that are locked together are **Require masked COD workflow**, **ICD Classification** and the derived COD entry.
- sources: `app/routes/admin.py` (`admin_update_project`, `_project_has_in_progress_coding`)
- checked: 2026-11-06

### How do I set a project to ICD-10 or ICD-11?

- id: hdi-admin-007
- roles: admin
- surfaces: web
- steps:
  1. In the project's **1 Basics** form open **ICD Classification**.
  2. Choose **ICD-10** or **ICD-11**.
  3. Press **Save**.
- notes: The **COD Entry** field is read-only and follows the choice: ICD-11 projects always use DORIS entry; ICD-10 projects always use simple entry. The choice applies to new coding only. A code from the other catalogue is rejected on save.
- sources: `app/templates/admin/panels/projects.html`; `app/routes/admin.py` (`_derive_cod_entry_mode`, `_validate_cod_project_mode`); help page `icd-codes`
- checked: 2026-11-06

### How do I change the recode window for a project?

- id: hdi-admin-008
- roles: admin
- surfaces: web
- steps:
  1. Open the project's **1 Basics** form.
  2. Set **Recode window (min)** to a whole number from 1 to 10080 (1440 is 24 hours, the default).
  3. Press **Save**.
- notes: This is how long a coder may reopen and replace their final cause; afterwards the case becomes reviewer-eligible. The help page "Recode Window" still describes a fixed 24 hours; the project setting is what applies.
- sources: `app/templates/admin/panels/projects.html`; `app/routes/admin.py` (`_parse_recode_window_minutes`); `app/services/recode_window.py`
- checked: 2026-11-06

### How do I choose how coders receive cases (random or pick and choose)?

- id: hdi-admin-009
- roles: admin
- surfaces: web
- steps:
  1. Open the project's **1 Basics** form.
  2. Set **Coding Intake Mode** to **Random form allocation** or **Pick and choose**.
  3. Press **Save**.
- notes: Random allocation gives the coder the next eligible case; pick and choose lets the coder browse a list. The Organization tab's **Coding scope** setting needs pick and choose.
- sources: `app/templates/admin/panels/projects.html`; help page `projects`
- checked: 2026-11-06

### How do I turn Narrative QA and Social Autopsy on or off?

- id: hdi-admin-010
- roles: admin
- surfaces: web
- steps:
  1. For Narrative QA open Project Setup, **Overview & Gates** and use **Narrative QA (AI Assist)**, then **Save Switches**.
  2. For Social Autopsy use the **Coder Social Autopsy** and **Reviewer Social Autopsy** switches in **1 Basics**, then **Save**.
- notes: When off, the step is not shown to coders (or reviewers) of that project. The Projects list also has a quick toggle for Narrative QA.
- sources: `app/templates/admin/panels/project_setup.html`; `app/templates/admin/panels/projects.html`
- checked: 2026-11-06

### How do I mark a project as a demo or training project?

- id: hdi-admin-011
- roles: admin
- surfaces: web
- steps:
  1. Open the project's **1 Basics** form.
  2. Switch **Demo / Training** on.
  3. Set **Retention (min)**, how long demo coding results are kept.
  4. Press **Save**.
- notes: Demo projects are open to signed-in users without a coder grant, their coding results expire after the retention time and do not count in output metrics. A demo or training project can never be included in the homepage KPIs.
- sources: `app/templates/admin/panels/projects.html`; help page `projects`
- checked: 2026-11-06

### How do I include a project in the homepage KPIs?

- id: hdi-admin-012
- roles: admin
- surfaces: web
- steps:
  1. Open the project's **1 Basics** form.
  2. Switch on **Included in homepage KPIs (not for training or demo projects)**.
  3. Press **Save**.
- notes: The public home page shows only aggregate counts (interviews, coders, languages, age and sex), never causes of death, and only for projects with this switch on. It is off by default. Counts come from hourly reporting views and may lag.
- sources: `app/templates/admin/panels/projects.html`; `docs/policy/public-home-stats.md`
- checked: 2026-11-06

### Why can't I switch on homepage KPIs for this project?

- id: hdi-admin-013
- roles: admin
- surfaces: web
- steps:
  1. Read the message: "A training or demo project cannot be included in the home page KPIs."
  2. Check whether **Demo / Training** is on for the project, or whether it is the configured training project.
  3. Switch **Demo / Training** off first if it is a real study project, then switch on **Included in homepage KPIs** and save.
- notes: The training project and any synthetic demo project are always excluded, and the server also filters them out when computing the public numbers.
- sources: `app/routes/admin.py` (`admin_update_project`); `docs/policy/public-home-stats.md`
- checked: 2026-11-06

### How do I let coders also interview (self-coding)?

- id: hdi-admin-014
- roles: admin
- surfaces: web
- steps:
  1. Switch **Web Intake** to a mode other than Off in **1 Basics**.
  2. Switch on **Self-coding (coders also interview; needs web intake on)**.
  3. Press **Save**.
- notes: Self-coding needs web intake on; the save is refused otherwise.
- sources: `app/templates/admin/panels/projects.html`; `app/routes/admin.py` (self_coding_enabled check)
- checked: 2026-11-06

### How do I set the SmartVA country for a project?

- id: hdi-admin-015
- roles: admin
- surfaces: web
- steps:
  1. In **1 Basics** open **Country**.
  2. Pick the country (or Unknown) and press **Save**.
- notes: The country is stamped on each new submission. Changing it does not change cases already received.
- sources: `app/templates/admin/panels/projects.html` (Country tooltip)
- checked: 2026-11-06

### How do I switch on web and mobile data capture for a project?

- id: hdi-admin-016
- roles: admin
- surfaces: web
- steps:
  1. In **1 Basics**, under **DigitVA data capture (browser VA form and Collect app)**, open **Web Intake**.
  2. Pick **Off (ODK only; no Collect app)**, **Direct questionnaire entry**, **Death register first** or **Both routes**.
  3. Press **Save**. In Overview & Gates the same choice is **Web & Mobile App Capture**.
- notes: With Web Intake off the project collects through ODK only and interviewers cannot sign in to the Collect app to collect. Check readiness (next entry) before announcing it.
- sources: `app/templates/admin/panels/projects.html`; `app/templates/admin/panels/project_setup.html`
- checked: 2026-11-06

### How do I check that a project is ready for web capture?

- id: hdi-admin-017
- roles: admin
- surfaces: web
- steps:
  1. Open the project's **1 Basics** form (an existing project).
  2. Read the **Web data capture readiness** list and its summary badge. The same list is in **Overview & Gates**.
  3. Fix each item shown, using the "Go to" link where one is offered.
- notes: Checks cover the capture mode, active sites, the web form per site, the questionnaire, the organization tree, geography fields, interviewers, the coding scope and languages. A warning does not stop interviews; a failed check means nobody can complete the web route yet.
- sources: `app/templates/admin/panels/projects.html`; `app/routes/admin.py` (`web-intake-readiness`); `docs/policy/web-intake.md` ("Ready for web capture")
- checked: 2026-11-06

### How do I choose the questionnaire layers for a project?

- id: hdi-admin-018
- roles: admin
- surfaces: web
- steps:
  1. In **1 Basics**, under **Web form questionnaire**, pick the **Questionnaire** (form type).
  2. Tick the layers wanted: **Death summary upload: offer document upload**, **Medical records: offer medical-record fields**, **Equity: ask residence type, social group, vulnerable groups, health coverage and the refusal profile**.
  3. Optionally write a **Welcome note**, or press **Use default note**.
  4. Press **Save**.
- notes: A form type whose personal-data set is not confirmed cannot collect real interviews. The welcome note is shown before the questionnaire starts. These options apply to the browser form and Collect app; ODK Central forms carry their own content.
- sources: `app/templates/admin/panels/projects.html`; `docs/policy/va-form-project-configuration.md`; `docs/policy/new-form-type-onboarding.md`
- checked: 2026-11-06

### How do I choose the languages of the web form?

- id: hdi-admin-019
- roles: admin
- surfaces: web
- steps:
  1. In **1 Basics** open **Web form languages**.
  2. Under **Language choice** either tick **Offer every questionnaire language** or tick the **Available languages**.
  3. Under **Narration languages** tick the languages the narrative may be recorded in; leave all unticked to hide that question.
  4. Optionally switch **Show interviewer guidance**. Press **Save**.
- notes: English is always available. Display languages are limited to those with a translation (see Instrument Translations). Narration languages come from the Languages panel. If the language list cannot load, the form leaves the stored settings untouched.
- sources: `app/templates/admin/panels/projects.html`; `docs/policy/va-web-form-options.md`
- checked: 2026-11-06

### How do I show or hide live attachment fetching from ODK Central?

- id: hdi-admin-020
- roles: admin
- surfaces: web
- steps:
  1. Open the project's Project Setup, **Overview & Gates**.
  2. Use **Live ODK Attachment Fetch** and press **Save Switches**.
  3. For the self-heal setting see the Attachments panel under **Central self-heal (per project)**.
- notes: With the switch off, an attachment missing from DigitVA's own store is not fetched again from ODK Central and shows as not found.
- sources: `app/templates/admin/panels/project_setup.html`; `app/templates/admin/panels/attachments.html`; `app/routes/admin.py` (`attachment-central-fetch`)
- checked: 2026-11-06

### How do I set the respondent consent notice for a project?

- id: hdi-admin-021
- roles: admin
- surfaces: web
- steps:
  1. Open Project Setup, **3 Data collection**, section **Respondent consent**.
  2. For a first notice press **Seed from draft** (English and Hindi), then edit; press **Fill from settings** to replace placeholders.
  3. To change wording or add a language press **New language** or edit a version, then **Save as new version**.
  4. Switch **Require respondent consent** on when the web flow should show it.
  5. An administrator presses **Approve** on a version after legal review.
- notes: Editing never changes an old version; consent records keep the version shown. A version can be used while it is pending legal review. Use the same purpose codes and required flags in every language; a respondent who refuses a required purpose has refused consent.
- sources: `app/templates/admin/panels/consent_settings.html`; `docs/policy/standalone-consent-notice-settings.md`
- checked: 2026-11-06

### How do I choose which registration numbers a project collects?

- id: hdi-admin-022
- roles: admin, project_pi, data_manager
- surfaces: web
- steps:
  1. Administrators: open Project Setup, **3 Data collection**, section **Registration identifier types**. Project PIs and data managers: open **Manage** then **Registration numbers** and pick the project.
  2. Press **Add type** and fill **Code**, **Label**, **Min length**, **Max length**, **Character type**, an optional **Pattern** and an **Example**.
  3. Save. To stop collecting a type, deactivate it.
- notes: Types are never deleted; stored numbers are kept when a type is deactivated. The code cannot change once numbers exist. Use an illustrative example, never a real number.
- sources: `app/templates/admin/panels/identifier_types.html`; `docs/policy/death-registration-identifiers.md`
- checked: 2026-11-06

## Sites, project sites and coding gates

### How do I add a site?

- id: hdi-admin-023
- roles: admin
- surfaces: web
- steps:
  1. Open the **Sites** panel and press **New Site**.
  2. Fill **Site ID**, **Name** and **Abbr**.
  3. Press **Save**.
- notes: New sites are always active. Edit uses the pencil on the row. Sites are shared across projects; adding it here does not attach it to any project.
- sources: `app/templates/admin/panels/sites.html`; help page `sites`
- checked: 2026-11-06

### How do I deactivate a site?

- id: hdi-admin-024
- roles: admin
- surfaces: web
- steps:
  1. In the **Sites** panel press the toggle on the row.
  2. Read the warning in the dialog and press **Deactivate** (the button reads **Activate** for an inactive site). Tick **Show inactive** to find it again.
- notes: Deactivating does not delete data. To pause coding at a site in one project only, use the project-site coding gate instead.
- sources: `app/templates/admin/panels/sites.html`; `app/routes/admin.py` (`admin_toggle_site`)
- checked: 2026-11-06

### How do I attach a site to a project?

- id: hdi-admin-025
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Open the **Project Sites** panel (or Project Setup, **2 Structure & Cadres** on a Sites project).
  2. Choose the project and press **Add Site**.
  3. Pick the **Site** and press **Add**.
- notes: A project PI can attach sites to their own project. The site must exist first (Sites panel). Without the project-site association there is no form mapping, no sync target and no scope for grants.
- sources: `app/templates/admin/panels/project_sites.html`; help page `project-sites`
- checked: 2026-11-06

### How do I stop coding at one site for a while, or cap daily coding?

- id: hdi-admin-026
- roles: admin
- surfaces: web
- steps:
  1. Open Project Setup, **Overview & Gates**, table **Site Coding Gates**, or the **Project Sites** panel and press the **Coding settings** button on the row.
  2. Set **Coding** to Enabled or Disabled, the **Start Date** and **End Date**, and the **Daily Coder Limit** (default 100).
  3. Press **Save**.
- notes: The end date must not be before the start date; the limit must be at least 1. Coders see no cases outside the window or over the daily limit, except users with the coding tester role. On organization projects a unit can also carry its own gate; the stricter gate wins. The save is an admin action.
- sources: `app/templates/admin/panels/project_sites.html`; `app/routes/admin.py` (`coding-settings`); help page `projects`
- checked: 2026-11-06

### How do I deactivate a site inside one project?

- id: hdi-admin-027
- roles: admin, project_pi
- surfaces: web
- steps:
  1. In **Project Sites** press the toggle on the row; tick **Show inactive** to see inactive ones.
  2. Press **Deactivate** in the dialog (**Activate** for an inactive one).
- notes: Its forms drop out of sync and its cases drop out of coder allocation. Existing data and coding records are kept.
- sources: `app/templates/admin/panels/project_sites.html`; help page `project-sites`
- checked: 2026-11-06

## Users and access (relationship-based access)

### How does access work: roles, scopes and grants?

- id: hdi-admin-028
- roles: admin, project_pi, data_manager
- surfaces: web
- steps:
  1. A grant gives a person a role (what they can do) at a scope (where): a project, one project-site, or a unit of the organization tree.
  2. Roles add up and do not inherit from each other. Nothing broader is inferred; a site grant never gives access to other sites.
  3. Set grants in **Access Grants**; administrators can also use Project Setup, **People & Grants**.
- notes: Roles are admin, project PI, site PI (in-charge at a unit), data manager, coder, reviewer, coding tester, collaborator (viewer), interviewer, interview supervisor and death reporter. Whether a person sees personal data is decided per project, from the project's grants: roles inside the health system see personal data on their units; project-level and mentoring-institute roles do not. The Roles Guide link in Project Setup explains this.
- sources: `docs/policy/access-control-model.md`; help pages `user-roles`, `project-sites`
- checked: 2026-11-06

### How do I create a user?

- id: hdi-admin-029
- roles: admin
- surfaces: web
- steps:
  1. Open the **Users** panel and press **New User**.
  2. Fill **Email** and **Confirm Email**, or tick **No email address** and give **Mobile number** with **Confirm mobile number**.
  3. Fill **Name** and optionally **Job title**, **Year of birth** and **Sex**; choose **VA Languages**.
  4. Press **Save**.
- notes: You never set a password. With an email, the person verifies it and then receives a generated password by email. With only a mobile number, press **Issue sign-in code** and give the code to the person privately. The mobile number must be 10 digits.
- sources: `app/templates/admin/panels/users.html`; `app/routes/admin.py` (`POST /api/users`); `docs/policy/account-onboarding-and-passwords.md`
- checked: 2026-11-06

### How do I give a user a sign-in code (mobile sign-in)?

- id: hdi-admin-030
- roles: admin, data_manager
- surfaces: web
- steps:
  1. In the **Users** panel press the mobile-phone icon (**Issue sign-in code**) on the user's row. Data managers use **Issue sign-in code** in **Manage Users**.
  2. Give the code to the person privately.
  3. The person chooses "I have a code" on the sign-in page and then sees their password once.
- notes: The code is shown only once and expires after 72 hours. It works for any account.
- sources: `app/static/js/admin/users_panel.js`; `app/routes/admin.py` (`admin_issue_sign_in_code`); help page `dm-grants`
- checked: 2026-11-06

### How do I resend a verification email or send a password reset link?

- id: hdi-admin-031
- roles: admin
- surfaces: web
- steps:
  1. Find the user in the **Users** panel.
  2. If they show **Unverified**, press the envelope button (**Resend verification email**).
  3. If they are **Verified**, press **Email a password reset link**.
- notes: Neither shows or sets a password. Mobile-only accounts get neither button; they use a sign-in code.
- sources: `app/static/js/admin/users_panel.js`
- checked: 2026-11-06

### How do I deactivate a user?

- id: hdi-admin-032
- roles: admin
- surfaces: web
- steps:
  1. Open the **Users** panel and press the toggle on the user's row (tick **Show inactive** to see inactive users).
  2. Press **Deactivate** in the dialog (**Activate** for an inactive user).
- notes: You cannot deactivate yourself. Data created by the user is kept.
- sources: `app/templates/admin/panels/users.html`; `app/routes/admin.py` (`admin_toggle_user`)
- checked: 2026-11-06

### How do I reset a user's passkeys and sessions?

- id: hdi-admin-033
- roles: admin
- surfaces: web
- steps:
  1. In **Users** press the key button (**Reset sign-in factors**) on the row.
  2. Enter a **Reason** and press **Reset factors**.
- notes: This removes every passkey, authenticator app and recovery code, ends all of the user's sessions and emails them. It cannot be undone. You cannot do this to your own account.
- sources: `app/templates/admin/panels/users.html`; `app/static/js/admin/users_panel.js`
- checked: 2026-11-06

### How do I make someone a system administrator?

- id: hdi-admin-034
- roles: admin
- surfaces: web
- steps:
  1. Open the user with the pencil button in the **Users** panel.
  2. Switch **System Admin** on (or off).
- notes: The switch takes effect immediately and calls the server; an error is shown beside the form if it fails. Grant it sparingly: administrators see every project.
- sources: `app/templates/admin/panels/users.html`; `app/static/js/admin/users_panel.js`
- checked: 2026-11-06

### How do I grant a role to a user?

- id: hdi-admin-035
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Open **Access Grants** (or Project Setup, **People & Grants**) and press **Grant Access**.
  2. Search the **User** by email or name.
  3. Pick the **Role**: **Coder**, **Coding Tester**, **Reviewer**, **Data Manager**, **Interviewer**, **In-charge (unit) / Site PI (site)**, **Viewer (Non-PII)**, **Interview Supervisor (unit only)**, **Death Reporter (unit only)** or **Project PI**.
  4. Pick the **Scope**: **Site-level**, **Project-level** or **Unit-level (organization tree)**, then the **Site** or **Unit**.
  5. For a unit grant pick the **Cadre**; the cadre's default roles are pre-ticked, untick any you do not want.
  6. Add **Notes** if useful and press **Create Grant**.
- notes: A project PI can create grants only inside their own project and never admin or project PI grants. Granting a role again on the same scope reactivates it. A coder at a unit needs a cadre allowed to code at that level.
- sources: `app/templates/admin/panels/access_grants.html`; `app/services/authz/actions.py` (PI_NEVER_ASSIGNS); `app/routes/admin.py` (`POST /api/access-grants`)
- checked: 2026-11-06

### How do I revoke a grant?

- id: hdi-admin-036
- roles: admin, project_pi
- surfaces: web
- steps:
  1. In **Access Grants** find the grant (use the search box or the role list).
  2. Press the small close mark (**Revoke**) on the grant's role badge in the row.
  3. Press **Revoke** in the dialog "Are you sure you want to revoke this grant?".
- notes: This switches the grant off; it does not delete the user or their earlier work. For many people at once use the bulk bar in Project Setup, **People & Grants**.
- sources: `app/templates/admin/panels/access_grants.html`; `app/routes/admin.py` (`toggle`)
- checked: 2026-11-06

### How do I give or revoke grants for many users at once?

- id: hdi-admin-037
- roles: admin
- surfaces: web
- steps:
  1. Open Project Setup, **People & Grants**.
  2. Select users in the table (one row per user, or the user by unit matrix on organization projects).
  3. In the bar choose **1. Role or Action** (for example **+ Grant: Coder**, **− Revoke Coding Roles at Target Scope**, **− Revoke ALL Grants in Project**).
  4. Choose **2. Target Unit Scope** (each user's own home unit, all other units at the user's level, all units at the user's level, specific units, or project-wide).
  5. Press **Apply to Selected**.
- notes: Project Setup is for administrators. The bar also has account activation and deactivation actions and **+ Grant: Project PI**. Interview supervisor, death reporter and "Apply Each User's Cadre Default Roles" appear on organization projects only.
- sources: `app/templates/admin/panels/project_setup.html`
- checked: 2026-11-06

### How do I assign a Project PI?

- id: hdi-admin-038
- roles: admin
- surfaces: web
- steps:
  1. Open the **Project PIs** panel.
  2. Press **Assign Project PI**, choose the **User** and **Project**, press **Assign**.
- notes: Removing a project PI uses the toggle and shows "User will no longer have access to manage this project." On a project with an organization tree, project-level roles are outside the health system and do not see personal data; on a Sites project the project PI does.
- sources: `app/templates/admin/panels/project_pi.html`; `docs/policy/access-control-model.md`
- checked: 2026-11-06

### What is the Coding Tester role and when do I use it?

- id: hdi-admin-039
- roles: admin, project_pi, data_manager
- surfaces: web
- steps:
  1. Grant **Coding Tester** to the person in **Access Grants** (project, site or unit scope).
- notes: A coding tester can practise the coding workflow and bypasses the site coding gates (enabled, dates, daily limit). Their work is a sandbox that must not change production status or the final cause. Project PIs and site PIs do not get coder access automatically; they need an explicit coder or coding tester grant.
- sources: help pages `coding-tester`, `projects`; `app/templates/admin/panels/organization.html`
- checked: 2026-11-06

## Organization tree

### How do I set up the organization tree for a project?

- id: hdi-admin-040
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Make sure the project's **Structure** is **Organization**.
  2. Open the **Organization** panel (or Project Setup, **2 Structure & Cadres**) and work through the tabs in order: **1. Levels**, **2. Units**, **3. Cadres & permissions**, **4. Workers & Scope**, **5. HIV & Malaria Mortality**, **6. Mentoring & Scientists**.
  3. Use **Populate district defaults** to start from the district reference model.
- notes: The panel explains the order on screen under "How to set up an organization". There are also **ODK form fields** and **Export / Import** tabs.
- sources: `app/templates/admin/panels/organization.html`; `docs/policy/organization-model.md`
- checked: 2026-11-06

### How do I add or change levels?

- id: hdi-admin-041
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Open **1. Levels** and press **Add level**.
  2. Fill **Code**, **Name**, **Depth** (1 is the top) and tick **Optional** if the level may be skipped.
  3. Save.
- notes: Levels must exist before units that use them can be imported.
- sources: `app/templates/admin/panels/organization.html`
- checked: 2026-11-06

### How do I add units to the tree?

- id: hdi-admin-042
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Open **2. Units** and press **Add top-level unit**, or use the **Add child** button on a unit row.
  2. Fill **Parent unit**, **Level**, **Code**, **Name** and optionally address, phone, coordinates and remarks.
  3. Press **Save**.
  4. To move a unit, drag it onto another unit.
- notes: Codes are unique within the project and are recorded on every VA form as the unit code. A unit with no parent is "unplaced" until you press **Map parents** and place it; interviewers are not offered unplaced units.
- sources: `app/templates/admin/panels/organization.html`
- checked: 2026-11-06

### How do I upload many units from a spreadsheet?

- id: hdi-admin-043
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Open the **Export / Import** tab.
  2. Under **Upload units** download the blank units CSV or Excel template and fill unit_code, unit_name, level_code and parent_code.
  3. Press **Preview units**, check the result, then **Apply units**.
- notes: The levels must already exist. Import top-level units before children. A blank parent creates an unplaced unit and leaves an existing unit's parent as it is. Units absent from the file stay active.
- sources: `app/templates/admin/panels/organization.html`
- checked: 2026-11-06

### How do I set who can do what at each level (cadres and permissions)?

- id: hdi-admin-044
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Open **3. Cadres & permissions**.
  2. In **b. Cadre Master List (Add / Rename Cadres)** press **Add cadre**.
  3. In **a. Level × Cadre Capability & Role Matrix (Full Width)** add the cadres that exist at each level, tick whether they can fill VA forms, code VA forms, supervise interviews or report deaths, and set default role pills.
- notes: Default roles are only pre-ticked when a person is granted; access comes only from each person's grants.
- sources: `app/templates/admin/panels/organization.html`; `docs/policy/district-reference-model.md`
- checked: 2026-11-06

### How do I add health workers and link them to existing accounts?

- id: hdi-admin-045
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Open **4. Workers & Scope**.
  2. Add the worker with name, unit and cadre; add an existing account's email or 10-digit mobile number to link it.
  3. Set the worker's coding or supervision units if they differ from their own unit.
- notes: Cadres with default roles create the account and the access together; cadres without default roles stay roster-only. Linking an existing user does not reset their password.
- sources: `app/templates/admin/panels/organization.html`; help page `projects`
- checked: 2026-11-06

### How do I set the HIV and malaria mortality levels?

- id: hdi-admin-046
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Open **5. HIV & Malaria Mortality**, or press **VA presets** on a unit.
  2. For a unit choose **Id10002 — HIV/AIDS mortality area** and **Id10003 — malaria mortality area**: Not set, High, Low or Very low. For many top-level units use **Set Top-Level (District) HIV** and **Set Top-Level (District) Malaria** and **Apply to Top-Level Units**.
- notes: A unit left Not set takes its nearest ancestor's value; with neither the interviewer is asked as usual.
- sources: `app/templates/admin/panels/organization.html`
- checked: 2026-11-06

### How do I limit coding to part of the tree?

- id: hdi-admin-047
- roles: admin, project_pi
- surfaces: web
- steps:
  1. For one subtree press **Coding gate** on a unit: set **Coding**, **Daily coder limit**, **Start date**, **End date**, then **Save gate** (or **Clear gate**).
  2. For the whole project set **Coding scope** (Project Setup, **4 Coding**): **Coding confined within** a level, and what **People granted above that level** may do (**View only (see, code nothing)** or **Code anything in their area**).
- notes: A unit gate narrows its whole subtree and never opens coding that the project-site gate has closed. Coding scope needs the Pick and choose coding intake.
- sources: `app/templates/admin/panels/organization.html`; `app/templates/admin/panels/project_setup.html`
- checked: 2026-11-06

### How do I export or bulk-import the organization workbook?

- id: hdi-admin-048
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Open **Export / Import**.
  2. Download **Workbook (.xlsx)** for levels, units, cadres, level_cadres and workers, or one CSV per sheet.
  3. To import, use **Advanced import**: upload the edited file, run **Dry run**, then **Apply**. Import cadres before level_cadres, and both before workers.
- notes: Rows are matched by code and nothing is deleted unless you tick **Deactivate rows missing from the supplied sheets**. The same tab imports project users and roles (**Preview users**, **Import users**).
- sources: `app/templates/admin/panels/organization.html`
- checked: 2026-11-06

### How do I attach a mentoring institute to districts?

- id: hdi-admin-049
- roles: admin
- surfaces: web
- steps:
  1. Open **Mentoring institutes** (or the link under **6. Mentoring & Scientists**).
  2. Create the institute with **Institute code** and **Institute name**, then **Create institute**.
  3. Under **Attached districts** enter the **Project ID** and **District unit code** and press **Attach district**; use **Detach** to remove.
  4. Under **Staff** link an existing account or **Create staff account**.
- notes: Staff membership gives no project access; assign ordinary unit grants separately in Access Grants. Detaching a district or removing staff keeps existing grants, except that removing staff deactivates their mentor grants in these districts unless another institute covers them. No records are deleted.
- sources: `app/templates/admin/panels/mentor_institutes.html`; `docs/policy/organization-model.md`
- checked: 2026-11-06

## ODK connections, forms and sync

### How do I add an ODK Central connection?

- id: hdi-admin-050
- roles: admin
- surfaces: web
- steps:
  1. Open the **ODK Connections** panel and press **Add Connection**.
  2. Fill **Name**, **Base URL**, **Username (email)** and the account's password (typed only into this form), plus optional **Notes**.
  3. Press **Save**.
- notes: Credentials are stored encrypted and never shown again; leave the username and password blank on edit to keep them. Only external HTTP or HTTPS addresses are accepted. Do not paste credentials anywhere else, including chat.
- sources: `app/templates/admin/panels/odk_connections.html`; help page `odk-connections` (it says "New Connection")
- checked: 2026-11-06

### How do I test an ODK connection?

- id: hdi-admin-051
- roles: admin
- surfaces: web
- steps:
  1. In **ODK Connections** press the **Test connection** button on the connection.
  2. Read the result shown beside it.
- notes: A connection in cooldown fails fast with a cooldown message. See the cooldown entry.
- sources: `app/templates/admin/panels/odk_connections.html`
- checked: 2026-11-06

### Why is my ODK connection in cooldown?

- id: hdi-admin-052
- roles: admin
- surfaces: web
- steps:
  1. Open **ODK Connections** and read "Cooldown until" and the last failure message.
  2. Fix the cause (wrong credentials, server unreachable, expired access).
  3. Wait for the cooldown to end, then press **Test connection**; one successful call clears it.
- notes: After three consecutive retryable failures a connection refuses new requests for about five minutes. Forms on other connections keep syncing. The same warning shows in the Project Forms panel and on the Data Sync status card.
- sources: `app/templates/admin/panels/odk_connections.html`; help page `odk-connections`
- checked: 2026-11-06

### How do I assign a project to an ODK connection?

- id: hdi-admin-053
- roles: admin
- surfaces: web
- steps:
  1. In **ODK Connections** open the connection's **Add project…** list.
  2. Choose the project, then press the **+** button beside the list. To remove it use the small close mark on the project label (**Unassign**).
- notes: One connection can serve several projects, but a project already on another connection is not offered. A project without a connection cannot be mapped to forms: Project Forms says "This project has no ODK connection assigned".
- sources: `app/templates/admin/panels/odk_connections.html`; `app/templates/admin/panels/project_forms.html`
- checked: 2026-11-06

### How do I map a site's ODK form to a project?

- id: hdi-admin-054
- roles: admin
- surfaces: web
- steps:
  1. Open the **Project Forms** panel (or Project Setup, **3 Data collection**) and select the project.
  2. On the site row press **Configure** (tooltip **Configure ODK form**).
  3. Choose **ODK Project**, **ODK Form** and **Form Type**; for an organization project optionally set **Fallback organization unit**.
  4. Press **Save**.
- notes: The dropdowns are read live from ODK Central; if the connection is in cooldown an inline message appears instead. A site can carry more than one form: choose **＋ Add another form…** in the **Editing form** list, or **Remove this form**. The next sync begins downloading for the mapping.
- sources: `app/templates/admin/panels/project_forms.html`; help page `project-forms` (it says at most one form per site)
- checked: 2026-11-06

### What do the SmartVA settings on a form mapping do?

- id: hdi-admin-055
- roles: admin
- surfaces: web
- steps:
  1. In the form's configuration row set **HIV**, **Malaria**, **HCE**, **Free Text** and **Country**.
  2. Press **Save**.
- notes: These settings apply to the next SmartVA run; they do not rewrite results already produced. To regenerate, use a SmartVA-only resync or force-resync in the Data Sync panel.
- sources: `app/templates/admin/panels/project_forms.html`; help page `project-forms`
- checked: 2026-11-06

### What does "Mapping conflicts" mean in Project Forms?

- id: hdi-admin-056
- roles: admin
- surfaces: web
- steps:
  1. Read the **Mapping conflicts** box; it lists an ODK form mapped to more than one project-site.
  2. Remove or correct one of the mappings.
- notes: A single ODK form should feed one project-site; two mappings would duplicate or mix cases.
- sources: `app/templates/admin/panels/project_forms.html`
- checked: 2026-11-06

### What is the Fallback organization unit?

- id: hdi-admin-057
- roles: admin, project_pi
- surfaces: web
- steps:
  1. In a form's configuration row open **Fallback organization unit**.
  2. Pick a unit, or keep "none: unrouted submissions go to the data manager".
- notes: Shown only for projects with an organization tree. Submissions whose payload names no unit are filed under the fallback unit, or left unrouted for the project's data managers.
- sources: `app/templates/admin/panels/project_forms.html`
- checked: 2026-11-06

### How do I start a sync now?

- id: hdi-admin-058
- roles: admin
- surfaces: web
- steps:
  1. Open the **Data Sync** panel.
  2. Press **Sync** in the header.
  3. Watch the status bar and the **Progress Log**; results land in **Recent Runs**.
- notes: A second sync cannot start while one runs (the button is disabled). A sync runs per form through three phases: fetch changed submissions, SmartVA, then coding readiness. Data managers have their own scoped sync under Operations on their dashboard.
- sources: `app/templates/admin/panels/sync_dashboard.html`; help page `sync-behavior`
- checked: 2026-11-06

### How do I stop a running sync?

- id: hdi-admin-059
- roles: admin
- surfaces: web
- steps:
  1. While a run is active press **Stop** in the Data Sync header.
- notes: The run is marked Cancelled and stays in history. Stop applies to full, SmartVA-only, single-form and single-submission runs.
- sources: `app/templates/admin/panels/sync_dashboard.html`; help page `sync-behavior`
- checked: 2026-11-06

### How do I change the auto-sync schedule?

- id: hdi-admin-060
- roles: admin
- surfaces: web
- steps:
  1. In **Data Sync** open **Auto-sync every** and choose 1, 2, 4, 6, 12, 24 or 48 hours.
  2. Press **Save**.
- notes: Takes effect without restarting services. The default is every 6 hours. The help page mentions 1 to 168 hours, but the panel offers only the listed choices.
- sources: `app/templates/admin/panels/sync_dashboard.html`; help page `sync-behavior`
- checked: 2026-11-06

### Why does the sync show partial, and what do I do?

- id: hdi-admin-061
- roles: admin
- surfaces: web
- steps:
  1. In **Data Sync** open **Recent Runs** and read the run's error text.
  2. Partial means at least one form failed while another succeeded; Error means the task crashed or all forms failed.
  3. Check the connection health in the status card, correct the cause, then press **Sync** again. A normal sync fills gaps safely.
- notes: Use **Force-resync** for that form only when data is suspected to be wrong; it redownloads everything for the form and flags finalized cases edited in ODK as upstream changes rather than resetting them.
- sources: `app/templates/admin/panels/sync_dashboard.html` (statusBadge, Force-resync tooltips); help page `sync-behavior`
- checked: 2026-11-06

### How do I compare ODK counts with local counts?

- id: hdi-admin-062
- roles: admin
- surfaces: web
- steps:
  1. In **Data Sync** find **ODK vs Local Coverage**.
  2. Press **Load**.
- notes: ODK counts are loaded on demand because they call ODK Central for every mapping. The local-only sections load automatically.
- sources: `app/templates/admin/panels/sync_dashboard.html`
- checked: 2026-11-06

### How do I repair a form with missing metadata, attachments or SmartVA results (ODK repair)?

- id: hdi-admin-063
- roles: admin
- surfaces: web
- steps:
  1. In **Data Sync** open **Form Repair Coverage by Project / Site / Form** and press **Refresh** if needed.
  2. On the form's row press **Repair** and confirm **Confirm Repair**.
- notes: Repair fixes local gaps in metadata, attachments, legacy attachment rows and SmartVA for that form. It does not compare against ODK counts and does not override protected finalized cases; if their ODK data changed they move to upstream changed instead. Only one Sync, Force-resync or Repair can run at a time.
- sources: `app/templates/admin/panels/sync_dashboard.html`; `docs/current-state/odk-repair-workflow.md`
- checked: 2026-11-06

### How do I force a full resync of one form?

- id: hdi-admin-064
- roles: admin
- surfaces: web
- steps:
  1. In **Data Sync** load **ODK vs Local Coverage**.
  2. Press **Force-resync** on the form's row and confirm.
- notes: Use with caution; prefer a normal **Sync**. Finalized submissions that changed in ODK are flagged for a data-manager decision, not reset.
- sources: `app/templates/admin/panels/sync_dashboard.html` (Force-resync tooltips, confirm text)
- checked: 2026-11-06

### What is the Revoked Submissions list in Data Sync?

- id: hdi-admin-065
- roles: admin
- surfaces: web
- steps:
  1. In **Data Sync** open **Revoked Submissions (Pending Review)**; the card appears only when there are such cases.
  2. Press its refresh button to reload.
  3. Tell the data managers of those projects to decide each case from their dashboard (**View Changes**).
- notes: These are finalized cases whose ODK data changed after coding and still await **Accept And Recode** or **Keep Current ICD Decision**.
- sources: `app/templates/admin/panels/sync_dashboard.html`; `app/static/js/data_manager_dashboard.js`
- checked: 2026-11-06

### How do I start and end site maintenance?

- id: hdi-admin-066
- roles: admin
- surfaces: web
- steps:
  1. Open the **Data Sync** panel and find **Site Maintenance**.
  2. Optionally write a **User Message**.
  3. Press **Start Maintenance**. Press **End Maintenance** when finished.
- notes: Non-admin users keep working for 15 minutes, see a countdown at the bottom of the page, then are logged out; only admin sign-in works afterwards. The state survives restarts and records who changed it.
- sources: `app/templates/admin/panels/sync_dashboard.html`; `docs/policy/site-maintenance-mode.md`
- checked: 2026-11-06

### How do I check attachments, storage and backups?

- id: hdi-admin-067
- roles: admin
- surfaces: web
- steps:
  1. Open the **Attachments** panel (or Project Setup, **Sync & activity**, for one project).
  2. Press **Refresh**, **Run integrity check**, **Upload backlog to S3 now** or **Quarantine uploaded local files** as needed.
  3. At the foot, **Archive pending runs** moves finished SmartVA run folders to storage and **Back up now** starts a database backup.
- notes: The panel never shows file names, paths or case ids. The S3 backlog also clears on a schedule; the button only saves waiting. Quarantine moves already-uploaded local files aside and deletes nothing.
- sources: `app/templates/admin/panels/attachments.html`
- checked: 2026-11-06

### How do I download the ODK XLSForm for a project?

- id: hdi-admin-068
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Administrators: open Project Setup, **3 Data collection**, card **ODK form (XLSForm)**, and press **Download** (one button per form if there are several).
  2. Administrators and project PIs: or open the Organization panel, **Export / Import**, and press **ODK form (.xlsx)**.
- notes: The workbook is the WHO VA 2022 form with the project's enabled extensions, approved languages and organization units, so ODK and the web form collect the same fields. Every download gets a new version stamp. If it fails, the reason is shown beside the button.
- sources: `app/templates/admin/panels/project_setup.html`; `app/templates/admin/panels/organization.html`; `app/routes/admin_xlsform.py`
- checked: 2026-11-06

### Where can I see how DigitVA differs from the WHO VA form?

- id: hdi-admin-069
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Open the **Help** pages and choose **Data Collection**.
  2. Use the field matrix to compare the WHO baseline, ICMR and the DigitVA behaviour per field.
- notes: Overrides and extension layers are fixed in the application, not editable in the admin console. A project chooses which extension layers it uses in 1 Basics (questionnaire layers entry above). The registry of overrides is described in the policy document named below.
- sources: help page `data-collection`; `docs/policy/digitva-who-form-overrides.md`
- checked: 2026-11-06

## Code catalogues, definitions, bucket schemes

### How do I look up an ICD-10 code and see whether coders can pick it?

- id: hdi-admin-070
- roles: admin
- surfaces: web
- steps:
  1. Open the **ICD-10 Browser** panel.
  2. Filter by **Coding**, **Sex** and **Age**, or type a code or title (at least two characters) in **Search**.
  3. Open a node to see its details.
- notes: Chapters, blocks, three-character categories and detailed codes load on demand. Use **Clear Filters** or **Reset Browser** to start over.
- sources: `app/templates/admin/panels/icd10_browser.html`; help page `icd-codes`
- checked: 2026-11-06

### How do I change whether an ICD code can be assigned, by age and sex (allowability)?

- id: hdi-admin-071
- roles: admin
- surfaces: web
- steps:
  1. In the **ICD-10 Browser** (or **ICD-11 Browser**) open a three-character or detailed code.
  2. Set **Coding Selectable**, **Sex Selectable**, **Age Group Selectable** and the **Restriction Note**.
  3. Press **Save Policy** (or **Reset**).
- notes: Chapters and blocks have no policy fields. Changes decide which codes the coding search offers for a death of that age and sex. Policy can be exported (**Export JSON**, **Export XLSX**) and re-imported (**Import JSON**; ICD-11 shows a preview to confirm first).
- sources: `app/templates/admin/panels/icd10_browser.html`; `app/templates/admin/panels/icd11_browser.html`; help page `icd-codes`
- checked: 2026-11-06

### How do I use the ICD-11 browser?

- id: hdi-admin-072
- roles: admin
- surfaces: web
- steps:
  1. Open the **ICD-11 Browser** panel (titled ICD-11 MMS Browser).
  2. Move through the level panes from left to right, use the filters and the search box ("Code or title").
  3. Edit policy as in the ICD-10 entry, or use **Import JSON**, **Export JSON** and **Export XLSX** for bulk work.
- notes: The panel shows the loaded ICD-11 MMS release and how many rows are active. Source structure is never changed, only local coding policy.
- sources: `app/templates/admin/panels/icd11_browser.html`
- checked: 2026-11-06

### How do I add a clinician shorthand or synonym to the coding search?

- id: hdi-admin-073
- roles: admin
- surfaces: web
- steps:
  1. Open **ICD Search Vocabulary** and press **Add Term**.
  2. Enter the **Term** (as the coder will see it), its **Classification** (ICD-10 or ICD-11), the **ICD code** it points to, an optional **Sort order** and **Note**; **Save**.
  3. To stop using a term deactivate it (there is no delete); **Export CSV** downloads the list.
- notes: Matching is exact, and vocabulary hits pass through the same coding-policy filters as other results, so a term for a code that is not allowed for the death does not appear.
- sources: `app/templates/admin/panels/icd_search_vocabulary.html`; `docs/policy/icd-coding-search-vocabulary.md`
- checked: 2026-11-06

### How do I edit a cause group scheme (COD buckets)?

- id: hdi-admin-074
- roles: admin
- surfaces: web
- steps:
  1. Open the **COD Buckets** panel and pick a scheme and age band.
  2. Edit headings, drag to reorder, use **+** to add a level, or open **Add ICD-10 Code** to map a code to the selected disease leaf.
  3. Use **ICD Codes Not Mapped To This Scheme** with **Bulk Map Selected** to map many codes.
  4. To make a new scheme choose the create option and fill **Scheme Name**, **Scheme Code** and age bands (**Min Age**, **Max Age**), then **Create Scheme**.
- notes: Changing a mapping affects reports only; it never rewrites a coder's or reviewer's final cause. Deleting a level lets you either unmap its codes or move them to an Unmapped bucket. Built-in schemes can be restored with **Reset Default**. Schemes can be exported and a JSON export re-imported, which replaces the scheme's bands, nodes and mappings. There is no per-project scheme setting: the scheme is chosen on the report.
- sources: `app/templates/admin/panels/cod_buckets.html`; help page `cod-buckets` (labels there mention ICD-10 only)
- checked: 2026-11-06

### How do I edit the VA cause definitions coders see?

- id: hdi-admin-075
- roles: admin
- surfaces: web
- steps:
  1. Open **VA Definitions**.
  2. Click a code to read it, then **Edit**; change the **Title** or **Definition** and press **Save**. Use **Add VA code** for a new one.
  3. Use the row toggle to **Activate** or **Deactivate**.
- notes: Coders see only active rows, in the VA Definitions modal and on the help page. An edited row is kept when the WHO source is re-imported unless the import is forced.
- sources: `app/templates/admin/panels/va_definitions.html`; help page `va-definitions`
- checked: 2026-11-06

### How do I manage the field mapping and form types?

- id: hdi-admin-076
- roles: admin
- surfaces: web
- steps:
  1. Open **Field Mapping**.
  2. Each card is a form type with its categories, fields and choices. Press **New Form Type** to create or duplicate one, or **Import**.
- notes: A card showing "PII set unconfirmed" means no field of that form is flagged as personal data, so non-PII viewers see no payload and exports withhold it until at least one field is flagged. Fields flagged as personal data are left out of exports.
- sources: `app/templates/admin/panels/field_mapping.html`; `docs/policy/new-form-type-onboarding.md`
- checked: 2026-11-06

## Languages, translations and UI strings

### How do I add or map a language?

- id: hdi-admin-077
- roles: admin
- surfaces: web
- steps:
  1. Open **Languages** and press **New Language**: fill **Code**, **Display Name** and **Aliases (comma-separated)**; save.
  2. If a yellow notice lists "Unmapped language values found in submissions", click the close mark on a value to add it as an alias of a language, or create a new language from it.
- notes: Aliases normalise the raw ODK value (for example different spellings) to one language so cases reach the right coders. Unknown values pass through unchanged and keep showing as unmapped until mapped.
- sources: `app/templates/admin/panels/languages.html`; help page `sync-behavior`
- checked: 2026-11-06

### How do I correct a phone-app or web UI string without a new release?

- id: hdi-admin-078
- roles: admin
- surfaces: web
- steps:
  1. Open **UI Strings** and choose the **Language**.
  2. Filter by **All**, **Corrected**, **Machine** or **Missing**.
  3. Press **Edit** on the row, type the **New text** (keep any {placeholder} exactly as in English) and press **Save**. **Google Translate** opens a suggestion in a new tab.
  4. Use **Revert** to undo a correction; **Export JSON** downloads the language.
- notes: Corrections reach users on their next sign-in or language switch. English is the reference and cannot be edited.
- sources: `app/templates/admin/panels/ui_strings.html`; `docs/policy/ui-strings.md`
- checked: 2026-11-06

### How do I get machine drafts of missing UI strings and accept them?

- id: hdi-admin-079
- roles: admin
- surfaces: web
- steps:
  1. In **UI Strings** tick the languages (none ticked means all) and press **Machine-translate missing strings**.
  2. Reload the panel, filter by **Machine**, check each draft.
  3. Press **Accept** to publish a draft, or **Edit** to fix it first.
- notes: Drafts are shown to nobody until you accept them. The control shows "Not configured" when the translation service is not set up on the server. The last run lists created, rejected, skipped and error counts per language.
- sources: `app/templates/admin/panels/ui_strings.html`
- checked: 2026-11-06

### How do I add a questionnaire language and activate it?

- id: hdi-admin-080
- roles: admin
- surfaces: web
- steps:
  1. Open **Instrument Translations** and use **Add a language** (**Locale code**, **Language name**, **Add language**).
  2. In the language's row press **Send for review**, then **Approve** (or **Back to draft**).
  3. Press **Activate** once approved. **Deactivate** stops serving it.
- notes: A language is created as an inactive draft. Activate is refused until an administrator has approved the locale. English is the per-string fallback. Coverage is shown for information and does not block approval.
- sources: `app/templates/admin/panels/instrument_translations.html`
- checked: 2026-11-06

### How do I improve questionnaire translations (edit, import, machine drafts, XLIFF)?

- id: hdi-admin-081
- roles: admin
- surfaces: web
- steps:
  1. To edit strings press **Edit** on the language's row.
  2. To import a one-time source workbook use **Import a source workbook** (**Locale**, **Language name**, **Workbook (.xlsx, max 5 MB)**, **Import**); **Cross-check only** reports without writing.
  3. For machine drafts press **Draft missing strings**; a draft is marked **Machine draft** and shown to nobody until you accept or edit it.
  4. For a translator's tool use **XLIFF 2.0 interchange**: export, then import the returned file.
- notes: Importing a source is a reviewed one-time action, not the way to fix strings already in use; correct those with the editor. XLIFF can never add a question.
- sources: `app/templates/admin/panels/instrument_translations.html`
- checked: 2026-11-06

### How do I accept or reject a wording suggested by district staff?

- id: hdi-admin-082
- roles: admin, project_pi
- surfaces: web
- steps:
  1. Open **Instrument Translations** (administrators) or **Manage** then **Translations**, tab **Review suggestions** (project PIs).
  2. In **Suggestions from district staff** read each suggestion.
  3. Press **Accept (changes this language for all projects)** and confirm, or **Reject**.
- notes: Translations belong to the questionnaire, not a project: accepting changes the language for every project that uses it. The accepted text is saved as an edited translation and goes out on the language's next version.
- sources: `app/templates/admin/panels/_translation_review_queue.html`; `app/static/js/translation_review_queue.js`
- checked: 2026-11-06

## Devices, training, monitoring

### How do I enrol a phone for the Collect app?

- id: hdi-admin-083
- roles: admin
- surfaces: web
- steps:
  1. Open Project Setup, **People & Grants**, tab **4. Mobile App Devices & Stations**, section **Devices**.
  2. Set **Expires in (minutes)** and **Uses**, then press **Create enrolment code**.
  3. Scan the QR code in the app. The code is shown once, only here.
- notes: The project must be active, and the server must have its device enrolment URL configured (otherwise "Device enrolment is not configured on this server." is shown). The server keeps only a hash of the code, so make a new one if it is lost.
- sources: `app/templates/admin/panels/project_setup.html`; `app/routes/admin_devices.py`
- checked: 2026-11-06

### How do I revoke a lost phone?

- id: hdi-admin-084
- roles: admin
- surfaces: web
- steps:
  1. In the same **Devices** section find the device in the list.
  2. Press **Revoke** and confirm. Everyone signed in on it is signed out. A second prompt asks whether it was lost or stolen; OK marks it compromised.
- notes: A device revoked as compromised is shown as "Revoked (compromised)" and every bundle it signed is refused; unsent work on the phone stays encrypted on the phone.
- sources: `app/templates/admin/panels/project_setup.html`; `app/routes/admin_devices.py`
- checked: 2026-11-06

### How do I register an offline station?

- id: hdi-admin-085
- roles: admin
- surfaces: web
- steps:
  1. In **Devices** find **Register an offline station**.
  2. Enter a **Name**, paste the station's enrolment file and press **Register station**.
- notes: For a station that has never been online. It gets no sign-in secret; its signing key verifies the bundles it sends. A device id already registered is refused.
- sources: `app/templates/admin/panels/project_setup.html`; `app/routes/admin_devices.py`
- checked: 2026-11-06

### Where do users download the Android app?

- id: hdi-admin-086
- roles: admin, project_pi, data_manager, site_pi
- surfaces: web
- steps:
  1. Open the Help page **Mobile app** (linked as **Get the Android app** in the page footer).
  2. Press **Download DigitVA Collect** (or **Collect Plus**) for the version hosted on this server, or use the releases page link.
  3. A phone that says the app is not compatible runs 32-bit Android: use the 32-bit download shown there (Collect only).
- notes: There is no admin panel for app releases. If the page says the APK has not been published for this environment, ask the engineering team for the approved link; do not install an APK from an unverified source.
- sources: help page `mobile-app`; `app/routes/api/app_release.py`
- checked: 2026-11-06

### How do I run a training session?

- id: hdi-admin-087
- roles: admin
- surfaces: web
- steps:
  1. Open **Training sessions**, enter a **New session name** and **Coder slots**, press **Create session**.
  2. Add trainees with **Existing user's email**, choose **Roles in this session**, press **Add participant**; or **Add several users at once**.
  3. Use **Open the trainer report** to see progress and agreement with the source cause.
  4. When done press **Close session**; **Reopen session** reverses it.
- notes: Each coder slot holds 10 pseudonymised cases. Closing deactivates the participants' training access and deletes nothing. If the panel says the training project is not enabled, it needs server configuration first. The trainer report shows the answer key.
- sources: `app/templates/admin/panels/training_sessions.html`; `docs/policy/training-demo-project.md`
- checked: 2026-11-06

### How do I find out who changed something (activity log)?

- id: hdi-admin-088
- roles: admin
- surfaces: web
- steps:
  1. Open **Activity**, or Project Setup, **Sync & activity**.
  2. Filter by **SID**, **Project**, **Site**, **Actor Email ID** or **Action** (the info icon explains the actions).
- notes: It lists state-changing workflow actions, including failed ODK review-state updates for Not Codeable cases.
- sources: `app/templates/admin/panels/activity_log.html`; `docs/policy/admin-activity-log.md`
- checked: 2026-11-06

### How do I check certificates and storage health?

- id: hdi-admin-089
- roles: admin
- surfaces: web
- steps:
  1. Open **System health**.
  2. Read each check's **Expires**, **Days left** and **Status**.
- notes: Certificates and the attachment store are checked live on each visit. "Not configured" means this deployment does not have that item.
- sources: `app/templates/admin/panels/system_health.html`
- checked: 2026-11-06
