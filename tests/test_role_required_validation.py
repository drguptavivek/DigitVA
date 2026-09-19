"""role_required() validates its role names when the decorator is applied.

Before this guard, role names absent from _ROLE_METHODS were filtered out of
the Layer-3 check. A route decorated only with unknown names therefore ran
any() over an empty generator, denying every user — including admins — while
the 403 log line named the bogus roles as if they were real. A typo was
indistinguishable from a deliberately locked-down route.

The names are now checked at decoration time (i.e. at import), so the failure
is a startup ValueError instead of a silent runtime 403.

See docs/policy/auth-decorator-rbac.md (the decorator specification) and
docs/policy/access-control-model.md (the role set).
"""
import ast
import importlib
from pathlib import Path

import flask
import pytest

from app.decorators.role_required import _ROLE_METHODS, role_required
from app.models import VaStatuses

# The module object, not the attribute path. app/decorators/__init__.py does
# `from app.decorators.role_required import role_required`, which rebinds the
# name in the package namespace — so the dotted string
# "app.decorators.role_required.current_user" resolves the middle segment to
# the FUNCTION and hangs a stray attribute off it. With monkeypatch's
# raising=False that is a silent no-op and the stub never takes effect.
_decorator_module = importlib.import_module("app.decorators.role_required")

APP_DIR = Path("app")


def _call_site_role_names() -> dict[str, list[str]]:
    """Every string literal passed to role_required() across app/.

    Returns {role_name: [source locations]} so a failure names the offender.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "role_required":
                continue
            for arg in node.args:
                assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
                    f"{path}:{node.lineno} passes a non-literal role to "
                    "role_required(); decoration-time validation cannot vouch for it"
                )
                found.setdefault(arg.value, []).append(f"{path}:{node.lineno}")
    return found


# ── Positive controls ────────────────────────────────────────────────────────
# docs/policy/test-harness.md, "Checks that cannot fail for what they appear to
# test": a file that only proves ValueError on a bad name passes just as well
# if the good path was broken along the way. Removing the
# `if role in _ROLE_METHODS` filter from the Layer-3 any() touched live gating
# code, so the gate itself is asserted here, in both directions.
#
# No DB: the decorator reads current_user off its own module namespace, so a
# stub is enough (test-harness Rule 6). Nothing is registered on the session
# app's url_map, which would outlive the test (Rule 7).


class _StubUser:
    is_authenticated = True
    user_status = VaStatuses.active

    def __init__(self, **predicates):
        self._predicates = predicates

    def __getattr__(self, name):
        if name in self._predicates:
            return lambda: self._predicates[name]
        raise AttributeError(name)

    def get_id(self):
        return "stub-user"


def _call_decorated_view(monkeypatch, roles, user, path="/api/probe"):
    """Run a view gated on `roles` as `user`, returning (sentinel | response)."""
    monkeypatch.setattr(_decorator_module, "current_user", user)

    @role_required(*roles)
    def view():
        return "view-body-ran"

    # current_app, not a conftest import: pytest loads conftest.py as the
    # top-level module `conftest`, so `tests.conftest` would be a second
    # module object whose session globals are never set. base.py uses the
    # same idiom (tests/base.py:177).
    app = flask.current_app._get_current_object()
    with app.test_request_context(path):
        return view()


def test_a_valid_role_still_admits_the_holder(monkeypatch):
    result = _call_decorated_view(
        monkeypatch, ("coder",), _StubUser(is_coder=True)
    )
    assert result == "view-body-ran"


def test_a_valid_role_still_refuses_a_non_holder(monkeypatch):
    body, status = _call_decorated_view(
        monkeypatch, ("coder",), _StubUser(is_coder=False)
    )
    assert status == 403
    assert "coder" in body.get_json()["error"]


def test_or_semantics_survive_on_the_second_listed_role(monkeypatch):
    """The removed filter sat inside this any() — check it still short-circuits
    across roles rather than only honouring the first one."""
    result = _call_decorated_view(
        monkeypatch,
        ("coder", "admin"),
        _StubUser(is_coder=False, is_admin=True),
    )
    assert result == "view-body-ran"


# ── The raise ────────────────────────────────────────────────────────────────

def test_unknown_role_name_raises_at_decoration_time():
    with pytest.raises(ValueError) as excinfo:
        role_required("not_a_real_role")

    message = str(excinfo.value)
    assert "not_a_real_role" in message
    # The error has to name the valid set, or the next person just guesses again.
    for valid in _ROLE_METHODS:
        assert valid in message


def test_unknown_role_rejected_even_when_mixed_with_a_valid_one():
    """The old filter let this through and silently gated on "admin" alone."""
    with pytest.raises(ValueError, match="codr"):
        role_required("admin", "codr")


def test_empty_role_list_raises():
    """A bare role_required() would deny everyone, the same failure mode."""
    with pytest.raises(ValueError):
        role_required()


def test_every_role_name_used_in_the_codebase_is_accepted():
    """Validation must not break any route that exists today."""
    call_sites = _call_site_role_names()
    assert call_sites, "found no role_required() call sites — the scan is broken"

    unknown = {
        role: locations
        for role, locations in call_sites.items()
        if role not in _ROLE_METHODS
    }
    assert not unknown, (
        "role_required() call sites use names with no _ROLE_METHODS entry; "
        f"these routes deny every user: {unknown}"
    )

    for role in call_sites:
        role_required(role)


def test_role_methods_is_a_literal_dict_never_derived_from_the_enum():
    """The wrong turn this whole change exists to prevent is "fix" the unknown-role
    raise by generating _ROLE_METHODS from VaAccessRoles — every enum member would
    become a live gate, silently widening access behind what looks like a lint fix.

    A value check cannot express this (the dict may legitimately grow to cover
    every enum member), so assert the structure instead: a Dict literal with
    string-constant keys. A comprehension over VaAccessRoles, a dict() call, or
    any generated form fails here.
    """
    source = Path("app/decorators/role_required.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "_ROLE_METHODS" for t in node.targets
        )
    ]
    assert len(assignments) == 1, "expected exactly one _ROLE_METHODS assignment"
    value = assignments[0].value

    assert isinstance(value, ast.Dict), (
        "_ROLE_METHODS must be a dict literal, not "
        f"{type(value).__name__} — a derived mapping makes every role routable"
    )
    for key in value.keys:
        assert isinstance(key, ast.Constant) and isinstance(key.value, str), (
            "every _ROLE_METHODS key must be a written-out string literal; "
            "a computed key means roles are being generated, not declared"
        )


def test_the_raise_is_at_decoration_time_not_at_first_request():
    """Decoration-time and request-time failure are different bugs, and the
    whole value of this change is which one you get. Asserted three ways: no
    request context exists when it raises, the view body never runs, and the
    name is never bound."""
    assert not flask.has_request_context()

    body_ran = []

    with pytest.raises(ValueError):
        @role_required("not_a_real_role")
        def view():
            body_ran.append(True)
            return "unreachable"

    assert not body_ran
    assert "view" not in locals()


def test_a_valid_role_decorates_without_raising():
    """The control for the test above: same shape, valid name, no raise."""
    @role_required("coder")
    def view():
        return "ok"

    assert callable(view)
    assert view.__name__ == "view"
