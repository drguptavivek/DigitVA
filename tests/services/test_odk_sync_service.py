from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaForms,
    VaInitialAssessments,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from app.models.va_submission_payload_versions import (
    PAYLOAD_VERSION_STATUS_ACTIVE,
    PAYLOAD_VERSION_STATUS_SUPERSEDED,
)
from app.services.odk_connection_guard_service import OdkConnectionCooldownError
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    SYNC_ISSUE_MISSING_IN_ODK,
    _attach_all_odk_comments,
    _release_active_allocations_after_sync,
    _mark_form_sync_issues,
    _upsert_form_submissions,
)
from app.services.workflow.definition import (
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_SMARTVA_PENDING,
)
from app.services.workflow.state_store import set_submission_workflow_state
from tests.base import BaseTestCase


class OdkSyncServiceTests(BaseTestCase):
    FORM_ID = "SYNC01BS0101"
    PROJECT_ID = "SYNC01"
    SITE_ID = "BS02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Sync Test Project",
                project_nickname="SyncTest",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.add(
            VaResearchProjects(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Sync Test Project",
                project_nickname="SyncTest",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.add(
            VaSiteMaster(
                site_id=cls.SITE_ID,
                site_name="Sync Test Site",
                site_abbr=cls.SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSites(
                site_id=cls.SITE_ID,
                project_id=cls.PROJECT_ID,
                site_name="Sync Test Site",
                site_abbr=cls.SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectSites(
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
        )
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                odk_form_id="SYNC_TEST_FORM",
                odk_project_id="11",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.commit()

    def _record(self, instance_id: str, consent):
        now = datetime.now(timezone.utc)
        return {
            "KEY": instance_id,
            "sid": f"{instance_id}-{self.FORM_ID.lower()}",
            "form_def": self.FORM_ID,
            "SubmissionDate": now.isoformat(),
            "updatedAt": now.isoformat(),
            "SubmitterName": "Collector",
            "ReviewState": "hasIssues",
            "instanceName": instance_id,
            "unique_id": instance_id,
            "unique_id2": f"{instance_id}-masked",
            "Id10013": consent,
            "language": "English",
            "finalAgeInYears": "42",
            "Id10019": "male",
            "isNeonatal": "0",
            "isChild": "0",
            "isAdult": "1",
        }

    def test_upsert_includes_submissions_without_positive_consent(self):
        amended_sids = set()
        added, updated, discarded, skipped = _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [
                self._record("uuid:sync-consent-no", "no"),
                self._record("uuid:sync-consent-missing", None),
            ],
            amended_sids,
            {},
        )
        db.session.commit()

        self.assertEqual((added, updated, discarded, skipped), (2, 0, 0, 0))
        rows = db.session.execute(
            db.select(VaSubmissions.va_sid, VaSubmissions.va_consent).where(
                VaSubmissions.va_sid.in_(
                    [
                        f"uuid:sync-consent-no-{self.FORM_ID.lower()}",
                        f"uuid:sync-consent-missing-{self.FORM_ID.lower()}",
                    ]
                )
            )
        ).all()
        self.assertEqual(len(rows), 2)
        consent_map = {sid: consent for sid, consent in rows}
        self.assertEqual(
            consent_map[f"uuid:sync-consent-no-{self.FORM_ID.lower()}"], "no"
        )
        self.assertEqual(
            consent_map[f"uuid:sync-consent-missing-{self.FORM_ID.lower()}"], ""
        )

    def test_upsert_sets_consented_submission_to_smartva_pending(self):
        amended_sids = set()
        sid = f"uuid:sync-consent-yes-{self.FORM_ID.lower()}"

        _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [self._record("uuid:sync-consent-yes", "yes")],
            amended_sids,
            {},
        )
        db.session.commit()

        workflow_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == sid
            )
        )
        self.assertEqual(workflow_state, WORKFLOW_SMARTVA_PENDING)

    def test_upsert_creates_active_payload_version_for_new_submission(self):
        amended_sids = set()
        sid = f"uuid:sync-payload-new-{self.FORM_ID.lower()}"

        _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [self._record("uuid:sync-payload-new", "yes")],
            amended_sids,
            {},
        )
        db.session.commit()

        submission = db.session.get(VaSubmissions, sid)
        self.assertIsNotNone(submission.active_payload_version_id)

        versions = db.session.scalars(
            db.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == sid
            )
        ).all()
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].version_status, PAYLOAD_VERSION_STATUS_ACTIVE)
        self.assertEqual(
            versions[0].payload_version_id,
            submission.active_payload_version_id,
        )
        self.assertEqual(versions[0].payload_data.get("sid"), sid)

    def test_changed_payload_creates_new_active_payload_version(self):
        amended_sids = set()
        sid = f"uuid:sync-payload-changed-{self.FORM_ID.lower()}"

        initial = self._record("uuid:sync-payload-changed", "yes")
        _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [initial],
            amended_sids,
            {},
        )
        db.session.commit()

        original_submission = db.session.get(VaSubmissions, sid)
        original_active_id = original_submission.active_payload_version_id

        updated = dict(initial)
        updated["updatedAt"] = datetime.now(timezone.utc).isoformat()
        updated["finalAgeInYears"] = "47"

        _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [updated],
            amended_sids,
            {},
        )
        db.session.commit()

        refreshed_submission = db.session.get(VaSubmissions, sid)
        self.assertNotEqual(
            refreshed_submission.active_payload_version_id,
            original_active_id,
        )

        versions = db.session.scalars(
            db.select(VaSubmissionPayloadVersion)
            .where(VaSubmissionPayloadVersion.va_sid == sid)
            .order_by(VaSubmissionPayloadVersion.version_created_at.asc())
        ).all()
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0].version_status, PAYLOAD_VERSION_STATUS_SUPERSEDED)
        self.assertEqual(versions[1].version_status, PAYLOAD_VERSION_STATUS_ACTIVE)
        self.assertEqual(
            versions[1].payload_version_id,
            refreshed_submission.active_payload_version_id,
        )
        self.assertEqual(versions[1].payload_data.get("finalAgeInYears"), "47")

        workflow_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == sid
            )
        )
        self.assertEqual(workflow_state, WORKFLOW_SMARTVA_PENDING)

    def test_unchanged_payload_does_not_create_new_payload_version(self):
        amended_sids = set()
        sid = f"uuid:sync-payload-same-{self.FORM_ID.lower()}"

        record = self._record("uuid:sync-payload-same", "yes")
        _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [record],
            amended_sids,
            {},
        )
        db.session.commit()

        original_submission = db.session.get(VaSubmissions, sid)
        original_active_id = original_submission.active_payload_version_id

        _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [dict(record)],
            amended_sids,
            {},
        )
        db.session.commit()

        refreshed_submission = db.session.get(VaSubmissions, sid)
        versions = db.session.scalars(
            db.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == sid
            )
        ).all()
        self.assertEqual(len(versions), 1)
        self.assertEqual(
            refreshed_submission.active_payload_version_id,
            original_active_id,
        )

    def test_release_allocations_after_sync_preserves_smartva_pending(self):
        sid = f"uuid:sync-release-pending-{self.FORM_ID.lower()}"
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=self.FORM_ID,
                va_submission_date=datetime.now(timezone.utc),
                va_odk_updatedat=datetime.now(timezone.utc),
                va_data_collector="Collector",
                va_odk_reviewstate=None,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=42,
                va_deceased_gender="male",
                va_uniqueid_masked="masked",
                va_data={"sid": sid},
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
        set_submission_workflow_state(
            sid,
            WORKFLOW_SMARTVA_PENDING,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.add(
            VaAllocations(
                va_sid=sid,
                va_allocated_to=self.base_coder_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            )
        )
        db.session.add(
            VaInitialAssessments(
                va_sid=sid,
                va_iniassess_by=self.base_coder_user.user_id,
                va_immediate_cod="R99",
                va_antecedent_cod="R99",
                va_iniassess_status=VaStatuses.active,
            )
        )
        db.session.commit()

        _release_active_allocations_after_sync()

        workflow_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == sid
            )
        )
        allocation_status = db.session.scalar(
            db.select(VaAllocations.va_allocation_status).where(
                VaAllocations.va_sid == sid
            )
        )
        initial_status = db.session.scalar(
            db.select(VaInitialAssessments.va_iniassess_status).where(
                VaInitialAssessments.va_sid == sid
            )
        )
        self.assertEqual(workflow_state, WORKFLOW_SMARTVA_PENDING)
        self.assertEqual(allocation_status, VaStatuses.deactive)
        self.assertEqual(initial_status, VaStatuses.deactive)

    def test_release_allocations_after_sync_resets_incomplete_first_pass_state(self):
        sid = f"uuid:sync-release-coding-{self.FORM_ID.lower()}"
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=self.FORM_ID,
                va_submission_date=datetime.now(timezone.utc),
                va_odk_updatedat=datetime.now(timezone.utc),
                va_data_collector="Collector",
                va_odk_reviewstate=None,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=42,
                va_deceased_gender="male",
                va_uniqueid_masked="masked",
                va_data={"sid": sid},
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
        set_submission_workflow_state(
            sid,
            WORKFLOW_CODING_IN_PROGRESS,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.add(
            VaAllocations(
                va_sid=sid,
                va_allocated_to=self.base_coder_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            )
        )
        db.session.add(
            VaInitialAssessments(
                va_sid=sid,
                va_iniassess_by=self.base_coder_user.user_id,
                va_immediate_cod="R99",
                va_antecedent_cod="R99",
                va_iniassess_status=VaStatuses.active,
            )
        )
        db.session.commit()

        _release_active_allocations_after_sync()

        workflow_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == sid
            )
        )
        self.assertEqual(workflow_state, WORKFLOW_READY_FOR_CODING)

    def test_mark_form_sync_issues_flags_local_records_missing_in_odk(self):
        sid = f"uuid:sync-orphan-{self.FORM_ID.lower()}"
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=self.FORM_ID,
                va_submission_date=datetime.now(timezone.utc),
                va_odk_updatedat=datetime.now(timezone.utc),
                va_data_collector="Collector",
                va_odk_reviewstate=None,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=42,
                va_deceased_age_normalized_days=Decimal("15340.5"),
                va_deceased_age_normalized_years=Decimal("42"),
                va_deceased_age_source="finalAgeInYears",
                va_deceased_gender="male",
                va_uniqueid_masked="masked",
                va_data={"sid": sid},
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.commit()

        _mark_form_sync_issues(
            db.session.get(VaForms, self.FORM_ID),
            ["uuid:some-other-instance"],
        )
        db.session.commit()

        stored = db.session.get(VaSubmissions, sid)
        self.assertEqual(stored.va_sync_issue_code, SYNC_ISSUE_MISSING_IN_ODK)

    def test_attach_all_odk_comments_adds_all_has_issues_comments(self):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"body": "Older review note", "createdAt": "2026-03-17T10:00:00+00:00"},
            {"body": "Newest review note", "createdAt": "2026-03-18T12:00:00+00:00"},
        ]
        client = Mock()
        client.session.get.return_value = mock_response
        # No connection_id tagged — guarded_odk_call passes through directly
        del client._digitva_connection_id

        submissions = _attach_all_odk_comments(
            db.session.get(VaForms, self.FORM_ID),
            [self._record("uuid:sync-comment", "yes")],
            client=client,
        )

        self.assertEqual(
            submissions[0]["OdkReviewComments"],
            [
                {
                    "body": "Newest review note",
                    "created_at": "2026-03-18T12:00:00+00:00",
                },
                {
                    "body": "Older review note",
                    "created_at": "2026-03-17T10:00:00+00:00",
                },
            ],
        )

    def test_upsert_persists_all_odk_review_comments(self):
        amended_sids = set()
        record = self._record("uuid:sync-comment-store", "yes")
        record["OdkReviewComments"] = [
            {"body": "Field team should fix respondent age."},
            {"body": "Village name is missing."},
        ]

        _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [record],
            amended_sids,
            {},
        )
        db.session.commit()

        stored = db.session.get(
            VaSubmissions,
            f"uuid:sync-comment-store-{self.FORM_ID.lower()}",
        )
        self.assertEqual(
            stored.va_odk_reviewcomments,
            [
                {"body": "Field team should fix respondent age."},
                {"body": "Village name is missing."},
            ],
        )

    def test_upsert_populates_normalized_age_fields_with_policy_precedence(self):
        amended_sids = set()
        record = self._record("uuid:sync-age-normalized", "yes")
        record.update(
            {
                "age_neonate_days": "",
                "age_neonate_hours": "",
                "ageInDays": "45",
                "ageInMonths": "1",
                "ageInYears": "99",
                "ageInYears2": "2",
                "finalAgeInYears": "2.0",
                "isNeonatal": "0",
                "isChild": "1",
                "isAdult": "0",
            }
        )

        _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [record],
            amended_sids,
            {},
        )
        db.session.commit()

        stored = db.session.get(
            VaSubmissions,
            f"uuid:sync-age-normalized-{self.FORM_ID.lower()}",
        )
        self.assertEqual(stored.va_deceased_age, 2)
        self.assertEqual(stored.va_deceased_age_source, "ageInDays")
        self.assertEqual(stored.va_deceased_age_normalized_days, Decimal("45"))
        self.assertEqual(
            stored.va_deceased_age_normalized_years,
            Decimal("45") / Decimal("365.25"),
        )

    # ── _attach_all_odk_comments cooldown/error behaviour ──────────────────────

    def test_attach_all_odk_comments_reraises_cooldown_error(self):
        """OdkConnectionCooldownError from a comment fetch must propagate up
        so the per-form handler can record the connection in cooldown."""
        cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=5)
        client = Mock()
        client.session.get.side_effect = OdkConnectionCooldownError(
            "test-conn", cooldown_until, "connect timeout"
        )
        del client._digitva_connection_id

        with self.assertRaises(OdkConnectionCooldownError):
            _attach_all_odk_comments(
                db.session.get(VaForms, self.FORM_ID),
                [self._record("uuid:sync-cooldown-comment", "yes")],
                client=client,
            )

    def test_attach_all_odk_comments_swallows_transient_per_submission_error(self):
        """Non-cooldown errors on a single submission's comment fetch must
        be swallowed so one bad submission does not abort the whole form."""
        ok_response = Mock()
        ok_response.status_code = 200
        ok_response.json.return_value = [{"body": "ok comment", "createdAt": "2026-03-24T10:00:00Z"}]

        call_count = {"n": 0}

        def _side_effect(*_args, **_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionError("transient network error")
            return ok_response

        client = Mock()
        client.session.get.side_effect = _side_effect
        del client._digitva_connection_id

        submissions = _attach_all_odk_comments(
            db.session.get(VaForms, self.FORM_ID),
            [
                self._record("uuid:sync-err-sub1", "yes"),  # will error
                self._record("uuid:sync-err-sub2", "yes"),  # should succeed
            ],
            client=client,
        )

        # First submission: errored — empty comments
        self.assertEqual(submissions[0]["OdkReviewComments"], [])
        # Second submission: succeeded despite first error
        self.assertEqual(len(submissions[1]["OdkReviewComments"]), 1)
        self.assertEqual(submissions[1]["OdkReviewComments"][0]["body"], "ok comment")

    def test_attach_all_odk_comments_skips_non_has_issues_submissions(self):
        """Submissions not in hasIssues ReviewState must never call ODK."""
        client = Mock()
        del client._digitva_connection_id

        record = self._record("uuid:sync-no-issues", "yes")
        record["ReviewState"] = "approved"

        _attach_all_odk_comments(
            db.session.get(VaForms, self.FORM_ID),
            [record],
            client=client,
        )

        client.session.get.assert_not_called()
        self.assertEqual(record["OdkReviewComments"], [])


class OdkSyncLoopCooldownTests(BaseTestCase):
    """Tests for connection-level cooldown short-circuit in va_data_sync_odkcentral.

    Uses patches to avoid real ODK calls. Verifies:
    - OdkConnectionCooldownError from a form → connection added to in-cooldown set
    - Subsequent forms on same connection skipped without touching ODK
    - Forms on different connection are unaffected
    """

    def _run_sync_with_mock_forms(self, form_behaviors: dict):
        """Run va_data_sync_odkcentral with controlled per-form ODK responses.

        form_behaviors: {form_id: callable(client) -> None or raise}
        Returns (added, updated, failed_form_ids, cooldown_skipped_form_ids).
        """
        from app.services.va_data_sync.va_data_sync_01_odkcentral import (
            va_data_sync_odkcentral,
        )
        import uuid

        conn_a = uuid.uuid4()
        conn_b = uuid.uuid4()

        form_ids = list(form_behaviors.keys())
        # Assign alternating connections: first half conn_a, rest conn_b
        # Caller controls this via form_behaviors order
        conn_for_form = {
            fid: conn_a if i < 2 else conn_b
            for i, fid in enumerate(form_ids)
        }

        fake_forms = []
        for fid in form_ids:
            f = Mock()
            f.form_id = fid
            f.project_id = fid
            f.site_id = "SITE"
            f.odk_form_id = f"odk-{fid}"
            f.odk_project_id = "1"
            fake_forms.append(f)

        results = {}

        def _fake_fetch_instance_ids(va_form, client=None):
            behavior = form_behaviors.get(va_form.form_id)
            if callable(behavior):
                behavior(client)  # may raise
            return []

        with (
            patch(
                "app.services.va_data_sync.va_data_sync_01_odkcentral"
                ".sync_runtime_forms_from_site_mappings",
                return_value=fake_forms,
            ),
            patch(
                "app.services.va_data_sync.va_data_sync_01_odkcentral"
                "._resolve_project_connections",
                return_value=conn_for_form,
            ),
            patch(
                "app.services.va_data_sync.va_data_sync_01_odkcentral"
                "._get_or_create_sync_odk_client",
                return_value=Mock(),
            ),
            patch(
                "app.services.va_data_sync.va_data_sync_01_odkcentral"
                ".va_odk_fetch_instance_ids",
                side_effect=_fake_fetch_instance_ids,
            ),
            patch(
                "app.services.va_data_sync.va_data_sync_01_odkcentral"
                ".db.session.scalars",
                return_value=Mock(all=lambda: []),
            ),
            patch(
                "app.services.va_data_sync.va_data_sync_01_odkcentral"
                "._release_active_allocations_after_sync",
            ),
            patch(
                "app.services.va_data_sync.va_data_sync_01_odkcentral"
                ".smartva_service",
                create=True,
            ),
        ):
            progress_lines = []
            va_data_sync_odkcentral(log_progress=progress_lines.append)
            results["progress"] = progress_lines

        return results

    def test_cooldown_on_form_skips_remaining_forms_on_same_connection(self):
        from datetime import datetime, timedelta, timezone
        import uuid

        cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=5)

        call_log = []

        def _raise_cooldown(_client):
            raise OdkConnectionCooldownError("conn-a", cooldown_until, "timeout")

        def _normal(_client):
            call_log.append("form3_called")

        # form1 (conn_a): raises cooldown
        # form2 (conn_a): should be preemptively skipped
        # form3 (conn_b): should still run
        results = self._run_sync_with_mock_forms({
            "FORM1": _raise_cooldown,
            "FORM2": _raise_cooldown,  # would raise if reached, but should be skipped
            "FORM3": _normal,
        })

        progress = "\n".join(results["progress"])
        self.assertIn("FORM1", progress)
        self.assertIn("cooldown", progress.lower())
        # FORM2 skipped preemptively — should NOT say FAILED
        self.assertIn("SKIPPED", progress)
        # FORM3 on a different connection should still run
        self.assertIn("form3_called", call_log)

    def test_form_failure_non_cooldown_does_not_affect_other_forms(self):
        call_log = []

        def _raise_generic(_client):
            raise RuntimeError("data error, not cooldown")

        def _normal(_client):
            call_log.append("form2_called")

        results = self._run_sync_with_mock_forms({
            "FORMA": _raise_generic,
            "FORMB": _normal,
        })

        progress = "\n".join(results["progress"])
        self.assertIn("FAILED", progress)
        # FORMB should still run — a non-cooldown failure must not skip other forms
        self.assertIn("form2_called", call_log)
