"""Focused contracts for the synthetic organization demo and APK guide."""

from unittest import mock

from tests.base import BaseTestCase


class OrganizationDemoDeliveryTests(BaseTestCase):
    def test_demo_guide_requires_a_signed_in_user(self):
        response = self.client.get("/help/organization-demo")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/vaauth/valogin", response.headers["Location"])

    def test_enabled_demo_shows_roles_and_landing_paths_without_passwords(self):
        self._login(self.base_coder_id)
        metadata = {
            "configured": True,
            "enabled": True,
            "project_id": "DEMO01",
            "accounts": [
                {
                    "role": "coder",
                    "email": "demo.coder@digitva.com",
                    "landing_path": "/app/coding",
                }
            ],
        }
        with mock.patch(
            "app.services.synthetic_demo_service.get_demo_metadata",
            return_value=metadata,
        ):
            body = self.client.get("/help/organization-demo").get_data(as_text=True)

        self.assertIn("demo.coder@digitva.com", body)
        self.assertIn("/app/coding", body)
        self.assertNotIn("demo-password", body)

    def test_disabled_demo_hides_account_metadata(self):
        self._login(self.base_coder_id)
        metadata = {
            "configured": True,
            "enabled": False,
            "project_id": "DEMO01",
            "accounts": [
                {
                    "role": "coder",
                    "email": "demo.coder@digitva.com",
                    "landing_path": "/app/coding",
                }
            ],
        }
        with mock.patch(
            "app.services.synthetic_demo_service.get_demo_metadata",
            return_value=metadata,
        ):
            body = self.client.get("/help/organization-demo").get_data(as_text=True)

        self.assertNotIn("demo.coder@digitva.com", body)
        self.assertNotIn("DEMO01", body)

    def test_weekly_schedule_is_disabled_without_project_configuration(self):
        from app.tasks import organization_demo_tasks as tasks

        self.app.config["DIGITVA_WEEKLY_DEMO_PROJECT_ID"] = ""
        with (
            mock.patch.object(tasks, "_disable_existing_schedule") as disable,
            mock.patch.object(tasks, "_seed_weekly_crontab") as seed,
            self.app.app_context(),
        ):
            self.assertFalse(tasks.ensure_weekly_demo_reset_scheduled())

        disable.assert_called_once_with()
        seed.assert_not_called()

    def test_weekly_task_delegates_to_service_and_does_not_print_credentials(self):
        from app.tasks import organization_demo_tasks as tasks

        result = {"status": "skipped", "project_id": "DEMO01", "counts": {}}
        with mock.patch(
            "app.services.synthetic_demo_service.reset_weekly_demo",
            return_value=result,
        ):
            with self.app.app_context():
                observed = tasks.reset_weekly_demo_task.run()

        self.assertEqual(observed, result)


class MobileAppGuideTests(BaseTestCase):
    def test_mobile_page_shows_valid_https_apk_url(self):
        self.app.config["DIGITVA_ANDROID_APK_URL"] = "https://github.com/example/app/releases/download/v1/app.apk"

        body = self.client.get("/help/mobile-app").get_data(as_text=True)

        self.assertIn(self.app.config["DIGITVA_ANDROID_APK_URL"], body)
        self.assertIn("Android app available.", body)

    def test_mobile_page_rejects_non_https_or_credentialed_url(self):
        for value in ("http://example.com/app.apk", "javascript:alert(1)", "https://u:p@example.com/app.apk"):
            with self.subTest(value=value):
                self.app.config["DIGITVA_ANDROID_APK_URL"] = value
                body = self.client.get("/help/mobile-app").get_data(as_text=True)
                self.assertNotIn(value, body)
                self.assertIn("has not been published", body)

    def test_mobile_page_keeps_browser_fallback_when_apk_is_unpublished(self):
        self.app.config["DIGITVA_ANDROID_APK_URL"] = ""

        body = self.client.get("/help/mobile-app").get_data(as_text=True)

        self.assertIn("/app/", body)
        self.assertIn("has not been published", body)
