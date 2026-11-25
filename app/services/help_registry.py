"""The help page registry and its visibility rule.

``app.routes.help`` serves the pages; ``ai_search_service`` ranks and filters
them by the same rule, so the registry lives here rather than in the route
module (digitva-r8nh.13).
"""


# ---------------------------------------------------------------------------
# Canonical help page registry
# ---------------------------------------------------------------------------
# (slug, title, icon, category, roles)
# roles = None means visible to everyone (including unauthenticated)
# Owner 2026-11-06: every help page is public. organization-demo stays
# signed-in only: it lists sign-in links for the synthetic demo accounts.
HELP_PAGES = [
    # ── Getting Started ──────────────────────────────────────────────
    ("getting-started",       "Getting Started",              "fa-rocket",               "Getting Started",  None),
    ("organization-demo",     "Synthetic Organization Demo",  "fa-building-circle-check", "Getting Started", ["authenticated"]),
    ("training-demo",         "Training & Demo Project",      "fa-graduation-cap",       "Getting Started",  None),
    ("mobile-app",            "Get the Mobile App",           "fa-mobile-screen-button", "Getting Started", None),
    # ── User Onboarding ──────────────────────────────────────────────
    ("authentication",        "Logging In & Authentication",  "fa-right-to-bracket",     "User Onboarding",  None),
    ("password-reset",        "Password Reset",               "fa-key",                  "User Onboarding",  None),
    ("email-verification",    "Email Verification",           "fa-envelope-circle-check", "User Onboarding",  None),
    # ── User Roles ───────────────────────────────────────────────────
    ("user-roles",            "User Roles & Permissions",     "fa-users-gear",           "User Roles",       None),
    ("mentoring-institutes",  "Medical College & Mentoring Staff", "fa-building-columns", "User Roles",      None),
    # ── Data Collection ──────────────────────────────────────────────
    ("data-collection",       "Data Collection",              "fa-clipboard-question",   "Data Collection",  None),
    # ── Coding Workflow ──────────────────────────────────────────────
    ("demo-coding",           "Demo / Training Coding",       "fa-graduation-cap",       "Coding Workflow",  None),
    ("coding-tester",         "Coding Tester Workflow",       "fa-vial",                 "Coding Workflow",  None),
    ("coding-workflow",       "Coding Workflow (Step 1 & 2)", "fa-code",                 "Coding Workflow",  None),
    ("icd-codes",             "ICD Codes, VA Causes & Search", "fa-book-medical",        "Coding Workflow",  None),
    ("icd10-codes",           "ICD-10 Code Browser",           "fa-book-medical",        "Coding Workflow",  None),
    ("icd11-codes",           "ICD-11 Code Browser",           "fa-book-medical",        "Coding Workflow",  None),
    ("va-definitions",        "VA Cause Definitions",         "fa-list-check",           "Coding Workflow",  None),
    ("va-code-mappings",      "ICD to VA Cause Mappings",     "fa-table-list",           "Coding Workflow",  None),
    ("cod-bucket-schemes",    "COD Bucket Schemes",           "fa-sitemap",              "Coding Workflow",  None),
    ("recode-window",         "Recode Window & Time Limits",  "fa-clock-rotate-left",    "Coding Workflow",  None),
    ("viewing-history",       "Viewing Coding History",       "fa-clock-rotate-left",    "Coding Workflow",  None),
    # ── Data Manager ─────────────────────────────────────────────────
    ("dm-dashboard",          "Data Manager Dashboard",       "fa-folder-open",          "Data Manager",  None),
    ("dm-operations",         "Data Manager Operations",      "fa-list-check",           "Data Manager",  None),
    ("dm-grants",             "Managing User Grants (DM)",    "fa-user-shield",          "Data Manager",  None),
    # ── COD Buckets & Reporting ──────────────────────────────────────
    ("cod-buckets",           "COD Buckets & Reports",        "fa-chart-pie",            "Reporting",  None),
    ("kpis",                  "KPI Dashboard",                "fa-gauge-high",           "Reporting",  None),
    # ── Profile ──────────────────────────────────────────────────────
    ("profile",               "My Profile",                   "fa-user",                 "Account",          None),
    # ── Administration ───────────────────────────────────────────────
    ("admin-overview",        "Admin Panel Overview",         "fa-gear",                 "Administration",  None),
    ("odk-connections",       "ODK Connections",              "fa-plug",                 "Administration",  None),
    ("projects",              "Projects",                     "fa-diagram-project",      "Administration",  None),
    ("sites",                 "Sites",                        "fa-location-dot",         "Administration",  None),
    ("project-sites",         "Project-Site Settings",        "fa-link",                 "Administration",  None),
    ("project-forms",         "Project-Form Settings",        "fa-file-lines",           "Administration",  None),
    ("sync-behavior",         "Sync Behavior & Dashboard",    "fa-arrows-rotate",        "Administration",  None),
]


def _user_has_role(user, roles):
    """Check if current user has any of the required roles."""
    if roles is None:
        return True
    if not user.is_authenticated:
        return False
    if "authenticated" in roles:
        return True
    if user.is_admin():
        return True
    for role in roles:
        method = getattr(user, f"is_{role}", None)
        if method and method():
            return True
    return False
