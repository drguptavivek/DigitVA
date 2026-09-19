"""Every registered route is auth-guarded, or is public by design.

There is no pending list: as of 2026-09-19 every route in `app.url_map` either
declares a guard or sits on `PUBLIC_BY_DESIGN` with a reason. A new route has
exactly those two outcomes -- "undecided" is not one of them.

`role_required`'s own validation (tests/test_role_required_validation.py)
guarantees that a route's role *names* are real. It cannot say anything about a
route that carries no decorator at all -- and that is the worse failure of the
two. A mistyped role name raises at import; a missing decorator **fails open**
and serves the view to everyone. `docs/policy/access-control-model.md` records
three found by audit, one of them a field-mapping panel that was simply
unguarded.

This walks `app.url_map` at runtime rather than sweeping the source with `ast`,
because only the runtime map sees blueprints registered dynamically.

**Why not `hasattr(f, "__wrapped__")`.** Every `functools.wraps` decorator sets
`__wrapped__`, so its presence says a function was decorated, not that it was
*authenticated*. On this app 322 of 334 rules carry it, including routes with no
auth decorator at all. The guard signal must name the guard:

  - `role_required` stamps `ROLE_MARKER_ATTR` on its wrapper (see
    docs/policy/auth-decorator-rbac.md section 3);
  - Flask-Login's `login_required` is identified by its wrapper's `__code__`.
    `__module__`/`__qualname__` are useless here: `functools.wraps` copies both
    from the *view*, so `login_required`'s wrapper claims to live in the
    application module it decorated. `__code__` is never rewritten.

See docs/policy/auth-decorator-rbac.md and .tasks/auth-decorator-followups.md.
"""
import flask
import pytest
from flask_login import login_required

from app.decorators.role_required import (
    API_PATH_PREFIXES,
    ROLE_MARKER_ATTR,
    role_required,
)

# Depth cap for the __wrapped__ walk. Real stacks are two or three deep; the cap
# plus the identity set below mean a self-referential or absurd chain fails the
# endpoint loudly instead of hanging the suite.
_MAX_WRAPPER_DEPTH = 32

_LOGIN_REQUIRED_CO_QUALNAME = "login_required.<locals>.decorated_view"


# ── Allowlist ────────────────────────────────────────────────────────────────

PUBLIC_BY_DESIGN = frozenset({
    # Static asset serving; Flask's own endpoint, no application data.
    "static",
    # Liveness probe for the container orchestrator; must answer before login.
    "health.health_check",
    # The login form and its POST. Cannot require a session to create one.
    "va_auth.va_login",
    # POST-only logout. Unwrapped but not public in effect: the body starts with
    # `if current_user.is_anonymous: return redirect(...)`, so an anonymous POST
    # is a redirect and nothing else. Checks current_user itself.
    "va_auth.va_logout",
    # Banner polled by the login page before a session exists; returns only the
    # active maintenance window, no user or submission data.
    "va_auth.site_maintenance_status",
    # Account-recovery and first-login flows. All four are reachable only with a
    # signed token or an email address, and by definition run with no session.
    "va_auth.forgot_password",
    "va_auth.reset_password",
    "va_auth.resend_verification",
    "va_auth.verify_email",
    # The public home page (/, /index, /vaindex). The system has a dedicated
    # login page; the landing page is what an anonymous visitor lands on and
    # renders no user data.
    "va_main.va_index",
    # Streams a WHO VA reference PDF from a fixed on-disk registry
    # (WHO_VA_DOCUMENTS); the slug must be a registry key, so no arbitrary read.
    # Published WHO material, deliberately readable without an account.
    "va_main.who_va_document",
    # Help index. Renders the shell; the page list is filtered per user by
    # `_visible_pages`, which treats anonymous as holding no roles, so an
    # anonymous visitor sees only the `roles=None` pages.
    "help.index",
    # A single help page, public by design *and* role-filtered in the body:
    # `_user_has_role(current_user, page_info[4])` aborts 403 for a page whose
    # registry entry names roles. That in-body filtering is the guard for the
    # role-restricted pages and must stay; only the `roles=None` pages
    # (getting-started, authentication, password-reset, email-verification,
    # user-roles, profile) render for anonymous visitors, and those are the
    # sign-in and account instructions a logged-out user needs.
    "help.page",
    # Index of the curated user-facing engineering docs. Public by design: the
    # curated list in ENGINEERING_DOCS is the published documentation set.
    "help.docs_index",
    # Renders one curated repo markdown doc (ENGINEERING_DOCS) as HTML. The slug
    # must be a registry key and `_render_md` blocks traversal, so the exposure
    # is exactly that curated list, which is published by design.
    "help.doc_page",
})

_ALLOWED = PUBLIC_BY_DESIGN


# ── The checker ──────────────────────────────────────────────────────────────

def _wrapper_chain(view_function):
    """The view function and everything it wraps, outermost first.

    Cycle-safe (identity set) and depth-capped, so a pathological chain returns
    what it has rather than spinning.
    """
    chain = []
    seen = set()
    current = view_function
    while current is not None and id(current) not in seen:
        if len(chain) >= _MAX_WRAPPER_DEPTH:
            break
        seen.add(id(current))
        chain.append(current)
        current = getattr(current, "__wrapped__", None)
    return chain


def _is_login_required_wrapper(function):
    """True for Flask-Login's `login_required` wrapper.

    Identified by its code object, which `functools.wraps` does not touch --
    unlike `__module__` and `__qualname__`, which it overwrites with the
    decorated view's.
    """
    code = getattr(function, "__code__", None)
    if code is None:
        return False
    filename = getattr(code, "co_filename", "").replace("\\", "/")
    return (
        getattr(code, "co_qualname", "") == _LOGIN_REQUIRED_CO_QUALNAME
        and filename.endswith("flask_login/utils.py")
    )


def _is_guarded(view_function):
    """True if any layer of this view's decorator stack declares an auth guard.

    Class-based views (`MethodView`) attach the class as `view_class` and the
    registered function is a thin dispatcher, so the decorators live on the
    class or its `decorators` list rather than on the chain above. None are
    registered today; rather than let that shape pass silently if one is added,
    it is reported as unguarded and `test_no_unhandled_class_based_views` says
    why.
    """
    view_class = getattr(view_function, "view_class", None)
    if view_class is not None:
        return False
    return any(
        hasattr(function, ROLE_MARKER_ATTR) or _is_login_required_wrapper(function)
        for function in _wrapper_chain(view_function)
    )


def unguarded_endpoints(app):
    """Every rule in `app.url_map` whose view declares no auth guard.

    Returns a sorted list of `(endpoint, rule, methods)`, methods as a
    comma-joined string covering every HTTP method the rule accepts.
    """
    found = []
    for rule in app.url_map.iter_rules():
        view_function = app.view_functions.get(rule.endpoint)
        if view_function is None:
            continue
        if not _is_guarded(view_function):
            methods = ",".join(sorted(rule.methods or ()))
            found.append((rule.endpoint, str(rule), methods))
    return sorted(found)


def _format(rows):
    return "\n".join(f"  {ep}  {rule}  {methods}" for ep, rule, methods in rows)


@pytest.fixture(scope="module")
def app():
    """The session-scoped app conftest already built and pushed (harness rule 2).

    Read off the live app context rather than importing conftest's module
    global: pytest imports the root conftest under its own module name, so
    `from tests.conftest import ...` binds a *second* copy whose globals are
    never populated and whose app is None.
    """
    return flask.current_app._get_current_object()


# ── Item 1: route auth coverage ──────────────────────────────────────────────

def test_every_route_is_guarded_or_allowlisted(app):
    offenders = [
        row for row in unguarded_endpoints(app) if row[0] not in _ALLOWED
    ]
    assert not offenders, (
        "These endpoints have no auth decorator and are not on "
        "PUBLIC_BY_DESIGN. "
        "An unguarded route fails open and serves every visitor:\n"
        f"{_format(offenders)}\n\n"
        "Fix by decorating the view with @role_required(...), or -- if it must "
        "be reachable unauthenticated -- add it to PUBLIC_BY_DESIGN in this "
        "module with a one-line reason."
    )


def test_allowlist_has_no_stale_entries(app):
    """An allowlist entry for a route that no longer exists is a standing
    exemption nobody is reading. It must be deleted with the route."""
    registered = {rule.endpoint for rule in app.url_map.iter_rules()}
    stale = sorted(_ALLOWED - registered)
    assert not stale, (
        "Allowlisted endpoints that are no longer in url_map -- delete them:\n"
        + "\n".join(f"  {endpoint}" for endpoint in stale)
    )


def test_allowlisted_endpoints_are_still_unguarded(app):
    """The allowlist must shrink honestly.

    Separate from the coverage test so the reason for the failure is
    unambiguous: nothing is unguarded, an exemption simply outlived its need.
    Decorating an allowlisted view is the good outcome -- remove it from the
    list in the same change.
    """
    unguarded = {row[0] for row in unguarded_endpoints(app)}
    now_guarded = sorted(_ALLOWED & {
        rule.endpoint
        for rule in app.url_map.iter_rules()
    } - unguarded)
    assert not now_guarded, (
        "These endpoints are allowlisted as unguarded but now carry an auth "
        "decorator. Remove them from PUBLIC_BY_DESIGN:\n"
        + "\n".join(f"  {endpoint}" for endpoint in now_guarded)
    )


# ── Vacuity guard: positive and negative controls for the checker ────────────
#
# These run `unguarded_endpoints` against a throwaway `flask.Flask("...")`
# rather than the session app, because the check must see a route that IS
# unguarded and the shared app must not be mutated (harness rule 7). Harness
# rule 2 forbids a second `create_app()`; a bare `flask.Flask` with three routes
# and no extensions, config or database is not that -- it never touches the
# session schema and is discarded with the test.

def _probe_app():
    probe = flask.Flask("route_auth_coverage_probe")

    @probe.route("/unguarded")
    def unguarded_view():
        return "open"

    @probe.route("/role-gated")
    @role_required("admin")
    def role_gated_view():
        return "gated"

    @probe.route("/login-gated")
    @login_required
    def login_gated_view():
        return "gated"

    return probe


def test_checker_reports_an_unguarded_view():
    """Positive control. If this ever passes vacuously, so does every assertion
    above it."""
    endpoints = {row[0] for row in unguarded_endpoints(_probe_app())}
    assert "unguarded_view" in endpoints


def test_checker_does_not_report_guarded_views():
    """Negative controls, one per guard signal. `login_gated_view` also proves
    the `__code__` detection works after `functools.wraps` has rewritten
    `__module__` and `__qualname__` to this test module's."""
    endpoints = {row[0] for row in unguarded_endpoints(_probe_app())}
    assert "role_gated_view" not in endpoints
    assert "login_gated_view" not in endpoints


def test_login_required_wrapper_is_not_detected_by_module_or_qualname():
    """Guards the guard: documents why `_is_login_required_wrapper` reads
    `__code__`. If flask_login ever stops using `functools.wraps`, this fails
    and the simpler signal becomes available."""
    @login_required
    def some_view():
        return "x"

    assert some_view.__module__ == __name__
    assert some_view.__qualname__.startswith(
        "test_login_required_wrapper_is_not_detected_by_module_or_qualname."
    )
    assert _is_login_required_wrapper(some_view)


def test_wrapped_alone_would_not_have_worked(app):
    """The premise of this module: `__wrapped__` is not an auth signal.

    Asserts that rules exist which carry `__wrapped__` and are nonetheless
    unguarded -- so a `hasattr(f, "__wrapped__")` version of this test would
    have passed while those routes served everyone.
    """
    unguarded = {row[0] for row in unguarded_endpoints(app)}
    wrapped_but_unguarded = {
        rule.endpoint
        for rule in app.url_map.iter_rules()
        if rule.endpoint in unguarded
        and hasattr(app.view_functions[rule.endpoint], "__wrapped__")
    }
    assert wrapped_but_unguarded, (
        "No unguarded endpoint carries __wrapped__ any more. If that is real, "
        "this module's rationale needs rewriting -- but check first that "
        "unguarded_endpoints() has not simply stopped finding anything."
    )


def test_no_unhandled_class_based_views(app):
    """`_is_guarded` cannot read decorators off a MethodView's class, so it
    reports such views as unguarded rather than guessing. None are registered
    today; if one appears, teach `_is_guarded` about `view_class.decorators`
    instead of allowlisting it."""
    class_based = sorted(
        rule.endpoint
        for rule in app.url_map.iter_rules()
        if getattr(app.view_functions.get(rule.endpoint), "view_class", None)
    )
    assert not class_based, (
        "Class-based views are registered and this module does not understand "
        "their decorators yet:\n"
        + "\n".join(f"  {endpoint}" for endpoint in class_based)
    )


# ── Item 2: the is_api prefix tuple covers every API blueprint ───────────────

def test_every_api_rule_matches_an_api_path_prefix(app):
    """`role_required` picks JSON vs HTML from `API_PATH_PREFIXES`.

    An API blueprint mounted at a fifth prefix gets an HTML redirect where the
    client expects a JSON 401, so `base.js` never raises the session-expired
    modal and the failure surfaces only as "my tab stopped refreshing".

    Asserted against the real constant, not a copy of the tuple.
    """
    offenders = []
    for rule in app.url_map.iter_rules():
        blueprint = rule.endpoint.rpartition(".")[0]
        looks_like_api = "api" in blueprint.lower() or "/api/" in str(rule)
        if looks_like_api and not str(rule).startswith(API_PATH_PREFIXES):
            offenders.append((rule.endpoint, str(rule)))

    assert not offenders, (
        "These rules look like API routes but match none of "
        f"{API_PATH_PREFIXES}, so role_required would answer them with an HTML "
        "redirect instead of a JSON 401:\n"
        + "\n".join(f"  {endpoint}  {rule}" for endpoint, rule in sorted(offenders))
        + "\n\nAdd the prefix to API_PATH_PREFIXES in "
        "app/decorators/role_required.py, or move the blueprint under an "
        "existing one."
    )


def test_api_path_prefixes_are_all_in_use(app):
    """A prefix nobody serves is dead configuration that reads as coverage."""
    rules = [str(rule) for rule in app.url_map.iter_rules()]
    unused = sorted(
        prefix for prefix in API_PATH_PREFIXES
        if not any(rule.startswith(prefix) for rule in rules)
    )
    assert not unused, f"API_PATH_PREFIXES entries matching no route: {unused}"
