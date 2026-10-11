"""Bearer credentials never inherit a mixed account's browser privileges."""

import uuid

from app.models import VaAccessRoles, VaAccessScopeTypes
from app.services.authz.grants import (
    Grant,
    ProjectSettings,
    ResolvedGrants,
    _device_projection,
)


def _grant(role, project, *, virtual=False):
    return Grant(
        role=role,
        scope_type=VaAccessScopeTypes.project,
        project_id=project,
        virtual=virtual,
    )


def _resolved(*grants):
    projects = {
        project: ProjectSettings(
            project_id=project,
            has_tree=False,
            scope_depth=None,
            above_mode="view_only",
            demo_training=virtual,
        )
        for project, virtual in ((grant.project_id, grant.virtual) for grant in grants)
    }
    return ResolvedGrants(
        user_id=uuid.uuid4(), is_admin=True, grants=tuple(grants), projects=projects
    )


def test_device_projection_removes_admin_and_data_manager_reach():
    full = _resolved(
        _grant(VaAccessRoles.coder, "COLLECT"),
        _grant(VaAccessRoles.data_manager, "PRIVATE"),
    )

    projected = _device_projection(full)

    assert projected.is_admin is False
    assert [grant.role for grant in projected.grants] == [VaAccessRoles.coder]
    assert set(projected.projects) == {"COLLECT"}
    assert full.is_admin is True
    assert set(full.projects) == {"COLLECT", "PRIVATE"}


def test_admin_only_virtual_demo_grants_do_not_become_native_coding_access():
    full = _resolved(
        _grant(VaAccessRoles.interviewer, "COLLECT"),
        _grant(VaAccessRoles.coder, "DEMO", virtual=True),
    )

    projected = _device_projection(full)

    assert [grant.role for grant in projected.grants] == [VaAccessRoles.interviewer]
    assert set(projected.projects) == {"COLLECT"}


def test_native_coder_keeps_its_eligible_virtual_demo_grants():
    full = _resolved(
        _grant(VaAccessRoles.coder, "COLLECT"),
        _grant(VaAccessRoles.coder, "DEMO", virtual=True),
    )

    projected = _device_projection(full)

    assert {grant.project_id for grant in projected.grants} == {"COLLECT", "DEMO"}
    assert any(grant.virtual for grant in projected.grants)
