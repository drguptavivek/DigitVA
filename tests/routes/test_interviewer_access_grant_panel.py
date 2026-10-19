"""The Access Grants panel can create and filter interviewer grants."""

import re
from datetime import UTC, datetime

from app import db
from app.models import VaProjectMaster, VaStatuses
from app.services import organization_service as org
from tests.base import BaseTestCase


class InterviewerAccessGrantPanelTests(BaseTestCase):
    def test_interviewer_is_available_for_granting_and_filtering(self):
        self._login(str(self.base_admin_id))
        response = self.client.get("/admin/panels/access-grants")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        for select_id in ("ag-role", "ag-filter-role"):
            with self.subTest(select_id=select_id):
                select = re.search(
                    rf'<select id="{select_id}".*?</select>', html, re.DOTALL
                )
                self.assertIsNotNone(select, select_id)
                self.assertRegex(
                    select.group(0),
                    re.compile(
                        r'<option value="interviewer">Interviewer</option>'
                    ),
                )


class InterviewerUnitGrantApiTests(BaseTestCase):
    PROJECT = "IVR001"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            now = datetime.now(UTC)
            db.session.add(
                VaProjectMaster(
                    project_id=cls.PROJECT,
                    project_code=cls.PROJECT,
                    project_name="Interviewer Grant Project",
                    project_nickname="InterviewerGrant",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
        db.session.commit()

    def _chc_and_cadres(self):
        org.seed_default_organization(self.PROJECT)
        levels = {level.level_code: level for level in org.list_levels(self.PROJECT)}
        district = org.create_unit(
            self.PROJECT,
            org_level_id=levels["district"].org_level_id,
            unit_code="D01",
            unit_name="District One",
        )
        chc = org.create_unit(
            self.PROJECT,
            org_level_id=levels["chc"].org_level_id,
            parent_org_unit_id=district.org_unit_id,
            unit_code="C01",
            unit_name="CHC One",
        )
        db.session.commit()
        cadres = {cadre.cadre_code: cadre for cadre in org.list_cadres(self.PROJECT)}
        return chc, cadres

    def _post_grant(self, *, unit, cadre):
        body = {
            "user_id": str(self.base_coder_user.user_id),
            "role": "interviewer",
            "scope_type": "org_unit",
            "org_unit_id": str(unit.org_unit_id),
        }
        if cadre:
            body["cadre_id"] = str(cadre.cadre_id)
        return self.client.post(
            "/admin/api/access-grants", json=body, headers=self._csrf_headers()
        )

    def test_admin_can_create_unit_interviewer_grant_with_eligible_cadre(self):
        chc, cadres = self._chc_and_cadres()
        self._login(str(self.base_admin_id))

        response = self._post_grant(unit=chc, cadre=cadres["SMO"])

        self.assertEqual(response.status_code, 201, response.get_json())
        grant = response.get_json()["grant"]
        self.assertEqual(grant["role"], "interviewer")
        self.assertEqual(grant["scope_type"], "org_unit")
        self.assertEqual(grant["unit_code"], "C01")
        self.assertEqual(grant["cadre_code"], "SMO")

    def test_admin_cannot_create_unit_interviewer_grant_with_ineligible_cadre(self):
        chc, cadres = self._chc_and_cadres()
        self._login(str(self.base_admin_id))

        response = self._post_grant(unit=chc, cadre=cadres["ASHA"])

        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn("not defined at level", response.get_json()["error"])
