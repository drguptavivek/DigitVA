"""Mentor view API: who sees which district, counts, drill-down, notes.

Policy: docs/policy/mentor-view.md (digitva-oux5). Tree CSC001: district
D01 > CHC C01 > PHC P01, P02, plus district D02 created here.
"""
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import sqlalchemy as sa

from app import db
from app.models import (
    MapUserNotification,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaCoderFeedbackNote,
    VaCoderReview,
    VaCodingEpisode,
    VaFinalAssessments,
    VaReviewerFinalAssessments,
    VaStatuses,
    VaSubmissionsAuditlog,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services import mentor_institute_service as mentors
from app.services import organization_service as org
from tests.base import BaseTestCase
from tests.test_unit_scoped_dm_tester import UnitScopeFixture

R = VaAccessRoles
API = "/api/v1/mentor"


class MentorViewTests(UnitScopeFixture, BaseTestCase):
    def setUp(self):
        super().setUp()
        levels, self.d1, self.chc, self.phc_a, self.phc_b = self._tree()
        self.d2 = org.create_unit(
            self.PROJECT, org_level_id=levels["district"].org_level_id,
            unit_code="D02", unit_name="District Two",
        )
        db.session.commit()
        self.coder_a = self._user_with("mv.coder.a@test.local", R.coder, self.phc_a)
        self.coder_b = self._user_with("mv.coder.b@test.local", R.coder, self.d1)
        self.coder_a.name, self.coder_b.name = "Alpha Coder", "Bravo Coder"
        self.dm = self._user_with("mv.dm@test.local", R.data_manager, self.d1)
        self.incharge = self._user_with("mv.incharge@test.local", R.site_pi, self.d1)
        self.reviewer = self._user_with("mv.reviewer@test.local", R.reviewer, self.d1)
        now = datetime.now(UTC)
        # s1 agreed, s2 changed, s3 by B, s4 ready, s5 old (outside 30d), s6 in D02.
        for sid, unit in (("mv-s1", self.phc_a), ("mv-s2", self.phc_a), ("mv-s3", self.phc_b),
                          ("mv-s4", self.phc_a), ("mv-s5", self.phc_a), ("mv-s6", self.d2)):
            self._sub(sid, unit=unit)
        self._coded("mv-s1", self.coder_a, now, reviewer_cod="A01")
        self._coded("mv-s2", self.coder_a, now, reviewer_cod="B02")
        self._coded("mv-s3", self.coder_b, now)
        self._coded("mv-s5", self.coder_a, now - timedelta(days=60))
        self._coded("mv-s6", self.coder_a, now)
        db.session.add(VaCoderReview(
            va_sid="mv-s4", va_creview_by=self.coder_a.user_id, va_creview_reason="other",
        ))
        db.session.add(VaCodingEpisode(
            va_sid="mv-s1", episode_type="recode", episode_status="completed",
            started_by=self.coder_a.user_id, completed_at=now,
        ))
        db.session.add(VaCodingEpisode(
            va_sid="mv-s2", episode_type="recode", episode_status="abandoned",
            started_by=self.coder_a.user_id,
        ))
        db.session.commit()

    # -- fixtures ----------------------------------------------------------

    def _coded(self, sid, coder, when, reviewer_cod=None):
        db.session.add(VaFinalAssessments(
            va_sid=sid, va_finassess_by=coder.user_id, va_conclusive_cod="A01",
            va_finassess_createdat=when,
        ))
        if reviewer_cod:
            db.session.add(VaReviewerFinalAssessments(
                va_sid=sid, va_rfinassess_by=self.reviewer.user_id, va_conclusive_cod=reviewer_cod,
            ))
        db.session.execute(sa.update(VaSubmissionWorkflow).where(
            VaSubmissionWorkflow.va_sid == sid).values(workflow_state="coder_finalized"))

    def _mentor(self, email, role):
        user = self._get_or_make_user(email, "MentorView123")
        mentors.create_institute("MVI", "Mentor View Institute")
        mentors.attach_district("MVI", self.PROJECT, "D01")
        mentors.add_member("MVI", email)
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.d1.org_unit_id, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user

    def _get(self, user, path):
        self._login(str(user.user_id))
        return self.client.get(f"{API}{path}")

    def _table(self, user, district=None, period="all"):
        district = district or self.d1
        return self._get(user, f"/coders?district={district.org_unit_id}&period={period}")

    def _note(self, user, sid, body="Check the fever history."):
        self._login(str(user.user_id))
        return self.client.post(f"{API}/cases/{sid}/notes", json={"body": body},
                                headers=self._csrf_headers())

    # -- who sees it -------------------------------------------------------

    def test_district_dm_and_incharge_see_their_district(self):
        for user in (self.dm, self.incharge):
            with self.subTest(user=user.email):
                response = self._get(user, "/districts")
                self.assertEqual(response.status_code, 200, response.get_json())
                ids = {d["district_id"] for d in response.get_json()["districts"]}
                self.assertEqual(ids, {str(self.d1.org_unit_id)})
                self.assertEqual(self._table(user).status_code, 200)
                self.assertEqual(self._table(user, self.d2).status_code, 404)

    def test_coder_only_and_project_scope_dm_are_refused(self):
        project_dm = self._get_or_make_user("mv.projdm@test.local", "MentorView123")
        db.session.add(VaUserAccessGrants(
            user_id=project_dm.user_id, role=R.data_manager, scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        for user in (self.coder_a, project_dm):
            with self.subTest(user=user.email):
                self.assertEqual(self._get(user, "/districts").status_code, 403)
                self.assertEqual(self._table(user).status_code, 403)
                cases = self._get(user, f"/coders/{self.coder_b.user_id}/cases?district={self.d1.org_unit_id}")
                self.assertEqual(cases.status_code, 403)

    def test_dm_below_the_district_is_refused(self):
        phc_dm = self._user_with("mv.phcdm@test.local", R.data_manager, self.phc_a)
        self.assertEqual(self._get(phc_dm, "/districts").status_code, 403)

    def test_bad_district_and_period(self):
        self.assertEqual(self._get(self.dm, "/coders?district=nope").status_code, 404)
        self.assertEqual(self._table(self.dm, period="7y").status_code, 400)

    def test_bearer_token_is_refused(self):
        response = self.client.get(f"{API}/districts", headers={"Authorization": "Bearer x"})
        self.assertIn(response.status_code, (401, 403))

    # -- counts ------------------------------------------------------------

    def test_counts_per_coder(self):
        body = self._table(self.dm).get_json()
        self.assertTrue(body["names_visible"])
        rows = {row["label"]: row for row in body["coders"]}
        self.assertEqual(list(rows), ["Alpha Coder", "Bravo Coder"])
        alpha = rows["Alpha Coder"]
        self.assertEqual(
            (alpha["coded"], alpha["reviewed_agreed"], alpha["reviewed_changed"],
             alpha["not_codeable"], alpha["recodes"], alpha["ready"]),
            (3, 1, 1, 1, 1, 1),  # s1, s2, s5 coded; s6 is in D02; s4 is ready under P01
        )
        self.assertEqual(alpha["coder_id"], str(self.coder_a.user_id))
        bravo = rows["Bravo Coder"]
        self.assertEqual((bravo["coded"], bravo["ready"]), (1, 1))
        recent = {r["label"]: r for r in self._table(self.dm, period="30d").get_json()["coders"]}
        self.assertEqual(recent["Alpha Coder"]["coded"], 2)

    def test_mentor_with_plain_grant_sees_pseudonyms_and_can_still_write_notes(self):
        mentor = self._mentor("mv.mentor.collab@test.local", R.collaborator)
        response = self._table(mentor)
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertFalse(body["names_visible"])
        self.assertEqual([r["label"] for r in body["coders"]], ["Coder 1", "Coder 2"])
        # Owner 2026-11-20: names stay hidden, but the mentor may open the
        # coder's cases and write a note.
        self.assertTrue(all(r.get("coder_id") for r in body["coders"]))
        cases = self._get(mentor, f"/coders/{self.coder_a.user_id}/cases?district={self.d1.org_unit_id}")
        self.assertEqual(cases.status_code, 200, cases.get_json())
        self.assertRegex(cases.get_json()["coder"]["name"], r"^Coder \d+$")
        self.assertNotIn(self.coder_a.name, cases.get_data(as_text=True))
        self.assertEqual(self._note(mentor, "mv-s1").status_code, 201)

    def test_pseudonyms_follow_user_id_not_name(self):
        mentor = self._mentor("mv.mentor.order@test.local", R.collaborator)
        hidden = self._table(mentor).get_json()["coders"]
        named = {r["coder_id"]: r for r in self._table(self.dm).get_json()["coders"]}
        by_id = sorted(named, key=uuid.UUID)
        self.assertEqual(sorted(r["recodes"] for r in hidden), [0, 1])  # the two rows differ
        self.assertEqual([r["recodes"] for r in hidden], [named[i]["recodes"] for i in by_id])
        self.assertEqual([r["ready"] for r in hidden], [named[i]["ready"] for i in by_id])

    def test_mentor_reach_ends_with_the_district_link(self):
        mentor = self._mentor("mv.mentor.link@test.local", R.collaborator)
        self.assertEqual(self._table(mentor, self.d2).status_code, 404)  # not attached
        mentors.detach_district("MVI", self.PROJECT, "D01")
        db.session.commit()
        self.assertEqual(self._table(mentor).status_code, 403)

    def test_mentor_without_unit_grant_sees_zero_counts(self):
        mentor = self._get_or_make_user("mv.mentor.bare@test.local", "MentorView123")
        mentors.create_institute("MVI", "Mentor View Institute")
        mentors.attach_district("MVI", self.PROJECT, "D01")
        mentors.add_member("MVI", mentor.email)
        db.session.commit()
        rows = self._table(mentor).get_json()["coders"]
        self.assertEqual(len(rows), 2)
        self.assertEqual({(r["coded"], r["ready"], r["recodes"]) for r in rows}, {(0, 0, 0)})

    def test_admin_sees_every_district(self):
        ids = {d["district_id"] for d in self._get(self.base_admin_user, "/districts").get_json()["districts"]}
        self.assertTrue({str(self.d1.org_unit_id), str(self.d2.org_unit_id)} <= ids)
        self.assertEqual(self._table(self.base_admin_user).status_code, 200)

    def test_mentor_with_district_dm_grant_sees_names(self):
        mentor = self._mentor("mv.mentor.dm@test.local", R.data_manager)
        body = self._table(mentor).get_json()
        self.assertTrue(body["names_visible"])
        self.assertIn("Alpha Coder", [r["label"] for r in body["coders"]])

    # -- drill-down --------------------------------------------------------

    def test_drilldown_lists_coded_cases_and_pages(self):
        path = f"/coders/{self.coder_a.user_id}/cases?district={self.d1.org_unit_id}"
        with self.assertLogs("GRANT_AUDIT", level="INFO") as logged:
            body = self._get(self.dm, path).get_json()
        line = logged.output[-1]
        self.assertIn("action=mentor_case_list_opened", line)
        self.assertIn(f"coder={self.coder_a.user_id}", line)
        self.assertIn("rows=3", line)
        outcomes = {c["va_sid"]: (c["review_outcome"], c["final_cod"]) for c in body["cases"]}
        self.assertEqual(outcomes, {
            "mv-s1": ("agreed", "A01"), "mv-s2": ("changed", "B02"), "mv-s5": ("not_reviewed", "A01"),
        })
        self.assertIsNone(body["next"])
        self.assertNotIn("va_uniqueid_real", str(body))
        from app.services import mentor_view_service as service
        original = service.CASE_PAGE_SIZE
        service.CASE_PAGE_SIZE = 2
        try:
            first = self._get(self.dm, path).get_json()
            self.assertEqual(len(first["cases"]), 2)
            second = self._get(self.dm, f"{path}&after={quote(first['next'])}")
            self.assertEqual(second.status_code, 200, second.get_json())
            second = second.get_json()
        finally:
            service.CASE_PAGE_SIZE = original
        sids = [c["va_sid"] for c in first["cases"] + second["cases"]]
        self.assertEqual(sorted(sids), ["mv-s1", "mv-s2", "mv-s5"])
        self.assertEqual(self._get(self.dm, f"{path}&after=garbage").status_code, 400)

    def test_drilldown_is_read_only_and_unknown_coder_is_404(self):
        path = f"/coders/{self.coder_a.user_id}/cases?district={self.d1.org_unit_id}"
        self._login(str(self.dm.user_id))
        self.assertEqual(self.client.post(f"{API}{path}", headers=self._csrf_headers()).status_code, 405)
        stranger = self._get(self.dm, f"/coders/{self.dm.user_id}/cases?district={self.d1.org_unit_id}")
        self.assertEqual(stranger.status_code, 404)

    # -- notes -------------------------------------------------------------

    def test_note_write_audit_notification_and_coder_read(self):
        response = self._note(self.dm, "mv-s1")
        self.assertEqual(response.status_code, 201, response.get_json())
        note_id = response.get_json()["note_id"]
        note = db.session.get(VaCoderFeedbackNote, uuid.UUID(note_id))
        self.assertEqual((note.coder_user_id, note.author_basis), (self.coder_a.user_id, "data_manager"))
        audit = db.session.scalars(sa.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_audit_entityid == note.note_id)).all()
        self.assertEqual([a.va_audit_action for a in audit], ["mentor_note_created"])
        self.assertNotIn("fever", str(audit[0].va_audit_note))
        kinds = db.session.scalars(sa.select(MapUserNotification.kind).where(
            MapUserNotification.user_id == self.coder_a.user_id)).all()
        self.assertIn("mentor_feedback", kinds)

        mine = self._get(self.coder_a, "/feedback/mine").get_json()
        self.assertEqual((len(mine["notes"]), mine["unread_count"]), (1, 1))
        self.assertEqual(mine["notes"][0]["body"], "Check the fever history.")
        self.assertEqual(len(self._get(self.coder_a, "/feedback/mine?sid=mv-s2").get_json()["notes"]), 0)
        self.assertEqual(self._get(self.coder_b, "/feedback/mine").get_json()["notes"], [])

        self._login(str(self.coder_b.user_id))
        self.assertEqual(self.client.post(f"{API}/feedback/{note_id}/read",
                                          headers=self._csrf_headers()).status_code, 404)
        self._login(str(self.coder_a.user_id))
        self.assertEqual(self.client.post(f"{API}/feedback/{note_id}/read",
                                          headers=self._csrf_headers()).status_code, 200)
        self.assertEqual(self._get(self.coder_a, "/feedback/mine").get_json()["unread_count"], 0)

        drill = self._get(self.dm, f"/coders/{self.coder_a.user_id}/cases?district={self.d1.org_unit_id}")
        notes = {c["va_sid"]: c["notes"] for c in drill.get_json()["cases"]}
        self.assertEqual(len(notes["mv-s1"]), 1)

    def test_note_refusals(self):
        self.assertEqual(self._note(self.coder_b, "mv-s1").status_code, 403)
        self.assertEqual(self._note(self.dm, "mv-s4").status_code, 404)   # not coded
        self.assertEqual(self._note(self.dm, "mv-s6").status_code, 404)   # other district
        self.assertEqual(self._note(self.dm, "mv-s1", body="  ").status_code, 400)
        self.assertEqual(self._note(self.dm, "mv-s1", body="x" * 2001).status_code, 400)
        self._login(str(self.dm.user_id))
        self.assertEqual(self.client.post(f"{API}/cases/mv-s1/notes", json={"body": "x"}).status_code, 400)

    def test_retract_rules(self):
        note_id = self._note(self.incharge, "mv-s1").get_json()["note_id"]
        for user in (self.coder_a, self.reviewer):
            self._login(str(user.user_id))
            self.assertEqual(self.client.post(f"{API}/notes/{note_id}/retract",
                                              headers=self._csrf_headers()).status_code, 404)
        self._login(str(self.dm.user_id))  # a district data manager may retract others' notes
        self.assertEqual(self.client.post(f"{API}/notes/{note_id}/retract",
                                          headers=self._csrf_headers()).status_code, 200)
        self.assertEqual(self.client.post(f"{API}/notes/{note_id}/retract",
                                          headers=self._csrf_headers()).status_code, 404)
        actions = db.session.scalars(sa.select(VaSubmissionsAuditlog.va_audit_action).where(
            VaSubmissionsAuditlog.va_sid == "mv-s1")).all()
        self.assertIn("mentor_note_retracted", actions)
        self.assertEqual(self._get(self.coder_a, "/feedback/mine").get_json()["notes"], [])
        self.assertIsNotNone(db.session.get(VaCoderFeedbackNote, uuid.UUID(note_id)))

    def test_author_and_admin_may_retract(self):
        for retractor in (self.dm, self.base_admin_user):
            with self.subTest(retractor=retractor.email):
                note_id = self._note(self.dm, "mv-s1").get_json()["note_id"]
                self._login(str(retractor.user_id))
                response = self.client.post(f"{API}/notes/{note_id}/retract", headers=self._csrf_headers())
                self.assertEqual(response.status_code, 200, response.get_json())
                note = db.session.get(VaCoderFeedbackNote, uuid.UUID(note_id))
                self.assertEqual(note.retracted_by, retractor.user_id)
