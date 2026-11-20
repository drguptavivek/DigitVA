"""A consent-withdrawn case is sealed: admin only (docs/policy/consent-withdrawal.md
section 4). Each surface is checked open before the withdrawal, refused after
for a non-admin, open to an admin, and open again after the admin's undo."""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import VaProjectMaster, VaSubmissions, VaWebIntakeDraft
from app.services import offline_coding_import_service as offline
from app.services import web_intake_service as intake_svc
from app.services.authz import Action, can, scope_filter
from app.services.case_transition_service import WebIntakeError
from tests.services import test_consent_withdrawal as withdrawal_tests


class ConsentWithdrawalSealTests(withdrawal_tests.WithdrawnCaseExclusionTests):
    PROJECT_ID = "WDSL01"
    SITE_ID = "WS01"
    FORM_ID = "WDSL01WS0101"

    def _sealed_case(self):
        case = self._case("ready_for_coding")
        draft = VaWebIntakeDraft(
            project_id=self.PROJECT_ID, site_id=self.SITE_ID, form_id=self.FORM_ID, user_id=self.ian.user_id,
            unique_id=case.unique_id, death_id=case.death_id, va_sid=case.va_sid, status="submitted",
        )
        db.session.add(draft)
        db.session.commit()
        return case, draft

    def _listed(self, user, action, va_sid):
        return va_sid in db.session.scalars(
            sa.select(VaSubmissions.va_sid).where(scope_filter(user, action), VaSubmissions.va_sid == va_sid)
        ).all()

    def _visible(self, case, draft):
        """What each non-admin surface answers for the case now."""
        sid = case.va_sid
        try:
            intake_svc.get_draft(self.ian, draft.draft_id)
            own_draft = True
        except WebIntakeError as exc:
            self.assertEqual(exc.status_code, 404)
            own_draft = False
        self._login(str(self.dana.user_id))
        events = self.client.get(f"/api/v1/workflow/events/{sid}").status_code
        return {
            "own_draft": own_draft,
            "own_submitted_list": draft.draft_id in {
                d.draft_id for d in intake_svc.list_drafts(self.ian, status="submitted")},
            "coder_view": bool(can(self.coder, Action.VIEW, sid)),
            "reviewer_view": bool(can(self.reviewer, Action.VIEW, sid)),
            "dm_view": bool(can(self.dana, Action.VIEW, sid)),
            "dm_triage": bool(can(self.dana, Action.TRIAGE, sid)),
            "dm_list": self._listed(self.dana, Action.LIST_DATA, sid),
            "dm_events_http": events,
            "dm_answers": intake_svc.may_read_submitted_answers(self.dana, sid),
        }

    def test_sealed_for_non_admins_open_to_admin_and_back_after_undo(self):
        case, draft = self._sealed_case()
        before = self._visible(case, draft)
        self.assertEqual(before, {
            "own_draft": True, "own_submitted_list": True, "coder_view": True, "reviewer_view": True,
            "dm_view": True, "dm_triage": True, "dm_list": True, "dm_events_http": 200, "dm_answers": True,
        })

        self._confirm(case)
        after = self._visible(case, draft)
        self.assertEqual(after, {
            "own_draft": False, "own_submitted_list": False, "coder_view": False, "reviewer_view": False,
            "dm_view": False, "dm_triage": False, "dm_list": False, "dm_events_http": 404, "dm_answers": False,
        })
        # Refused as a missing case, never as out of scope (the id is not confirmed).
        self.assertEqual(can(self.coder, Action.VIEW, case.va_sid).reason.value, "not_found")
        # The admin keeps everything.
        admin = self.base_admin_user
        self.assertTrue(can(admin, Action.VIEW, case.va_sid))
        self.assertTrue(self._listed(admin, Action.LIST_DATA, case.va_sid))
        self._login(str(admin.user_id))
        self.assertEqual(self.client.get(f"/api/v1/workflow/events/{case.va_sid}").status_code, 200)

        self._reopen(case)
        self.assertEqual(self._visible(case, draft), before)

    def test_coding_actions_keep_the_withdrawal_conflict(self):
        """CODE/REVIEW are not sealed in authz: the workflow answers 409 with
        the withdrawal message, the shape older apps show today."""
        case, _ = self._sealed_case()
        self._confirm(case)
        self.assertTrue(can(self.coder, Action.CODE, case.va_sid))

    def test_offline_coding_on_a_withdrawn_case_is_refused(self):
        case, draft = self._sealed_case()
        project = db.session.get(VaProjectMaster, self.PROJECT_ID)
        coding = {"coded_answers_sha256": ""}
        self.assertNotEqual(offline._push_refusal(self.coder, project, draft, coding), "not_available")
        self._confirm(case)
        self.assertEqual(offline._push_refusal(self.coder, project, draft, coding), "not_available")
        self._reopen(case)
        self.assertNotEqual(offline._push_refusal(self.coder, project, draft, coding), "not_available")


# Only the seal tests run here; the inherited reader tests run in their own modules.
for _name in dir(withdrawal_tests.WithdrawnCaseExclusionTests):
    if _name.startswith("test_") and _name not in ConsentWithdrawalSealTests.__dict__:
        setattr(ConsentWithdrawalSealTests, _name, None)
