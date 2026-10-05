"""The ODK-change vs send-back/reopen split in SQL (digitva-jcll).

The Core predicate, the raw-SQL renderer, the effective state, the per-page
lookup and ``get_open_revision_request`` must agree on every case in
``tests/revision_request_fixtures.py``.
"""

from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import VaForms, VaStatuses, VaSubmissionWorkflow, VaSubmissionWorkflowEvent
from app.services.workflow.revision_request_sql import (
    SENT_BACK_FOR_REVISION,
    dm_reopen_event_sql,
    effective_workflow_state_sql,
    odk_changed_sql,
    odk_detected_event_sql,
    open_revision_request_sids,
    revision_request_open_condition,
    revision_request_open_sql,
    sent_back_sql,
    workflow_filter_conditions,
)
from app.services.workflow.upstream_changes import get_open_revision_request
from tests.base import BaseTestCase
from tests.revision_request_fixtures import FUC, seed_revision_cases, seed_stale_fuc_case


class RevisionRequestSqlTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}21"

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
                odk_form_id="REV_SQL_FORM",
                odk_project_id="72",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.flush()
        cls.sids = seed_revision_cases(cls.FORM_ID, cls.base_coder_user.user_id, now, prefix="revsql")
        db.session.commit()
        cls.by_sid = {sid: name for name, sid in cls.sids.items()}

    def _names(self, sids) -> set[str]:
        return {self.by_sid[sid] for sid in sids}

    def _fuc_sids_where(self, condition) -> set[str]:
        return self._names(
            db.session.scalars(
                sa.select(VaSubmissionWorkflow.va_sid).where(
                    VaSubmissionWorkflow.va_sid.in_(list(self.sids.values())),
                    VaSubmissionWorkflow.workflow_state == FUC,
                    condition,
                )
            )
        )

    def _raw(self, where: str) -> set[str]:
        rows = db.session.execute(
            sa.text(f"SELECT w.va_sid FROM va_submission_workflow w WHERE w.va_sid = ANY(:sids) AND {where}"),
            {"sids": list(self.sids.values())},
        ).scalars()
        return self._names(rows)

    def test_core_predicate_splits_fuc_into_odk_and_revision_requests(self):
        sent_back = self._fuc_sids_where(revision_request_open_condition(VaSubmissionWorkflow.va_sid))
        odk = self._fuc_sids_where(sa.not_(revision_request_open_condition(VaSubmissionWorkflow.va_sid)))

        # Subject present before absence: both sides are non-empty.
        self.assertEqual(sent_back, {"sent_back", "reopened"})
        self.assertEqual(odk, {"odk", "legacy", "odk_after"})

    def test_raw_sql_agrees_with_the_core_predicate(self):
        self.assertEqual(self._raw(sent_back_sql("w")), {"sent_back", "reopened"})
        self.assertEqual(self._raw(odk_changed_sql("w")), {"odk", "legacy", "odk_after"})
        self.assertEqual(
            self._raw(f"w.workflow_state = '{FUC}' AND {revision_request_open_sql('w.va_sid')}"),
            {"sent_back", "reopened"},
        )

    def test_effective_state_reads_open_revision_requests_as_sent_back(self):
        rows = db.session.execute(
            sa.text(
                f"SELECT w.va_sid AS sid, {effective_workflow_state_sql('w')} AS state "
                "FROM va_submission_workflow w WHERE w.va_sid = ANY(:sids)"
            ),
            {"sids": list(self.sids.values())},
        ).all()
        states = {self.by_sid[sid]: state for sid, state in rows}

        self.assertEqual(states["sent_back"], SENT_BACK_FOR_REVISION)
        self.assertEqual(states["reopened"], SENT_BACK_FOR_REVISION)
        self.assertEqual(states["odk"], FUC)
        self.assertEqual(states["legacy"], FUC)
        self.assertEqual(states["odk_after"], FUC)  # ODK change after a send-back wins
        self.assertEqual(states["coded"], "coder_finalized")
        self.assertEqual(states["restarted"], "smartva_pending")  # stored state kept, never sent_back

    def test_open_revision_request_sids_matches_get_open_revision_request(self):
        sids = list(self.sids.values())
        page = open_revision_request_sids(sids)

        self.assertEqual(self._names(page), {"sent_back", "reopened"})
        for sid in sids:
            self.assertEqual(sid in page, get_open_revision_request(sid) is not None, self.by_sid[sid])
        self.assertEqual(open_revision_request_sids([]), set())

    def test_workflow_filter_values_split_the_two_kinds(self):
        def pick(value):
            return self._names(
                db.session.scalars(
                    sa.select(VaSubmissionWorkflow.va_sid).where(
                        VaSubmissionWorkflow.va_sid.in_(list(self.sids.values())),
                        *workflow_filter_conditions(value, VaSubmissionWorkflow.workflow_state, VaSubmissionWorkflow.va_sid),
                    )
                )
            )

        self.assertEqual(pick(FUC), {"odk", "legacy", "odk_after"})
        self.assertEqual(pick(SENT_BACK_FOR_REVISION), {"sent_back", "reopened"})
        self.assertEqual(pick("coder_finalized"), {"coded"})

    def test_per_event_predicates_use_the_event_reason(self):
        def events(transition_id, predicate):
            rows = db.session.execute(
                sa.text(
                    "SELECT e.va_sid FROM va_submission_workflow_events e "
                    f"WHERE e.va_sid = ANY(:sids) AND e.transition_id = :t AND {predicate}"
                ),
                {"sids": list(self.sids.values()), "t": transition_id},
            ).scalars()
            return sorted(self.by_sid[sid] for sid in rows)

        self.assertEqual(
            events("upstream_change_detected", odk_detected_event_sql("e")),
            ["dm_reopen", "odk", "odk_after"],
        )
        self.assertEqual(events("upstream_change_accepted", dm_reopen_event_sql("e")), ["dm_reopen"])
        # The revision restart is present, so excluding it above is a real exclusion.
        self.assertEqual(events("upstream_change_accepted", "true"), ["dm_reopen", "restarted"])

    def test_event_count_for_a_case_with_no_events(self):
        count = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSubmissionWorkflowEvent).where(
                VaSubmissionWorkflowEvent.va_sid == self.sids["legacy"]
            )
        )
        self.assertEqual(count, 0)
        self.assertEqual(open_revision_request_sids([self.sids["legacy"]]), set())

    def test_a_stale_fuc_row_whose_latest_event_left_fuc_is_not_open(self):
        """The analytics MV can still read fuc after the interviewer revised.

        The latest event (the revision restart) left fuc, so every definition
        says: not an open revision request, and not a send-back either.
        """
        sid = seed_stale_fuc_case(
            self.FORM_ID, self.base_coder_user.user_id, datetime.now(timezone.utc), "uuid:revsql-stale-fuc"
        )
        db.session.flush()

        # Present before absent: the row is fuc and has a send-back in its history.
        self.assertEqual(db.session.scalar(
            sa.select(VaSubmissionWorkflow.workflow_state).where(VaSubmissionWorkflow.va_sid == sid)), FUC)
        self.assertEqual(db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSubmissionWorkflowEvent).where(
                VaSubmissionWorkflowEvent.va_sid == sid,
                VaSubmissionWorkflowEvent.transition_reason == "sent_back_for_revision")), 1)

        core = db.session.scalar(sa.select(revision_request_open_condition(sa.literal(sid))))
        raw = db.session.scalar(
            sa.text(
                f"SELECT {revision_request_open_sql('w.va_sid')} "
                "FROM va_submission_workflow w WHERE w.va_sid = :sid"
            ),
            {"sid": sid},
        )
        self.assertIs(core, False)
        self.assertIs(raw, False)
        self.assertIsNone(get_open_revision_request(sid))
        self.assertEqual(open_revision_request_sids([sid]), set())
        self.assertEqual(
            db.session.scalar(sa.text(
                f"SELECT {effective_workflow_state_sql('w')} FROM va_submission_workflow w WHERE w.va_sid = :sid"),
                {"sid": sid}),
            FUC,
        )
