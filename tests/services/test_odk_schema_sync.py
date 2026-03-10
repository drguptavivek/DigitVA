"""
Tests for ODK schema sync service (Phase 5 TDD).

The sync service uses va_odk_clientsetup() to get a pyODK Client and
calls client.get() to fetch field/choice data from ODK Central.

We mock va_odk_clientsetup to avoid real ODK connections.

Run (inside Docker):
  docker compose exec minerva_app_service uv run pytest tests/services/test_odk_schema_sync.py -v
"""
import uuid
from unittest.mock import Mock
import json

from app import db
from app.models import MasFormTypes, MasChoiceMappings
from tests.base import BaseTestCase


def _mock_odk_response(data, status_code=200):
    """Create a mock HTTP response object like pyODK returns."""
    mock_resp = Mock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = data
    mock_resp.content = json.dumps(data).encode()
    return mock_resp


class TestOdkSchemaSyncService(BaseTestCase):
    """
    All ODK schema sync tests in one class to avoid SQLAlchemy metadata
    conflicts when running multiple test classes in the same session.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.form_type = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code="WHO_2022_VA",
            form_type_name="WHO 2022 VA",
            is_active=True,
        )
        db.session.add(cls.form_type)
        db.session.commit()

    def test_01_sync_unknown_form_type_returns_error(self):
        """Sync with unknown form_type_code returns error in stats."""
        from app.services.odk_schema_sync_service import OdkSchemaSyncService
        svc = OdkSchemaSyncService()
        stats = svc.sync_form_choices("UNKNOWN_FORM", 1, "test_form")
        self.assertIn("errors", stats)
        self.assertTrue(len(stats["errors"]) > 0)
        self.assertIn("not found", stats["errors"][0].lower())

    def test_02_sync_returns_stats_dict(self):
        """sync_form_choices returns dict with required stat keys."""
        from unittest.mock import patch
        from app.services.odk_schema_sync_service import OdkSchemaSyncService

        with patch("app.services.odk_schema_sync_service.va_odk_clientsetup") as mock_setup:
            mock_client = Mock()
            mock_client.get.return_value = _mock_odk_response([])
            mock_setup.return_value = mock_client

            svc = OdkSchemaSyncService()
            stats = svc.sync_form_choices("WHO_2022_VA", 1, "test_form")

        for key in ("fields_processed", "choices_added", "choices_updated", "errors"):
            self.assertIn(key, stats, f"Missing key: {key}")
        self.assertNotIn("choices_deactivated", stats)

    def test_03_sync_adds_new_choices(self):
        """Sync adds choices from ODK fields endpoint."""
        from unittest.mock import patch
        from app.services.odk_schema_sync_service import OdkSchemaSyncService

        with patch("app.services.odk_schema_sync_service.va_odk_clientsetup") as mock_setup:
            mock_client = Mock()
            mock_client.get.return_value = _mock_odk_response([
                {
                    "name": "TestField",
                    "type": "select_one testlist",
                    "choices": [
                        {"name": "choice1", "label": {"default": "Choice One"}},
                        {"name": "choice2", "label": {"default": "Choice Two"}},
                    ],
                }
            ])
            mock_setup.return_value = mock_client

            svc = OdkSchemaSyncService()
            stats = svc.sync_form_choices("WHO_2022_VA", 1, "test_form")

        self.assertEqual(stats["choices_added"], 2, stats)
        self.assertEqual(stats["errors"], [])

        choices = db.session.scalars(
            db.select(MasChoiceMappings).where(
                MasChoiceMappings.form_type_id == self.form_type.form_type_id,
                MasChoiceMappings.field_id == "TestField",
            )
        ).all()
        self.assertEqual(len(choices), 2)

    def test_04_sync_updates_changed_label(self):
        """Sync updates choice_label when ODK returns a different label."""
        from unittest.mock import patch
        from app.services.odk_schema_sync_service import OdkSchemaSyncService

        existing = MasChoiceMappings(
            form_type_id=self.form_type.form_type_id,
            field_id="UpdField",
            choice_value="upd_choice",
            choice_label="Old Label",
            display_order=1,
            is_active=True,
        )
        db.session.add(existing)
        db.session.flush()

        with patch("app.services.odk_schema_sync_service.va_odk_clientsetup") as mock_setup:
            mock_client = Mock()
            mock_client.get.return_value = _mock_odk_response([
                {
                    "name": "UpdField",
                    "type": "select_one updlist",
                    "choices": [
                        {"name": "upd_choice", "label": {"default": "New Label"}},
                    ],
                }
            ])
            mock_setup.return_value = mock_client

            svc = OdkSchemaSyncService()
            stats = svc.sync_form_choices("WHO_2022_VA", 1, "test_form")

        self.assertEqual(stats["choices_updated"], 1, stats)
        db.session.refresh(existing)
        self.assertEqual(existing.choice_label, "New Label")

    def test_05_sync_never_deactivates_choices(self):
        """Sync does not deactivate choices absent from ODK (additive only).

        Choices seeded from the WHO VA template cover all sites; a
        site-specific ODK form only has a subset.  Deactivating against
        one form would incorrectly remove other sites' choices.
        """
        from unittest.mock import patch
        from app.services.odk_schema_sync_service import OdkSchemaSyncService

        old_choice = MasChoiceMappings(
            form_type_id=self.form_type.form_type_id,
            field_id="DeactField",
            choice_value="old_choice",
            choice_label="Old Choice",
            display_order=1,
            is_active=True,
        )
        db.session.add(old_choice)
        db.session.flush()

        with patch("app.services.odk_schema_sync_service.va_odk_clientsetup") as mock_setup:
            mock_client = Mock()
            mock_client.get.return_value = _mock_odk_response([
                {
                    "name": "DeactField",
                    "type": "select_one deactlist",
                    "choices": [
                        {"name": "new_choice", "label": {"default": "New Choice"}},
                    ],
                }
            ])
            mock_setup.return_value = mock_client

            svc = OdkSchemaSyncService()
            stats = svc.sync_form_choices("WHO_2022_VA", 1, "test_form")

        # choice was NOT deactivated — sync is additive only
        db.session.refresh(old_choice)
        self.assertTrue(old_choice.is_active)
        self.assertNotIn("choices_deactivated", stats)

    def test_06_sync_unchanged_choice_not_counted(self):
        """Sync does not count a choice as updated if label is unchanged."""
        from unittest.mock import patch
        from app.services.odk_schema_sync_service import OdkSchemaSyncService

        existing = MasChoiceMappings(
            form_type_id=self.form_type.form_type_id,
            field_id="SameField",
            choice_value="same_val",
            choice_label="Same Label",
            display_order=1,
            is_active=True,
        )
        db.session.add(existing)
        db.session.flush()

        with patch("app.services.odk_schema_sync_service.va_odk_clientsetup") as mock_setup:
            mock_client = Mock()
            mock_client.get.return_value = _mock_odk_response([
                {
                    "name": "SameField",
                    "type": "select_one samelist",
                    "choices": [
                        {"name": "same_val", "label": {"default": "Same Label"}},
                    ],
                }
            ])
            mock_setup.return_value = mock_client

            svc = OdkSchemaSyncService()
            stats = svc.sync_form_choices("WHO_2022_VA", 1, "test_form")

        self.assertEqual(stats["choices_updated"], 0, stats)
        self.assertEqual(stats["choices_added"], 0, stats)

    def test_07_non_select_fields_do_not_add_choices(self):
        """Non-select fields never produce choice records."""
        from unittest.mock import patch
        from app.services.odk_schema_sync_service import OdkSchemaSyncService

        with patch("app.services.odk_schema_sync_service.va_odk_clientsetup") as mock_setup:
            mock_client = Mock()
            mock_client.get.return_value = _mock_odk_response([
                {"name": "TextField", "type": "text"},
                {"name": "IntField", "type": "integer"},
            ])
            mock_setup.return_value = mock_client

            svc = OdkSchemaSyncService()
            stats = svc.sync_form_choices("WHO_2022_VA", 1, "test_form")

        # Fields not in MasFieldDisplayConfig → fields_processed = 0
        self.assertEqual(stats["fields_processed"], 0)
        self.assertEqual(stats["choices_added"], 0)

    def test_08_fields_processed_counts_db_matched_fields(self):
        """fields_processed counts all ODK fields that exist in MasFieldDisplayConfig."""
        from unittest.mock import patch
        from app.services.odk_schema_sync_service import OdkSchemaSyncService

        with patch("app.services.odk_schema_sync_service.va_odk_clientsetup") as mock_setup:
            mock_client = Mock()
            # These field names don't exist in MasFieldDisplayConfig in the test DB,
            # so fields_processed stays 0 regardless of type.
            mock_client.get.return_value = _mock_odk_response([
                {
                    "name": "Sel1",
                    "type": "select_one list1",
                    "choices": [{"name": "a", "label": {"default": "A"}}],
                },
                {
                    "name": "Sel2",
                    "type": "select_multiple list2",
                    "choices": [{"name": "x", "label": {"default": "X"}}],
                },
                {"name": "TextF", "type": "text"},
            ])
            mock_setup.return_value = mock_client

            svc = OdkSchemaSyncService()
            stats = svc.sync_form_choices("WHO_2022_VA", 1, "test_form")

        # None of Sel1/Sel2/TextF exist in the test MasFieldDisplayConfig
        self.assertEqual(stats["fields_processed"], 0)
        # Choices are still upserted even without a DB field_config match
        self.assertEqual(stats["choices_added"], 2)

    def test_09_detect_changes_unknown_form_type(self):
        """detect_schema_changes returns error for unknown form type."""
        from app.services.odk_schema_sync_service import OdkSchemaSyncService
        svc = OdkSchemaSyncService()
        result = svc.detect_schema_changes("UNKNOWN_FORM", 1, "test")
        self.assertIn("error", result)

    def test_10_detect_changes_identifies_new_choices(self):
        """detect_schema_changes finds choices in ODK but not in DB."""
        from unittest.mock import patch
        from app.services.odk_schema_sync_service import OdkSchemaSyncService

        with patch("app.services.odk_schema_sync_service.va_odk_clientsetup") as mock_setup:
            mock_client = Mock()
            mock_client.get.return_value = _mock_odk_response([
                {
                    "name": "NewDetField",
                    "type": "select_one newlist",
                    "choices": [
                        {"name": "brand_new", "label": {"default": "Brand New"}},
                    ],
                }
            ])
            mock_setup.return_value = mock_client

            svc = OdkSchemaSyncService()
            result = svc.detect_schema_changes("WHO_2022_VA", 1, "test_form")

        self.assertIn("new_choices", result)
        self.assertTrue(any(
            fc[0] == "NewDetField" and fc[1] == "brand_new"
            for fc in result["new_choices"]
        ))
