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

Per-test isolation (savepoint rollback):
  - setUp: open a PostgreSQL SAVEPOINT via db.session.begin_nested()
  - tearDown: ROLLBACK TO SAVEPOINT — removes all test data automatically
  No manual DELETE queries are needed in test setUp/tearDown methods.

  This works because in our pushed-app-context test environment, Flask test
  client requests share the same scoped db.session as the test body, so the
  savepoint covers both direct ORM writes and data created through HTTP routes.

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

from itsdangerous import URLSafeTimedSerializer
import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
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
        now = datetime.now(timezone.utc)

        project = db.session.get(VaProjectMaster, cls.BASE_PROJECT_ID)
        if project is None:
            project = VaProjectMaster(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="Base Test Project",
                project_nickname="BaseTest",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
            db.session.add(project)
            db.session.flush()

        site = db.session.get(VaSiteMaster, cls.BASE_SITE_ID)
        if site is None:
            site = VaSiteMaster(
                site_id=cls.BASE_SITE_ID,
                site_name="Base Test Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
            db.session.add(site)
            db.session.flush()

        project_site = db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == cls.BASE_PROJECT_ID,
                VaProjectSites.site_id == cls.BASE_SITE_ID,
            )
        )
        if project_site is None:
            project_site = VaProjectSites(
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
            db.session.add(project_site)
            db.session.flush()

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
        # Begin a nested transaction (SAVEPOINT).  Any commit() inside this
        # test — whether from test code or from an HTTP route — only releases
        # the savepoint back to the outer transaction; nothing is permanently
        # written to the DB until that outer transaction commits (which it
        # never does in tests).  tearDown rolls back the outer transaction.
        db.session.begin_nested()
        self.client = self.app.test_client()

    def tearDown(self):
        # Roll back the outer transaction.  This undoes all writes made during
        # this test regardless of whether they came from direct ORM calls or
        # from HTTP routes that called db.session.commit() (which only released
        # the savepoint, not the outer transaction).
        db.session.rollback()
        db.session.expire_all()

    # ------------------------------------------------------------------
    # Shared helpers available to all test classes
    # ------------------------------------------------------------------

    def _login(self, user_id):
        """Inject a user session without going through the login route."""
        with self.client.session_transaction() as sess:
            sess["_user_id"] = user_id
            sess["_fresh"] = True

    def _csrf_headers(self):
        """Return headers containing a valid CSRF token for the current session."""
        with self.client.session_transaction() as client_session:
            raw_token = client_session.get("csrf_token") or uuid.uuid4().hex
            client_session["csrf_token"] = raw_token
        secret_key = self.app.config.get("WTF_CSRF_SECRET_KEY") or self.app.secret_key
        serializer = URLSafeTimedSerializer(secret_key, salt="wtf-csrf-token")
        token = serializer.dumps(raw_token)
        return {"X-CSRFToken": token}
