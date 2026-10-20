"""Contextual in-page help registry and endpoint resolver for DigitVA pages."""

from __future__ import annotations

import copy

CONTEXTUAL_HELP_PAGES: dict[str, dict] = {
    "home": {
        "page_key": "home",
        "stage_badge": "All 5 Stages · Workspace Overview",
        "title": "Your DigitVA Workspace",
        "summary": "Your personal home screen showing your assigned health areas, role cards, and 5-stage process activity.",
        "bullets": [
            "Part of the 5-Stage Process: Start here to see which tasks need your attention today across registration, interview, coding, review, or supervision.",
            "Within Area vs All: Your badges show whether you cover a specific health facility/area ('Within Area') or the entire project ('All').",
            "Quick actions: Click any card or button (e.g., 'Start coding', 'Register a death', or 'Supervision') to jump directly into your assigned work.",
            "Role access: If you need access to another facility or role, contact your District Programme Manager or Facility In-charge.",
        ],
        "sections": [
            {
                "heading": "How the 5-Stage Process Works",
                "items": [
                    "Stage 1 (Death Register): Community health workers (ASHA, ANM, CHO) record newly reported deaths in their area.",
                    "Stage 2 (Family Interview): Trained interviewers visit the household and complete the WHO Verbal Autopsy questionnaire.",
                    "Stage 3 (Medical Coding): Medical Officers read the interview and assign the ICD medical cause of death.",
                    "Stage 4 (Quality Review): Senior Medical Officers and Medical College Mentors independently review a sample of coded deaths.",
                    "Stage 5 (Summary Reports): Facility In-charges and Programme Managers review mortality causes and operational progress.",
                ],
            },
            {
                "heading": "Understanding Your Scope (Within Area vs All)",
                "items": [
                    "Within Area means your work is automatically filtered to your assigned health facility and all sub-units underneath it (for example, your PHC and its Sub-Centres).",
                    "All means your role covers every facility across the project or district.",
                ],
            },
        ],
        "help_slug": "/help/getting-started",
        "help_label": "Getting Started Guide",
    },
    "deathRegistration": {
        "page_key": "deathRegistration",
        "stage_badge": "Stage 1 of 5 · Death Register",
        "title": "Registering a Death",
        "summary": "Record a newly reported death in your village, sub-centre, or health facility area (Stage 1 of 5).",
        "bullets": [
            "Stage 1 (Death Register): Log basic details (name, date of death, age, location) as soon as you learn about a death in your area.",
            "Save vs Save and start interview: Tap 'Save' if you or another worker will visit the family later; tap 'Save and start interview' if you are with the family right now.",
            "Within Area: Select the specific village, sub-centre, or facility where the deceased lived or died within your assigned area.",
            "Duplicate check: DigitVA automatically checks for similar deaths to prevent registering the same person twice.",
        ],
        "sections": [
            {
                "heading": "Filling Out the Death Register",
                "items": [
                    "Choose the exact health unit (Sub-Centre, PHC, or Ward) where the household is located so the right interviewer receives the case.",
                    "Enter the deceased person's full name, sex, and date of death. If the exact date of birth is unknown, choose Month & Year, Year only, or Age in years.",
                    "Record clear household address landmarks and informant phone numbers so the interviewer can locate the family respectfully.",
                ],
            },
            {
                "heading": "Save vs Save and Start Interview",
                "items": [
                    "Tap 'Save' when reporting a death for a later household visit — the case enters the area worklist immediately.",
                    "Tap 'Save and start interview' only when you are trained for interviews and are sitting with the bereaved family right now.",
                ],
            },
        ],
        "help_slug": "/help/data-collection",
        "help_label": "Data Collection Guide",
    },
    "myRegisteredDeaths": {
        "page_key": "myRegisteredDeaths",
        "stage_badge": "Stage 1 of 5 · Death Register",
        "title": "My Registered Deaths",
        "summary": "View and update the deaths you have reported in your area before the family interview is completed (Stage 1 of 5).",
        "bullets": [
            "Tracking status: See which of your reported deaths are pending an interview, currently in progress, or already completed.",
            "Correcting details: You can edit dates, names, or addresses for any death you registered until an interviewer finishes the interview.",
            "Family visits: Interviewers use this list to locate the household and conduct the WHO Verbal Autopsy visit.",
            "Within Area: View deaths registered across your assigned health facilities and sub-centres.",
        ],
        "sections": [
            {
                "heading": "Managing Reported Deaths",
                "items": [
                    "Review your list of reported deaths to verify that names, dates of death, and household landmarks are accurate.",
                    "Tap 'Edit registration' on any pending record to fix spelling, update a phone number, or add a clearer landmark.",
                ],
            },
            {
                "heading": "When a Record Locks",
                "items": [
                    "Once an interviewer completes and submits the family interview (Stage 2), the registration details lock so the clinical record remains consistent.",
                    "If a death was registered twice by mistake, inform your Facility In-charge or Interview Supervisor so they can mark it as a duplicate.",
                ],
            },
        ],
        "help_slug": "/help/data-collection",
        "help_label": "Data Collection Guide",
    },
    "collection": {
        "page_key": "collection",
        "stage_badge": "Stage 2 of 5 · Family Interview",
        "title": "Reported Deaths & Interview Worklist",
        "summary": "Manage assigned deaths, schedule household visits, and start or resume WHO Verbal Autopsy interviews (Stage 2 of 5).",
        "bullets": [
            "Stage 2 (Interview): Visit the family to sensitively collect the illness history and symptoms using the WHO 2022 questionnaire.",
            "In-progress drafts: Save your draft frequently; if interrupted, you can safely resume the interview anytime from your draft list.",
            "Self-coding: If you are a Medical Officer with self-coding enabled, you can choose to assign the cause of death immediately after finishing the interview.",
            "Within Area vs All: Filter chips let you focus on interviews within your assigned facility or across all areas.",
        ],
        "sections": [
            {
                "heading": "Using Status & Area Filters",
                "items": [
                    "Use the status chips ('To visit', 'In progress', 'Completed') to see which families still need a household visit.",
                    "Open any reported death card to view informant phone numbers, log a contact attempt, or schedule the next visit date.",
                ],
            },
            {
                "heading": "Starting, Resuming & Self-Coding",
                "items": [
                    "Tap 'Start interview' when you arrive at the household, or 'Resume interview' to continue a saved draft.",
                    "On the mobile app, tap 'Sync' when you have internet connectivity to upload finished interviews and download newly reported deaths.",
                ],
            },
        ],
        "help_slug": "/help/data-collection",
        "help_label": "Data Collection Guide",
    },
    "interview": {
        "page_key": "interview",
        "stage_badge": "Stage 2 of 5 · Family Interview",
        "title": "WHO Verbal Autopsy Questionnaire",
        "summary": "Conduct and record the household verbal autopsy interview section by section (Stage 2 of 5).",
        "bullets": [
            "Automatic & manual saving: Your answers are saved automatically as you move between questions, and you can tap 'Save' anytime.",
            "Adaptive sections: The questionnaire automatically shows only the questions relevant to the deceased person's age group and sex.",
            "Local language support: Use the language selector at the top right to switch questions into Hindi or your local language while keeping English visible.",
            "Open narrative: Record the family's own story of the illness in clear clinical detail before completing the submission.",
        ],
        "sections": [
            {
                "heading": "Saving & Navigating Sections",
                "items": [
                    "Identity fields (name, sex, date of death) carried over from Stage 1 are pre-filled so you do not have to ask the family twice.",
                    "If the family needs a break, tap 'Save' and 'Back to collection' — you can resume from the exact same section later.",
                ],
            },
            {
                "heading": "Switching Language & Completing the Visit",
                "items": [
                    "Switch the form language anytime from the top header without losing any recorded answers.",
                    "At the end of the questionnaire, review any highlighted required questions and submit the interview to advance the case to Stage 3 (Medical Coding).",
                ],
            },
        ],
        "help_slug": "/help/data-collection",
        "help_label": "Data Collection Guide",
    },
    "caseDetail": {
        "page_key": "caseDetail",
        "stage_badge": "Stages 1–2 · Case Details & Follow-up",
        "title": "Death Case Details & Visit Log",
        "summary": "Review household address, informant contact details, visit attempts, and interview status for this death.",
        "bullets": [
            "Household & informant details: View the full address, village/ward, landmark, and clickable phone numbers to contact the family.",
            "Log contact attempts: Record whether the family was reached, unavailable, moved, or refused so your supervisor sees accurate field progress.",
            "Schedule next visit: Set a planned visit date to organize your upcoming field schedule.",
            "Start or resume interview: Launch the WHO Verbal Autopsy questionnaire directly from this screen when ready.",
        ],
        "sections": [
            {
                "heading": "Logging Contact Attempts & Next Visit",
                "items": [
                    "Tap 'Log attempt' after calling or visiting the household to record the outcome (Reached, No answer, Wrong number, Moved, or Refused).",
                    "Tap 'Set visit' to record the date you plan to visit the household so the worklist stays sorted by priority.",
                ],
            },
            {
                "heading": "Starting or Resuming the Interview",
                "items": [
                    "Tap 'Start interview' to open the questionnaire with the deceased person's registration details pre-filled.",
                    "If another interviewer already has an active draft on this case, DigitVA displays a notice so two workers do not interview the same family simultaneously.",
                ],
            },
        ],
        "help_slug": "/help/data-collection",
        "help_label": "Data Collection Guide",
    },
    "coding": {
        "page_key": "coding",
        "stage_badge": "Stage 3 of 5 · Medical Coding",
        "title": "Medical Officer Coding Queue",
        "summary": "Select or receive completed verbal autopsy interviews and assign the medical cause of death (Stage 3 of 5).",
        "bullets": [
            "Stage 3 (Coding): Read the family's narrative and symptom checklist, complete narrative quality assessment (if enabled), and select the ICD cause of death.",
            "Pick vs Random: Choose 'Start next random case' for automatic assignment or pick a specific case from your queue.",
            "24-hour correction window: After submitting your final cause of death, you can reopen and correct your determination for up to 24 hours ('Recode').",
            "Within Area: You only code deaths belonging to your assigned health facility, block, or district (or designated cross-facility roster).",
        ],
        "sections": [
            {
                "heading": "Pick a Case vs Random Allocation",
                "items": [
                    "Use 'Start next random case' to immediately open the next eligible completed interview matching your area and language skills.",
                    "Or browse the 'Available' tab to inspect age group, sex, and health unit before picking a specific case.",
                ],
            },
            {
                "heading": "Available vs My Coded Cases (24-Hour Recode)",
                "items": [
                    "Cases currently assigned to you appear at the top so you can resume where you left off.",
                    "Switch to 'My coded cases' to view cases you have already finalized; for 24 hours after coding, you can click 'Recode' to revise your cause of death before the case enters Stage 4 review.",
                ],
            },
        ],
        "help_slug": "/help/coding-workflow",
        "help_label": "Coding Workflow Guide",
    },
    "caseCoding": {
        "page_key": "caseCoding",
        "stage_badge": "Stage 3 of 5 · Coding a Case",
        "title": "Assigning the Medical Cause of Death",
        "summary": "Read the family narrative and symptom checklist on the left, then record Step 1 (Initial) and Step 2 (Final) ICD cause of death.",
        "bullets": [
            "Left-to-right clinical review: Browse symptom categories, open-ended narrative, and any required quality panels before opening the COD assessment tab.",
            "Step 1 (Initial) & Step 2 (Final): Record your initial clinical impression in Step 1, review any decision-support reference, and submit your conclusive cause in Step 2.",
            "ICD search: Search by medical term or ICD code; DigitVA automatically filters codes appropriate for the deceased person's age and sex.",
            "Private notes: Use the Notes panel to jot down clinical reasoning while examining the case.",
        ],
        "sections": [
            {
                "heading": "Step 1 (Initial) & Step 2 (Final) Assessment",
                "items": [
                    "First review each symptom category on the left sidebar (and complete Narrative Quality or Social Autopsy panels if prompted).",
                    "In Step 1, select the immediate and antecedent/underlying ICD causes based on your clinical judgment and save.",
                    "In Step 2, confirm or refine the conclusive underlying cause of death and submit to complete coding.",
                ],
            },
            {
                "heading": "When a Case Cannot Be Coded",
                "items": [
                    "If the interview lacks sufficient clinical information to determine any cause, use the 'Not codeable' option and state the reason clearly.",
                    "If you need to step away and return the case to the general pool for another Medical Officer, use 'Release case'.",
                ],
            },
        ],
        "help_slug": "/help/coding-workflow",
        "help_label": "Coding Workflow Guide",
    },
    "reviewing": {
        "page_key": "reviewing",
        "stage_badge": "Stage 4 of 5 · Quality Review",
        "title": "Senior Reviewer Queue",
        "summary": "Independently review finalized verbal autopsy cases for clinical quality assurance after the 24-hour recode window closes (Stage 4 of 5).",
        "bullets": [
            "Stage 4 (Review): Senior Medical Officers and Medical College Faculty independently assess cases once the original coder's 24-hour window has closed.",
            "Independent assessment: You evaluate the narrative and symptoms without seeing the first coder's decision to ensure unbiased quality control.",
            "Reviewer authority: Your reviewed cause of death serves as the final quality-assured determination while preserving the first coder's record in history.",
            "Within Area: Cases are drawn from your assigned district, block, or mentoring medical college partner area.",
        ],
        "sections": [
            {
                "heading": "Selecting a Case to Review",
                "items": [
                    "Cases appear in this queue only after the original coder has finalized Step 2 and the 24-hour recode window has elapsed.",
                    "Click 'Start next random review' or select a case from the 'Available' tab to begin your quality review.",
                ],
            },
            {
                "heading": "Blinded Quality Assurance",
                "items": [
                    "During your review, the original coder's ICD selection is hidden so your clinical judgment remains completely independent.",
                    "You cannot review a case that you personally coded in Stage 3.",
                ],
            },
        ],
        "help_slug": "/help/coding-workflow",
        "help_label": "Coding Workflow Guide",
    },
    "caseReviewing": {
        "page_key": "caseReviewing",
        "stage_badge": "Stage 4 of 5 · Reviewing a Case",
        "title": "Conducting an Independent Quality Review",
        "summary": "Evaluate the symptom history and narrative, complete your independent cause-of-death assessment, and finalize the review.",
        "bullets": [
            "Blinded evaluation: Review all interview sections and narrative details on the left before recording your independent ICD assessment.",
            "Two-step review: Save your initial reviewer impression (Step 1) and then confirm your final conclusive cause of death (Step 2).",
            "Audit preservation: DigitVA preserves both the original coder's assessment and your reviewer determination in the permanent audit trail.",
            "24-hour reviewer recode: After submitting your review, you can reopen and adjust your determination within 24 hours.",
        ],
        "sections": [
            {
                "heading": "Completing the Reviewer Assessment",
                "items": [
                    "Examine each symptom category and the open narrative using the left navigation list.",
                    "Select the ICD cause of death in the COD Assessment panel and submit both Step 1 and Step 2 to mark the case as Reviewed.",
                ],
            },
            {
                "heading": "Releasing or Returning a Case",
                "items": [
                    "If you cannot complete the review right now, click 'Release' so another Senior Reviewer or Medical College Mentor can pick it up.",
                ],
            },
        ],
        "help_slug": "/help/coding-workflow",
        "help_label": "Coding Workflow Guide",
    },
    "caseView": {
        "page_key": "caseView",
        "stage_badge": "Stages 3–4 · Read-Only Case View",
        "title": "Completed Case Summary & Audit Trail",
        "summary": "Read-only clinical view of the interview responses, coded causes of death, SmartVA reference, and workflow history.",
        "bullets": [
            "Read-only inspection: Browse every questionnaire section and the family narrative without modifying any clinical data.",
            "COD Reference card: Compare the Final COD, Reviewer determination, and Initial Coder assessment side by side.",
            "Workflow History: Inspect the chronological audit log of registration, interview submission, coding, and review events.",
            "Recode button: If you coded or reviewed this case within the last 24 hours, use the 'Recode' action in the queue to make corrections.",
        ],
        "sections": [
            {
                "heading": "Browsing Symptom Categories & COD Reference",
                "items": [
                    "Click any category on the left sidebar to inspect the respondent's answers and highlighted positive symptoms.",
                    "Scroll down to the COD Reference card to see the conclusive, immediate, and antecedent causes recorded for this death.",
                ],
            },
            {
                "heading": "Recoding Within 24 Hours",
                "items": [
                    "This screen is read-only so you can safely review past work without accidental edits.",
                    "If your 24-hour recode window is still open, return to 'My coded cases' or 'My reviewed cases' and click 'Recode' to reopen the assessment editor.",
                ],
            },
        ],
        "help_slug": "/help/viewing-history",
        "help_label": "Viewing History Guide",
    },
    "supervision": {
        "page_key": "supervision",
        "stage_badge": "Stage 2 Oversight · Field Supervision",
        "title": "Interview Supervision & Quality Triage",
        "summary": "Monitor field interviews in your health area, resolve flagged cases or refusals, and reopen interviews when needed.",
        "bullets": [
            "Supervisory oversight: Facility In-charges (SMO/MO) track field interviewers, visit schedules, and completed interviews in their area.",
            "Resolving flags: Review cases where an interviewer reported a problem, family refusal, or duplicate registration.",
            "Reopen or cancel: Authorised supervisors can reopen an interview sent back for revision or cancel invalid registrations.",
            "Within Area: You supervise interviews and field staff across your assigned health facility and every sub-centre under it.",
        ],
        "sections": [
            {
                "heading": "Attention Tiles and the Deaths Tab",
                "items": [
                    "Four tiles count your cases: 'Needs my decision' (a flag waits or a second complete interview is to be chosen), 'Overdue revisits', 'Stuck (30 days)' and 'Total in scope'. Tap a tile to filter the list.",
                    "In the Deaths tab, 'Needs my attention' lists those cases; switch to 'All deaths' to monitor every registered death across your facility's catchment area.",
                ],
            },
            {
                "heading": "Supervisor Actions (Reopen, Duplicate, Close)",
                "items": [
                    "Use 'Reopen for revision' when an interviewer needs to return to the household to complete a partial interview or fix an error.",
                    "Use 'Mark duplicate' or 'Cancel/Close' with a clear note when a death was registered twice or outside your jurisdiction.",
                ],
            },
        ],
        "help_slug": "/help/user-roles",
        "help_label": "User Roles Guide",
    },
    "mentoring": {
        "page_key": "mentoring",
        "stage_badge": "Stages 3–5 · Medical College Mentoring",
        "title": "Mentoring Institution Portal",
        "summary": "View your medical college's supported districts, your assigned Within Area roles, and manage the college faculty/resident roster.",
        "bullets": [
            "Medical college role: Medical colleges provide academic mentoring and quality coding/review support to partner health districts.",
            "College roster: The College / Institute Admin adds and manages accounts for professors, assistant professors, and resident doctors.",
            "District assignments: District Programme Managers assign specific Within Area roles (Coder, Reviewer, Coding Tester, Viewer) to college mentors.",
            "Outside district headcount: Mentors sit alongside district staff without taking up permanent district health cadre posts.",
        ],
        "sections": [
            {
                "heading": "How Medical College Mentoring Works",
                "items": [
                    "Each Medical College or Mentoring Institute is linked to one or more partner districts or health areas.",
                    "Faculty and residents assigned as Reviewers (Stage 4) or Coders (Stage 3) can jump directly to their Coding or Review queues from this page.",
                ],
            },
            {
                "heading": "Roster Management vs District Role Assignment",
                "items": [
                    "If you are a Mentoring Institute Admin, use the roster table below to add faculty/residents, update their designations, or deactivate accounts.",
                    "District Programme Managers then grant those college members 'Within Area' roles on the specific blocks or districts they support.",
                ],
            },
        ],
        "help_slug": "/help/mentoring-institutes",
        "help_label": "Mentoring Institutes Guide",
    },
    "organization": {
        "page_key": "organization",
        "stage_badge": "Health System Hierarchy · Within Area",
        "title": "My Health Facility & Organization Tree",
        "summary": "See where your assigned health facility sits in the District → Block/CHC → PHC → Sub-Centre hierarchy and who works in each unit.",
        "bullets": [
            "Administrative hierarchy: View and configure the health system levels (District, Block/CHC, PHC, Sub-centre, Village).",
            "Assigning roles: Programme Managers and In-charges assign roles (Interviewer, Coder, Reviewer, Supervisor) to health workers.",
            "Scope ('Within Area' vs 'All'): Choose whether a worker's role covers their own facility subtree ('Within Area'), selected cross-area units, or the entire project.",
            "QR onboarding: Generate one-scan login QR codes to onboard field workers into the DigitVA mobile app instantly.",
        ],
        "sections": [
            {
                "heading": "Understanding Your 'Within Area' Coverage",
                "items": [
                    "Your assigned unit is highlighted in the tree; 'Within Area' access automatically includes that unit and all child facilities beneath it.",
                    "Expand any Block/CHC, PHC, or Sub-Centre node to see its child units and reporting structure.",
                ],
            },
            {
                "heading": "Viewing Facility Staff & Sub-Units",
                "items": [
                    "Click any health unit in the tree to see the health workers, Medical Officers, and supervisors assigned to that facility.",
                    "Programme Managers and Admins can also add new sub-units or assign worker roles directly from the selected unit panel.",
                ],
            },
        ],
        "help_slug": "/help/user-roles",
        "help_label": "User Roles Guide",
    },
    "settings": {
        "page_key": "settings",
        "stage_badge": "Preferences · Display & Device",
        "title": "App Settings & Display Preferences",
        "summary": "Customize your colour theme (System, Light, or Dark) and manage your local device preferences.",
        "bullets": [
            "Appearance modes: Choose 'System' to follow your device's day/night schedule, 'Light' for bright outdoor field visits, or 'Dark' for low-glare reading.",
            "Instant saving: Your display preference is saved immediately on this browser or phone.",
            "Profile & passkeys: To change your coding languages, password, or passkey sign-in, open your account menu at the top right.",
        ],
        "sections": [
            {
                "heading": "Display Theme & Language",
                "items": [
                    "Select 'Light' mode for high contrast in daylight when conducting household interviews outdoors.",
                    "Select 'Dark' mode when coding or reviewing cases in low-light clinical environments.",
                ],
            },
        ],
        "help_slug": "/help/getting-started",
        "help_label": "Getting Started Guide",
    },
    "area": {
        "page_key": "area",
        "stage_badge": "Stage 5 of 5 · Summary Reports",
        "title": "Area Progress & Mortality Summary",
        "summary": "Track death registration, family interview completion, and medical coding progress across every facility in your assigned area.",
        "bullets": [
            "Stage 5 (Summary Reports): See how many deaths have been registered, interviewed, coded, and reviewed in your jurisdiction.",
            "Facility drill-down: Compare progress across blocks, PHCs, and sub-centres within your area to spot bottlenecks early.",
            "Within Area scope: Figures are automatically scoped to your assigned health facility subtree.",
        ],
        "sections": [
            {
                "heading": "Reading Your Area Pipeline",
                "items": [
                    "Compare Stage 1 (Registered), Stage 2 (Interviewed), Stage 3 (Coded), and Stage 4 (Reviewed) counts side by side.",
                    "Identify sub-centres with pending interviews or backlogged coding so you can support field teams promptly.",
                ],
            },
            {
                "heading": "Filtering by Time Period & Unit",
                "items": [
                    "Use the area and date filters to inspect monthly or quarterly mortality surveillance progress for review meetings.",
                ],
            },
        ],
        "help_slug": "/help/kpis",
        "help_label": "KPI Dashboard Guide",
    },
    "sitepi": {
        "page_key": "sitepi",
        "stage_badge": "Stage 5 of 5 · Facility In-charge Dashboard",
        "title": "Facility & Site In-charge Overview",
        "summary": "Review overall operational progress, coder completion rates, and cause-of-death distributions for your jurisdiction.",
        "bullets": [
            "Jurisdiction overview: Monitor total verbal autopsy submissions, coding completion percentages, and active health workers.",
            "Workload balance: Check how many cases are waiting for coding or quality review in your site or district.",
            "Leading causes of death: View high-level mortality patterns emerging from finalized verbal autopsies.",
        ],
        "sections": [
            {
                "heading": "Monitoring Operational Health",
                "items": [
                    "Use the summary cards at the top to check how many interviews were received this week and how many have been coded.",
                    "Coordinate with Medical Officers and Senior Reviewers if the pending coding or review queue grows.",
                ],
            },
        ],
        "help_slug": "/help/user-roles",
        "help_label": "User Roles Guide",
    },
    "dataManagement": {
        "page_key": "dataManagement",
        "stage_badge": "Stage 5 of 5 · Data Management",
        "title": "Data Manager Operations & Case Triage",
        "summary": "Search and triage submissions across your district or project, manage user role grants, and export summary datasets.",
        "bullets": [
            "Case search & triage: Filter verbal autopsy cases by workflow state, health unit, coder, reviewer, or date range.",
            "Operational actions: Reallocate stuck cases, manage exclusions, or trigger SmartVA reference runs where permitted.",
            "Data export: Export anonymized or summary COD snapshots according to your project's governance permissions.",
        ],
        "sections": [
            {
                "heading": "Searching & Filtering Submissions",
                "items": [
                    "Use the filter bar to locate cases by workflow stage (Pending Coding, Coded, Pending Review, Reviewed, or Not Codeable).",
                    "Click any case row to open its read-only summary and full workflow history.",
                ],
            },
            {
                "heading": "Managing Grants & Exports",
                "items": [
                    "Use the People & Roles and Export tools to keep district staffing up to date and download approved mortality reports.",
                ],
            },
        ],
        "help_slug": "/help/dm-dashboard",
        "help_label": "Data Manager Guide",
    },
    "dmKpi": {
        "page_key": "dmKpi",
        "stage_badge": "Stage 5 of 5 · Pipeline Analytics",
        "title": "KPI & Pipeline Performance Dashboard",
        "summary": "Monitor stage-by-stage turnaround times, coder daily throughput, language coverage, and quality metrics.",
        "bullets": [
            "Pipeline velocity: Track how quickly cases move from interview submission to medical coding and senior review.",
            "Coder & reviewer throughput: View active coders, completed cases per coder, and average turnaround times.",
            "Language match: Check whether pending interviews have enough coders fluent in each narration language.",
        ],
        "sections": [
            {
                "heading": "Using Pipeline & Burndown Charts",
                "items": [
                    "Inspect the pipeline funnel and burndown tabs to see whether coding is keeping pace with incoming field interviews.",
                    "Check the Language tab to ensure every local narration language has sufficient Medical Officer coverage.",
                ],
            },
        ],
        "help_slug": "/help/kpis",
        "help_label": "KPI Dashboard Guide",
    },
    "codBuckets": {
        "page_key": "codBuckets",
        "stage_badge": "Stage 5 of 5 · Mortality Causes",
        "title": "Cause-of-Death Bucket Reports",
        "summary": "View aggregated cause-of-death distributions grouped into public-health mortality buckets for your area.",
        "bullets": [
            "Public-health grouping: Individual ICD-10 and ICD-11 codes are grouped into standard mortality buckets (such as Maternal, Neonatal, Infectious, or Cardiovascular).",
            "Age & sex breakdown: Compare cause-of-death patterns across adult, child, and neonatal age bands.",
            "Actionable surveillance: Use these distributions for district health planning and mortality review meetings.",
        ],
        "sections": [
            {
                "heading": "Exploring Mortality Buckets",
                "items": [
                    "Filter by project, site, age band, or date range to see the leading causes of death in your area.",
                    "Switch between reporting schemes or export summary tables for public-health review.",
                ],
            },
        ],
        "help_slug": "/help/cod-buckets",
        "help_label": "COD Buckets Guide",
    },
    "peopleRoles": {
        "page_key": "peopleRoles",
        "stage_badge": "Health System Roster · Roles & Scope",
        "title": "People, Cadres & Role Assignments",
        "summary": "Inspect health workers, medical officers, and mentors across facilities and manage Within Area role grants.",
        "bullets": [
            "Unified staff directory: See all workers in your jurisdiction along with their cadre (ASHA, ANM, CHO, MO, SMO, DPM) and home facility.",
            "Within Area vs Cross-Area grants: Check which workers hold role grants on their own facility subtree or across partner units.",
            "Quick onboarding: Generate mobile login QR codes or update role assignments for staff in your scope.",
        ],
        "sections": [
            {
                "heading": "Filtering by Facility, Cadre & Role",
                "items": [
                    "Select any node in the health facility hierarchy to filter the staff list to that specific block, PHC, or sub-centre.",
                    "Review active role badges (Death Reporter, Interviewer, Interview Supervisor, Coder, Reviewer, Data Manager) for each person.",
                ],
            },
        ],
        "help_slug": "/help/dm-grants",
        "help_label": "Managing Grants Guide",
    },
    "translations": {
        "page_key": "translations",
        "stage_badge": "Localisation · Questionnaire Languages",
        "title": "Questionnaire Translation Suggestions",
        "summary": "Review and suggest clearer local-language phrasing for WHO Verbal Autopsy questions.",
        "bullets": [
            "Field-tested phrasing: Suggest natural, respectful local-language wording for questions, hints, and answer choices.",
            "Review workflow: Submitted suggestions are reviewed before being published to mobile and web interviewers.",
            "Versioned updates: Approved translations automatically sync to field devices on their next refresh.",
        ],
        "sections": [
            {
                "heading": "Proposing & Reviewing Translations",
                "items": [
                    "Select a target language and search for the question or symptom prompt you want to improve.",
                    "Enter your suggested translation and save it for language coordinator review.",
                ],
            },
        ],
        "help_slug": "/help/data-collection",
        "help_label": "Data Collection Guide",
    },
    "profile": {
        "page_key": "profile",
        "stage_badge": "Account · Profile & Security",
        "title": "My Profile, Coding Languages & Passkeys",
        "summary": "Update your designation, coding languages, time zone, password, and fast passkey sign-in.",
        "bullets": [
            "Coding languages: Select every language you can read and understand so DigitVA routes matching interviews to your coding queue.",
            "Passkey sign-in: Register a device passkey (fingerprint, face unlock, or screen lock) for one-tap passwordless sign-in.",
            "Personal details: Keep your job title, phone number, and time zone up to date.",
        ],
        "sections": [
            {
                "heading": "Keeping Your Coding Languages Updated",
                "items": [
                    "Medical Officers and Reviewers only receive cases narrated in languages they have checked in their profile.",
                    "After ticking your languages, click Save so your coding queue immediately reflects your language skills.",
                ],
            },
            {
                "heading": "Setting Up Fast Passkey Login",
                "items": [
                    "In the Passkeys card, click 'Add a passkey' to link this phone or laptop for instant biometric sign-in.",
                ],
            },
        ],
        "help_slug": "/help/profile",
        "help_label": "My Profile Guide",
    },
    "admin": {
        "page_key": "admin",
        "stage_badge": "Administration · Projects & System",
        "title": "Project & System Administration",
        "summary": "Configure projects, health facility trees, ODK sync connections, ICD vocabularies, and mentoring institutions.",
        "bullets": [
            "Left navigation console: Switch between Projects, Organization hierarchy, Access Grants, Project Sites, and Mentoring Institutes.",
            "Clinical & form configuration: Manage Project Forms, ICD-10/ICD-11 browsers, COD buckets, and instrument translations.",
            "Operations & health: Monitor ODK data sync, attachments, system activity logs, and TLS certificate health.",
        ],
        "sections": [
            {
                "heading": "Managing Projects, Facilities & Grants",
                "items": [
                    "Use 'Organization' and 'Access Grants' to configure the District → Block → PHC → Sub-Centre tree and assign 'Within Area' or 'All' roles.",
                    "Use 'Mentoring institutes' to register partner medical colleges and link them to supported districts.",
                ],
            },
            {
                "heading": "Coding Catalogues & Data Sync",
                "items": [
                    "Use the ICD-10, ICD-11, and COD Buckets panels to inspect selectable cause-of-death codes and reporting mappings.",
                    "Use 'Data Sync' and 'System health' to monitor automated background synchronisation and server status.",
                ],
            },
        ],
        "help_slug": "/help/admin-overview",
        "help_label": "Admin Overview Guide",
    },
    "admin_projects": {
        "page_key": "admin_projects",
        "stage_badge": "Admin · Projects",
        "title": "Project Directory & Status",
        "summary": "Create and manage mortality surveillance projects, intake workflows, and project configurations.",
        "bullets": [
            "Project directory: View all active and archived surveillance projects, their intake workflow mode, and assigned forms.",
            "Create or edit projects: Set up a new district or state project with its unique project code and display name.",
            "Quick setup access: Open any project's Setup page to configure death registration, self-coding, and facility hierarchy levels.",
        ],
        "sections": [
            {
                "heading": "Creating & Organising Projects",
                "items": [
                    "Click 'New Project' to register a surveillance project and choose whether field workers use web/app intake or ODK Central sync.",
                    "Click 'Setup' on any project row to configure its workflow rules, coding allocation mode, and organization levels.",
                ],
            },
            {
                "heading": "Archiving & Governance",
                "items": [
                    "Active projects appear in field worker, medical officer, and data manager workspaces according to user role grants.",
                    "Keep project names clear so multi-project users can easily distinguish their assigned programmes.",
                ],
            },
        ],
        "help_slug": "/help/projects",
        "help_label": "Projects Guide",
    },
    "admin_project-setup": {
        "page_key": "admin_project-setup",
        "stage_badge": "Admin · Project Setup",
        "title": "Project Setup & Workflow Rules",
        "summary": "Configure a project's death register requirement, self-coding mode, coding allocation mode, and organization levels.",
        "bullets": [
            "Intake & registration rules: Choose whether deaths must be registered before an interview or if interviewers can start directly.",
            "Coding workflow rules: Enable or disable Medical Officer self-coding (MO as Coder) and choose random vs pick allocation.",
            "Hierarchy levels: Define the administrative/facility levels (e.g., District → Block → PHC → Sub-Centre) used for Within Area access.",
        ],
        "sections": [
            {
                "heading": "Intake & Coding Modes",
                "items": [
                    "Enable 'Require Death Registration' when ASHA/ANM death notifications should precede CHO/Nurse verbal autopsy interviews.",
                    "Enable 'Self-Coding' if Medical Officers in this project conduct or review interviews and immediately assign the cause of death.",
                ],
            },
            {
                "heading": "Organization Hierarchy Levels",
                "items": [
                    "Configure level codes and labels before importing or building the project's health facility tree.",
                    "Ensure the coding classification (ICD-10 or ICD-11) and DORIS/SmartVA assistants match your study protocol.",
                ],
            },
        ],
        "help_slug": "/help/projects",
        "help_label": "Projects Guide",
    },
    "admin_organization": {
        "page_key": "admin_organization",
        "stage_badge": "Admin · Health Hierarchy",
        "title": "Facility & Unit Hierarchy Tree",
        "summary": "Build and edit the District → Block/CHC → PHC → Sub-Centre health facility tree for each project.",
        "bullets": [
            "Hierarchical facility tree: Organise health units from District down to Block/CHC, PHC/AAM, and Sub-Centre/Ward.",
            "Drives Within Area visibility: A user granted access at a parent unit (e.g., Block or PHC) automatically covers all child units beneath it.",
            "Import or edit inline: Add new units, rename facilities, or bulk-import the hierarchy from a structured spreadsheet.",
        ],
        "sections": [
            {
                "heading": "Building the Facility Tree",
                "items": [
                    "Select a project at the top to view its organization levels and expandable unit tree.",
                    "Add child units under any parent node to mirror your real-world district health reporting structure.",
                ],
            },
            {
                "heading": "How Hierarchy Controls Data Scope",
                "items": [
                    "Deaths and interviews recorded at a Sub-Centre roll up automatically to its parent PHC, Block, and District.",
                    "Verify unit codes match any facility codes used in field forms so submissions route to the right area.",
                ],
            },
        ],
        "help_slug": "/help/user-roles",
        "help_label": "User Roles & Areas Guide",
    },
    "admin_access-grants": {
        "page_key": "admin_access-grants",
        "stage_badge": "Admin · Access Control",
        "title": "User Role Grants & Within Area Scope",
        "summary": "Assign health workers, medical officers, and mentors to roles with Within Area or All coverage.",
        "bullets": [
            "Role-based access: Grant Death Reporter, Interviewer, Interview Supervisor, Coder, Reviewer, or Data Manager permissions.",
            "Within Area vs All: Scope a grant to a specific facility/subtree ('Within Area') or across the entire project ('All').",
            "Audit-ready management: Review existing grants by project, user, or health unit and revoke outdated assignments cleanly.",
        ],
        "sections": [
            {
                "heading": "Granting Within Area vs All Access",
                "items": [
                    "Choose an organization unit (such as a PHC or Block) to restrict the user's queue and dashboard to that facility and its child units.",
                    "Choose project-wide scope ('All') for District Programme Managers, Senior Reviewers, or Medical College Mentors who support the entire project.",
                ],
            },
            {
                "heading": "Best Practices for Role Assignments",
                "items": [
                    "A single user can hold multiple roles (for example, Interview Supervisor and Coder) within the same project.",
                    "For Coders and Reviewers, also confirm their spoken/reading languages are ticked in Users or My Profile.",
                ],
            },
        ],
        "help_slug": "/help/dm-grants",
        "help_label": "Access Grants Guide",
    },
    "admin_project-sites": {
        "page_key": "admin_project-sites",
        "stage_badge": "Admin · Project Sites",
        "title": "Study Sites & Field Workspaces",
        "summary": "Link master health facilities/sites to projects and configure site-level settings.",
        "bullets": [
            "Project-to-site binding: Connect master sites to a surveillance project so field teams can register deaths and submit interviews.",
            "Web & mobile intake mode: Configure whether each linked site uses death registration, verbal autopsy interviews, or both.",
            "Site-level oversight: Associate site leaders and verify active submission counts per linked site.",
        ],
        "sections": [
            {
                "heading": "Linking Sites to a Project",
                "items": [
                    "Select the target project and attach one or more sites from the master Sites registry.",
                    "Configure the intake mode so field workers see the appropriate registration and interview actions.",
                ],
            },
            {
                "heading": "Coordinating With the Organization Tree",
                "items": [
                    "When a project uses a full District → Block → PHC → Sub-Centre hierarchy, the system automatically manages internal site containers.",
                    "Use this panel when adding standalone study sites or adjusting site-specific intake rules.",
                ],
            },
        ],
        "help_slug": "/help/sites",
        "help_label": "Sites Guide",
    },
    "admin_mentor-institutes": {
        "page_key": "admin_mentor-institutes",
        "stage_badge": "Admin · Medical Colleges",
        "title": "Mentoring Medical Institutions",
        "summary": "Register partner medical colleges, link them to supported districts, and designate Institute Admins.",
        "bullets": [
            "Medical college registry: Maintain partner Community Medicine / PSM departments and mentoring institutions.",
            "District & project links: Connect each mentoring institute to the surveillance projects and districts it supports.",
            "Institute Admins & Faculty: Designate Institute Admins who can coordinate faculty reviewers, senior residents, and coding quality.",
        ],
        "sections": [
            {
                "heading": "Registering & Linking an Institute",
                "items": [
                    "Create a mentoring institute record with its institution code, name, and state/district location.",
                    "Link the institute to one or more projects so faculty mentors can oversee clinical coding quality.",
                ],
            },
            {
                "heading": "Assigning Institute Administrators",
                "items": [
                    "Add faculty members as Institute Admins or Mentors so they can access the Mentoring Portal.",
                    "Mentors can inspect coding concordance, DORIS agreement, and narrative quality across their linked areas.",
                ],
            },
        ],
        "help_slug": "/help/mentoring-institutes",
        "help_label": "Mentoring Institutes Guide",
    },
    "admin_project-forms": {
        "page_key": "admin_project-forms",
        "stage_badge": "Admin · Questionnaires",
        "title": "Verbal Autopsy Questionnaires",
        "summary": "Bind WHO Verbal Autopsy questionnaire versions and manage form configurations for each project.",
        "bullets": [
            "WHO 2022 VA instruments: View and bind standardized Verbal Autopsy questionnaire definitions to each project.",
            "Version pinning: Ensure in-progress interviews stay locked to the form version they started with while new interviews use the active release.",
            "ODK & web parity: Align form IDs and versions across mobile offline collection, web intake, and ODK Central sync.",
        ],
        "sections": [
            {
                "heading": "Managing Project Questionnaires",
                "items": [
                    "Check which questionnaire version is currently active for each project before launching field collection.",
                    "Verify form bindings whenever upgrading a project to a new WHO Verbal Autopsy instrument revision.",
                ],
            },
            {
                "heading": "Field & Sync Compatibility",
                "items": [
                    "Bound forms automatically determine the skip logic, age-group routing, and field mappings used in the coding workspace.",
                    "Coordinate form version updates with Instrument Translations so field interviewers see complete local-language prompts.",
                ],
            },
        ],
        "help_slug": "/help/data-collection",
        "help_label": "Data Collection Guide",
    },
    "admin_project-pi": {
        "page_key": "admin_project-pi",
        "stage_badge": "Admin · Governance",
        "title": "Project Principal Investigators (PIs)",
        "summary": "Assign and manage Principal Investigators with project-wide oversight.",
        "bullets": [
            "Project-wide leadership: Principal Investigators hold oversight across all sites and health units in their assigned project.",
            "Multi-site monitoring: PIs can review operational progress, coding completion, and cause-of-death distributions.",
            "Clean delegation: Add or remove Project PI assignments as study leadership evolves.",
        ],
        "sections": [
            {
                "heading": "Assigning a Project PI",
                "items": [
                    "Select a project and choose an existing user account to grant Project PI oversight.",
                    "Project PIs can access the Site PI & Project Oversight dashboard for their assigned projects.",
                ],
            },
            {
                "heading": "Difference Between Project PI & Data Manager",
                "items": [
                    "Project PIs focus on scientific and programmatic oversight across the project.",
                    "Data Managers handle day-to-day operational queues, user role grants, and pipeline troubleshooting.",
                ],
            },
        ],
        "help_slug": "/help/user-roles",
        "help_label": "User Roles & Areas Guide",
    },
    "admin_sites": {
        "page_key": "admin_sites",
        "stage_badge": "Admin · Facility Registry",
        "title": "Master Sites Registry",
        "summary": "Maintain the master list of study sites and facilities shared across projects.",
        "bullets": [
            "Central facility catalog: Create and maintain site codes, names, and geographic metadata.",
            "Reusable across projects: Master sites can be linked to one or more surveillance projects in the Project Sites panel.",
            "Site PI assignment: Associate local Site Principal Investigators or Facility In-charges with specific study sites.",
        ],
        "sections": [
            {
                "heading": "Adding & Updating Master Sites",
                "items": [
                    "Use consistent, human-readable site codes and names so field workers and analysts can identify facilities immediately.",
                    "After creating a site here, link it to a project under 'Project Sites' or manage fine-grained units under 'Organization'.",
                ],
            },
            {
                "heading": "Maintaining Clean Identifiers",
                "items": [
                    "Avoid renaming active site codes mid-study if external ODK forms reference the site code directly.",
                    "Update display labels and contact details anytime as facility teams change.",
                ],
            },
        ],
        "help_slug": "/help/sites",
        "help_label": "Sites Guide",
    },
    "admin_users": {
        "page_key": "admin_users",
        "stage_badge": "Admin · User Accounts",
        "title": "User Accounts & Sign-In Security",
        "summary": "Create and manage user accounts, coding languages, sign-in codes, password resets, and session revocations.",
        "bullets": [
            "Account provisioning: Create accounts for ASHAs, ANMs, CHOs, Medical Officers, Reviewers, Mentors, and Data Managers.",
            "Coding language skills: Assign the languages each Coder or Reviewer can read so their queue only shows matching narratives.",
            "Sign-in help & security: Generate one-time sign-in codes, reset passwords, unlock accounts, or revoke active device sessions.",
        ],
        "sections": [
            {
                "heading": "Onboarding Field Workers & Clinicians",
                "items": [
                    "Create the user account here first, then assign their project role and Within Area / All scope under 'Access Grants'.",
                    "For Coders and Reviewers, always tick their narrative languages so eligible cases appear in their queue.",
                ],
            },
            {
                "heading": "Supporting Field Sign-In & Security",
                "items": [
                    "Issue a short-lived sign-in code when a field worker is setting up the mobile app or cannot receive email.",
                    "Use 'Revoke sessions' or deactivate an account immediately when a staff member leaves the programme.",
                ],
            },
        ],
        "help_slug": "/help/users",
        "help_label": "Users Guide",
    },
    "admin_languages": {
        "page_key": "admin_languages",
        "stage_badge": "Admin · Languages",
        "title": "System & Coding Languages",
        "summary": "Configure languages available for interviews, narratives, and medical officer coding.",
        "bullets": [
            "Language registry: Manage the list of languages supported for verbal autopsy narratives and questionnaire display.",
            "Queue routing key: Each submission's narrative language is matched against Medical Officers' language profiles.",
            "Local script support: Enable regional languages (such as Hindi, Odia, Tamil, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati, or English).",
        ],
        "sections": [
            {
                "heading": "Adding & Enabling Languages",
                "items": [
                    "Register each language with its standard ISO code and clear display name.",
                    "Once enabled, the language can be selected on user profiles and during interview capture.",
                ],
            },
            {
                "heading": "How Languages Affect Coding Queues",
                "items": [
                    "A case narrated in a regional language is only offered to Coders and Reviewers who have that language enabled.",
                    "Check the DM KPI Language Readiness tab to ensure every active narrative language has enough qualified coders.",
                ],
            },
        ],
        "help_slug": "/help/admin-overview",
        "help_label": "Admin Overview Guide",
    },
    "admin_odk-connections": {
        "page_key": "admin_odk-connections",
        "stage_badge": "Admin · ODK Central",
        "title": "ODK Central Connections",
        "summary": "Configure ODK Central server endpoints and credentials for form synchronisation.",
        "bullets": [
            "Server credentials: Store the base URL and service account credentials for external ODK Central servers.",
            "Connection guard: Test connectivity and verify TLS/authentication health before enabling automated sync.",
            "Project binding: Link ODK Central projects and forms to DigitVA surveillance projects.",
        ],
        "sections": [
            {
                "heading": "Configuring an ODK Connection",
                "items": [
                    "Enter the ODK Central server URL and dedicated sync account credentials, then run a connection check.",
                    "Ensure the ODK service account has permission to read submissions and media attachments for the target form.",
                ],
            },
            {
                "heading": "Safety & Connection Guard",
                "items": [
                    "DigitVA's connection guard prevents accidental cross-environment writes and pauses sync if credentials fail.",
                    "After saving connection settings, monitor synchronization runs in the 'Data Sync' panel.",
                ],
            },
        ],
        "help_slug": "/help/odk-sync",
        "help_label": "ODK Sync Guide",
    },
    "admin_field-mapping": {
        "page_key": "admin_field-mapping",
        "stage_badge": "Admin · Schema Mapping",
        "title": "Form Field & Variable Mapping",
        "summary": "Inspect and manage mappings between questionnaire fields and standardized DigitVA variables.",
        "bullets": [
            "Clinical display groups: Map raw questionnaire fields into logical clinical categories (Demographics, History, Symptoms, Narrative).",
            "Cross-version consistency: Normalise field paths across WHO 2016, WHO 2022, and project-specific form adaptations.",
            "Visibility & rendering rules: Control how answers, units, and highlighted red-flag symptoms appear in the coding workspace.",
        ],
        "sections": [
            {
                "heading": "Inspecting & Updating Field Mappings",
                "items": [
                    "Filter by form version or clinical category to see how each question maps to the coding workspace.",
                    "Verify that key identifiers (deceased age, sex, date of death, and narrative language) map to their canonical variables.",
                ],
            },
            {
                "heading": "When to Adjust Mappings",
                "items": [
                    "Review field mappings whenever introducing a custom project form or adding local extension questions.",
                    "Changes here update how case summaries render for Medical Officers without altering raw submission data.",
                ],
            },
        ],
        "help_slug": "/help/field-mapping",
        "help_label": "Field Mapping Guide",
    },
    "admin_cod-buckets": {
        "page_key": "admin_cod-buckets",
        "stage_badge": "Admin · Mortality Analytics",
        "title": "Cause-of-Death Buckets",
        "summary": "Group ICD-10 and ICD-11 codes into public-health mortality reporting buckets.",
        "bullets": [
            "Public-health aggregation: Map individual ICD-10 and ICD-11 codes into broad epidemiological cause buckets.",
            "Age-band specific trees: Configure separate reporting hierarchies for Neonatal, Child, and Adult deaths.",
            "Powers COD dashboards: Directly drives the Cause-of-Death Bucket Reporting charts and CSV exports.",
        ],
        "sections": [
            {
                "heading": "Managing Reporting Schemes & Buckets",
                "items": [
                    "Select a reporting scheme and age band to inspect its bucket hierarchy and mapped ICD codes.",
                    "Check unmapped code counts to ensure newly used ICD codes are assigned to an appropriate public-health bucket.",
                ],
            },
            {
                "heading": "Exporting & Auditing Mappings",
                "items": [
                    "Publicly active schemes can also be browsed and downloaded as CSV from the Help Centre.",
                    "Keep bucket definitions aligned with ICMR, WHO, or state mortality surveillance reporting standards.",
                ],
            },
        ],
        "help_slug": "/help/cod-buckets",
        "help_label": "COD Buckets Guide",
    },
    "admin_icd10-browser": {
        "page_key": "admin_icd10-browser",
        "stage_badge": "Admin · Clinical Coding",
        "title": "ICD-10 2019 Mortality Browser",
        "summary": "Browse and search the WHO ICD-10 classification used for cause-of-death coding.",
        "bullets": [
            "WHO ICD-10 2019 hierarchy: Navigate chapters, blocks, and three-/four-character cause-of-death codes.",
            "Allowability & restrictions: Inspect which codes are selectable for underlying cause of death and check age/sex restrictions.",
            "WHO VA mapping status: View how each ICD-10 code maps to WHO Verbal Autopsy cause categories.",
        ],
        "sections": [
            {
                "heading": "Searching & Navigating ICD-10",
                "items": [
                    "Expand any chapter or use the search box to look up a code or clinical condition.",
                    "Click any node to inspect its parent chain, coding notes, and age/sex eligibility rules.",
                ],
            },
            {
                "heading": "Understanding Selectable Codes",
                "items": [
                    "Codes marked active/selectable can be chosen by Medical Officers and Reviewers in ICD-10 projects.",
                    "Ill-defined or mode-of-dying codes that WHO guidelines discourage for underlying cause are clearly flagged.",
                ],
            },
        ],
        "help_slug": "/help/icd-codes",
        "help_label": "ICD Codes Guide",
    },
    "admin_icd11-browser": {
        "page_key": "admin_icd11-browser",
        "stage_badge": "Admin · Clinical Coding",
        "title": "ICD-11 MMS Mortality Browser",
        "summary": "Browse and search the WHO ICD-11 Mortality and Morbidity Statistics classification.",
        "bullets": [
            "WHO ICD-11 MMS tree: Explore chapters, blocks, and stem codes used in ICD-11 verbal autopsy coding.",
            "Crosswalk & VA mappings: See how ICD-11 entities align with WHO Verbal Autopsy mortality groups and ICD-10 equivalents.",
            "Clinical coding reference: Verify code definitions, inclusions, and exclusions used by DORIS and Medical Officers.",
        ],
        "sections": [
            {
                "heading": "Exploring the ICD-11 Hierarchy",
                "items": [
                    "Browse from top-level chapters down to specific stem codes or search by code/clinical title.",
                    "Select any code to view its detailed lineage, WHO VA mapping status, and reporting bucket assignment.",
                ],
            },
            {
                "heading": "Using ICD-11 in Projects",
                "items": [
                    "Projects configured for ICD-11 use this catalogue in the coding workspace and DORIS clinical assistant.",
                    "Compare ICD-10 and ICD-11 coverage anytime in the Help Centre's interactive ICD reference pages.",
                ],
            },
        ],
        "help_slug": "/help/icd-codes",
        "help_label": "ICD Codes Guide",
    },
    "admin_icd-search-vocabulary": {
        "page_key": "admin_icd-search-vocabulary",
        "stage_badge": "Admin · Search Index",
        "title": "ICD Search Vocabulary & Synonyms",
        "summary": "Manage clinical search terms, synonyms, and local medical aliases for fast ICD lookup.",
        "bullets": [
            "Faster physician lookup: Add common clinical abbreviations, regional medical terms, and synonyms to ICD codes.",
            "Improves coding accuracy: Helps Medical Officers find the right ICD-10 or ICD-11 code even when typing informal clinical phrasing.",
            "Curated index: Review and refine search keywords without changing official WHO code titles.",
        ],
        "sections": [
            {
                "heading": "Adding Synonyms & Search Aliases",
                "items": [
                    "Search for a target ICD code and inspect the index terms currently linked to it.",
                    "Add common abbreviations or colloquial clinical terms used by physicians in your region.",
                ],
            },
            {
                "heading": "Maintaining Search Quality",
                "items": [
                    "Keep synonyms specific so search results stay focused and clinically accurate.",
                    "Updated search terms take effect immediately in the Coding and Review workspaces.",
                ],
            },
        ],
        "help_slug": "/help/icd-codes",
        "help_label": "ICD Codes Guide",
    },
    "admin_va-definitions": {
        "page_key": "admin_va-definitions",
        "stage_badge": "Admin · WHO Codebook",
        "title": "WHO VA Question & Variable Definitions",
        "summary": "Reference codebook of WHO Verbal Autopsy questions, skip logic, and variable definitions.",
        "bullets": [
            "Complete question catalog: Inspect every WHO Verbal Autopsy question ID, prompt text, answer type, and choice list.",
            "Skip logic & relevance: View the exact relevance conditions that control when a question is asked during an interview.",
            "Standardized reference: Helps data managers and researchers cross-check raw variables against WHO 2022 documentation.",
        ],
        "sections": [
            {
                "heading": "Browsing the WHO VA Codebook",
                "items": [
                    "Search by question ID (e.g., Id10007), variable name, or keyword to inspect its definition and answer options.",
                    "Review relevance expressions to understand why certain questions appear only for neonates, children, or adults.",
                ],
            },
            {
                "heading": "Using Definitions for Quality & Analysis",
                "items": [
                    "Use this reference when designing quality checks, reviewing field mappings, or preparing analysis scripts.",
                    "Downloadable form matrices are also available in the Data Collection Help Guide.",
                ],
            },
        ],
        "help_slug": "/help/data-collection",
        "help_label": "Data Collection Guide",
    },
    "admin_instrument-translations": {
        "page_key": "admin_instrument-translations",
        "stage_badge": "Admin · Vernacular Survey",
        "title": "Questionnaire Instrument Translations",
        "summary": "Manage and approve local-language translations for WHO Verbal Autopsy questionnaire items.",
        "bullets": [
            "Multilingual questionnaires: Maintain translated labels, hints, and answer choices for every supported interview language.",
            "Review field suggestions: Inspect and approve wording improvements proposed by field coordinators.",
            "Live device sync: Published translations are automatically delivered to web and mobile interviewers.",
        ],
        "sections": [
            {
                "heading": "Managing Questionnaire Translations",
                "items": [
                    "Select a questionnaire version and target language to view or edit translated question prompts and hints.",
                    "Filter for untranslated or pending items to ensure 100% coverage before field deployment.",
                ],
            },
            {
                "heading": "Publishing to Field Devices",
                "items": [
                    "Once saved and approved, updated translations sync automatically when interviewers refresh the app.",
                    "Keep wording natural, respectful, and faithful to the clinical meaning of the original WHO question.",
                ],
            },
        ],
        "help_slug": "/help/data-collection",
        "help_label": "Data Collection Guide",
    },
    "admin_ui-strings": {
        "page_key": "admin_ui-strings",
        "stage_badge": "Admin · App Localisation",
        "title": "Web & Mobile UI Strings",
        "summary": "Edit translated app labels and messages across languages without requiring a new app build.",
        "bullets": [
            "Interface localisation: Manage translated button labels, navigation titles, and status messages across the app.",
            "Over-the-air updates: Refinements saved here update web and mobile screens without needing a new APK install.",
            "Consistent terminology: Keep role names and workflow terms uniform across English, Hindi, and regional languages.",
        ],
        "sections": [
            {
                "heading": "Editing App Labels & Messages",
                "items": [
                    "Search by string key or English text to locate any button, heading, or message shown in the app.",
                    "Enter or refine the target language text and save to publish the update.",
                ],
            },
            {
                "heading": "Preserving Placeholders",
                "items": [
                    "If an English string contains placeholders like {count} or {name}, keep the exact placeholder names in your translation.",
                    "Use 'Instrument Translations' for survey questions and 'UI Strings' for app buttons and menus.",
                ],
            },
        ],
        "help_slug": "/help/admin-overview",
        "help_label": "Admin Overview Guide",
    },
    "admin_sync": {
        "page_key": "admin_sync",
        "stage_badge": "Admin · Data Pipeline",
        "title": "Data Sync & Ingestion Status",
        "summary": "Monitor background synchronisation jobs, trigger manual syncs, and inspect sync logs.",
        "bullets": [
            "Pipeline monitoring: Track automated and manual synchronisation runs between ODK Central and DigitVA.",
            "Submission ingestion: See how many new interviews, updates, and attachments were imported in each sync cycle.",
            "Error diagnosis: Inspect detailed error logs and repair quarantined or incomplete submissions.",
        ],
        "sections": [
            {
                "heading": "Running & Monitoring Sync Jobs",
                "items": [
                    "Review the latest sync timestamp, status badge, and record counts for each connected project.",
                    "Use 'Trigger Sync' when you need to pull newly uploaded field submissions immediately.",
                ],
            },
            {
                "heading": "Troubleshooting Sync Exceptions",
                "items": [
                    "If a run reports warnings or failed records, expand the run log to see the exact submission ID and reason.",
                    "Verify ODK Central connectivity in 'ODK Connections' if a server is unreachable.",
                ],
            },
        ],
        "help_slug": "/help/odk-sync",
        "help_label": "ODK Sync Guide",
    },
    "admin_attachments": {
        "page_key": "admin_attachments",
        "stage_badge": "Admin · Storage",
        "title": "Media & Audio Attachments",
        "summary": "Inspect and manage audio narrative recordings and form media attachments.",
        "bullets": [
            "Audio narrative verification: Track voice recordings and media files attached to verbal autopsy submissions.",
            "Download & sync status: Check which attachments are stored locally and retry any pending media downloads.",
            "Secure clinical playback: Ensure audio files are intact so Medical Officers and Reviewers can listen during coding.",
        ],
        "sections": [
            {
                "heading": "Checking Attachment Health",
                "items": [
                    "Filter by project or sync status to see whether any submission is waiting for its audio recording.",
                    "Retry failed attachment downloads so coders have both the written narrative and voice recording.",
                ],
            },
            {
                "heading": "Privacy & Access Control",
                "items": [
                    "Audio narratives may contain sensitive family details and are streamed only to authorised users in scope.",
                    "Monitor storage usage and verify media retention rules align with your study protocol.",
                ],
            },
        ],
        "help_slug": "/help/admin-overview",
        "help_label": "Admin Overview Guide",
    },
    "admin_activity": {
        "page_key": "admin_activity",
        "stage_badge": "Admin · Security Audit",
        "title": "System Activity & Audit Log",
        "summary": "Review the audit trail of sign-ins, role grant changes, and administrative actions.",
        "bullets": [
            "Complete audit trail: Track sign-ins, role grant updates, project configuration changes, and data exports.",
            "Filter by user or event: Quickly investigate when an account, permission, or project setting was modified.",
            "Governance & compliance: Supports institutional review board (IRB) and programme security audits.",
        ],
        "sections": [
            {
                "heading": "Inspecting Audit Events",
                "items": [
                    "Filter by date range, actor, or action type to trace administrative changes across the system.",
                    "Each log entry records the timestamp, acting user, target resource, and change summary.",
                ],
            },
            {
                "heading": "Security Monitoring",
                "items": [
                    "Review unusual sign-in attempts or permission changes and revoke sessions in the 'Users' panel if needed.",
                    "Case-level coding and review transitions are also tracked in each case's workflow history.",
                ],
            },
        ],
        "help_slug": "/help/admin-overview",
        "help_label": "Admin Overview Guide",
    },
    "admin_system-health": {
        "page_key": "admin_system-health",
        "stage_badge": "Admin · Infrastructure",
        "title": "System Health & TLS Certificates",
        "summary": "Monitor database, background worker, and TLS certificate expiration status.",
        "bullets": [
            "Infrastructure status: Check database connectivity, background task queues, and server readiness.",
            "TLS certificate monitor: View remaining validity days for HTTPS certificates across DigitVA and connected endpoints.",
            "Site maintenance controls: Manage scheduled maintenance windows and active session grace periods.",
        ],
        "sections": [
            {
                "heading": "Monitoring Certificates & Services",
                "items": [
                    "Check TLS certificate status regularly and renew certificates well before expiration to avoid field sync interruptions.",
                    "Verify background workers are healthy so SmartVA, DORIS, and ODK sync jobs run on schedule.",
                ],
            },
            {
                "heading": "Planned Maintenance Windows",
                "items": [
                    "When enabling site maintenance mode, active users receive a countdown banner so they can save their work safely.",
                    "Administrators remain able to sign in during maintenance to verify upgrades and re-open the site.",
                ],
            },
        ],
        "help_slug": "/help/system-health",
        "help_label": "System Health Guide",
    },
}


def get_contextual_help(page_key: str | None) -> dict | None:
    """Return a copy of the contextual help entry for page_key, or None if unknown."""
    if not page_key:
        return None
    entry = CONTEXTUAL_HELP_PAGES.get(page_key)
    if entry is None:
        return None
    return copy.deepcopy(entry)


def list_contextual_help() -> dict[str, dict]:
    """Return a copy of all contextual help entries keyed by page_key."""
    return copy.deepcopy(CONTEXTUAL_HELP_PAGES)


def resolve_flask_page_key(
    endpoint: str | None,
    path: str | None,
    panel: str | None = None,
) -> str | None:
    """Resolve the current Flask request endpoint/path/panel to a contextual help page_key."""
    clean_path = (path or "").strip()
    clean_endpoint = (endpoint or "").strip()

    if clean_path.startswith(("/help", "/vaauth")) or clean_endpoint.startswith(("help.", "va_auth.")):
        return None

    if clean_endpoint == "data_management.kpi_dashboard" or clean_path.startswith("/data-management/kpi"):
        return "dmKpi"
    if clean_endpoint == "data_management.cod_bucket_reporting" or clean_path.startswith("/data-management/cod-buckets"):
        return "codBuckets"
    if clean_endpoint.startswith("data_management.") or clean_path.startswith("/data-management"):
        return "dataManagement"

    if clean_endpoint.startswith("area.") or clean_path.startswith("/area"):
        return "area"
    if clean_endpoint.startswith("sitepi.") or clean_path.startswith("/sitepi"):
        return "sitepi"
    if clean_endpoint.startswith("people_roles_page.") or clean_path.startswith("/people-roles"):
        return "peopleRoles"
    if clean_endpoint.startswith("translation_suggestions_page.") or clean_path.startswith("/translation-suggestions"):
        return "translations"
    if clean_endpoint.startswith("profile.") or clean_path.startswith("/profile"):
        return "profile"
    if clean_endpoint.startswith("admin.") or clean_path.startswith("/admin"):
        candidate = (panel or clean_path).strip()
        if "/admin/panels/" in candidate:
            slug = candidate.split("/admin/panels/", 1)[1].strip("/").split("/")[0]
            panel_key = f"admin_{slug}"
            if panel_key in CONTEXTUAL_HELP_PAGES:
                return panel_key
        return "admin"

    if clean_endpoint == "coding.dashboard":
        return "coding"
    if clean_endpoint.startswith("coding."):
        return "caseCoding"
    if clean_endpoint == "reviewing.dashboard":
        return "reviewing"
    if clean_endpoint.startswith("reviewing."):
        return "caseReviewing"

    if clean_endpoint == "intake.new_death_page":
        return "deathRegistration"
    if clean_endpoint == "intake.supervision_page":
        return "supervision"
    if clean_endpoint == "intake.interview_page":
        return "interview"
    if clean_endpoint.startswith("intake."):
        return "collection"

    if clean_endpoint == "va_main.va_index" or clean_path in ("/", "/index"):
        return "home"

    return None
