"""Confirmed-duplicate web cases are not counted by any DM KPI endpoint.

digitva-vzk.7; policy: docs/policy/coding-workflow-state-machine.md,
"Confirmed Duplicate Cases". Reuses every per-module test of
tests/routes/test_dm_kpi_retired_submissions.py over a different seed: two
identical in-ODK submissions, one of which is the submission of a web case
confirmed as a duplicate. Any endpoint that still counts it reports 2 where
it should report 1, and every raw-SQL query in app/routes/api/dm_kpi/ runs.
"""

from datetime import date

import sqlalchemy as sa

from app import db
from app.models import VaDeathRegister
from app.services.duplicate_exclusion import not_confirmed_duplicate_sql
from tests.base import BaseTestCase
from tests.routes.test_dm_kpi_retired_submissions import DmKpiRetiredSubmissionTests


class DmKpiConfirmedDuplicateTests(DmKpiRetiredSubmissionTests):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}08"
    LIVE_SID = "uuid:dm-kpi-dup-live"
    RETIRED_SID = "uuid:dm-kpi-dup-confirmed"

    @classmethod
    def _seed_submission(cls, sid, now, sync_issue_code):
        # Both rows stay in ODK; the second is a confirmed duplicate instead.
        super()._seed_submission(sid, now, sync_issue_code=None)
        if sid != cls.RETIRED_SID:
            return
        db.session.add(VaDeathRegister(
            project_id=cls.BASE_PROJECT_ID, site_id=cls.BASE_SITE_ID, death_number=880001,
            unique_id="DMKPI-DUP-1", deceased_name="Asha Devi", deceased_sex="female",
            date_of_death=date.today(), registered_by=cls.base_coder_user.user_id,
            status="duplicate", va_sid=sid,
        ))
        db.session.flush()

    def test_fixture_would_be_double_counted_without_the_predicate(self):
        """Presence first: without the predicate both submissions count."""
        scoped = """
            SELECT COUNT(*) FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = :site_id
        """
        params = {"site_id": self.BASE_SITE_ID}
        self.assertEqual(db.session.scalar(sa.text(scoped), params), 2)
        excluded = sa.text(scoped + " AND " + not_confirmed_duplicate_sql("s.va_sid"))
        self.assertEqual(db.session.scalar(excluded, params), 1)
