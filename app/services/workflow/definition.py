"""Declarative submission-workflow definition.

This module is the single source of truth for canonical workflow states and
named transitions. Runtime services should depend on this definition rather
than hard-coding state strings ad hoc.
"""

from __future__ import annotations

from dataclasses import dataclass


WORKFLOW_SCREENING_PENDING = "screening_pending"
WORKFLOW_ATTACHMENT_SYNC_PENDING = "attachment_sync_pending"
WORKFLOW_SMARTVA_PENDING = "smartva_pending"
WORKFLOW_READY_FOR_CODING = "ready_for_coding"
WORKFLOW_CODING_IN_PROGRESS = "coding_in_progress"
WORKFLOW_CODER_STEP1_SAVED = "coder_step1_saved"
WORKFLOW_CODER_FINALIZED = "coder_finalized"
WORKFLOW_REVIEWER_ELIGIBLE = "reviewer_eligible"
WORKFLOW_REVIEWER_CODING_IN_PROGRESS = "reviewer_coding_in_progress"
WORKFLOW_REVIEWER_FINALIZED = "reviewer_finalized"
WORKFLOW_FINALIZED_UPSTREAM_CHANGED = "finalized_upstream_changed"
WORKFLOW_NOT_CODEABLE_BY_CODER = "not_codeable_by_coder"
WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER = "not_codeable_by_data_manager"
WORKFLOW_CONSENT_REFUSED = "consent_refused"

ALL_WORKFLOW_STATES = frozenset(
    {
        WORKFLOW_SCREENING_PENDING,
        WORKFLOW_ATTACHMENT_SYNC_PENDING,
        WORKFLOW_SMARTVA_PENDING,
        WORKFLOW_READY_FOR_CODING,
        WORKFLOW_CODING_IN_PROGRESS,
        WORKFLOW_CODER_STEP1_SAVED,
        WORKFLOW_CODER_FINALIZED,
        WORKFLOW_REVIEWER_ELIGIBLE,
        WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
        WORKFLOW_REVIEWER_FINALIZED,
        WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
        WORKFLOW_NOT_CODEABLE_BY_CODER,
        WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
        WORKFLOW_CONSENT_REFUSED,
    }
)

PROTECTED_WORKFLOW_STATES = frozenset(
    {
        WORKFLOW_CODER_FINALIZED,
        WORKFLOW_REVIEWER_ELIGIBLE,
        # An active reviewer session is protected: ODK data changes during a
        # reviewer's mid-session must go through the DM accept/reject path, not
        # silently re-route the case and orphan the reviewer's allocation.
        WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
        WORKFLOW_REVIEWER_FINALIZED,
        WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    }
)

SMARTVA_BLOCKED_WORKFLOW_STATES = frozenset(
    PROTECTED_WORKFLOW_STATES | {WORKFLOW_CONSENT_REFUSED}
)

CODER_READY_POOL_STATES = frozenset({WORKFLOW_READY_FOR_CODING})

# Coding-progress buckets shown on the area dashboard
# (docs/policy/area-dashboard.md). Every state is mapped explicitly, so a new
# state lands in "other" until someone decides where it belongs; a test holds
# the keys equal to ALL_WORKFLOW_STATES.
CODING_BUCKET_AWAITING = "awaiting_coding"
CODING_BUCKET_IN_CODING = "in_coding"
CODING_BUCKET_IN_REVIEW = "in_review"
CODING_BUCKET_CODED = "coded"
CODING_BUCKET_NOT_CODEABLE = "not_codeable"
CODING_BUCKET_OTHER = "other"

CODING_BUCKETS = (
    CODING_BUCKET_AWAITING,
    CODING_BUCKET_IN_CODING,
    CODING_BUCKET_IN_REVIEW,
    CODING_BUCKET_CODED,
    CODING_BUCKET_NOT_CODEABLE,
    CODING_BUCKET_OTHER,
)

WORKFLOW_CODING_BUCKETS = {
    # Pre-coding pipeline: each ends in ready_for_coding unless excluded.
    WORKFLOW_SCREENING_PENDING: CODING_BUCKET_AWAITING,
    WORKFLOW_ATTACHMENT_SYNC_PENDING: CODING_BUCKET_AWAITING,
    WORKFLOW_SMARTVA_PENDING: CODING_BUCKET_AWAITING,
    WORKFLOW_READY_FOR_CODING: CODING_BUCKET_AWAITING,
    WORKFLOW_CODING_IN_PROGRESS: CODING_BUCKET_IN_CODING,
    WORKFLOW_CODER_STEP1_SAVED: CODING_BUCKET_IN_CODING,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS: CODING_BUCKET_IN_REVIEW,
    # A coder's final COD exists; review, where it happens, is optional.
    WORKFLOW_CODER_FINALIZED: CODING_BUCKET_CODED,
    WORKFLOW_REVIEWER_ELIGIBLE: CODING_BUCKET_CODED,
    WORKFLOW_REVIEWER_FINALIZED: CODING_BUCKET_CODED,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED: CODING_BUCKET_CODED,
    WORKFLOW_NOT_CODEABLE_BY_CODER: CODING_BUCKET_NOT_CODEABLE,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER: CODING_BUCKET_NOT_CODEABLE,
    WORKFLOW_CONSENT_REFUSED: CODING_BUCKET_NOT_CODEABLE,
}


def coding_bucket(workflow_state: str | None) -> str:
    """The area-dashboard coding bucket for *workflow_state*; unknown or None -> other."""
    return WORKFLOW_CODING_BUCKETS.get(workflow_state, CODING_BUCKET_OTHER)


TRANSITION_SYNC_NEW_PAYLOAD = "sync_new_payload_routed"
TRANSITION_ATTACHMENTS_SYNCED = "attachments_synced"
TRANSITION_UPSTREAM_CHANGE_DETECTED = "upstream_change_detected"
TRANSITION_SMARTVA_COMPLETED = "smartva_completed"
TRANSITION_SMARTVA_FAILED_RECORDED = "smartva_failed_recorded"
TRANSITION_SCREENING_PASSED = "screening_passed"
TRANSITION_SCREENING_REJECTED = "screening_rejected"
TRANSITION_CODING_STARTED = "coding_started"
TRANSITION_RECODE_STARTED = "recode_started"
TRANSITION_CODER_STEP1_SAVED = "coder_step1_saved"
TRANSITION_CODER_FINALIZED = "coder_finalized"
TRANSITION_RECODE_FINALIZED = "recode_finalized"
TRANSITION_CODER_NOT_CODEABLE = "coder_not_codeable"
TRANSITION_DM_NOT_CODEABLE = "data_manager_not_codeable"
TRANSITION_UPSTREAM_CHANGE_ACCEPTED = "upstream_change_accepted"
TRANSITION_UPSTREAM_CHANGE_REJECTED = "upstream_change_rejected"
TRANSITION_UPSTREAM_CHANGE_KEPT_CURRENT_ICD = "upstream_change_kept_current_icd"
TRANSITION_ADMIN_OVERRIDE_TO_RECODE = "admin_override_to_recode"
TRANSITION_REVIEWER_ELIGIBLE_AFTER_RECODE_WINDOW = "reviewer_eligible_after_recode_window"
TRANSITION_REVIEWER_CODING_STARTED = "reviewer_coding_started"
TRANSITION_REVIEWER_FINALIZED = "reviewer_finalized"
TRANSITION_INCOMPLETE_FIRST_PASS_RESET = "incomplete_first_pass_reset"
TRANSITION_INCOMPLETE_RECODE_RESET = "incomplete_recode_reset"
TRANSITION_INCOMPLETE_REVIEWER_RESET = "incomplete_reviewer_reset"
TRANSITION_DEMO_RESET = "demo_reset"
TRANSITION_DEMO_STARTED = "demo_started"


@dataclass(frozen=True)
class TransitionDefinition:
    transition_id: str
    label: str
    target_state: str | None = None


TRANSITIONS = {
    TRANSITION_SYNC_NEW_PAYLOAD: TransitionDefinition(
        transition_id=TRANSITION_SYNC_NEW_PAYLOAD,
        label="Sync New Payload Routed",
    ),
    TRANSITION_ATTACHMENTS_SYNCED: TransitionDefinition(
        transition_id=TRANSITION_ATTACHMENTS_SYNCED,
        label="Attachments Synced",
        target_state=WORKFLOW_SMARTVA_PENDING,
    ),
    TRANSITION_UPSTREAM_CHANGE_DETECTED: TransitionDefinition(
        transition_id=TRANSITION_UPSTREAM_CHANGE_DETECTED,
        label="Upstream Change Detected",
        target_state=WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    ),
    TRANSITION_SMARTVA_COMPLETED: TransitionDefinition(
        transition_id=TRANSITION_SMARTVA_COMPLETED,
        label="SmartVA Completed",
        target_state=WORKFLOW_READY_FOR_CODING,
    ),
    TRANSITION_SMARTVA_FAILED_RECORDED: TransitionDefinition(
        transition_id=TRANSITION_SMARTVA_FAILED_RECORDED,
        label="SmartVA Failed Recorded",
        target_state=WORKFLOW_READY_FOR_CODING,
    ),
    TRANSITION_SCREENING_PASSED: TransitionDefinition(
        transition_id=TRANSITION_SCREENING_PASSED,
        label="Screening Passed",
        target_state=WORKFLOW_SMARTVA_PENDING,
    ),
    TRANSITION_SCREENING_REJECTED: TransitionDefinition(
        transition_id=TRANSITION_SCREENING_REJECTED,
        label="Screening Rejected",
        target_state=WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    ),
    TRANSITION_CODING_STARTED: TransitionDefinition(
        transition_id=TRANSITION_CODING_STARTED,
        label="Coding Started",
        target_state=WORKFLOW_CODING_IN_PROGRESS,
    ),
    TRANSITION_RECODE_STARTED: TransitionDefinition(
        transition_id=TRANSITION_RECODE_STARTED,
        label="Recode Started",
        target_state=WORKFLOW_CODING_IN_PROGRESS,
    ),
    TRANSITION_CODER_STEP1_SAVED: TransitionDefinition(
        transition_id=TRANSITION_CODER_STEP1_SAVED,
        label="Coder Step 1 Saved",
        target_state=WORKFLOW_CODER_STEP1_SAVED,
    ),
    TRANSITION_CODER_FINALIZED: TransitionDefinition(
        transition_id=TRANSITION_CODER_FINALIZED,
        label="Coder Finalized",
        target_state=WORKFLOW_CODER_FINALIZED,
    ),
    TRANSITION_RECODE_FINALIZED: TransitionDefinition(
        transition_id=TRANSITION_RECODE_FINALIZED,
        label="Recode Finalized",
        target_state=WORKFLOW_CODER_FINALIZED,
    ),
    TRANSITION_CODER_NOT_CODEABLE: TransitionDefinition(
        transition_id=TRANSITION_CODER_NOT_CODEABLE,
        label="Coder Marked Not Codeable",
        target_state=WORKFLOW_NOT_CODEABLE_BY_CODER,
    ),
    TRANSITION_DM_NOT_CODEABLE: TransitionDefinition(
        transition_id=TRANSITION_DM_NOT_CODEABLE,
        label="Data Manager Marked Not Codeable",
        target_state=WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    ),
    TRANSITION_UPSTREAM_CHANGE_ACCEPTED: TransitionDefinition(
        transition_id=TRANSITION_UPSTREAM_CHANGE_ACCEPTED,
        label="Upstream Change Accepted",
        target_state=WORKFLOW_SMARTVA_PENDING,
    ),
    TRANSITION_UPSTREAM_CHANGE_REJECTED: TransitionDefinition(
        transition_id=TRANSITION_UPSTREAM_CHANGE_REJECTED,
        label="Upstream Change Rejected",
        target_state=WORKFLOW_CODER_FINALIZED,
    ),
    TRANSITION_UPSTREAM_CHANGE_KEPT_CURRENT_ICD: TransitionDefinition(
        transition_id=TRANSITION_UPSTREAM_CHANGE_KEPT_CURRENT_ICD,
        label="Upstream Change Kept Current ICD",
        target_state=WORKFLOW_CODER_FINALIZED,
    ),
    TRANSITION_ADMIN_OVERRIDE_TO_RECODE: TransitionDefinition(
        transition_id=TRANSITION_ADMIN_OVERRIDE_TO_RECODE,
        label="Admin Override To Recode",
        target_state=WORKFLOW_READY_FOR_CODING,
    ),
    TRANSITION_REVIEWER_ELIGIBLE_AFTER_RECODE_WINDOW: TransitionDefinition(
        transition_id=TRANSITION_REVIEWER_ELIGIBLE_AFTER_RECODE_WINDOW,
        label="Reviewer Eligible After Recode Window",
        target_state=WORKFLOW_REVIEWER_ELIGIBLE,
    ),
    TRANSITION_REVIEWER_CODING_STARTED: TransitionDefinition(
        transition_id=TRANSITION_REVIEWER_CODING_STARTED,
        label="Reviewer Coding Started",
        target_state=WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    ),
    TRANSITION_REVIEWER_FINALIZED: TransitionDefinition(
        transition_id=TRANSITION_REVIEWER_FINALIZED,
        label="Reviewer Finalized",
        target_state=WORKFLOW_REVIEWER_FINALIZED,
    ),
    TRANSITION_INCOMPLETE_FIRST_PASS_RESET: TransitionDefinition(
        transition_id=TRANSITION_INCOMPLETE_FIRST_PASS_RESET,
        label="Incomplete First Pass Reset",
        target_state=WORKFLOW_READY_FOR_CODING,
    ),
    TRANSITION_INCOMPLETE_RECODE_RESET: TransitionDefinition(
        transition_id=TRANSITION_INCOMPLETE_RECODE_RESET,
        label="Incomplete Recode Reset",
        target_state=WORKFLOW_CODER_FINALIZED,
    ),
    TRANSITION_INCOMPLETE_REVIEWER_RESET: TransitionDefinition(
        transition_id=TRANSITION_INCOMPLETE_REVIEWER_RESET,
        label="Incomplete Reviewer Session Reset",
        target_state=WORKFLOW_REVIEWER_ELIGIBLE,
    ),
    TRANSITION_DEMO_RESET: TransitionDefinition(
        transition_id=TRANSITION_DEMO_RESET,
        label="Demo Reset",
    ),
    TRANSITION_DEMO_STARTED: TransitionDefinition(
        transition_id=TRANSITION_DEMO_STARTED,
        label="Demo Started",
        target_state=WORKFLOW_CODING_IN_PROGRESS,
    ),
}
