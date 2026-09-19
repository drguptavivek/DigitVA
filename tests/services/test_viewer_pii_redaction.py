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
import csv
import io
from datetime import datetime, timezone
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
    VaUserAccessGrants,
)
from app.services.data_management_service import (
    COD_SNAPSHOT_STAFF_IDENTITY_HEADERS,
    dm_coded_cod_snapshot_export_csv,
    CSV_EXPORT_STAFF_IDENTITY_HEADERS,
    _dm_search_condition,
    _redact_staff_identity_export_row,
    _redact_staff_identity_row,
    dm_coder_daily_statistics,
    dm_submissions_export_csv,
    dm_submissions_page,
)
from app.services.submission_analytics_mv import COD_SNAPSHOT_MV_NAME
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


class RedactStaffIdentityExportRowTests(BaseTestCase):
    """_redact_staff_identity_export_row: the one place staff-identity CSV
    columns are blanked.

    The columns must be emptied, never dropped — the submissions export
    documents that downstream consumers depend on its column offsets, so a
    redacted export has to keep the same shape as an unredacted one.
    """

    def test_redact_true_empties_listed_columns_only(self):
        row = {
            "va_sid": "uuid:x",
            "final_assess_by": "5f1b0c3e-0000-0000-0000-000000000001",
            "final_conclusive_cod": "I21",
        }
        _redact_staff_identity_export_row(
            row, redact=True, headers=CSV_EXPORT_STAFF_IDENTITY_HEADERS
        )
        self.assertEqual(row["final_assess_by"], "")
        self.assertEqual(row["va_sid"], "uuid:x")
        self.assertEqual(row["final_conclusive_cod"], "I21")

    def test_redact_true_keeps_every_key(self):
        """Emptied, not dropped: the CSV column count must not change."""
        row = {header: "someone" for header in CSV_EXPORT_STAFF_IDENTITY_HEADERS}
        row["va_sid"] = "uuid:x"
        before = set(row)
        _redact_staff_identity_export_row(
            row, redact=True, headers=CSV_EXPORT_STAFF_IDENTITY_HEADERS
        )
        self.assertEqual(set(row), before)
        self.assertTrue(
            all(row[h] == "" for h in CSV_EXPORT_STAFF_IDENTITY_HEADERS)
        )

    def test_redact_false_leaves_row_untouched(self):
        row = {"final_assess_by": "someone", "coder_review_by": "someone else"}
        _redact_staff_identity_export_row(
            row, redact=False, headers=CSV_EXPORT_STAFF_IDENTITY_HEADERS
        )
        self.assertEqual(row["final_assess_by"], "someone")
        self.assertEqual(row["coder_review_by"], "someone else")

    def test_absent_column_is_not_created(self):
        """A row that never carried the column must not gain an empty one."""
        row = {"va_sid": "uuid:x"}
        _redact_staff_identity_export_row(
            row, redact=True, headers=CSV_EXPORT_STAFF_IDENTITY_HEADERS
        )
        self.assertEqual(row, {"va_sid": "uuid:x"})

    def test_snapshot_headers_cover_every_staff_name_column(self):
        """Guard against a name column being added to the snapshot export and
        silently escaping redaction: every MV column ending in ``_name`` that
        holds a va_users.name is listed."""
        self.assertEqual(
            COD_SNAPSHOT_STAFF_IDENTITY_HEADERS,
            frozenset({
                "coder_name",
                "reviewer_name",
                "nqa_name",
                "social_autopsy_name",
                "active_coder_assigned_name",
                "active_reviewer_assigned_name",
            }),
        )


class DmSubmissionsExportStaffIdentityTests(BaseTestCase):
    """End-to-end through dm_submissions_export_csv.

    A redacted viewer cannot be built end-to-end today: dm_scope_filter
    resolves visible project/site pairs from data_manager grants only, and a
    data_manager grant is itself PII-granting, so any user who can see a row
    is by construction unredacted (see module docstring). The redacted branch
    is therefore reached by patching the single decision point where the
    export calls it — which is also the thing worth asserting: that the
    export consults should_redact_pii at all, rather than deciding locally.
    """

    PROJECT = "VEX001"
    SITE = "VE01"
    FORM_ID = "VEX01VE0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Viewer PII Export Project",
                project_nickname="ViewerPiiExport",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        if db.session.get(VaSiteMaster, cls.SITE) is None:
            db.session.add(VaSiteMaster(
                site_id=cls.SITE,
                site_name="Viewer PII Export Site",
                site_abbr=cls.SITE,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
        if db.session.get(VaResearchProjects, cls.PROJECT) is None:
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Viewer PII Export Project",
                project_nickname="ViewerPiiExport",
                project_status=VaStatuses.active,
            ))
        db.session.flush()
        if db.session.get(VaSites, cls.SITE) is None:
            db.session.add(VaSites(
                site_id=cls.SITE,
                project_id=cls.PROJECT,
                site_name="Viewer PII Export Site",
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
                odk_form_id="VEX_FORM",
                odk_project_id="299",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
        db.session.commit()

        cls.dm_user = cls._get_or_make_user("vex.dm@test.local", "VexDm123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.dm_user.user_id,
            role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project,
            project_id=cls.PROJECT,
            grant_status=VaStatuses.active,
        ))

        # The coder whose identity must survive one export and not the other.
        cls.coder_user = cls._get_or_make_user("vex.coder@test.local", "VexCoder123")

        cls.va_sid = "uuid:viewer-pii-export-1"
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
            # Populates final_assess_by, so the redaction assertion below is
            # not vacuously true against an all-NULL column.
            db.session.add(VaFinalAssessments(
                va_sid=cls.va_sid,
                va_finassess_by=cls.coder_user.user_id,
                va_conclusive_cod="I21 Acute myocardial infarction",
                va_finassess_status=VaStatuses.active,
                va_finassess_createdat=now,
                va_finassess_updatedat=now,
            ))
        db.session.commit()

    def _export_rows(self, csv_text):
        reader = csv.DictReader(io.StringIO(csv_text))
        return [r for r in reader if r["va_sid"] == self.va_sid]

    def test_unredacted_export_carries_staff_identity(self):
        """Non-vacuity guard: the column is populated when not redacting."""
        rows = self._export_rows(dm_submissions_export_csv(self.dm_user))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["final_assess_by"], str(self.coder_user.user_id))

    @patch("app.services.data_management_service.should_redact_pii", return_value=True)
    def test_redacted_export_blanks_every_staff_identity_column(self, _mock):
        csv_text = dm_submissions_export_csv(self.dm_user)
        rows = self._export_rows(csv_text)
        self.assertEqual(len(rows), 1)
        for header in CSV_EXPORT_STAFF_IDENTITY_HEADERS:
            self.assertEqual(rows[0][header], "", f"{header} was not redacted")
        self.assertNotIn(str(self.coder_user.user_id), csv_text)

    @patch("app.services.data_management_service.should_redact_pii", return_value=True)
    def test_redacted_export_keeps_the_same_columns(self, _mock):
        """Column order and offsets are a downstream contract: redaction
        empties cells, it must not drop or reorder headers."""
        redacted = dm_submissions_export_csv(self.dm_user)
        with patch(
            "app.services.data_management_service.should_redact_pii",
            return_value=False,
        ):
            unredacted = dm_submissions_export_csv(self.dm_user)
        self.assertEqual(
            redacted.splitlines()[0], unredacted.splitlines()[0]
        )

    @patch("app.services.data_management_service.should_redact_pii", return_value=True)
    def test_redacted_export_keeps_non_identity_columns(self, _mock):
        """Redaction is narrow: the coded cause of death still exports."""
        rows = self._export_rows(dm_submissions_export_csv(self.dm_user))
        self.assertEqual(
            rows[0]["final_conclusive_cod"], "I21 Acute myocardial infarction"
        )
        self.assertEqual(rows[0]["workflow_state"], WORKFLOW_CODER_FINALIZED)

    # ---------------------------------------------------------------
    # dm_coded_cod_snapshot_export_csv — .tasks/viewer-pii-roles.md, "Two
    # surfaces still unredacted" (2): it emitted coder, reviewer, NQA,
    # social autopsy and allocation names as plain columns with no
    # redaction at all. The fixture's active VaFinalAssessments row is what
    # the snapshot MV coalesces into `coder_name`, so there is a real name
    # to redact rather than an all-NULL column. The MV is dropped first
    # because the class transaction rolls back DDL, so a test that queries
    # it must let the export build it.
    # ---------------------------------------------------------------

    def _snapshot_rows(self):
        db.session.execute(
            sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {COD_SNAPSHOT_MV_NAME} CASCADE")
        )
        db.session.commit()
        csv_text = dm_coded_cod_snapshot_export_csv(self.dm_user)
        reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
        return csv_text, [r for r in reader if r["va_sid"] == self.va_sid]

    def test_unredacted_snapshot_carries_the_coder_name(self):
        """Non-vacuity guard: there is a staff name here to redact."""
        _csv_text, rows = self._snapshot_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["coder_name"], self.coder_user.name)

    @patch("app.services.data_management_service.should_redact_pii", return_value=True)
    def test_redacted_snapshot_blanks_every_staff_name(self, _mock):
        csv_text, rows = self._snapshot_rows()
        self.assertEqual(len(rows), 1)
        for header in COD_SNAPSHOT_STAFF_IDENTITY_HEADERS:
            self.assertEqual(rows[0][header], "", f"{header} was not redacted")
        self.assertNotIn(self.coder_user.name, csv_text)

    @patch("app.services.data_management_service.should_redact_pii", return_value=True)
    def test_redacted_snapshot_keeps_the_coded_cause_of_death(self, _mock):
        """Redaction is narrow: what the export exists for still exports."""
        _csv_text, rows = self._snapshot_rows()
        self.assertEqual(
            rows[0]["authoritative_cod_text"], "I21 Acute myocardial infarction"
        )


class DmCoderDailyStatisticsRedactionTests(BaseTestCase):
    """dm_coder_daily_statistics: every row is a named coder and their
    throughput, so a redacted viewer gets no rows rather than pseudonymized
    ones — an opaque but stable coder_id would re-identify across days."""

    PROJECT = "VCD001"
    SITE = "VC01"
    FORM_ID = "VCD01VC0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if db.session.get(VaProjectMaster, cls.PROJECT) is None:
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Viewer PII Coder Stats Project",
                project_nickname="ViewerPiiCoderStats",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        if db.session.get(VaSiteMaster, cls.SITE) is None:
            db.session.add(VaSiteMaster(
                site_id=cls.SITE,
                site_name="Viewer PII Coder Stats Site",
                site_abbr=cls.SITE,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
        if db.session.get(VaResearchProjects, cls.PROJECT) is None:
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="Viewer PII Coder Stats Project",
                project_nickname="ViewerPiiCoderStats",
                project_status=VaStatuses.active,
            ))
        db.session.flush()
        if db.session.get(VaSites, cls.SITE) is None:
            db.session.add(VaSites(
                site_id=cls.SITE,
                project_id=cls.PROJECT,
                site_name="Viewer PII Coder Stats Site",
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
                odk_form_id="VCD_FORM",
                odk_project_id="399",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
        db.session.commit()

        cls.dm_user = cls._get_or_make_user("vcd.dm@test.local", "VcdDm123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.dm_user.user_id,
            role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project,
            project_id=cls.PROJECT,
            grant_status=VaStatuses.active,
        ))
        cls.coder_user = cls._get_or_make_user("vcd.coder@test.local", "VcdCoder123")

        cls.va_sid = "uuid:viewer-pii-coder-stats-1"
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
            db.session.add(VaSubmissionWorkflowEvent(
                va_sid=cls.va_sid,
                transition_id="coder_finalized",
                previous_state=None,
                current_state=WORKFLOW_CODER_FINALIZED,
                actor_user_id=cls.coder_user.user_id,
                event_created_at=now,
            ))
        db.session.commit()

    def test_unredacted_stats_name_the_coder(self):
        """Non-vacuity guard: there is a row to redact in the first place."""
        result = dm_coder_daily_statistics(self.dm_user)
        coder_ids = {row["coder_id"] for row in result["rows"]}
        self.assertIn(str(self.coder_user.user_id), coder_ids)
        self.assertFalse(result["staff_identity_redacted"])

    @patch("app.services.data_management_service.should_redact_pii", return_value=True)
    def test_redacted_stats_return_no_rows(self, _mock):
        result = dm_coder_daily_statistics(self.dm_user)
        self.assertEqual(result["rows"], [])
        self.assertTrue(result["staff_identity_redacted"])

    @patch("app.services.data_management_service.should_redact_pii", return_value=True)
    def test_redacted_stats_keep_the_response_shape(self, _mock):
        """The dashboard renders the date header before the rows arrive, so
        the window must survive redaction even though the rows do not."""
        result = dm_coder_daily_statistics(self.dm_user, days=7)
        self.assertEqual(len(result["dates"]), 7)
        self.assertEqual(result["window_days"], 7)
        self.assertTrue(result["timezone"])


