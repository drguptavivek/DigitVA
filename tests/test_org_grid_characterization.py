"""Characterization of the project users grid, bulk apply and the module's import surface.

Written on the unchanged organization_service before it was split into org_*
modules (digitva-r8nh.14): every operation string and scope_mode of
``bulk_apply_project_users_grid``, the shape of ``get_project_users_grid``, and
the guarantee that every name the module exposed still imports from
``app.services.organization_service``. A split must leave all of it green.
Policy: docs/policy/access-control-model.md, docs/policy/organization-model.md.
"""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnit,
    MasOrgUnitWorker,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import organization_service as org
from tests.base import BaseTestCase

# Every top-level name organization_service defined before the split (public
# and private). Private names are imported by other services and tests.
PRE_SPLIT_NAMES = (
    "CODE_RE LEVEL_CODE_RE DEFAULT_LEVEL_TEMPLATE DEFAULT_CADRE_TEMPLATE "
    "DEFAULT_LEVEL_CADRE_TEMPLATE DEFAULT_TYPICAL_ROLES EXPORT_SHEETS OrganizationError "
    "normalize_code normalize_level_code odk_field_name_for_level odk_choice_list_name_for_level "
    "_clean_text _clean_coordinate _clean_url _to_bool _get_project require_organization_mode "
    "_ORGANIZATION_SITE_PREFIX organization_site_name _next_organization_site_id "
    "ensure_organization_site _uuid serialize_level serialize_unit serialize_cadre "
    "serialize_level_cadre serialize_worker list_levels _get_level create_level update_level "
    "list_units list_units_by_codes resolve_org_unit_export_labels _aliased_parent "
    "_top_level_depth _is_unplaced unplaced_unit_codes get_unit_tree _get_unit "
    "_validate_parent_for_level create_unit _rewrite_subtree_paths update_unit MAX_PLACEMENTS "
    "place_units unit_deactivation_preview set_unit_active serialize_unit_coding_gate "
    "get_unit_coding_gate set_unit_coding_gate VA_PRESET_VALUES serialize_unit_va_presets "
    "get_unit_va_presets _validate_va_preset_value set_unit_va_presets clear_unit_va_presets "
    "clear_unit_coding_gate get_unit_collection_gate serialize_unit_collection_gate "
    "set_unit_collection_gate clear_unit_collection_gate find_unit_by_code subtree_unit_ids "
    "list_cadres _get_cadre create_cadre update_cadre list_level_cadres normalize_default_roles "
    "upsert_level_cadre get_level_cadre_permission _WORKER_CODING_ROLES _WORKER_SUPERVISION_ROLES "
    "list_workers _get_worker _require_cadre_at_unit_level resolve_user _resolve_user "
    "_next_worker_code create_worker update_worker replace_placement_grants "
    "seed_default_organization district_reference_model _LEVEL_HEADERS _UNIT_HEADERS "
    "_CADRE_HEADERS _LEVEL_CADRE_HEADERS _DEFAULT_ROLES_SEPARATOR _WORKER_HEADERS "
    "export_organization_rows _spreadsheet_safe export_organization_xlsx export_organization_csv "
    "export_odk_choices_rows export_odk_choices_csv ImportPlan parse_organization_workbook "
    "parse_organization_csv parse_units_upload import_organization _import_levels "
    "_import_cadres _import_level_cadres _without_blank _import_units _import_workers "
    "MY_ORG_PEOPLE_CAP _granted_project_ids _granted _my_units _ancestor_units _people_by_unit "
    "_unit_summaries _my_project _granted_site_names _my_positions my_organization unit_people "
    "lookup_existing_user SUGGEST_LIMIT SUGGEST_MIN_EMAIL SUGGEST_MIN_DIGITS SUGGEST_MAX_LEN "
    "suggest_existing_users worker_data_collector_user sync_worker_unit_scope_grants "
    "list_project_va_presets bulk_set_unit_va_presets project_mentoring_overview "
    "sync_mentor_scientist_unit_grants _DISPLAY_ROLE_META _grant_in_project on_project_roster "
    "require_on_project_roster remove_from_project get_project_users_grid _BULK_ROLE_MAP "
    "bulk_apply_project_users_grid"
).split()


class OrganizationServiceSurfaceTests(BaseTestCase):
    def test_every_pre_split_name_still_imports_from_the_facade(self):
        missing = [name for name in PRE_SPLIT_NAMES if not hasattr(org, name)]
        self.assertEqual(missing, [])

    def test_dunder_all_names_all_resolve(self):
        self.assertEqual([n for n in org.__all__ if not hasattr(org, n)], [])
        self.assertEqual(len(org.__all__), 66)

    def test_names_imported_elsewhere_in_the_repo_resolve(self):
        from app.services.organization_service import (  # noqa: F401
            _UNIT_HEADERS,
            DEFAULT_TYPICAL_ROLES,
            OrganizationError,
            _spreadsheet_safe,
            district_reference_model,
            list_levels,
            on_project_roster,
            resolve_org_unit_export_labels,
            suggest_existing_users,
        )
        self.assertTrue(issubclass(OrganizationError, ValueError))


class ProjectUsersGridCharacterizationTests(BaseTestCase):
    PROJECT = "GRDCH1"

    def setUp(self):
        super().setUp()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=self.PROJECT, project_code=self.PROJECT, project_name="Grid characterization",
            project_nickname=self.PROJECT, project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, project_structure_mode="organization",
        ))
        db.session.flush()
        org.seed_default_organization(self.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        cadres = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}
        self.chc_level_id = levels["chc"].org_level_id
        self.village_level_id = levels["village"].org_level_id
        dist = org.create_unit(self.PROJECT, org_level_id=levels["district"].org_level_id,
                               unit_code="GD1", unit_name="Grid D1")
        self.c1 = org.create_unit(self.PROJECT, org_level_id=self.chc_level_id,
                                  parent_org_unit_id=dist.org_unit_id, unit_code="GC1", unit_name="Grid C1")
        self.c2 = org.create_unit(self.PROJECT, org_level_id=self.chc_level_id,
                                  parent_org_unit_id=dist.org_unit_id, unit_code="GC2", unit_name="Grid C2")
        self.admin = db.session.get(VaUsers, uuid.UUID(str(self.base_admin_id)))
        self.u1 = self._make_user("grid.char.u1@test.local", "GridChar123")
        self.u2 = self._make_user("grid.char.u2@test.local", "GridChar123")
        self.u3 = self._make_user("grid.char.u3@test.local", "GridChar123")  # no placement
        self.mo = cadres["MO"]
        for code, user, unit in (("GW1", self.u1, self.c1), ("GW2", self.u2, self.c2)):
            db.session.add(MasOrgUnitWorker(
                project_id=self.PROJECT, org_unit_id=unit.org_unit_id, cadre_id=self.mo.cadre_id,
                user_id=user.user_id, worker_code=code, worker_name=code, is_active=True,
            ))
        db.session.flush()

    # -- helpers ---------------------------------------------------------

    def _apply(self, users, operation, scope_mode="own", actor=None, **extra):
        payload = {
            "user_ids": [str(u.user_id) for u in users],
            "operation": operation,
            "scope_mode": scope_mode,
            **extra,
        }
        result = org.bulk_apply_project_users_grid(self.PROJECT, payload, actor=actor or self.admin)
        db.session.flush()
        return result

    def _grants(self, user, *, active_only=True):
        rows = db.session.scalars(
            sa.select(VaUserAccessGrants).where(VaUserAccessGrants.user_id == user.user_id)).all()
        out = set()
        for g in rows:
            if active_only and g.grant_status != VaStatuses.active:
                continue
            where = db.session.get(MasOrgUnit, g.org_unit_id).unit_code if g.org_unit_id else g.project_id
            out.add((g.role.value, g.scope_type.value, where))
        return out

    def _assert_summary(self, summary, **counts):
        want = {"users_processed": 1, "grants_created": 0, "grants_reactivated": 0,
                "grants_revoked": 0, "accounts_updated": 0}
        want.update(counts)
        self.assertEqual({k: summary[k] for k in want}, want)

    @staticmethod
    def _actions(changed):
        return sorted(action for _data, action in changed)

    # -- account status --------------------------------------------------

    def test_activate_and_deactivate_users(self):
        summary, changed = self._apply([self.u3], "deactivate_users", "project")
        self._assert_summary(summary, accounts_updated=1)
        self.assertEqual((summary["operation"], summary["scope_mode"]), ("deactivate_users", "project"))
        self.assertEqual(changed, [])
        self.assertEqual(self.u3.user_status, VaStatuses.deactive)
        summary, changed = self._apply([self.u3], "activate_users", "project")
        self._assert_summary(summary, accounts_updated=1)
        self.assertEqual(self.u3.user_status, VaStatuses.active)
        summary, _ = self._apply([self.u3], "activate_users", "project")
        self._assert_summary(summary, accounts_updated=0)

    def test_account_status_is_admin_only_and_never_self(self):
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.admin], "deactivate_users", "project")
        self.assertIn("own account", str(ctx.exception))
        with self.assertRaises(org.OrganizationError):
            self._apply([self.u3], "deactivate_users", "project", actor=self.u1)

    # -- payload refusals ------------------------------------------------

    def test_payload_refusals(self):
        u1 = str(self.u1.user_id)
        for payload, text in (
            ({"user_ids": [], "operation": "coder"}, "Select at least one user"),
            ({"user_ids": [u1], "operation": ""}, "Choose a role"),
            ({"user_ids": [u1], "operation": "nonsense", "scope_mode": "project"}, "Unknown bulk operation"),
            ({"user_ids": [str(uuid.uuid4())], "operation": "coder"}, "not found"),
            ({"user_ids": [u1], "operation": "coder", "scope_mode": "bogus"}, "Unsupported scope_mode"),
            ({"user_ids": [u1], "operation": "coder", "scope_mode": "custom"}, "target unit"),
            ({"user_ids": [u1], "operation": "coder", "scope_mode": f"level:{self.village_level_id}"},
             "no active units"),
        ):
            with self.assertRaises(org.OrganizationError) as ctx:
                org.bulk_apply_project_users_grid(self.PROJECT, payload, actor=self.admin)
            self.assertIn(text, str(ctx.exception), payload)
        with self.assertRaises(org.OrganizationError) as ctx:
            org.bulk_apply_project_users_grid(
                self.PROJECT, {"user_ids": [str(uuid.uuid4()) for _ in range(501)], "operation": "coder"},
                actor=self.admin)
        self.assertIn("At most 500", str(ctx.exception))

    def test_no_home_unit_is_refused_for_unit_scopes(self):
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u3], "coder", "own")
        self.assertIn("no home unit placement", str(ctx.exception))

    # -- unit scopes -----------------------------------------------------

    def test_coder_own_creates_one_unit_grant_then_is_idempotent(self):
        summary, changed = self._apply([self.u1], "coder", "own")
        self._assert_summary(summary, grants_created=1)
        self.assertEqual(self._grants(self.u1), {("coder", "org_unit", "GC1")})
        self.assertEqual(self._actions(changed), ["grant_created"])
        data = changed[0][0]
        self.assertEqual(
            {k: data[k] for k in ("user_id", "role", "scope_type", "org_unit_id", "cadre_id")},
            {"user_id": self.u1.user_id, "role": "coder", "scope_type": "org_unit",
             "org_unit_id": self.c1.org_unit_id, "cadre_id": self.mo.cadre_id})
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(VaUserAccessGrants.user_id == self.u1.user_id))
        self.assertEqual(grant.created_by_user_id, self.admin.user_id)
        self.assertEqual(data["grant_id"], grant.grant_id)
        summary, changed = self._apply([self.u1], "coder", "own")
        self._assert_summary(summary)
        self.assertEqual(changed, [])

    def test_all_user_level_then_own_syncs_scope_and_reactivates(self):
        summary, changed = self._apply([self.u1], "coder", "all_user_level")
        self._assert_summary(summary, grants_created=2)
        self.assertEqual(self._grants(self.u1), {("coder", "org_unit", "GC1"), ("coder", "org_unit", "GC2")})
        summary, changed = self._apply([self.u1], "coder", "own")
        self._assert_summary(summary, grants_revoked=1)
        self.assertEqual(self._actions(changed), ["grant_revoked"])
        self.assertEqual(self._grants(self.u1), {("coder", "org_unit", "GC1")})
        summary, changed = self._apply([self.u1], "coder", "all_user_level")
        self._assert_summary(summary, grants_reactivated=1)
        self.assertEqual(self._actions(changed), ["grant_reactivated"])

    def test_sync_scope_false_keeps_grants_outside_the_new_scope(self):
        self._apply([self.u1], "coder", "all_user_level")
        summary, _ = self._apply([self.u1], "coder", "own", sync_scope=False)
        self._assert_summary(summary)
        self.assertEqual(self._grants(self.u1), {("coder", "org_unit", "GC1"), ("coder", "org_unit", "GC2")})

    def test_cross_level_targets_only_the_other_units(self):
        summary, _ = self._apply([self.u1], "coder", "cross_level")
        self._assert_summary(summary, grants_created=1)
        self.assertEqual(self._grants(self.u1), {("coder", "org_unit", "GC2")})

    def test_custom_and_level_scopes(self):
        summary, _ = self._apply([self.u1], "reviewer", "custom", custom_unit_ids=[str(self.c2.org_unit_id)])
        self._assert_summary(summary, grants_created=1)
        self.assertEqual(self._grants(self.u1), {("reviewer", "org_unit", "GC2")})
        summary, _ = self._apply([self.u2], "coder", f"level:{self.chc_level_id}")
        self._assert_summary(summary, grants_created=2)
        self.assertEqual(self._grants(self.u2), {("coder", "org_unit", "GC1"), ("coder", "org_unit", "GC2")})

    def test_custom_unit_outside_the_project_is_refused(self):
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u1], "coder", "custom", custom_unit_ids=[str(uuid.uuid4())])
        self.assertIn("does not belong to this project", str(ctx.exception))

    def test_a_user_with_no_home_unit_gets_nothing_in_a_batch(self):
        summary, _ = self._apply([self.u1, self.u3], "coder", "own")
        self._assert_summary(summary, users_processed=2, grants_created=1)
        self.assertEqual(self._grants(self.u3), set())

    def test_home_cadre_not_defined_at_the_level_is_refused(self):
        anm = next(c for c in org.list_cadres(self.PROJECT) if c.cadre_code == "ANM")
        # ANM is not defined at the CHC level at all.
        db.session.add(MasOrgUnitWorker(
            project_id=self.PROJECT, org_unit_id=self.c1.org_unit_id, cadre_id=anm.cadre_id,
            user_id=self.u3.user_id, worker_code="GW3", worker_name="GW3", is_active=True,
        ))
        db.session.flush()
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u3], "coder", "own")
        self.assertIn("not defined at level", str(ctx.exception))

    # -- project scope ---------------------------------------------------

    def test_project_scope_grant_reactivate_and_pii_downgrade(self):
        summary, changed = self._apply([self.u3], "collaborator", "project")
        self._assert_summary(summary, grants_created=1)
        self.assertEqual(self._grants(self.u3), {("collaborator", "project", self.PROJECT)})
        self.assertEqual(self._actions(changed), ["grant_created"])
        summary, changed = self._apply([self.u3], "viewer_pii", "project")
        self._assert_summary(summary, grants_created=1)
        self.assertEqual(self._grants(self.u3), {("collaborator", "project", self.PROJECT),
                                                 ("collaborator_pii", "project", self.PROJECT)})
        summary, changed = self._apply([self.u3], "revoke_pii", "project")
        self._assert_summary(summary, grants_revoked=1)
        self.assertEqual(self._actions(changed), ["grant_revoked"])
        self.assertEqual(self._grants(self.u3), {("collaborator", "project", self.PROJECT)})
        # collaborator re-applied revokes a leftover collaborator_pii and is idempotent otherwise.
        self._apply([self.u3], "viewer_pii", "project")
        summary, _ = self._apply([self.u3], "collaborator", "project")
        self._assert_summary(summary, grants_revoked=1)
        self.assertEqual(self._grants(self.u3), {("collaborator", "project", self.PROJECT)})
        self._apply([self.u3], "revoke_all", "project")
        summary, changed = self._apply([self.u3], "collaborator", "project")
        self._assert_summary(summary, grants_reactivated=1)
        self.assertEqual(self._actions(changed), ["grant_reactivated"])

    def test_project_pi_is_always_project_wide(self):
        summary, _ = self._apply([self.u3], "project_pi", "own")
        self._assert_summary(summary, grants_created=1)
        self.assertEqual(self._grants(self.u3), {("project_pi", "project", self.PROJECT)})

    def test_unit_scoped_roles_cannot_be_granted_project_wide(self):
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u3], "interview_supervisor", "project")
        self.assertIn("unit-scoped", str(ctx.exception))
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u3], "death_reporter", "project")
        self.assertIn("unit-scoped", str(ctx.exception))

    def test_site_pi_without_sites_is_refused(self):
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u3], "site_pi", "project")
        self.assertIn("no sites configured", str(ctx.exception))

    # -- revocations -----------------------------------------------------

    def test_revoke_all_deactivates_every_grant_in_the_project(self):
        self._apply([self.u1], "coder", "all_user_level")
        self._apply([self.u1], "collaborator", "project")
        summary, changed = self._apply([self.u1], "revoke_all", "own")
        self._assert_summary(summary, grants_revoked=3)
        self.assertEqual(self._actions(changed), ["grant_revoked"] * 3)
        self.assertEqual(self._grants(self.u1), set())
        self.assertEqual(len(self._grants(self.u1, active_only=False)), 3)
        self.assertEqual({c[0]["scope_type"] for c in changed}, {"org_unit", "project"})

    def test_revoke_pii_and_revoke_coder_at_unit_and_project_scope(self):
        self._apply([self.u1], "coder", "own")
        self._apply([self.u1], "reviewer", "own")
        # collaborator_pii at unit scope, written directly (the bulk map never grants it at a unit).
        db.session.add(VaUserAccessGrants(
            user_id=self.u1.user_id, role=VaAccessRoles.collaborator_pii, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.c1.org_unit_id, grant_status=VaStatuses.active))
        db.session.flush()
        summary, changed = self._apply([self.u1], "revoke_pii", "own")
        self._assert_summary(summary, grants_revoked=1)
        self.assertEqual(self._grants(self.u1), {("coder", "org_unit", "GC1"), ("reviewer", "org_unit", "GC1")})
        summary, changed = self._apply([self.u1], "revoke_coder", "own")
        self._assert_summary(summary, grants_revoked=2)
        self.assertEqual(self._grants(self.u1), set())
        # project scope sweeps project and every unit grant of the coding roles.
        self._apply([self.u1], "coder", "all_user_level")
        self._apply([self.u1], "reviewer", "project")
        summary, _ = self._apply([self.u1], "revoke_coder", "project")
        self._assert_summary(summary, grants_revoked=3)
        self.assertEqual(self._grants(self.u1), set())

    # -- cadre defaults --------------------------------------------------

    def test_cadre_defaults_apply_the_home_cadre_default_roles(self):
        # MO at CHC defaults to ["coder"] in the seeded template.
        summary, changed = self._apply([self.u1], "cadre_defaults", "own")
        self._assert_summary(summary, grants_created=1)
        self.assertEqual(self._grants(self.u1), {("coder", "org_unit", "GC1")})
        self.assertEqual(self._actions(changed), ["grant_created"])
        summary, _ = self._apply([self.u2], "cadre_defaults", "project")
        self._assert_summary(summary, grants_created=1)
        self.assertEqual(self._grants(self.u2), {("coder", "org_unit", "GC2")})

    def test_cadre_defaults_refuses_a_single_user_without_placement(self):
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u3], "cadre_defaults", "own")
        self.assertIn("active worker placement", str(ctx.exception))
        summary, _ = self._apply([self.u3, self.u1], "cadre_defaults", "own")
        self._assert_summary(summary, users_processed=2, grants_created=1)

    def test_unit_scopes_need_an_organization_mode_project(self):
        db.session.get(VaProjectMaster, self.PROJECT).project_structure_mode = "sites"
        db.session.flush()
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u1], "coder", "own")
        self.assertIn("organization-mode", str(ctx.exception))
        with self.assertRaises(org.OrganizationError):
            self._apply([self.u1], "cadre_defaults", "own")

    # -- grid read -------------------------------------------------------

    def test_grid_read_shape_and_rows(self):
        self._apply([self.u1], "coder", "own")
        self._apply([self.u1], "collaborator", "project")
        grid = org.get_project_users_grid(self.PROJECT, viewer=self.admin)
        self.assertEqual(
            set(grid),
            {"project_id", "structure_mode", "levels", "units", "cadres", "level_cadres", "sites", "users",
             "unlinked_workers", "counts"})
        self.assertEqual((grid["project_id"], grid["structure_mode"]), (self.PROJECT, "organization"))
        self.assertEqual(len(grid["levels"]), 7)
        self.assertEqual({u["unit_code"] for u in grid["units"]}, {"GD1", "GC1", "GC2"})
        self.assertEqual(
            {u["email"] for u in grid["users"]}, {"grid.char.u1@test.local", "grid.char.u2@test.local"})
        row = next(u for u in grid["users"] if u["email"] == "grid.char.u1@test.local")
        self.assertEqual(row["user_id"], str(self.u1.user_id))
        self.assertEqual([w["unit_code"] for w in row["workers"]], ["GC1"])
        self.assertEqual(grid["counts"]["total_users"], 2)
        self.assertEqual(grid["counts"]["unlinked_workers"], 0)
        other = next(u for u in grid["users"] if u["email"].endswith("u2@test.local"))
        self.assertEqual(sorted(row), sorted(other))

    def test_grid_read_is_single_pass_query_count(self):
        """The read issues a fixed number of statements, none per user (no N+1)."""
        self._apply([self.u1], "coder", "own")
        self._apply([self.u1, self.u2], "collaborator", "project")
        statements = []

        def count(conn, cursor, statement, *_):
            statements.append(statement)

        engine = db.session.get_bind()
        sa.event.listen(engine, "before_cursor_execute", count)
        try:
            grid = org.get_project_users_grid(self.PROJECT, viewer=self.admin)
        finally:
            sa.event.remove(engine, "before_cursor_execute", count)
        self.assertEqual(len(grid["users"]), 2)
        self.assertEqual(len(statements), 17)
