"""Social Autopsy API — /api/v1/va/<sid>/social-autopsy

Resources:
  POST <sid>/social-autopsy   — save/update Social Autopsy analysis
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from app import db
from app.models import (
    VaAllocations,
    VaAllocation,
    VaStatuses,
    VaSocialAutopsyAnalysis,
    VaSocialAutopsyAnalysisOption,
    VaSubmissionsAuditlog,
)
from app.services.social_autopsy_analysis_service import (
    SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS,
    social_autopsy_option_set,
)
from app.services.payload_bound_coding_artifact_service import (
    deactivate_other_active_social_autopsy_analyses,
    get_submission_with_current_payload,
)

bp = Blueprint("so_api", __name__)
log = logging.getLogger(__name__)

DEMO_RETENTION_HOURS = 6


def _require_coding_access(va_sid: str):
    """Return a JSON 403 if the user lacks an active coding allocation.

    Admin users with va_actiontype == "vademo_start_coding" in the body are allowed through.
    """
    data = request.get_json(silent=True) or {}
    if data.get("va_actiontype") == "vademo_start_coding":
        if not current_user.is_admin():
            return jsonify({"error": "Only admins can perform demo coding sessions."}), 403
        return None

    alloc = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            VaAllocations.va_allocated_to == current_user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_status == VaStatuses.active,
            VaAllocations.va_sid == va_sid,
        )
    )
    if not alloc:
        return jsonify({"error": "Active coding allocation required."}), 403
    return None


def _demo_expiry(va_actiontype: str | None):
    if va_actiontype != "vademo_start_coding":
        return None
    return datetime.now(timezone.utc) + timedelta(hours=DEMO_RETENTION_HOURS)


@bp.post("/<va_sid>/social-autopsy")
@login_required
def save_social_autopsy(va_sid: str):
    """Save or update the Social Autopsy analysis selections for a coder."""
    err = _require_coding_access(va_sid)
    if err:
        return err

    data = request.get_json(force=True) or {}
    va_actiontype = data.get("va_actiontype")
    selected_options = data.get("selected_options") or []
    remark = (data.get("remark") or "").strip() or None

    if not isinstance(selected_options, list):
        return jsonify({"error": "selected_options must be a list."}), 400

    valid_pairs = social_autopsy_option_set()
    normalized = []
    seen: set[tuple[str, str]] = set()
    for item in selected_options:
        if not isinstance(item, dict):
            return jsonify({"error": "Each selected option must be an object."}), 400
        delay_level = (item.get("delay_level") or "").strip()
        option_code = (item.get("option_code") or "").strip()
        pair = (delay_level, option_code)
        if pair not in valid_pairs:
            return jsonify({"error": f"Invalid Social Autopsy option: {delay_level}/{option_code}"}), 400
        if pair in seen:
            continue
        seen.add(pair)
        normalized.append(pair)

    # "None" is exclusive within a delay level.
    by_delay: dict[str, set[str]] = {}
    for delay_level, option_code in normalized:
        by_delay.setdefault(delay_level, set()).add(option_code)

    normalized = []
    for delay_level in sorted(by_delay.keys()):
        option_codes = by_delay[delay_level]
        if "none" in option_codes:
            normalized.append((delay_level, "none"))
            continue
        for option_code in sorted(option_codes):
            normalized.append((delay_level, option_code))

    required_delay_levels = {
        question["delay_level"] for question in SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS
    }
    missing_delay_levels = sorted(required_delay_levels - set(by_delay.keys()))
    if missing_delay_levels:
        return jsonify({
            "error": (
                "Please answer every Social Autopsy delay question. "
                "Use 'None' where no delay factor applies."
            ),
            "missing_delay_levels": missing_delay_levels,
        }), 400

    _, active_payload_version = get_submission_with_current_payload(
        va_sid,
        for_update=True,
        created_by_role="vacoder",
        created_by=current_user.user_id,
    )
    existing = db.session.scalar(
        sa.select(VaSocialAutopsyAnalysis).where(
            VaSocialAutopsyAnalysis.va_sid == va_sid,
            VaSocialAutopsyAnalysis.va_saa_by == current_user.user_id,
            VaSocialAutopsyAnalysis.payload_version_id
            == active_payload_version.payload_version_id,
            VaSocialAutopsyAnalysis.va_saa_status == VaStatuses.active,
        )
    )

    created = False
    if existing:
        analysis = existing
        analysis.va_saa_remark = remark
        analysis.demo_expires_at = _demo_expiry(va_actiontype)
        analysis.selected_options.clear()
        db.session.flush()
        audit_operation = "u"
        audit_action = "social autopsy analysis updated"
    else:
        deactivate_other_active_social_autopsy_analyses(
            va_sid,
            current_user.user_id,
            audit_byrole="vacoder",
            audit_by=current_user.user_id,
        )
        analysis = VaSocialAutopsyAnalysis(
            va_sid=va_sid,
            va_saa_by=current_user.user_id,
            payload_version_id=active_payload_version.payload_version_id,
            va_saa_remark=remark,
            va_saa_status=VaStatuses.active,
            demo_expires_at=_demo_expiry(va_actiontype),
        )
        db.session.add(analysis)
        created = True
        audit_operation = "c"
        audit_action = "social autopsy analysis saved"

    for delay_level, option_code in normalized:
        analysis.selected_options.append(
            VaSocialAutopsyAnalysisOption(
                delay_level=delay_level,
                option_code=option_code,
            )
        )

    if existing:
        deactivate_other_active_social_autopsy_analyses(
            va_sid,
            current_user.user_id,
            keep_id=analysis.va_saa_id,
            audit_byrole="vacoder",
            audit_by=current_user.user_id,
        )
    db.session.flush()
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="vacoder",
            va_audit_by=current_user.user_id,
            va_audit_operation=audit_operation,
            va_audit_action=audit_action,
            va_audit_entityid=analysis.va_saa_id,
        )
    )
    db.session.commit()

    return jsonify({
        "saved": True,
        "created": created,
        "selection_count": len(normalized),
        "remark": analysis.va_saa_remark,
    })
