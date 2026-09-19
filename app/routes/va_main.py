"""Core public routes — index page."""

from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, send_from_directory, url_for

va_main = Blueprint("va_main", __name__)

WHO_VA_STANDARDS_URL = (
    "https://www.who.int/standards/classifications/other-classifications/"
    "verbal-autopsy-standards-ascertaining-and-attributing-causes-of-death-tool"
)

WHO_VA_DOCUMENTS = {
    "2022-who-va-instrument.pdf": {
        "filename": "2022 - verbal-autopsy-standards_2022-who-verbal-autopsy-instrument.pdf",
        "label": "WHO VA 2022 Instrument",
    },
    "2022-va-field-interviewer-manual.pdf": {
        "filename": "2022-va-field-interviewer-manual.pdf",
        "label": "Field Interviewer Manual",
    },
    "2022-who-va-manual-for-interviewers.pdf": {
        "filename": "2022-who-va-manual-for-interviewers.pdf",
        "label": "Interviewer Manual",
    },
    "2022-who-va-manual-for-supervisors.pdf": {
        "filename": "2022-who-va-manual-for-supervisors.pdf",
        "label": "Supervisor Manual",
    },
    "2025-odk-4-va-quick-guide-v2.pdf": {
        "filename": "2025 - odk 4 va-quick-guide-v2.pdf",
        "label": "ODK 4 VA Quick Guide",
    },
    "2026-pcva-manual-for-physician-reviewers.pdf": {
        "filename": "2026 - pcva_manual-for-physician-reviewers.pdf",
        "label": "Manual for Physician Reviewers",
    },
}


def _who_va_document_dir() -> Path:
    return Path(current_app.root_path).parent / "docs" / "kb" / "WHO_VA_2022_Docs"


def _document_link(slug: str) -> dict[str, str]:
    document = WHO_VA_DOCUMENTS[slug]
    return {
        "label": document["label"],
        "href": url_for("va_main.who_va_document", document_slug=slug),
        "external": False,
    }


def _who_va_related_documents() -> dict[str, list[dict[str, str | bool]]]:
    standards_link = {
        "label": "WHO VA Standards",
        "href": WHO_VA_STANDARDS_URL,
        "external": True,
    }
    return {
        "conducting": [
            standards_link,
            _document_link("2022-who-va-instrument.pdf"),
            _document_link("2022-va-field-interviewer-manual.pdf"),
            _document_link("2022-who-va-manual-for-interviewers.pdf"),
            _document_link("2022-who-va-manual-for-supervisors.pdf"),
            _document_link("2025-odk-4-va-quick-guide-v2.pdf"),
        ],
        "ascertainment": [
            standards_link,
            _document_link("2022-who-va-instrument.pdf"),
            _document_link("2026-pcva-manual-for-physician-reviewers.pdf"),
        ],
    }


@va_main.route("/")
@va_main.route("/index")
@va_main.route("/vaindex")
def va_index():
    return render_template(
        "va_frontpages/va_index.html",
        who_va_related_documents=_who_va_related_documents(),
    )


@va_main.route("/who-va-documents/<path:document_slug>")
def who_va_document(document_slug):
    document = WHO_VA_DOCUMENTS.get(document_slug)
    if document is None:
        abort(404)
    document_dir = _who_va_document_dir()
    if not (document_dir / document["filename"]).is_file():
        abort(404)
    return send_from_directory(
        document_dir,
        document["filename"],
        mimetype="application/pdf",
    )
