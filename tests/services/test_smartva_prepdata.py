import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


class TestSmartvaPrepdataLogging(TestCase):
    def test_logs_prepared_and_skipped_counts_clearly(self):
        from app.utils.va_smartva.va_smartva_02_prepdata import va_smartva_prepdata

        va_form = SimpleNamespace(
            form_id="FORM01",
            form_smartvahiv="False",
            form_smartvamalaria="False",
            form_type_id=None,
            form_type=None,
        )

        with tempfile.TemporaryDirectory() as workspace_dir:
            with patch(
                "app.utils.va_smartva.va_smartva_02_prepdata._prepared_payload_rows",
                return_value=[("sid-1", {"field_a": "value"})],
            ):
                with patch(
                    "app.utils.va_smartva.va_smartva_02_prepdata.log"
                ) as mock_log:
                    result = va_smartva_prepdata(
                        va_form,
                        workspace_dir,
                        pending_sids={"sid-1"},
                    )

        self.assertIn("input_path", result)
        mock_log.info.assert_called_once_with(
            "SmartVA prep [%s]: prepared %d row(s); skipped %d already-complete row(s).",
            "FORM01",
            1,
            0,
        )


class TestSmartvaPrepdataDropsSealedFields(TestCase):
    """PII policy OD7: no sealed field reaches the SmartVA input CSV."""

    def _input_csv(self, payload, *, flagged=frozenset()):
        import csv
        import os

        from app.utils.va_smartva.va_smartva_02_prepdata import va_smartva_prepdata

        va_form = SimpleNamespace(form_id="FORM01", form_type_id=None, form_type=None)
        with tempfile.TemporaryDirectory() as workspace_dir:
            with patch(
                "app.utils.va_smartva.va_smartva_02_prepdata._prepared_payload_rows",
                return_value=[("sid-1", payload)],
            ), patch(
                "app.services.field_mapping_service.FieldMappingService.get_pii_field_ids",
                return_value=set(flagged),
            ):
                result = va_smartva_prepdata(va_form, workspace_dir, pending_sids={"sid-1"})
            with open(os.path.join(workspace_dir, "smartva_input.csv"), newline="") as handle:
                return result, list(csv.DictReader(handle))

    def test_global_and_form_flagged_pii_fields_are_dropped_and_scoring_fields_kept(self):
        from app.services.pii_field_registry import PII_FIELDS

        payload = {field: "x" for field in PII_FIELDS}
        payload.update({"Id10019": "female", "ageInYears": "52", "custom_name": "Jane"})
        self.assertIn("Id10073", payload)
        result, rows = self._input_csv(payload, flagged={"custom_name"})
        self.assertIn("input_path", result)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["Id10019"], row["ageInYears"], row["sid"]), ("female", "52", "sid-1"))
        for field in (*PII_FIELDS, "custom_name"):
            self.assertNotIn(field, row)

    def test_an_admin_flagged_date_of_death_stays_in_the_input_as_at_head(self):
        """Owner decision A: Id10023 is never sealed, so a form that flags it
        is_pii still passes it to SmartVA, as before the sealed-set drop."""
        _, rows = self._input_csv({"Id10023": "2024-01-05", "custom_name": "Jane"},
                                  flagged={"Id10023", "custom_name"})
        self.assertEqual(rows[0]["Id10023"], "2024-01-05")
        self.assertNotIn("custom_name", rows[0])


class TestSmartvaPrepdataEmitsOnlyColumnsSmartvaReads(TestCase):
    """digitva-omn4: intake/bundle payload metadata must not push the header
    below SmartVA's WHO-questionnaire threshold (>80% Id####/age*/is*)."""

    WHO_RULE = r"^[Ii]d\d+(_\w+)?$|^age|^is"  # same as workerthread.who_questionaire_test

    def _headers(self, payload):
        import csv
        import os
        import re

        from app.utils.va_smartva.va_smartva_02_prepdata import va_smartva_prepdata

        va_form = SimpleNamespace(form_id="FORM01", form_type_id=None, form_type=None)
        with tempfile.TemporaryDirectory() as workspace_dir:
            with patch(
                "app.utils.va_smartva.va_smartva_02_prepdata._prepared_payload_rows",
                return_value=[("sid-1", payload)],
            ), patch(
                "app.services.field_mapping_service.FieldMappingService.get_pii_field_ids",
                return_value=set(),
            ):
                va_smartva_prepdata(va_form, workspace_dir, pending_sids={"sid-1"})
            with open(os.path.join(workspace_dir, "smartva_input.csv"), newline="") as handle:
                headers = next(csv.reader(handle))
        matches = sum(bool(re.match(self.WHO_RULE, h)) for h in headers)
        return headers, matches / len(headers)

    def test_web_style_metadata_is_dropped_and_header_passes_who_rule(self):
        payload = {f"Id{10000 + i}": "yes" for i in range(40)}
        payload.update({"Id10019": "female", "ageInYears": "52", "isAdult": "1", "Id10219_a": "1"})
        payload.update({f"org_{i}": "x" for i in range(10)})
        payload.update({f"survey_{i}": "x" for i in range(10)})
        payload.update({f"intake_{i}": "x" for i in range(10)})
        payload.update({"death_register_id": "D1", "interview_outcome": "done", "SubmitterName": "n", "KEY": "k"})
        headers, ratio = self._headers(payload)
        self.assertGreater(ratio, 0.8)
        self.assertIn("sid", headers)
        for kept in ("Id10019", "ageInYears", "isAdult", "Id10219_a"):
            self.assertIn(kept, headers)
        self.assertNotIn("org_0", headers)
        self.assertNotIn("SubmitterName", headers)

    def test_odk_style_payload_keeps_its_id_and_age_columns(self):
        payload = {"Id10019": "x", "Id10013": "yes", "Id10120_1": "3", "ageInDays": "10",
                   "age_neonate_days": "10", "isNeonatal1": "1", "sa01_1": "x", "survey_block": "x"}
        headers, ratio = self._headers(payload)
        self.assertEqual(
            sorted(headers),
            sorted(["Id10019", "Id10013", "Id10120_1", "ageInDays", "age_neonate_days", "isNeonatal1", "sid"]),
        )
        self.assertGreater(ratio, 0.8)
