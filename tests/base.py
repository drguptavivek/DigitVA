"""
Base test case for DigitVA tests.

Uses TestConfig which points to a separate `minerva_test` database so that
the development database is never touched during test runs.

Schema lifecycle (session-scoped, managed by conftest.py):
  - conftest.pytest_sessionstart: creates schema ONCE for the entire session
  - conftest.pytest_sessionfinish: drops schema ONCE after all tests

Per-class setup (BaseTestCase.setUpClass):
  - Re-uses the session schema and app; no drop_all/create_all per class.
  - Seeds base fixtures idempotently (shared across all classes in the session).
  - Subclass fixtures use unique IDs and accumulate harmlessly; schema is dropped at session end.

Per-test isolation (outer transaction + nested savepoint):
  - setUp: bind db.session to a dedicated connection, open an outer
    transaction, then open a nested savepoint
  - tearDown: remove the scoped session and roll back the outer transaction

  This keeps route code free to call db.session.commit() while still ensuring
  that all writes are discarded at the end of each test.

Standard fixtures available on every test class (via class attributes):
  - base_admin_user / base_admin_id         — global admin
  - base_project_pi_user / base_project_pi_id — project PI for BASE_PROJECT_ID
  - base_coder_user / base_coder_id         — coder for BASE_SITE_ID
  - BASE_PROJECT_ID / BASE_SITE_ID          — project + site + mapping

Subclasses may add class-level fixtures in their own setUpClass (call
super().setUpClass() first). Subclass fixtures must use unique IDs so they
do not conflict with base fixtures or other test classes in the same session.

Provisioning the test database (one-time, already done):
  docker exec minerva_db psql -U minerva -c "CREATE DATABASE minerva_test;"

Running tests (inside Docker):
  python -m pytest tests/ -v
"""

import unittest
import uuid
import warnings
from datetime import datetime, timezone

# Suppress deprecation warnings from libraries in tests
warnings.filterwarnings("ignore", category=DeprecationWarning)

from flask_login.utils import _create_identifier
from itsdangerous import URLSafeTimedSerializer
import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from config import TestConfig


class BaseTestCase(unittest.TestCase):
    """
    Inherit from this class instead of unittest.TestCase.

    Subclasses may override `config_class` to supply a different config,
    but TestConfig is the right default for all automated tests.
    """

    config_class = TestConfig

    # IDs reserved for base fixtures — subclasses must use different IDs
    BASE_PROJECT_ID = "BASE01"
    BASE_SITE_ID = "BS01"

    @classmethod
    def setUpClass(cls):
        # Reuse the session-scoped app and context created by conftest.pytest_sessionstart.
        # Schema already exists — no drop_all/create_all here.
        #
        # Retrieve the app from the currently-active app context.
        # conftest.pytest_sessionstart pushes the context before any setUpClass
        # runs, so current_app is always available here.  This avoids any
        # module-identity issues with how pytest imports conftest plugins.
        from flask import current_app
        cls.app = current_app._get_current_object()
        cls.ctx = None  # context is managed by conftest; do not push/pop per class
        db.session().expire_on_commit = False

        # _seed_base_fixtures is idempotent: safe to call once per class.
        # Base fixtures (BASE_PROJECT_ID, BASE_SITE_ID, 3 users) are shared across
        # all test classes and seeded once; subsequent classes find and reuse them.
        # Subclass-specific fixtures use unique IDs so they never conflict.
        cls._seed_base_fixtures()

    @classmethod
    def tearDownClass(cls):
        # Per-class teardown is lightweight: per-test savepoints handle data isolation.
        # The full schema drop happens once at session end in conftest.pytest_sessionfinish.
        db.session.expire_all()

    @classmethod
    def _seed_base_fixtures(cls):
        """
        Create (or find) the minimal reference data that every test class may rely on.

        Idempotent: if BASE_PROJECT_ID/BASE_SITE_ID/users already exist (seeded by a
        previous test class in the same session), they are reused rather than re-inserted.
        This allows all test classes to share a single copy of the base fixtures for the
        whole pytest session without unique-constraint conflicts.
        """
        project_site = cls._ensure_project_site_fixture(
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            project_name="Base Test Project",
            project_nickname="BaseTest",
            site_name="Base Test Site",
        )

        cls.base_admin_user = cls._get_or_make_user("base.admin@test.local", "BaseAdmin123")
        cls.base_project_pi_user = cls._get_or_make_user("base.project_pi@test.local", "BaseProjectPi123")
        cls.base_coder_user = cls._get_or_make_user("base.coder@test.local", "BaseCoder123")

        # Grants are idempotent via the role+user+scope combination
        admin_grant = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == cls.base_admin_user.user_id,
                VaUserAccessGrants.role == VaAccessRoles.admin,
            )
        )
        if admin_grant is None:
            db.session.add(VaUserAccessGrants(
                user_id=cls.base_admin_user.user_id,
                role=VaAccessRoles.admin,
                scope_type=VaAccessScopeTypes.global_scope,
                notes="base admin grant",
                grant_status=VaStatuses.active,
            ))

        pi_grant = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == cls.base_project_pi_user.user_id,
                VaUserAccessGrants.role == VaAccessRoles.project_pi,
                VaUserAccessGrants.project_id == cls.BASE_PROJECT_ID,
            )
        )
        if pi_grant is None:
            db.session.add(VaUserAccessGrants(
                user_id=cls.base_project_pi_user.user_id,
                role=VaAccessRoles.project_pi,
                scope_type=VaAccessScopeTypes.project,
                project_id=cls.BASE_PROJECT_ID,
                notes="base project pi grant",
                grant_status=VaStatuses.active,
            ))

        coder_grant = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == cls.base_coder_user.user_id,
                VaUserAccessGrants.role == VaAccessRoles.coder,
                VaUserAccessGrants.project_site_id == project_site.project_site_id,
            )
        )
        if coder_grant is None:
            db.session.add(VaUserAccessGrants(
                user_id=cls.base_coder_user.user_id,
                role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site.project_site_id,
                notes="base coder grant",
                grant_status=VaStatuses.active,
            ))

        db.session.commit()

        cls.base_admin_id = str(cls.base_admin_user.user_id)
        cls.base_project_pi_id = str(cls.base_project_pi_user.user_id)
        cls.base_coder_id = str(cls.base_coder_user.user_id)

    @classmethod
    def _ensure_project_site_fixture(
        cls,
        *,
        project_id,
        site_id,
        project_name,
        project_nickname,
        site_name,
        site_abbr=None,
        create_research_project=True,
        now=None,
    ):
        """Create or reuse a project/site/runtime scope graph for route tests."""
        now = now or datetime.now(timezone.utc)
        site_abbr = site_abbr or site_id

        project = db.session.get(VaProjectMaster, project_id)
        if project is None:
            project = VaProjectMaster(
                project_id=project_id,
                project_code=project_id,
                project_name=project_name,
                project_nickname=project_nickname,
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
            db.session.add(project)
            db.session.flush()

        if create_research_project:
            research_project = db.session.get(VaResearchProjects, project_id)
            if research_project is None:
                research_project = VaResearchProjects(
                    project_id=project_id,
                    project_code=project_id,
                    project_name=project_name,
                    project_nickname=project_nickname,
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
                db.session.add(research_project)
                db.session.flush()

        site_master = db.session.get(VaSiteMaster, site_id)
        if site_master is None:
            site_master = VaSiteMaster(
                site_id=site_id,
                site_name=site_name,
                site_abbr=site_abbr,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
            db.session.add(site_master)
            db.session.flush()

        site = db.session.get(VaSites, site_id)
        if site is not None and site.project_id != project_id:
            raise AssertionError(
                f"Test fixture site_id {site_id!r} is already bound to project "
                f"{site.project_id!r}; choose a globally unique site_id for {project_id!r}."
            )
        if site is None:
            site = VaSites(
                site_id=site_id,
                project_id=project_id,
                site_name=site_name,
                site_abbr=site_abbr,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
            db.session.add(site)
            db.session.flush()

        project_site = db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == project_id,
                VaProjectSites.site_id == site_id,
            )
        )
        if project_site is None:
            project_site = VaProjectSites(
                project_id=project_id,
                site_id=site_id,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
            db.session.add(project_site)
            db.session.flush()

        return project_site

    @classmethod
    def _ensure_form_fixture(
        cls,
        *,
        form_id,
        project_id,
        site_id,
        odk_form_id,
        odk_project_id,
        form_type,
        now=None,
    ):
        """Create or reuse a form fixture keyed by form_id."""
        now = now or datetime.now(timezone.utc)
        form = db.session.get(VaForms, form_id)
        if form is None:
            form = VaForms(
                form_id=form_id,
                project_id=project_id,
                site_id=site_id,
                odk_form_id=odk_form_id,
                odk_project_id=odk_project_id,
                form_type=form_type,
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
            db.session.add(form)
            db.session.flush()
        return form

    @classmethod
    def _get_or_make_user(cls, email, password):
        """Return an existing user by email, or create one if not found."""
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
        if user is None:
            user = cls._make_user(email, password)
        return user

    @classmethod
    def _make_user(cls, email, password):
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status=VaStatuses.active,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        return user

    # ------------------------------------------------------------------
    # Per-test isolation via savepoint rollback
    # ------------------------------------------------------------------

    def setUp(self):
        # Use a dedicated connection + outer transaction per test so route
        # handlers may call db.session.commit() without leaking data into
        # later tests in the same session-scoped schema.
        self._connection = db.engine.connect()
        self._outer_transaction = self._connection.begin()
        db.session.remove()
        db.session.configure(bind=self._connection)
        db.session.begin_nested()

        self._session = db.session()

        @sa.event.listens_for(self._session, "after_transaction_end")
        def _restart_savepoint(session, transaction):
            parent = getattr(transaction, "_parent", None)
            if transaction.nested and (parent is None or not parent.nested):
                session.begin_nested()
        self._restart_savepoint = _restart_savepoint

        # Flask 3.1 keeps g attached to the session-scoped app context used in
        # tests. Flask-Login caches the loaded user in g._login_user, so clear
        # it here to prevent auth leakage between requests in different tests.
        from flask import g

        if hasattr(g, "_login_user"):
            del g._login_user
        self.client = self.app.test_client()

    def tearDown(self):
        sa.event.remove(self._session, "after_transaction_end", self._restart_savepoint)
        db.session.remove()
        self._outer_transaction.rollback()
        self._connection.close()
        db.session.configure(bind=db.engine)
        db.session.expire_all()

    # ------------------------------------------------------------------
    # Shared helpers available to all test classes
    # ------------------------------------------------------------------

    def _login(self, user_id):
        """Inject a user session without going through the login route."""
        user_agent = self.client.environ_base.get("HTTP_USER_AGENT", "Werkzeug/Test")
        with self.app.test_request_context(
            "/",
            headers={"User-Agent": user_agent},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ):
            session_identifier = _create_identifier()
        with self.client.session_transaction() as sess:
            csrf_token = sess.get("csrf_token")
            sess.clear()
            sess["_user_id"] = user_id
            sess["_fresh"] = True
            sess["_id"] = session_identifier
            if csrf_token is not None:
                sess["csrf_token"] = csrf_token

    def _csrf_headers(self):
        """Return headers containing a valid CSRF token for the current session."""
        with self.client.session_transaction() as client_session:
            raw_token = client_session.get("csrf_token") or uuid.uuid4().hex
            client_session["csrf_token"] = raw_token
        secret_key = self.app.config.get("WTF_CSRF_SECRET_KEY") or self.app.secret_key
        serializer = URLSafeTimedSerializer(secret_key, salt="wtf-csrf-token")
        token = serializer.dumps(raw_token)
        return {"X-CSRFToken": token}
