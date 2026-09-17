"""Unit-scoped access grants: cadre gating, subtree resolution, and the admin API.

Rules under test live in app/services/org_grant_service.py and the org_unit
branch of app/routes/admin.py::_resolve_scope_from_payload. Policy:
docs/policy/organization-model.md.
"""
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import org_grant_service as og
from app.services import organization_service as org
from tests.base import BaseTestCase


class OrgUnitGrantTests(BaseTestCase):
    PROJECT = "OGR001"
    OTHER = "OGR002"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id, name in ((cls.PROJECT, "Unit Grant Project"), (cls.OTHER, "Other Project")):
            if db.session.get(VaProjectMaster, project_id) is None:
                db.session.add(
                    VaProjectMaster(
                        project_id=project_id,
                        project_code=project_id,
                        project_name=name,
                        project_nickname=name,
                        project_status=VaStatuses.active,
                        project_registered_at=now,
                        project_updated_at=now,
                    )
                )
        db.session.commit()

    # -- fixtures ----------------------------------------------------------

    def _levels(self, project_id=None):
        return {lv.level_code: lv for lv in org.list_levels(project_id or self.PROJECT)}

    def _cadres(self, project_id=None):
        return {c.cadre_code: c for c in org.list_cadres(project_id or self.PROJECT)}

    def _tree(self):
        """District D01 > CHC C01 > PHC P01 > Sub-centre S01, plus a sibling CHC C02."""
        org.seed_default_organization(self.PROJECT)
        lv = self._levels()
        district = org.create_unit(
            self.PROJECT, org_level_id=lv["district"].org_level_id,
            unit_code="D01", unit_name="District One",
        )
        chc = org.create_unit(
            self.PROJECT, org_level_id=lv["chc"].org_level_id,
            parent_org_unit_id=district.org_unit_id, unit_code="C01", unit_name="CHC One",
        )
        phc = org.create_unit(
            self.PROJECT, org_level_id=lv["phc"].org_level_id,
            parent_org_unit_id=chc.org_unit_id, unit_code="P01", unit_name="PHC One",
        )
        subcentre = org.create_unit(
            self.PROJECT, org_level_id=lv["subcentre"].org_level_id,
            parent_org_unit_id=phc.org_unit_id, unit_code="S01", unit_name="Sub-centre One",
        )
        sibling = org.create_unit(
            self.PROJECT, org_level_id=lv["chc"].org_level_id,
            parent_org_unit_id=district.org_unit_id, unit_code="C02", unit_name="CHC Two",
        )
        db.session.commit()
        return district, chc, phc, subcentre, sibling

    def _grant(self, user_id, role, unit, cadre=None):
        grant = VaUserAccessGrants(
            user_id=user_id,
            role=role,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=unit.org_unit_id,
            cadre_id=cadre.cadre_id if cadre else None,
            grant_status=VaStatuses.active,
        )
        db.session.add(grant)
        db.session.commit()
        return grant

    # -- cadre gating ------------------------------------------------------

    def test_coder_grant_requires_a_cadre_that_may_code_at_that_level(self):
        _, chc, phc, subcentre, _ = self._tree()
        cadres = self._cadres()

        unit, cadre = og.validate_org_unit_grant(
            role=VaAccessRoles.coder, org_unit_id=phc.org_unit_id, cadre_id=cadres["MO"].cadre_id
        )
        self.assertEqual(unit.unit_code, "P01")
        self.assertEqual(cadre.cadre_code, "MO")

        # CHO fills at a PHC but may not code there.
        with self.assertRaises(org.OrganizationError) as ctx:
            og.validate_org_unit_grant(
                role=VaAccessRoles.coder, org_unit_id=phc.org_unit_id, cadre_id=cadres["CHO"].cadre_id
            )
        self.assertIn("may not code", str(ctx.exception))

        # SMO codes at a CHC but is not defined at a sub-centre at all.
        with self.assertRaises(org.OrganizationError) as ctx:
            og.validate_org_unit_grant(
                role=VaAccessRoles.coder,
                org_unit_id=subcentre.org_unit_id,
                cadre_id=cadres["SMO"].cadre_id,
            )
        self.assertIn("not defined at level", str(ctx.exception))

        # A coder grant without any cadre is refused outright.
        with self.assertRaises(org.OrganizationError) as ctx:
            og.validate_org_unit_grant(role=VaAccessRoles.coder, org_unit_id=chc.org_unit_id)
        self.assertIn("requires a cadre", str(ctx.exception))

    def test_non_coding_role_may_omit_cadre_but_a_named_cadre_must_exist_at_the_level(self):
        _, chc, _, subcentre, _ = self._tree()
        cadres = self._cadres()

        unit, cadre = og.validate_org_unit_grant(
            role=VaAccessRoles.site_pi, org_unit_id=chc.org_unit_id
        )
        self.assertEqual(unit.unit_code, "C01")
        self.assertIsNone(cadre)

        # Descriptive cadre on a non-coding role: allowed when defined at the level.
        _, cadre = og.validate_org_unit_grant(
            role=VaAccessRoles.reviewer, org_unit_id=chc.org_unit_id, cadre_id=cadres["SMO"].cadre_id
        )
        self.assertEqual(cadre.cadre_code, "SMO")

        with self.assertRaises(org.OrganizationError):
            og.validate_org_unit_grant(
                role=VaAccessRoles.reviewer,
                org_unit_id=subcentre.org_unit_id,
                cadre_id=cadres["SMO"].cadre_id,
            )

    def test_cadre_from_another_project_is_refused(self):
        _, chc, _, _, _ = self._tree()
        org.seed_default_organization(self.OTHER)
        db.session.commit()
        other_cadre = self._cadres(self.OTHER)["SMO"]
        with self.assertRaises(org.OrganizationError) as ctx:
            og.validate_org_unit_grant(
                role=VaAccessRoles.coder, org_unit_id=chc.org_unit_id, cadre_id=other_cadre.cadre_id
            )
        self.assertIn("not found in this unit's project", str(ctx.exception))

    def test_inactive_unit_and_disallowed_roles_are_refused(self):
        _, chc, _, _, _ = self._tree()
        cadres = self._cadres()

        with self.assertRaises(org.OrganizationError) as ctx:
            og.validate_org_unit_grant(
                role=VaAccessRoles.project_pi, org_unit_id=chc.org_unit_id
            )
        self.assertIn("cannot use org_unit scope", str(ctx.exception))
        with self.assertRaises(org.OrganizationError):
            og.validate_org_unit_grant(role=VaAccessRoles.admin, org_unit_id=chc.org_unit_id)

        org.set_unit_active(self.PROJECT, chc.org_unit_id, False)
        db.session.commit()
        with self.assertRaises(org.OrganizationError) as ctx:
            og.validate_org_unit_grant(
                role=VaAccessRoles.coder, org_unit_id=chc.org_unit_id, cadre_id=cadres["SMO"].cadre_id
            )
        self.assertIn("inactive", str(ctx.exception))

        with self.assertRaises(org.OrganizationError):
            og.validate_org_unit_grant(role=VaAccessRoles.coder, org_unit_id="not-a-uuid")

    # -- subtree resolution ------------------------------------------------

    def test_grant_covers_its_own_subtree_only(self):
        district, chc, phc, subcentre, sibling = self._tree()
        cadres = self._cadres()
        self._grant(self.base_coder_user.user_id, VaAccessRoles.coder, chc, cadres["SMO"])

        covered = og.scope_unit_ids(self.base_coder_user.user_id, VaAccessRoles.coder)
        self.assertEqual(
            covered, {chc.org_unit_id, phc.org_unit_id, subcentre.org_unit_id}
        )
        self.assertNotIn(district.org_unit_id, covered)
        self.assertNotIn(sibling.org_unit_id, covered)

        # A role the user does not hold at any unit resolves to nothing.
        self.assertEqual(og.scope_unit_ids(self.base_coder_user.user_id, VaAccessRoles.reviewer), set())

        self.assertEqual(
            og.granted_project_ids(self.base_coder_user.user_id, VaAccessRoles.coder), {self.PROJECT}
        )
        self.assertEqual(
            [u.unit_code for u in og.granted_units(self.base_coder_user.user_id, VaAccessRoles.coder)],
            ["C01"],
        )

    def test_deactivated_units_and_revoked_grants_drop_out_of_scope(self):
        _, chc, phc, subcentre, _ = self._tree()
        cadres = self._cadres()
        grant = self._grant(self.base_coder_user.user_id, VaAccessRoles.coder, chc, cadres["SMO"])

        # Deactivating the PHC cascades to the sub-centre below it.
        org.set_unit_active(self.PROJECT, phc.org_unit_id, False)
        db.session.commit()
        covered = og.scope_unit_ids(self.base_coder_user.user_id, VaAccessRoles.coder)
        self.assertEqual(covered, {chc.org_unit_id})
        self.assertNotIn(subcentre.org_unit_id, covered)

        grant.grant_status = VaStatuses.deactive
        db.session.commit()
        self.assertEqual(og.scope_unit_ids(self.base_coder_user.user_id, VaAccessRoles.coder), set())

    def test_unit_grants_do_not_leak_into_legacy_form_resolution(self):
        _, chc, _, _, _ = self._tree()
        cadres = self._cadres()
        before = self.base_project_pi_user.get_coder_va_forms()
        self._grant(self.base_project_pi_user.user_id, VaAccessRoles.coder, chc, cadres["SMO"])
        self.assertEqual(self.base_project_pi_user.get_coder_va_forms(), before)
        # The unit grant is visible only through the unit-scope accessors.
        self.assertIn(chc.org_unit_id, self.base_project_pi_user.get_coder_org_unit_ids())
        self.assertEqual(
            self.base_project_pi_user.get_org_unit_projects("coder"), {self.PROJECT}
        )

    # -- database constraints ----------------------------------------------

    def test_scope_shape_and_cadre_constraints_hold_in_the_database(self):
        _, chc, _, _, _ = self._tree()
        cadres = self._cadres()

        # org_unit scope may not also carry a project_id.
        db.session.add(
            VaUserAccessGrants(
                user_id=self.base_coder_user.user_id,
                role=VaAccessRoles.reviewer,
                scope_type=VaAccessScopeTypes.org_unit,
                project_id=self.PROJECT,
                org_unit_id=chc.org_unit_id,
                grant_status=VaStatuses.active,
            )
        )
        with self.assertRaises(sa.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()

        # A cadre is meaningless outside a unit grant.
        db.session.add(
            VaUserAccessGrants(
                user_id=self.base_coder_user.user_id,
                role=VaAccessRoles.reviewer,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.PROJECT,
                cadre_id=cadres["SMO"].cadre_id,
                grant_status=VaStatuses.active,
            )
        )
        with self.assertRaises(sa.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_one_active_grant_per_user_role_and_unit(self):
        _, chc, _, _, _ = self._tree()
        cadres = self._cadres()
        self._grant(self.base_coder_user.user_id, VaAccessRoles.coder, chc, cadres["SMO"])
        db.session.add(
            VaUserAccessGrants(
                user_id=self.base_coder_user.user_id,
                role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.org_unit,
                org_unit_id=chc.org_unit_id,
                cadre_id=cadres["MO"].cadre_id,
                grant_status=VaStatuses.active,
            )
        )
        with self.assertRaises(sa.exc.IntegrityError):
            db.session.commit()
        db.session.rollback()


class OrgUnitGrantApiTests(BaseTestCase):
    PROJECT = "OGR010"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(
                VaProjectMaster(
                    project_id=cls.PROJECT,
                    project_code=cls.PROJECT,
                    project_name="Unit Grant API Project",
                    project_nickname="UnitGrantApi",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
        db.session.commit()

    def _tree(self):
        org.seed_default_organization(self.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        district = org.create_unit(
            self.PROJECT, org_level_id=levels["district"].org_level_id,
            unit_code="D01", unit_name="District One",
        )
        chc = org.create_unit(
            self.PROJECT, org_level_id=levels["chc"].org_level_id,
            parent_org_unit_id=district.org_unit_id, unit_code="C01", unit_name="CHC One",
        )
        db.session.commit()
        cadres = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}
        return chc, cadres

    def _post_grant(self, body):
        return self.client.post(
            "/admin/api/access-grants", json=body, headers=self._csrf_headers()
        )

    def test_panel_offers_unit_scope_with_unit_and_cadre_pickers(self):
        self._login(str(self.base_admin_id))
        response = self.client.get(f"/admin/panels/access-grants?project_id={self.PROJECT}")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('value="org_unit"', body)
        self.assertIn('id="ag-unit"', body)
        self.assertIn('id="ag-cadre"', body)

    def test_admin_creates_a_unit_grant_and_reads_it_back(self):
        chc, cadres = self._tree()
        self._login(str(self.base_admin_id))
        response = self._post_grant(
            {
                "user_id": str(self.base_coder_user.user_id),
                "role": "coder",
                "scope_type": "org_unit",
                "org_unit_id": str(chc.org_unit_id),
                "cadre_id": str(cadres["SMO"].cadre_id),
                "notes": "SMO at CHC One",
            }
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        grant = response.get_json()["grant"]
        self.assertEqual(grant["scope_type"], "org_unit")
        self.assertEqual(grant["project_id"], self.PROJECT)
        self.assertEqual(grant["unit_code"], "C01")
        self.assertEqual(grant["cadre_code"], "SMO")
        self.assertEqual(grant["unit_path"], "D01.C01")
        self.assertIsNone(grant["site_id"])

        listed = self.client.get(f"/admin/api/access-grants?project_id={self.PROJECT}")
        self.assertEqual(listed.status_code, 200)
        unit_grants = [g for g in listed.get_json()["grants"] if g["scope_type"] == "org_unit"]
        self.assertEqual([g["unit_code"] for g in unit_grants], ["C01"])

    def test_api_rejects_a_coder_grant_whose_cadre_may_not_code(self):
        chc, cadres = self._tree()
        self._login(str(self.base_admin_id))
        response = self._post_grant(
            {
                "user_id": str(self.base_coder_user.user_id),
                "role": "coder",
                "scope_type": "org_unit",
                "org_unit_id": str(chc.org_unit_id),
                "cadre_id": str(cadres["ASHA"].cadre_id),
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not defined at level", response.get_json()["error"])

    def test_api_rejects_mixed_scope_payloads(self):
        chc, cadres = self._tree()
        self._login(str(self.base_admin_id))
        for payload, expected in (
            ({"scope_type": "org_unit"}, "requires org_unit_id"),
            (
                {"scope_type": "org_unit", "org_unit_id": str(chc.org_unit_id), "project_id": self.PROJECT},
                "must not include project_id",
            ),
            ({"scope_type": "project", "project_id": self.PROJECT, "org_unit_id": str(chc.org_unit_id)},
             "requires project_id only"),
        ):
            body = {
                "user_id": str(self.base_coder_user.user_id),
                "role": "reviewer",
            }
            body.update(payload)
            response = self._post_grant(body)
            self.assertEqual(response.status_code, 400, response.get_json())
            self.assertIn(expected, response.get_json()["error"])

    def test_project_pi_sees_and_manages_unit_grants_of_their_own_project_only(self):
        chc, cadres = self._tree()
        self._login(str(self.base_admin_id))
        self.assertEqual(
            self._post_grant(
                {
                    "user_id": str(self.base_coder_user.user_id),
                    "role": "reviewer",
                    "scope_type": "org_unit",
                    "org_unit_id": str(chc.org_unit_id),
                }
            ).status_code,
            201,
        )

        # The base PI holds project_pi on BASE_PROJECT_ID, not on this project.
        self._login(str(self.base_project_pi_id))
        listed = self.client.get("/admin/api/access-grants")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            [g for g in listed.get_json()["grants"] if g["scope_type"] == "org_unit"], []
        )
        denied = self._post_grant(
            {
                "user_id": str(self.base_coder_user.user_id),
                "role": "coder",
                "scope_type": "org_unit",
                "org_unit_id": str(chc.org_unit_id),
                "cadre_id": str(cadres["SMO"].cadre_id),
            }
        )
        self.assertEqual(denied.status_code, 403)

        # Granted project_pi on this project, the same PI sees and creates them.
        db.session.add(
            VaUserAccessGrants(
                user_id=self.base_project_pi_user.user_id,
                role=VaAccessRoles.project_pi,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.PROJECT,
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        self._login(str(self.base_project_pi_id))
        listed = self.client.get(f"/admin/api/access-grants?project_id={self.PROJECT}")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            [g["unit_code"] for g in listed.get_json()["grants"] if g["scope_type"] == "org_unit"],
            ["C01"],
        )
        allowed = self._post_grant(
            {
                "user_id": str(self.base_coder_user.user_id),
                "role": "coder",
                "scope_type": "org_unit",
                "org_unit_id": str(chc.org_unit_id),
                "cadre_id": str(cadres["SMO"].cadre_id),
            }
        )
        self.assertEqual(allowed.status_code, 201, allowed.get_json())

    def test_project_pi_may_revoke_a_unit_grant_in_their_own_project(self):
        chc, _ = self._tree()
        self._login(str(self.base_admin_id))
        created = self._post_grant(
            {
                "user_id": str(self.base_coder_user.user_id),
                "role": "reviewer",
                "scope_type": "org_unit",
                "org_unit_id": str(chc.org_unit_id),
            }
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        grant_id = created.get_json()["grant"]["grant_id"]

        # A PI without project_pi on this project cannot revoke it.
        self._login(str(self.base_project_pi_id))
        denied = self.client.post(
            f"/admin/api/access-grants/{grant_id}/toggle", headers=self._csrf_headers()
        )
        self.assertEqual(denied.status_code, 403)

        db.session.add(
            VaUserAccessGrants(
                user_id=self.base_project_pi_user.user_id,
                role=VaAccessRoles.project_pi,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.PROJECT,
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        self._login(str(self.base_project_pi_id))
        allowed = self.client.post(
            f"/admin/api/access-grants/{grant_id}/toggle", headers=self._csrf_headers()
        )
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        self.assertEqual(allowed.get_json()["status"], "deactive")

    def test_data_manager_grant_interface_refuses_unit_scope(self):
        """Even for an admin: that interface knows projects and sites, not units."""
        chc, cadres = self._tree()
        self._login(str(self.base_admin_id))
        for role, extra in (
            ("reviewer", {}),
            ("coder", {"cadre_id": str(cadres["SMO"].cadre_id)}),
        ):
            body = {
                "user_id": str(self.base_coder_user.user_id),
                "role": role,
                "scope_type": "org_unit",
                "org_unit_id": str(chc.org_unit_id),
            }
            body.update(extra)
            response = self.client.post(
                "/data-management/api/access-grants",
                json=body,
                headers=self._csrf_headers(),
            )
            self.assertEqual(response.status_code, 403, response.get_json())
            self.assertIn("admin user panel", response.get_json()["error"])
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaUserAccessGrants)
                .where(VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit)
            ),
            0,
        )
