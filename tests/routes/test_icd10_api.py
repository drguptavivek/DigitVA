from app import db
from app.models import VaIcdCodes
from tests.base import BaseTestCase


class TestIcd10Api(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.session.add_all(
            [
                VaIcdCodes(
                    disease_id=900001,
                    icd_code="ZZ10",
                    icd_to_display="ZZ10-Alpha toxic syndrome",
                    category="test",
                ),
                VaIcdCodes(
                    disease_id=900002,
                    icd_code="ZX20",
                    icd_to_display="ZX20-Contact with venomous reptiles",
                    category="test",
                ),
                VaIcdCodes(
                    disease_id=900003,
                    icd_code="ZA11",
                    icd_to_display="ZA11-Chronic kidney failure",
                    category="test",
                ),
                VaIcdCodes(
                    disease_id=900004,
                    icd_code="ZM30",
                    icd_to_display="ZM30-Motorised vehicle crash involving wild animals",
                    category="test",
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
