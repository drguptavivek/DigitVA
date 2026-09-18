import enum


class VaStatuses(enum.Enum):
    pending = "pending"
    active = "active"
    deactive = "deactive"


class VaUsernotesFor(enum.Enum):
    coding = "coding"
    reviewing = "reviewing"
    viewing = "viewing"


class VaAllocation(enum.Enum):
    coding = "coding"
    reviewing = "reviewing"


class VaAccessRoles(enum.Enum):
    admin = "admin"
    project_pi = "project_pi"
    site_pi = "site_pi"
    collaborator = "collaborator"
    # Read-only, same reach as collaborator, but personal data is not
    # redacted. See docs/policy/access-control-model.md, "collaborator_pii".
    collaborator_pii = "collaborator_pii"
    coder = "coder"
    coding_tester = "coding_tester"
    reviewer = "reviewer"
    data_manager = "data_manager"
    interviewer = "interviewer"


class VaAccessScopeTypes(enum.Enum):
    global_scope = "global"
    project = "project"
    project_site = "project_site"
    # Health-system projects scope a grant to a node of the project's own
    # organization tree (mas_org_unit); the grant covers that unit's subtree.
    # See docs/policy/organization-model.md.
    org_unit = "org_unit"
