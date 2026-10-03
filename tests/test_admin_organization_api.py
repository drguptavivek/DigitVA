"""HTTP contract of app/routes/admin_organization.py: authorization and thin dispatch."""
import io
from datetime import UTC, datetime
from unittest.mock import patch

import sqlalchemy as sa
from openpyxl import load_workbook

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.mas_languages import MasLanguages
from app.services import organization_service as org
from tests.base import BaseTestCase


class AdminOrganizationApiTests(BaseTestCase):
    PROJECT = "ORGA01"
    SITES_PROJECT = "ORGS01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Org API Project",
                project_nickname="OrgApi",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
                project_structure_mode="organization",
            )
        )
        db.session.add(
            VaProjectMaster(
                project_id=cls.SITES_PROJECT,
                project_code=cls.SITES_PROJECT,
                project_name="Sites Project",
                project_nickname="Sites",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        if db.session.get(MasLanguages, "en") is None:
            db.session.add(MasLanguages(language_code="en", language_name="English", is_active=True))
        db.session.commit()

    def _url(self, suffix=""):
        return f"/admin/api/organization/{self.PROJECT}{suffix}"

    def _import_users(self, text, dry_run="1"):
        return self.client.post(
            self._url("/project-users/import"),
            data={"file": (io.BytesIO(text.encode("utf-8")), "users.csv"), "dry_run": dry_run},
            content_type="multipart/form-data", headers=self._csrf_headers(),
        )

    def test_blank_csv_templates(self):
        self._login(str(self.base_admin_id))
        units = self.client.get(self._url("/templates/units.csv"))
        users = self.client.get(self._url("/templates/project-users.csv"))
        self.assertEqual(units.status_code, 200)
        self.assertEqual(users.status_code, 200)
        self.assertTrue(units.get_data(as_text=True).startswith("unit_code,unit_name,level_code,parent_code"))
        self.assertNotIn(",path,", units.get_data(as_text=True))
        self.assertEqual(users.get_data(as_text=True).strip(),
                         "email,name,role,org_unit_code,cadre_code,language_codes,phone")

    def test_blank_xlsx_templates(self):
        self._login(str(self.base_admin_id))
        for suffix, first in (("/templates/units.xlsx", "unit_code"),
                              ("/templates/project-users.xlsx", "email")):
            response = self.client.get(self._url(suffix))
            self.assertEqual(response.status_code, 200)
            workbook = load_workbook(io.BytesIO(response.data), read_only=True)
            self.assertEqual(workbook.active.cell(1, 1).value, first)
            workbook.close()

    def test_excel_csv_and_xlsx_user_import_preview(self):
        self._login(str(self.base_admin_id))
        csv_body = ("sep=;\r\n EMAIL ; NAME ; ROLE ; ORG_UNIT_CODE ; CADRE_CODE ; LANGUAGE_CODES ; PHONE ;\r\n"
                    "excel@example.org;Café;reviewer;;;en;;\r\n").encode("cp1252")
        response = self.client.post(
            self._url("/project-users/import"),
            data={"file": (io.BytesIO(csv_body), "users.csv")},
            content_type="multipart/form-data", headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["rows"][0]["email"], "excel@example.org")

        template = self.client.get(self._url("/templates/project-users.xlsx"))
        workbook = load_workbook(io.BytesIO(template.data))
        workbook.active.append(["xlsx@example.org", "Workbook", "reviewer", "", "", "en", ""])
        content = io.BytesIO()
        workbook.save(content)
        response = self.client.post(
            self._url("/project-users/import"),
            data={"file": (io.BytesIO(content.getvalue()), "users.xlsx")},
            content_type="multipart/form-data", headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["rows"][0]["email"], "xlsx@example.org")
        with patch("app.services.email_service.is_mail_configured", return_value=False):
            applied = self.client.post(
                self._url("/project-users/import"),
                data={"file": (io.BytesIO(content.getvalue()), "users.xlsx"), "dry_run": "0"},
                content_type="multipart/form-data", headers=self._csrf_headers(),
            )
        self.assertEqual(applied.status_code, 200, applied.get_json())
        self.assertEqual(applied.get_json()["created_users"], 1)
        self.assertIsNotNone(db.session.scalar(
            sa.select(VaUsers).where(VaUsers.email == "xlsx@example.org")
        ))

    def test_invalid_role_error_lists_grantable_roles(self):
        self._login(str(self.base_admin_id))
        response = self._import_users(
            "email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
            "invalid-role@example.org,Name,bogus,,,en,\n"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("role must be one of:", response.get_json()["error"])
        self.assertNotIn("VaAccessRoles", response.get_json()["error"])

    def test_project_pi_cannot_see_inactive_account_status_or_grant_pi(self):
        db.session.add(VaUserAccessGrants(
            user_id=self.base_project_pi_user.user_id,
            role=VaAccessRoles.project_pi,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
            grant_status=VaStatuses.active,
        ))
        inactive = VaUsers(email="inactive-import@example.org", name="Inactive Import",
                           user_status=VaStatuses.deactive, permission={},
                           landing_page="coder", pw_reset_t_and_c=False,
                           email_verified=True, vacode_language=["en"])
        inactive.set_password("UnusedPassword123!")
        db.session.add(inactive)
        db.session.commit()
        self._login(str(self.base_project_pi_id))
        header = "email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
        unknown = self._import_users(header + "missing-import@example.org,,reviewer,,,,\n")
        disabled = self._import_users(header + "inactive-import@example.org,,reviewer,,,,\n")
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(disabled.status_code, 400)
        self.assertEqual(unknown.get_json()["error"].replace("missing-import@example.org", "EMAIL"),
                         disabled.get_json()["error"].replace("inactive-import@example.org", "EMAIL"))
        denied = self._import_users(header + "base.coder@test.local,,project_pi,,,,\n")
        self.assertEqual(denied.status_code, 400)
        self.assertIn("role must be one of:", denied.get_json()["error"])

    def test_blank_cadre_on_rerun_preserves_existing_grant_cadre(self):
        self._login(str(self.base_admin_id))
        org.seed_default_organization(self.PROJECT)
        levels = {level.level_code: level for level in org.list_levels(self.PROJECT)}
        district = org.create_unit(self.PROJECT, org_level_id=levels["district"].org_level_id,
                                   unit_code="D90", unit_name="District 90")
        chc = org.create_unit(self.PROJECT, org_level_id=levels["chc"].org_level_id,
                              unit_code="C90", unit_name="CHC 90",
                              parent_org_unit_id=district.org_unit_id)
        phc = org.create_unit(self.PROJECT, org_level_id=levels["phc"].org_level_id,
                              unit_code="P90", unit_name="PHC 90",
                              parent_org_unit_id=chc.org_unit_id)
        cadre = next(c for c in org.list_cadres(self.PROJECT) if c.cadre_code == "MO")
        grant = VaUserAccessGrants(
            user_id=self.base_coder_id, role=VaAccessRoles.reviewer,
            scope_type=VaAccessScopeTypes.org_unit, org_unit_id=phc.org_unit_id,
            cadre_id=cadre.cadre_id, grant_status=VaStatuses.active,
        )
        db.session.add(grant)
        db.session.commit()
        response = self._import_users(
            "email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
            "base.coder@test.local,,reviewer,P90,,,\n", dry_run="0",
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["changed_grants"], 0)
        db.session.refresh(grant)
        self.assertEqual(grant.cadre_id, cadre.cadre_id)

    def test_other_project_pi_cannot_import_or_download_templates(self):
        self._login(str(self.base_project_pi_id))
        for suffix in ("/templates/units.csv", "/templates/units.xlsx",
                       "/templates/project-users.csv", "/templates/project-users.xlsx"):
            self.assertEqual(self.client.get(self._url(suffix)).status_code, 403)
        response = self._import_users(
            "email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
            "someone@example.org,,reviewer,,,,\n"
        )
        self.assertEqual(response.status_code, 403)
        units = self.client.post(
            self._url("/import"),
            data={"file": (io.BytesIO(b"unit_code,unit_name,level_code\nP01,PHC,phc\n"),
                           "units.csv"), "sheet": "units", "dry_run": "1"},
            content_type="multipart/form-data", headers=self._csrf_headers(),
        )
        self.assertEqual(units.status_code, 403)

    def test_invalid_row_leaves_no_account_or_grant(self):
        self._login(str(self.base_admin_id))
        header = "email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
        response = self._import_users(header +
            "valid@example.org,Valid,coder,,,en,\n" +
            "bad@example.org,Bad,admin,,,en,\n", dry_run="0")
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIsNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "valid@example.org")))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaUserAccessGrants)
                          .where(VaUserAccessGrants.project_id == self.PROJECT)), 0)

    def test_blank_line_keeps_physical_row_number(self):
        self._login(str(self.base_admin_id))
        response = self._import_users(
            "email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
            "\n"
            "bad@example.org,Bad,admin,,,en,\n"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Row 3", response.get_json()["error"])

    def test_conflicting_new_user_profiles_reject_whole_file(self):
        self._login(str(self.base_admin_id))
        response = self._import_users(
            "email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
            "conflict@example.org,First,reviewer,,,en,\n"
            "conflict@example.org,Second,data_manager,,,en,\n",
            dry_run="0",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("profile differs", response.get_json()["error"])
        self.assertIsNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "conflict@example.org")))

    def test_admin_import_creates_one_account_and_rerun_retains_grant(self):
        self._login(str(self.base_admin_id))
        text = ("email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
                "bulk@example.org,Bulk User,reviewer,,,en,\n")
        preview = self._import_users(text)
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertEqual(preview.get_json()["rows"][0]["scope"], "whole project")
        self.assertIsNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "bulk@example.org")))
        with patch("app.services.email_service.is_mail_configured", return_value=True), patch(
            "app.services.email_service.send_verification_email", return_value=True
        ) as verification, patch(
            "app.services.email_service.send_password_reset_email", return_value=True
        ) as password:
            first = self._import_users(text, dry_run="0")
        self.assertEqual(first.status_code, 200, first.get_json())
        self.assertEqual(first.get_json()["created_users"], 1)
        self.assertEqual(first.get_json()["invitations_queued"], 1)
        verification.assert_called_once()
        # digitva-kmoy: no reset link at creation; verifying emails the password.
        password.assert_not_called()
        second = self._import_users(text, dry_run="0")
        self.assertEqual(second.status_code, 200, second.get_json())
        self.assertEqual(second.get_json()["changed_grants"], 0)

    def test_disabled_email_reports_skipped_invitation(self):
        self._login(str(self.base_admin_id))
        text = ("email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
                "skipped@example.org,Skipped,reviewer,,,en,\n")
        with patch("app.services.email_service.is_mail_configured", return_value=True), patch(
            "app.services.email_service._email_delivery_enabled", return_value=False
        ):
            response = self._import_users(text, dry_run="0")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["invitations_queued"], 0)
        self.assertTrue(any("skipped@example.org" in warning
                            for warning in response.get_json()["invite_warnings"]))

    def test_unconfigured_email_does_not_queue_invitations(self):
        self._login(str(self.base_admin_id))
        text = ("email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
                "unconfigured@example.org,Unconfigured,reviewer,,,en,\n")
        with patch("app.services.email_service.is_mail_configured", return_value=False), patch(
            "app.services.email_service.send_verification_email"
        ) as verification, patch(
            "app.services.email_service.send_password_reset_email"
        ) as password:
            response = self._import_users(text, dry_run="0")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["invitations_queued"], 0)
        self.assertTrue(any("not configured" in warning
                            for warning in response.get_json()["invite_warnings"]))
        verification.assert_not_called()
        password.assert_not_called()

    def test_project_pi_can_attach_existing_user_but_cannot_create_account(self):
        db.session.add(VaUserAccessGrants(
            user_id=self.base_project_pi_user.user_id,
            role=VaAccessRoles.project_pi,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._login(str(self.base_project_pi_id))
        existing = ("email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
                    "base.coder@test.local,,reviewer,,,,\n")
        response = self._import_users(existing, dry_run="0")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["created_users"], 0)
        new = ("email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
               "new-pi@example.org,New,reviewer,,,en,\n")
        denied = self._import_users(new, dry_run="0")
        self.assertEqual(denied.status_code, 400, denied.get_json())
        self.assertIsNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "new-pi@example.org")))

    def test_panel_renders_for_admin(self):
        self._login(str(self.base_admin_id))
        response = self.client.get(f"/admin/panels/organization?project_id={self.PROJECT}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="panel-organization"', response.data)
        html = response.get_data(as_text=True)
        self.assertIn('id="org-reference-model"', html)
        self.assertIn("<summary", html)  # collapsed without Bootstrap JS
        self.assertIn("District reference model", html)
        self.assertIn("CS Civil Surgeon", html)
        # The in-charge cadres suggest site_pi, shown as In-charge (held at a unit)
        self.assertIn('href="/help/user-roles#role-site_pi">In-charge</a>', html)
        self.assertNotIn('role-site_pi">site_pi</a>', html)
        self.assertNotIn('href="/help/user-roles#role-interview_supervisor"', html)
        self.assertIn('href="/help/user-roles#role-death_reporter"', html)
        self.assertIn('href="/help/user-roles">What each role can do</a>', html)
        self.assertIn("Populate district defaults", html)
        self.assertNotIn(">Seed template<", html)

    def test_coder_is_forbidden(self):
        self._login(str(self.base_coder_id))
        response = self.client.get(self._url())
        self.assertIn(response.status_code, (302, 403))

    def test_project_pi_of_other_project_is_forbidden(self):
        self._login(str(self.base_project_pi_id))
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "You do not have access to that project.")

    def test_project_pi_manages_own_project(self):
        from app.models import VaAccessRoles, VaAccessScopeTypes, VaUserAccessGrants

        db.session.add(
            VaUserAccessGrants(
                user_id=self.base_project_pi_id,
                role=VaAccessRoles.project_pi,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.PROJECT,
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        self._login(str(self.base_project_pi_id))
        headers = self._csrf_headers()
        self.assertEqual(self.client.post(self._url("/seed-template"), json={}, headers=headers).status_code, 200)
        level = self.client.get(self._url("/levels")).get_json()["levels"][0]
        created = self.client.post(
            self._url("/units"),
            json={"org_level_id": level["org_level_id"], "unit_code": "D01", "unit_name": "District One"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        missing_flag = self.client.post(self._url(f"/units/{created.get_json()['unit']['org_unit_id']}/toggle"), json={}, headers=headers)
        self.assertEqual(missing_flag.status_code, 400)

    def test_admin_builds_tree_through_api(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()

        seeded = self.client.post(self._url("/seed-template"), json={}, headers=headers)
        self.assertEqual(seeded.status_code, 200)
        self.assertEqual(seeded.get_json()["seeded"]["levels"], 6)

        levels = {lv["level_code"]: lv for lv in self.client.get(self._url("/levels")).get_json()["levels"]}
        created = self.client.post(
            self._url("/units"),
            json={"org_level_id": levels["district"]["org_level_id"], "unit_code": "d01", "unit_name": "District One", "google_maps_url": "https://maps.app.goo.gl/abc"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        district = created.get_json()["unit"]
        self.assertEqual(district["unit_code"], "D01")

        bad = self.client.post(
            self._url("/units"),
            json={"org_level_id": levels["phc"]["org_level_id"], "parent_org_unit_id": district["org_unit_id"], "unit_code": "P01", "unit_name": "Skips CHC"},
            headers=headers,
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn("'chc'", bad.get_json()["error"])

        chc = self.client.post(
            self._url("/units"),
            json={"org_level_id": levels["chc"]["org_level_id"], "parent_org_unit_id": district["org_unit_id"], "unit_code": "C01", "unit_name": "CHC One"},
            headers=headers,
        ).get_json()["unit"]
        self.assertEqual(chc["path"], "D01.C01")
        self.assertEqual(chc["parent_code"], "D01")

        summary = self.client.get(self._url()).get_json()
        self.assertEqual(summary["units"][0]["children"][0]["unit_code"], "C01")
        self.assertEqual(len(summary["level_cadres"]), len(org.DEFAULT_LEVEL_CADRE_TEMPLATE))

        toggled = self.client.post(self._url(f"/units/{district['org_unit_id']}/toggle"), json={"is_active": False}, headers=headers)
        self.assertEqual(toggled.get_json()["changed"], 2)
        self.assertEqual(self.client.get(self._url("/units")).get_json()["units"], [])
        self.assertEqual(len(self.client.get(self._url("/units?include_inactive=1")).get_json()["units"]), 2)

        perm = self.client.put(
            self._url("/level-cadres"),
            json={"org_level_id": levels["district"]["org_level_id"], "cadre_id": summary["cadres"][0]["cadre_id"], "can_fill_va_form": False, "can_code_va_form": True},
            headers=headers,
        )
        self.assertEqual(perm.status_code, 200)
        self.assertTrue(perm.get_json()["level_cadre"]["can_code_va_form"])

        reactivated = self.client.post(self._url(f"/units/{district['org_unit_id']}/toggle"), json={"is_active": True}, headers=headers)
        self.assertEqual(reactivated.status_code, 200)
        smo_cadre_id = next(c["cadre_id"] for c in summary["cadres"] if c["cadre_code"] == "SMO")
        worker = self.client.post(
            self._url("/workers"),
            json={"org_unit_id": chc["org_unit_id"], "cadre_id": smo_cadre_id, "worker_name": "Dr Test"},
            headers=headers,
        )
        self.assertEqual(worker.status_code, 201, worker.get_json())
        blocked = self.client.put(
            self._url("/level-cadres"),
            json={"org_level_id": levels["chc"]["org_level_id"], "cadre_id": smo_cadre_id, "can_fill_va_form": False, "can_code_va_form": True, "is_active": False},
            headers=headers,
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("first", blocked.get_json()["error"])

    def _seed_one_unit(self, headers):
        self.client.post(self._url("/seed-template"), json={}, headers=headers)
        level = self.client.get(self._url("/levels")).get_json()["levels"][0]
        created = self.client.post(
            self._url("/units"),
            json={"org_level_id": level["org_level_id"], "unit_code": "D01", "unit_name": "District One"},
            headers=headers,
        )
        return created.get_json()["unit"]["org_unit_id"]

    def test_va_presets_set_get_and_clear_round_trip(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        unit_id = self._seed_one_unit(headers)

        empty = self.client.get(self._url(f"/units/{unit_id}/va-presets"))
        self.assertEqual(empty.status_code, 200)
        self.assertIsNone(empty.get_json()["va_presets"])
        self.assertEqual(empty.get_json()["inherited"], {})

        saved = self.client.put(
            self._url(f"/units/{unit_id}/va-presets"),
            json={"hiv_mortality": "high", "malaria_mortality": "low"},
            headers=headers,
        )
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(saved.get_json()["va_presets"]["hiv_mortality"], "high")
        self.assertEqual(saved.get_json()["va_presets"]["malaria_mortality"], "low")

        fetched = self.client.get(self._url(f"/units/{unit_id}/va-presets")).get_json()
        self.assertEqual(fetched["va_presets"]["hiv_mortality"], "high")

        cleared = self.client.delete(self._url(f"/units/{unit_id}/va-presets"), headers=headers)
        self.assertEqual(cleared.status_code, 200)
        self.assertTrue(cleared.get_json()["cleared"])
        self.assertIsNone(self.client.get(self._url(f"/units/{unit_id}/va-presets")).get_json()["va_presets"])

    def test_va_presets_reports_inherited_value_and_source_unit(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        parent_id = self._seed_one_unit(headers)
        self.client.put(
            self._url(f"/units/{parent_id}/va-presets"), json={"hiv_mortality": "veryl"}, headers=headers,
        )
        levels = {lv["level_code"]: lv for lv in self.client.get(self._url("/levels")).get_json()["levels"]}
        child = self.client.post(
            self._url("/units"),
            json={
                "org_level_id": levels["chc"]["org_level_id"], "parent_org_unit_id": parent_id,
                "unit_code": "C01", "unit_name": "Child CHC",
            },
            headers=headers,
        ).get_json()["unit"]

        result = self.client.get(self._url(f"/units/{child['org_unit_id']}/va-presets")).get_json()

        self.assertIsNone(result["va_presets"])
        self.assertEqual(result["inherited"]["hiv_mortality"]["value"], "veryl")
        self.assertEqual(result["inherited"]["hiv_mortality"]["source_unit_name"], "District One")

    def test_va_presets_rejects_bad_value(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        unit_id = self._seed_one_unit(headers)

        bad = self.client.put(
            self._url(f"/units/{unit_id}/va-presets"), json={"hiv_mortality": "bogus"}, headers=headers,
        )

        self.assertEqual(bad.status_code, 400)
        self.assertIsNone(org.get_unit_va_presets(self.PROJECT, unit_id))

    def test_va_presets_requires_csrf_token(self):
        self._login(str(self.base_admin_id))
        unit_id = self._seed_one_unit(self._csrf_headers())

        no_token = self.client.put(self._url(f"/units/{unit_id}/va-presets"), json={"hiv_mortality": "high"})

        self.assertEqual(no_token.status_code, 400)
        self.assertIn("CSRF", no_token.get_json()["error"])
        self.assertIsNone(org.get_unit_va_presets(self.PROJECT, unit_id))

    def test_va_presets_forbidden_for_coder(self):
        self._login(str(self.base_coder_id))

        response = self.client.get(self._url("/units/00000000-0000-0000-0000-000000000000/va-presets"))

        self.assertIn(response.status_code, (302, 403))

    def test_export_and_import_endpoints(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        org.seed_default_organization(self.PROJECT)
        level = org.list_levels(self.PROJECT)[0]
        org.create_unit(self.PROJECT, org_level_id=level.org_level_id, unit_code="D01", unit_name="District One")
        db.session.commit()

        xlsx = self.client.get(self._url("/export.xlsx"))
        self.assertEqual(xlsx.status_code, 200)
        self.assertIn("spreadsheetml", xlsx.mimetype)
        csv_resp = self.client.get(self._url("/export/units.csv"))
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("D01,District One,district", csv_resp.get_data(as_text=True))
        choices = self.client.get(self._url("/odk-choices.csv"))
        self.assertIn("org_district,D01,District One,", choices.get_data(as_text=True))
        self.assertEqual(self.client.get(self._url("/export/bogus.csv")).status_code, 400)

        dry = self.client.post(
            self._url("/import"),
            data={"file": (io.BytesIO(xlsx.data), "org.xlsx"), "dry_run": "1"},
            content_type="multipart/form-data",
            headers=headers,
        )
        self.assertEqual(dry.status_code, 200, dry.get_json())
        body = dry.get_json()
        self.assertTrue(body["dry_run"])
        self.assertFalse(body["plan"]["applied"])
        self.assertEqual(body["plan"]["counts"]["units"]["update"], 1)

        rejected = self.client.post(
            self._url("/import"),
            data={"file": (io.BytesIO(b"not a workbook"), "org.xlsx"), "dry_run": "1"},
            content_type="multipart/form-data",
            headers=headers,
        )
        self.assertEqual(rejected.status_code, 400)

    def test_upload_request_limits_return_json_413(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        for suffix, size, filename in (
            ("/project-users/import", 1024 * 1024 + 64 * 1024, "users.csv"),
            ("/import", 5 * 1024 * 1024 + 64 * 1024, "units.csv"),
        ):
            with self.subTest(suffix=suffix):
                response = self.client.post(
                    self._url(suffix),
                    data={"file": (io.BytesIO(b"x" * (size + 1)), filename)},
                    content_type="multipart/form-data", headers=headers,
                )
                self.assertEqual(response.status_code, 413, response.get_json())
                self.assertIn("limit", response.get_json()["error"])

    def test_json_unit_text_is_safe_in_csv_and_xlsx_exports(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        org.seed_default_organization(self.PROJECT)
        district = next(level for level in org.list_levels(self.PROJECT) if level.level_code == "district")
        created = self.client.post(
            self._url("/units"),
            json={"org_level_id": str(district.org_level_id), "unit_code": "D90",
                  "unit_name": "=HYPERLINK(1)", "latitude": "-12.5"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        unit_id = created.get_json()["unit"]["org_unit_id"]
        updated = self.client.patch(
            self._url(f"/units/{unit_id}"), json={"remarks": "@SUM(1)"}, headers=headers,
        )
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()["unit"]["unit_name"], "=HYPERLINK(1)")

        csv_rows = self.client.get(self._url("/export/units.csv")).get_data(as_text=True)
        self.assertIn("'=HYPERLINK(1)", csv_rows)
        self.assertIn("'@SUM(1)", csv_rows)
        self.assertIn("-12.500000", csv_rows)
        workbook = load_workbook(io.BytesIO(self.client.get(self._url("/export.xlsx")).data))
        try:
            headings = [cell.value for cell in workbook["units"][1]]
            exported = next(row for row in workbook["units"].iter_rows(min_row=2)
                            if row[0].value == "D90")
            self.assertEqual(exported[headings.index("unit_name")].value, "'=HYPERLINK(1)")
            self.assertEqual(exported[headings.index("unit_name")].data_type, "s")
            self.assertEqual(exported[headings.index("remarks")].value, "'@SUM(1)")
            self.assertEqual(exported[headings.index("latitude")].value, "-12.500000")
        finally:
            workbook.close()

    def _import_csv(self, headers, sheet, text, dry_run):
        return self.client.post(
            self._url("/import"),
            data={"file": (io.BytesIO(text.encode("utf-8-sig")), f"{sheet}.csv"), "sheet": sheet, "dry_run": "1" if dry_run else "0"},
            content_type="multipart/form-data",
            headers=headers,
        )

    def test_csv_import_adds_cadres_placements_and_workers(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        org.seed_default_organization(self.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        district = org.create_unit(self.PROJECT, org_level_id=levels["district"].org_level_id, unit_code="D01", unit_name="District One")
        org.create_unit(self.PROJECT, org_level_id=levels["chc"].org_level_id, parent_org_unit_id=district.org_unit_id, unit_code="C01", unit_name="CHC One")
        db.session.commit()

        cadres = "cadre_code,cadre_name\nLT,Lab Technician\n"
        dry = self._import_csv(headers, "cadres", cadres, dry_run=True)
        self.assertEqual(dry.status_code, 200, dry.get_json())
        self.assertEqual(dry.get_json()["plan"]["counts"]["cadres"]["create"], 1)
        self.assertNotIn("LT", {c.cadre_code for c in org.list_cadres(self.PROJECT)})
        self.assertEqual(self._import_csv(headers, "cadres", cadres, dry_run=False).status_code, 200)
        self.assertIn("LT", {c.cadre_code for c in org.list_cadres(self.PROJECT)})

        placements = "level_code,cadre_code,can_fill_va_form,can_code_va_form\nchc,LT,true,false\n"
        self.assertEqual(self._import_csv(headers, "level_cadres", placements, dry_run=False).status_code, 200)

        workers = "worker_code,worker_name,unit_code,cadre_code,phone,user_email,remarks,is_active\nW01,Lab Person,C01,LT,,,,\n"
        applied = self._import_csv(headers, "workers", workers, dry_run=False)
        self.assertEqual(applied.status_code, 200, applied.get_json())
        worker = {w["worker_code"]: w for w in org.list_workers(self.PROJECT, include_inactive=True)}["W01"]
        self.assertTrue(worker["is_active"])
        self.assertIsNone(worker["phone"])

        # A re-upload with a blank is_active keeps the worker active: blank
        # CSV cells mean "no value", as empty workbook cells do.
        again = self._import_csv(headers, "workers", workers.replace("Lab Person", "Lab Person Two"), dry_run=False)
        self.assertEqual(again.status_code, 200, again.get_json())
        worker = {w["worker_code"]: w for w in org.list_workers(self.PROJECT, include_inactive=True)}["W01"]
        self.assertEqual(worker["worker_name"], "Lab Person Two")
        self.assertTrue(worker["is_active"])

        # A worker whose cadre is not placed at the unit's level is refused.
        bad = self._import_csv(headers, "workers", "worker_code,worker_name,unit_code,cadre_code\nW02,Nobody,D01,LT\n", dry_run=True)
        self.assertEqual(bad.status_code, 400)
        self.assertTrue(bad.get_json()["plan"]["errors"])

        unknown_sheet = self._import_csv(headers, "bogus", cadres, dry_run=True)
        self.assertEqual(unknown_sheet.status_code, 400)

    def test_import_rejects_invalid_boolean_rows_without_partial_writes(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        org.seed_default_organization(self.PROJECT)
        levels = {level.level_code: level for level in org.list_levels(self.PROJECT)}
        district = org.create_unit(
            self.PROJECT, org_level_id=levels["district"].org_level_id,
            unit_code="D90", unit_name="District 90",
        )
        org.create_unit(
            self.PROJECT, org_level_id=levels["chc"].org_level_id,
            unit_code="C90", unit_name="CHC 90", parent_org_unit_id=district.org_unit_id,
        )
        db.session.commit()
        original_level_cadres = org.list_level_cadres(self.PROJECT)
        cases = (
            ("levels", "level_code,level_name,depth,is_optional,is_active\n"
             "newlevel,New Level,7,false,true\ninvalid,Invalid Level,8,maybe,true\n",
             "is_optional", "NEWLEVEL"),
            ("levels", "level_code,level_name,depth,is_optional,is_active\n"
             "newlevel,New Level,7,false,true\ninvalid,Invalid Level,8,false,maybe\n",
             "is_active", "NEWLEVEL"),
            ("cadres", "cadre_code,cadre_name,is_active\nLT,Lab Technician,true\nXT,Other,falseish\n",
             "is_active", "LT"),
            ("level_cadres", "level_code,cadre_code,can_fill_va_form,can_code_va_form,is_active\n"
             "district,MO,true,false,true\ndistrict,SMO,maybe,false,true\n",
             "can_fill_va_form", None),
            ("level_cadres", "level_code,cadre_code,can_fill_va_form,can_code_va_form,is_active\n"
             "district,MO,true,false,true\ndistrict,SMO,false,maybe,true\n",
             "can_code_va_form", None),
            ("level_cadres", "level_code,cadre_code,can_fill_va_form,can_code_va_form,is_active\n"
             "district,MO,true,false,true\ndistrict,SMO,false,false,maybe\n",
             "is_active", None),
            ("workers", "worker_code,worker_name,unit_code,cadre_code,is_active\n"
             "W90,First,C90,MO,true\nW91,Second,C90,MO,maybe\n",
             "is_active", "W90"),
        )
        for sheet, content, field, created_code in cases:
            with self.subTest(sheet=sheet, field=field):
                for dry_run in (True, False):
                    response = self._import_csv(headers, sheet, content, dry_run=dry_run)
                    self.assertEqual(response.status_code, 400, response.get_json())
                    self.assertIn(f"{sheet} row 3: {field} must be true or false",
                                  response.get_json()["plan"]["errors"][0])
                if sheet == "levels":
                    self.assertNotIn(created_code, {level.level_code.upper() for level in
                                                    org.list_levels(self.PROJECT, include_inactive=True)})
                elif sheet == "cadres":
                    self.assertNotIn(created_code, {cadre.cadre_code for cadre in
                                                    org.list_cadres(self.PROJECT, include_inactive=True)})
                elif sheet == "level_cadres":
                    self.assertEqual(org.list_level_cadres(self.PROJECT), original_level_cadres)
                elif sheet == "workers":
                    self.assertNotIn(created_code, {worker["worker_code"] for worker in
                                                    org.list_workers(self.PROJECT, include_inactive=True)})

    def test_new_rows_honor_explicit_false_and_blank_preserves_it(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        org.seed_default_organization(self.PROJECT)
        levels = {level.level_code: level for level in org.list_levels(self.PROJECT)}
        district = org.create_unit(
            self.PROJECT, org_level_id=levels["district"].org_level_id,
            unit_code="D90", unit_name="District 90",
        )
        org.create_unit(
            self.PROJECT, org_level_id=levels["chc"].org_level_id,
            unit_code="C90", unit_name="CHC 90", parent_org_unit_id=district.org_unit_id,
        )
        db.session.commit()
        uploads = (
            ("levels", "level_code,level_name,depth,is_active\nnewlevel,New Level,7,false\n"),
            ("cadres", "cadre_code,cadre_name,is_active\nLT,Lab Technician,false\n"),
            ("workers", "worker_code,worker_name,unit_code,cadre_code,is_active\n"
             "W90,Worker 90,C90,MO,false\n"),
        )
        for sheet, content in uploads:
            with self.subTest(sheet=sheet):
                preview = self._import_csv(headers, sheet, content, dry_run=True)
                self.assertEqual(preview.status_code, 200, preview.get_json())
                applied = self._import_csv(headers, sheet, content, dry_run=False)
                self.assertEqual(applied.status_code, 200, applied.get_json())
        level = next(level for level in org.list_levels(self.PROJECT, include_inactive=True)
                     if level.level_code == "newlevel")
        cadre = next(cadre for cadre in org.list_cadres(self.PROJECT, include_inactive=True)
                     if cadre.cadre_code == "LT")
        worker = next(worker for worker in org.list_workers(self.PROJECT, include_inactive=True)
                      if worker["worker_code"] == "W90")
        self.assertFalse(level.is_active)
        self.assertFalse(cadre.is_active)
        self.assertFalse(worker["is_active"])
        for sheet, content in (
            ("levels", "level_code,level_name,depth,is_active\nnewlevel,New Level,7,\n"),
            ("cadres", "cadre_code,cadre_name,is_active\nLT,Lab Technician,\n"),
            ("workers", "worker_code,worker_name,unit_code,cadre_code,is_active\n"
             "W90,Worker 90,C90,MO,\n"),
        ):
            response = self._import_csv(headers, sheet, content, dry_run=False)
            self.assertEqual(response.status_code, 200, response.get_json())
        db.session.expire_all()
        self.assertFalse(level.is_active)
        self.assertFalse(cadre.is_active)
        self.assertFalse(next(worker for worker in org.list_workers(self.PROJECT, include_inactive=True)
                              if worker["worker_code"] == "W90")["is_active"])

    def test_worker_code_is_optional(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        org.seed_default_organization(self.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        district = org.create_unit(self.PROJECT, org_level_id=levels["district"].org_level_id, unit_code="D01", unit_name="District One")
        chc = org.create_unit(self.PROJECT, org_level_id=levels["chc"].org_level_id, parent_org_unit_id=district.org_unit_id, unit_code="C01", unit_name="CHC One")
        mo = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}["MO"]
        db.session.commit()

        created = self.client.post(
            self._url("/workers"),
            json={"org_unit_id": str(chc.org_unit_id), "cadre_id": str(mo.cadre_id), "worker_name": "Dr Kaur"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        self.assertEqual(created.get_json()["worker"]["worker_code"], "W00001")

        # Code-less rows match by unit and name: Dr Kaur is updated, Dr Rao is new,
        # and re-uploading the same file creates nothing more.
        rows = "worker_name,unit_code,cadre_code,phone\ndr kaur,C01,MO,111\nDr Rao,C01,MO,\n"
        for _ in range(2):
            self.assertEqual(self._import_csv(headers, "workers", rows, dry_run=False).status_code, 200)
        workers = {w["worker_code"]: w for w in org.list_workers(self.PROJECT, include_inactive=True)}
        self.assertEqual(set(workers), {"W00001", "W00002"})
        self.assertEqual(workers["W00001"]["phone"], "111")
        self.assertEqual(workers["W00002"]["worker_name"], "Dr Rao")

    # -- project structure mode (docs/policy/organization-model.md) ----------

    def test_writes_refused_for_sites_project_reads_allowed(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        base = f"/admin/api/organization/{self.SITES_PROJECT}"

        self.assertEqual(self.client.get(base).status_code, 200)
        self.assertEqual(self.client.get(f"{base}/levels").status_code, 200)

        refused = [
            self.client.post(f"{base}/seed-template", json={}, headers=headers),
            self.client.post(
                f"{base}/levels",
                json={"level_code": "district", "level_name": "District", "depth": 1},
                headers=headers,
            ),
            self.client.post(f"{base}/cadres", json={"cadre_code": "MO", "cadre_name": "MO"}, headers=headers),
            self.client.put(f"{base}/level-cadres", json={}, headers=headers),
            self.client.post(
                f"{base}/import",
                data={"file": (io.BytesIO(b"x"), "org.xlsx"), "dry_run": "1"},
                content_type="multipart/form-data",
                headers=headers,
            ),
        ]
        for response in refused:
            self.assertEqual(response.status_code, 409, response.get_json())
            self.assertIn("Organization", response.get_json()["error"])
        self.assertEqual(org.list_levels(self.SITES_PROJECT, include_inactive=True), [])
        self.assertEqual(org.list_cadres(self.SITES_PROJECT, include_inactive=True), [])

    def test_create_project_accepts_and_rejects_structure_mode(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        payload = {"project_name": "Mode", "project_nickname": "Mode"}

        default = self.client.post("/admin/api/projects", json={**payload, "project_id": "MODE01"}, headers=headers)
        self.assertEqual(default.status_code, 201, default.get_json())
        self.assertEqual(default.get_json()["project"]["project_structure_mode"], "sites")

        explicit = self.client.post(
            "/admin/api/projects",
            json={**payload, "project_id": "MODE02", "project_structure_mode": "organization"},
            headers=headers,
        )
        self.assertEqual(explicit.status_code, 201, explicit.get_json())
        self.assertEqual(explicit.get_json()["project"]["project_structure_mode"], "organization")

        bogus = self.client.post(
            "/admin/api/projects",
            json={**payload, "project_id": "MODE03", "project_structure_mode": "tree"},
            headers=headers,
        )
        self.assertEqual(bogus.status_code, 400)
        self.assertIsNone(db.session.get(VaProjectMaster, "MODE03"))

        bad_update = self.client.put(
            "/admin/api/projects/MODE01", json={"project_structure_mode": ["sites"]}, headers=headers
        )
        self.assertEqual(bad_update.status_code, 400)

    def test_switch_back_to_sites_refused_while_units_active(self):
        self._login(str(self.base_admin_id))
        headers = self._csrf_headers()
        url = f"/admin/api/projects/{self.SITES_PROJECT}"

        to_org = self.client.put(url, json={"project_structure_mode": "organization"}, headers=headers)
        self.assertEqual(to_org.status_code, 200, to_org.get_json())
        self.assertEqual(to_org.get_json()["project"]["project_structure_mode"], "organization")

        org.seed_default_organization(self.SITES_PROJECT, include_cadres=False)
        level = org.list_levels(self.SITES_PROJECT)[0]
        unit = org.create_unit(self.SITES_PROJECT, org_level_id=level.org_level_id, unit_code="D01", unit_name="District One")
        db.session.commit()

        refused = self.client.put(url, json={"project_structure_mode": "sites"}, headers=headers)
        self.assertEqual(refused.status_code, 409)
        self.assertIn("active organization units", refused.get_json()["error"])
        db.session.expire_all()
        self.assertEqual(db.session.get(VaProjectMaster, self.SITES_PROJECT).project_structure_mode, "organization")
        self.assertIsNotNone(org.find_unit_by_code(self.SITES_PROJECT, "D01"))

        org.set_unit_active(self.SITES_PROJECT, unit.org_unit_id, False)
        db.session.commit()
        allowed = self.client.put(url, json={"project_structure_mode": "sites"}, headers=headers)
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        self.assertEqual(allowed.get_json()["project"]["project_structure_mode"], "sites")
