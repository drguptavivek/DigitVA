"""Coding artifact helpers grouped by artifact policy.

Routes may import from this package for compatibility, while implementation
stays split by artifact type so NQA, reviewer review, and Social Autopsy
policies can evolve independently.
"""

from app.services.coding.payload_artifacts.common import (
    get_submission_with_current_payload,
)
from app.services.coding.payload_artifacts.narrative_quality import (
    deactivate_active_narrative_assessments_for_submission,
    deactivate_other_active_narrative_assessments,
    get_current_payload_narrative_assessment,
    promote_active_narrative_assessments_to_payload,
)
from app.services.coding.payload_artifacts.reviewer_review import (
    deactivate_active_reviewer_reviews_for_submission,
    deactivate_other_active_reviewer_reviews,
    get_current_payload_reviewer_review,
    promote_active_reviewer_reviews_to_payload,
)
from app.services.coding.payload_artifacts.social_autopsy import (
    deactivate_active_social_autopsy_analyses_for_submission,
    deactivate_other_active_social_autopsy_analyses,
    get_current_payload_social_autopsy_analysis,
    promote_active_social_autopsy_analyses_to_payload,
)

__all__ = [
    "deactivate_active_narrative_assessments_for_submission",
    "deactivate_active_reviewer_reviews_for_submission",
    "deactivate_active_social_autopsy_analyses_for_submission",
    "deactivate_other_active_narrative_assessments",
    "deactivate_other_active_reviewer_reviews",
    "deactivate_other_active_social_autopsy_analyses",
    "get_current_payload_narrative_assessment",
    "get_current_payload_reviewer_review",
    "get_current_payload_social_autopsy_analysis",
    "get_submission_with_current_payload",
    "promote_active_narrative_assessments_to_payload",
    "promote_active_reviewer_reviews_to_payload",
    "promote_active_social_autopsy_analyses_to_payload",
]
