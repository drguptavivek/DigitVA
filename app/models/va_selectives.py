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
    coder = "coder"
    reviewer = "reviewer"
    data_manager = "data_manager"


class VaAccessScopeTypes(enum.Enum):
    global_scope = "global"
    project = "project"
    project_site = "project_site"
