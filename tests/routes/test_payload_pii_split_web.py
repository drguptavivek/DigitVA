"""PII slice 1b part II-A, web side: revision and supervisor choice with
``PAYLOAD_PII_SPLIT_ENABLED`` on (docs/kb/pii-slice-1b.md).

The carry of a revision or a choice is the OPENED prior payload, so ABHA and
the identity answers survive; an identical revision is a no-op (compared by
``version_fingerprint`` on both sides). The fixtures are the existing suites'
own: their test methods are switched off here (set to None), only their
set-up and helpers run.
"""

import uuid

import sqlalchemy as sa

from app import db
from app.models import VaDeathRegister, VaSubmissionPayloadVersion
from app.services import payload_pii_accessor as accessor
from app.services import web_intake_service as intake_svc
from app.services.pii_field_registry import PII_FIELDS
from app.services.submission_payload_version_service import get_active_payload_version
from tests.routes import test_interview_choice_api as choice_suite
from tests.services import test_web_intake_service as intake_suite

SEALED = frozenset(PII_FIELDS)
ABHA = "12345678901234"


def _only_own_tests(cls, parent):
    """Switch off every test the fixture suite *parent* defines (unittest
    collects callables only), so the subclass runs its own."""
    for name in dir(parent):
        if name.startswith("test") and name not in cls.__dict__:
            setattr(cls, name, None)
    return cls


class _SplitOn:
    def setUp(self):
        super().setUp()
        previous = self.app.config.get("PAYLOAD_PII_SPLIT_ENABLED", False)
        self.app.config["PAYLOAD_PII_SPLIT_ENABLED"] = True
        self.addCleanup(self.app.config.__setitem__, "PAYLOAD_PII_SPLIT_ENABLED", previous)

    def _versions(self, va_sid):
        return db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissionPayloadVersion).where(
            VaSubmissionPayloadVersion.va_sid == va_sid))

    def _assert_stripped(self, version):
        self.assertIsNotNone(accessor.get_side_row(version))
        self.assertIn("Id10019", version.payload_data)  # subject present
        self.assertFalse(SEALED & set(version.payload_data))


class SplitRevisionTests(_SplitOn, intake_suite.WebIntakeServiceTests):
    def _revise(self, draft, data):
        return intake_svc.revise_submission(
            self.interviewer, draft.va_sid, reason_code=intake_svc.REVISION_REASONS[0], data=data,
            answers_sha256=None, completion={"valid": True, "issues": []}, envelope={},
        )

    def test_an_identical_revision_is_a_no_op_and_a_real_one_keeps_abha(self):
        death = self._register_death(abha_number=ABHA)
        draft, submission = self._submit_for_new_draft(death, self._completion())
        first = get_active_payload_version(submission.va_sid)
        self._assert_stripped(first)
        self.assertEqual(accessor.get_pii(first)["abha_number"], ABHA)
        # The register loses its ABHA after the submit, so no locked answer
        # brings it back: only the carry (the opened prior) keeps it, and an
        # unchanged revision stays unchanged.
        death.abha_number = None
        db.session.flush()

        reply = self._revise(draft, self._completion()["data"])

        self.assertFalse(reply["changed"])
        self.assertEqual(self._versions(submission.va_sid), 1)

        reply = self._revise(draft, self._completion(data={"Id10476": "Fever and cough."})["data"])

        self.assertTrue(reply["changed"])
        self.assertEqual(self._versions(submission.va_sid), 2)
        revised = get_active_payload_version(submission.va_sid)
        self._assert_stripped(revised)
        joined = accessor.get_full_payload(revised)
        self.assertEqual(joined["Id10476"], "Fever and cough.")
        self.assertEqual(joined["abha_number"], ABHA)
        self.assertEqual((joined["Id10017"], joined["Id10018"]), ("Asha", "Devi"))


_only_own_tests(SplitRevisionTests, intake_suite.WebIntakeServiceTests)


class SplitChoiceTests(_SplitOn, choice_suite.InterviewChoiceTests):
    def _case(self):
        death_id = super()._case()
        db.session.get(VaDeathRegister, uuid.UUID(death_id)).abha_number = ABHA
        db.session.commit()
        return death_id

    def test_a_choice_carries_the_opened_prior_and_stores_the_split(self):
        death_id, va_sid, _alice_draft, bela_draft = self._pair()
        before = get_active_payload_version(va_sid)
        self._assert_stripped(before)
        self.assertEqual(accessor.get_pii(before)["abha_number"], ABHA)
        db.session.get(VaDeathRegister, uuid.UUID(death_id)).abha_number = None  # the carry must win
        db.session.commit()

        response = self._choose(self.dm_id, death_id, bela_draft.draft_id)

        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.expire_all()
        version = get_active_payload_version(va_sid)
        self.assertNotEqual(version.payload_version_id, before.payload_version_id)
        self._assert_stripped(version)
        joined = accessor.get_full_payload(version)
        self.assertEqual(joined["Id10017"], "Meena")
        self.assertEqual(joined["abha_number"], ABHA)
        self.assertNotIn("Meena", repr(version.payload_data))


_only_own_tests(SplitChoiceTests, choice_suite.InterviewChoiceTests)
