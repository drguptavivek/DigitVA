"""The authorization vocabulary and rule tables (digitva-0wc).

``Action`` names what a person wants to do; ``Lens`` names one way a grant
resolves to submissions; ``RULES`` says which lenses open which action. The
predicate for an action is the OR of its lenses (``predicates.scope_filter``),
and ``can`` is that same predicate asked of one submission, so a list can
never offer what ``can`` refuses.

Policy: docs/policy/access-control-model.md, docs/policy/organization-model.md.
Design: .tasks/digitva-0wc-design.md, sections 1.2 and 2.
"""

from __future__ import annotations

import enum

from app.models import VaAccessRoles


class Action(enum.Enum):
    # target = va_sid
    VIEW = "view"                    # open read-only: shell, read partials, attachments, events
    CODE = "code"                    # start / pick / random pool / resume / coder saves
    RECODE = "recode"                # same scope as CODE; ownership and 24h window are workflow
    REVIEW = "review"                # reviewer start / resume / Step 1 / final
    TRIAGE = "triage"                # DM not-codeable, screening, upstream accept/reject, ODK edit
    SYNC_SUBMISSION = "sync_submission"
    ROUTE_PIN = "route_pin"          # pin / clear pin; target may also be ("unit", org_unit_id)
    # target = form_id
    SYNC_FORM = "sync_form"          # whole-form sync, preview, run history
    # target = project_id
    LIST_UNROUTED = "list_unrouted"
    # target = ("pair", project_id, site_id) | ("unit", org_unit_id)
    SITE_PI_REPORT = "site_pi_report"
    # target = a VaDeathRegister row (project_id, site_id, org_unit_id)
    SUPERVISE_INTAKE = "supervise_intake"
    # no target: scope_filter only (DM grid, KPI panels, exports, filter options)
    LIST_DATA = "list_data"


# Attachments and workflow events are part of viewing a submission.
READ_ATTACHMENTS = Action.VIEW
READ_EVENTS = Action.VIEW


class Reason(enum.Enum):
    ALLOWED = "allowed"
    NOT_FOUND = "not_found"
    NO_ROLE = "no_role"
    PROJECT_CLOSED = "project_closed"
    OUT_OF_SCOPE = "out_of_scope"
    VIEW_ONLY = "view_only"
    UNROUTED = "unrouted"


class Lens(enum.Enum):
    """One way a grant resolves to submissions (design section 2.1)."""

    CODE_CODER = "code_coder"                    # coder, coding_tester, virtual demo
    CODE_REVIEWER = "code_reviewer"              # reviewer, virtual demo
    VIEW_CODER = "view_coder"                    # coder, coding_tester; no scope level
    VIEW_REVIEWER = "view_reviewer"              # reviewer; no scope level
    DM = "dm"                                    # data_manager; site_pi@org_unit; project_pi on a tree
    VIEWER = "viewer"                            # collaborator, collaborator_pii
    SITE_PI_PAIR = "site_pi_pair"                # site_pi@project_site
    PROJECT_PI_SITE = "project_pi_site"          # project_pi on a site project
    DM_PROJECT_UNROUTED = "dm_project_unrouted"  # unrouted cases of a tree project, any DM grant
    DM_DIRECT = "dm_direct"                      # data_manager @project/@pair; project_pi on a tree


RULES: dict[Action, tuple[Lens, ...]] = {
    Action.VIEW: (
        Lens.VIEW_CODER,
        Lens.VIEW_REVIEWER,
        Lens.DM,
        Lens.VIEWER,
        Lens.SITE_PI_PAIR,
        Lens.PROJECT_PI_SITE,
    ),
    Action.CODE: (Lens.CODE_CODER,),
    Action.RECODE: (Lens.CODE_CODER,),
    Action.REVIEW: (Lens.CODE_REVIEWER,),
    Action.TRIAGE: (Lens.DM,),
    Action.SYNC_SUBMISSION: (Lens.DM,),
    Action.ROUTE_PIN: (Lens.DM, Lens.DM_PROJECT_UNROUTED),
    Action.LIST_DATA: (Lens.DM, Lens.VIEWER),
    Action.LIST_UNROUTED: (Lens.DM_PROJECT_UNROUTED,),
    Action.SYNC_FORM: (Lens.DM_DIRECT,),
}

# Actions whose target is one submission (va_sid): can() is EXISTS over scope_filter.
SUBMISSION_ACTIONS = frozenset({
    Action.VIEW,
    Action.CODE,
    Action.RECODE,
    Action.REVIEW,
    Action.TRIAGE,
    Action.SYNC_SUBMISSION,
    Action.ROUTE_PIN,
})

# Admin reaches every project, closed ones included, for these. Coding and
# reviewing are not bypassed (admin codes demo only, through its own path),
# and intake supervision has no admin bypass (authz.supervision).
ADMIN_BYPASS = frozenset(Action) - {
    Action.CODE,
    Action.RECODE,
    Action.REVIEW,
    Action.SUPERVISE_INTAKE,
}

# A user holding any of these roles somewhere (or an admin) also holds a
# project-scope grant of all of them on each active demo-training project
# (owner 2026-10-02: coding AND reviewing, never data_manager; 2026-10-03:
# only for people who already code or review). The one place to change it.
DEMO_VIRTUAL_ROLES = frozenset({
    VaAccessRoles.coder,
    VaAccessRoles.coding_tester,
    VaAccessRoles.reviewer,
})

# Roles that confer intake supervision (SUPERVISE_INTAKE), besides project_pi
# on a tree project; site_pi counts only at org_unit scope (the In-charge).
SUPERVISING_ROLES = frozenset({
    VaAccessRoles.interview_supervisor,
    VaAccessRoles.data_manager,
    VaAccessRoles.site_pi,
})


# ---------------------------------------------------------------------------
# Grant management (design section 2.5; access-control-model.md "Who creates
# which grants"; dm-user-grant-management.md "Scope Rules")
# ---------------------------------------------------------------------------

# What a data manager assigns in a site (no tree) project, at their own scope.
DM_SITE_ASSIGNABLE = frozenset({
    VaAccessRoles.coder,
    VaAccessRoles.coding_tester,
    VaAccessRoles.data_manager,
})
# What a data manager (or In-charge) assigns anywhere in their subtree in a
# district project, own level included. data_manager itself goes strictly below.
DM_TREE_ASSIGNABLE = frozenset({
    VaAccessRoles.interviewer,
    VaAccessRoles.coder,
    VaAccessRoles.reviewer,
    VaAccessRoles.coding_tester,
    VaAccessRoles.collaborator,
    VaAccessRoles.collaborator_pii,
})
# Never written by a project_pi.
PI_NEVER_ASSIGNS = frozenset({VaAccessRoles.admin, VaAccessRoles.project_pi})
