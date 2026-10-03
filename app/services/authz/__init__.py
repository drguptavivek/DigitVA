"""Authorization: the single source for who may do what to which object.

Every role and scope decision in the app is asked here; workflow checks
(allocation, state, narration language, the recode window) stay with the
workflow services.

- ``can(user, action, target)`` / ``require(...)``: one decision. Targets are
  a ``va_sid`` for the submission actions (``ROUTE_PIN`` also takes
  ``("unit", org_unit_id)``), a ``form_id`` for ``SYNC_FORM``, a
  ``project_id`` for ``LIST_UNROUTED``, ``("pair", project_id, site_id)`` or
  ``("unit", org_unit_id)`` for ``SITE_PI_REPORT``, a ``VaDeathRegister``
  row for ``SUPERVISE_INTAKE``. ``require`` raises ``AuthzError`` (404 for a
  missing target, else 403).
- ``scope_filter(user, action)``: the same rule as a SQL predicate on
  ``VaSubmissions``, for lists, counts and exports; ``can`` is ``EXISTS``
  over it, so a list never offers what ``can`` refuses. ``subtree_select``
  is the unit-subtree SELECT for raw-SQL and MV surfaces that cannot embed
  it; ``reaches`` asks one lens (a rendering that belongs to one role).
- ``can_grant(actor, GrantTarget)`` / ``grant_list_filter(actor)``: grant
  writes and the grant lists, one rule.
- ``effective_roles(user)``: which ``role_required`` gates the user opens.
- ``reachable_unit_ids(user, project_id, roles)``: the units of a project
  the user may browse (unit picker, device unit list, area dashboard).
- ``coding_gate_waivers`` (gates, not scope) and ``redacts_pii`` (the
  per-user redaction rule).

Every answer is derived from one per-request ``ResolvedGrants``
(``resolve_grants``; a grant write calls ``invalidate``) and the ``RULES``
table. Policy: docs/policy/access-control-model.md.
"""

from app.services.authz.actions import (
    DEMO_VIRTUAL_ROLES,
    GRANT_RULES,
    READ_ATTACHMENTS,
    READ_EVENTS,
    RULES,
    Action,
    Lens,
    Reason,
)
from app.services.authz.grant_writes import (
    GrantTarget,
    can_grant,
    grant_list_filter,
    writer_grants,
)
from app.services.authz.grants import (
    Grant,
    ProjectSettings,
    ResolvedGrants,
    invalidate,
    resolve_grants,
)
from app.services.authz.predicates import (
    AuthzError,
    Decision,
    can,
    effective_roles,
    reachable_unit_ids,
    reaches,
    require,
    scope_filter,
)
from app.services.authz.predicates import _subtree_select as subtree_select
from app.services.authz.waivers import CodingWaivers, coding_gate_waivers
from app.services.viewer_pii_service import should_redact_pii as redacts_pii

__all__ = [
    "DEMO_VIRTUAL_ROLES",
    "GRANT_RULES",
    "READ_ATTACHMENTS",
    "READ_EVENTS",
    "RULES",
    "Action",
    "AuthzError",
    "CodingWaivers",
    "Decision",
    "Grant",
    "GrantTarget",
    "Lens",
    "ProjectSettings",
    "Reason",
    "ResolvedGrants",
    "can",
    "can_grant",
    "coding_gate_waivers",
    "effective_roles",
    "grant_list_filter",
    "invalidate",
    "reachable_unit_ids",
    "reaches",
    "redacts_pii",
    "require",
    "resolve_grants",
    "scope_filter",
    "subtree_select",
    "writer_grants",
]
