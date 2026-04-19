from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.models.va_forms import VaForms
from app.models.va_project_master import VaProjectMaster
from app.services.coding_service import render_va_coding_page


class TestCodingService(unittest.TestCase):
    def test_render_va_coding_page_includes_project_site_and_demo_context(self):
        submission = SimpleNamespace(
            va_sid="SID-1",
            va_form_id="FORM-1",
            va_catcount={},
            va_uniqueid_masked="VA-1",
            va_deceased_age=43,
            va_deceased_gender="male",
        )
        category_service = Mock()
        category_service.get_category_nav.return_value = []
        category_service.get_default_category_code.return_value = "vademographicdetails"

        with (
            patch("app.services.coding_service._count_attachments_per_category", return_value={}),
            patch("app.services.coding_service.db.session.get") as mock_db_get,
            patch("app.utils.va_get_form_type_code_for_form", return_value="WHO_2022_VA"),
            patch(
                "app.services.category_rendering_service.get_category_rendering_service",
                return_value=category_service,
            ),
            patch(
                "app.services.category_rendering_service.get_visible_category_codes",
                return_value=["vademographicdetails"],
            ),
            patch("app.services.coder_workflow_service.is_upstream_recode", return_value=False),
            patch("app.services.demo_project_service.is_demo_training_submission", return_value=True),
            patch("app.services.submission_payload_version_service.get_active_payload_version", return_value=None),
            patch("app.services.workflow.upstream_changes.get_latest_pending_upstream_change", return_value=None),
            patch("flask.url_for", return_value="/stub"),
            patch("flask.render_template", return_value="OK") as mock_render_template,
        ):
            def _db_get(model, key):
                if model is VaForms and key == "FORM-1":
                    return SimpleNamespace(project_id="PROJ01", site_id="SITE1")
                if model is VaProjectMaster and key == "PROJ01":
                    return SimpleNamespace(project_code="PROJECT-CODE")
                return None

            mock_db_get.side_effect = _db_get
            result = render_va_coding_page(
                submission=submission,
                va_action="vacode",
                va_actiontype="varesumecoding",
                back_dashboard_role="coder",
            )

        self.assertEqual(result, "OK")
        self.assertTrue(mock_render_template.called)
        template_name = mock_render_template.call_args.args[0]
        context = mock_render_template.call_args.kwargs
        self.assertEqual(template_name, "va_frontpages/va_coding.html")
        self.assertEqual(context["project_code"], "PROJECT-CODE")
        self.assertEqual(context["site_code"], "SITE1")
        self.assertTrue(context["is_demo_project"])

    def test_render_va_coding_page_queues_open_repair_for_vacode(self):
        submission = SimpleNamespace(
            va_sid="SID-1",
            va_form_id="FORM-1",
            va_catcount={},
            va_uniqueid_masked="VA-1",
            va_deceased_age=43,
            va_deceased_gender="male",
        )
        category_service = Mock()
        category_service.get_category_nav.return_value = []
        category_service.get_default_category_code.return_value = "vademographicdetails"

        with (
            patch("app.services.coding_service._count_attachments_per_category", return_value={}),
            patch("app.services.coding_service.db.session.get", side_effect=lambda model, key: submission if key == "SID-1" else (SimpleNamespace(project_id="PROJ01", site_id="SITE1") if model is VaForms else (SimpleNamespace(project_code="PROJECT-CODE") if model is VaProjectMaster else None))),
            patch("app.utils.va_get_form_type_code_for_form", return_value="WHO_2022_VA"),
            patch(
                "app.services.category_rendering_service.get_category_rendering_service",
                return_value=category_service,
            ),
            patch(
                "app.services.category_rendering_service.get_visible_category_codes",
                return_value=["vademographicdetails"],
            ),
            patch("app.services.coder_workflow_service.is_upstream_recode", return_value=False),
            patch("app.services.demo_project_service.is_demo_training_submission", return_value=False),
            patch("app.services.coding_service.flask_cache.get", return_value=None),
            patch("app.services.coding_service.flask_cache.set") as mock_cache_set,
            patch("app.tasks.sync_tasks.run_open_submission_repair.delay") as mock_repair,
            patch("app.services.submission_payload_version_service.get_active_payload_version", return_value=None),
            patch("app.services.workflow.upstream_changes.get_latest_pending_upstream_change", return_value=None),
            patch("flask.url_for", return_value="/stub"),
            patch("flask.render_template", return_value="OK"),
        ):
            result = render_va_coding_page(
                submission=submission,
                va_action="vacode",
                va_actiontype="varesumecoding",
                back_dashboard_role="coder",
            )

        self.assertEqual(result, "OK")
        mock_repair.assert_called_once_with(
            va_sid="SID-1",
            trigger_source="vacode_open_repair",
        )
        mock_cache_set.assert_called_once()

    def test_render_va_coding_page_queues_open_repair_for_data_manager_view(self):
        submission = SimpleNamespace(
            va_sid="SID-1",
            va_form_id="FORM-1",
            va_catcount={},
            va_uniqueid_masked="VA-1",
            va_deceased_age=43,
            va_deceased_gender="male",
        )
        category_service = Mock()
        category_service.get_category_nav.return_value = []
        category_service.get_default_category_code.return_value = "vademographicdetails"

        with (
            patch("app.services.coding_service._count_attachments_per_category", return_value={}),
            patch("app.services.coding_service.db.session.get", side_effect=lambda model, key: submission if key == "SID-1" else (SimpleNamespace(project_id="PROJ01", site_id="SITE1") if model is VaForms else (SimpleNamespace(project_code="PROJECT-CODE") if model is VaProjectMaster else None))),
            patch("app.utils.va_get_form_type_code_for_form", return_value="WHO_2022_VA"),
            patch(
                "app.services.category_rendering_service.get_category_rendering_service",
                return_value=category_service,
            ),
            patch(
                "app.services.category_rendering_service.get_visible_category_codes",
                return_value=["vademographicdetails"],
            ),
            patch("app.services.coder_workflow_service.is_upstream_recode", return_value=False),
            patch("app.services.demo_project_service.is_demo_training_submission", return_value=False),
            patch("app.services.coding_service.flask_cache.get", return_value=None),
            patch("app.services.coding_service.flask_cache.set") as mock_cache_set,
            patch("app.tasks.sync_tasks.run_open_submission_repair.delay") as mock_repair,
            patch("app.services.submission_payload_version_service.get_active_payload_version", return_value=None),
            patch("app.services.workflow.upstream_changes.get_latest_pending_upstream_change", return_value=None),
            patch("flask.url_for", return_value="/stub"),
            patch("flask.render_template", return_value="OK"),
        ):
            result = render_va_coding_page(
                submission=submission,
                va_action="vadata",
                va_actiontype="vaview",
                back_dashboard_role="data_manager",
            )

        self.assertEqual(result, "OK")
        mock_repair.assert_called_once_with(
            va_sid="SID-1",
            trigger_source="vadata_open_repair",
        )
        mock_cache_set.assert_called_once()

    def test_render_va_coding_page_skips_open_repair_for_non_coding_views(self):
        submission = SimpleNamespace(
            va_sid="SID-1",
            va_form_id="FORM-1",
            va_catcount={},
            va_uniqueid_masked="VA-1",
            va_deceased_age=43,
            va_deceased_gender="male",
        )
        category_service = Mock()
        category_service.get_category_nav.return_value = []
        category_service.get_default_category_code.return_value = "vademographicdetails"

        with (
            patch("app.services.coding_service._count_attachments_per_category", return_value={}),
            patch("app.services.coding_service.db.session.get", side_effect=lambda model, key: submission if key == "SID-1" else (SimpleNamespace(project_id="PROJ01", site_id="SITE1") if model is VaForms else (SimpleNamespace(project_code="PROJECT-CODE") if model is VaProjectMaster else None))),
            patch("app.utils.va_get_form_type_code_for_form", return_value="WHO_2022_VA"),
            patch(
                "app.services.category_rendering_service.get_category_rendering_service",
                return_value=category_service,
            ),
            patch(
                "app.services.category_rendering_service.get_visible_category_codes",
                return_value=["vademographicdetails"],
            ),
            patch("app.services.coder_workflow_service.is_upstream_recode", return_value=False),
            patch("app.services.demo_project_service.is_demo_training_submission", return_value=False),
            patch("app.tasks.sync_tasks.run_open_submission_repair.delay") as mock_repair,
            patch("app.services.submission_payload_version_service.get_active_payload_version", return_value=None),
            patch("app.services.workflow.upstream_changes.get_latest_pending_upstream_change", return_value=None),
            patch("flask.url_for", return_value="/stub"),
            patch("flask.render_template", return_value="OK"),
        ):
            result = render_va_coding_page(
                submission=submission,
                va_action="vareview",
                va_actiontype="vaview",
                back_dashboard_role="reviewer",
            )

        self.assertEqual(result, "OK")
        mock_repair.assert_not_called()
