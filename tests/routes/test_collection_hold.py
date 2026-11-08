"""Uploads outside the collection period are accepted and held (bead digitva-nuy9).

Policy: docs/policy/project-clock-and-gates.md ("Uploads outside the
collection period are accepted and held"). Decided once at the first upload
from the interview's start date on the project clock against the site (and
unit) gate; the daily limit never holds. Held and rejected interviews leave
every coding/analytics reader through the shared predicate; a gate save that
covers them clears them; a data manager releases or rejects, audited.
"""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import sqlalchemy as sa

from app import db
from app.models import (
    MapOrgUnitCollectionGate,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaSubmissionsAuditlog,
    VaUserAccessGrants,
    VaWebIntakeDraft,
)
from app.services import collection_gate
from app.services.duplicate_exclusion import (
    HELD_MESSAGE,
    excluded_message,
    is_confirmed_duplicate,
    not_confirmed_duplicate_condition,
)
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.authz.fixture import TA, AuthzFixtureMixin
from tests.base import BaseTestCase
from tests.routes import test_collection_gate as gate_tests
from tests.routes.test_collection_gate import API, _upload_body

DM_API = "/api/v1/data-management"


def _iso(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


class CollectionHoldTests(gate_tests.SiteCollectionGateTests):
    """A site project (no tree), on the gate tests' fixture and helpers (their tests are not rerun)."""

    PROJECT_ID = "CGH01"
    SITE_ID = "CH01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dm = cls._get_or_make_user("hold.dm@test.local", "HoldDm12345")
        cls.other_dm = cls._get_or_make_user("hold.otherdm@test.local", "HoldDm12345")
        for user, project in ((cls.dm, cls.PROJECT_ID), (cls.other_dm, cls.BASE_PROJECT_ID)):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.data_manager, scope_type=VaAccessScopeTypes.project,
                project_id=project, notes="collection hold test", grant_status=VaStatuses.active,
            ))
        db.session.commit()

    # ── helpers ────────────────────────────────────────────────────────────

    def _upload(self, started_at=None):
        body = _upload_body(self.PROJECT_ID, self.SITE_ID)
        if started_at is None:
            body["draft"].pop("startedAt")  # an older APK sends no start time
        else:
            body["draft"]["startedAt"] = started_at
        response = self.client.post(f"{API}/submissions", headers=self._csrf_headers(), json=body)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response

    def _draft(self, va_sid):
        db.session.expire_all()
        return db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.va_sid == va_sid, VaWebIntakeDraft.status == "submitted"))

    def _audit(self, va_sid):
        return db.session.scalars(sa.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_sid == va_sid,
            VaSubmissionsAuditlog.va_audit_action.like("collection_hold_%"),
        ).order_by(VaSubmissionsAuditlog.va_audit_id)).all()

    # ── the rule ───────────────────────────────────────────────────────────

    def test_inside_the_window_is_not_held_even_when_uploaded_after_the_end(self):
        today = self._project_today()
        self._gate(collection_start_date=today - timedelta(days=20), collection_end_date=today - timedelta(days=1))
        sid = self._upload(_iso(10)).get_json()["va_sid"]
        self.assertIsNotNone(self._draft(sid))
        self.assertIsNone(self._draft(sid).collection_hold)
        self.assertFalse(is_confirmed_duplicate(sid))

    def test_outside_dates_and_switched_off_hold_with_the_reason(self):
        today = self._project_today()
        for gate, started, reason in (
            ({"collection_end_date": today - timedelta(days=5)}, _iso(1), collection_gate.ENDED),
            ({"collection_start_date": today + timedelta(days=1)}, _iso(0), collection_gate.NOT_STARTED),
            ({"collection_enabled": False}, _iso(0), collection_gate.PAUSED),
        ):
            with self.subTest(reason=reason):
                self._gate(collection_enabled=True, collection_start_date=None, collection_end_date=None)
                self._gate(**gate)
                sid = self._upload(started).get_json()["va_sid"]
                draft = self._draft(sid)
                self.assertEqual((draft.collection_hold, draft.collection_hold_reason), ("held", reason))
                self.assertEqual([a.va_audit_action for a in self._audit(sid)], ["collection_hold_held"])

    def test_an_old_apk_upload_without_a_start_time_uses_receipt_and_keeps_its_reply_shape(self):
        open_reply = self._upload(None).get_json()
        self._gate(collection_end_date=self._project_today() - timedelta(days=1))
        held_reply = self._upload(None).get_json()
        self.assertEqual(self._draft(held_reply["va_sid"]).collection_hold, "held")
        self.assertIsNone(self._draft(open_reply["va_sid"]).collection_hold)
        self.assertEqual(set(held_reply), set(open_reply))
        self.assertFalse(held_reply["can_code_now"])

    def test_the_daily_limit_never_holds(self):
        self._gate(daily_interviewer_limit=1)
        self.assertEqual(self._register().status_code, 201)
        sid = self._upload(_iso(0)).get_json()["va_sid"]
        self.assertIsNone(self._draft(sid).collection_hold)

    # ── exclusion ──────────────────────────────────────────────────────────

    def test_held_and_rejected_leave_the_shared_predicate_released_and_odk_pass(self):
        self._gate(collection_enabled=False)
        sid = self._upload(_iso(0)).get_json()["va_sid"]
        def passes(s):
            return db.session.scalar(sa.select(not_confirmed_duplicate_condition(sa.literal(s))))
        self.assertFalse(passes(sid))
        self.assertTrue(is_confirmed_duplicate(sid))
        self.assertEqual(excluded_message(sid), HELD_MESSAGE)
        # An ODK submission has no intake draft: never held.
        self.assertTrue(passes("odk-uuid:never-held"))
        for status, expected in (("rejected", False), ("released", True)):
            db.session.execute(sa.update(VaWebIntakeDraft).where(VaWebIntakeDraft.va_sid == sid)
                               .values(collection_hold=status))
            self.assertEqual(passes(sid), expected, status)

    def test_the_coder_pool_skips_a_held_interview_until_it_is_released(self):
        from app.models import VaSubmissions, VaSubmissionWorkflow
        from app.services.coder_workflow_service import _available_submission_filters

        open_sid = self._upload(_iso(0)).get_json()["va_sid"]
        self._gate(collection_enabled=False)
        held_sid = self._upload(_iso(0)).get_json()["va_sid"]
        db.session.execute(sa.update(VaSubmissionWorkflow).where(
            VaSubmissionWorkflow.va_sid.in_([open_sid, held_sid])).values(workflow_state="ready_for_coding"))
        form_ids = list(db.session.scalars(sa.select(VaSubmissions.va_form_id).where(
            VaSubmissions.va_sid.in_([open_sid, held_sid]))).all())
        def pool():
            return set(db.session.scalars(
                sa.select(VaSubmissions.va_sid)
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(*_available_submission_filters(form_ids))).all())
        self.assertIn(open_sid, pool())
        self.assertNotIn(held_sid, pool())
        self._login(str(self.dm.user_id))
        self.assertEqual(self._decide(held_sid, "release").status_code, 200)
        self.assertIn(held_sid, pool())

    # ── auto-clear on a gate save ──────────────────────────────────────────

    def _put_site(self, body):
        self._login(self.base_admin_id)
        response = self.client.put(
            f"/admin/api/project-sites/{self.PROJECT_ID}/{self.SITE_ID}/collection-settings",
            headers=self._csrf_headers(), json=body)
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_a_site_save_that_covers_the_start_date_clears_and_one_that_does_not_keeps(self):
        today = self._project_today()
        self._gate(collection_end_date=today - timedelta(days=5))
        sid = self._upload(_iso(1)).get_json()["va_sid"]
        self.assertEqual(self._draft(sid).collection_hold, "held")
        self._put_site({"collection_enabled": True, "collection_end_date": (today - timedelta(days=3)).isoformat()})
        self.assertEqual(self._draft(sid).collection_hold, "held")
        self._put_site({"collection_enabled": True, "collection_end_date": ""})
        self.assertEqual(self._draft(sid).collection_hold, "released")
        self.assertTrue(db.session.scalar(sa.select(not_confirmed_duplicate_condition(sa.literal(sid)))))
        self.assertEqual([a.va_audit_action for a in self._audit(sid)],
                         ["collection_hold_held", "collection_hold_cleared"])

    def test_a_covering_gate_save_never_clears_a_rejected_interview(self):
        today = self._project_today()
        self._gate(collection_end_date=today - timedelta(days=5))
        sid = self._upload(_iso(1)).get_json()["va_sid"]
        self._login(str(self.dm.user_id))
        self.assertEqual(self._decide(sid, "reject", note="Outside study").status_code, 200)
        self._put_site({"collection_enabled": True, "collection_end_date": ""})
        self.assertEqual(self._draft(sid).collection_hold, "rejected")

    def test_a_revision_of_a_held_interview_stays_held(self):
        self._gate(collection_enabled=False)
        sid = self._upload(_iso(0)).get_json()["va_sid"]
        text = json.dumps(dict(gate_tests._answers(), Id10017="Binita"), separators=(",", ":"))
        revision = self.client.post(f"{API}/submissions/{sid}/revisions", headers=self._csrf_headers(), json={
            "reason_code": "interviewer_correction", "draft": {}, "completion": {"valid": True, "issues": []},
            "answers_json": text, "answers_sha256": hashlib.sha256(text.encode()).hexdigest(),
        })
        self.assertEqual(revision.status_code, 200, revision.get_json())
        self.assertEqual(self._draft(sid).collection_hold, "held")
        self.assertFalse(db.session.scalar(sa.select(not_confirmed_duplicate_condition(sa.literal(sid)))))

    def test_the_interviewers_own_counts_keep_held_and_rejected_interviews(self):
        from app.services.user_home_service import get_user_activity_summary

        self._gate(collection_enabled=False)
        sid = self._upload(_iso(0)).get_json()["va_sid"]
        def submitted():
            totals = get_user_activity_summary(self.interviewer)["by_project"][self.PROJECT_ID]
            return totals["interviews_submitted"]
        self.assertEqual(submitted(), 1)
        db.session.execute(sa.update(VaWebIntakeDraft).where(VaWebIntakeDraft.va_sid == sid)
                           .values(collection_hold="rejected"))
        db.session.commit()
        self.assertEqual(submitted(), 1)

    # ── data manager ───────────────────────────────────────────────────────

    def _held_sid(self):
        self._gate(collection_enabled=False)
        return self._upload(_iso(0)).get_json()["va_sid"]

    def _decide(self, sid, action, **body):
        return self.client.post(f"{DM_API}/submissions/{sid}/collection-hold/{action}",
                                headers=self._csrf_headers(), json=body)

    def test_dm_lists_rejects_and_releases_with_audited_notes(self):
        sid = self._held_sid()
        self._login(str(self.dm.user_id))
        listed = self.client.get(f"{DM_API}/collection-holds").get_json()
        item = next(i for i in listed["items"] if i["va_sid"] == sid)
        self.assertEqual(item["reason"], collection_gate.PAUSED)
        self.assertNotIn("deceased_name", item)
        self.assertEqual(self._decide(sid, "reject", note="Outside study").status_code, 200)
        self.assertEqual(self._decide(sid, "reject").status_code, 409)
        rejected = self.client.get(f"{DM_API}/collection-holds?status=rejected").get_json()["items"]
        self.assertIn(sid, [i["va_sid"] for i in rejected])
        self.assertEqual(self._decide(sid, "release", note="Approved late").status_code, 200)
        self.assertEqual(self._draft(sid).collection_hold, "released")
        self.assertEqual(self._decide(sid, "release").status_code, 409)
        audit = self._audit(sid)
        self.assertEqual([(a.va_audit_action, a.va_audit_note) for a in audit], [
            ("collection_hold_held", None), ("collection_hold_rejected", "Outside study"),
            ("collection_hold_released", "Approved late")])
        self.assertEqual(audit[-1].va_audit_by, self.dm.user_id)
        self.assertEqual(audit[-1].va_audit_byrole, "data_manager")

    def test_list_pages_with_a_clamped_limit_and_refuses_a_bad_cursor(self):
        sids = {self._held_sid(), self._held_sid()}
        self._login(self.base_admin_id)
        first = self.client.get(f"{DM_API}/collection-holds?limit=1&project_id={self.PROJECT_ID}").get_json()
        self.assertEqual(len(first["items"]), 1)
        second = self.client.get(
            f"{DM_API}/collection-holds?limit=1&project_id={self.PROJECT_ID}&cursor={quote(first['next_cursor'])}"
        ).get_json()
        self.assertEqual({first["items"][0]["va_sid"], second["items"][0]["va_sid"]}, sids)
        self.assertEqual(self.client.get(f"{DM_API}/collection-holds?cursor=nope").status_code, 400)
        self.assertEqual(self.client.get(f"{DM_API}/collection-holds?status=released").status_code, 400)

    def test_dm_out_of_scope_gets_403_and_an_empty_list(self):
        sid = self._held_sid()
        self._login(str(self.other_dm.user_id))
        self.assertEqual(self._decide(sid, "release").status_code, 403)
        listed = self.client.get(f"{DM_API}/collection-holds").get_json()["items"]
        self.assertNotIn(sid, [i["va_sid"] for i in listed])
        self.assertEqual(self._draft(sid).collection_hold, "held")
        self._login(self.interviewer_id)
        self.assertEqual(self._decide(sid, "release").status_code, 403)

    def test_release_without_a_csrf_token_is_refused(self):
        sid = self._held_sid()
        self._login(str(self.dm.user_id))
        old = self.app.config.get("WTF_CSRF_ENABLED")
        self.app.config["WTF_CSRF_ENABLED"] = True
        try:
            response = self.client.post(f"{DM_API}/submissions/{sid}/collection-hold/release", json={})
        finally:
            self.app.config["WTF_CSRF_ENABLED"] = old
        self.assertIn(response.status_code, (400, 403))
        self.assertEqual(self._draft(sid).collection_hold, "held")


# The gate tests' own test methods run in their module, not again here.
for _name in dir(gate_tests.SiteCollectionGateTests):
    if _name.startswith("test_") and _name not in vars(CollectionHoldTests):
        setattr(CollectionHoldTests, _name, None)


class TreeCollectionHoldTests(AuthzFixtureMixin, BaseTestCase):
    """The AZTA01 tree: the stricter unit gate holds, and a unit save clears."""

    SITE = "AZS1"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from app.models import VaProjectMaster

        project = db.session.get(VaProjectMaster, TA)
        project.web_intake_mode = "both"
        project.project_structure_mode = "organization"
        _ensure_legacy_project_site_rows(TA, cls.SITE)
        db.session.commit()

    def setUp(self):
        super().setUp()
        self._login(str(self.users["interviewer_p1"].user_id))

    def test_a_closed_unit_holds_under_an_open_site_and_a_unit_save_clears(self):
        unit_id = self.units["P1"].org_unit_id
        db.session.add(MapOrgUnitCollectionGate(org_unit_id=unit_id, collection_enabled=False))
        db.session.commit()
        site = db.session.get(VaProjectSites, self.project_site_ids[(TA, self.SITE)])
        self.assertTrue(site.collection_enabled)
        body = _upload_body(TA, self.SITE, org_unit_id=str(self.units["SC1"].org_unit_id))
        response = self.client.post(f"{API}/submissions", headers=self._csrf_headers(), json=body)
        self.assertEqual(response.status_code, 201, response.get_json())
        sid = response.get_json()["va_sid"]
        def draft():
            return db.session.scalar(sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.va_sid == sid))
        self.assertEqual(draft().collection_hold, "held")
        self._login(self.base_admin_id)
        saved = self.client.put(f"/admin/api/organization/{TA}/units/{unit_id}/collection-gate",
                                headers=self._csrf_headers(), json={"collection_enabled": True})
        self.assertEqual(saved.status_code, 200, saved.get_json())
        db.session.expire_all()
        self.assertEqual(draft().collection_hold, "released")
