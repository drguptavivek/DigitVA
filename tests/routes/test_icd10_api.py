from app import db
import sqlalchemy as sa

from app.models import MasIcd1020192
from tests.base import BaseTestCase


class TestIcd10Api(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.session.execute(
            sa.delete(MasIcd1020192).where(MasIcd1020192.code.in_(("ZZ10", "ZX20", "ZA11", "ZM30")))
        )
        db.session.add_all(
            [
                MasIcd1020192(
                    code="ZZ10",
                    title="Alpha toxic syndrome",
                    node_type="category",
                    semantic_level="three_character",
                    sort_order=1,
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code=True,
                    is_detailed_code=False,
                    source_version="2019-test",
                    source_path="tests",
                    is_active=True,
                ),
                MasIcd1020192(
                    code="ZX20",
                    title="Contact with venomous reptiles",
                    node_type="category",
                    semantic_level="detailed_code",
                    sort_order=2,
                    parent_code="ZX2",
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code=False,
                    is_detailed_code=True,
                    source_version="2019-test",
                    source_path="tests",
                    is_active=True,
                ),
                MasIcd1020192(
                    code="ZA11",
                    title="Chronic kidney failure",
                    node_type="category",
                    semantic_level="detailed_code",
                    sort_order=3,
                    parent_code="ZA1",
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code=False,
                    is_detailed_code=True,
                    source_version="2019-test",
                    source_path="tests",
                    is_active=True,
                ),
                MasIcd1020192(
                    code="ZM30",
                    title="Motorised vehicle crash involving wild animals",
                    node_type="category",
                    semantic_level="detailed_code",
                    sort_order=4,
                    parent_code="ZM3",
                    has_children=False,
                    is_leaf=True,
                    is_three_character_code=False,
                    is_detailed_code=True,
                    source_version="2019-test",
                    source_path="tests",
                    is_active=True,
                ),
            ]
        )
        db.session.commit()

    def test_search_rejects_too_short_query(self):
        self._login(self.base_admin_id)
        response = self.client.get("/api/v1/icd10/search?q=z")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_search_matches_icd_code_prefix(self):
        self._login(self.base_admin_id)
        response = self.client.get("/api/v1/icd10/search?q=zx2")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(any(item["icd_code"] == "ZX20" for item in payload))

    def test_search_matches_display_text_case_insensitive(self):
        self._login(self.base_admin_id)
        response = self.client.get("/api/v1/icd10/search?q=kidney")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(any(item["icd_code"] == "ZA11" for item in payload))

    def test_search_matches_multi_word_terms_across_text(self):
        self._login(self.base_admin_id)
        response = self.client.get("/api/v1/icd10/search?q=motor animal")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(any(item["icd_code"] == "ZM30" for item in payload))
