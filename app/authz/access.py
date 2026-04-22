from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import logging
from typing import Any, Callable

from flask import current_app, g, jsonify, redirect, request, url_for
from flask_login import current_user, logout_user

from app.authz import policy as auth_policy
from app.models import VaStatuses
from app.utils.va_permission.va_permission_01_abortwithflash import (
    va_permission_abortwithflash,
)

log = logging.getLogger(__name__)


class AuthorizationConfigurationError(RuntimeError):
    pass


class AuthorizationDenied(RuntimeError):
    def __init__(self, reason: str, *, status_code: int = 403):
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class ResourceResolutionError(RuntimeError):
    def __init__(self, reason: str, *, status_code: int = 404):
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class PredicateExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResourceContext:
    resource_type: str
    resource_id: str | None = None
    project_id: str | None = None
    site_id: str | None = None
    form_id: str | None = None
    obj: Any | None = None


def _is_api_request() -> bool:
    return (
        request.path.startswith("/api/")
        or request.path.startswith("/admin/api/")
        or request.path.startswith("/data-management/api/")
        or request.path.startswith("/vaform/attachment/")
        or request.path.startswith("/vaform/media/")
    )


def _deny_response(reason: str, status_code: int):
    if status_code == 401 and not _is_api_request():
        return redirect(url_for("va_auth.va_login", next=request.url))
    if _is_api_request():
        return jsonify({"error": reason}), status_code
    va_permission_abortwithflash(reason, status_code)
    return None


def _log_decision(
    *,
    action: str,
    policy_scope: str,
    resource: ResourceContext | None,
    decision: str,
    deny_reason: str | None = None,
    predicate: str | None = None,
) -> None:
    payload = {
        "action": action,
        "route": request.path,
        "method": request.method,
        "user_id": current_user.get_id() if getattr(current_user, "is_authenticated", False) else None,
        "resource_type": resource.resource_type if resource else None,
        "resource_id": resource.resource_id if resource else None,
        "resolved_project_id": resource.project_id if resource else None,
        "resolved_project_site_id": (
            f"{resource.project_id}:{resource.site_id}"
            if resource and resource.project_id and resource.site_id
            else None
        ),
        "decision": decision,
        "deny_reason": deny_reason,
        "predicate": predicate,
        "policy_scope": policy_scope,
    }
    message = "authz_decision " + " ".join(
        f"{key}={value}" for key, value in payload.items() if value is not None
    )
    if decision == "deny":
        log.info(message)
    else:
        log.debug(message)


def _policy_registry() -> dict[str, auth_policy.ActionPolicy]:
    registry = current_app.extensions.get("authz_policy_registry")
    if not registry:
        raise AuthorizationConfigurationError("Authorization policy registry is not loaded.")
    return registry


def _predicate_registry() -> dict[str, Callable[[Any, ResourceContext | None], bool]]:
    registry = current_app.extensions.get("authz_predicates")
    if registry is None:
        raise AuthorizationConfigurationError("Authorization predicate registry is not loaded.")
    return registry


def _user_has_role(user, role: str) -> bool:
    return {
        "admin": user.is_admin,
        "project_pi": user.is_project_pi,
        "site_pi": user.is_site_pi,
        "data_manager": user.is_data_manager,
        "collaborator": user.is_collaborator,
        "coder": user.is_coder,
        "coding_tester": user.is_coding_tester,
        "reviewer": user.is_reviewer,
    }[role]()


def _role_has_any_scope(user, role: str) -> bool:
    if role == "admin":
        return user.is_admin()
    if role == "project_pi":
        return bool(user.get_project_pi_projects())
    if role == "site_pi":
        return bool(user.get_site_pi_project_sites())
    if role == "data_manager":
        return bool(user.get_data_manager_projects() or user.get_data_manager_project_sites())
    if role == "collaborator":
        return bool(user.get_collaborator_projects() or user.get_collaborator_project_sites())
    if role == "coder":
        return bool(user.get_coder_va_forms())
    if role == "coding_tester":
        return bool(user.get_coding_tester_va_forms())
    if role == "reviewer":
        return bool(user.get_reviewer_va_forms())
    return False


def _role_has_resource_scope(user, role: str, resource: ResourceContext) -> bool:
    if role == "admin":
        return user.is_admin()
    if role == "project_pi":
        return bool(resource.project_id) and user.has_project_pi_submission_access(resource.project_id)
    if role == "site_pi":
        return (
            bool(resource.project_id and resource.site_id)
            and user.has_site_pi_submission_access(resource.project_id, resource.site_id)
        )
    if role == "data_manager":
        if resource.form_id:
            return user.has_data_manager_form_access(resource.form_id)
        return (
            bool(resource.project_id and resource.site_id)
            and user.has_data_manager_submission_access(resource.project_id, resource.site_id)
        )
    if role == "collaborator":
        return (
            bool(resource.project_id and resource.site_id)
            and user.has_collaborator_submission_access(resource.project_id, resource.site_id)
        )
    if role == "coder":
        return bool(resource.form_id) and user.is_coder(resource.form_id)
    if role == "coding_tester":
        return bool(resource.form_id) and user.is_coding_tester(resource.form_id)
    if role == "reviewer":
        return bool(resource.form_id) and user.is_reviewer(resource.form_id)
    return False


def authorize_action(user, action: str, resource: ResourceContext | None = None) -> auth_policy.ActionPolicy:
    if not user.is_authenticated:
        raise AuthorizationDenied("Authentication required.", status_code=401)
    if user.user_status != VaStatuses.active:
        logout_user()
        raise AuthorizationDenied("Authentication required.", status_code=401)

    registry = _policy_registry()
    policy = registry.get(action)
    if policy is None:
        raise AuthorizationConfigurationError(f"Missing authorization policy for action {action}.")

    if policy.scope == "authenticated":
        scope_ok = True
        allowed_roles = []
    else:
        allowed_roles = [role for role in policy.roles if _user_has_role(user, role)]
        if not allowed_roles:
            raise AuthorizationDenied(f"{', '.join(policy.roles)} access is required.")

    if policy.scope == "global":
        scope_ok = any(role == "admin" and user.is_admin() for role in allowed_roles)
    elif policy.scope == "any_scope":
        scope_ok = any(_role_has_any_scope(user, role) for role in allowed_roles)
    elif policy.scope == "resource_scope":
        if resource is None:
            raise AuthorizationConfigurationError(
                f"Action {action} requires a resource context."
            )
        scope_ok = any(_role_has_resource_scope(user, role, resource) for role in allowed_roles)
    elif policy.scope != "authenticated":
        raise AuthorizationConfigurationError(
            f"Action {action} uses unsupported scope {policy.scope!r}."
        )

    if not scope_ok:
        raise AuthorizationDenied("Access denied.")

    if policy.predicate:
        predicate_fn = _predicate_registry().get(policy.predicate)
        if predicate_fn is None:
            raise AuthorizationConfigurationError(
                f"Action {action} references unknown predicate {policy.predicate}."
            )
        try:
            predicate_ok = predicate_fn(user, resource)
        except Exception as exc:
            raise PredicateExecutionError(
                f"Predicate {policy.predicate} failed: {exc}"
            ) from exc
        if not predicate_ok:
            raise AuthorizationDenied("Access denied.")

    _log_decision(
        action=action,
        policy_scope=policy.scope,
        resource=resource,
        decision="allow",
        predicate=policy.predicate,
    )
    return policy


def _handle_auth_exception(action: str, exc: Exception, resource: ResourceContext | None):
    if isinstance(exc, AuthorizationDenied):
        _log_decision(
            action=action,
            policy_scope=_policy_registry().get(action).scope if _policy_registry().get(action) else "unknown",
            resource=resource,
            decision="deny",
            deny_reason=exc.reason,
            predicate=_policy_registry().get(action).predicate if _policy_registry().get(action) else None,
        )
        return _deny_response(exc.reason, exc.status_code)
    if isinstance(exc, ResourceResolutionError):
        log.error("authz_resource_resolution_error action=%s route=%s reason=%s", action, request.path, exc.reason)
        return _deny_response(exc.reason, exc.status_code)
    if isinstance(exc, PredicateExecutionError):
        log.error("authz_predicate_error action=%s route=%s error=%s", action, request.path, exc, exc_info=True)
        return _deny_response("Access denied.", 403)
    if isinstance(exc, AuthorizationConfigurationError):
        log.error("authz_configuration_error action=%s route=%s error=%s", action, request.path, exc, exc_info=True)
        return _deny_response("Authorization configuration error.", 500)
    raise exc


def action_authorized(
    action: str,
    *,
    resource_resolver: Callable[..., ResourceContext | None] | None = None,
):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            resource: ResourceContext | None = None
            try:
                g.authz_action = action
                g.authz_resource = resource
                if not getattr(current_user, "is_authenticated", False):
                    authorize_action(current_user, action, None)
                else:
                    if resource_resolver is not None:
                        resource = resource_resolver(*args, **kwargs)
                    g.authz_resource = resource
                    authorize_action(current_user, action, resource)
            except Exception as exc:
                handled = _handle_auth_exception(action, exc, resource)
                if handled is not None:
                    return handled
            return f(*args, **kwargs)

        wrapped.__authz_action__ = action
        wrapped.__authz_resource_resolver__ = resource_resolver
        return wrapped

    return decorator


def dynamic_action_authorized(
    action_resolver: Callable[..., tuple[str | None, ResourceContext | None]],
):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            action: str | None = None
            resource: ResourceContext | None = None
            try:
                action, resource = action_resolver(*args, **kwargs)
                g.authz_action = action
                g.authz_resource = resource
                if action is None:
                    return f(*args, **kwargs)
                if not getattr(current_user, "is_authenticated", False):
                    authorize_action(current_user, action, None)
                else:
                    authorize_action(current_user, action, resource)
            except Exception as exc:
                handled = _handle_auth_exception(action or "dynamic", exc, resource)
                if handled is not None:
                    return handled
            return f(*args, **kwargs)

        wrapped.__authz_dynamic__ = True
        return wrapped

    return decorator


def _validate_route_coverage(app) -> None:
    missing = []
    for endpoint, view_func in app.view_functions.items():
        endpoint_parts = set(endpoint.split(".")[:-1])
        if not (endpoint_parts & auth_policy.MIGRATED_BLUEPRINTS):
            continue
        if endpoint in {"static"}:
            continue
        if not (
            getattr(view_func, "__authz_action__", None)
            or getattr(view_func, "__authz_dynamic__", False)
        ):
            missing.append(endpoint)
    if missing:
        raise AuthorizationConfigurationError(
            "Migrated blueprints contain routes without action mapping: "
            + ", ".join(sorted(missing))
        )


def init_app(app) -> None:
    policies = auth_policy.load_policies()
    app.extensions["authz_policy_registry"] = policies
    app.extensions["authz_predicates"] = {}
    with app.app_context():
        from app.authz.predicates import register_predicates

        app.extensions["authz_predicates"] = register_predicates()
        _validate_route_coverage(app)
