"""Help blueprint – user-facing documentation grounded in policy."""

import csv
import io
import os
import re

import markdown2
from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
)
from flask_login import current_user

from app import limiter, talisman
from app.services.icd10_2019_2_service import (
    AGE_GROUP_SELECTABLE_OPTIONS,
    SEX_SELECTABLE_OPTIONS,
    get_icd10_2019_2_node_details,
    list_icd10_2019_2_children,
)
from app.services.icd11_mms_service import (
    get_icd11_mms_node_details,
    list_icd11_mms_children,
)
from app.services.va_code_mapping_public_service import (
    ANNEX_FILE_NAME,
    CLASSIFICATION_LABELS,
    CSV_HEADERS,
    ICD10_CSV_HEADERS,
    ICD11_CSV_HEADERS,
    ICD11_ORIGIN_FILTER_LABELS,
    ICD11_ORIGIN_FILTERS,
    ICD11_RELEASE,
    ORIGIN_DIGITVA,
    ORIGIN_LABELS,
    ORIGIN_TONES,
    POLICY_REVIEW_FILTERS,
    SELECTABLE_FILTERS,
    cached_icd11_state_csv,
    compare_trees,
    count_unmapped_icd10,
    count_unmapped_icd11,
    csv_cell,
    filter_icd10_catalogue,
    filter_icd11_catalogue,
    filter_mappings,
    get_icd10_catalogue,
    get_icd11_browser_hierarchy,
    get_icd11_catalogue,
    get_public_mappings,
    icd10_code_states,
    icd10_state_csv_row,
    icd11_code_states,
    icd11_state_csv_row,
    public_origin_display,
)

help_bp = Blueprint("help", __name__, template_folder="../templates/help")

# ---------------------------------------------------------------------------
# Project root – used to resolve docs/ paths
# ---------------------------------------------------------------------------
# __file__ = .../app/routes/help.py  →  need 3 dirname calls to reach repo root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Canonical help page registry
# ---------------------------------------------------------------------------
# (slug, title, icon, category, roles)
# roles = None means visible to everyone (including unauthenticated)
HELP_PAGES = [
    # ── Getting Started ──────────────────────────────────────────────
    ("getting-started",       "Getting Started",              "fa-rocket",               "Getting Started",  None),
    # ── User Onboarding ──────────────────────────────────────────────
    ("authentication",        "Logging In & Authentication",  "fa-right-to-bracket",     "User Onboarding",  None),
    ("password-reset",        "Password Reset",               "fa-key",                  "User Onboarding",  None),
    ("email-verification",    "Email Verification",           "fa-envelope-circle-check", "User Onboarding",  None),
    # ── User Roles ───────────────────────────────────────────────────
    ("user-roles",            "User Roles & Permissions",     "fa-users-gear",           "User Roles",       None),
    # ── Coding Workflow ──────────────────────────────────────────────
    ("demo-coding",           "Demo / Training Coding",       "fa-graduation-cap",       "Coding Workflow",  ["coder", "coding_tester", "admin"]),
    ("coding-tester",         "Coding Tester Workflow",       "fa-vial",                 "Coding Workflow",  ["coding_tester", "admin"]),
    ("coding-workflow",       "Coding Workflow (Step 1 & 2)", "fa-code",                 "Coding Workflow",  ["coder", "coding_tester", "reviewer", "admin"]),
    ("icd-codes",             "ICD Codes, VA Causes & Search", "fa-book-medical",        "Coding Workflow",  ["coder", "coding_tester", "reviewer", "admin"]),
    ("icd10-codes",           "ICD-10 Code Browser",           "fa-book-medical",        "Coding Workflow",  None),
    ("icd11-codes",           "ICD-11 Code Browser",           "fa-book-medical",        "Coding Workflow",  None),
    ("va-definitions",        "VA Cause Definitions",         "fa-list-check",           "Coding Workflow",  ["coder", "coding_tester", "reviewer", "admin"]),
    ("va-code-mappings",      "ICD to VA Cause Mappings",     "fa-table-list",           "Coding Workflow",  None),
    ("recode-window",         "Recode Window & Time Limits",  "fa-clock-rotate-left",    "Coding Workflow",  ["coder", "coding_tester", "reviewer", "admin"]),
    ("viewing-history",       "Viewing Coding History",       "fa-clock-rotate-left",    "Coding Workflow",  ["coder", "coding_tester", "reviewer", "admin"]),
    # ── Data Manager ─────────────────────────────────────────────────
    ("dm-dashboard",          "Data Manager Dashboard",       "fa-folder-open",          "Data Manager",     ["data_manager", "admin"]),
    ("dm-operations",         "Data Manager Operations",      "fa-list-check",           "Data Manager",     ["data_manager", "admin"]),
    ("dm-grants",             "Managing User Grants (DM)",    "fa-user-shield",          "Data Manager",     ["data_manager", "admin"]),
    # ── COD Buckets & Reporting ──────────────────────────────────────
    ("cod-buckets",           "COD Buckets & Reports",        "fa-chart-pie",            "Reporting",        ["data_manager", "admin"]),
    ("kpis",                  "KPI Dashboard",                "fa-gauge-high",           "Reporting",        ["data_manager", "admin"]),
    # ── Profile ──────────────────────────────────────────────────────
    ("profile",               "My Profile",                   "fa-user",                 "Account",          None),
    # ── Administration ───────────────────────────────────────────────
    ("admin-overview",        "Admin Panel Overview",         "fa-gear",                 "Administration",   ["admin"]),
    ("odk-connections",       "ODK Connections",              "fa-plug",                 "Administration",   ["admin"]),
    ("projects",              "Projects",                     "fa-diagram-project",      "Administration",   ["admin"]),
    ("sites",                 "Sites",                        "fa-location-dot",         "Administration",   ["admin"]),
    ("project-sites",         "Project-Site Settings",        "fa-link",                 "Administration",   ["admin", "project_pi"]),
    ("project-forms",         "Project-Form Settings",        "fa-file-lines",           "Administration",   ["admin"]),
    ("sync-behavior",         "Sync Behavior & Dashboard",    "fa-arrows-rotate",        "Administration",   ["admin"]),
]

# ---------------------------------------------------------------------------
# Curated engineering docs exposed publicly
# ---------------------------------------------------------------------------
# (slug, title, icon, doc_category, relative path from project root)
ENGINEERING_DOCS = [
    # ── Architecture ────────────────────────────────────────────────
    ("arch-overview",              "Architecture Overview",        "fa-sitemap",            "Architecture",
     "docs/current-state/architecture-overview.md"),
    ("data-model",                 "Data Model",                   "fa-database",           "Architecture",
     "docs/current-state/data-model.md"),
    ("async-tasks",                "Async Tasks (Celery)",         "fa-gears",              "Architecture",
     "docs/current-state/async-tasks.md"),
    ("submission-analytics",       "Submission Analytics",         "fa-chart-bar",          "Architecture",
     "docs/current-state/submission-analytics.md"),
    # ── Data Pipeline ───────────────────────────────────────────────
    ("odk-sync-arch",              "ODK Sync Pipeline",            "fa-arrows-rotate",      "Data Pipeline",
     "docs/current-state/odk-sync.md"),
    ("odk-sync-policy",            "ODK Sync Policy",              "fa-file-contract",      "Data Pipeline",
     "docs/policy/odk-sync-policy.md"),
    ("odk-connection-guard",       "ODK Connection Guard",         "fa-shield",             "Data Pipeline",
     "docs/policy/odk-connection-guard.md"),
    ("sync-dashboard",             "Sync Dashboard Operations",    "fa-gauge",              "Data Pipeline",
     "docs/policy/sync-dashboard-operations.md"),
    ("odk-repair",                 "ODK Repair Workflow",          "fa-wrench",             "Data Pipeline",
     "docs/current-state/odk-repair-workflow.md"),
    # ── Coding Workflow ─────────────────────────────────────────────
    ("wf-state-machine",           "Workflow State Machine",       "fa-diagram-project",    "Coding Workflow",
     "docs/policy/coding-workflow-state-machine.md"),
    ("wf-permissions",             "Workflow & Permissions",       "fa-shield-halved",      "Coding Workflow",
     "docs/current-state/workflow-and-permissions.md"),
    ("coding-timeouts",            "Coding Allocation Timeouts",   "fa-hourglass-half",     "Coding Workflow",
     "docs/policy/coding-allocation-timeouts.md"),
    ("final-cod",                  "Final COD Authority",          "fa-gavel",              "Coding Workflow",
     "docs/policy/final-cod-authority.md"),
    ("demo-retention",             "Demo Coding Retention",        "fa-graduation-cap",     "Coding Workflow",
     "docs/policy/demo-coding-retention.md"),
    ("nqa-policy",                 "Narrative Quality Assessment", "fa-check-double",       "Coding Workflow",
     "docs/policy/narrative-quality-assessment.md"),
    ("social-autopsy",             "Social Autopsy Analysis",      "fa-people-group",       "Coding Workflow",
     "docs/policy/social-autopsy-analysis.md"),
    # ── SmartVA ─────────────────────────────────────────────────────
    ("smartva-analysis",           "SmartVA Analysis",             "fa-brain",              "SmartVA",
     "docs/current-state/smartva-analysis.md"),
    ("smartva-policy",             "SmartVA Generation Policy",    "fa-robot",              "SmartVA",
     "docs/policy/smartva-generation-policy.md"),
    ("smartva-keywords",           "SmartVA Keyword Processing",   "fa-key",                "SmartVA",
     "docs/current-state/smartva-keyword-processing.md"),
    # ── ICD-10 & COD Reporting ──────────────────────────────────────
    ("icd-browser-policy",         "ICD-10 Browser Policy",        "fa-book-medical",       "ICD-10 & COD Reporting",
     "docs/policy/icd10-browser-policy.md"),
    ("icd-catalog",                "ICD-10 Reference Catalog",     "fa-list-ol",            "ICD-10 & COD Reporting",
     "docs/policy/icd10-reference-catalog.md"),
    ("icd-allowability",           "ICD-10 Coding Allowability",   "fa-filter",             "ICD-10 & COD Reporting",
     "docs/policy/who-2022-icd10-coding-allowability.md"),
    ("cod-bucket-reporting-arch",  "COD Bucket Reporting",         "fa-chart-pie",          "ICD-10 & COD Reporting",
     "docs/current-state/cod-bucket-reporting.md"),
    ("cod-bucket-policy",          "COD Bucket Reporting Policy",  "fa-chart-simple",       "ICD-10 & COD Reporting",
     "docs/policy/cod-bucket-reporting.md"),
    ("cod-snapshot-export",        "COD Snapshot Export",          "fa-file-export",        "ICD-10 & COD Reporting",
     "docs/policy/data-management-cod-snapshot-export.md"),
    ("age-derivation",             "WHO 2022 Age Derivation",      "fa-calculator",         "ICD-10 & COD Reporting",
     "docs/policy/who-2022-age-derivation.md"),
    # ── Field Mapping ───────────────────────────────────────────────
    ("field-mapping",              "Field Mapping System",         "fa-table-list",         "Field Mapping",
     "docs/current-state/field-mapping-system.md"),
    ("category-rendering",         "Category Rendering",           "fa-layer-group",        "Field Mapping",
     "docs/current-state/category-rendering-and-visibility.md"),
    # ── Access Control ──────────────────────────────────────────────
    ("access-control",             "Access Control Model",         "fa-user-lock",          "Access Control",
     "docs/policy/access-control-model.md"),
    ("admin-api-access",           "Admin API Access",             "fa-key",                "Access Control",
     "docs/policy/admin-api-access.md"),
    ("password-policy",            "Password Breach Checks",       "fa-lock",               "Access Control",
     "docs/policy/password-breach-checks.md"),
    ("request-abuse",              "Request Method Abuse Control", "fa-ban",                "Access Control",
     "docs/policy/request-method-abuse-control.md"),
    # ── Data Manager ────────────────────────────────────────────────
    ("dm-dashboard-arch",          "Data Manager Dashboard",       "fa-folder-open",        "Data Manager",
     "docs/current-state/data-manager-dashboard.md"),
    ("dm-workflow",                "Data Manager Workflow",        "fa-clipboard-list",     "Data Manager",
     "docs/policy/data-manager-workflow.md"),
    ("dm-grants-doc",              "DM User Grant Management",     "fa-user-shield",        "Data Manager",
     "docs/policy/dm-user-grant-management.md"),
    ("kpi-framework",              "KPI Framework",                "fa-gauge-high",         "Data Manager",
     "docs/policy/kpis.md"),
    # ── Operations ──────────────────────────────────────────────────
    ("site-maintenance",           "Site Maintenance Mode",        "fa-wrench",             "Operations",
     "docs/policy/site-maintenance-mode.md"),
    ("not-codeable-sync",          "Not Codeable ODK Sync",        "fa-triangle-exclamation", "Operations",
     "docs/policy/not-codeable-odk-central-sync.md"),
]

_ENG_DOCS_BY_SLUG = {d[0]: d for d in ENGINEERING_DOCS}
_ENG_DOC_SLUGS = set(_ENG_DOCS_BY_SLUG.keys())

# Build ordered list of unique doc categories
_ENG_DOC_CATEGORIES = []
_seen_eng_cats = set()
for _d in ENGINEERING_DOCS:
    if _d[3] not in _seen_eng_cats:
        _ENG_DOC_CATEGORIES.append(_d[3])
        _seen_eng_cats.add(_d[3])

# ---------------------------------------------------------------------------
# Build category lists for help pages
# ---------------------------------------------------------------------------
_PAGES_BY_SLUG = {p[0]: p for p in HELP_PAGES}
_CATEGORIES = []
_seen_cats = set()
for _p in HELP_PAGES:
    if _p[3] not in _seen_cats:
        _CATEGORIES.append(_p[3])
        _seen_cats.add(_p[3])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_has_role(user, roles):
    """Check if current user has any of the required roles."""
    if roles is None:
        return True
    if not user.is_authenticated:
        return False
    if user.is_admin():
        return True
    for role in roles:
        method = getattr(user, f"is_{role}", None)
        if method and method():
            return True
    return False


def _visible_pages(user):
    """Return help pages visible to the given user."""
    return [p for p in HELP_PAGES if _user_has_role(user, p[4])]


def _strip_yaml_front_matter(text):
    """Remove YAML front matter (--- delimited) from markdown text."""
    return re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.DOTALL)


def _render_md(rel_path):
    """Read a markdown file and return HTML."""
    abs_path = os.path.join(_PROJECT_ROOT, rel_path)
    if not os.path.isfile(abs_path):
        abort(404)
    # Prevent path traversal
    real = os.path.realpath(abs_path)
    if not real.startswith(os.path.realpath(_PROJECT_ROOT)):
        abort(403)

    with open(abs_path, encoding="utf-8") as f:
        raw = f.read()

    md_text = _strip_yaml_front_matter(raw)
    html = markdown2.markdown(
        md_text,
        extras=[
            "fenced-code-blocks",
            "tables",
            "header-ids",
            "toc",
            "strike",
            "task_list",
            "code-friendly",
            "cuddled-lists",
        ],
    )
    return html


# ---------------------------------------------------------------------------
# Common template context
# ---------------------------------------------------------------------------

def _base_ctx():
    return dict(
        categories=_CATEGORIES,
        visible_pages=_visible_pages,
        user_has_role=_user_has_role,
        all_pages=HELP_PAGES,
        engineering_docs=ENGINEERING_DOCS,
        eng_doc_categories=_ENG_DOC_CATEGORIES,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@help_bp.route("/help")
def index():
    """Help index with search."""
    return render_template("help/help_base.html", **_base_ctx())


@help_bp.route("/help/<slug>")
def page(slug):
    """Render a specific help page."""
    if slug not in _PAGES_BY_SLUG:
        abort(404)

    page_info = _PAGES_BY_SLUG[slug]

    if not _user_has_role(current_user, page_info[4]):
        abort(403)

    template_name = f"help/pages/{slug}.html"
    return render_template(
        "help/help_base.html",
        page_slug=slug,
        page_title=page_info[1],
        page_icon=page_info[2],
        page_category=page_info[3],
        page_template=template_name,
        **_base_ctx(),
    )


@help_bp.route("/help/icd-codes/search-demo")
@talisman(content_security_policy={
    "default-src": "'self'",
    "script-src": "'self' 'unsafe-inline'",
    "style-src": "'self' 'unsafe-inline'",
    "img-src": "'self' data:",
    "media-src": "'self'",
    "font-src": "'self' data:",
    "connect-src": "'self' http://127.0.0.1:8382",
})
def icd_codes_search_demo():
    """Live coding-search demo: try the real search without opening a death."""
    page_info = _PAGES_BY_SLUG["icd-codes"]
    if not _user_has_role(current_user, page_info[4]):
        abort(403)
    return render_template(
        "help/help_base.html",
        page_slug=page_info[0],
        page_title="Try the Coding Search",
        page_icon=page_info[2],
        page_category=page_info[3],
        page_template="help/pages/icd-codes-search-demo.html",
        **_base_ctx(),
    )


@help_bp.route("/help/docs")
def docs_index():
    """Engineering docs index."""
    return render_template(
        "help/help_base.html",
        page_slug="__docs_index__",
        page_title="Engineering Docs",
        page_icon="fa-file-code",
        page_category="Engineering Docs",
        **_base_ctx(),
    )


@help_bp.route("/help/docs/<slug>")
def doc_page(slug):
    """Render a curated engineering doc as HTML."""
    if slug not in _ENG_DOCS_BY_SLUG:
        abort(404)

    doc_info = _ENG_DOCS_BY_SLUG[slug]
    html_content = _render_md(doc_info[4])  # index 4 = path
    return render_template(
        "help/help_base.html",
        page_slug=f"doc:{slug}",
        page_title=doc_info[1],
        page_icon=doc_info[2],
        page_category="Engineering Docs",
        doc_html=html_content,
        **_base_ctx(),
    )


# ---------------------------------------------------------------------------
# Public ICD-to-VA-cause mapping list (docs/policy/icd10-to-icd11-transition.md s7)
# ---------------------------------------------------------------------------

MAPPINGS_PER_PAGE = 100
_MAX_QUERY_LEN = 100


def _mapping_filters(va_causes):
    """Validated filters from the query string; anything unknown is ignored."""
    classification = request.args.get("classification", "").strip()
    origin = request.args.get("origin", "").strip()
    va_code = request.args.get("va_code", "").strip()
    return {
        "q": request.args.get("q", "").strip()[:_MAX_QUERY_LEN],
        "classification": classification if classification in CLASSIFICATION_LABELS else "",
        "origin": origin if origin in ORIGIN_LABELS or origin == ORIGIN_DIGITVA else "",
        "va_code": va_code if va_code in {code for code, _ in va_causes} else "",
    }


def _page_bounds(total):
    """`(page_no, page_count, start)` for the `page` argument, clamped to the pages that exist."""
    page_count = max(1, -(-total // MAPPINGS_PER_PAGE))
    page_no = min(max(request.args.get("page", 1, type=int) or 1, 1), page_count)
    return page_no, page_count, (page_no - 1) * MAPPINGS_PER_PAGE


def _mapping_page_ctx(template):
    """Sidebar and heading of the mapping list, for its sub-pages."""
    page_info = _PAGES_BY_SLUG["va-code-mappings"]
    return dict(
        page_slug=page_info[0],
        page_title=page_info[1],
        page_icon=page_info[2],
        page_category=page_info[3],
        page_template=template,
        **_base_ctx(),
    )


def _csv_response(header, rows, filename):
    """Stream `rows` (lists of cells) as a CSV attachment."""
    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
        yield buffer.getvalue()

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@help_bp.route("/help/va-code-mappings")
@limiter.limit("60 per minute")
def va_code_mappings():
    """Public, paged list of WHO_2022_VA_2026 ICD-to-VA-cause mappings."""
    rows, va_causes = get_public_mappings()
    filters = _mapping_filters(va_causes)
    matches = filter_mappings(rows, **filters)
    page_no, page_count, start = _page_bounds(len(matches))
    return render_template(
        "help/help_base.html",
        mapping_rows=matches[start:start + MAPPINGS_PER_PAGE],
        mapping_total=len(matches),
        mapping_all_total=len(rows),
        mapping_page=page_no,
        mapping_page_count=page_count,
        mapping_filters=filters,
        mapping_link_args={key: value for key, value in filters.items() if value},
        mapping_va_causes=va_causes,
        origin_labels=ORIGIN_LABELS,
        origin_tones=ORIGIN_TONES,
        classification_labels=CLASSIFICATION_LABELS,
        annex_file_name=ANNEX_FILE_NAME,
        **_mapping_page_ctx("help/pages/va-code-mappings.html"),
    )


@help_bp.route("/help/va-code-mappings.csv")
@limiter.limit("60 per minute")
def va_code_mappings_csv():
    """The same list as CSV, all rows matching the filters, streamed."""
    rows, va_causes = get_public_mappings()
    matches = filter_mappings(rows, **_mapping_filters(va_causes))
    return _csv_response(
        CSV_HEADERS,
        ([csv_cell(row[column]) for column in CSV_HEADERS] for row in matches),
        "who_2022_va_2026_icd_mappings.csv",
    )


_COMPARE_COLUMNS = [
    {"id": "code", "title": "Chapter / block / code"},
    {"id": "origin", "title": "Origin", "width": "260px"},
]
@help_bp.route("/help/va-code-mappings/compare")
@limiter.limit("60 per minute")
def va_code_mappings_compare():
    """ICD-10 and ICD-11 codes mapped to one VA cause, side by side as trees."""
    rows, va_causes = get_public_mappings()
    va_code = request.args.get("va_code", "").strip()
    if va_code not in {code for code, _ in va_causes}:
        va_code = ""
    trees = compare_trees(rows, va_code, get_icd11_catalogue()) if va_code else {"icd10": [], "icd11": []}
    counts = {key: sum(1 for node in nodes if "cells" in node) for key, nodes in trees.items()}
    return render_template(
        "help/help_base.html",
        compare_va_code=va_code,
        compare_trees=trees,
        compare_counts=counts,
        compare_columns=_COMPARE_COLUMNS,
        mapping_va_causes=va_causes,
        **_mapping_page_ctx("help/pages/va-code-mappings-compare.html"),
    )


def _icd11_state_filters():
    """Validated filters of the public ICD-11 browser; unknowns are ignored."""
    selectable = request.args.get("selectable", "").strip()
    if not selectable:
        selectable = {"active": "yes", "disabled": "no"}.get(
            request.args.get("coding_filter", "").strip(), ""
        )
    origin = request.args.get("origin", "").strip()
    policy_status = request.args.get("policy_status", "").strip()
    sex = request.args.get("sex_filter", request.args.get("sex", "")).strip()
    age = request.args.get("age_filter", request.args.get("age", "")).strip()
    return {
        "q": request.args.get("q", "").strip()[:_MAX_QUERY_LEN],
        "selectable": selectable if selectable in SELECTABLE_FILTERS else "",
        "origin": origin if origin in ICD11_ORIGIN_FILTERS else "",
        "policy_status": policy_status if policy_status in POLICY_REVIEW_FILTERS else "",
        "sex_filter": sex if sex in SEX_SELECTABLE_OPTIONS else "",
        "age_filter": age if age in AGE_GROUP_SELECTABLE_OPTIONS else "",
    }


def _icd10_state_filters():
    """Validated filters for the public ICD-10 catalogue."""
    selectable = request.args.get("selectable", "").strip()
    if not selectable:
        selectable = {"active": "yes", "disabled": "no"}.get(
            request.args.get("coding_filter", "").strip(), ""
        )
    origin = request.args.get("origin", "").strip()
    policy_status = request.args.get("policy_status", "").strip()
    sex = request.args.get("sex", request.args.get("sex_filter", "")).strip()
    age = request.args.get("age", request.args.get("age_filter", "")).strip()
    return {
        "q": request.args.get("q", "").strip()[:_MAX_QUERY_LEN],
        "selectable": selectable if selectable in SELECTABLE_FILTERS else "",
        "origin": origin if origin in ICD11_ORIGIN_FILTERS else "",
        "policy_status": policy_status if policy_status in POLICY_REVIEW_FILTERS else "",
        "sex_filter": sex if sex in SEX_SELECTABLE_OPTIONS else "",
        "age_filter": age if age in AGE_GROUP_SELECTABLE_OPTIONS else "",
    }


@help_bp.route("/help/icd10-codes")
@limiter.limit("60 per minute")
def icd10_codes_browser():
    """Public read-only ICD-10 browser using the admin hierarchy panes."""
    rows, va_causes = get_public_mappings()
    catalogue = get_icd10_catalogue()
    filters = _icd10_state_filters()
    codes = _filtered_icd10_browser_codes(catalogue, rows, filters)
    page_info = _PAGES_BY_SLUG["icd10-codes"]
    return render_template(
        "help/help_base.html",
        page_slug=page_info[0],
        page_title=page_info[1],
        page_icon=page_info[2],
        page_category=page_info[3],
        page_template="help/pages/icd10-codes.html",
        state_total=len(codes),
        state_all_total=len(catalogue),
        state_unmapped_total=count_unmapped_icd10(catalogue, rows),
        state_filters=filters,
        state_link_args={key: value for key, value in filters.items() if value},
        origin_filter_labels=ICD11_ORIGIN_FILTER_LABELS,
        icd10_browser_read_only=True,
        icd10_browser_api_base="/help/icd10-codes",
        mapping_va_causes=va_causes,
        **_base_ctx(),
    )


@help_bp.route("/help/icd10-codes.csv")
@limiter.limit("60 per minute")
def icd10_codes_browser_csv():
    """Stream the public ICD-10 browser rows matching its current filters."""
    rows, _ = get_public_mappings()
    catalogue = get_icd10_catalogue()
    filters = _icd10_state_filters()
    codes = filter_icd10_catalogue(catalogue, rows, **filters)
    states = icd10_code_states(codes, catalogue, rows)
    return _csv_response(
        ICD10_CSV_HEADERS,
        (icd10_state_csv_row(state) for state in states),
        "who_2022_va_2026_icd10_code_states.csv",
    )


def _filtered_icd10_browser_codes(catalogue, rows, filters):
    return filter_icd10_catalogue(catalogue, rows, **filters)


def _icd10_browser_public_row(row, *, child_count=None):
    """Whitelist the safe fields needed by the shared read-only pane UI."""
    public = {
        key: row.get(key)
        for key in (
            "code",
            "title",
            "semantic_level",
            "child_count",
            "is_coding_selectable",
            "sex_selectable",
            "age_group_selectable",
            "restriction_note",
            "status_indicator",
            "ancestors",
        )
        if key in row
    }
    if child_count is not None:
        public["child_count"] = child_count
    return public


def _icd10_visible_child_counts(catalogue, visible):
    """Count only children that remain visible under all public filters."""
    children_by_parent = {}

    def add(parent, child):
        if parent and child:
            children_by_parent.setdefault(parent, set()).add(child)

    for code in visible:
        entry = catalogue.get(code)
        if entry is None:
            continue
        chapter_code = entry["chapter"][0]
        block_code = entry["block"][0]
        if entry["semantic_level"] in {"three_character", "detailed_code"}:
            add(chapter_code, block_code)
        if entry["semantic_level"] == "three_character":
            add(block_code, code)
        elif entry["semantic_level"] == "detailed_code":
            add(entry["parent_code"], code)

    return {parent: len(children) for parent, children in children_by_parent.items()}


def _icd10_context_codes(codes, catalogue):
    """Keep matching codes and their hierarchy ancestors visible in the panes."""
    visible = set()
    for code in codes:
        current = code
        while current and current not in visible:
            visible.add(current)
            entry = catalogue.get(current)
            if entry is None:
                break
            current = entry.get("parent_code")
        entry = catalogue.get(code, {})
        visible.update(
            value[0]
            for value in (entry.get("chapter", ("", "")), entry.get("block", ("", "")))
            if value[0]
        )
    return visible


def _icd10_browser_matching_state():
    rows, _ = get_public_mappings()
    catalogue = get_icd10_catalogue()
    filters = _icd10_state_filters()
    codes = _filtered_icd10_browser_codes(catalogue, rows, filters)
    return rows, catalogue, filters, codes, _icd10_context_codes(codes, catalogue)


@help_bp.get("/help/icd10-codes/children")
@limiter.limit("60 per minute")
def icd10_codes_browser_children():
    """Publicly expose one filtered hierarchy level with curated row fields."""
    parent_code = (request.args.get("parent_code") or "").strip().upper() or None
    if parent_code and len(parent_code) > 16:
        return jsonify({"error": "Invalid parent_code."}), 400
    rows, catalogue, filters, codes, visible = _icd10_browser_matching_state()
    coding_filter = {"yes": "active", "no": "disabled"}.get(filters["selectable"], "any")
    children = list_icd10_2019_2_children(
        parent_code,
        coding_filter=coding_filter,
        sex_filter=filters["sex_filter"] or "any",
        age_filter=filters["age_filter"] or "any",
    )
    visible_child_counts = _icd10_visible_child_counts(catalogue, visible)
    safe_children = [
        _icd10_browser_public_row(
            child,
            child_count=visible_child_counts.get(child["code"], 0),
        )
        for child in children
        if child["code"] in visible
    ]
    return jsonify({
        "parent_code": parent_code,
        "children": safe_children,
        "matching_code_count": len(codes),
        "all_code_count": len(catalogue),
        "unmapped_code_count": count_unmapped_icd10(catalogue, rows),
    })


@help_bp.get("/help/icd10-codes/node/<code>")
@limiter.limit("60 per minute")
def icd10_codes_browser_node(code):
    """Return safe details for one selected code, with its public VA mapping."""
    payload = get_icd10_2019_2_node_details(code.strip().upper())
    if payload is None:
        return jsonify({"error": "ICD-10 code not found."}), 404
    public = _icd10_browser_public_row(payload)
    public["ancestors"] = [
        {key: ancestor.get(key) for key in ("code", "title", "semantic_level")}
        for ancestor in payload.get("ancestors", [])
    ]
    catalogue = get_icd10_catalogue()
    if payload["code"] in catalogue:
        rows, _ = get_public_mappings()
        state = icd10_code_states([payload["code"]], catalogue, rows)[0]
        origin = public_origin_display(state)
        public.update({
            "policy_status": state["policy_status"],
            "va_code": state["va_code"],
            "va_title": state["va_title"],
            "origin": state["origin"] or "unmapped",
            "origin_badge": origin["badge"],
            "origin_tone": origin["tone"],
            "origin_reason": origin["note"],
            "origin_tooltip": origin["title"],
            "also_claimed_by": state["also_claimed_by"],
        })
    else:
        public.update({
            "policy_status": "",
            "va_code": "",
            "va_title": "",
            "origin": "",
            "origin_badge": "",
            "origin_tone": "secondary",
            "origin_reason": "",
            "origin_tooltip": "",
            "also_claimed_by": "",
        })
    return jsonify(public)


@help_bp.get("/help/icd10-codes/search")
@limiter.limit("60 per minute")
def icd10_codes_browser_search():
    """Search public ICD-10 codes and return bounded pane-navigation targets."""
    query = (request.args.get("q") or "").strip()[:_MAX_QUERY_LEN]
    if len(query) < 2:
        return jsonify({"results": []})
    rows, catalogue, _filters, codes, _visible = _icd10_browser_matching_state()
    matching = [code for code in codes if query.lower() in catalogue[code]["_search"]]
    results = [
        {"code": code, "title": catalogue[code]["title"], "semantic_level": catalogue[code]["semantic_level"]}
        for code in matching[:30]
    ]
    return jsonify({"results": results, "total": len(matching)})


@help_bp.route("/help/va-code-mappings/unmapped")
@limiter.limit("60 per minute")
def va_code_mappings_unmapped():
    """Compatibility alias for the read-only ICD-11 pane browser."""
    return _render_icd11_codes_browser()


@help_bp.route("/help/icd11-codes")
@limiter.limit("60 per minute")
def icd11_codes_browser():
    """Canonical public ICD-11 browser using admin panes in read-only mode."""
    return _render_icd11_codes_browser()


def _render_icd11_codes_browser():
    rows, _ = get_public_mappings()
    catalogue = get_icd11_catalogue()
    filters = _icd11_state_filters()
    codes = filter_icd11_catalogue(catalogue, rows, **filters)
    page_info = _PAGES_BY_SLUG["icd11-codes"]
    return render_template(
        "help/help_base.html",
        page_slug=page_info[0],
        page_title=page_info[1],
        page_icon=page_info[2],
        page_category=page_info[3],
        page_template="help/pages/icd11-codes.html",
        state_total=len(codes),
        state_all_total=len(catalogue),
        state_unmapped_total=count_unmapped_icd11(catalogue, rows),
        state_filters=filters,
        state_link_args={key: value for key, value in filters.items() if value},
        origin_filter_labels=ICD11_ORIGIN_FILTER_LABELS,
        icd11_browser_read_only=True,
        icd11_browser_api_base="/help/icd11-codes",
        release=ICD11_RELEASE,
        **_base_ctx(),
    )


def _icd11_browser_state(hierarchy=None):
    rows, _ = get_public_mappings()
    catalogue = get_icd11_catalogue()
    if hierarchy is None:
        hierarchy = get_icd11_browser_hierarchy()
    filters = _icd11_state_filters()
    codes = filter_icd11_catalogue(catalogue, rows, **filters)
    visible = set()
    for code in codes:
        uri = hierarchy["uri_by_code"].get(code)
        while uri and uri in hierarchy["nodes"] and uri not in visible:
            visible.add(uri)
            uri = hierarchy["nodes"][uri]["parent_linearization_uri"]
    visible_child_counts = {}
    for uri in visible:
        parent_uri = hierarchy["nodes"][uri]["parent_linearization_uri"]
        if parent_uri:
            visible_child_counts[parent_uri] = visible_child_counts.get(parent_uri, 0) + 1
    return rows, catalogue, hierarchy, filters, codes, visible, visible_child_counts


def _icd11_browser_public_row(row, *, child_count=None):
    """Whitelist the fields needed to navigate and display a public node."""
    fields = (
        "linearization_uri", "parent_linearization_uri", "code", "title",
        "class_kind", "depth_in_kind", "chapter_no", "is_residual", "is_leaf",
        "is_coding_selectable", "sex_selectable", "age_group_selectable",
        "policy_status", "restriction_note", "coding_note", "status_indicator",
    )
    public = {key: row.get(key) for key in fields if key in row}
    if child_count is not None:
        public["child_count"] = child_count
    return public


@help_bp.get("/help/icd11-codes/children")
@limiter.limit("60 per minute")
def icd11_codes_browser_children():
    """Return one safely projected public hierarchy pane."""
    parent_uri = (request.args.get("parent_linearization_uri") or "").strip() or None
    if parent_uri and len(parent_uri) > 512:
        return jsonify({"error": "ICD-11 node not found."}), 404
    hierarchy = get_icd11_browser_hierarchy() if parent_uri else None
    if parent_uri and parent_uri not in hierarchy["nodes"]:
        return jsonify({"error": "ICD-11 node not found."}), 404
    rows, catalogue, hierarchy, filters, codes, visible, visible_child_counts = (
        _icd11_browser_state(hierarchy)
    )
    coding_filter = {"yes": "active", "no": "disabled"}.get(filters["selectable"], "any")
    children = list_icd11_mms_children(
        parent_uri,
        release=ICD11_RELEASE,
        coding_filter=coding_filter,
        sex_filter=filters["sex_filter"] or "any",
        age_filter=filters["age_filter"] or "any",
    )
    safe_children = [
        _icd11_browser_public_row(
            child,
            child_count=visible_child_counts.get(child["linearization_uri"], 0),
        )
        for child in children
        if child["linearization_uri"] in visible
    ]
    return jsonify({
        "parent_linearization_uri": parent_uri,
        "children": safe_children,
        "matching_code_count": len(codes),
        "all_code_count": len(catalogue),
        "unmapped_code_count": count_unmapped_icd11(catalogue, rows),
    })


@help_bp.get("/help/icd11-codes/node")
@limiter.limit("60 per minute")
def icd11_codes_browser_node():
    """Return a safe public node and its hierarchy path plus mapping state."""
    uri = (request.args.get("linearization_uri") or "").strip()
    if not uri or len(uri) > 512:
        return jsonify({"error": "ICD-11 node not found."}), 404
    rows, catalogue, hierarchy, _filters, _codes, _visible, visible_child_counts = (
        _icd11_browser_state()
    )
    if uri not in hierarchy["nodes"]:
        return jsonify({"error": "ICD-11 node not found."}), 404
    details = get_icd11_mms_node_details(uri, release=ICD11_RELEASE)
    if details is None:
        return jsonify({"error": "ICD-11 node not found."}), 404
    ancestor_uris = []
    parent_uri = hierarchy["nodes"][uri]["parent_linearization_uri"]
    while parent_uri and parent_uri in hierarchy["nodes"]:
        ancestor_uris.append(parent_uri)
        parent_uri = hierarchy["nodes"][parent_uri]["parent_linearization_uri"]
    details["ancestors"] = [hierarchy["nodes"][ancestor] for ancestor in reversed(ancestor_uris)]
    public = _icd11_browser_public_row(details)
    public["ancestors"] = [
        _icd11_browser_public_row(ancestor)
        for ancestor in details["ancestors"]
    ]
    public["child_count"] = visible_child_counts.get(uri, 0)
    if public["class_kind"] == "category" and public.get("code") in catalogue:
        state = icd11_code_states([public["code"]], catalogue, rows)[0]
        origin = public_origin_display(state)
        public.update({
            "va_code": state["va_code"],
            "va_title": state["va_title"],
            "origin": state["origin"] or "unmapped",
            "origin_badge": origin["badge"],
            "origin_tone": origin["tone"],
            "origin_reason": origin["note"],
            "origin_tooltip": origin["title"],
        })
    else:
        public.update({
            "va_code": "", "va_title": "", "origin": "",
            "origin_badge": "", "origin_tone": "secondary",
            "origin_reason": "", "origin_tooltip": "",
        })
    return jsonify(public)


@help_bp.get("/help/icd11-codes/search")
@limiter.limit("60 per minute")
def icd11_codes_browser_search():
    """Bounded search for public ICD-11 categories and pane reveal targets."""
    query = (request.args.get("q") or "").strip()[:_MAX_QUERY_LEN]
    if len(query) < 2:
        return jsonify({"results": []})
    _rows, catalogue, hierarchy, _filters, codes, _visible, _counts = _icd11_browser_state()
    matching = [code for code in codes if query.lower() in catalogue[code]["_search"]]
    return jsonify({
        "results": [
            {
                "linearization_uri": hierarchy["uri_by_code"].get(code, ""),
                "icd_code": code,
                "title": catalogue[code]["title"],
            }
            for code in matching[:30]
            if hierarchy["uri_by_code"].get(code)
        ],
        "total": len(matching),
    })


@help_bp.route("/help/va-code-mappings/unmapped.csv")
@limiter.limit("60 per minute")
def va_code_mappings_unmapped_csv():
    """Compatibility alias for the public ICD-11 browser CSV."""
    return _icd11_codes_browser_csv_response()


@help_bp.route("/help/icd11-codes.csv")
@limiter.limit("60 per minute")
def icd11_codes_browser_csv():
    """Download every ICD-11 category matching the browser filters."""
    return _icd11_codes_browser_csv_response()


def _icd11_codes_browser_csv_response():
    rows, _ = get_public_mappings()
    catalogue = get_icd11_catalogue()
    filters = _icd11_state_filters()

    def states():
        return icd11_code_states(filter_icd11_catalogue(catalogue, rows, **filters), catalogue, rows)

    filename = "who_2022_va_2026_icd11_code_states.csv"
    if not any(filters[key] for key in ("q", "origin", "policy_status", "sex_filter", "age_filter")):
        path = cached_icd11_state_csv(_public_csv_dir(), filters["selectable"], states)
        try:
            handle = open(path, "rb") if path else None
        except OSError:  # replaced by a newer version between check and open
            handle = None
        if handle is not None:
            return send_file(handle, mimetype="text/csv", as_attachment=True, download_name=filename)
    return _csv_response(ICD11_CSV_HEADERS, (icd11_state_csv_row(state) for state in states()), filename)


def _public_csv_dir():
    """File cache for public CSVs: APP_DATA/public_csv (instance/data if unset)."""
    app_data = current_app.config.get("APP_DATA") or os.path.join(current_app.instance_path, "data")
    return os.path.join(app_data, "public_csv")
