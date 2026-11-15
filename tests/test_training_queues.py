"""Training session types, phase 2 (docs/policy/training-session-types.md,
"Coding in a self-coding session"): self-coding per session through explicit
grants, the standard and own queues (standard by default on every training
pool, count and pick), the pick set check from data, the own-queue language
exemption and the "X of Y" counts."""

from datetime import datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MasTrainingSession,
    VaFinalAssessments,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaWebIntakeDraft,
)
from app.services import training_demo_service as svc
from app.services import web_intake_service
from app.services.coder_workflow_service import (
    AllocationError,
    allocate_own_case,
    allocate_pick_form,
)
from tests.test_training_session_types import SessionTypeTestBase

API = "/api/v1/coding"


class QueueTestBase(SessionTypeTestBase):
    """A self-coding session with one self-coder (their ten copies) who sent one
    Bengali interview on their slot unit, and a coder session with one coder."""

    def setUp(self):
        super().setUp()
        self.self_code = self._typed("self_coding", slots=2, name="SC")["session_code"]
        self.coder_code = self._typed("coder", slots=1, name="C")["session_code"]
        self.self_coder, self.coder = self._user("qself"), self._user("qcoder")
        self._add(self.self_code, self.self_coder)
        self._add(self.coder_code, self.coder)
        self.slot_unit = svc._unit_by_code(svc.slot_unit_code(self.self_code, 1))
        self.standard = {c.va_sid for c in self._cases(self.self_code)}
        self.own_sid = self._interview("trn-own-1", self.self_coder, self.slot_unit.org_unit_id)
        db.session.commit()

    def _interview(self, sid, owner, org_unit_id, language="bengali"):
        """A sent TRN01 interview, ready for coding; *owner* None leaves it without a draft."""
        form = svc._web_form()
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=form.form_id, va_data_collector="Trainee", va_uniqueid_masked=sid,
            va_consent="yes", va_narration_language=language, va_deceased_age=40, va_deceased_gender="male",
            va_catcount={}, va_category_list=[], va_submission_date=datetime(2026, 11, 1),
            org_unit_id=org_unit_id, org_unit_resolution="manual",
        ))
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(va_sid=sid, workflow_state="ready_for_coding", workflow_reason="test"))
        if owner is not None:
            db.session.add(VaWebIntakeDraft(
                project_id=form.project_id, site_id=form.site_id, form_id=form.form_id, user_id=owner.user_id,
                unique_id=sid, meta={"interviewOutcome": "completed"}, prefill={}, status="submitted", va_sid=sid,
            ))
        db.session.flush()
        return sid

    def _available(self, query=""):
        return self.client.get(f"{API}/available?limit=200&training=1{query}")


class QueueApiTests(QueueTestBase):
    def test_standard_is_the_default_and_own_holds_only_the_own_interview(self):
        self._login(str(self.self_coder.user_id))
        own = self._available("&queue=own")
        self.assertEqual(own.status_code, 200, own.get_json())
        self.assertEqual({f["va_sid"] for f in own.get_json()["forms"]}, {self.own_sid})  # Bengali: exempt
        default = {f["va_sid"] for f in self._available().get_json()["forms"]}
        self.assertEqual(default, self.standard)
        self.assertNotIn(self.own_sid, default)
        self.assertEqual(default, {f["va_sid"] for f in self._available("&queue=standard").get_json()["forms"]})
        stats = self.client.get(f"{API}/stats?training=1").get_json()
        self.assertEqual(stats["pick_ready"], 10)
        self.assertEqual(stats["training_queues"],
                         {"own": {"coded": 0, "total": 1}, "standard": {"coded": 0, "total": 10}})
        self.assertEqual(self.client.get(f"{API}/stats?training=1&queue=own").get_json()["pick_ready"], 1)

    def test_coded_counts_follow_active_final_assessments(self):
        sid = sorted(self.standard)[0]
        db.session.add(VaFinalAssessments(va_sid=sid, va_finassess_by=self.self_coder.user_id,
                                          va_conclusive_cod="J18.9"))
        db.session.commit()
        self._login(str(self.self_coder.user_id))
        queues = self.client.get(f"{API}/stats?training=1").get_json()["training_queues"]
        self.assertEqual(queues["standard"], {"coded": 1, "total": 10})

    def test_own_queue_needs_a_self_coding_session_and_bad_values_are_400(self):
        self._login(str(self.coder.user_id))
        self.assertEqual(self._available().status_code, 200)
        refused = self._available("&queue=own")
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (403, "forbidden"))
        self.assertIsNone(self.client.get(f"{API}/stats?training=1").get_json()["training_queues"]["own"])
        bad = self._available("&queue=mine")
        self.assertEqual((bad.status_code, bad.get_json()["code"]), (400, "invalid_request"))
        # the real side ignores queue: no new codes for non-training requests
        self.assertEqual(self.client.get(f"{API}/available?limit=20&queue=mine").status_code, 200)
        self.assertNotIn("training_queues", self.client.get(f"{API}/stats").get_json())

    def test_legacy_coder_still_sees_their_slot_as_the_standard_set(self):
        legacy = self._user("qlegacy")
        svc.add_participant("S001", legacy.email, "coder", self.admin)
        self._login(str(legacy.user_id))
        forms = {f["va_sid"] for f in self._available().get_json()["forms"]}
        self.assertEqual(forms, self._session_sids()[1])


class PickAndCodeNowTests(QueueTestBase):
    def test_pick_refuses_a_case_outside_the_users_set(self):
        stray = self._interview("trn-stray-1", None, self.slot_unit.org_unit_id, language="english")
        db.session.commit()
        self.assertIn(stray, set(db.session.scalars(  # in the coder's scope (their slot unit)
            sa.select(VaSubmissions.va_sid).where(VaSubmissions.org_unit_id == self.slot_unit.org_unit_id))))
        with self.assertRaises(AllocationError) as ctx:
            allocate_pick_form(self.self_coder, stray)
        self.assertEqual((ctx.exception.status_code, ctx.exception.code), (403, "not_in_your_training_set"))
        self.assertEqual(allocate_pick_form(self.self_coder, sorted(self.standard)[0]).actiontype, "vapickcoding")

    def test_own_interview_is_codeable_in_its_language_by_pick_and_code_now(self):
        self.assertNotIn("bengali", self.self_coder.vacode_language)
        result = allocate_own_case(self.self_coder, self.own_sid)
        self.assertEqual((result.va_sid, result.actiontype), (self.own_sid, "vapickcoding"))

    def test_own_pick_without_own_case_is_allowed_too(self):
        self.assertEqual(allocate_pick_form(self.self_coder, self.own_sid).va_sid, self.own_sid)

    def test_own_interview_is_not_codeable_once_the_session_closes(self):
        svc.close_training_session(self.self_code, self.admin)
        self.assertEqual(svc.training_self_coding_ids(self.self_coder.user_id), frozenset())
        with self.assertRaises(AllocationError):
            allocate_own_case(self.self_coder, self.own_sid)

    def test_code_now_is_unit_aware(self):
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.va_sid == self.own_sid))
        self.assertIn("TRN01", web_intake_service.self_coding_project_ids(self.self_coder))
        self.assertTrue(web_intake_service.can_code_now(self.self_coder, draft))
        root = db.session.scalar(sa.select(MasTrainingSession.org_unit_id).where(
            MasTrainingSession.session_code == self.self_code))
        db.session.get(VaSubmissions, self.own_sid).org_unit_id = root
        db.session.flush()
        self.assertFalse(web_intake_service.can_code_now(self.self_coder, draft))
        self.assertNotIn("TRN01", web_intake_service.self_coding_project_ids(self.coder))

    def test_a_coder_session_coder_never_gets_an_own_exemption(self):
        unit = svc._unit_by_code(svc.slot_unit_code(self.coder_code, 1))
        sid = self._interview("trn-coder-own", self.coder, unit.org_unit_id, language="english")
        db.session.commit()
        with self.assertRaises(AllocationError) as ctx:
            allocate_own_case(self.coder, sid)
        self.assertEqual(ctx.exception.code, "forbidden")
        with self.assertRaises(AllocationError) as ctx:
            allocate_pick_form(self.coder, sid)
        self.assertEqual(ctx.exception.code, "not_in_your_training_set")


class OwnExemptionScopeTests(QueueTestBase):
    def test_only_drafts_on_a_self_coding_unit_are_exempt(self):
        """A self-coder who is also a legacy S001 coder: their own draft on the
        S001 slot stays excluded; the one on their self-coding unit does not."""
        slot = svc.add_participant("S001", self.self_coder.email, "coder", self.admin)["coder_slot"]
        legacy_sids = sorted(self._session_sids()[slot])
        drafted, plain = legacy_sids[0], legacy_sids[1]
        form = svc._web_form()
        db.session.add(VaWebIntakeDraft(
            project_id=form.project_id, site_id=form.site_id, form_id=form.form_id, user_id=self.self_coder.user_id,
            unique_id=drafted, meta={}, prefill={}, status="submitted", va_sid=drafted,
        ))
        english_own = self._interview("trn-own-en", self.self_coder, self.slot_unit.org_unit_id, language="english")
        db.session.commit()
        picks = self._pick_list(self.self_coder)  # no request scope: no queue applies
        self.assertIn(plain, picks)
        self.assertIn(english_own, picks)
        self.assertNotIn(drafted, picks)


class OwnInterviewNameTests(QueueTestBase):
    def test_coding_names_of_an_own_training_interview(self):
        """Recorded decision (coding-workflow-state-machine.md, "Training
        queues"): ``coding_names`` is unchanged for training."""
        import uuid
        from datetime import date

        from app.models import VaDeathRegister
        from app.services.case_list_service import coding_names

        form = svc._web_form()
        db.session.add(VaDeathRegister(
            project_id=form.project_id, site_id=form.site_id, org_unit_id=self.slot_unit.org_unit_id,
            death_number=uuid.uuid4().int % 10**9, unique_id=f"OWN-{uuid.uuid4().hex[:8]}",
            deceased_name="Made Up Name", deceased_sex="male", date_of_death=date(2026, 1, 1),
            registered_by=self.self_coder.user_id, source="register", status="registered", va_sid=self.own_sid,
        ))
        db.session.commit()
        self.assertEqual(coding_names(self.self_coder, [self.own_sid]), {self.own_sid: "Made Up Name"})


class RandomQueueTests(QueueTestBase):
    def _random(self, query=""):
        return self.client.post(f"{API}/allocation?training=1{query}", json={}, headers=self._csrf_headers())

    def test_random_allocation_takes_the_queue_standard_by_default(self):
        from app.models import VaProjectMaster

        db.session.get(VaProjectMaster, "TRN01").coding_intake_mode = "random_form_allocation"
        db.session.commit()
        self._login(str(self.self_coder.user_id))
        own = self._random("&queue=own")
        self.assertEqual(own.status_code, 201, own.get_json())
        self.assertEqual(own.get_json()["va_sid"], self.own_sid)
        self.assertEqual(self.client.post(f"{API}/allocation/release?training=1",
                                          headers=self._csrf_headers()).status_code, 200)
        standard = self._random()
        self.assertEqual(standard.status_code, 201, standard.get_json())
        self.assertIn(standard.get_json()["va_sid"], self.standard)
