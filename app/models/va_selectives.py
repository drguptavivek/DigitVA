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
