"""The DM grid's text search matches % and _ literally (digitva-iv7)."""
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import VaForms, VaStatuses, VaSubmissions
from app.services.data_management_service import _dm_search_condition
from tests.base import BaseTestCase


class DmSearchWildcardTests(BaseTestCase):
    FORM_ID = "DMSRCHFORM01"
    SIDS = ("dmsrch-1", "dmsrch-2", "dmsrch-3", "dmsrch-4")
    MASKED = ("QZ_9K", "QZX9K", "QZ%7K", "QZY7K")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_base_research_project_and_site()
        now = datetime.now(UTC)
        db.session.add(VaForms(
            form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID, site_id=cls.BASE_SITE_ID,
            odk_form_id="DM_SEARCH_FORM", odk_project_id="1", form_type="WHO_2022_VA",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        for sid, masked in zip(cls.SIDS, cls.MASKED):
            db.session.add(VaSubmissions(
                va_sid=sid, va_form_id=cls.FORM_ID, va_submission_date=now,
                va_odk_updatedat=now, va_data_collector=f"collector {masked}",
                va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=masked,
                va_consent="yes", va_narration_language="English",
                va_deceased_age=42, va_deceased_gender="male",
                va_summary=[], va_catcount={}, va_category_list=[],
            ))
        db.session.commit()

    def _matches(self, search, *, redact):
        return set(db.session.scalars(
            sa.select(VaSubmissions.va_sid).where(
                VaSubmissions.va_sid.in_(self.SIDS),
                _dm_search_condition(search, redact_staff_identity=redact),
            )
        ))

    def test_wildcards_match_literally(self):
        for redact in (False, True):
            with self.subTest(redact=redact):
                self.assertEqual(self._matches("Z_9", redact=redact), {"dmsrch-1"})
                self.assertEqual(self._matches("Z%7", redact=redact), {"dmsrch-3"})
                self.assertEqual(self._matches("qz", redact=redact), set(self.SIDS))
