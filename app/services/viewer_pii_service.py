"""Viewer PII redaction — the single decision point for whether the
current viewer's read-only access must hide personal data.

Policy: docs/policy/access-control-model.md ("collaborator",
"collaborator_pii", "Why this is a role and not a flag").
Task record: .tasks/viewer-pii-roles.md.

Rule (decided, not re-litigated here): redact unless the user holds a live
grant in ``_PII_GRANTING_ROLES`` — admin, project_pi, site_pi, data_manager,
coder, coding_tester, reviewer, interviewer, collaborator_pii. A plain
``collaborator`` and an ``interview_supervisor`` (docs/policy/web-intake.md,
"Privacy rule (item 14)") are redacted.
A user holding both ``collaborator`` and, say, ``coder`` sees personal data
via the coder grant.

Call ``should_redact_pii`` wherever a screen decides whether to show subject
PII (payload fields flagged ``is_pii``) or staff identity (who collected,
coded, reviewed a death). Never re-implement this check per screen: a screen
that checks only "is this read-only" and forgets this call fails OPEN (a
plain viewer sees personal data), which is the failure mode that matters.
"""

from app.models import VaAccessRoles

# An explicit allowlist, so a role added later redacts until someone decides
# otherwise (a deny-list fails open). Membership per
# docs/policy/access-control-model.md: project_pi and the In-charge (site_pi)
# see every screen "with personal data"; collaborator_pii exists to see it.
# The rollout note under "collaborator" narrowed only that role, so admin,
# data_manager, coder, coding_tester, reviewer and interviewer keep the
# personal data they saw before the viewer split. Left out: collaborator
# (redacted by definition) and interview_supervisor, whose identifier access
# is confined to the intake worklist and case views (docs/policy/web-intake.md,
# "Privacy rule (item 14)") and never lifts this redaction.
_PII_GRANTING_ROLES = frozenset({
    VaAccessRoles.admin,
    VaAccessRoles.project_pi,
    VaAccessRoles.site_pi,
    VaAccessRoles.data_manager,
    VaAccessRoles.coder,
    VaAccessRoles.coding_tester,
    VaAccessRoles.reviewer,
    VaAccessRoles.interviewer,
    VaAccessRoles.collaborator_pii,
})


def should_redact_pii(user) -> bool:
    """Return True if ``user`` must not see subject PII or staff identity.

    False (do not redact) when the user holds a live grant in
    ``_PII_GRANTING_ROLES``. A user with no such grant, or no grants at all,
    gets True: this helper only governs what a read-only view may display
    once access has already been granted elsewhere — it is not an access
    check.

    "Live" is the authz grant relation (``resolve_grants``): an active grant
    on an active project, and for a pair or unit grant an active pair or
    unit. Reusing it keeps redaction in step with the resolvers, so a grant
    that opens no screen (closed project, deactivated unit or pair) cannot
    switch redaction off on screens reached through another grant.
    Demo-training virtual grants are ignored: they are derived, not held.
    """
    # Imported here: app.services.authz imports this module at package load.
    from app.services.authz.grants import resolve_grants

    if not getattr(user, "user_id", None):
        return True
    resolved = resolve_grants(user)
    if resolved.is_admin:
        return False
    return not any(
        g.role in _PII_GRANTING_ROLES and not g.virtual for g in resolved.grants
    )
