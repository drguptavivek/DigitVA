import json
from pathlib import Path
from uuid import uuid4

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


OUT = Path("docs/manuscript/DigitVA_NPJ_Digital_Medicine_Manuscript.docx")
ZOTERO_USER_ID = "337745"


def add_complex_field(paragraph, instruction, visible_text):
    begin_run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin_run._r.append(begin)

    instruction_run = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    instruction_run._r.append(instr)

    separate_run = paragraph.add_run()
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    separate_run._r.append(separate)

    result_run = paragraph.add_run()
    for index, line in enumerate(visible_text.split("\n")):
        if index:
            result_run._r.append(OxmlElement("w:br"))
        text = OxmlElement("w:t")
        text.set(qn("xml:space"), "preserve")
        text.text = line
        result_run._r.append(text)

    end_run = paragraph.add_run()
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    end_run._r.append(end)


def add_zotero_citation(paragraph, item_keys, visible_text):
    payload = {
        "citationID": f"digitva-{uuid4().hex[:16]}",
        "properties": {"noteIndex": 0},
        "citationItems": [
            {"id": key, "uris": [f"http://zotero.org/users/{ZOTERO_USER_ID}/items/{key}"]}
            for key in item_keys
        ],
        "schema": "https://github.com/citation-style-language/schema/raw/master/csl-citation.json",
    }
    paragraph.add_run(" ")
    add_complex_field(
        paragraph,
        " ADDIN ZOTERO_ITEM CSL_CITATION " + json.dumps(payload, separators=(",", ":")),
        visible_text,
    )


def add_zotero_bibliography(doc, visible_text):
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    add_complex_field(
        paragraph,
        ' ADDIN ZOTERO_BIBL {"uncited":[],"omitted":[],"custom":[]}',
        visible_text,
    )
    return paragraph


def shade(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def borders(table, color="D9D9D9", size="6"):
    tbl_pr = table._tbl.tblPr
    tbl_borders = tbl_pr.first_child_found_in("w:tblBorders")
    if tbl_borders is None:
        tbl_borders = OxmlElement("w:tblBorders")
        tbl_pr.append(tbl_borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = "w:" + edge
        element = tbl_borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            tbl_borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:color"), color)


def set_cell_margins(cell, top=100, start=120, bottom=100, end=120):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def add_page_number(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instr, separate, end])


def add_paragraph(doc, text, bold_lead=None):
    p = doc.add_paragraph()
    if bold_lead and text.startswith(bold_lead):
        p.add_run(bold_lead).bold = True
        p.add_run(text[len(bold_lead):])
    else:
        p.add_run(text)
    return p


def add_bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    p.add_run(text)
    return p


def add_table(doc, headers, rows, widths=None):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    hdr = table.rows[0].cells
    for idx, label in enumerate(headers):
        hdr[idx].text = label
        shade(hdr[idx], "1F4E78")
        hdr[idx].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        for run in hdr[idx].paragraphs[0].runs:
            run.font.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)
            run.font.size = Pt(9)
        set_cell_margins(hdr[idx])
    for row_idx, row in enumerate(rows):
        cells = table.add_row().cells
        for col_idx, value in enumerate(row):
            cells[col_idx].text = str(value)
            cells[col_idx].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if row_idx % 2:
                shade(cells[col_idx], "EAF2F8")
            for p in cells[col_idx].paragraphs:
                p.paragraph_format.space_after = Pt(0)
                for run in p.runs:
                    run.font.size = Pt(8.5)
            set_cell_margins(cells[col_idx])
    if widths:
        for row in table.rows:
            for idx, width in enumerate(widths):
                row.cells[idx].width = Inches(width)
    borders(table)
    doc.add_paragraph()
    return table


def build():
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Inches(0.78)
    sec.bottom_margin = Inches(0.72)
    sec.left_margin = Inches(0.88)
    sec.right_margin = Inches(0.88)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.line_spacing = 1.12
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    for style_name, size in (("Title", 18), ("Heading 1", 13), ("Heading 2", 11)):
        style = styles[style_name]
        style.font.name = "Arial"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.font.bold = True
    styles["Heading 1"].paragraph_format.space_before = Pt(12)
    styles["Heading 1"].paragraph_format.space_after = Pt(5)
    styles["Heading 2"].paragraph_format.space_before = Pt(8)
    styles["Heading 2"].paragraph_format.space_after = Pt(4)

    for section in doc.sections:
        footer = section.footer.paragraphs[0]
        footer.add_run("DigitVA manuscript draft  |  ")
        add_page_number(footer)

    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    title.add_run("DigitVA for verbal autopsy coding and mortality intelligence")
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = subtitle.add_run("A secure workflow platform evolving from batch processing to real time health system use")
    r.bold = True
    r.font.size = Pt(12)
    doc.add_paragraph("Vivek Gupta and collaborators [author list and affiliations to be completed]")
    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(6)
    note.paragraph_format.space_after = Pt(12)
    run = note.add_run("Draft for npj Digital Medicine. Operational counts are from the current DigitVA database on 22 September 2026. References should undergo final full-text verification before submission.")
    run.italic = True
    run.font.color.rgb = RGBColor(80, 80, 80)

    doc.add_heading("Abstract", level=1)
    add_paragraph(doc, "Background: Verbal autopsy provides cause-of-death information for deaths that are not medically certified, but programmes frequently operate separate systems for interview collection, physician review, computer-coded verbal autopsy, quality assurance and reporting. Fragmentation delays the conversion of completed interviews into mortality intelligence.", "Background:")
    add_paragraph(doc, "Methods: We describe DigitVA, a containerised web application developed for verbal autopsy intake, data synchronisation, computer-coded verbal autopsy support, single-physician cause assignment, targeted review, audit and reporting. The software architecture and security controls were characterised from the current codebase and technical documentation. Operational use was summarised from two implementation phases. Counts were queried from the application database and coded deaths were defined as distinct submissions with an active final assessment.", "Methods:")
    add_paragraph(doc, "Results: DigitVA uses Flask, PostgreSQL, Celery and Redis, with ODK Central as the source of truth for interviews collected using the WHO verbal autopsy instrument. It provides incremental synchronisation, payload versioning, attachment management, SmartVA outputs, ICD-based single-physician coding, targeted reviewer workflows, cause-of-death grouping, scope-based dashboards and filtered exports. Phase 1, the UNSW project, included 965 verbal autopsy submissions across four sites; 949 had active final coding by 24 distinct final-assessment users. Phase 2, the ICMR project, included 6,952 submissions across seven sites; 6,928 had active final coding by 58 users. Across both phases, 7,877 of 7,917 submissions had an active final assessment. The platform evolved from batch import and analysis toward incremental processing, event-based workflow state, direct web intake and health-system organisation structures.", "Results:")
    add_paragraph(doc, "Conclusions: DigitVA demonstrates how verbal autopsy software can integrate physician coding and computer-generated evidence within one auditable workflow. The next stage is prospective evaluation of timeliness, reliability, usability and interoperability as the platform moves toward real-time death notification, health-system deployment and ICD-11 mortality coding.", "Conclusions:")

    doc.add_heading("Introduction", level=1)
    p = add_paragraph(doc, "Reliable cause-of-death information is a basic requirement for population health planning. However, many deaths occur outside facilities or without medical certification, leaving health programmes to plan services using incomplete or modelled mortality data. Verbal autopsy addresses this gap through a structured interview with a relative or caregiver, followed by physician review or computer-based cause assignment. The WHO instruments were designed to improve standardisation and compatibility with automated analysis, while Indian experience has shown that physician-coded and computer-coded methods have different strengths and should be evaluated in the context in which they are used.")
    add_zotero_citation(p, ["SJLJFQEM", "M34P3RLJ", "2CMAM96L"], "[1–3]")
    p = add_paragraph(doc, "The principal operational problem is no longer only how to assign a cause. Programmes must move interviews from field collection through completeness checks, attachments, physician coding, quality review, recoding, analysis and reporting without losing the relationship between the original interview and the final decision. Separate spreadsheets and software packages can perform parts of this pathway, but they make access control, versioning, audit and programme monitoring difficult. Our earlier MINErVA platform supported India’s Sample Registration System form and a dual-physician coding model. It was taken up by the Sample Registration System under the Registrar General of India and remains in operation. DigitVA was subsequently developed as a new, fully open-source system for the WHO verbal autopsy instrument and a computer-coded-VA-supported single-physician model. Related initiatives, including openVA, the Unified Mobile App and VMan3, illustrate the wider need for integrated digital VA systems.")
    add_zotero_citation(p, ["2Y48HNZL", "XX42INSZ", "8AB46D42", "GW7XT3RM"], "[4–7]")
    add_paragraph(doc, "DigitVA does not introduce a new diagnostic algorithm. It presents structured and narrative WHO-form evidence, computer-coded outputs and coding references to one authorised physician coder, records that physician’s decision, supports targeted review when required and generates programme-level outputs. Routine coding is therefore not a repeat of MINErVA’s dual-physician process. This manuscript describes the application, its evolution before August 2026, its use in the UNSW and ICMR projects, its security and architecture, and the planned transition from batch processing to real-time health-system use and ICD-11.")

    doc.add_heading("Methods", level=1)
    doc.add_heading("System description and evidence sources", level=2)
    add_paragraph(doc, "We conducted a descriptive software and implementation study. The system description was derived from the active DigitVA repository, including current-state architecture, data model, ODK synchronisation, workflow, dashboard and ICD-11 planning documents, supplemented by inspection of the implemented database. The implementation history was reconstructed from version-control records and the project handoff. The scientific context was developed from references retrieved from the author’s Zotero library.")
    doc.add_heading("Operational measures", level=2)
    add_paragraph(doc, "For each implementation project, we counted distinct submissions linked to registered project forms, distinct submissions with an active row in the final-assessment table, distinct users who authored those active final assessments, and distinct sites represented by the forms. The term coded death record therefore refers to a verbal autopsy submission with an active final assessment; it is not a count from a separate civil-registration death table. These definitions were chosen because they follow the authoritative coding artefact used by the application.")
    doc.add_heading("Software scope", level=2)
    add_paragraph(doc, "The analysis describes functionality present in the current development branch as of 22 September 2026. Proposed ICD-11 mortality-rule integration, passkeys and full health-system deployment are presented as future work. The description does not claim clinical validation of SmartVA, comparative diagnostic accuracy or improved mortality outcomes.")

    doc.add_heading("Results", level=1)
    doc.add_heading("From MINErVA to DigitVA", level=2)
    add_paragraph(doc, "MINErVA was the immediate programme and software predecessor developed by our group. It digitised the physician review process for verbal autopsies collected through the Sample Registration System form. Its routine cause-assignment model used two independent physician coders, with reconciliation or adjudication when their decisions differed. The platform was taken up by the Sample Registration System under the Registrar General of India and remains ongoing. This model was appropriate to the established SRS physician-review method, but it required substantial physician time and treated computer-coded methods as separate analytical processes.")
    add_paragraph(doc, "DigitVA was designed as a new system rather than a replacement deployment of MINErVA. It changed both the instrument and the operating model: the WHO verbal autopsy instrument replaced the SRS form, and computer-coded VA evidence was integrated into the case workspace. One physician makes the primary cause assignment after reviewing the interview, narrative, medical information where available, and algorithmic output. A reviewer can be allocated for targeted quality assurance, escalation or programme-defined review, but a second physician review is not required for every death. The fully open-source platform was designed for wider stakeholder participation and adaptation by medical colleges, health and demographic surveillance system sites, research programmes and routine health-system services.")
    doc.add_heading("Evolution from phase 1 to phase 2", level=2)
    add_paragraph(doc, "Phase 1 was implemented for the UNSW project, Using Digital Solutions to Improve Cause of Death Data in India. The initial model was batch-oriented: interviews were collected in ODK, synchronised into DigitVA, transformed for SmartVA and then made available for physician coding. This phase established the project–site–form model, role-based coding, final assessment storage and the operational linkage between collected data and physician decisions.")
    add_paragraph(doc, "Phase 2 was implemented for the ICMR project, Implementation and Scaling Up of a Model to Achieve Universal Coverage with Physician-Ascertained Cause of Death at District Level in India. The larger volume and site network shifted the development objective from completing a batch to operating a service. Before August 2026, the platform added reviewer coding and quality assurance, protected recoding, coded cause-of-death snapshots, ICD-10 policy controls, cause-of-death bucket schemes, site maintenance controls, help documentation and a data-manager view. The later architecture added incremental delta checks, queue-based bounded tasks, payload-version lineage and canonical workflow events. These changes reduced dependence on whole-dataset batch reruns and created the prerequisites for near-real-time processing.")

    add_table(
        doc,
        ["Phase and project", "Sites", "VA submissions", "Active final coded", "Distinct final-assessment users", "Coding coverage"],
        [
            ["Phase 1  UNSW01", "4", "965", "949", "24", "98.3%"],
            ["Phase 2  ICMR01", "7", "6,952", "6,928", "58", "99.7%"],
            ["Total", "11", "7,917", "7,877", "82", "99.5%"],
        ],
        widths=[1.55, 0.55, 0.95, 1.05, 1.55, 0.9],
    )
    cap = doc.paragraphs[-1]
    cap.add_run("Table 1. Operational database counts on 22 September 2026. Distinct final-assessment users are users who authored at least one active final assessment in that project; they are an observed operational coder count, not the number of currently enabled accounts.").italic = True

    doc.add_page_break()
    doc.add_heading("Functional modules and salient features", level=2)
    add_table(
        doc,
        ["Module", "Purpose", "Salient features"],
        [
            ["Collection and intake", "Receive WHO verbal autopsy records", "ODK Central synchronisation; project and site mappings; developing direct web intake; multilingual instruments"],
            ["Data integrity", "Maintain authoritative interview lineage", "Stable ODK key identity; payload versions; changed-field review; protected finalised records; attachment repair"],
            ["Computer-coded VA", "Generate algorithmic evidence", "SmartVA preparation, execution, likelihoods and results linked to the active payload version"],
            ["Physician coding", "Assign and document cause of death", "Single PCVA supported by structured and narrative WHO-form evidence, SmartVA output, ICD search, save and resume, and a not-codeable pathway"],
            ["Review and recoding", "Provide targeted quality control", "Optional reviewer allocation rather than routine dual PCVA; final authority; non-destructive coding episodes; upstream-data-change decisions"],
            ["Mortality reporting", "Convert case decisions into programme information", "ICD policy; hierarchical cause buckets; age bands; coded snapshots; filtered CSV exports"],
            ["Operations", "Manage programmes and users", "Project, site, form and organisation setup; scoped grants; synchronisation monitoring; maintenance and audit views"],
        ],
        widths=[1.15, 1.8, 3.55],
    )

    doc.add_heading("Architecture", level=2)
    add_paragraph(doc, "DigitVA is an HTML-first Flask application. Server-rendered pages and lightweight JavaScript interfaces support administrators, data managers, coders, reviewers and site investigators. PostgreSQL stores configuration, submissions, payload versions, allocations, assessments, workflow state and audit records. Celery workers and Redis coordinate bounded synchronisation, attachment, export and SmartVA tasks. ODK Central remains the source of truth for submitted interview content, while DigitVA stores operationally enriched versions and downstream coding artefacts. Gunicorn and Docker Compose provide the application runtime.")
    add_paragraph(doc, "The data flow is ODK or web intake to canonical submission, attachment completion, SmartVA processing, physician coding, optional reviewer coding and programme reporting. Workflow transitions are explicit and recorded as events. When ODK data change after coding, the incoming payload is held as a pending version; a data manager can accept it for recoding or promote it while retaining the current ICD decision. This design prevents a routine synchronisation from silently overwriting an authoritative coded record.")
    add_paragraph(doc, "The batch-to-real-time transition is incremental rather than a single replacement. The current application still performs scheduled and user-initiated synchronisation, but it now uses form-level delta checks, bounded tasks and event-based state transitions. Direct web intake and a death register are intended to remove the remaining collection-to-sync delay. A realistic near-real-time target is therefore rapid progression after data arrival, with idempotent retries and visible exceptions, rather than an assumption that every external data source will provide instantaneous events.")

    doc.add_heading("Security privacy and governance", level=2)
    add_paragraph(doc, "DigitVA uses authenticated sessions and explicit role and scope grants. Project, site, form and language eligibility are evaluated before records enter a user’s work queue. Browser-originated state changes require CSRF protection, including JSON requests. Data-manager views, synchronisation actions and exports are constrained to the user’s authorised scope. Personally identifiable payload fields are marked in the field configuration and excluded from standard exports, and selected local identifiers are also suppressed.")
    add_paragraph(doc, "ODK credentials are stored in database-managed connection records with encryption, with a legacy file-based fallback retained during migration. Attachments use opaque storage names. Derived exports are private, short-lived and served with no-store caching controls; object-storage deployments use server-side encryption. Database backups are checksum-verified and audit records are maintained for synchronisation, workflow changes and protected-record decisions. The planned security programme adds passkeys or time-based one-time passwords for privileged roles. Formal threat modelling, penetration testing and prospective access-log review remain necessary before broader health-system deployment.")

    doc.add_heading("Discussion", level=1)
    add_paragraph(doc, "The main contribution of DigitVA is integration of programme operations around cause assignment. Studies of computer-coded VA ask whether an algorithm can reproduce a reference cause or estimate population cause fractions. In the Indian evaluation by Benara and colleagues, physician-coded VA had the highest cause-specific mortality fraction accuracy, agreement and kappa, while Tariff 2.0, InterVA and InSilicoVA each had lower aggregate performance. This supports an architecture in which algorithmic results inform but do not silently replace physician judgement. DigitVA preserves SmartVA results, likelihoods and provenance while maintaining one physician-authored final assessment and an optional targeted review pathway. This differs deliberately from MINErVA’s routine dual-physician coding of the SRS form.")
    add_paragraph(doc, "The operational results show feasibility at a scale exceeding 5,000 coded records: the ICMR phase alone contained 6,928 active final coded records, and the two phases together contained 7,877. These counts demonstrate use of the platform, not effectiveness. They do not establish diagnostic accuracy, coding consistency, time saved, cost-effectiveness or improved completeness of death registration. A publication-quality evaluation should add coding turnaround time, allocation-to-completion time, inter-coder agreement, reviewer-change rates, not-codeable proportions, SmartVA–physician concordance, system uptime, failed-task recovery and user experience.")
    p = add_paragraph(doc, "DigitVA also differs from algorithm packages such as openVA and management platforms such as VMan3. openVA standardises analysis across VA algorithms, whereas DigitVA manages operational provenance, authorisation and physician workflow around the individual case. VMan3 provides a useful comparator for quality management and national interoperability. A direct comparative table should be added after full-text review and author confirmation of the intended claims; the present manuscript avoids claiming superiority.")
    add_zotero_citation(p, ["2Y48HNZL", "GW7XT3RM"], "[4,7]")

    doc.add_heading("What comes next", level=1)
    doc.add_heading("Additional verbal autopsy forms", level=2)
    add_paragraph(doc, "DigitVA’s next form-layer milestone is to support additional verbal autopsy instruments through explicit form profiles rather than hard-coded field names. Priority candidates include SmartVA-compatible short forms and programme-specific adaptations of the WHO instrument. Each profile should define identity fields, age and sex derivation, narrative and medical-history sections, attachment expectations, algorithm-export mappings and versioned validation rules. The application should preserve the source instrument and version with every submission so that records collected through different forms are not treated as analytically interchangeable without validation. A conformance test set and side-by-side field-mapping review will be required before a new form can enter routine coding.")

    doc.add_heading("LLM-assisted functions", level=2)
    add_paragraph(doc, "Large language models could assist with bounded tasks such as structuring free-text narratives, translating coder-facing text, highlighting internally inconsistent responses, retrieving relevant coding guidance and drafting a concise evidence summary for physician review. They should not autonomously assign or overwrite the final cause of death. Any implementation should use a model gateway that records model and prompt versions, constrains the information transmitted, prevents training on submitted data, supports locally hosted models where governance requires them, and stores model output as a reviewable derivative rather than source data. Prospective evaluation should measure factual omission, unsupported inference, translation fidelity, automation bias, subgroup performance, latency and cost. Human confirmation and a complete audit trail should remain mandatory before model-assisted content influences the final assessment.")

    doc.add_heading("Real time health system workflow", level=2)
    add_paragraph(doc, "The next programme step is to connect VA to the health system rather than treat it as an isolated research batch. DigitVA now has an organisation model that can represent health-system levels, units, cadres and workers. Its open-source model is intended to let medical colleges, HDSS sites, research networks and government health services configure the same core platform for their own governance and service pathways. In a health-system deployment, a death notification should create or match a death-register record, identify the responsible organisational unit, initiate interview follow-up, expose progress to authorised supervisors and return coded aggregate information to district and higher-level planning. Integration should use documented interfaces and minimum necessary data, with clear ownership of death identifiers, consent, corrections and final cause authority.")
    add_paragraph(doc, "Prospective implementation should measure the interval from death notification to interview, interview to algorithmic processing, processing to physician coding, and coding to availability in programme dashboards. Real-time operation also requires queue monitoring, retries, reconciliation with upstream systems, downtime procedures and an auditable manual fallback. The health-system value of the platform will depend on whether these workflows increase coverage, timeliness, quality and use of mortality data, not only whether the software responds quickly.")
    p = add_paragraph(doc, "The transition should be evaluated as a health-policy and health-systems intervention, including whether mortality information is actually used by district and programme decision-makers.")
    add_zotero_citation(p, ["26YTFYJN", "L4RYIGF4"], "[8,9]")

    doc.add_heading("ICD 11 transition", level=2)
    add_paragraph(doc, "DigitVA currently retains ICD-10 coding and cause-group reporting. The ICD-11 programme is being developed additively: a local ICD-11 Mortality and Morbidity Statistics catalogue, server-side selectability and age/sex policy, a browser interface, and native ICD-11 mappings for the WHO 2022 VA 2026 cause list. Source codes and provenance are retained so that an ICD-11-coded death is not reduced to an ICD-10 surrogate. Projects will be able to operate in ICD-10, ICD-11 or selectable mode according to programme readiness.")
    add_paragraph(doc, "The next clinical component is evaluation of the WHO ICD-11 coding tool and mortality rules for selecting the underlying cause. This is more than a code-search change: the coding interface must distinguish immediate, antecedent and underlying causes, retain the ICD release and URI, apply the mortality rules consistently and show when a local VA bucket mapping is used. Parallel coding studies should compare ICD-10 and ICD-11 decisions before routine cutover, with explicit handling of crosswalk disagreements and unmapped codes.")
    p = add_paragraph(doc, "The implementation will align with the WHO ICD-11 Mortality and Morbidity Statistics release and retain release-specific identifiers for reproducibility.")
    add_zotero_citation(p, ["WZB5UKME"], "[10]")

    doc.add_heading("Limitations", level=1)
    add_paragraph(doc, "This is a descriptive report from a living software system. Database counts are a current snapshot and may change with recoding, deactivation, synchronisation or correction. Distinct final-assessment authors were used as the operational coder count; this differs from the number of authorised or trained coders at any single date. The repository documents some features more completely than others, and not all current functions have undergone independent usability or security evaluation. Clinical outcomes, diagnostic validity and programme impact were outside the scope of this analysis. Finally, the Zotero library supplied metadata and abstracts for the scientific framing; full-text claim-by-claim citation verification should be completed before submission.")

    doc.add_heading("Conclusion", level=1)
    add_paragraph(doc, "DigitVA has evolved from a batch-oriented research workflow into a high-volume, fully open-source platform for verbal autopsy data, physician coding, computer-generated evidence, review and mortality reporting. Use in Phase 1 UNSW and Phase 2 ICMR provides an implementation base of 7,917 verbal autopsy records, of which 7,877 have active final coding. Its broader purpose is to provide a shared, adaptable system for medical colleges, HDSS sites and routine health services. The next scientific question is whether near-real-time health-system deployment improves the coverage, timeliness, reproducibility and use of cause-of-death information while protecting sensitive data. Prospective implementation research, independent security review and controlled ICD-11 evaluation should accompany that transition.")

    doc.add_heading("Data availability", level=1)
    add_paragraph(doc, "Individual verbal autopsy records are not publicly available because they may contain sensitive personal and health information. Aggregate operational counts used in this manuscript were derived from the current DigitVA database. A de-identified analysis specification and reproducible aggregate queries can be supplied with the final manuscript, subject to project governance approval.")
    doc.add_heading("Code availability", level=1)
    add_paragraph(doc, "The complete DigitVA source code is openly available under the MIT License at https://github.com/drguptavivek/DigitVA. The repository includes the application, database migrations, tests, current-state documentation and deployment configuration.")
    doc.add_heading("Ethics", level=1)
    add_paragraph(doc, "The relevant ethics approvals, data-controller responsibilities and consent arrangements for the UNSW and ICMR implementation phases must be inserted by the study investigators. This descriptive software manuscript does not report individual-level clinical data.")
    doc.add_heading("Competing interests and funding", level=1)
    add_paragraph(doc, "To be completed by all authors. Project funding statements should distinguish software development, field implementation and manuscript preparation.")

    doc.add_heading("References", level=1)
    refs = [
        "1. Riley I, Flaxman AD, Clark SJ, et al. The WHO 2016 verbal autopsy instrument: an international standard suitable for automated analysis by InterVA, InSilicoVA, and Tariff 2.0. PLoS Med. 2018;15:e1002486. doi:10.1371/journal.pmed.1002486.",
        "2. Lozano R, et al. A shortened verbal autopsy instrument for use in routine mortality surveillance systems. BMC Med. 2015;13:302. doi:10.1186/s12916-015-0528-8.",
        "3. Remolador H, et al. Collecting verbal autopsies: improving and streamlining data collection processes using electronic tablets. Popul Health Metr. 2018;16:3. doi:10.1186/s12963-018-0161-9.",
        "4. Li ZR, Thomas J, Choi E, McCormick TH, Clark SJ. The openVA Toolkit for Verbal Autopsies. R J. 2022;14:316–334. doi:10.32614/RJ-2023-020.",
        "5. Gupta V, Krishnan A, Nongkynrih B, et al. Mortality in India established through verbal autopsies (MINErVA): strengthening national mortality surveillance system in India. J Glob Health. 2020;10:020431. doi:10.7189/jogh.10.020431.",
        "6. Kaur H, Tripathi S, Chalga MS, et al. Unified Mobile App for Streamlining Verbal Autopsy and Cause of Death Assignment in India: Design and Development Study. JMIR Form Res. 2025;9:e59937. doi:10.2196/59937.",
        "7. Lyatuu I, Odhiambo C, Mrema S, et al. Verbal Autopsy Manager (VMan3): a comprehensive software tool for managing and improving quality, availability and use of cause of death data from community deaths. medRxiv. 2025. doi:10.1101/2025.05.28.25328220. Preprint.",
        "8. Thomas LM, D’Ambruoso L, Balabanova D. Verbal autopsy in health policy and systems: a literature review. BMJ Glob Health. 2018;3:e000639. doi:10.1136/bmjgh-2017-000639.",
        "9. Ohemeng-Dapaah S, Pronyk P, Akosa E, Nemser B, Kanter AS. Combining vital events registration, verbal autopsy and electronic medical records in rural Ghana for improved health services delivery. Stud Health Technol Inform. 2010;160:416–420.",
        "10. World Health Organization. ICD-11 for Mortality and Morbidity Statistics. https://icd.who.int/.",
    ]
    add_zotero_bibliography(doc, "\n".join(refs))
    p = doc.add_paragraph()
    p.add_run("Reference pending import into Zotero: ").bold = True
    p.add_run("Benara SK, Sharma S, Juneja A, et al. Evaluation of methods for assigning causes of death from verbal autopsies in India. Front Big Data. 2023;6:1197471. doi:10.3389/fdata.2023.1197471.")
    p = doc.add_paragraph()
    p.add_run("Software source: ").bold = True
    p.add_run("DigitVA repository. Architecture overview, ODK sync, workflow and permissions, data-manager dashboard, current data model and ICD-11 planning documents. Version reviewed 22 September 2026.")

    doc.add_section(WD_SECTION.NEW_PAGE)
    doc.add_heading("Author completion checklist", level=1)
    for text in [
        "Confirm whether the target length was approximately 2,000 words; this full scientific draft is intentionally longer to cover all requested sections.",
        "Complete authors, affiliations, corresponding author and contribution statement.",
        "Insert the ethics approvals, consent pathway and data governance for UNSW and ICMR.",
        "Confirm the final study cut-off date and rerun the operational count query immediately before submission.",
        "Open the manuscript in Microsoft Word with Zotero installed, select the journal citation style and run Zotero Refresh; import and link the Benara et al. reference first so that it joins the live bibliography.",
        "Add prospective performance measures or clearly retain the paper as a system description and implementation report.",
        "Complete funding, software governance and competing-interest statements.",
    ]:
        add_bullet(doc, text)

    props = doc.core_properties
    props.title = "DigitVA for verbal autopsy coding and mortality intelligence"
    props.subject = "Draft manuscript for npj Digital Medicine"
    props.author = "Vivek Gupta and collaborators"
    props.keywords = "verbal autopsy; cause of death; digital health; ICD-11; physician coding; SmartVA"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build()
