---
title: How-Do-I Corpus - Data Management
doc_type: help-corpus
status: draft
owner: engineering
last_updated: 2026-11-06
---

# How-Do-I Corpus - Data Management

Entries for data managers (`data_manager`) and the administrators who use the
same pages. Spec: `docs/policy/help-chatbot.md`, "How-Do-I corpus". Labels were
copied from the templates and scripts named in each `sources` line, checked
against the working tree on 2026-11-06.

### How do I open the Data Manager dashboard?

- id: hdi-datamgmt-001
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Sign in and open the **Manage** menu in the top bar.
  2. Choose **Data Manager**.
  3. The dashboard loads the submissions inside your grants. Cards appear at the top and the submission table loads below them.
- notes: The **Manage** menu only lists pages your roles allow. If **Data Manager** is missing you hold no data-manager grant; ask a project administrator. A viewer sees a menu entry called **Data** and gets a read-only table with only a **View** action.
- sources: help page `dm-dashboard`; `app/templates/va_intermediate_partials/va_navbar.html`; `app/routes/data_management.py`
- checked: 2026-11-06

### How do I know which submissions I can see on the dashboard?

- id: hdi-datamgmt-002
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Your view is the union of your data-manager grants. A project-level grant covers every site of that project; a project-site grant covers only that pair.
  2. Use **Filters** to narrow inside that scope. The filters cannot widen it.
- notes: The scope is grant-based, not based on who coded a case. If a project or site is missing from the **Project** or **Site** filter, you hold no active grant there. Administrators can look at grants in Access Grants.
- sources: help page `dm-dashboard`; `app/routes/data_management.py`; `app/templates/va_frontpages/data_manager_partials/_filter_offcanvas.html`
- checked: 2026-11-06

### What do the cards at the top of the dashboard mean?

- id: hdi-datamgmt-003
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Hover or focus the small info button on a card to read its definition.
  2. The cards are: **Total**, **Pending Coding**, **SmartVA Queue**, **Coded**, **Upstream Changed**, **Needs Field Attention**, **Not Codeable (DM)**, **Not analysable**, **Missing in ODK**, **SmartVA Missing** and **SmartVA Failed**.
  3. Click a card that offers a filter to apply it to the table.
- notes: **Pending Coding** counts every case not yet coded: still in screening, attachment sync or SmartVA, in the coder-ready pool, or being coded. **SmartVA Queue** is a separate card that counts only the cases waiting for SmartVA. **Needs Field Attention** means ODK Central review state hasIssues. **Not analysable** groups refused, unavailable-respondent and partly completed interviews. Card counts follow your current filters.
- sources: `app/templates/va_frontpages/data_manager_partials/_kpi_cards.html`; help page `dm-dashboard`
- checked: 2026-11-06

### How do I filter the submission table?

- id: hdi-datamgmt-004
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Press **Filters** in the dashboard header. A panel opens from the right.
  2. Set any of **Project**, **Site**, **Org unit**, **Submission date from** and **Submission date to**, **Date of death from** and **Date of death to**, **ODK Status**, **SmartVA Status**, **Age Group**, **Gender**, **ODK Sync** and **Workflow State**.
  3. Press **Apply Filters**. Press **Clear Filters** to reset.
- notes: **ODK Sync** defaults to In sync; choose Missing in ODK or All to see cases that left ODK Central. With a date-of-death filter set, cases with no recorded date of death are left out. The filter state is kept in the page address, so you can bookmark or share a filtered view with another data manager in the same scope.
- sources: `app/templates/va_frontpages/data_manager_partials/_filter_offcanvas.html`; help page `dm-dashboard`
- checked: 2026-11-06

### How do I search for one submission?

- id: hdi-datamgmt-005
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Type in the box above the table (placeholder "Search VA ID, collector…").
  2. Press **Search**. Press **Clear** to remove the search.
- notes: The table shows masked submission ids. Search runs inside your scope only.
- sources: `app/templates/va_frontpages/data_manager_partials/_table_shell.html`
- checked: 2026-11-06

### How do I show or hide columns in the submission table?

- id: hdi-datamgmt-006
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Press **Columns** above the table.
  2. Tick or untick the optional columns (for example project, collector, flagged-at time).
- notes: The default columns include workflow state, ODK review state, ODK sync issue state, SmartVA status and attachment count.
- sources: `app/templates/va_frontpages/data_manager_partials/_table_shell.html`; help page `dm-dashboard`
- checked: 2026-11-06

### What do the Available, Failed, Ineligible and Missing SmartVA statuses mean?

- id: hdi-datamgmt-007
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Read the SmartVA status column, or set **SmartVA Status** in **Filters**.
  2. Available: an active SmartVA result exists and did not fail. Failed: an active result exists with outcome failed. Ineligible: the case is consent_refused so SmartVA is not required. Missing: no active result exists.
- notes: The filter offers All, Available, Missing and Failed. Open the case with **View** to see the failure stage and detail in the Data Manager Triage panel.
- sources: help page `dm-dashboard`; `app/templates/va_frontpages/data_manager_partials/_filter_offcanvas.html`; `app/templates/va_formcategory_partials/category_data_manager_triage.html`
- checked: 2026-11-06

### How do I open a submission to inspect it?

- id: hdi-datamgmt-008
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Find the row in the dashboard table.
  2. Press **View** in its actions cell. The read-only case page opens.
  3. Use the category navigation to move through the sections. The Data Manager Triage section shows the SmartVA summary.
- notes: Opening a case is recorded in the audit log. You cannot change the submission data here; **Edit** on the dashboard row opens the ODK edit link in a new tab for cases that are not waiting on an upstream decision.
- sources: `app/routes/data_management.py` (`view_submission`); `app/static/js/data_manager_dashboard.js` (ActionsRenderer)
- checked: 2026-11-06

### How do I mark a submission Not Codeable as a data manager?

- id: hdi-datamgmt-009
- roles: data_manager, admin
- surfaces: web
- steps:
  1. From the dashboard, press **View** on the submission.
  2. Go to the **Data Manager Triage** section.
  3. Pick a reason in the list. For **Others**, also fill the explanation box that appears.
  4. Press **Mark Not Codeable**.
- notes: The button only appears while the case is in screening_pending, ready_for_coding or not_codeable_by_data_manager. In any other state the page says the case can no longer be triaged. The case is removed from coder allocation. The local decision is saved first, then DigitVA tries to set the ODK Central review state to hasIssues; if that call fails you get a warning that the local save succeeded and the failure is logged. The reasons offered are submission incomplete or unusable, content does not match the expected deceased or source data, duplicate submission, narrative or key data cannot be understood, and Others.
- sources: `app/forms/va_datamanagerreview_form.py`; `app/templates/va_formcategory_partials/category_data_manager_triage.html`; `app/routes/va_form.py` (data-manager review block); `docs/policy/not-codeable-odk-central-sync.md`
- checked: 2026-11-06

### Why did the ODK Central update fail after I marked a case Not Codeable?

- id: hdi-datamgmt-010
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Read the warning: it says the local save succeeded but the ODK Central update failed.
  2. Check the ODK connection health in the admin Data Sync panel (an administrator can see cooldown and recent failures there).
  3. Ask an administrator to look at the Activity panel for the action "odk review state update failed" for that case.
- notes: The Not Codeable decision stands locally either way; the case stays out of the coding pool. ODK Central write-back is a follow-up step, not a gate.
- sources: `docs/policy/not-codeable-odk-central-sync.md`; `app/routes/va_form.py`; `app/templates/admin/panels/sync_dashboard.html`
- checked: 2026-11-06

### Why can't I see the Mark Not Codeable button?

- id: hdi-datamgmt-011
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Open the case with **View** and check its workflow state in the Data Manager Triage section.
  2. The button is offered only in screening_pending, ready_for_coding and not_codeable_by_data_manager.
- notes: Coded, in-progress and reviewer states cannot be triaged by a data manager. A case already excluded shows "This submission is currently excluded from coder allocation" with the reason. You also need an active data-manager grant covering the case.
- sources: `app/templates/va_formcategory_partials/category_data_manager_triage.html`; `app/routes/data_management.py`
- checked: 2026-11-06

### How do I queue a sync from the dashboard?

- id: hdi-datamgmt-012
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Press **Operations** in the dashboard header.
  2. Press **Sync Latest Data**.
  3. In the **Sync Data** window choose **Projects** and **Sites**.
  4. Review the counts: **Total Forms**, **New To Fetch**, **Updated** and **Missing In ODK**, and the per-form table with Local, ODK, New and Missing.
  5. Press **Queue Syncs**.
- notes: The button is shown only to a data manager with a project or project-site grant; an administrator without such a grant does not see it. The window reports that tasks were queued, not that they finished; follow progress under **Recent Sync Results** in the same **Operations** panel. A case missing from ODK Central is flagged locally, not deleted.
- sources: `app/templates/va_frontpages/data_manager_partials/_ops_offcanvas.html`; `app/templates/va_frontpages/data_manager_partials/_sync_modal.html`; `app/routes/api/data_management.py` (`sync_form`, `sync_preview`); help page `dm-operations`
- checked: 2026-11-06

### Where do I see whether my sync finished?

- id: hdi-datamgmt-013
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Press **Operations** in the dashboard header.
  2. Read the **Recent Sync Results** table.
  3. Read the **Target**, **Started**, **Status**, **Added** and **Updated** columns for the latest runs.
- notes: The list shows the latest 25 data-manager runs: yours, plus other data managers' runs on forms you may sync. Times are in your own timezone. A status of Partial means some forms succeeded and some failed; see the entry on partial syncs.
- sources: `app/templates/va_frontpages/data_manager_partials/_ops_offcanvas.html`; `app/routes/api/data_management.py` (`/sync/runs`)
- checked: 2026-11-06

### Why does the sync show partial?

- id: hdi-datamgmt-014
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Open **Operations** and read the **Recent Sync Results** table for the run's status.
  2. Partial means the run finished but part of it failed (for example one form or some attachments) while the rest succeeded. Error means the task crashed or nothing succeeded.
  3. Run the sync again for the failed form; a normal sync detects and fills gaps. If the cause is an ODK connection problem, ask an administrator to check the connection.
- notes: A run left in Running state for more than about 45 minutes is closed as an error automatically when the next run starts or a worker restarts. Administrators see the same statuses (Success, Partial, Cancelled, Error, Running) under Recent Runs in the Data Sync panel.
- sources: `app/templates/admin/panels/sync_dashboard.html` (statusBadge); help page `sync-behavior`
- checked: 2026-11-06

### Why do the ODK count and the local count differ after a sync?

- id: hdi-datamgmt-015
- roles: data_manager, admin
- surfaces: web
- steps:
  1. In the **Sync Data** window compare the **Local** and **ODK** columns for the form.
  2. Small gaps are normal. Queue a sync again; a normal sync detects missing submissions.
  3. If cases were deleted in ODK Central they appear under **Missing in ODK**, not as errors.
- notes: Every ODK submission is stored locally, including consent-refused ones, which are marked and not coded; small gaps during a sync are normal (the admin coverage table says so). Do not ask for a force-resync for a small gap; that is an administrator action.
- sources: `app/templates/va_frontpages/data_manager_partials/_sync_modal.html`; `app/templates/admin/panels/sync_dashboard.html`; help page `sync-behavior`
- checked: 2026-11-06

### What is the Missing in ODK card and how do I list those cases?

- id: hdi-datamgmt-016
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Click the **Missing in ODK** card, or set **ODK Sync** to Missing in ODK in **Filters**.
  2. The table lists cases that are no longer in ODK Central.
- notes: These cases keep their history, are not coded and are not counted in the other KPIs. They are flagged, never deleted, so a later sync can restore them if they reappear.
- sources: `app/templates/va_frontpages/data_manager_partials/_kpi_cards.html`; `app/templates/va_frontpages/data_manager_partials/_filter_offcanvas.html`; `docs/policy/odk-retired-submissions.md`
- checked: 2026-11-06

### What do I do when a finalized case shows Upstream Changed?

- id: hdi-datamgmt-017
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Click the **Upstream Changed** card or filter the **Workflow State** to Upstream Changed (ODK).
  2. On the case row press **View Changes** and read the changed fields.
  3. Choose **Accept And Recode** to use the new ODK data, clear the old assigned ICD codes and send the case back for recoding.
  4. Or choose **Keep Current ICD Decision** to use the new ODK data but keep the finalized ICD decision.
  5. A confirmation window opens; press its button, which carries the same label as your choice (**Accept And Recode** or **Keep Current ICD Decision**).
- notes: Neither choice writes a comment back to ODK Central. The coding and workflow stay protected until you decide. A case sent back for an interviewer's revision shows **Cancel request** instead; see the entry on revision requests.
- sources: `app/templates/va_frontpages/data_manager_partials/_changes_modal.html`; `app/static/js/data_manager_dashboard.js` (ACTION_LABELS, ActionsRenderer); help page `dm-operations`
- checked: 2026-11-06

### What does Sent back for revision mean and how do I cancel it?

- id: hdi-datamgmt-018
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Filter **Workflow State** to **Sent back for revision**.
  2. On the row, press **Cancel request**, then confirm (**Cancel Request**).
- notes: This is a web or device interview that a coder, reviewer or supervisor sent back to its interviewer. It uses the upstream-changed state but there is no ODK change to review. Cancelling returns the case to the state it was sent back from with its coding untouched.
- sources: `app/static/js/data_manager_dashboard.js`; `app/templates/va_frontpages/data_manager_partials/_filter_offcanvas.html`; help page `dm-operations`
- checked: 2026-11-06

### How do I export data from the dashboard?

- id: hdi-datamgmt-019
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Set the filters you want.
  2. Open the **Export** menu in the dashboard header.
  3. Choose **Export Data**, **Coded COD Snapshot**, **SmartVA Input Data**, **Results** or **Likelihoods**.
- notes: Exports follow your filters and your grant scope. Answer fields marked as personal data in the field mapping are left out, and a form type whose personal-data set is not yet confirmed exports no answers. Identity columns follow your personal-data grant per project. CSV files are UTF-8 with a byte-order mark so Excel opens them correctly. SmartVA exports do not carry the full raw payload.
- sources: `app/templates/va_frontpages/data_manager_partials/_page_header.html`; `app/routes/api/data_management.py` (export routes); help page `dm-dashboard`
- checked: 2026-11-06

### What is in the Coded COD Snapshot export?

- id: hdi-datamgmt-020
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Open **Export** then **Coded COD Snapshot**.
  2. The file has one row per submission.
- notes: Each row carries the coder's final cause, the reviewer's final cause, the authoritative final cause and the SmartVA causes, each with its WHO 2022 VA bucket, plus the Narrative Quality Assessment question columns and Social Autopsy fields. Buckets are left empty, not guessed, when no bucket exists. Original ICD codes are never overwritten by reporting aliases.
- sources: `docs/policy/data-management-cod-snapshot-export.md`; `app/routes/api/data_management.py` (`export-coded-cod-snapshot.csv`)
- checked: 2026-11-06

### What is the difference between the SmartVA Input, Results and Likelihoods exports?

- id: hdi-datamgmt-021
- roles: data_manager, admin
- surfaces: web
- steps:
  1. **SmartVA Input Data**: the cleaned input prepared for SmartVA, for active payloads.
  2. **Results**: the summary result fields of the active SmartVA run.
  3. **Likelihoods**: the raw likelihood rows of the active run.
- notes: All three take only the active (current) SmartVA outputs, not history.
- sources: help page `dm-dashboard`; `app/routes/api/data_management.py`
- checked: 2026-11-06

### How does the coder daily statistics table work?

- id: hdi-datamgmt-022
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Scroll to **Coder Daily Statistics** on the dashboard.
  2. Rows are coders; columns are the last 7 calendar days, including today, in your timezone.
- notes: Only first-pass finalizations are counted; recode finalizations are excluded. The table follows the same filters as the grid.
- sources: help page `dm-dashboard`; `app/templates/va_frontpages/data_manager_partials/_coder_daily_stats.html`; `app/routes/api/data_management.py` (`coder-daily-stats`)
- checked: 2026-11-06

### How do I refresh the dashboard numbers?

- id: hdi-datamgmt-023
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Press **Refresh Dashboard** in the dashboard header; it refreshes the reporting views, then reloads the cards, charts and table.
  2. On the KPI Dashboard press **Refresh**, which also refreshes the reporting views and reloads.
- notes: The KPI Dashboard reads reporting views that are rebuilt about hourly, so a number can lag the live dashboard. The refresh buttons are rate limited.
- sources: `app/templates/va_frontpages/data_manager_partials/_page_header.html`; `app/templates/va_frontpages/data_manager_kpi_partials/_header.html`; `app/routes/api/analytics.py` (`/mv/refresh`); help page `sync-behavior`
- checked: 2026-11-06

### How do I open the KPI Dashboard?

- id: hdi-datamgmt-024
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Open **Manage** in the top bar.
  2. Choose **KPI Dashboard**.
  3. Pick **7 days**, **30 days** or **90 days** at the top right.
- notes: Sections include overview cards (Pending Backlog, Daily Coding Rate, Days to Clear, Coder Utilization), Pipeline Aging (C-07), Site Bottleneck (C-22), Quality Gates & Exclusions, Sync Health (C-02/C-03/C-13), Language Gap Analysis (C-15/C-20), Coder Performance, workflow charts and Daily Operations (Last 8 Days).
- sources: `app/templates/va_frontpages/data_manager_kpi_partials/`; `app/templates/va_intermediate_partials/va_navbar.html`; help page `kpis`
- checked: 2026-11-06

### Why is the Burndown Chart not shown?

- id: hdi-datamgmt-025
- roles: data_manager, admin
- surfaces: web
- steps:
  1. The project has no target completion date, so the burndown line is not drawn. The project form has no field for this date yet.
  2. Read "Days to clear at current rate" in the same card instead.
- notes: The estimate divides the current backlog by the recent coding rate; it shows ∞ when nothing was coded recently.
- sources: `app/templates/va_frontpages/data_manager_kpi_partials/_burndown_section.html`; `app/static/js/dm_kpi_dashboard.js`; `app/routes/api/dm_kpi/dm_kpi_burndown.py`
- checked: 2026-11-06

### What do Pipeline Aging, Time to Code and Site Bottleneck show?

- id: hdi-datamgmt-026
- roles: data_manager, admin
- surfaces: web
- steps:
  1. On the KPI Dashboard find **Pipeline Aging (C-07)**: tiles for cases older than 48 hours (**>48h**), **>7d** and **>30d**, with **Time to Code P50** (the median) beneath.
  2. Find **Site Bottleneck (C-22)** for the sites holding the oldest work.
- notes: Use these to decide which site or language needs more coders. **Language Gap Analysis (C-15/C-20)** compares pending cases to coders and their daily rate per language.
- sources: `app/templates/va_frontpages/data_manager_kpi_partials/_pipeline_section.html`; `app/templates/va_frontpages/data_manager_kpi_partials/_language_coders_section.html`
- checked: 2026-11-06

### How do I open the cause-of-death report (COD reports)?

- id: hdi-datamgmt-027
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Open **Manage** then **COD reports**, or press **COD Buckets** on the Data Manager dashboard.
  2. The page is titled **Cause of Death Report**.
  3. Pick a **Scheme**, optionally a **Project**, **Site**, **Form**, **Date from** and **Date to**, then press **Apply**.
- notes: The report shows Top 10 Causes of Death, Main Cause Groups, an age and sex distribution and a top-10-by-dimension comparison. It covers coded submissions in your scope only and does not change any coder's final cause.
- sources: `app/templates/va_frontpages/va_cod_bucket_reporting.html`; `app/templates/va_frontpages/data_manager_partials/_page_header.html`; help page `cod-buckets`
- checked: 2026-11-06

### How do I change the cause group scheme used in the report?

- id: hdi-datamgmt-028
- roles: data_manager, admin
- surfaces: web
- steps:
  1. On the **Cause of Death Report** page, open the **Scheme** list.
  2. Pick another scheme and press **Apply**.
- notes: The scheme only changes how results are grouped in the report. It is a report choice, not a project setting. Editing the schemes themselves is an administrator task in the COD Buckets panel.
- sources: `app/templates/va_frontpages/va_cod_bucket_reporting.html`; `app/models/va_project_master.py` (no per-project scheme column)
- checked: 2026-11-06

### How do I export the cause-of-death report?

- id: hdi-datamgmt-029
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Set the **Scheme** and filters and press **Apply**.
  2. Press **Export data**.
- notes: The export is built from your scoped coded data and avoids personal data. The page is also laid out for printing.
- sources: `app/templates/va_frontpages/va_cod_bucket_reporting.html`; help page `cod-buckets`
- checked: 2026-11-06

### Why are some deaths missing from the report tables?

- id: hdi-datamgmt-030
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Look for the note under a section's table saying how many coded deaths did not match any reporting category.
  2. Press **View dropped CoDs** beside it. The **Dropped CODs** window lists which ICD codes are not in the chosen scheme for that age group and which are not eligible for coding.
- notes: A coded death whose final ICD code has no active bucket in the chosen scheme for that age group cannot be placed. An administrator can map the code in the COD Buckets panel.
- sources: help page `cod-buckets`
- checked: 2026-11-06

### How do I open AI Questions?

- id: hdi-datamgmt-031
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Open **Manage** then **AI questions**.
  2. Pick a built-in report or a common question from the side column, or type your own in the **Question** box and press **Ask**.
- notes: Answers use aggregate counts inside your scope; individual submissions are never read. Do not type names or personal details.
- sources: `app/templates/va_frontpages/va_ai_questions.html`; `app/templates/va_intermediate_partials/va_navbar.html`; `docs/current-state/ai-analytics-questions.md`
- checked: 2026-11-06

### How do I ask a question in plain language?

- id: hdi-datamgmt-032
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Type your question in the **Question** box, for example "Top 10 causes of death by age band".
  2. If more than one **AI service** is offered, choose one.
  3. Press **Ask**.
  4. To ask about the result, type a follow-up (up to the follow-up limit shown) or press **New question**.
- notes: The page shows how many AI questions are left this week. Built-in reports and common questions do not use the AI service and do not count toward that limit.
- sources: `app/templates/va_frontpages/va_ai_questions.html`; `app/templates/va_frontpages/ai_questions_partials/_result.html`; `app/routes/ai_questions.py`
- checked: 2026-11-06

### Why can't I use the Ask box on AI Questions?

- id: hdi-datamgmt-033
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Read the message in place of the box.
  2. "AI questions are turned off" or "No AI service is configured on this server" means an administrator has not enabled it for this deployment.
  3. Use the **Built-in reports** and your saved queries instead; they still run.
- notes: If you used up your weekly questions you also cannot ask until the count resets.
- sources: `app/templates/va_frontpages/va_ai_questions.html`
- checked: 2026-11-06

### How do I save an AI question to run again?

- id: hdi-datamgmt-034
- roles: data_manager, admin
- surfaces: web
- steps:
  1. After an answer, find the **Save as** field under the result.
  2. Enter a name, optionally a **Description (optional)**, and press **Save**.
  3. Find it later under **My saved queries** and press **Run**; use the delete button there to remove it (you confirm "Delete this saved query?").
- notes: Running a saved query does not use a weekly AI question. Saved queries are your own.
- sources: `app/templates/va_frontpages/ai_questions_partials/_result.html`; `app/templates/va_frontpages/ai_questions_partials/_saved_list.html`
- checked: 2026-11-06

### How do I see the breakdown behind a chart or table row?

- id: hdi-datamgmt-035
- roles: data_manager, admin
- surfaces: web
- steps:
  1. In an AI Questions result, click a chart bar or segment, or press **Breakdown** on a table row.
  2. A side drawer shows that category by sex, age band and workflow state.
- notes: Only the first 500 rows of a result are shown. The result also shows the SQL used.
- sources: `app/templates/va_frontpages/ai_questions_partials/_result.html`; `app/templates/va_frontpages/va_ai_questions.html`
- checked: 2026-11-06

### What does "This data is not captured in DigitVA" mean?

- id: hdi-datamgmt-036
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Read the explanation; the question asks for something DigitVA does not hold, such as population or catchment size.
  2. Rephrase around cases, causes, sites, coders or timings that DigitVA does record.
- notes: No query is run for such questions. A question that needs data hidden from AI questions gets a similar message, "This data is not available to AI questions".
- sources: `docs/current-state/ai-analytics-questions.md` ("Not-captured answers"); `app/templates/va_frontpages/ai_questions_partials/_not_captured.html`
- checked: 2026-11-06

### How do I create a user as a data manager?

- id: hdi-datamgmt-037
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Press **Manage Users** in the Data Manager dashboard header. The **User Management** page opens on the **Users** tab.
  2. Search first (**Find by full email or mobile**, then **Find**) in case the person already has an account.
  3. Press **New User**.
  4. Enter **Name**, optionally **Email** and **Confirm Email**, **Job title** and **Mobile number**. Provide an email, a mobile number, or both.
  5. Choose the initial grant: **Initial Grant Project**, **Initial Grant Role** and **Initial Grant Scope** (site or unit), and the **VA Languages**.
  6. Press **Create User**.
- notes: You never set a password. With an email the person gets a verification message; opening it and confirming emails them a generated password. With a mobile number only, you are shown a one-time sign-in code to give them privately. The initial grant must be inside your own scope.
- sources: `app/templates/va_frontpages/data_manager_partials/_user_management.html`; help page `dm-grants`; `docs/policy/dm-user-grant-management.md`
- checked: 2026-11-06

### How do I give someone a grant in my project as a data manager?

- id: hdi-datamgmt-038
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Open **Manage Users** and the **Access Grants** tab.
  2. Press **Grant Access**.
  3. Search the **User** by email or name, then choose **Role**, **Scope** (**Site-level**, **Unit-level**, or **Project-level** where offered) and the **Site** or **Unit**.
  4. For a unit grant pick a **Cadre**; the cadre's default roles are pre-ticked and can be unticked.
  5. Optionally add **Notes**, then press **Create Grant**.
- notes: The roles offered depend on your scope. Site projects: coder, coding tester and data manager. District projects also allow interviewer, death reporter, reviewer and viewer-type roles in your subtree, and data managers only below your own level. Site PI, interview supervisor, project PI and admin grants stay with administrators. A refused grant shows "You may not manage this grant."
- sources: `app/templates/va_frontpages/data_manager_partials/_user_management.html`; `app/services/authz/actions.py` (DM_SITE_ASSIGNABLE, DM_TREE_ASSIGNABLE); `app/routes/data_management.py`; `docs/policy/dm-user-grant-management.md`
- checked: 2026-11-06

### How do I revoke or restore someone's grant as a data manager?

- id: hdi-datamgmt-039
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Open **Manage Users** and the **Access Grants** tab.
  2. Filter by **Project**, role or the user's name or email.
  3. Press the red revoke button (ban icon, tooltip "Revoke") in the **Actions** column of the grant row.
  4. In the **Revoke Grant** window press **Revoke**.
  5. To restore it, press **Grant Access** and add the same grant again.
- notes: Your own data-manager grant is not listed, so you cannot revoke it and lock yourself out. A revoked grant leaves the list; adding the same grant again reactivates it rather than duplicating it. Only grants inside your scope appear.
- sources: help page `dm-grants`; `app/routes/data_management.py` (`/api/access-grants/<id>/toggle`)
- checked: 2026-11-06

### How do I find a user who is outside my area?

- id: hdi-datamgmt-040
- roles: data_manager, admin
- surfaces: web
- steps:
  1. On the **Users** tab of **Manage Users**, type the person's complete email address or mobile number in **Find by full email or mobile**.
  2. Press **Find**.
- notes: The exact lookup exists so you can add a grant for someone who already has an account elsewhere. A partial name search only searches people already in your area.
- sources: `app/templates/va_frontpages/data_manager_partials/_user_management.html`; `app/routes/data_management.py` (`/api/users/lookup`)
- checked: 2026-11-06

### How do I help a user who cannot sign in or never received the verification email?

- id: hdi-datamgmt-041
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Open **Manage Users**, search for the person and open their details.
  2. If their email is unverified, press **Resend Verification**.
  3. If they have no email or cannot use it, press **Issue sign-in code** and give them the code privately; they use "I have a code" on the sign-in page.
- notes: Codes are shown once. Email can be changed only for users you created who have not signed in yet. If the person simply forgot their password, they use "Forgot Password" with a verified email.
- sources: `app/templates/va_frontpages/data_manager_partials/_user_management.html`; help page `dm-grants`; `app/routes/data_management.py` (resend-verification, sign-in-code)
- checked: 2026-11-06

### How do I change a user's VA languages?

- id: hdi-datamgmt-042
- roles: data_manager, admin
- surfaces: web
- steps:
  1. In **Manage Users** open the person's details.
  2. Tick the **Languages** they should code in.
  3. Press **Save Changes**.
- notes: At least one language is required. Coders are matched to cases by language.
- sources: `app/templates/va_frontpages/data_manager_partials/_user_management.html`; help page `dm-grants`
- checked: 2026-11-06

### What is the Registration numbers page?

- id: hdi-datamgmt-043
- roles: data_manager, project_pi, admin
- surfaces: web
- steps:
  1. Open **Manage** then **Registration numbers**.
  2. If you have more than one project, pick it in **Project:**. The page shows **Registration identifier types** for that project, with a form to add or edit a type.
- notes: This is a configuration page, not only a list: a project PI or project-wide data manager can add and edit the registration numbers the death register collects. Administrators also reach the same panel under Project Setup, Data collection. Only types marked **Active** are collected.
- sources: `app/templates/va_intermediate_partials/va_navbar.html`; `app/routes/admin.py` (`registration_numbers_page`); `app/templates/admin/panels/identifier_types.html`
- checked: 2026-11-06

### How do I see who holds which role in my projects?

- id: hdi-datamgmt-044
- roles: data_manager, site_pi, project_pi, admin
- surfaces: web
- steps:
  1. Open **Manage** then **People**.
  2. Browse the read-only list of roles by place for the projects where you hold a grant.
- notes: The page shows who holds a role; it does not change anything. Names are shown only to viewers allowed to see personal data.
- sources: `app/templates/va_frontpages/va_people_roles.html`; `app/templates/va_intermediate_partials/va_navbar.html`
- checked: 2026-11-06

### Why can't I use the ODK repair or force-resync controls?

- id: hdi-datamgmt-045
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Data managers queue syncs from **Operations**, then **Sync Latest Data**.
  2. Force-resync, per-form **Repair**, attachment repair, the sync schedule and maintenance mode are in the admin Data Sync panel and need the admin role.
  3. Ask an administrator, naming the project, site and form.
- notes: The Repair button fixes missing local metadata, attachments and SmartVA results for one form without comparing counts to ODK Central. Force-resync re-downloads every submission of a form and should be a last resort.
- sources: `app/templates/admin/panels/sync_dashboard.html`; help page `sync-behavior`; `docs/current-state/odk-repair-workflow.md`
- checked: 2026-11-06

### How do coders get cases when the dashboard shows many Pending Coding?

- id: hdi-datamgmt-046
- roles: data_manager, admin
- surfaces: web
- steps:
  1. Check the project's coding intake: random allocation hands the next eligible case to the coder; pick and choose lets the coder browse a list.
  2. Check that coders have active grants and the right languages (**Manage Users**).
  3. Ask an administrator to check the site coding gates (Coding on or off, start and end date, daily coder limit) in Project Setup.
- notes: Cases marked Not Codeable (DM) and cases still in SmartVA or attachment queues are not offered to coders. A coder who reached the daily limit sees no more cases that day.
- sources: help page `projects`; `app/templates/admin/panels/project_sites.html`; `app/templates/admin/panels/project_setup.html`
- checked: 2026-11-06
