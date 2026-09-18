"""Viewer PII redaction — the single decision point for whether the
current viewer's read-only access must hide personal data.

Policy: docs/policy/access-control-model.md ("collaborator",
"collaborator_pii", "Why this is a role and not a flag").
Task record: .tasks/viewer-pii-roles.md.

Rule (decided, not re-litigated here): redact ONLY for a user whose read
access comes through a plain ``collaborator`` grant and who holds no other
active grant that would grant personal data. Every other role — admin,
project_pi, site_pi, data_manager, coder, coding_tester, reviewer,
interviewer, collaborator_pii — sees personal data exactly as it does today.
A user holding both ``collaborator`` and, say, ``coder`` sees personal data
via the coder grant.

Call ``should_redact_pii`` wherever a screen decides whether to show subject
PII (payload fields flagged ``is_pii``) or staff identity (who collected,
coded, reviewed a death). Never re-implement this check per screen: a screen
that checks only "is this read-only" and forgets this call fails OPEN (a
plain viewer sees personal data), which is the failure mode that matters.
"""

import sqlalchemy as sa

from app import db
from app.models import VaAccessRoles, VaStatuses, VaUserAccessGrants

# Every role except plain `collaborator` already sees personal data today.
# Holding any ONE of these as an active grant unlocks personal data for the
# viewer, even if the same user also holds a plain collaborator grant.
_PII_GRANTING_ROLES = frozenset(VaAccessRoles) - {VaAccessRoles.collaborator}


def should_redact_pii(user) -> bool:
    """Return True if ``user`` must not see subject PII or staff identity.

    False (do not redact) for every role except a user whose active grants
    are exclusively plain ``collaborator``. A user with no active grants at
    all also gets True: this helper only governs what a read-only view may
    display once access has already been granted elsewhere — it is not an
    access check.
    """
    user_id = getattr(user, "user_id", None)
    if not user_id:
        return True

    stmt = sa.select(
        sa.exists().where(
            VaUserAccessGrants.user_id == user_id,
            VaUserAccessGrants.role.in_(_PII_GRANTING_ROLES),
            VaUserAccessGrants.grant_status == VaStatuses.active,
        )
    )
    return not bool(db.session.scalar(stmt))
