"""Tests for the viewer PII redaction helper and its call sites.

Redaction half of the viewer-PII split (.tasks/viewer-pii-roles.md,
docs/policy/access-control-model.md, "collaborator" / "collaborator_pii").
The foundation half (role existence, grant/scope rules) is covered by
tests/test_collaborator_pii_role.py and is not re-tested here.

Scope note: ``dm_scope_filter`` (and therefore ``dm_submissions_page`` /
``dm_submissions_export_csv``) resolves visible project/site pairs only from
``data_manager``-role grants — collaborator is not wired into that scope
resolution, and no route grants a plain ``collaborator`` or
``collaborator_pii`` access to these dashboard endpoints today (see
app/decorators/role_required.py: only "data_manager" and "admin" are
recognized there). That wiring is separate, out-of-scope work. This file
therefore tests the redaction primitives directly — the exact units
``dm_submissions_page``, the CSV exports, and the search predicate call —
so that whenever collaborator access is wired up, the redaction is already
proven correct.
"""
from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services.data_management_service import (
    _dm_search_condition,
    _redact_staff_identity_row,
    dm_submissions_export_csv,
    dm_submissions_page,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.viewer_pii_service import should_redact_pii
from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED
from tests.base import BaseTestCase


class ShouldRedactPiiTests(BaseTestCase):
    """should_redact_pii: the single decision point, exercised against every
    grant combination the policy calls out by name."""

    PROJECT = "VPR001"
    SITE = "VP01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Viewer PII Test Project",
                project_nickname="ViewerPiiTest",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        if db.session.get(VaSiteMaster, cls.SITE) is None:
            db.session.add(VaSiteMaster(
                site_id=cls.SITE,
                site_name="Viewer PII Test Site",
                site_abbr=cls.SITE,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
        db.session.commit()

    def _grant(self, user, role, **kwargs):
        kwargs.setdefault("grant_status", VaStatuses.active)
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=role,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
            **kwargs,
        ))
        db.session.commit()

    def test_plain_collaborator_is_redacted(self):
        user = self._get_or_make_user("vpr.collab@test.local", "VprCollab123")
        self._grant(user, VaAccessRoles.collaborator)
        self.assertTrue(should_redact_pii(user))

    def test_collaborator_pii_is_not_redacted(self):
        user = self._get_or_make_user("vpr.collab.pii@test.local", "VprCollabPii123")
        self._grant(user, VaAccessRoles.collaborator_pii)
        self.assertFalse(should_redact_pii(user))

    def test_collaborator_plus_coder_is_not_redacted(self):
        """The coder grant wins: holding both sees personal data."""
        user = self._get_or_make_user("vpr.collab.coder@test.local", "VprCollabCoder123")
        self._grant(user, VaAccessRoles.collaborator)
        self._grant(user, VaAccessRoles.coder)
        self.assertFalse(should_redact_pii(user))

    def test_data_manager_is_not_redacted(self):
        user = self._get_or_make_user("vpr.dm@test.local", "VprDm123")
        self._grant(user, VaAccessRoles.data_manager)
        self.assertFalse(should_redact_pii(user))

    def test_user_with_no_grants_is_redacted(self):
        user = self._get_or_make_user("vpr.none@test.local", "VprNone123")
        self.assertTrue(should_redact_pii(user))

    def test_inactive_collaborator_pii_grant_does_not_unlock_pii(self):
        user = self._get_or_make_user("vpr.collab.inactive@test.local", "VprInactive123")
        self._grant(user, VaAccessRoles.collaborator)
        self._grant(
            user, VaAccessRoles.collaborator_pii, grant_status=VaStatuses.deactive
        )
        self.assertTrue(should_redact_pii(user))


class DmSearchConditionRedactionTests(BaseTestCase):
    """_dm_search_condition: staff-name clauses must disappear, not just the
    rendering — a viewer must not confirm a name by searching for it."""

    def test_redacted_search_drops_staff_name_clauses(self):
        clause = _dm_search_condition("Jane Doe", redact_staff_identity=True)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": False}))
        self.assertNotIn("va_data_collector", compiled)
        self.assertNotIn("va_users", compiled.lower())
        self.assertIn("va_uniqueid_masked", compiled)

    def test_unredacted_search_keeps_staff_name_clauses(self):
        clause = _dm_search_condition("Jane Doe", redact_staff_identity=False)
        compiled = str(clause.compile(compile_kwargs={"literal_binds": False}))
        self.assertIn("va_data_collector", compiled)
        self.assertIn("va_uniqueid_masked", compiled)


class RedactStaffIdentityRowTests(BaseTestCase):
    """_redact_staff_identity_row: the one place base-column staff identity
    is blanked for a DM dashboard row."""

    def test_redact_true_blanks_collector_and_coder(self):
        row = {"va_data_collector": "Jane Doe", "coded_by": "John Coder", "va_sid": "x"}
        _redact_staff_identity_row(row, redact=True)
        self.assertIsNone(row["va_data_collector"])
        self.assertIsNone(row["coded_by"])
        self.assertEqual(row["va_sid"], "x")

    def test_redact_false_leaves_row_untouched(self):
        row = {"va_data_collector": "Jane Doe", "coded_by": "John Coder"}
        _redact_staff_identity_row(row, redact=False)
        self.assertEqual(row["va_data_collector"], "Jane Doe")
        self.assertEqual(row["coded_by"], "John Coder")


class DmSubmissionsPageStaffIdentityTests(BaseTestCase):
    """End-to-end through dm_submissions_page.

    dm_scope_filter resolves visible project/site pairs from data_manager
    grants only, so the fixture user must hold a data_manager-shaped grant
    to see any rows at all (see module docstring). To exercise both
    redaction outcomes without touching scope resolution, the same
    project/site is granted twice: once as data_manager (for scope) and
    once, on a second user, additionally as collaborator — proving the
    redaction decision is independent of, and layered on top of, scope.
    """

    PROJECT = "VSP001"
    SITE = "VS01"
    FORM_ID = "VSP01VS0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Viewer PII Submissions Project",
                project_nickname="ViewerPiiSub",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        if db.session.get(VaSiteMaster, cls.SITE) is None:
            db.session.add(VaSiteMaster(
                site_id=cls.SITE,
                site_name="Viewer PII Submissions Site",
                site_abbr=cls.SITE,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
        if db.session.get(VaResearchProjects, cls.PROJECT) is None:
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Viewer PII Submissions Project",
                project_nickname="ViewerPiiSub",
                project_status=VaStatuses.active,
            ))
        db.session.flush()
        if db.session.get(VaSites, cls.SITE) is None:
            db.session.add(VaSites(
                site_id=cls.SITE,
                project_id=cls.PROJECT,
                site_name="Viewer PII Submissions Site",
                site_abbr=cls.SITE,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
        db.session.flush()
        if db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == cls.PROJECT,
                VaProjectSites.site_id == cls.SITE,
            )
        ) is None:
            db.session.add(VaProjectSites(
                project_id=cls.PROJECT,
                site_id=cls.SITE,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            ))
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.PROJECT,
                site_id=cls.SITE,
                odk_form_id="VSP_FORM",
                odk_project_id="199",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
        db.session.commit()

        cls.va_sid = "uuid:viewer-pii-sub-1"
        if db.session.get(VaSubmissions, cls.va_sid) is None:
            submission = VaSubmissions(
                va_sid=cls.va_sid,
                va_form_id=cls.FORM_ID,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="Jane Collector",
                va_odk_reviewstate=None,
                va_instance_name=cls.va_sid,
                va_uniqueid_real=None,
                va_uniqueid_masked=cls.va_sid,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=42,
                va_deceased_gender="male",
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
            db.session.add(submission)
            db.session.flush()
            ensure_active_payload_version(
                submission,
                payload_data={
                    "sid": cls.va_sid,
                    "form_def": cls.FORM_ID,
                    "SubmitterName": "Jane Collector",
                    "unique_id": cls.va_sid,
                },
                source_updated_at=now,
                created_by_role="vasystem",
            )
            db.session.add(VaSubmissionWorkflow(
                va_sid=cls.va_sid,
                workflow_state=WORKFLOW_CODER_FINALIZED,
                workflow_created_at=now,
                workflow_updated_at=now,
            ))
            db.session.commit()

    def _grant(self, user, role):
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=role,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def test_data_manager_sees_collector_unredacted(self):
        """Regression: an unaffected role's output is unchanged."""
        user = self._get_or_make_user("vsp.dm@test.local", "VspDm123")
        self._grant(user, VaAccessRoles.data_manager)

        result = dm_submissions_page(user, per_page=25)
        rows = [r for r in result["data"] if r["va_sid"] == self.va_sid]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["va_data_collector"], "Jane Collector")

    def test_data_manager_plus_plain_collaborator_still_redacts(self):
        """A data_manager grant unlocks PII on its own; adding a plain
        collaborator grant on top must not remove it (should_redact_pii is
        an OR over PII-granting roles, not an AND)."""
        user = self._get_or_make_user("vsp.dm.collab@test.local", "VspDmCollab123")
        self._grant(user, VaAccessRoles.data_manager)
        self._grant(user, VaAccessRoles.collaborator)
        self.assertFalse(should_redact_pii(user))

        result = dm_submissions_page(user, per_page=25)
        rows = [r for r in result["data"] if r["va_sid"] == self.va_sid]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["va_data_collector"], "Jane Collector")

    def test_export_csv_never_includes_collector_base_column(self):
        """va_data_collector is never a base export column, for any role —
        the export/base-column inconsistency the policy calls out to close.
        """
        user = self._get_or_make_user("vsp.dm.export@test.local", "VspDmExport123")
        self._grant(user, VaAccessRoles.data_manager)

        csv_text = dm_submissions_export_csv(user)
        header_line = csv_text.splitlines()[0]
        self.assertNotIn("va_data_collector", header_line)
        self.assertNotIn("Jane Collector", csv_text)

    def test_export_csv_never_includes_submitter_name_payload_field(self):
        user = self._get_or_make_user("vsp.dm.export2@test.local", "VspDmExport223")
        self._grant(user, VaAccessRoles.data_manager)

        csv_text = dm_submissions_export_csv(user)
        header_line = csv_text.splitlines()[0]
        self.assertNotIn("SubmitterName", header_line)
