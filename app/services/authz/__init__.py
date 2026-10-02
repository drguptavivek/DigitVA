"""Authorization: one module for who may do what to which object (digitva-0wc).

Public interface: ``can``, ``require``, ``scope_filter``, ``can_grant`` and
``grant_list_filter``, plus ``effective_roles`` (what opens a role gate),
``coding_gate_waivers`` (gates, not scope) and ``redacts_pii`` (the per-user
redaction rule, unchanged). Every answer is derived from one per-request
``ResolvedGrants`` and the ``RULES`` table.

Stage 1: the coding screens (coder pool, pick, recode, coder view, area
overview and the ``vacode`` partial validator) call this package. Stage 2:
the read-only rendering (``vadata``/``vaarea`` validators, write partials in
va_form.renderpartial), attachments and workflow events. Every other caller
still uses the old helpers in org_grant_service and VaUsers until the stages
in .tasks/digitva-0wc-design.md move it here. Stage 3: the data-manager
grid, exports, KPIs, triage, sync, the unrouted queue and pinning.
``subtree_select`` is the unit-subtree SELECT for the raw-SQL and MV
surfaces that cannot embed ``scope_filter``.
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
from app.services.authz.grant_writes import GrantTarget, can_grant, grant_list_filter
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
    "redacts_pii",
    "require",
    "resolve_grants",
    "scope_filter",
    "subtree_select",
]
