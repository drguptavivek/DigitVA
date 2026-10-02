"""Coding gate waivers (digitva-0wc, design 1.5).

Copied from ``coder_workflow_service._CodingWaivers`` / ``_coding_waivers``
(the originals stay until stage 1 moves their callers here) and fed from
``ResolvedGrants`` instead of five ``VaUsers.get_*`` calls. Gates are
separate from scope by policy (access-control-model.md, "Role To Scope
Rules"; organization-model.md, "Per-unit coding gates"): a waiver lifts the
enabled flag, date window and daily limit, never scope, so it is
deliberately not part of ``scope_filter``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app import db
from app.models import VaAccessRoles, VaAccessScopeTypes
from app.services.authz.grants import ResolvedGrants, resolve_grants
from app.services.authz.predicates import _subtree_select


@dataclass(frozen=True)
class CodingWaivers:
    """Where a user skips the coding gates (enabled flag, date window, limit).

    PI waiver: a project_pi grant on the project or a site_pi grant on the
    (project, site) pair -- keyed on the pair, never the bare site id, so a
    grant in one project waives nothing in another (digitva-d5s).
    coding_tester waiver: a project or project_site grant there, or a unit
    grant whose subtree holds the submission's unit.
    """

    pi_projects: frozenset
    pi_pairs: frozenset
    tester_projects: frozenset
    tester_pairs: frozenset
    tester_unit_ids: frozenset

    def is_pi(self, project_id, site_id) -> bool:
        return project_id in self.pi_projects or (project_id, site_id) in self.pi_pairs

    def is_tester(self, project_id, site_id, org_unit_id=None) -> bool:
        return (
            project_id in self.tester_projects
            or (project_id, site_id) in self.tester_pairs
            or (org_unit_id is not None and org_unit_id in self.tester_unit_ids)
        )

    def waives(self, project_id, site_id, org_unit_id=None) -> bool:
        return self.is_pi(project_id, site_id) or self.is_tester(
            project_id, site_id, org_unit_id
        )


def coding_gate_waivers(user, *, _grants: ResolvedGrants | None = None) -> CodingWaivers:
    """The user's PI and coding_tester gate waivers, resolved once.

    Real grants only: a demo-training virtual grant waives nothing, as
    today. ``tester_unit_ids`` is the expanded subtree of the tester's unit
    grants (``is_tester`` tests the submission's own unit against it), one
    query and only when such a grant exists.
    """
    g = _grants if _grants is not None else resolve_grants(user)
    tester = VaAccessRoles.coding_tester
    tester_units = g.unit_grant_ids((tester,), coding=False)
    return CodingWaivers(
        pi_projects=frozenset(
            x.project_id for x in g.of((VaAccessRoles.project_pi,), virtual=False)
        ),
        pi_pairs=frozenset(
            (x.project_id, x.site_id)
            for x in g.of(
                (VaAccessRoles.site_pi,), scope_types=(VaAccessScopeTypes.project_site,)
            )
        ),
        tester_projects=frozenset(
            x.project_id
            for x in g.of((tester,), scope_types=(VaAccessScopeTypes.project,), virtual=False)
        ),
        tester_pairs=frozenset(
            (x.project_id, x.site_id)
            for x in g.of((tester,), scope_types=(VaAccessScopeTypes.project_site,))
        ),
        tester_unit_ids=frozenset(
            db.session.scalars(_subtree_select(tester_units)).all() if tester_units else ()
        ),
    )
