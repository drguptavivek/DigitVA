"""Build the Lancet Digital Health version of the DigitVA manuscript.

Run with a Python that has python-docx, from the repository root:
    /Users/vivekgupta/.codex/.venv/bin/python scripts/build_digitva_ldh_manuscript.py

Figures come from the dev database, data cut-off 31 May 2026. The data sheet and
Stata analysis that reproduce them are in scripts/stata (see its README); rerun them
before submission.
"""
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_digitva_npj_manuscript import (  # noqa: E402  reuse the field helpers
    add_bullet,
    add_page_number,
    add_paragraph,
    add_table,
    add_zotero_bibliography,
    add_zotero_citation,
)

OUT = Path("docs/manuscript/DigitVA_LDH_Manuscript.docx")

# Zotero keys (user library 337745). An item marked None is not in Zotero: it is cited
# as plain text and must be imported, then linked, before Zotero Refresh.
REFS = [
    ("ASYNVIF5", "Office of the Registrar General and Census Commissioner, India. Report on medical certification of cause of death 2023. New Delhi: Ministry of Home Affairs, 2025."),
    ("VR8CCH6N", "Mikkelsen L, Phillips DE, AbouZahr C, et al. A global assessment of civil registration and vital statistics systems: monitoring data quality and progress. Lancet 2015; 386: 1395–406."),
    ("SJLJFQEM", "Nichols EK, Byass P, Chandramohan D, et al. The WHO 2016 verbal autopsy instrument: an international standard suitable for automated analysis by InterVA, InSilicoVA, and Tariff 2.0. PLoS Med 2018; 15: e1002486."),
    ("M34P3RLJ", "Serina P, Riley I, Stewart A, et al. A shortened verbal autopsy instrument for use in routine mortality surveillance systems. BMC Med 2015; 13: 302."),
    ("26YTFYJN", "Thomas LM, D'Ambruoso L, Balabanova D. Verbal autopsy in health policy and systems: a literature review. BMJ Glob Health 2018; 3: e000639."),
    ("Z23KHMG7", "Hazard RH, Buddhika MPK, Hart JD, et al. Automated verbal autopsy: from research to routine use in civil registration and vital statistics systems. BMC Med 2020; 18: 60."),
    ("LW5TMTEX", "Joshi R, Hazard RH, Mahesh PKB, et al. Improving cause of death certification in the Philippines: implementation of an electronic verbal autopsy decision support tool (SmartVA auto-analyse) to aid physician diagnoses of out-of-facility deaths. BMC Public Health 2021; 21: 563."),
    ("BIEQ75U2", "Reeve M, Chowdhury H, Mahesh PKB, et al. Generating cause of death information to inform health policy: implementation of an automated verbal autopsy system in the Solomon Islands. BMC Public Health 2021; 21: 2080."),
    ("2CMAM96L", "Flaxman AD, Stewart A, Joseph JC, et al. Collecting verbal autopsies: improving and streamlining data collection processes using electronic tablets. Popul Health Metr 2018; 16: 3."),
    ("2Y48HNZL", "Li ZR, Thomas J, Choi E, McCormick TH, Clark SJ. The openVA toolkit for verbal autopsies. R J 2022; 14: 316–34."),
    ("GW7XT3RM", "Lyatuu I, Odhiambo C, Mrema S, et al. Verbal Autopsy Manager (VMan3): a comprehensive software tool for managing and improving quality, availability and use of cause of death data from community deaths. medRxiv 2025; published online May 29. https://doi.org/10.1101/2025.05.28.25328220 (preprint)."),
    ("8AB46D42", "Kaur H, Tripathi S, Chalga MS, et al. Unified mobile app for streamlining verbal autopsy and cause of death assignment in India: design and development study. JMIR Form Res 2025; 9: e59937."),
    ("XX42INSZ", "Krishnan A, Gupta V, Nongkynrih B, et al. Mortality in India established through verbal autopsies (MINErVA): strengthening national mortality surveillance system in India. J Glob Health 2020; 10: 020431."),
    ("TP5HNVXL", "Benara SK, Sharma S, Juneja A, et al. Evaluation of methods for assigning causes of death from verbal autopsies in India. Front Big Data 2023; 6: 1197471."),
    ("7GC7MJ2S", "Leitao J, Desai N, Aleksandrowicz L, et al. Comparison of physician-certified verbal autopsy with computer-coded verbal autopsy for cause of death assignment in hospitalized patients in low- and middle-income countries: systematic review. BMC Med 2014; 12: 22."),
    ("FR46I58N", "Perrin Franck C, Babington-Ashaye A, Dietrich D, et al. iCHECK-DH: guidelines and checklist for the reporting on digital health implementations. J Med Internet Res 2023; 25: e46694."),
    ("N6NRDDK8", "Serina P, Riley I, Stewart A, et al. Improving performance of the Tariff Method for assigning causes of death to verbal autopsies. BMC Med 2015; 13: 291."),
    ("WZB5UKME", "WHO. ICD-11 for mortality and morbidity statistics. Geneva: World Health Organization. https://icd.who.int/browse/en (accessed Nov 6, 2026)."),
    ("549BPWEY", "Tunga M, Lungo JH, Chambua J, Kateule R, Lyatuu I. Exploring challenges and recommendations for verbal autopsy implementation in low-/middle-income countries: a cross-sectional study of Iringa Region-Tanzania. BMJ Open 2023; 13: e075399."),
    ("D472GT7E", "Maqungo M, Nannan N, Nojilana B, et al. Can verbal autopsies be used on a national scale? Key findings and lessons from South Africa's national cause-of-death validation study. Glob Health Action 2024; 17: 2399413."),
    ("6E96B328", "Tripathi S, Gupta S, Sharma S, et al. Perceptions of healthcare workers on implementing the 2022 WHO verbal autopsy instrument in rural India through the existing public health system. J Family Med Prim Care 2024; 13: 5840–46."),
]
NUM = {i + 1: key for i, (key, _) in enumerate(REFS)}


def cite(p, nums, label=None):
    """Add a live Zotero citation for the numbered references that are in Zotero,
    and plain bracketed numbers for the rest."""
    live = [n for n in nums if NUM[n]]
    plain = [n for n in nums if not NUM[n]]
    if live:
        add_zotero_citation(p, [NUM[n] for n in live], label or "[" + ranges(live) + "]")
    if plain:
        p.add_run(" [" + ranges(plain) + "]")


def ranges(nums):
    """[5, 6, 7, 9] -> '5–7,9'."""
    out, run = [], [nums[0]]
    for n in nums[1:]:
        if n == run[-1] + 1:
            run.append(n)
        else:
            out.append(run)
            run = [n]
    out.append(run)
    return ",".join(f"{r[0]}–{r[-1]}" if len(r) > 2 else ",".join(map(str, r)) for r in out)


def para(doc, *segments):
    """para(doc, text) or para(doc, text, [refs], more_text, [refs], ...):
    citations sit right after the text they support."""
    p = doc.add_paragraph()
    for seg in segments:
        if isinstance(seg, list):
            cite(p, seg)
        else:
            p.add_run(seg)
    return p


def lead(doc, head, text):
    p = doc.add_paragraph()
    p.add_run(head + " ").bold = True
    p.add_run(text)
    return p


def build():
    doc = Document()
    sec = doc.sections[0]
    for side in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(sec, side, Inches(1))
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for name, size in (("Title", 16), ("Heading 1", 13), ("Heading 2", 11)):
        st = doc.styles[name]
        st.font.name = "Arial"
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = RGBColor(0, 0, 0)
    footer = sec.footer.paragraphs[0]
    footer.add_run("DigitVA, Lancet Digital Health draft  |  ")
    add_page_number(footer)

    # Title page -------------------------------------------------------------
    t = doc.add_paragraph(style="Title")
    t.add_run(
        "Development and routine use of DigitVA, an open-source platform for verbal "
        "autopsy collection, physician coding and programme monitoring in India: "
        "a retrospective observational study"
    )
    doc.add_paragraph("Vivek Gupta, Apurva Sidhu, Rakesh Kumar, Biju Soman, Mubhashir [surname], "
                      "Subrata Vaidya, Tenam Sobti, Ashwini [surname], Rohina Joshi, Anand Krishnan")
    doc.add_paragraph("[Affiliations and ORCID iDs]")
    doc.add_paragraph("Correspondence to: Dr Vivek Gupta [affiliation, email]")
    doc.add_paragraph(
        "Article. Summary [~300 words]; main text [count]; 3 tables, 3 figures; "
        f"{len(REFS)} references. Reported according to RECORD and iCHECK-DH."
    )

    # Summary ----------------------------------------------------------------
    doc.add_heading("Summary", level=1).paragraph_format.page_break_before = True
    lead(doc, "Background", "In India, about four in five registered deaths have no medical certificate of cause of death. Verbal autopsy can fill this gap, but programmes often use separate tools for interviews, physician coding, review and reporting. We describe DigitVA, an open-source platform, and its routine use in two Indian programmes.")
    lead(doc, "Methods", "DigitVA, built on ODK Central and ODK Collect with the WHO 2022 forms, supported interviews, physician coding and reporting in a four-site programme (version 1, 2025) and a seven-site programme (version 2, 2025–26). From the application database (cut-off May 31, 2026) we extracted predefined indicators: coding coverage, timeliness, coding time, narrative and document capture and change in cause after SmartVA output was shown.")
    lead(doc, "Findings", "Of 7917 verbal autopsies, 79 physicians coded 7877 (99·5%). Median intervals were 193 days (IQR 114–289) from death to interview and 96 days (68–132) from submission to final cause. Median coding time was 5·1 min (3·0–8·3) in the four-site and 2·5 min (1·6–4·3) in the seven-site programme. After SmartVA output was shown, coders changed the cause group for 853 (10·9%) deaths, 445 (52·2%) of them into agreement with SmartVA. A written narrative (≥100 characters) was recorded for 5257 (66·4%) deaths and medical documents for 617 (7·8%). Deaths with medical documents less often had an ill-defined final cause (5·5% vs 20·8%; adjusted risk ratio 0·34, 95% CI 0·25–0·47).")
    lead(doc, "Interpretation", "One open-source platform supported verbal autopsy interviews, physician coding and reporting at programme scale. The main delay was between death and interview, not in coding. Coders often moved towards SmartVA once it was shown, so masking should be a deliberate choice. Version 3, which adds a death register, offline coding on phones, ICD-11 with WHO mortality rules and configurable workflows, needs prospective evaluation of timeliness, coding reliability and use of its data in district planning.")
    lead(doc, "Funding", "CDC Foundation; Indian Council of Medical Research [grant numbers].")

    # Research in context ----------------------------------------------------
    doc.add_heading("Research in context", level=1)
    lead(doc, "Evidence before this study", "We searched Europe PMC (which includes PubMed) from Jan 1, 1990, to Oct 31, 2026, without language restrictions, with the terms \"verbal autopsy\" AND (software OR platform OR \"information system\" OR \"mobile application\" OR electronic OR digital); the search returned 2876 records. [Complete screening: record the number screened and included, and add Embase.] Published tools address one or two steps of the verbal autopsy pathway. Analysis toolkits assign causes by algorithm. Electronic data collection and SmartVA decision support have been used in civil registration systems in the Philippines and the Solomon Islands. Management systems such as VMan3 support quality checks and reporting, and in India a mobile app and the MINErVA platform supported interviews and dual-physician coding in the Sample Registration System. We found no report of an open-source platform that covers collection, physician coding with ICD-11 mortality rules, offline use and programme monitoring, with routine-use data from thousands of deaths.")
    lead(doc, "Added value of this study", "We describe an open-source platform that links the steps from death notification to district reporting and report routine-use indicators from 7917 deaths coded by 79 physicians in two programmes. We show where the delays occurred, how much coding capacity the platform supported and how narrative and document capture related to the proportion of ill-defined final causes, and how often coders changed their cause after SmartVA output was shown. We trace the main design changes in the current version to problems observed in routine use.")
    lead(doc, "Implications of all the available evidence", "Verbal autopsy programmes can measure where cases are held up when every step is recorded on one platform. In these programmes the longest delay was before the interview, so links with death notification in the health system are likely to matter more than coding speed. Deaths with medical documents had fewer ill-defined causes; asking for documents during the interview is a low-cost step that merits testing. The current version needs prospective evaluation in district health systems.")

    # Introduction -----------------------------------------------------------
    doc.add_heading("Introduction", level=1).paragraph_format.page_break_before = True
    para(doc, "Cause-of-death data are needed to plan health services, set priorities and monitor programmes. In India, most deaths occur at home, and in 2023 only about 22% of registered deaths were medically certified. Districts, therefore, plan services without local information on why people die. Weak civil registration and vital statistics systems are a common problem in low-income and middle-income countries.", [1, 2])
    para(doc, "Verbal autopsy is a structured interview with a family member or caregiver about the signs, symptoms and circumstances before death. The interview is then interpreted by a physician or by a computer algorithm to assign a probable cause. WHO instruments standardise the interview, and shortened versions have been developed for routine mortality surveillance.", [3, 4])
    para(doc, "Each verbal autopsy passes through several steps: notification of the death, interview, data transfer, physician coding, quality review and reporting. Delay or loss at any step reduces the coverage and timeliness of the final data. Moving verbal autopsy from research into routine civil registration and health-system use needs tools that support each step and show where cases are held up. Electronic data collection, automated verbal autopsy and SmartVA decision support have been introduced into routine systems in several countries.", [5, 6, 7, 8, 9])
    para(doc, "Available software usually supports one part of this pathway. The openVA toolkit standardises computer-coded analysis, VMan3 supports data management and quality checks, and a mobile app has been used in India for interviews and cause assignment. Our earlier platform, MINErVA, supported interviews with the Sample Registration System form and dual-physician coding.", [10, 11, 12, 13], " Physician coding performs at least as well as computer-coded methods, in an Indian evaluation and a systematic review, and remains the reference method.", [14, 15])
    para(doc, "DigitVA was developed to support the whole pathway for the WHO verbal autopsy instrument, with a single physician coding each death, first without and then with SmartVA output, and targeted review. We aimed to describe the current platform (version 3), report routine use of versions 1 and 2 in two Indian programmes and explain how that use shaped version 3.")

    # Methods ----------------------------------------------------------------
    doc.add_heading("Methods", level=1)
    doc.add_heading("Study design and setting", level=2)
    para(doc, "We did a retrospective observational study of routine platform use, reported according to the RECORD and iCHECK-DH checklists (appendix).", [16], " Version 1 supported the programme Using Digital Solutions to Improve Cause of Death Data in India, funded by the CDC Foundation, at four sites in Karnataka, Kerala, Delhi and Tripura, with interviews from March to November, 2025, and coding from September to November, 2025. Version 2 supported the programme Implementation and Scaling Up of a Model to Achieve Universal Coverage with Physician-Ascertained Cause of Death at District Level in India, funded by the Indian Council of Medical Research, at seven sites in Delhi, Madhya Pradesh, Meghalaya, Odisha, Puducherry and Rajasthan, with interviews from June, 2025, to March, 2026, and coding from November, 2025, to May, 2026. In both, trained interviewers used the WHO 2022 forms and trained physicians coded with ICD-10.")
    doc.add_heading("Platform development", level=2)
    para(doc, "DigitVA was developed by the study team as open-source software under the MIT licence. Versions 1 and 2 were built around the open-source ODK ecosystem: interviewers used the WHO-recommended ODK forms of the WHO 2022 instrument in ODK Collect, ODK Central held the submissions, and DigitVA synchronised them for coding, review and reporting. ODK, a general-purpose platform, lacks functions these programmes need, such as username, password and PIN sign-in, a death register and case workflows, so version 3 adds its own collection while keeping ODK. Each version followed review of needs with site teams and coders. The server uses Python (Flask), PostgreSQL, Celery and Redis in Docker containers, and the DigitVA Collect Android app uses React Native (Expo). Automated tests (7286 server and about 3300 mobile in November, 2026) and continuous-integration pipelines check each change and build signed releases; deployments follow a verified database backup. Five rounds of external security review were done during development.")
    doc.add_heading("Indicators and data extraction", level=2)
    para(doc, "Indicators were defined before extraction and are listed in table 2. A coded death was a submission with an active final assessment, and a coder was a physician who authored at least one. Death to interview was the interval between the date of death and the interview date recorded in the questionnaire. Submission to final cause was the interval between the submission date in ODK and the saved final assessment. Coding time was the interval between allocation of a case to a coder and the saved final assessment. Throughput was coded deaths per coder-day and per calendar day. A death was counted as flagged difficult to code when the coder marked it so and gave a reason; such deaths could still be coded later. A written narrative was counted when the narrative field had at least 100 characters; shorter entries were classified as placeholders (for example “na” or “.”), references to an uploaded photograph, or short statements. A narrative was counted as photographed or audio-recorded when the corresponding attachment was present. A later version from ODK was counted when a second version of the interview data was received, and as an ODK Central edit when the record had a new instance identifier. Medical documents were counted when at least one document photograph was attached. Coders recorded a cause sequence first without seeing SmartVA output (step 1) and then, with SmartVA output shown, the final cause (step 2). We compared the underlying cause at the two steps, and each with SmartVA's most likely cause, by cause group of the WHO 2022 verbal autopsy list (65 groups in 14 categories), with ICD-10 codes mapped to groups as in the platform's reporting. A change was counted as into agreement with SmartVA when the step 1 group differed from SmartVA's and the step 2 group matched it, and out of agreement in the reverse case. An ill-defined final cause was an ICD-10 code in chapter XVIII (R00–R99). Synchronisation reliability was the proportion of ODK synchronisation runs that completed; refreshes of reporting views were counted separately.")
    para(doc, "The cut-off date was May 31, 2026. Test, training and demonstration projects were excluded. Only aggregate statistics were extracted; no names, identifiers or narratives left the database.")
    doc.add_heading("Statistical analysis", level=2)
    para(doc, "We report counts, proportions and medians (IQR). Intervals were calculated only when both dates were present and the interval was between 0 and 3650 days. We compared the proportion of ill-defined final causes in deaths with and without medical documents with a Mantel–Haenszel risk ratio, stratified by programme, age group (<15, 15–69 and ≥70 years) and place of death (health facility, home or other). Agreement with SmartVA at step 1 and step 2 was compared with McNemar's test for paired proportions. Data were extracted with PostgreSQL 16 and analysed with Stata 19 (StataCorp, College Station, TX, USA); the extraction queries and the Stata do-file are available with the source code. Sensitivity analyses and missing data are reported in the appendix.")
    doc.add_heading("Ethics", level=2)
    para(doc, "The programmes were approved by [institutional ethics committees, approval numbers]. Verbal autopsy respondents gave informed consent before the interview. This analysis used aggregate operational data under these approvals.")
    doc.add_heading("Role of the funding source", level=2)
    para(doc, "The funders had no role in study design, data collection, data analysis, data interpretation or writing of the report.")

    # Results ----------------------------------------------------------------
    doc.add_heading("Results", level=1)
    doc.add_heading("The platform", level=2)
    para(doc, "DigitVA supports each step of the verbal autopsy pathway (figure 1; table 1). A death can be entered in a death register by a health worker, assigned to an interviewer in the responsible health unit and followed until the interview is done. Possible duplicate registrations are flagged by matching names, telephone numbers and health identifiers, while names stay encrypted. Interviews are collected in ODK Collect and synchronised to the server, entered in a web browser, or collected in the DigitVA Collect Android app, which works without a network and keeps unsent interviews in an encrypted store on the phone. Photographs of medical documents and of the written narrative, and audio-recorded narratives, are stored with the interview. In version 3, the death register, consent and interview share one record. The WHO 2022 questionnaire is the base, and each project switches on DigitVA layers: consent, social autopsy, medical records and death summaries, the narration language with photographed or audio narrative, health identifiers, the certificate fields needed by the WHO mortality rules, and optional equity questions (residence, social group, vulnerability and health insurance, in DHS categories). A public register lists each layer and change to a WHO question.")
    para(doc, "For training, a permanent project holds about 200 consented, pseudonymised cases on which every role practises in the same screens; a trainer opens sessions with coder places, and practice work is kept apart from programme data. In standalone mode, a physician without a project account can interview and code on the phone without a network, with SmartVA and ICD-11 with the WHO mortality rules, keep an encrypted backup and send the records to a project after enrolment. A public demonstration site lets anyone collect, code and review a test interview.")
    para(doc, "SmartVA is run on every interview, on the server and on the phone. In versions 1 and 2, coding was done in two steps: the physician reviewed the structured answers, narrative and documents and recorded a cause sequence without seeing SmartVA output, and then recorded the final cause with SmartVA output shown. In version 3, a project chooses between this masked two-step coding and a single step with SmartVA output shown, and the cause is recorded in ICD-10 or ICD-11. In version 3, the underlying cause is selected with the WHO mortality rules (DORIS) and checked with CoDEdit; the same coding screens run on the web and on the phone, with or without a network. A reviewer can be allocated for quality assurance, and a recoding window allows correction. A coder or reviewer can send an incomplete interview back to the interviewer for revision, and coders classify social autopsy findings by the three delays in seeking, reaching and receiving care.", [17, 18])
    para(doc, "In versions 1 and 2, access was role based, with each role limited to a project or site. Version 3 extends this to relationship-based access control: what a user can see and do follows their relationship to the health-system hierarchy and to each death. Field staff without email, such as ASHAs, sign in with a mobile number; passwords found in known breaches are refused. A grant at a district reaches the units below it, a death reporter sees the deaths they registered, and staff of a mentoring institute attached to a district see its cases without personal identifiers. Personal identifiers are shown only to staff inside the health system who hold a grant in that project, are masked for other roles and are removed from standard exports. Death registration numbers are encrypted at rest, and each project sets how long identifiers are kept. When interview data change in ODK after coding, the new version is held for a data manager's decision and does not overwrite the coded record. Dashboards show deaths, interviews and coding progress by health-system unit, and flag deaths not interviewed within 60 days and interviews not coded within 15 days.")
    para(doc, "Projects are set up through configuration rather than changes to code: questionnaire layers, option lists, the consent notice, the coding workflow (masked or unmasked coding, narrative quality assessment, reviewer allocation, recoding window, ICD-10 or ICD-11) and the cause-group scheme used for reporting. Administrators curate which ICD-10 and ICD-11 codes can be selected and set sex and age restrictions, which refuse or warn about a code that does not fit the deceased. Each ICD-10 and ICD-11 code is mapped to the cause groups of the WHO 2022 verbal autopsy list, and the same deaths can be reported with the Sample Registration System or CMEA10 cause lists; administrators can edit each mapping. Missing translations are drafted by machine translation and used only after an administrator accepts them. Help pages, cause-group schemes and the code-to-cause mapping are public. Data managers can ask questions in plain language: a language model writes a query that is checked against permitted operations and run only on aggregate counts within the user's access; no record-level or personal data reach the model. Dashboards read summary tables refreshed in the background.")
    add_table(doc, ["Function", "Version 1 (CDC Foundation, 2025)", "Version 2 (ICMR, 2025–26)", "Version 3 (current)"], [
        ["Death notification", "None", "None", "Death register by health unit; possible-duplicate check; interviewer assignment"],
        ["Interview", "ODK Collect, batch import", "ODK Collect, scheduled incremental sync", "ODK, web browser, DigitVA Collect app (offline); signed, encrypted transfer files from sites without a network"],
        ["Questionnaire", "WHO 2022 (ODK form)", "WHO 2022 (ODK form)", "WHO 2022 base with DigitVA layers switched on per project, including equity questions"],
        ["Narrative and documents", "Text, photographs, audio", "Text, photographs, audio", "Same, captured on the phone or browser; interview can be sent back for revision"],
        ["Decision support", "SmartVA on server, masked at step 1", "SmartVA on server, masked at step 1", "SmartVA on server and phone; masking set per project"],
        ["Cause coding", "Single physician, two steps, ICD-10", "Single physician, two steps, ICD-10; reviewer and recoding", "ICD-10 or ICD-11 with WHO mortality rules; web and phone, offline"],
        ["Data integrity", "Re-import", "Payload versions; protected coded record", "Same, with encrypted receipts from phones"],
        ["Organisation", "Project and site", "Project and site", "Seven-level health-system hierarchy; mentoring institutes"],
        ["Monitoring", "Exports", "Data-manager dashboard", "Dashboards by health unit; overdue flags; phone performance counters on own server, no third-party analytics"],
        ["Access and privacy", "Password; role by project and site", "Password; role by project and site", "Password, passkey or mobile-number sign-in; breached passwords refused; relationship-based access along the health-system hierarchy; personal data by project; encrypted phone store; access audit page; public privacy notice and data-request pages"],
        ["Training and demonstration", "··", "··", "Training project with pseudonymised cases; weekly synthetic demonstration; public demonstration site; standalone phone mode"],
        ["Codes and cause groups", "ICD-10 list", "ICD-10 list", "Curated ICD-10 and ICD-11 lists with sex and age rules; WHO verbal autopsy, SRS and CMEA10 cause groups; open mapping pages"],
        ["Analysis", "Exports", "Exports", "Plain-language questions on aggregate data (AI); precomputed cause groups"],
    ], widths=[1.3, 1.5, 1.7, 2.0])
    doc.add_paragraph("Table 1: Platform functions by version")

    doc.add_heading("Routine use in versions 1 and 2", level=2)
    para(doc, "Of 7917 verbal autopsies from 11 sites, 79 physicians coded 7877 (99·5%; table 2). Three physicians coded in both programmes. Interviews were done in nine languages; Hindi was the most common (3444 [43·5%]), followed by Tamil (1301 [16·4%]), Odia (1246 [15·7%]), Khasi (966 [12·2%]) and English (469 [5·9%]); four other languages accounted for 491 (6·2%). The median interval from death to interview was 114 days (IQR 54–179) in the four-site and 208 days (126–300) in the seven-site programme. The median interval from submission to final cause was 60 days (34–114) in the four-site and 99 days (72–133) in the seven-site programme. In the seven-site programme, most interviews were loaded in one batch on April 2, 2026, after a pipeline delay, and 5915 deaths were coded in April, 2026, with a peak of 421 deaths in a day (figure 2).")
    para(doc, "Median coding time was 5·1 min (IQR 3·0–8·3) in the four-site and 2·5 min (1·6–4·3) in the seven-site programme. Coders coded a median of seven deaths (4–12) per coder-day in the four-site and 15 (6–40) in the seven-site programme. Workload was uneven: the top 10% of coders coded 26% of deaths in the four-site and 44% in the seven-site programme (figure 3).")
    para(doc, "A written narrative of at least 100 characters was recorded for 5257 (66·4%) deaths: 903 (93·6%) in the four-site and 4354 (62·6%) in the seven-site programme. Of the other written entries, 1072 (13·5%) were short statements, mostly of the presumed cause, 342 (4·3%) referred to an uploaded photograph and 1246 (15·7%) were empty or placeholders such as “na”; 1206 of the placeholders were in the seven-site programme. A photograph of a handwritten narrative was attached for 3617 (45·7%) deaths (50·4% in the seven-site vs 11·4% in the four-site programme) and an audio narrative for 443 (5·6%). Counting these, 7850 (99·2%) deaths had a narrative in some form and 44 (0·6%) had none. Medical documents were attached for 617 (7·8%) deaths (13·2% in the four-site and 7·0% in the seven-site programme), with a median of three pages. Deaths with documents were more often facility deaths (38·0% vs 20·1%). An ill-defined final cause was recorded for 34 (5·5%) of 615 coded deaths with documents and 1509 (20·8%) of 7262 without; after stratification by programme, age group and place of death, the risk ratio was 0·34 (95% CI 0·25–0·47).")
    para(doc, "Coders flagged 68 (0·9%) deaths as difficult to code, most often because of insufficient information or a narrative in a language the coder did not read; 48 were coded by the cut-off. Final causes were recoded for 85 (1·1%) deaths; the three-character ICD-10 code changed for 26 deaths. A later version of the interview arrived from ODK for 1071 (13·5%) submissions, including 542 edited in ODK Central; 991 had at least one changed answer (median three fields). In the four-site programme, all later versions arrived in one resynchronisation in April, 2026; those for deaths already coded were held for a data-manager decision, and 44 were rejected. SmartVA results were available for 7897 (99·7%) deaths; the 20 without a result were not coded. During the April, 2026, batch load, SmartVA failed at least once for 3477 deaths, all of which succeeded when rerun. No attachment among the 16 751 files was refused or recorded with an error. Between March 31 and May 31, 2026, 976 (96·8%) of 1008 ODK synchronisation runs completed.")
    para(doc, "Coders recorded both steps for 7875 (>99·9%) coded deaths. Between step 1 and step 2, the underlying ICD-10 code changed for 231 (24·3%) deaths in the four-site and 904 (13·1%) in the seven-site programme, and the cause group for 179 (19·0%) of 944 and 674 (9·7%) of 6914 deaths with both groups assigned; the cause category changed for 141 (14·9%) and 525 (7·6%). Of the 853 group changes, 445 (52·2%) moved into agreement with SmartVA's most likely cause, 101 (11·8%) moved out of agreement and 307 (36·0%) moved between two other groups. Agreement with SmartVA rose from 37·5% at step 1 to 44·2% at step 2 in the four-site programme (difference 6·7 percentage points, 95% CI 4·5–8·9; McNemar p<0·0001) and from 44·3% to 48·4% in the seven-site programme (4·1, 3·5–4·7; p<0·0001). SmartVA assigned an undetermined cause to 213 (22·4%) deaths in the four-site and 2384 (34·4%) in the seven-site programme; when SmartVA assigned a cause, agreement rose from 40·1% to 48·2% and from 46·6% to 51·8%.")
    add_table(doc, ["Indicator", "Four-site programme", "Seven-site programme", "Total"], [
        ["Sites; interview languages", "4; 6", "7; 5", "11; 9"],
        ["Verbal autopsies", "965", "6952", "7917"],
        ["Coded, n (%)", "949 (98·3%)", "6928 (99·7%)", "7877 (99·5%)"],
        ["Physician coders", "24", "58", "79"],
        ["Death to interview, days", "114 (54–179)", "208 (126–300)", "193 (114–289)"],
        ["Submission to final cause, days", "60 (34–114)", "99 (72–133)", "96 (68–132)"],
        ["Coding time, min", "5·1 (3·0–8·3)", "2·5 (1·6–4·3)", "··"],
        ["Deaths per coder-day", "7 (4–12)", "15 (6–40)", "··"],
        ["Peak deaths coded in a day", "70", "421", "··"],
        ["Written narrative ≥100 characters, n (%)", "903 (93·6%)", "4354 (62·6%)", "5257 (66·4%)"],
        ["Written placeholder only, n (%)", "40 (4·1%)", "1206 (17·3%)", "1246 (15·7%)"],
        ["Photographed narrative, n (%)", "110 (11·4%)", "3507 (50·4%)", "3617 (45·7%)"],
        ["Audio narrative, n (%)", "10 (1·0%)", "433 (6·2%)", "443 (5·6%)"],
        ["Narrative in any form, n (%)", "955 (99·0%)", "6895 (99·2%)", "7850 (99·2%)"],
        ["Medical documents, n (%)", "127 (13·2%)", "490 (7·0%)", "617 (7·8%)"],
        ["Flagged difficult to code, n (%)", "17 (1·8%)", "51 (0·7%)", "68 (0·9%)"],
        ["Recoded, n (%)", "33 (3·5%)", "52 (0·8%)", "85 (1·1%)"],
        ["SmartVA result available, n (%)", "965 (100%)", "6932 (99·7%)", "7897 (99·7%)"],
        ["Cause group changed from step 1 to step 2, n/N (%)", "179/944 (19·0%)", "674/6914 (9·7%)", "853/7858 (10·9%)"],
        ["Of changes, into agreement with SmartVA, n (%)", "85 (47·5%)", "360 (53·4%)", "445 (52·2%)"],
        ["Agreement with SmartVA cause group, step 1 → step 2, %", "37·5 → 44·2", "44·3 → 48·4", "43·5 → 47·9"],
        ["Later version from ODK, n (%)", "964 (99·9%)", "107 (1·5%)", "1071 (13·5%)"],
        ["Edited in ODK Central, n (%)", "510 (52·8%)", "32 (0·5%)", "542 (6·8%)"],
        ["Attachment files", "1648", "15 103", "16 751"],
        ["Hosting cost per month, US$, mean (range)", "··", "··", "28 (23–42)"],
    ], widths=[2.6, 1.3, 1.3, 1.3])
    doc.add_paragraph("Table 2: Routine-use indicators, versions 1 and 2. Data are n, n (%) or median (IQR). Data cut-off May 31, 2026. ·· = not applicable or not computed.")

    doc.add_heading("Lessons from routine use and the design of version 3", level=2)
    para(doc, "Problems observed in versions 1 and 2 shaped version 3 (table 3). The long interval between death and interview showed that the main delay was before the interview, so version 3 adds a death register and assignment of interviewers by health unit. Batch loading delayed coding, so version 3 synchronises incrementally and queues submissions on the phone; district connectivity was unreliable, so collection and coding also work without a network. Programme staff could not see where cases were held up, so dashboards now report progress and overdue cases by health unit.")
    add_table(doc, ["Observation in versions 1 and 2", "Evidence", "Response in version 3"], [
        ["Interviews done long after death", "Median 193 days from death to interview", "Death register; interviewer assignment by health unit; overdue flags at 60 days"],
        ["Records reached coders in batches", "6836 seven-site programme records loaded on one day", "Incremental sync; collection and queued submission on the phone"],
        ["Unreliable connectivity in districts", "Programme experience", "Offline collection and coding, with SmartVA and ICD-11 on the phone"],
        ["Many interview languages", "Nine languages; narrative language among reasons for not coding", "Narration language recorded per case; Hindi interface"],
        ["Interview data changed after coding", "1071 submissions with a second version", "Payload versions; protected coded record; data-manager decision"],
        ["Progress not visible to programme staff", "Programme experience", "Dashboards by health unit; overdue flags"],
        ["Research roles did not match district staff", "Programme experience", "Health-system hierarchy; mentoring institutes; interviewer, supervisor and death-reporter roles"],
        ["Coders often moved towards SmartVA at step 2", "52% of cause-group changes moved into agreement with SmartVA", "Masked or unmasked coding set per project; step 1 kept where independent coding is needed"],
        ["Coding concentrated in few physicians", "Top 10% of coders coded 44% (seven-site programme)", "Allocation time-outs; per-project recoding window"],
    ], widths=[1.9, 2.2, 2.4])
    doc.add_paragraph("Table 3: Lessons from versions 1 and 2 and the response in version 3")

    # Discussion -------------------------------------------------------------
    doc.add_heading("Discussion", level=1)
    para(doc, "DigitVA supported the interviews, physician coding and reporting of 7917 verbal autopsies in two Indian programmes; 79 physicians coded more than 98% in both. When the cases reached the platform, coding was quick: up to 421 deaths were coded in a day and the median coding time was a few minutes. The longest delay was before the interview, a median of more than 6 months after death. Weak death notification delays interviews elsewhere too.", [19, 20], " For district use, the priority is to shorten the interval from death to interview.")
    para(doc, "The short coding times need care. SmartVA output and the structured case summary may also have shortened the review. Short coding times may also reflect pressure to clear a backlog and say nothing about accuracy, which needs double coding of a sample of deaths.")
    para(doc, "Medical documents were attached for fewer than one in ten deaths, but these deaths were about a third as likely to have an ill-defined final cause, after accounting for programme, age and place of death. This association may partly reflect better care and diagnosis before death. Even so, it may be feasible for interviewers to ask for prescriptions, discharge summaries and test reports, and the platform makes these documents available to the coder. Photographed narratives were far more common in the seven-site programme, perhaps from site practice; handwritten local-language narratives can be hard for physicians to read.", [21], " About one in six of its written narratives was a placeholder, so version 3 lets a coder send such an interview back for revision; a minimum-length check and refresher training may also help.")
    para(doc, "Masking SmartVA output until the physician has recorded a first cause has advantages and costs. The step 1 cause is an independent physician judgment: it guards against anchoring on an algorithm when neither physician nor algorithm is reliably accurate for individual deaths, keeps a physician-only cause for comparison with algorithms, and makes the influence of SmartVA measurable.", [15], " The second step lets the coder reconsider in the light of SmartVA, which may catch a missed symptom or a slip. The costs are a second look at every death, which adds time, and the risk that an uncertain coder defers to the algorithm. In these programmes, a change of cause group after SmartVA was shown was about four times as likely to move into agreement with SmartVA as out of it, and the cause group changed for about one death in ten. Without a reference standard we cannot tell how many of these changes were corrections. Version 3 therefore makes masking a project setting: programmes that train new coders or need an independent physician cause can keep two steps, and programmes with experienced coders can code in one.")
    para(doc, "Other tools cover parts of this pathway (appendix table S7).", [7, 8, 10, 11, 12, 13], " The closest are VMan3, which adds multi-physician consensus and InterVA5 analysis to ODK interviews, with ICD-11 planned,", [11], " and an Indian mobile app that links death listing, offline interviews and medical officer coding without an algorithm.", [12], " DigitVA combines collection, physician coding with ICD-11 mortality rules, review and programme monitoring in one open-source platform, and records each step so that delays can be measured.")
    para(doc, "This study has limitations. It is a retrospective analysis of routine data from two programmes, and the platform changed during the study. Coding times were taken from application timestamps and do not include time spent outside the platform. In the seven-site programme, a single batch load affected the interval from submission to final cause. Reviewer use was too limited to report agreement between coders, although independent physicians often disagree,", [20], " and accuracy was not assessed against a reference standard. The association between documents and ill-defined causes may be confounded by factors we did not measure. Agreement with SmartVA is not a measure of accuracy, and changes after SmartVA was shown may be corrections or deference to the algorithm. Version 3 functions were not yet used in these programmes.")
    para(doc, "Version 3 needs to be evaluated in district health systems. The evaluation should measure the interval from death notification to interview and to coded cause, coding reliability with double coding, the effect of ICD-11 and the WHO mortality rules on the selection of the underlying cause, the cost per coded death, and whether district and programme managers use the data for planning.")

    # End matter -------------------------------------------------------------
    doc.add_heading("Contributors", level=1)
    doc.add_paragraph("VG conceptualised the platform, developed versions 2 and 3, curated and analysed the "
                      "data and wrote the first draft. TS developed version 1. AK conceptualised the programme, "
                      "supervised the work and acquired funding. AS, RK, BS, Mubhashir [surname], SV, Ashwini "
                      "[surname] and RJ were project scientists and site leads: they contributed requirements and "
                      "suggestions for the platform, tested it, managed and supervised field data collection and "
                      "gathered user feedback. VG and [second author] accessed and verified the data. All authors "
                      "reviewed and edited the manuscript, had full access to the data and accepted "
                      "responsibility for the decision to submit for publication.")
    doc.add_heading("Declaration of interests", level=1)
    doc.add_paragraph("[To be completed by all authors.]")
    doc.add_heading("Data sharing", level=1)
    doc.add_paragraph("Individual verbal autopsy records contain personal and health information and cannot be shared publicly. The aggregate indicator tables and the database queries used to produce them will be available from the corresponding author from publication, for research use, after approval by the All India Institute of Medical Sciences, New Delhi. The DigitVA source code is available under the MIT licence at https://github.com/drguptavivek/DigitVA [cite the release tag or archived DOI].")
    doc.add_heading("Acknowledgments", level=1)
    doc.add_paragraph("[Interviewers, coders, site teams and families.]")

    doc.add_heading("References", level=1).paragraph_format.page_break_before = True
    add_zotero_bibliography(doc, "\n".join(f"{i + 1}. {text}" for i, (_, text) in enumerate(REFS)))
    missing = [f"{i + 1}" for i, (key, _) in enumerate(REFS) if key is None]
    if missing:
        p = doc.add_paragraph()
        p.add_run("Not yet in Zotero (cited as plain numbers; import and link before Zotero Refresh): ").bold = True
        p.add_run("references " + ", ".join(missing) + ".")

    doc.add_section(WD_SECTION.NEW_PAGE)
    doc.add_heading("Figures", level=1)
    add_bullet(doc, "Figure 1: The verbal autopsy pathway in DigitVA version 3, from death notification to district dashboards, with the platform components at each step (docs/manuscript/figures/figure1_pathway.pdf).")
    add_bullet(doc, "Figure 2: Interviews submitted and deaths coded per month, four-site and seven-site programmes (Stata: private/ldh-analysis/output/figure2_monthly.png).")
    add_bullet(doc, "Figure 3: Deaths coded per physician coder, ranked, four-site and seven-site programmes (Stata: private/ldh-analysis/output/figure3_workload.png).")
    doc.add_heading("Before submission", level=1)
    for text in [
        "Confirm limits on the live LDH author page (blocked to automated access).",
        "Rerun all queries at the cut-off and recheck every number.",
        "Verify the MCCD 2023 figure (about 22% of registered deaths) against the official report.",
        "Complete the literature screening for Research in context.",
        "Add running-cost results, or remove that row.",
        "Pre-submission enquiry to the LDH editors.",
    ]:
        add_bullet(doc, text)

    props = doc.core_properties
    props.title = "DigitVA: development and routine use of an open-source verbal autopsy platform"
    props.author = "Vivek Gupta and collaborators"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(OUT)


APPENDIX_OUT = Path("docs/manuscript/DigitVA_LDH_Appendix.docx")


def build_appendix():
    """Supplementary appendix: the RECORD, iCHECK-DH and mERA items that do not
    fit in 3500 words. Numbers from private/ldh-analysis/digitva_ldh_cases.csv
    (export: scripts/stata/digitva_ldh_export.sql), cut-off 31 May 2026."""
    doc = Document()
    sec = doc.sections[0]
    for side in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(sec, side, Inches(1))
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(6)
    doc.add_paragraph(style="Title").add_run("Supplementary appendix")
    doc.add_paragraph(
        "Development and routine use of DigitVA, an open-source platform for verbal autopsy "
        "collection, physician coding and programme monitoring in India: a retrospective "
        "observational study"
    )

    doc.add_heading("1. Reporting checklists", level=1)
    para(doc, "The study is reported according to RECORD, the extension of STROBE for routinely "
         "collected health data, and iCHECK-DH for digital health implementations; applicable mERA "
         "items are also addressed. The completed checklists, with the section where each item is "
         "reported, are given in appendix tables S1–S3. [Insert the final checklists.]")

    doc.add_heading("2. Data source, selection and access", level=1)
    para(doc, "Data were extracted from the DigitVA PostgreSQL database on [date], with a cut-off of "
         "May 31, 2026. The authors who extracted the data are platform developers and had full access "
         "to the database. One row was extracted per submission. Submissions were included when they "
         "belonged to the version 1 (CDC Foundation) or version 2 (ICMR) programme project and were submitted "
         "before June 1, 2026; the active payload version of each submission was used. Final causes "
         "were included when active and recorded before June 1, 2026. No data were linked to other "
         "sources. Identifiers, names, narratives and free text were not extracted; coders appear as "
         "pseudonyms numbered within each programme. The extraction query and the Stata do-file are "
         "published with the source code (scripts/stata/).")
    para(doc, "Counts were not checked against an independent source such as ODK Central. "
         "[Confirm, or report the reconciliation if one is done before submission.] The platform "
         "itself keeps every payload version received from ODK, so later edits are visible in the "
         "data rather than overwriting earlier ones.")

    doc.add_heading("3. Participant flow", level=1)
    add_table(doc, ["Step", "Version 1", "Version 2", "Total"], [
        ["Submissions before the cut-off", "965", "6952", "7917"],
        ["Not coded by the cut-off", "16", "24", "40"],
        ["   No SmartVA result", "", "", "20"],
        ["   Flagged by a coder as difficult and not coded", "", "", "20"],
        ["Coded (final cause recorded)", "949", "6928", "7877"],
        ["Coded with a step 1 and a step 2 cause", "", "", "7875"],
        ["Cause group assigned at both steps", "944", "6914", "7858"],
    ], widths=[3.0, 1.1, 1.1, 1.1])
    doc.add_paragraph("Table S4: Flow of submissions. [Add the version split for the two reasons.] "
                      "Of 68 deaths flagged by a coder, 48 were coded by the cut-off.")

    doc.add_heading("4. Indicator definitions", level=1)
    add_table(doc, ["Indicator", "Definition"], [
        ["Death to interview", "Interview date (Id10012) minus date of death (Id10023), in days, when both dates were valid"],
        ["Submission to final cause", "Time of the active final cause minus the submission date, in days"],
        ["Coding time", "Time of the final cause minus the latest non-training coding allocation before it, in minutes"],
        ["Written narrative", "Id10476 classed as: empty or placeholder (for example na, nil, '.', one or two letters); "
         "pointer to an uploaded photograph; short statement under 100 characters; narrative of 100 characters or more"],
        ["Photographed or audio narrative", "Narrative image or audio field present"],
        ["Medical documents", "Number of medical-document image fields present (up to 30)"],
        ["Ill-defined final cause", "Final ICD-10 code in chapter XVIII (R00–R99)"],
        ["Recoded", "At least one superseded final cause, excluding demonstration and tester records"],
        ["Later version from ODK", "More than one payload version; edited in ODK Central when the instanceID changed; "
         "changed answers counted over questionnaire fields"],
        ["Cause group", "Three-character ICD-10 code mapped to the WHO 2022 verbal autopsy cause list "
         "(field and category), with legacy code aliases applied, as in the platform's reporting layer"],
        ["Agreement with SmartVA", "Same WHO 2022 cause group for the physician cause and SmartVA's most likely cause"],
        ["SmartVA undetermined", "SmartVA's most likely cause in ICD-10 chapter XVIII"],
    ], widths=[1.8, 4.6])
    doc.add_paragraph("Table S5: Indicator definitions. All indicators were defined before extraction; "
                      "the comparison of ill-defined causes by document attachment was [prespecified / "
                      "added during analysis].")

    doc.add_heading("5. Missing data", level=1)
    add_table(doc, ["Variable", "Missing, version 1 (n=965)", "Missing, version 2 (n=6952)", "Reason"], [
        ["Final cause, coding time, intervals to final cause", "16", "24", "Not coded by the cut-off"],
        ["Death to interview", "2", "51", "Missing or invalid date (51), or interval outside 0–3650 days (2)"],
        ["Step 1 to step 2 code change", "16", "26", "Not coded, or no step 1 code"],
        ["Cause group at both steps", "21", "38", "As above, or code not mapped to a cause group"],
        ["SmartVA most likely cause", "0", "20", "No SmartVA result"],
    ], widths=[2.4, 1.3, 1.3, 1.4])
    doc.add_paragraph("Table S6: Missing data. Analyses used all available records; no values were imputed.")

    doc.add_heading("6. Sensitivity analyses", level=1)
    para(doc, "Batch load: in version 2 most interviews were loaded on April 2, 2026, so the interval "
         "from submission to final cause includes time before the platform received them. For the "
         "6813 version 2 deaths coded on or after that date, the median interval from the load to the "
         "final cause was 21 days (IQR 16–26).")
    para(doc, "Documents and ill-defined causes: the crude risk ratio was 0·27 (34 of 615 deaths with "
         "documents vs 1509 of 7262 without). The Mantel-Haenszel risk ratio stratified by programme, "
         "age group and place of death was 0·34, and 0·35 when the 1246 deaths with an empty or "
         "placeholder written narrative were excluded.")
    para(doc, "Agreement with SmartVA: excluding deaths with an undetermined SmartVA cause, agreement "
         "rose from 40·1% to 48·2% in version 1 and from 46·6% to 51·8% in version 2 (main text).")

    doc.add_heading("7. Users, usability and training", level=1)
    para(doc, "No formal usability testing was done for this study. Coders were trained in verbal "
         "autopsy coding by each programme. [Describe the platform training given to interviewers, "
         "coders and data managers in each programme.]")

    doc.add_heading("8. Hosting, governance and sustainability", level=1)
    para(doc, "The source code is open under the MIT licence; verbal autopsy data belong to the "
         "programmes and are not open. The platform was hosted on Amazon Web Services in the Mumbai "
         "region, and data were handled under the ICMR National Ethical Guidelines for Biomedical and "
         "Health Research Involving Human Participants. The MINErVA team at the All India Institute "
         "of Medical Sciences, New Delhi, maintains the platform, with VG as technical lead and AK "
         "as overall lead, and funds it through new project grants. Personal identifiers are encrypted at rest, shown only to staff with a "
         "grant in that project, and kept for a period set by each project.")

    doc.add_heading("9. Costs", level=1)
    para(doc, "Hosting on Amazon Web Services (Mumbai region) cost US$416 from March, 2025, to May, 2026, "
         "including tax: a mean of US$28 per month (range 23–42), rising from April, 2026, with the "
         "full version 2 coding load (AWS invoices). Version 1 was developed from November, 2024, by "
         "one full-time developer (TS), who also set up version 2 for its first 115 coded deaths in "
         "November, 2025; version 2 from March, 2026, and version 3 were developed by one "
         "physician-developer (VG); development time was not "
         "recorded. The code repository begins on Oct 7, 2025, after version 1 was built; it shows "
         "commits on 43 days up to May 31, 2026 (version 2; VG on 39, TS on five) and on 45 days "
         "from September, 2026 (version 3, by VG). Commit days are a lower bound on effort, not "
         "hours worked.")

    doc.add_heading("10. Literature search", level=1)
    para(doc, "Europe PMC (including PubMed), Jan 1, 1990, to Oct 31, 2026, no language restriction: "
         "\"verbal autopsy\" AND (software OR platform OR \"information system\" OR \"mobile "
         "application\" OR electronic OR digital); 2876 records. [Records screened, full texts "
         "assessed and included; Embase search.] A feature comparison of published verbal autopsy "
         "software is in table S7.")
    add_table(doc, ["Tool (reference)", "Interviews and offline use", "Physician coding",
                    "Algorithm", "ICD", "Open source", "Reported scale"], [
        ["DigitVA (this study)", "ODK Collect (versions 1–2); own web and Android app with "
         "offline use, photos and audio (version 3)", "Two steps, SmartVA hidden until the first "
         "cause; reviewer and recode window", "SmartVA, shown after step 1 (masking is a project "
         "setting)", "ICD-10 (versions 1–2); ICD-11 with WHO mortality rules (version 3)",
         "Yes (MIT)", "7877 deaths coded by 79 physicians"],
        ["VMan3 (ref 11)", "ODK Collect and Central; offline not reported",
         "Several coders per death; chat-based resolution of discordant causes",
         "InterVA5; shown to coders not reported", "ICD-10; ICD-11 planned", "Not reported",
         "Stress test with 38 000 records; no deployment reported"],
        ["Unified mobile app, India (ref 12)", "Own Android app, offline with sync; English "
         "and Hindi", "Medical officer assigns the cause in the app; single or dual not reported",
         "None (planned)", "Not reported", "Not reported", "Prototype; no deployment reported"],
        ["MINErVA (ref 13)*", "Paper forms, scanned and digitised", "Two blinded physicians, "
         "third physician and adjudicator on disagreement", "None", "ICD-10", "In-house, free "
         "open-source components; licence not reported", "More than 75 000 forms; 676 physicians"],
        ["SmartVA Auto-Analyse, Philippines (ref 7)", "ODK Collect on tablets; offline not "
         "reported", "One physician, after seeing the algorithm", "Tariff 2.0, top three causes "
         "shown", "Version not stated", "Not reported", "5649 deaths, 91 municipalities"],
        ["SmartVA, Solomon Islands (ref 8)", "ODK on tablets; data carried on USB where there "
         "was no network", "None", "Tariff 2.0", "Hospital codes mapped for comparison",
         "Not reported", "1034 interviews"],
        ["openVA (ref 10)", "Not part of the toolkit; a companion pipeline reads ODK data",
         "None (can use physician codes in InSilicoVA)", "InterVA4, InterVA5, InSilicoVA, Tariff",
         "Not reported", "Yes", "No deployment figures"],
    ], widths=[1.0, 1.1, 1.1, 0.9, 0.9, 0.7, 0.8])
    doc.add_paragraph("Table S7: Features of published verbal autopsy software, as stated in each "
                      "report; \"not reported\" means the report does not say. *One author of this "
                      "paper is an author of the MINErVA report.")

    APPENDIX_OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(APPENDIX_OUT)
    print(APPENDIX_OUT)


if __name__ == "__main__":
    build()
    build_appendix()
