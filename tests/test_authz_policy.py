from flask import current_app

from app.authz.policy import MIGRATED_BLUEPRINTS, load_policies


def test_authz_policy_entries_have_reason():
    policies = load_policies()

    assert policies
    for action_id, policy in policies.items():
        assert policy.reason, f"{action_id} is missing a reason"
        assert policy.roles, f"{action_id} is missing roles"


def test_migrated_routes_have_action_mapping():
    missing = []
    for endpoint, view_func in current_app.view_functions.items():
        endpoint_parts = set(endpoint.split(".")[:-1])
        if not (endpoint_parts & MIGRATED_BLUEPRINTS):
            continue
        if endpoint == "static":
            continue
        if not (
            getattr(view_func, "__authz_action__", None)
            or getattr(view_func, "__authz_dynamic__", False)
        ):
            missing.append(endpoint)

    assert missing == []
