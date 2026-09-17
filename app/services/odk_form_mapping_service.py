"""One definition of an ODK form mapping conflict.

Business rule: an ODK Central form — identified by
(ODK connection, ``odk_project_id``, ``odk_form_id``) — may be mapped to at most
one DigitVA ``(project_id, site_id)`` pair. ``map_project_site_odk`` only carries
the inverse uniqueness (one ODK form per project-site), and it does not carry the
connection: the connection is resolved per project through ``map_project_odk`` and
may be reassigned. The rule is therefore enforced here, in the service layer, and
not by a database constraint.

Two mappings conflict when they resolve to the **same** ODK connection, carry the
same ``(odk_project_id, odk_form_id)``, and belong to different project-site pairs.

Deactivated project-site pairs still count. A stale mapping keeps making sync pull
the same ODK form twice regardless of the pair's status, so the remedy is to delete
the stale mapping, not to deactivate the pair.

A project with no ``map_project_odk`` row has no connection, so no scope in which to
compare — such mappings are inert (sync cannot run for them) and never conflict.
"""

import uuid
from dataclasses import dataclass

import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectOdk,
    MapProjectSiteOdk,
    MasOdkConnections,
    VaForms,
    VaProjectSites,
    VaStatuses,
    VaSubmissions,
)

# Audit reads are bounded even though map_project_site_odk holds one row per
# project-site pair (tens of rows in practice).
MAX_CONFLICT_GROUPS = 200


@dataclass(frozen=True)
class OdkMappingTarget:
    """One project-site pair that an ODK form is mapped to."""

    mapping_id: uuid.UUID
    project_id: str
    site_id: str
    project_site_active: bool
    submission_count: int


@dataclass(frozen=True)
class OdkFormMappingConflict:
    """One ODK form mapped to more than one project-site on the same connection."""

    connection_id: uuid.UUID
    connection_name: str
    odk_project_id: int
    odk_form_id: str
    targets: tuple[OdkMappingTarget, ...]

    @property
    def active_targets(self) -> tuple[OdkMappingTarget, ...]:
        return tuple(t for t in self.targets if t.project_site_active)

    @property
    def stale_targets(self) -> tuple[OdkMappingTarget, ...]:
        """Targets safe to delete: deactivated pairs, with an active one remaining."""
        if not self.active_targets:
            return ()
        return tuple(t for t in self.targets if not t.project_site_active)


def get_project_odk_connection_id(project_id: str) -> uuid.UUID | None:
    """Return the ODK connection assigned to a project, or None when unassigned."""
    return db.session.scalar(
        sa.select(MapProjectOdk.connection_id).where(
            MapProjectOdk.project_id == project_id
        )
    )


def get_odk_form_mapping_targets(
    connection_id: uuid.UUID,
    odk_project_id: int,
) -> dict[str, MapProjectSiteOdk]:
    """Map ``odk_form_id`` → its existing mapping, for one connection + ODK project.

    Used to annotate the admin form picker so already-mapped forms can be shown as
    unselectable. When duplicates already exist in the data, the lowest
    project/site pair wins so the annotation is deterministic.
    """
    rows = db.session.scalars(
        _mappings_on_connection_stmt()
        .where(
            MapProjectOdk.connection_id == connection_id,
            MapProjectSiteOdk.odk_project_id == odk_project_id,
        )
        .order_by(MapProjectSiteOdk.project_id, MapProjectSiteOdk.site_id)
        .limit(MAX_CONFLICT_GROUPS)
    ).all()
    targets: dict[str, MapProjectSiteOdk] = {}
    for row in rows:
        targets.setdefault(row.odk_form_id, row)
    return targets


def find_conflicting_odk_form_mapping(
    project_id: str,
    site_id: str,
    odk_project_id: int,
    odk_form_id: str,
) -> MapProjectSiteOdk | None:
    """Return an existing mapping of the same ODK form to a *different* pair.

    ``project_id``/``site_id`` are the pair being saved; they are excluded so an
    idempotent re-save of the same pair never reports a conflict. Returns None when
    the project has no ODK connection assigned (see module docstring).
    """
    connection_id = get_project_odk_connection_id(project_id)
    if connection_id is None:
        return None

    return db.session.scalar(
        _mappings_on_connection_stmt()
        .where(
            MapProjectOdk.connection_id == connection_id,
            MapProjectSiteOdk.odk_project_id == odk_project_id,
            MapProjectSiteOdk.odk_form_id == odk_form_id,
            sa.not_(
                sa.and_(
                    MapProjectSiteOdk.project_id == project_id,
                    MapProjectSiteOdk.site_id == site_id,
                )
            ),
        )
        .order_by(MapProjectSiteOdk.project_id, MapProjectSiteOdk.site_id)
        .limit(1)
    )


def find_duplicate_odk_form_mappings(
    limit: int = MAX_CONFLICT_GROUPS,
) -> list[OdkFormMappingConflict]:
    """Return every ODK form mapped to more than one project-site pair.

    Shared by the ``odk-mappings audit`` CLI command and the admin conflicts
    endpoint so both report the same thing. Three bounded queries, no per-row
    lookups.
    """
    limit = max(1, min(limit, MAX_CONFLICT_GROUPS))
    rows = db.session.execute(
        sa.select(
            MapProjectSiteOdk.id,
            MapProjectSiteOdk.project_id,
            MapProjectSiteOdk.site_id,
            MapProjectSiteOdk.odk_project_id,
            MapProjectSiteOdk.odk_form_id,
            MapProjectOdk.connection_id,
            MasOdkConnections.connection_name,
            VaProjectSites.project_site_status,
        )
        .join(MapProjectOdk, MapProjectOdk.project_id == MapProjectSiteOdk.project_id)
        .join(
            MasOdkConnections,
            MasOdkConnections.connection_id == MapProjectOdk.connection_id,
        )
        .outerjoin(
            VaProjectSites,
            sa.and_(
                VaProjectSites.project_id == MapProjectSiteOdk.project_id,
                VaProjectSites.site_id == MapProjectSiteOdk.site_id,
            ),
        )
        .order_by(MapProjectSiteOdk.project_id, MapProjectSiteOdk.site_id)
    ).all()

    grouped: dict[tuple[uuid.UUID, int, str], list] = {}
    for row in rows:
        grouped.setdefault(
            (row.connection_id, row.odk_project_id, row.odk_form_id), []
        ).append(row)

    duplicate_groups = [
        (key, members) for key, members in grouped.items() if len(members) > 1
    ]
    duplicate_groups.sort(key=lambda item: (str(item[0][0]), item[0][1], item[0][2]))
    duplicate_groups = duplicate_groups[:limit]
    if not duplicate_groups:
        return []

    pairs = {
        (row.project_id, row.site_id)
        for _, members in duplicate_groups
        for row in members
    }
    submission_counts = _submission_counts_by_project_site(pairs)

    conflicts: list[OdkFormMappingConflict] = []
    for (connection_id, odk_project_id, odk_form_id), members in duplicate_groups:
        conflicts.append(
            OdkFormMappingConflict(
                connection_id=connection_id,
                connection_name=members[0].connection_name,
                odk_project_id=odk_project_id,
                odk_form_id=odk_form_id,
                targets=tuple(
                    OdkMappingTarget(
                        mapping_id=row.id,
                        project_id=row.project_id,
                        site_id=row.site_id,
                        project_site_active=(
                            row.project_site_status == VaStatuses.active
                        ),
                        submission_count=submission_counts.get(
                            (row.project_id, row.site_id), 0
                        ),
                    )
                    for row in members
                ),
            )
        )
    return conflicts


def _mappings_on_connection_stmt():
    """Select mappings joined to the connection their project resolves to."""
    return sa.select(MapProjectSiteOdk).join(
        MapProjectOdk, MapProjectOdk.project_id == MapProjectSiteOdk.project_id
    )


def _submission_counts_by_project_site(
    pairs: set[tuple[str, str]],
) -> dict[tuple[str, str], int]:
    """Count submissions per project-site in one aggregated query."""
    if not pairs:
        return {}
    rows = db.session.execute(
        sa.select(
            VaForms.project_id,
            VaForms.site_id,
            sa.func.count(VaSubmissions.va_sid),
        )
        .join(VaSubmissions, VaSubmissions.va_form_id == VaForms.form_id)
        .where(
            sa.tuple_(VaForms.project_id, VaForms.site_id).in_(sorted(pairs)),
        )
        .group_by(VaForms.project_id, VaForms.site_id)
    ).all()
    return {(project_id, site_id): count for project_id, site_id, count in rows}
