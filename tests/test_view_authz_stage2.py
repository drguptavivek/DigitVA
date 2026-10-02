"""Viewing a submission on the authz module: what stage 2 changes on purpose.

digitva-0wc stage 2 (.tasks/digitva-0wc-design.md section 7) moves the
read-only rendering, attachments and workflow events onto ``Action.VIEW``
(.tasks/digitva-0wc-access-matrix-current.md):

- F3 / digitva-blp: a coder or reviewer above the coding scope level opens
  ``/coding/area/<sid>`` and its partials load (they returned 403).
- F12: attachments follow VIEW and the submission's current routing, not an
  allocation.
- F13 / F8 / F11: events follow VIEW, so admin, project_pi and viewers read
  them and a unit grant reads only its subtree.
- F3 side note: opening a submission read-only never queues a repair job.

The PII side of the viewer rendering is in
tests/routes/test_va_form_pii_redaction.py.
"""
from unittest.mock import patch

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.services.attachment_service import can_access_submission_attachment
from tests.base import BaseTestCase
from tests.test_coding_scope_enforcement import CodingScopeFixtureMixin


class ViewAuthzStageTwoTests(CodingScopeFixtureMixin, BaseTestCase):
    """CSC001: District > CHC > PHC (two), coding scope level PHC, view_only."""

    def setUp(self):
        super().setUp()
        self.levels, _, self.chc, self.phc_a, self.phc_b = self._tree()
        self._set_scope(self.levels["phc"])
        self._submission("csc-s2-phc-a", unit=self.phc_a)
        self._submission("csc-s2-phc-b", unit=self.phc_b)

    # -- fixtures ----------------------------------------------------------

    def _user(self, key, role, where):
        """A fresh user holding one grant: at "project" or at a unit."""
        user = self._make_user(f"stage2.{key}@test.local", "Stage2Test123")
        fields = (
            {"scope_type": VaAccessScopeTypes.project, "project_id": self.PROJECT}
            if where == "project"
            else {"scope_type": VaAccessScopeTypes.org_unit, "org_unit_id": where.org_unit_id}
        )
        if role == VaAccessRoles.coder and where != "project":
            from app.services import organization_service as org

            cadres = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}
            fields["cadre_id"] = cadres["SMO"].cadre_id
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, grant_status=VaStatuses.active, **fields,
        ))
        db.session.commit()
        return user

    def _get(self, user, url, **query):
        self._login(str(user.user_id))
        return self.client.get(url, query_string=query).status_code

    # -- F3 / blp ----------------------------------------------------------

    def test_a_view_only_coder_opens_the_area_view_and_its_partials(self):
        coder = self._user("blp.coder", VaAccessRoles.coder, self.chc)
        self.assertEqual(self._get(coder, "/coding/area/csc-s2-phc-a"), 200)
        for action in ("vaarea", "vadata"):
            with self.subTest(action=action):
                self.assertEqual(self._get(
                    coder, "/vaform/csc-s2-phc-a/workflow_history",
                    action=action, actiontype="vaview",
                ), 200)

    def test_a_view_only_reviewer_opens_the_area_view_and_its_partials(self):
        reviewer = self._user("blp.reviewer", VaAccessRoles.reviewer, self.chc)
        self.assertEqual(self._get(reviewer, "/coding/area/csc-s2-phc-b"), 200)
        self.assertEqual(self._get(
            reviewer, "/vaform/csc-s2-phc-b/workflow_history",
            action="vaarea", actiontype="vaview",
        ), 200)

    def test_area_partials_stay_inside_the_subtree(self):
        coder = self._user("blp.unit", VaAccessRoles.coder, self.phc_a)
        self.assertEqual(self._get(
            coder, "/vaform/csc-s2-phc-a/workflow_history", action="vaarea", actiontype="vaview",
        ), 200)
        self.assertEqual(self._get(
            coder, "/vaform/csc-s2-phc-b/workflow_history", action="vaarea", actiontype="vaview",
        ), 403)
        self.assertEqual(self._get(coder, "/coding/area/csc-s2-phc-b"), 403)

    def test_a_viewer_opens_the_area_view_in_scope_only(self):
        viewer = self._user("viewer.unit", VaAccessRoles.collaborator, self.phc_a)
        self.assertEqual(self._get(viewer, "/coding/area/csc-s2-phc-a"), 200)
        self.assertEqual(self._get(viewer, "/coding/area/csc-s2-phc-b"), 403)

    def test_opening_read_only_never_queues_a_repair_for_a_viewer(self):
        viewer = self._user("viewer.repair", VaAccessRoles.collaborator_pii, "project")
        coder = self._user("coder.repair", VaAccessRoles.coder, self.chc)
        with patch("app.tasks.sync_tasks.run_open_submission_repair.delay") as repair:
            self.assertEqual(self._get(viewer, "/coding/area/csc-s2-phc-a"), 200)
            self.assertEqual(self._get(coder, "/coding/area/csc-s2-phc-b"), 200)
        repair.assert_not_called()

    # -- F12: attachments ----------------------------------------------------

    def test_attachments_follow_view_scope_not_an_allocation(self):
        coder = self._user("att.coder", VaAccessRoles.coder, self.phc_a)
        # In scope, nothing held: allowed.
        self.assertTrue(can_access_submission_attachment(
            coder, va_form_id=self.FORM_ID, va_sid="csc-s2-phc-a"))
        # Re-routed out of the coder's unit while the coder holds it: denied.
        db.session.add(VaAllocations(
            va_sid="csc-s2-phc-a", va_allocated_to=coder.user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active,
        ))
        submission = db.session.get(VaSubmissions, "csc-s2-phc-a")
        submission.org_unit_id = self.phc_b.org_unit_id
        db.session.commit()
        self.assertFalse(can_access_submission_attachment(
            coder, va_form_id=self.FORM_ID, va_sid="csc-s2-phc-a"))

    def test_attachments_for_viewers_in_and_out_of_scope(self):
        viewer = self._user("att.viewer", VaAccessRoles.collaborator_pii, self.phc_a)
        self.assertTrue(can_access_submission_attachment(
            viewer, va_form_id=self.FORM_ID, va_sid="csc-s2-phc-a"))
        self.assertFalse(can_access_submission_attachment(
            viewer, va_form_id=self.FORM_ID, va_sid="csc-s2-phc-b"))

    # -- F13 / F8 / F11: events --------------------------------------------

    def test_events_follow_view_scope(self):
        coder = self._user("ev.coder", VaAccessRoles.coder, self.phc_a)
        self.assertEqual(self._get(coder, "/api/v1/workflow/events/csc-s2-phc-a"), 200)
        self.assertEqual(self._get(coder, "/api/v1/workflow/events/csc-s2-phc-b"), 403)

        viewer = self._user("ev.viewer", VaAccessRoles.collaborator, "project")
        self.assertEqual(self._get(viewer, "/api/v1/workflow/events/csc-s2-phc-b"), 200)

        project_pi = self._user("ev.pi", VaAccessRoles.project_pi, "project")
        self.assertEqual(self._get(project_pi, "/api/v1/workflow/events/csc-s2-phc-b"), 200)

        self.assertEqual(self._get(self.base_admin_user, "/api/v1/workflow/events/csc-s2-phc-b"), 200)

    def test_events_refuse_a_user_with_no_scope(self):
        nobody = self._make_user("stage2.ev.nobody@test.local", "Stage2Test123")
        db.session.commit()
        self.assertEqual(self._get(nobody, "/api/v1/workflow/events/csc-s2-phc-a"), 403)

    def test_a_demo_trainee_without_a_grant_keeps_view(self):
        # Demo coding sessions read attachments, events and notes through
        # VIEW; the virtual demo grants must count for it (design 2.6).
        from app.models import VaProjectMaster
        from app.services.authz import Action, can

        trainee = self._make_user("stage2.demo.trainee@test.local", "Stage2Test123")
        db.session.commit()
        self.assertFalse(can(trainee, Action.VIEW, "csc-s2-phc-a"))
        db.session.get(VaProjectMaster, self.PROJECT).demo_training_enabled = True
        db.session.commit()
        self.assertTrue(can(trainee, Action.VIEW, "csc-s2-phc-a"))
