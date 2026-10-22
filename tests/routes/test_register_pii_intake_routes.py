"""PII slice 2, T2: the intake and export routes over sealed register rows.

The route test classes below run again with ``REGISTER_PII_SPLIT_ENABLED`` on,
so every case they register is sealed and every reader goes through the
accessor; they must pass as they do flag-off. Three tests assert on a
plaintext column of the stored row (a sealed row has none), so they are
switched off here and covered by ``tests/services/test_register_pii_readers.py``.
The export class seals its fixture instead and adds the no-decrypt check.
"""
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import VaDeathRegister
from app.services import register_pii_accessor as accessor
from app.utils import pii_crypto as pc
from tests.routes import test_cases_export as export_tests
from tests.routes import test_death_reporter as reporter_tests
from tests.routes import test_intake_api as api_tests
from tests.routes import test_intake_prefill_routes as prefill_tests
from tests.routes import test_intake_worklist_api as worklist_tests


class _FlagOn:
    def setUp(self):
        super().setUp()
        previous = self.app.config.get("REGISTER_PII_SPLIT_ENABLED", False)
        self.app.config["REGISTER_PII_SPLIT_ENABLED"] = True
        self.addCleanup(self.app.config.__setitem__, "REGISTER_PII_SPLIT_ENABLED", previous)


def _sealed(base, switched_off=()):
    sealed = type(f"Sealed{base.__name__}", (_FlagOn, base), {})
    for name in switched_off:
        setattr(sealed, name, None)
    return sealed


SealedDeathReporterTests = _sealed(
    reporter_tests.DeathReporterTests, ("test_a_reporter_cannot_correct_a_death_it_did_not_register_or_cannot_reach",))
SealedIntakeApiTests = _sealed(api_tests.IntakeApiTests, (
    "test_a_death_correction_refuses_an_unknown_field_and_changes_nothing",
    "test_browser_submit_after_a_teammate_won_replies_superseded_and_leaves_the_case",
))


def _list_opens_no_location_when_the_fix_is_hidden(self):
    self._register_with(**self.FIX)
    url = f"/api/v1/intake/deaths?project_id={self.PROJECT_ID}&site_id={self.SITE_ID}"
    with mock.patch.object(pc, "open_record", wraps=pc.open_record) as spy:
        shown = self.client.get(url).get_json()["deaths"]
    self.assertTrue(shown and "latitude" in shown[0])  # present before absent
    self.assertTrue(any(c.kwargs["only"] is None or "location" in c.kwargs["only"] for c in spy.call_args_list))
    with mock.patch("app.services.web_intake_service.shows_gps", return_value=False), \
            mock.patch.object(pc, "open_record", wraps=pc.open_record) as spy:
        hidden = self.client.get(url).get_json()["deaths"]
    self.assertEqual(len(hidden), len(shown))
    self.assertTrue(spy.call_count)
    self.assertNotIn("latitude", hidden[0])
    for call in spy.call_args_list:
        self.assertIsNotNone(call.kwargs["only"])
        self.assertNotIn("location", call.kwargs["only"])


SealedIntakeApiTests.test_the_list_opens_no_location_when_the_fix_is_hidden = _list_opens_no_location_when_the_fix_is_hidden
SealedIntakeWorklistApiTests = _sealed(worklist_tests.IntakeWorklistApiTests)
SealedIntakePrefillRouteTests = _sealed(prefill_tests.IntakePrefillRouteTests)
SealedWebOnlyProjectIntakeTests = _sealed(api_tests.WebOnlyProjectIntakeTests)


class SealedCaseExportTests(export_tests.CaseExportTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for death in db.session.scalars(sa.select(VaDeathRegister)):
            accessor.seal_register_pii(death)
        db.session.commit()

    def test_the_export_decrypts_no_register_field_and_carries_no_name(self):
        row = db.session.execute(sa.text(
            "SELECT deceased_name IS NULL AS gone, pii_sealed IS NOT NULL AS sealed FROM va_death_register "
            "WHERE death_id = :i"), {"i": self.one.death_id}).one()
        self.assertEqual((row.gone, row.sealed), (True, True))
        with mock.patch.object(pc, "open_record", wraps=pc.open_record) as spy:
            text = self._export(self.dana).get_data(as_text=True)
        self.assertIn(str(self.one.unique_id), text)  # present before absent
        self.assertNotIn("Submitted Person", text)
        self.assertEqual(spy.call_count, 0)

