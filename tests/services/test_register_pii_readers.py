"""PII slice 2, T2: the readers of the sealed register (docs/kb/pii-slice-2.md).

Each reader is run on a plaintext row and again on the same row after
``seal_register_pii`` (plaintext columns NULL); the outputs must match. Fixtures
(project WIT01, interviewer) come from the web intake service tests.
"""
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import VaDeathRegister, VaSubmissionPayloadVersion
from app.services import register_pii_accessor as accessor
from app.services import web_intake_service as intake_svc
from app.utils import pii_crypto as pc
from tests.services import test_web_intake_service as intake_tests

PII = {
    "deceased_name": "Asha Devi", "father_name": "Ram Lal", "mother_name": "Sita Devi",
    "informant_name": "Mohan", "informant_phone": "9876543210", "informant_phone_2": "9123456780",
    "abha_number": "12345678901234", "abha_address": "asha@abdm", "address": "12 Gandhi Road, Pune",
    "address_house_street": "12 Gandhi Road", "address_village_ward": "Ward 4",
    "address_landmark": "Near the temple", "place_of_death": "Home", "remarks": "Remark text",
    "latitude": 18.5204, "longitude": 73.8567, "accuracy_m": 12.5,
}


class RegisterReadersTests(intake_tests.WebIntakeServiceTests):
    def _row(self, n: int = 1, **over) -> VaDeathRegister:
        values = {
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "death_number": 700 + n,
            "unique_id": f"RRD-{uuid.uuid4().hex[:10]}", "deceased_sex": "female", "age_years": 62,
            "date_of_death": date.today() - timedelta(days=3), "status": "registered", "source": "register",
            "registered_by": self.interviewer.user_id, **PII, "captured_at": datetime.now(UTC),
        }
        values.update(over)
        death = VaDeathRegister(**values)
        db.session.add(death)
        db.session.flush()
        return death

    def _same_sealed(self, read, **over):
        """``read(death)`` on a plaintext row, then on the same row sealed."""
        death = self._row(**over)
        before = read(death)
        accessor.seal_register_pii(death)
        db.session.flush()
        self.assertIsNone(death.deceased_name)  # present-before-absent: the plaintext is really gone
        after = read(death)
        # Sealing touches updated_at; nothing else may differ.
        before.pop("updated_at", None), after.pop("updated_at", None)
        return before, after

    def _other_user(self):
        return self._get_or_make_user("rrd.other@test.local", "WebIntake123").user_id

    def _opened_fields(self, call):
        """The ``only`` field sets of every blob open ``call()`` makes."""
        with mock.patch.object(pc, "open_record", wraps=pc.open_record) as spy:
            call()
        return [set(c.kwargs["only"]) if c.kwargs.get("only") is not None else None for c in spy.call_args_list]

    # -- serialisers ---------------------------------------------------------

    def test_serialize_death_matches_and_opens_the_fix_only_when_shown(self):
        for show_gps in (True, False):
            before, after = self._same_sealed(lambda d: intake_svc.serialize_death(d, show_gps=show_gps))
            self.assertEqual(before, after)
            self.assertEqual(after["deceased_name"], "Asha Devi")
            self.assertEqual("latitude" in after, show_gps)
        death = self._row()
        accessor.seal_register_pii(death)
        opens = self._opened_fields(lambda: intake_svc.serialize_death(death))
        self.assertEqual(len(opens), 1)
        self.assertNotIn("location", opens[0])

    def test_worklist_row_matches_takes_phone_presence_from_flags_and_opens_only_the_name(self):
        def read(death):
            return intake_svc.serialize_worklist_row(self.interviewer, death, None, None)
        before, after = self._same_sealed(read, informant_phone_2=None)
        self.assertEqual(before, after)
        self.assertEqual(after["deceased_name"], "Asha Devi")
        self.assertIs(after["has_informant_phone"], True)
        self.assertIs(after["has_informant_phone_2"], False)
        for key in ("informant_phone", "informant_name", "address"):
            self.assertNotIn(key, after)
        death = self._row()
        accessor.seal_register_pii(death)
        self.assertEqual(self._opened_fields(lambda: read(death)), [{"deceased_name"}])
        # The flags are the answer: a flag edit shows even though the bidx is unchanged.
        death.has_informant_phone = False
        self.assertIs(read(death)["has_informant_phone"], False)

    def test_case_detail_matches_and_never_opens_abha_parents_or_a_hidden_fix(self):
        def read(death):
            return intake_svc.serialize_case_detail(self.interviewer, death, None, None)
        before, after = self._same_sealed(read, registered_by=self._other_user())
        self.assertEqual(before, after)
        self.assertEqual(after["informant"], {"name": "Mohan", "phone": "9876543210", "phone_2": "9123456780"})
        self.assertEqual(after["household_address"]["landmark"], "Near the temple")
        self.assertEqual(after["remarks"], "Remark text")
        death = self._row(registered_by=self._other_user())
        accessor.seal_register_pii(death)
        (fields,) = self._opened_fields(lambda: read(death))
        self.assertTrue({"deceased_name", "informant_name", "remarks"} <= fields)
        self.assertFalse(fields & {"abha_number", "abha_address", "father_name", "mother_name"})
        # Registered by the caller: the fix is shown and opened.
        mine = self._row(2)
        accessor.seal_register_pii(mine)
        (fields,) = self._opened_fields(lambda: read(mine))
        self.assertIn("location", fields)
        self.assertEqual(read(mine)["household_address"]["latitude"], 18.5204)

    def test_supervised_row_matches(self):
        def read(death):
            return intake_svc.serialize_supervised_row(self.interviewer, death, "Unit", "Reg", "Start")
        before, after = self._same_sealed(read)
        self.assertEqual(before, after)
        self.assertEqual(after["deceased_name"], "Asha Devi")
        self.assertNotIn("has_informant_phone", after)

    def test_draft_list_names_match_with_a_constant_number_of_queries(self):
        def drafts_for(count):
            drafts = []
            for n in range(count):
                death = self._row(n + 1)
                accessor.seal_register_pii(death)
                drafts.append(intake_svc.start_draft(
                    self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=death.death_id))
            return drafts
        seen = []
        record = lambda conn, cur, stmt, *a: seen.append(stmt)  # noqa: E731
        small = drafts_for(2)
        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            rows = intake_svc.serialize_drafts(small)
            two = len(seen)
            seen.clear()
            more = drafts_for(3)
            seen.clear()
            with mock.patch.object(pc, "open_record", wraps=pc.open_record) as spy:
                big = intake_svc.serialize_drafts(small + more)
            five = len(seen)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)
        self.assertEqual({r["deceased_name"] for r in rows}, {"Asha Devi"})
        self.assertEqual(len(big), 5)
        self.assertEqual((two, spy.call_count), (five, 5))

    # -- prefill and the interview ------------------------------------------------

    def test_prefill_matches_for_a_sealed_row(self):
        def read(death):
            return intake_svc._prefill_from_death(death, self.interviewer, None)
        before, after = self._same_sealed(read)
        self.assertEqual(before, after)
        self.assertEqual(after["deceased"]["givenNames"], "Asha")
        self.assertEqual(after["deceased"]["surname"], "Devi")
        self.assertEqual(after["answers"]["abha_number"], "12345678901234")
        self.assertEqual(after["answers"]["Id10061"], "Ram Lal")
        self.assertIn("Gandhi Road", after["answers"]["Id10055"])
        self.assertIn("abha_number", after["lockedQuestionNames"])

    def test_prefill_opens_the_blob_once_a_row(self):
        death = self._row()
        accessor.seal_register_pii(death)
        self.assertEqual(len(self._opened_fields(
            lambda: intake_svc._prefill_from_death(death, self.interviewer, None))), 1)

    def test_start_draft_and_locked_answers_work_on_a_sealed_case(self):
        death = self._row()
        accessor.seal_register_pii(death)
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=death.death_id)
        self.assertEqual(draft.prefill["deceased"]["givenNames"], "Asha")
        self.assertEqual(intake_svc._draft_locked_answers(draft)["abha_number"], "12345678901234")

    def test_submit_carries_abha_into_the_payload_of_a_sealed_case(self):
        previous = self.app.config.get("REGISTER_PII_SPLIT_ENABLED", False)
        self.app.config["REGISTER_PII_SPLIT_ENABLED"] = True  # the identity sync re-seals the row
        self.addCleanup(self.app.config.__setitem__, "REGISTER_PII_SPLIT_ENABLED", previous)
        death = self._row()
        accessor.seal_register_pii(death)
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=death.death_id)
        submission = intake_svc.submit_draft(draft, self.interviewer, completion=self._completion())
        payload = db.session.get(VaSubmissionPayloadVersion, submission.active_payload_version_id).payload_data
        self.assertEqual(payload["abha_number"], "12345678901234")
        self.assertEqual(death.status, "submitted")

    # -- worklist page --------------------------------------------------------------

    def test_worklist_page_opens_once_a_row_for_any_page_size(self):
        def page(count):
            for n in range(count):
                accessor.seal_register_pii(self._row(100 + n, registered_by=self.interviewer.user_id))
            # The duplicate check opens names of its own (test_register_duplicates).
            with mock.patch.object(intake_svc.register_duplicate_service, "possible_duplicate_rows", return_value=[]), \
                    mock.patch.object(pc, "open_record", wraps=pc.open_record) as spy:
                body = intake_svc.worklist_page(self.interviewer, {"limit": "50"})
            return body, spy.call_count
        body, opens = page(2)
        names = [c["deceased_name"] for c in body["cases"]]
        self.assertTrue(names)  # present before absent
        self.assertTrue(all(n == "Asha Devi" for n in names))
        self.assertEqual(opens, len(names))
        body, opens = page(3)
        self.assertEqual(opens, len(body["cases"]))


# The inherited intake tests run in their own module.
for _name in [n for n in dir(intake_tests.WebIntakeServiceTests) if n.startswith("test_")]:
    setattr(RegisterReadersTests, _name, None)
