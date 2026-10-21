"""ODK sync reruns after the national-ID reduction (PII slice 1a).

The merge gate of docs/kb/pii-slice-1a.md: once ingest reduces ``Id10073``,
a rerun of unchanged ODK data (full number incoming) must not read as a
change, whether the stored version is already reduced or still holds the full
number from before the change. Otherwise every sync would release coding or
mark every finalised case upstream-changed.
"""

from datetime import UTC, datetime

import sqlalchemy as sa

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
    VaSubmissions,
    VaSubmissionUpstreamChange,
    VaSubmissionWorkflow,
)
from app.services.submission_payload_version_service import (
    canonical_payload_fingerprint,
    ensure_active_payload_version,
    get_active_payload_version,
)
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    _finalize_enriched_submissions_for_form,
    _upsert_form_submissions,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODING_IN_PROGRESS,
)
from app.services.workflow.state_store import set_submission_workflow_state
from tests.base import BaseTestCase

FULL_ID = "2345 6789 0123"
REDUCED_ID = "XXXXXXXXX123"


def create_form(project_id: str, site_id: str, form_id: str) -> None:
    """A project, site and WHO 2022 form to sync into (committed)."""
    now = datetime.now(UTC)
    for model in (VaProjectMaster, VaResearchProjects):
        db.session.add(model(
            project_id=project_id, project_code=project_id,
            project_name="National ID Sync", project_nickname="NidSync",
            project_status=VaStatuses.active, project_registered_at=now, project_updated_at=now,
        ))
    db.session.add(VaSiteMaster(
        site_id=site_id, site_name="National ID Site", site_abbr=site_id,
        site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
    ))
    db.session.flush()
    db.session.add(VaSites(
        site_id=site_id, project_id=project_id, site_name="National ID Site",
        site_abbr=site_id, site_status=VaStatuses.active,
        site_registered_at=now, site_updated_at=now,
    ))
    db.session.flush()
    db.session.add(VaProjectSites(
        project_id=project_id, site_id=site_id, project_site_status=VaStatuses.active,
        project_site_registered_at=now, project_site_updated_at=now,
    ))
    db.session.add(VaForms(
        form_id=form_id, project_id=project_id, site_id=site_id,
        odk_form_id="NID_FORM", odk_project_id="98", form_type="WHO VA 2022",
        form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
    ))
    db.session.commit()


class NationalIdSyncRerunTests(BaseTestCase):
    FORM_ID = "NID01ND0101"
    PROJECT_ID = "NID01"
    SITE_ID = "ND01"
    UPDATED_AT = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_form(cls.PROJECT_ID, cls.SITE_ID, cls.FORM_ID)

    # -- helpers -------------------------------------------------------------

    def _record(self, instance_id: str) -> dict:
        """The ODK record as Central sends it: full national ID, free text with one."""
        sid = f"{instance_id}-{self.FORM_ID.lower()}"
        return {
            "KEY": instance_id,
            "sid": sid,
            "form_def": self.FORM_ID,
            "SubmissionDate": self.UPDATED_AT.isoformat(),
            "updatedAt": self.UPDATED_AT.isoformat(),
            "SubmitterName": "Collector",
            "ReviewState": None,
            "instanceName": instance_id,
            "unique_id": instance_id,
            "unique_id2": f"{instance_id}-masked",
            "Id10013": "yes",
            "language": "English",
            "finalAgeInYears": "52",
            "Id10019": "female",
            "Id10073": FULL_ID,
            "Id10476": f"Card {FULL_ID} was shown.",
        }

    def _stored_case(self, instance_id: str, *, stored_full: bool) -> VaSubmissions:
        """A synced submission whose active version holds the reduced record,
        or (``stored_full``) the full one, as rows written before slice 1a do."""
        record = self._record(instance_id)
        sub = VaSubmissions(
            va_sid=record["sid"], va_form_id=self.FORM_ID,
            va_submission_date=self.UPDATED_AT, va_odk_updatedat=self.UPDATED_AT.replace(tzinfo=None),
            va_data_collector="Collector", va_odk_reviewstate=None, va_consent="yes",
            va_narration_language="English", va_deceased_age=52, va_deceased_gender="female",
            va_uniqueid_masked="masked", va_summary=[], va_catcount={}, va_category_list=[],
        )
        db.session.add(sub)
        db.session.flush()
        version = ensure_active_payload_version(
            sub, payload_data=record, source_updated_at=sub.va_odk_updatedat, created_by_role="vasystem",
        )
        if stored_full:
            version.payload_data = record
        db.session.flush()
        return sub

    def _versions(self, va_sid: str) -> int:
        return db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSubmissionPayloadVersion)
            .where(VaSubmissionPayloadVersion.va_sid == va_sid)
        )

    def _upstream_changes(self, va_sid: str) -> int:
        return db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSubmissionUpstreamChange)
            .where(VaSubmissionUpstreamChange.va_sid == va_sid)
        )

    def _state(self, va_sid: str) -> str | None:
        return db.session.scalar(
            sa.select(VaSubmissionWorkflow.workflow_state).where(VaSubmissionWorkflow.va_sid == va_sid)
        )

    def _rerun(self, va_sid: str, instance_id: str):
        va_form = db.session.get(VaForms, self.FORM_ID)
        amended: set = set()
        counts = _upsert_form_submissions(va_form, [self._record(instance_id)], amended, {}, enrich_payloads=False)
        db.session.flush()
        return counts, amended

    # -- the version written --------------------------------------------------

    def test_a_new_version_stores_the_reduced_id_and_redacted_free_text(self):
        sub = self._stored_case("uuid:nid-new", stored_full=False)
        stored = get_active_payload_version(sub.va_sid).payload_data
        self.assertIn("Id10073", stored)
        self.assertEqual(stored["Id10073"], REDUCED_ID)
        self.assertEqual(stored["Id10476"], f"Card {REDUCED_ID} was shown.")
        self.assertNotIn("6789", repr(stored))

    def test_fingerprint_of_full_and_reduced_payloads_is_equal(self):
        record = self._record("uuid:nid-fp")
        reduced = {**record, "Id10073": REDUCED_ID, "Id10476": f"Card {REDUCED_ID} was shown."}
        self.assertEqual(canonical_payload_fingerprint(record), canonical_payload_fingerprint(reduced))
        changed = {**reduced, "Id10073": "XXXXXXXXX999"}
        self.assertNotEqual(canonical_payload_fingerprint(record), canonical_payload_fingerprint(changed))

    # -- the merge gate -------------------------------------------------------

    def test_rerun_of_unchanged_odk_data_on_a_finalised_case_creates_nothing(self):
        # Full Id10073 incoming, reduced stored.
        sub = self._stored_case("uuid:nid-final-reduced", stored_full=False)
        set_submission_workflow_state(sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test")
        db.session.flush()
        self.assertEqual(self._versions(sub.va_sid), 1)

        (added, updated, discarded, _), amended = self._rerun(sub.va_sid, "uuid:nid-final-reduced")

        self.assertEqual((added, updated, discarded), (0, 0, 0))
        self.assertEqual(amended, set())
        self.assertEqual(self._versions(sub.va_sid), 1)
        self.assertEqual(self._upstream_changes(sub.va_sid), 0)
        self.assertEqual(self._state(sub.va_sid), WORKFLOW_CODER_FINALIZED)

    def test_rerun_on_a_finalised_case_stored_before_the_reduction_creates_nothing(self):
        # The first sync after deploy: full Id10073 both stored and incoming.
        sub = self._stored_case("uuid:nid-final-full", stored_full=True)
        set_submission_workflow_state(sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test")
        db.session.flush()
        self.assertEqual(get_active_payload_version(sub.va_sid).payload_data["Id10073"], FULL_ID)

        (added, updated, discarded, _), _ = self._rerun(sub.va_sid, "uuid:nid-final-full")

        self.assertEqual((added, updated, discarded), (0, 0, 0))
        self.assertEqual(self._versions(sub.va_sid), 1)
        self.assertEqual(self._upstream_changes(sub.va_sid), 0)
        self.assertEqual(self._state(sub.va_sid), WORKFLOW_CODER_FINALIZED)

    def test_rerun_does_not_release_a_coding_session(self):
        sub = self._stored_case("uuid:nid-coding", stored_full=True)
        set_submission_workflow_state(sub.va_sid, WORKFLOW_CODING_IN_PROGRESS, reason="test", by_role="test")
        allocation = VaAllocations(
            va_sid=sub.va_sid, va_allocated_to=self.base_coder_user.user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active,
        )
        initial = VaInitialAssessments(
            va_sid=sub.va_sid, va_iniassess_by=self.base_coder_user.user_id,
            va_immediate_cod="R99", va_antecedent_cod="R99", va_iniassess_status=VaStatuses.active,
        )
        db.session.add_all([allocation, initial])
        db.session.flush()
        self.assertEqual(allocation.va_allocation_status, VaStatuses.active)

        (_, updated, discarded, _), _ = self._rerun(sub.va_sid, "uuid:nid-coding")

        self.assertEqual((updated, discarded), (0, 0))
        self.assertEqual(allocation.va_allocation_status, VaStatuses.active)
        self.assertEqual(initial.va_iniassess_status, VaStatuses.active)
        self.assertEqual(self._state(sub.va_sid), WORKFLOW_CODING_IN_PROGRESS)
        self.assertEqual(self._versions(sub.va_sid), 1)

    def test_finalize_pass_on_a_protected_case_reduces_in_place_without_a_version(self):
        # The enrichment pass calls ensure_active_payload_version for an
        # unchanged case: the stored full number is replaced by the reduced
        # form in the same version; nothing is released or recorded.
        sub = self._stored_case("uuid:nid-enrich", stored_full=True)
        set_submission_workflow_state(sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test")
        db.session.flush()
        va_form = db.session.get(VaForms, self.FORM_ID)
        record = self._record("uuid:nid-enrich")

        finalized = _finalize_enriched_submissions_for_form(
            va_form, [record], {sub.va_sid: record["KEY"]}, set(), client=None,
        )
        db.session.flush()

        self.assertEqual(finalized, 1)
        self.assertEqual(self._versions(sub.va_sid), 1)
        self.assertEqual(self._upstream_changes(sub.va_sid), 0)
        self.assertEqual(self._state(sub.va_sid), WORKFLOW_CODER_FINALIZED)
        self.assertEqual(get_active_payload_version(sub.va_sid).payload_data["Id10073"], REDUCED_ID)

    def test_a_changed_kept_digit_is_still_a_change(self):
        sub = self._stored_case("uuid:nid-changed", stored_full=False)
        set_submission_workflow_state(sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test")
        db.session.flush()
        va_form = db.session.get(VaForms, self.FORM_ID)
        record = {**self._record("uuid:nid-changed"), "Id10073": "2345 6789 0999"}

        _upsert_form_submissions(va_form, [record], set(), {}, enrich_payloads=False)
        db.session.flush()

        self.assertEqual(self._upstream_changes(sub.va_sid), 1)
        incoming = db.session.scalar(
            sa.select(VaSubmissionUpstreamChange.incoming_va_data)
            .where(VaSubmissionUpstreamChange.va_sid == sub.va_sid)
        )
        self.assertEqual(incoming["Id10073"], "XXXXXXXXX999")

    def test_an_upstream_change_never_copies_a_stored_full_number(self):
        sub = self._stored_case("uuid:nid-changed-legacy", stored_full=True)
        set_submission_workflow_state(sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test")
        db.session.flush()
        self.assertEqual(get_active_payload_version(sub.va_sid).payload_data["Id10073"], FULL_ID)
        va_form = db.session.get(VaForms, self.FORM_ID)
        record = {**self._record("uuid:nid-changed-legacy"), "Id10019": "male"}

        _upsert_form_submissions(va_form, [record], set(), {}, enrich_payloads=False)
        db.session.flush()

        row = db.session.scalar(
            sa.select(VaSubmissionUpstreamChange).where(VaSubmissionUpstreamChange.va_sid == sub.va_sid)
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.previous_va_data["Id10073"], REDUCED_ID)
        self.assertEqual(row.incoming_va_data["Id10073"], REDUCED_ID)
