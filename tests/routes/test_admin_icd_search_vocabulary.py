"""Admin panel and JSON API tests for the ICD search vocabulary.

Run (inside Docker):
  docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/minerva_test_pii \
    minerva_app_service uv run --no-sync pytest tests/routes/test_admin_icd_search_vocabulary.py \
    -q -p no:cacheprovider
"""
import uuid

import sqlalchemy as sa

from app import db
from app.models import MasIcd1020192, MasIcdSearchTerms
from app.services.icd_search_vocabulary_service import (
    clear_cache,
    create_term,
    set_active,
)
from tests.base import BaseTestCase

_LIST_URL = "/admin/api/icd-search-vocabulary"
_TERM_URL = "/admin/api/icd-search-vocabulary/term"
_EXPORT_URL = "/admin/api/icd-search-vocabulary/export.csv"
_PANEL_URL = "/admin/panels/icd-search-vocabulary"


class TestAdminIcdSearchVocabulary(BaseTestCase):
    def setUp(self):
        super().setUp()
        clear_cache()
        db.session.execute(sa.delete(MasIcdSearchTerms))
        db.session.execute(sa.delete(MasIcd1020192))
        # One catalogue row so the soft code warning has a positive control:
        # A15 resolves, Z99 does not.
        db.session.add(
            MasIcd1020192(
                code="A15",
                title="Tuberculosis of lung",
                node_type="category",
                semantic_level="three_character",
                source_version="ICD-10-2019",
                is_active=True,
            )
        )
        db.session.flush()
        self.cva = create_term(
            term="CVA",
            icd_classification="icd10",
            icd_code="I64",
            note="clinician shorthand",
        )
        self.inactive = create_term(
            term="old term", icd_classification="icd11", icd_code="AA00"
        )
        set_active(str(self.inactive.term_id), False)

    def tearDown(self):
        clear_cache()
        super().tearDown()

    # ----- authorization -----

    def test_panel_renders_for_admin(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.get(_PANEL_URL)

        self.assertEqual(response.status_code, 200)
        self.assertIn("ICD Search Vocabulary", response.get_data(as_text=True))

    def test_panel_denied_for_coder(self):
        self._login(str(self.base_coder_user.user_id))

        response = self.client.get(_PANEL_URL)

        self.assertEqual(response.status_code, 403)

    def test_apis_denied_for_coder(self):
        self._login(str(self.base_coder_user.user_id))

        self.assertEqual(self.client.get(_LIST_URL).status_code, 403)
        self.assertEqual(self.client.get(_EXPORT_URL).status_code, 403)
        self.assertEqual(
            self.client.post(_LIST_URL, json={"term": "x"}, headers=self._csrf_headers()).status_code,
            403,
        )

    # ----- list -----

    def test_list_returns_rows_and_search_filters(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.get(_LIST_URL)
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["total"], 2)
        self.assertEqual(
            [row["term"] for row in payload["rows"]],
            ["CVA", "old term"],
        )

        searched = self.client.get(_LIST_URL, query_string={"q": "cva"}).get_json()
        self.assertEqual([row["term"] for row in searched["rows"]], ["CVA"])

    # ----- create -----

    def test_create_persists_and_derives_the_lookup_key(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.post(
            _LIST_URL,
            json={"term": "Koch's disease", "icd_classification": "icd10", "icd_code": "a15"},
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["term"]["term_normalized"], "koch s disease")
        self.assertEqual(payload["term"]["icd_code"], "A15")
        self.assertEqual(payload["term"]["sort_order"], 100)
        self.assertIsNone(payload["code_warning"])
        persisted = db.session.scalar(
            sa.select(MasIcdSearchTerms).where(MasIcdSearchTerms.term == "Koch's disease")
        )
        self.assertIsNotNone(persisted)

    def test_create_accepts_and_validates_sort_order(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.post(
            _LIST_URL,
            json={
                "term": "ranked term",
                "icd_classification": "icd10",
                "icd_code": "A15",
                "sort_order": 3,
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["term"]["sort_order"], 3)

        invalid = self.client.post(
            _LIST_URL,
            json={
                "term": "bad sort",
                "icd_classification": "icd10",
                "icd_code": "A15",
                "sort_order": 0,
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(invalid.status_code, 400)

    def test_create_warns_softly_when_the_code_is_absent(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.post(
            _LIST_URL,
            json={"term": "future code", "icd_classification": "icd10", "icd_code": "Z99"},
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsNotNone(payload["code_warning"])
        self.assertIn("Z99", payload["code_warning"])
        persisted = db.session.scalar(
            sa.select(MasIcdSearchTerms).where(MasIcdSearchTerms.term == "future code")
        )
        self.assertIsNotNone(persisted)  # soft warning: the save went through

    def test_create_rejects_invalid_payload(self):
        self._login(str(self.base_admin_user.user_id))

        bad_classification = self.client.post(
            _LIST_URL,
            json={"term": "x", "icd_classification": "icd9", "icd_code": "X00"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(bad_classification.status_code, 400)

        empty_term = self.client.post(
            _LIST_URL,
            json={"term": "  ", "icd_classification": "icd10", "icd_code": "X00"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(empty_term.status_code, 400)

        no_body = self.client.post(_LIST_URL, headers=self._csrf_headers())
        self.assertEqual(no_body.status_code, 400)

    def test_create_requires_csrf_token(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.post(
            _LIST_URL,
            json={"term": "x", "icd_classification": "icd10", "icd_code": "X00"},
        )

        self.assertEqual(response.status_code, 400)

    # ----- update -----

    def test_update_changes_term_and_lookup_key(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.patch(
            f"{_TERM_URL}/{self.cva.term_id}",
            json={
                "term": "brain attack",
                "icd_classification": "icd10",
                "icd_code": "I64",
                "note": "updated note",
            },
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["term"]["term_normalized"], "brain attack")
        self.assertEqual(payload["term"]["note"], "updated note")
        db.session.expire_all()
        refreshed = db.session.get(MasIcdSearchTerms, self.cva.term_id)
        self.assertEqual(refreshed.term_normalized, "brain attack")

    def test_update_changes_sort_order(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.patch(
            f"{_TERM_URL}/{self.cva.term_id}",
            json={
                "term": "CVA",
                "icd_classification": "icd10",
                "icd_code": "I64",
                "sort_order": 7,
            },
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["term"]["sort_order"], 7)

        invalid = self.client.patch(
            f"{_TERM_URL}/{self.cva.term_id}",
            json={
                "term": "CVA",
                "icd_classification": "icd10",
                "icd_code": "I64",
                "sort_order": "not-a-number",
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(invalid.status_code, 400)

    def test_update_unknown_term_returns_404(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.patch(
            f"{_TERM_URL}/{uuid.uuid4()}",
            json={"term": "x", "icd_classification": "icd10", "icd_code": "X00"},
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 404)

    def test_update_rejects_malformed_id(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.patch(
            f"{_TERM_URL}/not-a-uuid",
            json={"term": "x", "icd_classification": "icd10", "icd_code": "X00"},
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 400)

    # ----- set-active -----

    def test_set_active_toggles_without_deleting(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.post(
            f"{_TERM_URL}/{self.cva.term_id}/set-active",
            json={"is_active": False},
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["term"]["is_active"])
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(MasIcdSearchTerms, self.cva.term_id))

        reactivated = self.client.post(
            f"{_TERM_URL}/{self.cva.term_id}/set-active",
            json={"is_active": True},
            headers=self._csrf_headers(),
        )
        self.assertTrue(reactivated.get_json()["term"]["is_active"])

    def test_set_active_requires_boolean(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.post(
            f"{_TERM_URL}/{self.cva.term_id}/set-active",
            json={"is_active": "false"},
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 400)

    # ----- export -----

    def test_export_csv_shape(self):
        self._login(str(self.base_admin_user.user_id))

        response = self.client.get(_EXPORT_URL)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.content_type)
        lines = response.get_data(as_text=True).strip().splitlines()
        self.assertEqual(
            lines[0],
            "term,term_normalized,icd_classification,icd_code,source,note,sort_order,is_active,created_at,updated_at",
        )
        self.assertEqual(len(lines), 3)  # header + 2 seeded links
        self.assertIn("CVA,cva,icd10,I64", lines[1])
        self.assertIn("old term,old term,icd11,AA00,admin,,100,false", lines[2])
