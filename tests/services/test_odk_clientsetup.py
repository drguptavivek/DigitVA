from unittest import TestCase
from unittest.mock import MagicMock, patch


class TestOdkClientSetupLogging(TestCase):
    def test_logs_db_backed_connection_usage_for_project(self):
        with patch(
            "app.utils.va_odk.va_odk_01_clientsetup._client_from_db",
            return_value=MagicMock(name="db_client"),
        ):
            with patch(
                "app.utils.va_odk.va_odk_01_clientsetup._client_from_toml",
            ) as toml_client:
                with patch(
                    "app.utils.va_odk.va_odk_01_clientsetup.log"
                ) as mock_log:
                    client = __import__(
                        "app.utils.va_odk.va_odk_01_clientsetup",
                        fromlist=["va_odk_clientsetup"],
                    ).va_odk_clientsetup(project_id="ROOT01")

        self.assertIsNotNone(client)
        toml_client.assert_not_called()
        mock_log.info.assert_called_once_with(
            "ODK client setup: using DB-backed connection for project %s",
            "ROOT01",
        )
        mock_log.warning.assert_not_called()

    def test_logs_toml_fallback_when_project_has_no_active_mapping(self):
        fallback_client = MagicMock(name="fallback_client")

        with patch(
            "app.utils.va_odk.va_odk_01_clientsetup._client_from_db",
            return_value=None,
        ):
            with patch(
                "app.utils.va_odk.va_odk_01_clientsetup._client_from_toml",
                return_value=fallback_client,
            ) as toml_client:
                with patch(
                    "app.utils.va_odk.va_odk_01_clientsetup.log"
                ) as mock_log:
                    client = __import__(
                        "app.utils.va_odk.va_odk_01_clientsetup",
                        fromlist=["va_odk_clientsetup"],
                    ).va_odk_clientsetup(project_id="ROOT01")

        self.assertIs(client, fallback_client)
        toml_client.assert_called_once()
        mock_log.warning.assert_called_once_with(
            "ODK client setup: project %s has no active DB-backed ODK connection; "
            "falling back to legacy TOML config",
            "ROOT01",
        )
