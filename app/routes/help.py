"""Help blueprint – user-facing documentation grounded in policy."""

import os
import re

import markdown2
from flask import Blueprint, render_template, abort
from flask_login import current_user

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
    ("icd-codes",             "ICD-10 Codes & WHO Browser",   "fa-book-medical",         "Coding Workflow",  ["coder", "coding_tester", "reviewer", "admin"]),
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

    with open(abs_path, "r", encoding="utf-8") as f:
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
