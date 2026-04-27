import io
import json
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MasIcd1020192,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
)
from tests.base import BaseTestCase


class TestIcd10BrowserApi(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data_manager_user = cls._get_or_make_user(
            "icd.dm@test.local",
            "IcdDm1234!",
        )
        project_site = db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == cls.BASE_PROJECT_ID,
                VaProjectSites.site_id == cls.BASE_SITE_ID,
            )
        )
        grant = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == cls.data_manager_user.user_id,
                VaUserAccessGrants.role == VaAccessRoles.data_manager,
            )
        )
        if grant is None:
            db.session.add(
                VaUserAccessGrants(
                    user_id=cls.data_manager_user.user_id,
                    role=VaAccessRoles.data_manager,
                    scope_type=VaAccessScopeTypes.project_site,
                    project_site_id=project_site.project_site_id,
                    grant_status=VaStatuses.active,
                )
            )
            db.session.commit()

    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MasIcd1020192))
        db.session.flush()

        now = datetime.now(UTC)
        db.session.add_all(
            [
                MasIcd1020192(
                    code="I",
                    title="Certain infectious and parasitic diseases",
                    node_type="chapter",
                    semantic_level="chapter",
                    sort_order=1,
                    chapter_code="I",
                    chapter_title="Certain infectious and parasitic diseases",
                    has_children=True,
                    is_leaf=False,
                    is_three_character_code=False,
                    is_detailed_code=False,
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
                MasIcd1020192(
                    code="A00-A09",
                    title="Intestinal infectious diseases",
                    node_type="block",
                    semantic_level="block",
                    sort_order=2,
                    parent_code="I",
                    chapter_code="I",
                    chapter_title="Certain infectious and parasitic diseases",
                    block_code="A00-A09",
                    block_title="Intestinal infectious diseases",
                    has_children=True,
                    is_leaf=False,
                    is_three_character_code=False,
                    is_detailed_code=False,
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
                MasIcd1020192(
                    code="A00",
                    title="Cholera",
                    node_type="category",
                    semantic_level="three_character",
                    sort_order=3,
                    parent_code="A00-A09",
                    chapter_code="I",
                    chapter_title="Certain infectious and parasitic diseases",
                    block_code="A00-A09",
                    block_title="Intestinal infectious diseases",
                    three_character_code="A00",
                    three_character_title="Cholera",
                    has_children=True,
                    is_leaf=False,
                    is_three_character_code=True,
                    is_detailed_code=False,
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
                MasIcd1020192(
                    code="A00.0",
                    title="Cholera due to Vibrio cholerae 01, biovar cholerae",
                    node_type="category",
                    semantic_level="detailed_code",
                    sort_order=4,
                    parent_code="A00",
                    chapter_code="I",
                    chapter_title="Certain infectious and parasitic diseases",
                    block_code="A00-A09",
                    block_title="Intestinal infectious diseases",
                    three_character_code="A00",
                    three_character_title="Cholera",
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code=False,
                    is_detailed_code=True,
                    policy_status="unreviewed",
                    source_version="ICD-10-2019",
                    source_path="test",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        db.session.commit()

    def test_data_manager_can_browse_root_children(self):
        self._login(str(self.data_manager_user.user_id))

        response = self.client.get("/api/v1/icd10/2019-2/children")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsNone(payload["parent_code"])
        self.assertEqual(len(payload["children"]), 1)
        self.assertEqual(payload["children"][0]["code"], "I")
        self.assertEqual(payload["children"][0]["child_count"], 1)

    def test_data_manager_can_browse_nested_children(self):
        self._login(str(self.data_manager_user.user_id))

        response = self.client.get("/api/v1/icd10/2019-2/children?parent_code=A00-A09")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["parent_code"], "A00-A09")
        self.assertEqual([row["code"] for row in payload["children"]], ["A00"])
        self.assertEqual(payload["children"][0]["status_indicator"], "red")

    def test_data_manager_can_browse_blocks_with_status_indicator(self):
        self._login(str(self.data_manager_user.user_id))

        response = self.client.get("/api/v1/icd10/2019-2/children?parent_code=I")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["code"] for row in payload["children"]], ["A00-A09"])
        self.assertEqual(payload["children"][0]["status_indicator"], "red")

    def test_filter_updates_block_counts(self):
        self._login(str(self.data_manager_user.user_id))

        response = self.client.get(
            "/api/v1/icd10/2019-2/children?parent_code=I&coding_filter=active"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([row["code"] for row in payload["children"]], ["A00-A09"])
        self.assertEqual(payload["children"][0]["child_count"], 0)

    def test_node_details_include_ancestors(self):
        self._login(str(self.data_manager_user.user_id))

        response = self.client.get("/api/v1/icd10/2019-2/node/A00.0")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["code"], "A00.0")
        self.assertEqual(
            [row["code"] for row in payload["ancestors"]],
            ["I", "A00-A09", "A00"],
        )

    def test_policy_options_exposed_for_browser(self):
        self._login(str(self.data_manager_user.user_id))

        response = self.client.get("/api/v1/icd10/2019-2/policy-options")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["sex_selectable"], ["both", "female", "male"])
        self.assertEqual(
            payload["age_group_selectable"],
            ["all", "neonate", "infant", "child", "adult"],
        )

    def test_data_manager_can_export_curated_policy_json(self):
        self._login(str(self.data_manager_user.user_id))

        detailed = db.session.get(MasIcd1020192, "A00.0")
        detailed.is_coding_selectable = True
        detailed.sex_selectable = "both"
        detailed.age_group_selectable = "adult"
        db.session.commit()

        response = self.client.get("/api/v1/icd10/2019-2/policy-export")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        payload = response.get_json()
        self.assertEqual(payload["row_count"], 1)
        self.assertEqual(payload["items"][0]["code"], "A00.0")
        self.assertEqual(payload["items"][0]["age_group_selectable"], "adult")

    def test_admin_can_import_policy_json(self):
        self._login(str(self.base_admin_user.user_id))

        payload = {
            "items": [
                {
                    "code": "A00.0",
                    "is_coding_selectable": True,
                    "sex_selectable": "female",
                    "age_group_selectable": "adult",
                }
            ]
        }

        response = self.client.post(
            "/api/v1/icd10/2019-2/policy-import",
            data={"file": (io.BytesIO(json.dumps(payload).encode("utf-8")), "policy.json")},
            headers=self._csrf_headers(),
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["total_items"], 1)
        self.assertEqual(body["updated_items"], 1)
        self.assertEqual(body["failed_codes"], [])

        refreshed = db.session.get(MasIcd1020192, "A00.0")
        self.assertTrue(refreshed.is_coding_selectable)
        self.assertEqual(refreshed.sex_selectable, "female")

    def test_non_admin_cannot_import_policy_json(self):
        self._login(str(self.data_manager_user.user_id))

        payload = {
            "items": [
                {
                    "code": "A00",
                    "is_coding_selectable": True,
                    "sex_selectable": "both",
                    "age_group_selectable": "all",
                }
            ]
        }

        response = self.client.post(
            "/api/v1/icd10/2019-2/policy-import",
            data={"file": (io.BytesIO(json.dumps(payload).encode("utf-8")), "policy.json")},
            headers=self._csrf_headers(),
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_can_update_policy_fields(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.patch(
            "/api/v1/icd10/2019-2/node/A00/policy",
            json={
                "is_coding_selectable": True,
                "sex_selectable": "both",
                "age_group_selectable": "adult",
                "restriction_note": "default adult code",
            },
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertTrue(payload["is_coding_selectable"])
        self.assertEqual(payload["sex_selectable"], "both")

        refreshed = db.session.get(MasIcd1020192, "A00")
        self.assertTrue(refreshed.is_coding_selectable)
        self.assertEqual(refreshed.restriction_note, "default adult code")

    def test_non_admin_cannot_update_policy_fields(self):
        non_admin_user = self._make_user("icd.nonadmin@test.local", "IcdNonAdmin1234!")
        db.session.commit()
        self._login(str(non_admin_user.user_id))

        response = self.client.patch(
            "/api/v1/icd10/2019-2/node/A00/policy",
            json={
                "is_coding_selectable": True,
                "sex_selectable": "both",
                "age_group_selectable": "adult",
                "restriction_note": "",
            },
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 403)

    def test_invalid_policy_value_returns_400(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.patch(
            "/api/v1/icd10/2019-2/node/A00/policy",
            json={
                "is_coding_selectable": True,
                "sex_selectable": "invalid",
                "age_group_selectable": "adult",
                "restriction_note": "",
            },
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 400)

    def test_structural_node_policy_update_returns_400(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.patch(
            "/api/v1/icd10/2019-2/node/I/policy",
            json={
                "is_coding_selectable": True,
                "sex_selectable": "both",
                "age_group_selectable": "all",
                "restriction_note": "",
            },
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("three-character and detailed ICD codes", response.get_json()["error"])
