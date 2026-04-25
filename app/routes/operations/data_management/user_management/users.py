"""User routes for data-management user management."""

import secrets
import uuid

import sqlalchemy as sa
from flask import jsonify, request
from flask_login import current_user

from app import db
from app.authz.access import action_authorized
from app.authz.resources import user_from_kwarg
from app.authz.scope import user_has_role
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.authz.grants import (
    grant_project_id_expression as _grant_project_id_expression,
    grant_site_id_expression as _grant_site_id_expression,
)
from app.http.responses import json_error as _json_error
from app.serializers import (
    serialize_grant as _serialize_grant,
    serialize_user,
)

from ..base import data_management, log
from ..helpers import (
    dm_can_manage_scope,
    dm_can_manage_target_user,
    dm_grant_filter,
)
from .helpers import _managed_roles, _valid_language_codes, dm_can_edit_user_email


@data_management.get("/api/users")
@action_authorized("dm_manage_users")
def manage_users():
    """User search for data-manager grant assignment."""
    query = (request.args.get("query") or "").strip()
    include_inactive = request.args.get("include_inactive", "1") == "1"

    stmt = sa.select(VaUsers)
    if not include_inactive:
        stmt = stmt.where(VaUsers.user_status == VaStatuses.active)
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            sa.or_(VaUsers.email.ilike(pattern), VaUsers.name.ilike(pattern))
        )

    users = db.session.scalars(stmt.order_by(VaUsers.email).limit(25)).all()
    return jsonify({"users": [serialize_user(user) for user in users]})


@data_management.post("/api/users")
@action_authorized("dm_manage_user_create")
def manage_create_user():
    """Create a new user (data-manager scoped)."""
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    email_confirm = (payload.get("email_confirm") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    languages = payload.get("languages")
    initial_role_value = payload.get("initial_role")
    initial_scope_value = payload.get("initial_scope_type")
    initial_project_id = (payload.get("initial_project_id") or "").strip() or None

    if not email or not email_confirm or not name:
        return _json_error("email, email_confirm, and name are required.", 400)
    if email != email_confirm:
        return _json_error("Email confirmation does not match.", 400)
    if not isinstance(languages, list) or not languages:
        return _json_error("At least one language must be selected.", 400)

    invalid_codes = [code for code in languages if code not in _valid_language_codes()]
    if invalid_codes:
        return _json_error(f"Invalid language codes: {invalid_codes}", 400)

    existing = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
    if existing:
        return _json_error("Email already in use.", 400)

    if not initial_role_value or not initial_scope_value:
        return _json_error("initial_role and initial_scope_type are required.", 400)
    if not initial_project_id:
        return _json_error("initial_project_id is required.", 400)
    if initial_role_value not in {role.value for role in VaAccessRoles}:
        return _json_error("Invalid initial_role.", 400)
    if initial_scope_value not in {scope.value for scope in VaAccessScopeTypes}:
        return _json_error("Invalid initial_scope_type.", 400)

    role = VaAccessRoles(initial_role_value)
    scope_type = VaAccessScopeTypes(initial_scope_value)
    resolved_project_id = None
    project_site_id = None

    if scope_type == VaAccessScopeTypes.project:
        resolved_project_id = initial_project_id
    elif scope_type == VaAccessScopeTypes.project_site:
        raw_project_site_id = payload.get("initial_project_site_id")
        if not raw_project_site_id:
            return _json_error("initial_project_site_id is required for site scope.", 400)
        try:
            project_site_id = uuid.UUID(raw_project_site_id)
        except (ValueError, TypeError):
            return _json_error("Invalid initial_project_site_id.", 400)
        project_site = db.session.get(VaProjectSites, project_site_id)
        if not project_site or project_site.project_site_status != VaStatuses.active:
            return _json_error("Active project-site mapping not found.", 404)
        if project_site.project_id != initial_project_id:
            return _json_error(
                "initial_project_site_id does not belong to initial_project_id.",
                400,
            )
        resolved_project_id = project_site.project_id
    else:
        return _json_error("Invalid initial_scope_type.", 400)

    ok, err = dm_can_manage_scope(
        current_user,
        role,
        scope_type,
        resolved_project_id,
        project_site_id,
    )
    if not ok:
        return _json_error(err, 403)

    new_user = VaUsers(
        email=email,
        name=name,
        phone=phone or None,
        user_status=VaStatuses.active,
        vacode_language=languages,
        permission={},
        landing_page="coder",
        pw_reset_t_and_c=False,
        email_verified=False,
        other={"created_by_user_id": str(current_user.user_id)},
    )
    new_user.set_password(secrets.token_urlsafe(32))

    db.session.add(new_user)
    db.session.flush()

    new_grant = VaUserAccessGrants(
        user_id=new_user.user_id,
        role=role,
        scope_type=scope_type,
        project_id=resolved_project_id
        if scope_type == VaAccessScopeTypes.project
        else None,
        project_site_id=project_site_id,
        notes="auto-created with user",
        grant_status=VaStatuses.active,
    )
    db.session.add(new_grant)
    db.session.commit()

    try:
        from app.services.notifications.email import (
            send_password_reset_email,
            send_verification_email,
        )
        from app.services.security.token import generate_token

        verify_token = generate_token(new_user.user_id, "email_verify")
        reset_token = generate_token(new_user.user_id, "password_reset")
        send_verification_email(new_user, verify_token)
        send_password_reset_email(new_user, reset_token, invite_mode=True)
    except Exception:
        pass

    return jsonify({"user": serialize_user(new_user)}), 201


@data_management.get("/api/users/<uuid:target_user_id>")
@action_authorized(
    "dm_manage_user_detail",
    resource_resolver=user_from_kwarg("target_user_id"),
)
def manage_user_detail(target_user_id):
    """Return user details for DM/admin view."""
    user = db.session.get(VaUsers, target_user_id)
    if not user:
        return _json_error("User not found.", 404)

    project_id_expression = _grant_project_id_expression()
    site_id_expression = _grant_site_id_expression()
    rows = db.session.execute(
        sa.select(
            VaUserAccessGrants.grant_id,
            VaUserAccessGrants.user_id,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_site_id,
            VaUserAccessGrants.grant_status,
            VaUserAccessGrants.notes,
            VaUsers.email,
            VaUsers.name,
            project_id_expression.label("resolved_project_id"),
            site_id_expression.label("resolved_site_id"),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(
            VaUserAccessGrants.user_id == target_user_id,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUserAccessGrants.role.in_(_managed_roles()),
            dm_grant_filter(project_id_expression),
        )
        .order_by(
            project_id_expression.asc(),
            site_id_expression.asc().nullsfirst(),
            VaUserAccessGrants.role.asc(),
        )
    ).all()

    if not user_has_role(current_user, "admin") and not rows:
        return _json_error("User not found.", 404)

    serialized_grants = [_serialize_grant(row) for row in rows]
    project_grants = [
        grant
        for grant in serialized_grants
        if grant["scope_type"] == VaAccessScopeTypes.project.value
    ]
    project_site_grants = [
        grant
        for grant in serialized_grants
        if grant["scope_type"] == VaAccessScopeTypes.project_site.value
    ]

    return jsonify(
        {
            "user": serialize_user(user),
            "grants": serialized_grants,
            "project_grants": project_grants,
            "project_site_grants": project_site_grants,
        }
    )


@data_management.post("/api/users/<uuid:target_user_id>/resend-verification")
@action_authorized(
    "dm_manage_user_resend_verification",
    resource_resolver=user_from_kwarg("target_user_id"),
)
def manage_resend_verification(target_user_id):
    """Resend email verification link for a user."""
    user = db.session.get(VaUsers, target_user_id)
    if not user:
        return _json_error("User not found.", 404)
    if not dm_can_manage_target_user(target_user_id):
        return _json_error("User not found.", 404)
    if user.email_verified:
        return _json_error("User email is already verified.", 400)

    try:
        from app.services.notifications.email import send_verification_email
        from app.services.security.token import generate_token

        verify_token = generate_token(user.user_id, "email_verify")
        send_verification_email(user, verify_token)
    except Exception as exc:
        log.exception("Resend verification failed for %s: %s", user.email, exc)
        return _json_error("Failed to send verification email.", 500)

    return jsonify({"message": "Verification email sent."})


@data_management.put("/api/users/<uuid:target_user_id>")
@action_authorized(
    "dm_manage_user_update",
    resource_resolver=user_from_kwarg("target_user_id"),
)
def manage_update_user(target_user_id):
    """Update user email and/or languages (email is creator-scoped for DMs)."""
    target_user = db.session.get(VaUsers, target_user_id)
    if not target_user:
        return _json_error("User not found.", 404)
    if not dm_can_manage_target_user(target_user_id):
        return _json_error("User not found.", 404)

    payload = request.get_json(silent=True) or {}
    email_raw = payload.get("email")
    email_confirm_raw = payload.get("email_confirm")
    email_requested = email_raw is not None or email_confirm_raw is not None
    languages_requested = "languages" in payload

    if not email_requested and not languages_requested:
        return _json_error("Provide email/email_confirm and/or languages.", 400)

    changed_email = False
    changed_languages = False

    if email_requested:
        if not dm_can_edit_user_email(target_user):
            return _json_error("You may update email only for users created by you.", 403)

        email = (email_raw or "").strip().lower()
        email_confirm = (email_confirm_raw or "").strip().lower()
        if not email or not email_confirm:
            return _json_error("email and email_confirm are required.", 400)
        if email != email_confirm:
            return _json_error("Email confirmation does not match.", 400)
        if email != target_user.email:
            existing = db.session.scalar(
                sa.select(VaUsers).where(
                    VaUsers.email == email,
                    VaUsers.user_id != target_user.user_id,
                )
            )
            if existing:
                return _json_error("Email already in use.", 400)
            target_user.email = email
            target_user.email_verified = False
            changed_email = True

    if languages_requested:
        languages = payload.get("languages")
        if not isinstance(languages, list) or not languages:
            return _json_error("At least one language must be selected.", 400)

        invalid_codes = [code for code in languages if code not in _valid_language_codes()]
        if invalid_codes:
            return _json_error(f"Invalid language codes: {invalid_codes}", 400)
        if list(target_user.vacode_language or []) != list(languages):
            target_user.vacode_language = languages
            changed_languages = True

    if changed_email or changed_languages:
        db.session.commit()

    if changed_email:
        try:
            from app.services.notifications.email import send_verification_email
            from app.services.security.token import generate_token

            verify_token = generate_token(target_user.user_id, "email_verify")
            send_verification_email(target_user, verify_token)
        except Exception:
            pass

    return jsonify({"user": serialize_user(target_user)})
