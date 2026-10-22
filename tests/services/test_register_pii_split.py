"""PII slice 2, T1: the sealed register (docs/kb/pii-slice-2.md).

``app/services/register_pii_accessor.py``, the model's presence-flag listener
and CHECKs, and the writers behind ``REGISTER_PII_SPLIT_ENABLED``. Fixtures
(project WIT01, interviewer) come from the web intake service tests; their own
tests are not repeated here.
"""
import json
import unittest
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import MapCaseTransition, VaDeathRegister
from app.services import case_transition_service as cases
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


class RegisterPiiSplitTests(intake_tests.WebIntakeServiceTests):
    """Reuses the web intake fixtures; the inherited tests are switched off
    below (they run in their own module)."""

    def _flag(self, on: bool):
        previous = self.app.config.get("REGISTER_PII_SPLIT_ENABLED", False)
        self.app.config["REGISTER_PII_SPLIT_ENABLED"] = on
        self.addCleanup(self.app.config.__setitem__, "REGISTER_PII_SPLIT_ENABLED", previous)

    def _plain_row(self, n: int = 1, **over) -> VaDeathRegister:
        """A flag-off row built with plaintext, added and flushed."""
        values = {
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "death_number": 900 + n,
            "unique_id": f"RPS-{uuid.uuid4().hex[:10]}", "deceased_sex": "female",
            "date_of_death": date.today() - timedelta(days=3), "status": "registered", "source": "register",
            "registered_by": self.interviewer.user_id, **PII,
            "captured_at": datetime.now(UTC),
        }
        values.update(over)
        death = VaDeathRegister(**values)
        db.session.add(death)
        db.session.flush()
        return death

    def _db_row(self, death):
        return db.session.execute(
            sa.text("SELECT * FROM va_death_register WHERE death_id = :i"), {"i": death.death_id}
        ).mappings().one()

    # -- seal / open ----------------------------------------------------

    def test_round_trip_of_every_field_and_location(self):
        self._flag(True)
        death = self._plain_row()
        accessor.seal_register_pii(death)
        db.session.flush()
        row = self._db_row(death)
        for name in accessor.SEALED_ATTRS:
            self.assertIsNone(row[name], name)
        self.assertEqual(set(row["pii_sealed"]), set(accessor.SEALED_FIELDS))
        self.assertIsNotNone(row["pii_sealed_at"])
        self.assertEqual(row["pii_key_id"], pc.current_key_id())
        self.assertEqual(row["pii_blind_key_id"], pc.blind_key_id())
        stored = json.dumps(row["pii_sealed"]) + row["pii_dek_wrapped"]
        for plain in ("Asha", "9876543210", "Gandhi", "18.52", "asha@abdm"):
            self.assertNotIn(plain, stored)
        opened = accessor.open_register_pii([death])[death.death_id]
        self.assertEqual(opened, PII)
        # Non-sealed columns stay plaintext.
        self.assertEqual(row["deceased_sex"], "female")
        self.assertIsNotNone(row["captured_at"])

    def test_unsealed_rows_read_as_their_plaintext_and_only_limits_the_fields(self):
        death = self._plain_row()
        self.assertEqual(accessor.open_register_pii([death])[death.death_id], PII)
        self.assertEqual(
            accessor.open_register_pii([death], only=("remarks", "latitude"))[death.death_id],
            {"remarks": "Remark text", "latitude": 18.5204},
        )

    def test_a_moved_ciphertext_or_row_id_fails_to_open(self):
        self._flag(True)
        first, second = self._plain_row(1), self._plain_row(2, deceased_name="Other Name")
        accessor.seal_register_pii(first)
        accessor.seal_register_pii(second)
        # A field's ciphertext copied into another column of the same row.
        moved = dict(first.pii_sealed, remarks=first.pii_sealed["address"])
        first.pii_sealed = moved
        with self.assertRaises(pc.PiiCryptoError):
            accessor.open_register_pii([first])
        # A whole blob copied to another row.
        second.pii_sealed, second.pii_dek_wrapped = (
            dict(first.pii_sealed, remarks=second.pii_sealed["remarks"]), first.pii_dek_wrapped)
        with self.assertRaises(pc.PiiCryptoError) as raised:
            accessor.open_register_pii([second])
        self.assertNotIn("Asha", str(raised.exception))

    def test_one_dek_per_write(self):
        self._flag(True)
        death = self._plain_row()
        with mock.patch.object(pc, "wrap_dek", wraps=pc.wrap_dek) as wrap:
            accessor.seal_register_pii(death)
            self.assertEqual(wrap.call_count, 1)
            first_dek = death.pii_dek_wrapped
            accessor.write_fields(death, {"remarks": "changed", "address": "elsewhere", "date_of_birth": None})
            self.assertEqual(wrap.call_count, 2)
        self.assertNotEqual(death.pii_dek_wrapped, first_dek)
        opened = accessor.current_values(death)
        self.assertEqual((opened["remarks"], opened["address"]), ("changed", "elsewhere"))
        self.assertEqual(opened["deceased_name"], "Asha Devi")

    # -- presence flags and CHECKs -----------------------------------------

    def test_flag_off_writer_keeps_the_flags_right(self):
        death = self._plain_row()
        row = self._db_row(death)
        self.assertEqual(
            (row["has_deceased_name"], row["has_informant_phone"], row["has_informant_phone_2"], row["has_location"]),
            (True, True, True, True),
        )
        death.informant_phone_2 = None
        death.latitude = death.longitude = death.accuracy_m = None
        death.captured_at = None
        db.session.flush()
        row = self._db_row(death)
        self.assertEqual((row["has_informant_phone_2"], row["has_location"]), (False, False))
        bare = self._plain_row(2, **{k: None for k in PII}, status="draft_identity", source="direct", captured_at=None)
        row = self._db_row(bare)
        self.assertEqual((row["has_deceased_name"], row["has_informant_phone"], row["has_location"]),
                         (False, False, False))

    def test_a_stripped_row_can_be_inserted_and_updated_under_the_checks(self):
        self._flag(True)
        death = self._plain_row()
        accessor.seal_register_pii(death)
        db.session.flush()
        # An update of a plain column on the stripped row: the listener leaves the flags alone.
        death.next_visit_at = datetime.now(UTC) + timedelta(days=2)
        db.session.flush()
        row = self._db_row(death)
        self.assertTrue(row["has_deceased_name"] and row["has_location"])
        # A sealed update, including dropping the fix.
        accessor.write_fields(death, {"latitude": None, "longitude": None, "accuracy_m": None})
        death.captured_at = None
        db.session.flush()
        row = self._db_row(death)
        self.assertEqual((row["has_location"], row["captured_at"], row["has_deceased_name"]), (False, None, True))
        self.assertNotIn("location", row["pii_sealed"])
        # The checks still bite: a registered row with no name at all.
        with self.assertRaises(sa.exc.IntegrityError):
            with db.session.begin_nested():
                accessor.write_fields(death, {"deceased_name": None})
                db.session.flush()

    def test_identity_complete_is_unchanged_by_the_seal(self):
        self._flag(True)
        death = self._plain_row()
        self.assertTrue(cases.identity_complete(death))
        accessor.seal_register_pii(death)
        self.assertIsNone(death.deceased_name)
        self.assertTrue(cases.identity_complete(death))
        accessor.write_fields(death, {"deceased_name": None})
        self.assertFalse(cases.identity_complete(death))
        nameless = VaDeathRegister(date_of_death=date.today(), deceased_sex="male")
        self.assertFalse(cases.identity_complete(nameless))

    # -- flag off ---------------------------------------------------------

    def test_flag_off_writer_refuses_a_sealed_row_but_reads_it(self):
        self._flag(True)
        death = self._plain_row()
        accessor.seal_register_pii(death)
        db.session.flush()
        self._flag(False)
        with self.assertRaises(accessor.RegisterSplitStateError):
            accessor.write_fields(death, {"remarks": "x"})
        with self.assertRaises(accessor.RegisterSplitStateError):
            intake_svc.update_death(self.interviewer, death.death_id, {"remarks": "x"})
        self.assertEqual(accessor.current_values(death)["remarks"], "Remark text")
        accessor.write_fields(death, {})  # nothing to write is not a write
        self.assertEqual(accessor.current_values(death)["deceased_name"], "Asha Devi")

    def test_flag_off_writer_lets_non_sealed_attributes_through_on_a_sealed_row(self):
        self._flag(True)
        death = self._plain_row()
        accessor.seal_register_pii(death)
        db.session.flush()
        self._flag(False)
        accessor.write_fields(death, {"age_years": 70, "date_of_birth": date(1950, 1, 1)})
        db.session.flush()
        self.assertEqual((death.age_years, death.date_of_birth), (70, date(1950, 1, 1)))
        # A mixed write is refused whole: nothing is set.
        with self.assertRaises(accessor.RegisterSplitStateError):
            accessor.write_fields(death, {"age_years": 71, "remarks": "x"})
        self.assertEqual(death.age_years, 70)
        self.assertEqual(accessor.current_values(death)["remarks"], "Remark text")

    def test_flag_on_non_sealed_update_of_an_unsealed_legacy_row_keeps_the_flags(self):
        self._flag(True)
        death = self._plain_row()  # pre-backfill: plaintext, no blob
        accessor.write_fields(death, {"age_years": 70})
        db.session.flush()
        row = self._db_row(death)
        self.assertIsNone(row["pii_sealed"])
        self.assertEqual(row["age_years"], 70)
        self.assertEqual(row["deceased_name"], "Asha Devi")
        self.assertTrue(
            row["has_deceased_name"] and row["has_informant_phone"] and row["has_informant_phone_2"]
            and row["has_location"]
        )

    def test_core_insert_sets_the_presence_flags_from_the_columns(self):
        """A Core insert skips the mapper listener: the column default must
        get the flags right, including a row with a captured fix."""
        def insert(**over):
            values = {
                "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "death_number": 970,
                "unique_id": f"RPS-{uuid.uuid4().hex[:10]}", "deceased_sex": "female",
                "date_of_death": date.today(), "status": "registered", "source": "register",
                "registered_by": self.interviewer.user_id, **over,
            }
            return db.session.execute(
                sa.insert(VaDeathRegister).values(**values).returning(
                    VaDeathRegister.has_deceased_name, VaDeathRegister.has_informant_phone,
                    VaDeathRegister.has_informant_phone_2, VaDeathRegister.has_location)
            ).one()

        full = insert(deceased_name="Asha", informant_phone="9876543210", informant_phone_2="9123456780",
                      latitude=18.5, longitude=73.8, captured_at=datetime.now(UTC))
        self.assertEqual(tuple(full), (True, True, True, True))
        one = insert(deceased_name="Asha", informant_phone_2="9123456780", death_number=971)
        self.assertEqual(tuple(one), (True, False, True, False))

    def test_flag_off_leaves_new_rows_in_plaintext(self):
        death = self._register_death(remarks="plain")
        row = self._db_row(death)
        self.assertEqual((row["deceased_name"], row["remarks"], row["pii_sealed"]), ("Asha Devi", "plain", None))
        accessor.seal_new_row(death)
        self.assertIsNone(death.pii_sealed)

    # -- blind indexes -----------------------------------------------------

    def test_phone_and_abha_blind_indexes(self):
        self._flag(True)
        death = self._plain_row(informant_phone="9876543210", informant_phone_2="+91 98765-43210")
        accessor.seal_register_pii(death)
        self.assertEqual(death.informant_phone_bidx, death.informant_phone_2_bidx)
        self.assertEqual(death.informant_phone_bidx, pc.class_index("phone", "9876543210"))
        self.assertEqual(accessor.phone_bidx("098765 43210"), death.informant_phone_bidx)
        self.assertIsNone(accessor.phone_bidx("call after 5"))
        self.assertEqual(death.abha_number_bidx, pc.class_index("abha_number", "12345678901234"))
        self.assertEqual(accessor.abha_number_bidx("12-3456-7890-1234"), death.abha_number_bidx)
        self.assertEqual(death.abha_address_bidx, accessor.abha_address_bidx(" ASHA@abdm "))
        self.assertEqual(death.pii_sealed is not None and death.pii_blind_key_id, pc.blind_key_id())
        # Clearing a value clears its index and flag.
        accessor.write_fields(death, {"informant_phone": None, "abha_number": None})
        self.assertEqual((death.informant_phone_bidx, death.abha_number_bidx), (None, None))
        self.assertFalse(death.has_informant_phone)
        self.assertTrue(death.has_informant_phone_2)

    # -- writers ----------------------------------------------------------

    def test_register_death_seals_and_update_death_audits_sealed_values_only(self):
        self._flag(True)
        death = self._register_death(
            informant_phone="9876543210", remarks="first", latitude="18.5", longitude="73.8")
        row = self._db_row(death)
        self.assertEqual((row["deceased_name"], row["informant_phone"], row["remarks"], row["latitude"]),
                         (None, None, None, None))
        self.assertEqual((row["status"], row["has_deceased_name"], row["has_location"]), ("registered", True, True))
        self.assertIsNotNone(row["captured_at"])
        created = db.session.scalars(
            sa.select(MapCaseTransition).where(MapCaseTransition.death_id == death.death_id)).all()
        self.assertEqual([t.action for t in created], ["created"])

        intake_svc.update_death(
            self.interviewer, death.death_id, {"remarks": "second", "deceased_name": "Asha D", "age_years": 63})
        db.session.flush()
        self.assertEqual(accessor.current_values(death)["remarks"], "second")
        self.assertEqual(accessor.current_values(death)["informant_phone"], "9876543210")
        audit = db.session.scalars(
            sa.select(MapCaseTransition).where(
                MapCaseTransition.death_id == death.death_id, MapCaseTransition.action == "details_edited")
        ).one()
        self.assertIsNotNone(audit.changes_dek_wrapped)
        self.assertEqual(audit.changes_key_id, pc.current_key_id())
        stored = json.dumps(audit.changes)
        for plain in ("first", "second", "Asha"):
            self.assertNotIn(plain, stored)
        self.assertEqual(audit.changes["age_years"], {"old": 62, "new": 63})  # not sealed, stays plain
        opened = accessor.open_audit_changes(audit)
        self.assertEqual(opened["remarks"], {"old": "first", "new": "second"})
        self.assertEqual(opened["deceased_name"], {"old": "Asha Devi", "new": "Asha D"})
        # The audit ciphertext is bound to its transition id.
        other = MapCaseTransition(transition_id=uuid.uuid4(), changes=audit.changes,
                                  changes_dek_wrapped=audit.changes_dek_wrapped)
        with self.assertRaises(pc.PiiCryptoError):
            accessor.open_audit_changes(other)

    def test_flag_off_audit_rows_stay_plain(self):
        death = self._register_death(remarks="first")
        intake_svc.update_death(self.interviewer, death.death_id, {"remarks": "second"})
        audit = db.session.scalars(
            sa.select(MapCaseTransition).where(
                MapCaseTransition.death_id == death.death_id, MapCaseTransition.action == "details_edited")
        ).one()
        self.assertEqual(audit.changes["remarks"], {"old": "first", "new": "second"})
        self.assertIsNone(audit.changes_dek_wrapped)
        self.assertEqual(accessor.open_audit_changes(audit), audit.changes)

    def test_interview_identity_copy_re_seals_and_audits(self):
        self._flag(True)
        death = cases.open_case(
            VaDeathRegister(
                project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_number=950,
                unique_id=f"RPS-{uuid.uuid4().hex[:10]}", source="direct", registered_by=self.interviewer.user_id,
                started_by_user_id=self.interviewer.user_id),
            actor=self.interviewer)
        self.assertEqual(death.status, "draft_identity")
        answers = {"Id10017": "Asha", "Id10018": "Devi", "Id10019": "female",
                   "Id10023": (date.today() - timedelta(days=3)).isoformat()}
        intake_svc._sync_case_identity(death, answers, self.interviewer)
        db.session.flush()
        self.assertEqual(death.status, "in_progress")
        self.assertIsNone(death.deceased_name)
        self.assertEqual(accessor.current_values(death)["deceased_name"], "Asha Devi")
        # A later interview replaces the name; the old value is audited, sealed.
        intake_svc._sync_case_identity(death, dict(answers, Id10017="Asha K"), self.interviewer)
        db.session.flush()
        audit = db.session.scalars(
            sa.select(MapCaseTransition).where(
                MapCaseTransition.death_id == death.death_id,
                MapCaseTransition.action == intake_svc.IDENTITY_FROM_INTERVIEW)).one()
        self.assertEqual(accessor.open_audit_changes(audit)["deceased_name"],
                         {"old": "Asha Devi", "new": "Asha K Devi"})
        self.assertNotIn("Asha", json.dumps(audit.changes))

    def test_odk_case_insert_seals(self):
        from app.services import odk_case_service

        self._flag(True)
        identity = {"deceased_name": "Odk Person", "deceased_sex": "male", "date_of_death": date.today()}
        with mock.patch.object(odk_case_service, "_allocate_unique_id", return_value=(951, "RPS-ODK1")):
            case = odk_case_service._insert_case(
                va_sid=None, org_unit_id=None, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                payload={}, identity=identity)
        self.assertIsNone(self._db_row(case)["deceased_name"])
        self.assertEqual(accessor.current_values(case)["deceased_name"], "Odk Person")

    def test_national_id_sweep_refuses_sealed_register_rows(self):
        from app.services import national_id_sweep_service as sweep

        self._flag(True)
        death = self._plain_row()
        accessor.seal_register_pii(death)
        db.session.flush()
        with self.assertRaises(sweep.SweepRefused) as raised:
            sweep.sweep_national_ids(tables=("va_death_register",))
        self.assertIn("sealed register", str(raised.exception))
        self.assertNotIn("Asha", str(raised.exception))


class PhoneRuleTests(unittest.TestCase):
    """web intake's ``_clean_phone`` calls ``app.utils.phone.normalise_phone``:
    one rule, pinned over a corpus."""

    CORPUS = (
        "9876543210", "98765 43210", "98765-43210", "(987) 654-3210", "+919876543210", "+91 98765 43210",
        "919876543210", "09876543210", "0 98765 43210", "5876543210", "987654321", "98765432101",
        "+9198765432", "98765abcde", "call me", "", "   ", "91 987", "+1 9876543210", "0091 9876543210",
    )

    def test_helper_and_clean_phone_agree(self):
        from app.utils.phone import normalise_phone

        for raw in self.CORPUS:
            try:
                expected = intake_svc._clean_phone(raw, what="Phone")
            except intake_svc.WebIntakeError:
                expected = None
            if not raw.strip():  # blank is "no phone" for _clean_phone, not a malformed one
                self.assertIsNone(expected, raw)
                self.assertIsNone(normalise_phone(raw), raw)
                continue
            self.assertEqual(normalise_phone(raw), expected, raw)
        self.assertEqual(normalise_phone("+91 98765-43210"), "9876543210")


    def test_non_ascii_digits_are_not_a_phone_in_either(self):
        from app.utils.phone import normalise_phone

        for raw in ("\u096f\u096e\u096d\u096c\u096b\u096a\u0969\u0968\u0967\u0966",  # Devanagari
                    "\u0669\u0668\u0667\u0666\u0665\u0664\u0663\u0662\u0661\u0660"):  # Arabic-Indic
            self.assertIsNone(normalise_phone(raw))
            with self.assertRaises(intake_svc.WebIntakeError):
                intake_svc._clean_phone(raw, what="Phone")


# The inherited intake tests run in their own module.
for _name in [n for n in dir(intake_tests.WebIntakeServiceTests) if n.startswith("test_")]:
    setattr(RegisterPiiSplitTests, _name, None)
