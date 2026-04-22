import secrets

import sqlalchemy as sa
from flask import jsonify, render_template, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.routes.admin import admin
from app.routes.admin_support.auth import request_user_has_role
from app.routes.admin_support.http import json_error as _json_error
from app.routes.admin_support.serializers import serialize_user


def _active_language_codes():
    from app.models.mas_languages import MasLanguages

    return set(
        db.session.scalars(
            sa.select(MasLanguages.language_code).where(MasLanguages.is_active == True)
        ).all()
    )


def _available_languages():
    from app.models.mas_languages import MasLanguages

    languages = db.session.scalars(
        sa.select(MasLanguages)
        .where(MasLanguages.is_active == True)
        .order_by(MasLanguages.language_name)
    ).all()
    return [
        {"code": language.language_code, "name": language.language_name}
        for language in languages
    ]


def _validate_languages(languages):
    if not isinstance(languages, list) or not languages:
        return "At least one language must be selected."

    valid_codes = _active_language_codes()
    invalid = [code for code in languages if code not in valid_codes]
    if invalid:
        return f"Invalid language codes: {invalid}"

    return None


@admin.get("/api/users")
@role_required("admin")
def admin_users():
    query = (request.args.get("query") or "").strip()
    master = request.args.get("master") == "1"

    stmt = sa.select(VaUsers)

    if master:
        if not request_user_has_role("admin"):
            return _json_error("Admin access required.", 403)
        if request.args.get("include_inactive") != "1":
            stmt = stmt.where(VaUsers.user_status == VaStatuses.active)
    else:
        stmt = stmt.where(VaUsers.user_status == VaStatuses.active)

    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            sa.or_(VaUsers.email.ilike(pattern), VaUsers.name.ilike(pattern))
        )

    users = db.session.scalars(
        stmt.order_by(VaUsers.email).limit(25 if not master else None)
    ).all()
    return jsonify({"users": [serialize_user(user) for user in users]})


@admin.post("/api/users")
@role_required("admin")
def admin_create_user():
    if not request_user_has_role("admin"):
        return _json_error("Admin access required.", 403)

    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    email_confirm = (payload.get("email_confirm") or email).strip().lower()
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    languages = payload.get("languages")

    if not email or not name:
        return _json_error("email and name are required.", 400)
    if email != email_confirm:
        return _json_error("Email confirmation does not match.", 400)

    language_error = _validate_languages(languages)
    if language_error:
        return _json_error(language_error, 400)

    existing = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
    if existing:
        return _json_error("Email already in use.", 400)

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
    )
    new_user.set_password(secrets.token_urlsafe(32))

    db.session.add(new_user)
    db.session.commit()

    try:
        from app.services.email_service import (
            send_password_reset_email,
            send_verification_email,
        )
        from app.services.token_service import generate_token

        verify_token = generate_token(new_user.user_id, "email_verify")
        reset_token = generate_token(new_user.user_id, "password_reset")
        send_verification_email(new_user, verify_token)
        send_password_reset_email(new_user, reset_token, invite_mode=True)
    except Exception:
        pass

    return jsonify({"user": serialize_user(new_user)}), 201


@admin.put("/api/users/<uuid:target_user_id>")
@role_required("admin")
def admin_update_user(target_user_id):
    if not request_user_has_role("admin"):
        return _json_error("Admin access required.", 403)

    target_user = db.session.get(VaUsers, target_user_id)
    if not target_user:
        return _json_error("User not found.", 404)

    payload = request.get_json(silent=True) or {}

    if "email" in payload or "email_confirm" in payload:
        new_email = (payload.get("email") or "").strip().lower()
        new_email_confirm = (payload.get("email_confirm") or "").strip().lower()
        if not new_email or not new_email_confirm:
            return _json_error("email and email_confirm are required.", 400)
        if new_email != new_email_confirm:
            return _json_error("Email confirmation does not match.", 400)
        if new_email != target_user.email:
            existing = db.session.scalar(
                sa.select(VaUsers).where(
                    VaUsers.email == new_email,
                    VaUsers.user_id != target_user.user_id,
                )
            )
            if existing:
                return _json_error("Email already in use.", 400)
            target_user.email = new_email
            target_user.email_verified = False

    if "name" in payload:
        name = (payload["name"] or "").strip()
        if not name:
            return _json_error("Name cannot be empty.", 400)
        target_user.name = name

    if "phone" in payload:
        target_user.phone = (payload["phone"] or "").strip() or None

    if "status" in payload:
        try:
            target_user.user_status = VaStatuses(payload["status"])
        except ValueError:
            return _json_error("Invalid status.", 400)

    if payload.get("password"):
        from app.utils.password_policy import password_error_message

        password_error = password_error_message(payload["password"])
        if password_error:
            return _json_error(password_error, 400)
        target_user.set_password(payload["password"])

    if "languages" in payload:
        language_error = _validate_languages(payload.get("languages"))
        if language_error:
            return _json_error(language_error, 400)
        target_user.vacode_language = payload["languages"]

    db.session.commit()

    if ("email" in payload or "email_confirm" in payload) and not target_user.email_verified:
        try:
            from app.services.email_service import send_verification_email
            from app.services.token_service import generate_token

            verify_token = generate_token(target_user.user_id, "email_verify")
            send_verification_email(target_user, verify_token)
        except Exception:
            pass

    return jsonify({"user": serialize_user(target_user)})


@admin.post("/api/users/<uuid:target_user_id>/resend-verification")
@role_required("admin")
def admin_resend_verification(target_user_id):
    if not request_user_has_role("admin"):
        return _json_error("Admin access required.", 403)

    target_user = db.session.get(VaUsers, target_user_id)
    if not target_user:
        return _json_error("User not found.", 404)
    if target_user.email_verified:
        return _json_error("User email is already verified.", 400)

    try:
        from app.services.email_service import send_verification_email
        from app.services.token_service import generate_token

        token = generate_token(target_user.user_id, "email_verify")
        send_verification_email(target_user, token)
    except Exception:
        return _json_error("Failed to send verification email.", 500)

    return jsonify({"message": "Verification email sent."})


@admin.post("/api/users/<uuid:target_user_id>/toggle")
@role_required("admin")
def admin_toggle_user(target_user_id):
    if not request_user_has_role("admin"):
        return _json_error("Admin access required.", 403)

    target_user = db.session.get(VaUsers, target_user_id)
    if not target_user:
        return _json_error("User not found.", 404)

    if target_user.user_id == current_user.user_id:
        return _json_error("You cannot deactivate yourself.", 400)

    target_user.user_status = (
        VaStatuses.deactive
        if target_user.user_status == VaStatuses.active
        else VaStatuses.active
    )
    db.session.commit()
    return jsonify(
        {
            "user_id": str(target_user.user_id),
            "status": target_user.user_status.value,
        }
    )


@admin.post("/api/users/<uuid:target_user_id>/toggle-admin")
@role_required("admin")
def admin_toggle_user_admin(target_user_id):
    if not request_user_has_role("admin"):
        return _json_error("Admin access required.", 403)

    target_user = db.session.get(VaUsers, target_user_id)
    if not target_user:
        return _json_error("User not found.", 404)

    if target_user.user_id == current_user.user_id:
        return _json_error("You cannot change your own admin status.", 400)

    grant = db.session.scalar(
        sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == target_user.user_id,
            VaUserAccessGrants.role == VaAccessRoles.admin,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.global_scope,
        )
    )

    if grant and grant.grant_status == VaStatuses.active:
        grant.grant_status = VaStatuses.deactive
        is_admin = False
    else:
        if grant is None:
            grant = VaUserAccessGrants(
                user_id=target_user.user_id,
                role=VaAccessRoles.admin,
                scope_type=VaAccessScopeTypes.global_scope,
                grant_status=VaStatuses.active,
                notes="toggled via admin panel",
            )
            db.session.add(grant)
        else:
            grant.grant_status = VaStatuses.active
        is_admin = True

    db.session.commit()
    return jsonify(
        {
            "user_id": str(target_user.user_id),
            "is_admin": is_admin,
        }
    )


@admin.get("/panels/users")
@role_required("admin")
def admin_panel_users():
    return render_template(
        "admin/panels/users.html",
        available_languages=_available_languages(),
    )
