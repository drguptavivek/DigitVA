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
