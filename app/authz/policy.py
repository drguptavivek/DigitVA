from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from app.models.va_selectives import VaAccessRoles


VALID_RESOURCES = frozenset({"none", "submission", "form", "grant", "user"})
VALID_SCOPES = frozenset({"global", "any_scope", "resource_scope"})
MIGRATED_BLUEPRINTS = frozenset(
    {
        "data_management",
        "data_management_api",
        "cod_buckets_api",
        "coding",
        "coding_api",
        "workflow",
    }
)


class PolicyLoadError(RuntimeError):
    pass


class PolicyValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActionPolicy:
    action_id: str
    roles: tuple[str, ...]
    resource: str
    scope: str
    predicate: str | None
    reason: str


def policy_path() -> Path:
    return Path(__file__).with_name("policy.toml")


def load_policies() -> dict[str, ActionPolicy]:
    try:
        with policy_path().open("rb") as handle:
            raw = tomllib.load(handle)
    except OSError as exc:
        raise PolicyLoadError(f"Unable to read auth policy TOML: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise PolicyLoadError(f"Invalid auth policy TOML: {exc}") from exc

    action_section = raw.get("action")
    if not isinstance(action_section, dict) or not action_section:
        raise PolicyValidationError("Auth policy must define at least one [action.*] entry.")

    policies: dict[str, ActionPolicy] = {}
    valid_roles = {role.value for role in VaAccessRoles}
    for action_id, entry in action_section.items():
        if not isinstance(entry, dict):
            raise PolicyValidationError(f"Action {action_id} must be a TOML table.")
        roles = entry.get("roles")
        resource = entry.get("resource")
        scope = entry.get("scope")
        predicate = entry.get("predicate")
        reason = entry.get("reason")

        if not isinstance(roles, list) or not roles:
            raise PolicyValidationError(f"Action {action_id} must define a non-empty roles list.")
        normalized_roles = tuple(str(role) for role in roles)
        unknown_roles = sorted(set(normalized_roles) - valid_roles)
        if unknown_roles:
            raise PolicyValidationError(
                f"Action {action_id} references unknown roles: {unknown_roles}."
            )
        if resource not in VALID_RESOURCES:
            raise PolicyValidationError(
                f"Action {action_id} has invalid resource {resource!r}."
            )
        if scope not in VALID_SCOPES:
            raise PolicyValidationError(f"Action {action_id} has invalid scope {scope!r}.")
        if predicate is not None and not isinstance(predicate, str):
            raise PolicyValidationError(
                f"Action {action_id} predicate must be a string when present."
            )
        if not isinstance(reason, str) or not reason.strip():
            raise PolicyValidationError(f"Action {action_id} must define a non-empty reason.")

        policies[action_id] = ActionPolicy(
            action_id=action_id,
            roles=normalized_roles,
            resource=resource,
            scope=scope,
            predicate=predicate,
            reason=reason.strip(),
        )

    return policies
