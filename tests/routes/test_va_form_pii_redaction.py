"""Submission-detail rendering: subject PII redaction and its cache key.

Covers the surface .tasks/viewer-pii-roles.md calls out as still open — the
category-data render inside ``app/routes/va_form.py::renderpartial`` (reached
today via ``view_submission`` -> ``render_va_coding_page`` for a
data_manager/admin viewer; a plain ``collaborator`` cannot reach this route
yet, since wiring collaborator access is a separate, not-yet-done task — see
``app/decorators/va_validate_permissions.py::_validate_vadata``, which still
requires ``has_data_manager_submission_access``).

Because the route itself is not reachable by ``collaborator`` today, these
tests exercise the real render path as a ``data_manager`` (who can reach it)
and patch ``should_redact_pii`` at its call site in ``app.routes.va_form`` to
stand in for the redaction decision a wired-up collaborator viewer would get.
This proves the redaction logic itself is correct now, so it is already
right the moment the route is opened up — the same approach
``tests/services/test_viewer_pii_redaction.py`` uses for the dashboard and
search surfaces.

Fixture note (docs/policy/test-harness.md, "Seeding a project: the dual-table
trap"): ``va_forms.project_id``/``va_sites.project_id`` key to
``va_research_projects``, while ``va_project_sites.project_id`` keys to
``va_project_master``. ``BaseTestCase._seed_base_fixtures`` (run by
``setUpClass``) seeds the ``va_project_master``/``va_project_sites`` pair for
``BASE_PROJECT_ID``/``BASE_SITE_ID``; the legacy
``va_research_projects``/``va_sites`` pair is seeded separately here via
``_ensure_base_research_project_and_site()``, matching
``tests/services/test_runtime_form_sync_service.py``.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    MasCategoryDisplayConfig,
    MasFieldDisplayConfig,
    MasFormTypes,
    MasSubcategoryOrder,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED
from tests.base import BaseTestCase


class RenderpartialPiiRedactionTests(BaseTestCase):
    FORM_TYPE_CODE = "PIITEST_VA"
    FORM_ID = "PIITESTFRM01"
    VA_SID = "uuid:pii-render-test-1"
    PII_VALUE = "Jane Realname Actual"
    PUBLIC_VALUE = "SomePublicSymptomValue"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_base_research_project_and_site()
        now = datetime.now(timezone.utc)

        form_type = db.session.scalar(
            sa.select(MasFormTypes).where(MasFormTypes.form_type_code == cls.FORM_TYPE_CODE)
        )
        if form_type is None:
            form_type = MasFormTypes(
                form_type_code=cls.FORM_TYPE_CODE,
                form_type_name="PII Redaction Test Form",
                is_active=True,
            )
            db.session.add(form_type)
            db.session.flush()
        cls.form_type_id = form_type.form_type_id

        if db.session.scalar(
            sa.select(MasCategoryDisplayConfig).where(
                MasCategoryDisplayConfig.form_type_id == cls.form_type_id,
                MasCategoryDisplayConfig.category_code == "cat1",
            )
        ) is None:
            db.session.add(MasCategoryDisplayConfig(
                form_type_id=cls.form_type_id,
                category_code="cat1",
                display_label="Category One",
                nav_label="Category One",
                display_order=1,
                render_mode="table_sections",
                show_to_coder=True,
                show_to_reviewer=True,
                show_to_site_pi_datamanager=True,
                always_include=True,
                is_default_start=True,
                is_active=True,
            ))

        if db.session.scalar(
            sa.select(MasSubcategoryOrder).where(
                MasSubcategoryOrder.form_type_id == cls.form_type_id,
                MasSubcategoryOrder.category_code == "cat1",
                MasSubcategoryOrder.subcategory_code == "sub1",
            )
        ) is None:
            db.session.add(MasSubcategoryOrder(
                form_type_id=cls.form_type_id,
                category_code="cat1",
                subcategory_code="sub1",
                subcategory_name="Sub One",
                display_order=1,
                is_active=True,
            ))

        for field_id, is_pii, label, order in (
            ("PiiField1", True, "Deceased Real Name", 1),
            ("PublicField1", False, "Public Symptom", 2),
        ):
            if db.session.scalar(
                sa.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == cls.form_type_id,
                    MasFieldDisplayConfig.field_id == field_id,
                )
            ) is None:
                db.session.add(MasFieldDisplayConfig(
                    form_type_id=cls.form_type_id,
                    field_id=field_id,
                    category_code="cat1",
                    subcategory_code="sub1",
                    short_label=label,
                    is_pii=is_pii,
                    is_active=True,
                    display_order=order,
                ))
        db.session.flush()

        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="PII_TEST_FORM",
                odk_project_id="901",
                form_type="PII Redaction Test Form",
                form_type_id=cls.form_type_id,
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
            db.session.flush()

        if db.session.get(VaSubmissions, cls.VA_SID) is None:
            submission = VaSubmissions(
                va_sid=cls.VA_SID,
                va_form_id=cls.FORM_ID,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="Collector",
                va_odk_reviewstate=None,
                va_instance_name=cls.VA_SID,
                va_uniqueid_real=cls.VA_SID,
                va_uniqueid_masked="masked-pii-render-1",
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=50,
                va_deceased_gender="female",
                va_summary=[],
                va_catcount={},
                va_category_list=["cat1"],
            )
            db.session.add(submission)
            db.session.flush()
            ensure_active_payload_version(
                submission,
                payload_data={
                    "PiiField1": cls.PII_VALUE,
                    "PublicField1": cls.PUBLIC_VALUE,
                },
                source_updated_at=now,
                created_by_role="vasystem",
            )
            db.session.add(VaSubmissionWorkflow(
                va_sid=cls.VA_SID,
                workflow_state=WORKFLOW_CODER_FINALIZED,
                workflow_created_at=now,
                workflow_updated_at=now,
            ))

        cls.dm_user = cls._get_or_make_user(
            "pii.render.dm@test.local", "PiiRenderDm123"
        )
        project_site_id = db.session.scalar(
            sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == cls.BASE_PROJECT_ID,
                VaProjectSites.site_id == cls.BASE_SITE_ID,
            )
        )
        if db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == cls.dm_user.user_id,
                VaUserAccessGrants.role == VaAccessRoles.data_manager,
            )
        ) is None:
            db.session.add(VaUserAccessGrants(
                user_id=cls.dm_user.user_id,
                role=VaAccessRoles.data_manager,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site_id,
                grant_status=VaStatuses.active,
                notes="pii render test dm grant",
            ))
        db.session.commit()
        cls.dm_user_id = str(cls.dm_user.user_id)

    def _get_partial(self):
        return self.client.get(
            f"/vaform/{self.VA_SID}/cat1",
            query_string={"action": "vadata", "actiontype": "vaview"},
        )

    def test_no_pii_viewer_does_not_see_pii_field_value(self):
        """The redaction decision, forced True: stand-in for a wired-up
        plain ``collaborator``."""
        self._login(self.dm_user_id)
        with patch(
            "app.routes.va_form.should_redact_pii", return_value=True
        ):
            response = self._get_partial()
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertNotIn(self.PII_VALUE, body)
        self.assertIn(self.PUBLIC_VALUE, body)

    def test_pii_viewer_sees_pii_field_value(self):
        """Forced False: stand-in for a wired-up ``collaborator_pii`` (and
        the regression check that today's data_manager/admin view is
        unchanged)."""
        self._login(self.dm_user_id)
        with patch(
            "app.routes.va_form.should_redact_pii", return_value=False
        ):
            response = self._get_partial()
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn(self.PII_VALUE, body)
        self.assertIn(self.PUBLIC_VALUE, body)

    def test_unconfirmed_pii_set_withholds_the_whole_payload(self):
        """Fail-closed: strip this form type's only is_pii row down to what
        the registry would have created (no subcategory, no odk_label,
        is_custom) and the set is no longer confirmed — a viewer without PII
        then sees no payload value at all, not just the flagged one."""
        from app import cache as flask_cache
        from app.services.field_mapping_service import get_mapping_service

        # The mapping service's fieldsitepi cache is process-level and not
        # versioned; the render below rebuilds it from the mutated row, and
        # the savepoint rollback in tearDown does not undo that. Clear both
        # caches on exit so later tests in this class see the fixture again.
        self.addCleanup(get_mapping_service().clear_cache)
        self.addCleanup(flask_cache.clear)

        self._login(self.dm_user_id)
        # Present before: with the set confirmed, a redacting viewer still
        # sees the non-PII value.
        with patch("app.routes.va_form.should_redact_pii", return_value=True):
            before = self._get_partial()
        self.assertIn(self.PUBLIC_VALUE, before.get_data(as_text=True))

        pii_row = db.session.scalar(
            sa.select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == self.form_type_id,
                MasFieldDisplayConfig.field_id == "PiiField1",
            )
        )
        pii_row.category_code = None
        pii_row.subcategory_code = None
        pii_row.odk_label = None
        pii_row.is_custom = True
        db.session.flush()
        self.assertFalse(
            get_mapping_service().is_pii_set_confirmed(self.FORM_TYPE_CODE)
        )
        # The rendered section is cached per (sid, partial, redaction), and
        # that key does not depend on the mapping config, so the warmed entry
        # above would otherwise answer this request.
        flask_cache.clear()
        get_mapping_service().clear_cache()

        with patch("app.routes.va_form.should_redact_pii", return_value=True):
            withheld = self._get_partial()
        self.assertEqual(withheld.status_code, 200)
        withheld_body = withheld.get_data(as_text=True)
        self.assertNotIn(self.PUBLIC_VALUE, withheld_body)
        self.assertNotIn(self.PII_VALUE, withheld_body)

        # Positive control: a viewer entitled to PII is unaffected.
        flask_cache.clear()
        with patch("app.routes.va_form.should_redact_pii", return_value=False):
            full = self._get_partial()
        self.assertIn(self.PUBLIC_VALUE, full.get_data(as_text=True))

    def test_cache_does_not_leak_full_render_into_a_later_redacted_one(self):
        """The bug the cache-key fix closes: render unredacted first (warms
        the plain cache entry), then redacted — the second call must not be
        served the first call's cached PII value."""
        self._login(self.dm_user_id)
        with patch(
            "app.routes.va_form.should_redact_pii", return_value=False
        ):
            first = self._get_partial()
        self.assertIn(self.PII_VALUE, first.get_data(as_text=True))

        with patch(
            "app.routes.va_form.should_redact_pii", return_value=True
        ):
            second = self._get_partial()
        second_body = second.get_data(as_text=True)
        self.assertNotIn(
            self.PII_VALUE,
            second_body,
            "redacted render was served the earlier unredacted cache entry",
        )
        self.assertIn(self.PUBLIC_VALUE, second_body)

    def test_cache_does_not_leak_redacted_render_into_a_later_full_one(self):
        """The reverse ordering: render redacted first (warms the
        ``:nopii`` cache entry), then unredacted — the second call must
        still get the real value, not the redacted cache entry."""
        self._login(self.dm_user_id)
        with patch(
            "app.routes.va_form.should_redact_pii", return_value=True
        ):
            first = self._get_partial()
        self.assertNotIn(self.PII_VALUE, first.get_data(as_text=True))

        with patch(
            "app.routes.va_form.should_redact_pii", return_value=False
        ):
            second = self._get_partial()
        self.assertIn(
            self.PII_VALUE,
            second.get_data(as_text=True),
            "unredacted render was served the earlier redacted cache entry",
        )
