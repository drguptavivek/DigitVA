---
title: How-Do-I Corpus - Site PI
doc_type: help-corpus
status: draft
owner: engineering
last_updated: 2026-11-06
---

# How-Do-I Corpus - Site PI

Entries for site principal investigators (`site_pi`). Project PIs (`project_pi`)
use the same page for their projects' sites. Spec: `docs/policy/help-chatbot.md`,
"How-Do-I corpus".

### How do I open the site supervisor dashboard?

- id: hdi-sitepi-001
- roles: site_pi, project_pi
- surfaces: web
- steps:
  1. Sign in and open **Manage** in the top bar.
  2. Choose **VA Dashboard**.
  3. The page opens on the first site (or unit) you are offered, with its figures.
- notes: The page is headed **Site Supervisor Dashboard - KPIs and VA Monitoring**, for one site at a time. If it says "No sites or units assigned for supervision" you hold no site PI grant to show; ask a project administrator. It is read-only monitoring: you cannot code or change cases from it.
- sources: `app/routes/sitepi.py` (`dashboard`); `app/templates/va_frontpages/va_sitepi.html`; `app/templates/va_intermediate_partials/va_navbar.html`
- checked: 2026-11-06

### How do I look at another site or unit?

- id: hdi-sitepi-002
- roles: site_pi, project_pi
- surfaces: web
- steps:
  1. On the VA Dashboard use the **Select a site or unit:** list.
  2. Choose the entry you want; the figures below reload.
- notes: Sites are listed as "project / site". On a district (organization) project the list shows units instead, written with the project, level, unit name and unit code. The list only offers places your grants cover. If you pick one you are not allowed to see you get "Access denied for this site."
- sources: `app/routes/sitepi.py` (`_report_options`, `_report`, `sitepi_data`); `app/templates/va_frontpages/va_sitepi.html`
- checked: 2026-11-06

### What do the cards on the site dashboard mean?

- id: hdi-sitepi-003
- roles: site_pi, project_pi
- surfaces: web
- steps:
  1. Read the cards at the top: **Total VA Submissions**, **Authoritative COD Present**, **Not Codeable**, **Reviewer Eligible**, **Reviewer Finalized**, **Post-Coder Complete** and **Upstream Changed**.
  2. **Authority Source** splits finalized causes into **Coder authoritative** and **Reviewer authoritative**.
  3. **Repair / Review Cycles** counts admin resets, upstream changes and accepts, recode starts and finalizations, and reviewer starts and finalizations.
- notes: Figures are counts for the selected site or unit only. **Pending/active forms** is shown inside the cycles card. These cards describe where cases are in the workflow; they show no deceased names or case details.
- sources: `app/templates/va_intermediate_partials/sitepi_dashboard_content.html`
- checked: 2026-11-06

### How do I see which coders at my site have started coding?

- id: hdi-sitepi-004
- roles: site_pi, project_pi
- surfaces: web
- steps:
  1. Scroll to **VA Coder Participation**.
  2. Read each coder's row: **VA Coder Onboarded DigitVA** shows Onboarded or Pending, then **Coder Finalizations** and **Marked Not-Codeable**.
  3. The table can be sorted and paged.
- notes: Pending means the coder has not onboarded yet; remind them to sign in and accept the terms. The table lists coders for the selected site or unit only.
- sources: `app/templates/va_intermediate_partials/sitepi_dashboard_content.html`
- checked: 2026-11-06

### How do I follow what happened to individual submissions at my site?

- id: hdi-sitepi-005
- roles: site_pi, project_pi
- surfaces: web
- steps:
  1. Scroll to **Submission Workflow Cycles**.
  2. Each row shows the **VA SID** (case id), **Current State**, **Authority**, and counts for coder finals, admin resets, upstream changes and accepts, recode starts and finals, reviewer starts and finals, and the **Last Event** time.
- notes: On a unit report the table shows only the 2000 cases with the most recent workflow events, and a notice says so; the cards above still count every case. A site report lists every case.
- sources: `app/templates/va_intermediate_partials/sitepi_dashboard_content.html`; `app/services/sitepi_reporting_service.py`
- checked: 2026-11-06

### Why does the site dashboard show no data?

- id: hdi-sitepi-006
- roles: site_pi, project_pi
- surfaces: web
- steps:
  1. Check the selected site or unit in **Select a site or unit:**.
  2. If every card shows 0 and the tables are empty, no submissions have been synced or routed to that site or unit yet.
  3. Ask a data manager or administrator to check the ODK sync and the project-site form mapping.
- notes: A site with no mapped form has nothing to show. The VA Coder Participation table lists only coders with an active grant there.
- sources: `app/templates/va_intermediate_partials/sitepi_dashboard_content.html`; help page `project-sites`
- checked: 2026-11-06

### Can a site PI see names, addresses or case details?

- id: hdi-sitepi-007
- roles: site_pi
- surfaces: web
- steps:
  1. Use the dashboard for counts and workflow monitoring.
  2. For case-level work, someone with a coding, review or data-manager grant opens the case.
- notes: By policy a site PI at a mentoring institute or external site is outside the health system and does not see deceased names, addresses, GPS or registration numbers. An in-charge of a health-system unit has a different, personal-data-enabled role. The site PI role does not by itself allow coding; a coder grant is separate.
- sources: `docs/policy/access-control-model.md` ("Three-Tier Mental Model", "site_pi"); help page `user-roles`
- checked: 2026-11-06

### How do I suggest a better wording for a translated question?

- id: hdi-sitepi-008
- roles: site_pi, project_pi, data_manager
- surfaces: web
- steps:
  1. Open **Manage** then **Translations**. The page is titled **Questionnaire translations**; stay on the **Read and suggest** tab.
  2. Choose the **Project** and **Language**.
  3. Find the question with the search box ("Search by question name or English text") and press **Suggest** on its row.
  4. Type the wording and press **Send suggestion**.
- notes: You cannot edit the questionnaire here. An administrator or the project PI accepts or rejects your suggestion. If the page says there is nothing to show, you hold no grant on an active project that serves a translated language. The page needs a grant on the project.
- sources: `app/templates/va_frontpages/va_translation_suggestions.html`; `app/templates/va_intermediate_partials/va_navbar.html`
- checked: 2026-11-06

### How do I see who holds which role at my site?

- id: hdi-sitepi-009
- roles: site_pi, project_pi
- surfaces: web
- steps:
  1. Open **Manage** then **People**.
  2. Read the list of roles by place for the projects where you hold a grant.
- notes: Read-only. To add or remove someone, a data manager (within their scope) or an administrator changes the grant.
- sources: `app/templates/va_frontpages/va_people_roles.html`; `app/templates/va_intermediate_partials/va_navbar.html`
- checked: 2026-11-06
