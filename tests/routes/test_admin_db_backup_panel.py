"""The admin Database backups block: overview and the "Back up now" action.

Both endpoints are admin-only, the action is a state-changing POST and so needs
a CSRF token, and neither response may carry anything beyond the object key —
no connection string, no credential, no host.
"""

from unittest import mock

from app.models import VaDbBackup
from app.services import db_backup_service as svc
from tests.services.test_db_backup_service import DbBackupBase


class AdminDbBackupPanelTests(DbBackupBase):
    OVERVIEW_URL = "/admin/api/db-backups/overview"
    RUN_URL = "/admin/api/db-backups/run"

    # -- overview ---------------------------------------------------------

    def test_overview_reports_retention_and_the_recent_backups(self):
        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_CLI)
        self._login(str(self.base_admin_id))

        response = self.client.get(self.OVERVIEW_URL)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["store"], "local")
        self.assertEqual(payload["keep_daily"], self.app.config["DB_BACKUP_KEEP_DAILY"])
        self.assertEqual(payload["recent"][0]["object_key"], outcome.object_key)
        self.assertNotIn("postgresql://", response.get_data(as_text=True))

    def test_overview_is_admin_only(self):
        self._login(str(self.base_coder_id))
        self.assertIn(self.client.get(self.OVERVIEW_URL).status_code, (302, 403))

    def test_overview_requires_a_login(self):
        self.assertIn(self.client.get(self.OVERVIEW_URL).status_code, (302, 401))

    # -- back up now ------------------------------------------------------

    def test_back_up_now_queues_the_task_for_an_admin(self):
        self._login(str(self.base_admin_id))

        with mock.patch("app.tasks.backup_tasks.run_db_backup.delay") as delay:
            delay.return_value = mock.Mock(id="task-1")
            response = self.client.post(
                self.RUN_URL, json={}, headers=self._csrf_headers()
            )

        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["task_id"], "task-1")
        delay.assert_called_once()
        kwargs = delay.call_args.kwargs
        self.assertEqual(kwargs["triggered_by"], VaDbBackup.TRIGGER_MANUAL)
        self.assertEqual(kwargs["user_id"], str(self.base_admin_id))

    def test_back_up_now_without_a_csrf_token_is_rejected(self):
        self._login(str(self.base_admin_id))

        with mock.patch("app.tasks.backup_tasks.run_db_backup.delay") as delay:
            response = self.client.post(self.RUN_URL, json={})

        self.assertEqual(response.status_code, 400)
        delay.assert_not_called()

    def test_back_up_now_is_admin_only(self):
        self._login(str(self.base_coder_id))

        with mock.patch("app.tasks.backup_tasks.run_db_backup.delay") as delay:
            response = self.client.post(
                self.RUN_URL, json={}, headers=self._csrf_headers()
            )

        self.assertIn(response.status_code, (302, 403))
        delay.assert_not_called()
