from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import MasIcd11Mms
from tests.base import BaseTestCase


class TestAdminIcd11Browser(BaseTestCase):
    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MasIcd11Mms))
        db.session.flush()

        now = datetime.now(UTC)
        db.session.add_all(
            [
                MasIcd11Mms(
                    release="2026-01",
                    linearization_uri="lin:chapter1",
                    foundation_uri="f:chapter1",
                    code=None,
                    title="Certain infectious or parasitic diseases",
                    class_kind="chapter",
                    depth_in_kind=1,
                    chapter_no="01",
                    is_residual=False,
                    is_leaf=False,
                    sort_order=1,
                    parent_foundation_uri=None,
                    parent_linearization_uri=None,
                    source_version="ICD-11-MMS-2026-01",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
                MasIcd11Mms(
                    release="2026-01",
                    linearization_uri="lin:1A00",
                    foundation_uri="f:1A00",
                    code="1A00",
                    title="Cholera",
                    class_kind="category",
                    depth_in_kind=1,
                    chapter_no="01",
                    is_residual=False,
                    is_leaf=True,
                    sort_order=2,
                    parent_foundation_uri="f:chapter1",
                    parent_linearization_uri="lin:chapter1",
                    is_coding_selectable=True,
                    sex_selectable="both",
                    age_group_selectable="all",
                    source_version="ICD-11-MMS-2026-01",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        db.session.flush()

    def test_admin_panel_renders_for_admin(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.get("/admin/panels/icd11-browser")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("ICD-11 MMS Browser", body)

    def test_admin_panel_denied_for_project_pi(self):
        self._login(str(self.base_project_pi_user.user_id))

        response = self.client.get("/admin/panels/icd11-browser")

        self.assertEqual(response.status_code, 403)

    def test_admin_children_api_returns_root_chapter(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.get("/admin/api/icd11/mms/children")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["children"]), 1)
        self.assertEqual(payload["children"][0]["linearization_uri"], "lin:chapter1")
        self.assertEqual(payload["children"][0]["child_count"], 1)

    def test_admin_children_api_returns_category_under_chapter(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.get(
            "/admin/api/icd11/mms/children",
            query_string={"parent_linearization_uri": "lin:chapter1"},
        )

        self.assertEqual(response.status_code, 200)
        codes = [row["code"] for row in response.get_json()["children"]]
        self.assertEqual(codes, ["1A00"])

    def test_admin_node_api_returns_details_with_ancestors(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.get(
            "/admin/api/icd11/mms/node", query_string={"linearization_uri": "lin:1A00"}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["code"], "1A00")
        self.assertEqual(len(payload["ancestors"]), 1)
        self.assertEqual(payload["ancestors"][0]["linearization_uri"], "lin:chapter1")

    def test_admin_node_api_returns_404_for_unknown_node(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.get(
            "/admin/api/icd11/mms/node", query_string={"linearization_uri": "lin:missing"}
        )

        self.assertEqual(response.status_code, 404)

    def test_admin_search_api_finds_selectable_category(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.get("/admin/api/icd11/mms/search", query_string={"q": "cholera"})

        self.assertEqual(response.status_code, 200)
        results = response.get_json()["results"]
        self.assertTrue(any(row["icd_code"] == "1A00" for row in results))

    def test_admin_api_denied_for_anonymous(self):
        response = self.client.get("/admin/api/icd11/mms/children")

        self.assertIn(response.status_code, (302, 401, 403))
