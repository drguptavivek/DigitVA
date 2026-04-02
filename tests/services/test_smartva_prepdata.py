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
        )

        with tempfile.TemporaryDirectory() as workspace_dir:
            with patch(
                "app.utils.va_smartva.va_smartva_02_prepdata._prepared_payload_rows",
                return_value=[("sid-1", {"field_a": "value"})],
            ):
                with patch(
                    "app.utils.va_smartva.va_smartva_02_prepdata._derive_smartva_run_options",
                    return_value={"hiv": "False", "malaria": "False"},
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
