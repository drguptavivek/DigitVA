"""Submission-detail rendering: subject PII redaction and its cache key.

Stage 2 of digitva-0wc opened this render to viewers: collaborator and
collaborator_pii open one submission read-only through ``/coding/area/<sid>``
(action ``vaarea``), and the ``vadata`` validator is ``VIEW``. The
``Viewer*`` tests below exercise that path with real viewer grants and no
patching; the older tests keep the data-manager stand-in described next.

The older tests below render as a ``data_manager`` and patch
``should_redact_pii`` at its call site in ``app.services.case_content_service`` to stand in
for each redaction decision, so the redaction logic and its cache key are
tested independently of who may reach the route.

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
import uuid
from datetime import UTC, datetime, timezone
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
    STAFF_VALUE = "Interviewer Staffname Actual"

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
            # Staff identity: not is_pii, but withheld from a plain
            # collaborator like the submissions export withholds it.
            ("SubmitterName", False, "Submitted By", 3),
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
                    "SubmitterName": cls.STAFF_VALUE,
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
            "app.services.case_content_service.should_redact_pii", return_value=True
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
            "app.services.case_content_service.should_redact_pii", return_value=False
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
        with patch("app.services.case_content_service.should_redact_pii", return_value=True):
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

        with patch("app.services.case_content_service.should_redact_pii", return_value=True):
            withheld = self._get_partial()
        self.assertEqual(withheld.status_code, 200)
        withheld_body = withheld.get_data(as_text=True)
        self.assertNotIn(self.PUBLIC_VALUE, withheld_body)
        self.assertNotIn(self.PII_VALUE, withheld_body)

        # Positive control: a viewer entitled to PII is unaffected.
        flask_cache.clear()
        with patch("app.services.case_content_service.should_redact_pii", return_value=False):
            full = self._get_partial()
        self.assertIn(self.PUBLIC_VALUE, full.get_data(as_text=True))

    def test_cache_does_not_leak_full_render_into_a_later_redacted_one(self):
        """The bug the cache-key fix closes: render unredacted first (warms
        the plain cache entry), then redacted — the second call must not be
        served the first call's cached PII value."""
        self._login(self.dm_user_id)
        with patch(
            "app.services.case_content_service.should_redact_pii", return_value=False
        ):
            first = self._get_partial()
        self.assertIn(self.PII_VALUE, first.get_data(as_text=True))

        with patch(
            "app.services.case_content_service.should_redact_pii", return_value=True
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
            "app.services.case_content_service.should_redact_pii", return_value=True
        ):
            first = self._get_partial()
        self.assertNotIn(self.PII_VALUE, first.get_data(as_text=True))

        with patch(
            "app.services.case_content_service.should_redact_pii", return_value=False
        ):
            second = self._get_partial()
        self.assertIn(
            self.PII_VALUE,
            second.get_data(as_text=True),
            "unredacted render was served the earlier redacted cache entry",
        )

    # ------------------------------------------------------------------
    # Viewers on the real path (digitva-0wc stage 2)
    # ------------------------------------------------------------------

    def _viewer(self, role):
        user = self._make_user(
            f"pii.render.{role.value}.{uuid.uuid4().hex[:6]}@test.local", "PiiViewer123"
        )
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=role,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.BASE_PROJECT_ID,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return str(user.user_id)

    def _viewer_partial(self, action):
        return self.client.get(
            f"/vaform/{self.VA_SID}/cat1",
            query_string={"action": action, "actiontype": "vaview"},
        )

    def _fresh_cache(self):
        from app import cache as flask_cache

        flask_cache.clear()
        self.addCleanup(flask_cache.clear)

    def test_viewer_collaborator_gets_the_submission_redacted(self):
        self._fresh_cache()
        # Present first: the data manager sees all three values.
        self._login(self.dm_user_id)
        full = self._viewer_partial("vadata").get_data(as_text=True)
        for value in (self.PII_VALUE, self.STAFF_VALUE, self.PUBLIC_VALUE):
            self.assertIn(value, full)

        self._login(self._viewer(VaAccessRoles.collaborator))
        for action in ("vaarea", "vadata"):
            with self.subTest(action=action):
                response = self._viewer_partial(action)
                self.assertEqual(response.status_code, 200)
                body = response.get_data(as_text=True)
                self.assertIn(self.PUBLIC_VALUE, body)
                self.assertNotIn(self.PII_VALUE, body)
                self.assertNotIn(self.STAFF_VALUE, body)

    def test_view_only_coder_and_reviewer_get_the_content_partial_in_scope(self):
        """digitva-blp: a coder or reviewer admitted by VIEW reads a real
        category partial through ``vaarea``, not only the shell."""
        self._fresh_cache()
        for role in (VaAccessRoles.coder, VaAccessRoles.reviewer):
            with self.subTest(role=role.value):
                self._login(self._viewer(role))
                response = self._viewer_partial("vaarea")
                self.assertEqual(response.status_code, 200)
                self.assertIn(self.PUBLIC_VALUE, response.get_data(as_text=True))

    def test_viewer_collaborator_pii_sees_personal_data_and_staff_identity(self):
        self._fresh_cache()
        self._login(self._viewer(VaAccessRoles.collaborator_pii))
        response = self._viewer_partial("vaarea")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        for value in (self.PII_VALUE, self.STAFF_VALUE, self.PUBLIC_VALUE):
            self.assertIn(value, body)

    def test_viewer_collaborator_on_an_unconfirmed_form_type_gets_no_payload(self):
        from app.services.field_mapping_service import get_mapping_service

        self._fresh_cache()
        self.addCleanup(get_mapping_service().clear_cache)
        viewer_id = self._viewer(VaAccessRoles.collaborator)
        self._login(viewer_id)
        self.assertIn(self.PUBLIC_VALUE, self._viewer_partial("vaarea").get_data(as_text=True))

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
        self.assertFalse(get_mapping_service().is_pii_set_confirmed(self.FORM_TYPE_CODE))
        self._fresh_cache()
        get_mapping_service().clear_cache()

        response = self._viewer_partial("vaarea")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        for value in (self.PUBLIC_VALUE, self.PII_VALUE, self.STAFF_VALUE):
            self.assertNotIn(value, body)

    def test_viewer_shell_is_read_only_with_area_hints(self):
        self._login(self._viewer(VaAccessRoles.collaborator))
        response = self.client.get(f"/coding/area/{self.VA_SID}")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("read-only mode", body)
        self.assertIn("action=vaarea", body)
        self.assertIn('href="/data-management/"', body)
        for write_affordance in ("Data Triage", "vadmtriage", 'id="dm-accept-upstream-btn"', "odk-edit"):
            self.assertNotIn(write_affordance, body)

    def test_viewer_outside_scope_is_refused(self):
        from app.models import VaProjectMaster

        now = datetime.now(UTC)
        if db.session.get(VaProjectMaster, "PIIOT1") is None:
            db.session.add(VaProjectMaster(
                project_id="PIIOT1", project_code="PIIOT1",
                project_name="PII Out Of Scope", project_nickname="PiiOut",
                project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
            db.session.flush()
        user = self._make_user(f"pii.render.out.{uuid.uuid4().hex[:6]}@test.local", "PiiViewer123")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.collaborator_pii,
            scope_type=VaAccessScopeTypes.project,
            project_id="PIIOT1",
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self.assertTrue(user.is_viewer())  # the role gate opens; scope decides
        self._login(str(user.user_id))
        self.assertEqual(self.client.get(f"/coding/area/{self.VA_SID}").status_code, 403)
        for action in ("vaarea", "vadata"):
            with self.subTest(action=action):
                self.assertEqual(self._viewer_partial(action).status_code, 403)

    # ------------------------------------------------------------------
    # Reading is VIEW; every write partial asks its own write action
    # ------------------------------------------------------------------

    def test_coder_area_partials_load(self):
        """digitva-blp: the area rendering's partials returned 403 to a coder
        (the vadata validator was data-manager only), so the page stayed on
        "Loading...". A coder in viewing scope sees the data, PII included."""
        self._fresh_cache()
        self._login(str(self.base_coder_user.user_id))
        for action in ("vaarea", "vadata"):
            with self.subTest(action=action):
                response = self._viewer_partial(action)
                self.assertEqual(response.status_code, 200)
                body = response.get_data(as_text=True)
                self.assertIn(self.PUBLIC_VALUE, body)
                self.assertIn(self.PII_VALUE, body)

    def test_admin_reads_the_read_only_partials(self):
        """F11: admin opened the shells but every read partial refused."""
        self._login(self.base_admin_id)
        self.assertEqual(self._viewer_partial("vadata").status_code, 200)

    def test_data_manager_still_opens_the_triage_panel(self):
        self._login(self.dm_user_id)
        response = self.client.get(
            f"/vaform/{self.VA_SID}/vadmtriage",
            query_string={"action": "vadata", "actiontype": "vaview"},
        )
        self.assertEqual(response.status_code, 200)

    def test_viewer_reaches_no_write_partial(self):
        """Widening the read to viewers must not widen any write: each write
        partial requires its own action in the handler (design section 2.4)."""
        for role in (VaAccessRoles.collaborator, VaAccessRoles.collaborator_pii):
            self._login(self._viewer(role))
            # Present: the viewer may read this submission.
            self.assertEqual(self._viewer_partial("vadata").status_code, 200)
            headers = self._csrf_headers()
            for partial, action in (
                ("vadmtriage", "vadata"),
                ("vainitialasses", "vadata"),
                ("vafinalasses", "vadata"),
                ("vacoderreview", "vadata"),
                ("vareviewform", "vadata"),
                ("vausernote", "vadata"),
                ("vausernote", "vaarea"),
            ):
                with self.subTest(role=role.value, partial=partial, action=action):
                    response = self.client.post(
                        f"/vaform/{self.VA_SID}/{partial}",
                        query_string={"action": action, "actiontype": "vaview"},
                        data={"va_dmreview_reason": "other", "va_note_content": "x"},
                        headers=headers,
                    )
                    self.assertEqual(response.status_code, 403)
            with self.subTest(role=role.value, partial="vadmtriage", method="GET"):
                response = self.client.get(
                    f"/vaform/{self.VA_SID}/vadmtriage",
                    query_string={"action": "vadata", "actiontype": "vaview"},
                )
                self.assertEqual(response.status_code, 403)

    def test_read_only_renderings_refuse_the_coding_forms_on_get(self):
        """A read-only page has no coding forms. Their GET passed on VIEW
        alone and ran the DORIS prefill on the raw payload (Sex, DateBirth,
        DateDeath, EstimatedAge) for a plain collaborator."""
        self._fresh_cache()
        self._login(self._viewer(VaAccessRoles.collaborator))
        # Present: the viewer reads this submission and its read partials.
        for partial in ("cat1", "workflow_history", "vausernote"):
            with self.subTest(partial=partial):
                response = self.client.get(
                    f"/vaform/{self.VA_SID}/{partial}",
                    query_string={"action": "vaarea", "actiontype": "vaview"},
                )
                self.assertEqual(response.status_code, 200)
        with patch("app.routes.va_form._is_doris", return_value=True), patch(
            "app.services.doris_context_service.is_doris", return_value=True
        ), patch(
            "app.services.doris_context_service.doris_prefill_from_payload",
            return_value=({}, {}),
        ) as prefill:
            for action in ("vaarea", "vadata"):
                for partial in ("vainitialasses", "vafinalasses", "vacoderreview", "vareviewform"):
                    with self.subTest(action=action, partial=partial):
                        response = self.client.get(
                            f"/vaform/{self.VA_SID}/{partial}",
                            query_string={"action": action, "actiontype": "vaview"},
                        )
                        self.assertEqual(response.status_code, 403)
        prefill.assert_not_called()

    def test_doris_prefill_skips_a_redacting_viewer(self):
        """Defense in depth: the prefill reads interview facts from the raw
        payload, so a viewer the render redacts never gets it."""
        from app.services import doris_context_service

        submission = db.session.get(VaSubmissions, self.VA_SID)
        prefilled = ({"Sex": "female"}, {"Sex": "payload"})
        with patch.object(doris_context_service, "is_doris", return_value=True), patch.object(
            doris_context_service, "doris_prefill_from_payload", return_value=prefilled
        ) as prefill:
            # Present: a viewer entitled to PII gets the prefill.
            self.assertEqual(
                doris_context_service.doris_initial(None, submission, "doris", False), prefilled
            )
            self.assertEqual(
                doris_context_service.doris_initial(None, submission, "doris", True), ({}, {})
            )
        self.assertEqual(prefill.call_count, 1)

    def test_a_saved_certificate_loses_its_administrative_data_for_a_redacting_viewer(self):
        from app.services import doris_context_service

        saved = {
            "AdministrativeData": {"Sex": "female", "DateDeath": "2026-01-02"},
            "MedicalData": {"CauseA": "X"},
        }
        full, _ = doris_context_service.doris_initial(saved, None, "doris", False)
        self.assertIn("AdministrativeData", full)
        redacted, _ = doris_context_service.doris_initial(saved, None, "doris", True)
        self.assertNotIn("AdministrativeData", redacted)
        self.assertEqual(redacted["MedicalData"], {"CauseA": "X"})
        self.assertIn("AdministrativeData", saved)  # the stored certificate is untouched

    def test_invalidating_section_cache_drops_the_redacted_entry_too(self):
        from app import cache as flask_cache
        from app.services.case_content_service import (
            invalidate_section_data_cache,
            section_data_cache_key,
        )

        self._fresh_cache()
        version_id = db.session.get(VaSubmissions, self.VA_SID).active_payload_version_id
        self.assertIsNotNone(version_id)
        # Every role and PII variant of the current payload version goes.
        keys = [
            section_data_cache_key(self.VA_SID, version_id, role, "cat1", redacted=redacted)
            for role in ("coder", "reviewer", "data_manager", "viewer")
            for redacted in (False, True)
        ]
        for cache_key in keys:
            flask_cache.set(cache_key, {"stale": True})
            self.assertIsNotNone(flask_cache.get(cache_key))
        invalidate_section_data_cache(self.VA_SID)
        for cache_key in keys:
            self.assertIsNone(flask_cache.get(cache_key), cache_key)

    def test_triage_post_follows_triage_scope_not_the_role(self):
        """The vadmtriage POST checked is_data_manager() with no scope: a data
        manager of another pair who could read this submission (here through
        a viewer grant) could also triage it. TRIAGE is scoped to the
        submission."""
        from app.models import VaProjectMaster, VaSiteMaster

        now = datetime.now(UTC)
        if db.session.get(VaProjectMaster, "PIIOT1") is None:
            db.session.add(VaProjectMaster(
                project_id="PIIOT1", project_code="PIIOT1",
                project_name="PII Out Of Scope", project_nickname="PiiOut",
                project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
        if db.session.get(VaSiteMaster, "PIO1") is None:
            db.session.add(VaSiteMaster(
                site_id="PIO1", site_name="PII Out Site", site_abbr="PIO1",
                site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        other_pair = VaProjectSites(
            project_id="PIIOT1", site_id="PIO1",
            project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        )
        db.session.add(other_pair)
        db.session.flush()
        other_dm = self._make_user(f"pii.render.dm2.{uuid.uuid4().hex[:6]}@test.local", "PiiDm2123")
        db.session.add(VaUserAccessGrants(
            user_id=other_dm.user_id,
            role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=other_pair.project_site_id,
            grant_status=VaStatuses.active,
        ))
        db.session.add(VaUserAccessGrants(
            user_id=other_dm.user_id,
            role=VaAccessRoles.collaborator_pii,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.BASE_PROJECT_ID,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self.assertTrue(other_dm.is_data_manager())
        self._login(str(other_dm.user_id))
        # Present: the read passes, so the refusal below is TRIAGE's.
        self.assertEqual(self._viewer_partial("vadata").status_code, 200)
        response = self.client.post(
            f"/vaform/{self.VA_SID}/vadmtriage",
            query_string={"action": "vadata", "actiontype": "vaview"},
            data={"va_dmreview_reason": "other"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 403)

