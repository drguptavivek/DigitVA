"""The end-of-day upstream-changed KPI counts ODK changes only (digitva-jcll)."""

from datetime import date, datetime, timezone

from app import db
from app.models import VaForms, VaStatuses
from app.tasks.kpi_tasks import _count_upstream_changed_eod
from tests.base import BaseTestCase
from tests.revision_request_fixtures import seed_revision_cases


class UpstreamChangedEodTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}23"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        cls._ensure_base_research_project_and_site()
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="KPI_EOD_FORM",
                odk_project_id="74",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.flush()
        cls.sids = seed_revision_cases(cls.FORM_ID, cls.base_coder_user.user_id, now, prefix="kpieod")
        db.session.commit()

    def test_sent_back_and_reopened_cases_are_not_counted(self):
        count = _count_upstream_changed_eod(db, self.BASE_SITE_ID, date.today())

        # Present first: the ODK-changed cases (odk, legacy, odk_after) are counted ...
        self.assertGreaterEqual(count, 3)
        # ... and only they are: sent_back and reopened share the state but add nothing.
        self.assertEqual(count, 3)
