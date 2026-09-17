"""
Base test case for DigitVA tests.

Uses TestConfig which points to a separate `minerva_test` database so that
the development database is never touched during test runs.

Schema lifecycle (session-scoped, managed by conftest.py):
  - conftest.pytest_sessionstart: creates schema ONCE for the entire session
  - conftest.pytest_sessionfinish: drops schema ONCE after all tests

Per-class setup (BaseTestCase.setUpClass):
  - Re-uses the session schema and app; no drop_all/create_all per class.
  - Seeds the base fixtures for this class inside the class transaction.

Isolation (nested transactions — nothing is ever committed to the database):
  - setUpClass: open one connection, BEGIN a transaction on it, and bind the
    scoped db.session to that connection with
    join_transaction_mode="create_savepoint".  Class fixtures are seeded (and
    "committed") inside it.
  - setUp: connection.begin_nested() — a SAVEPOINT one level inside the class
    transaction.
  - tearDown: end the session transaction and ROLLBACK to that savepoint, so
    class fixtures survive for the rest of the class.
  - tearDownClass: ROLLBACK the class transaction and close the connection, so
    no class leaves rows behind for another class.

  Because the session joins through a savepoint of its own, a
  db.session.commit() inside a test — from test code or from a route — only
  releases the session's savepoint.  Nothing reaches the database.
  No manual DELETE queries are needed in test setUp/tearDown methods.

  This works because in our pushed-app-context test environment, Flask test
  client requests share the same scoped db.session as the test body, so the
  transactions cover both direct ORM writes and data created through HTTP
  routes.  Code that bypasses the session and goes straight to the engine
  (db.engine.connect()/begin(), e.g. the ODK connection guard) runs on another
  connection and cannot see this data: such classes set
  isolate_in_transaction = False and clean up after themselves.

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
from flask_sqlalchemy.session import Session as FlaskSQLAlchemySession
from itsdangerous import URLSafeTimedSerializer
import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
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


class ExternalTransactionSession(FlaskSQLAlchemySession):
    """
    Session class that honours an explicitly bound Connection.

    Flask-SQLAlchemy's own ``Session.get_bind()`` ignores ``self.bind`` and always
    returns ``db.engines[None]``, which defeats the standard SQLAlchemy "join a
    session into an external transaction" recipe that per-test isolation depends
    on.  This subclass returns the bound connection when one has been configured
    (``db.session.configure(bind=connection)``) and otherwise falls back to
    Flask-SQLAlchemy's bind-key routing.
    """

    def get_bind(self, mapper=None, clause=None, bind=None, **kwargs):
        if bind is None and self.bind is not None:
            return self.bind
        return super().get_bind(mapper=mapper, clause=clause, bind=bind, **kwargs)


def install_external_transaction_session():
    """
    Swap the scoped session factory over to ExternalTransactionSession.

    Called once from conftest.pytest_sessionstart, before any session is used,
    so that BaseTestCase.setUp can rebind db.session to a per-test connection.
    """
    db.session.remove()
    # sessionmaker.configure() cannot change class_ (it would be forwarded to
    # Session.__init__ as a keyword), so set it on the factory directly.
    db.session.session_factory.class_ = ExternalTransactionSession


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

    # Set to False only for classes whose code under test opens its own
    # connection through db.engine (e.g. the ODK connection guard, whose state
    # is deliberately kept outside the request transaction).  A second
    # connection cannot see rows the class transaction has not committed, so
    # such classes write for real and MUST delete what they created in their
    # own tearDownClass.
    isolate_in_transaction = True

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

        # Discard any transaction left dirty by a previous class.
        db.session.rollback()

        # Open the class-level connection and transaction, and bind the scoped
        # session to it.  Everything this class writes — class fixtures and test
        # data alike — lives inside this transaction and is rolled back in
        # tearDownClass, so no class can leak committed rows into another.
        cls._class_connection = None
        cls._class_transaction = None
        if cls.isolate_in_transaction:
            cls._class_connection = db.engine.connect()
            cls._class_transaction = cls._class_connection.begin()
            session = db.session()
            session.bind = cls._class_connection
            session.join_transaction_mode = "create_savepoint"
            session.expire_all()

        # _seed_base_fixtures is idempotent: safe to call once per class.
        # Base fixtures (BASE_PROJECT_ID, BASE_SITE_ID, 3 users) are re-seeded by
        # every class because the previous class's copy was rolled back.
        # Subclass-specific fixtures use unique IDs so they never conflict.
        cls._seed_base_fixtures()

    @classmethod
    def tearDownClass(cls):
        # Roll the class transaction back: class fixtures exist only for the
        # lifetime of the class that seeded them.  The schema itself is dropped
        # once at session end in conftest.pytest_sessionfinish.
        session = db.session()
        session.rollback()
        session.expunge_all()
        if cls._class_transaction is None:
            return
        session.bind = None
        try:
            cls._class_transaction.rollback()
        finally:
            cls._class_connection.close()

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
    def _ensure_base_research_project_and_site(cls):
        """
        Get-or-create the legacy `va_research_projects` / `va_sites` rows for
        cls.BASE_PROJECT_ID / cls.BASE_SITE_ID and return them as a tuple.

        Opt-in — deliberately NOT called from _seed_base_fixtures, because many
        test classes never touch the legacy tables. Class-level fixtures that
        need those rows must go through this helper: an unconditional insert
        raises UniqueViolation as soon as another class in the same session has
        already committed the same ids, which leaves the scoped session in
        PendingRollback and breaks every later class.

        Rows are flushed, not committed — the calling setUpClass owns the commit.
        """
        now = datetime.now(timezone.utc)

        research_project = db.session.get(VaResearchProjects, cls.BASE_PROJECT_ID)
        if research_project is None:
            research_project = VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="Base Research Project",
                project_nickname="BaseResearch",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
            db.session.add(research_project)
            db.session.flush()

        site = db.session.get(VaSites, cls.BASE_SITE_ID)
        if site is None:
            site = VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Base Test Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
            db.session.add(site)
            db.session.flush()

        return research_project, site

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
    # Per-test isolation via an external transaction
    # ------------------------------------------------------------------

    def setUp(self):
        session = db.session()
        session.rollback()  # end any session transaction left over from setUpClass
        # SAVEPOINT on the class connection, one level inside the class
        # transaction.  The session joins it with a savepoint of its own, so a
        # commit() during the test — from test code or from a route — only
        # releases the session's savepoint and never escapes this one.
        self._test_savepoint = (
            self._class_connection.begin_nested()
            if self._class_connection is not None
            else None
        )
        # Flask 3.1 keeps g attached to the session-scoped app context used in
        # tests. Flask-Login caches the loaded user in g._login_user, so clear
        # it here to prevent auth leakage between requests in different tests.
        from flask import g

        if hasattr(g, "_login_user"):
            del g._login_user
        self.client = self.app.test_client()

    def tearDown(self):
        # End the session transaction and roll back to the per-test savepoint.
        # Class fixtures seeded in setUpClass sit outside this savepoint, so
        # they survive for the rest of the class as intended.
        session = db.session()
        session.rollback()
        session.expire_all()
        if self._test_savepoint is not None and self._test_savepoint.is_active:
            self._test_savepoint.rollback()

    # ------------------------------------------------------------------
    # Shared helpers available to all test classes
    # ------------------------------------------------------------------

    def _login(self, user_id):
        """Inject a user session without going through the login route.

        Flask-Login caches the loaded user on ``g``, and the app context that
        holds ``g`` lives for the whole pytest session, so the cache outlives a
        request.  Drop it here or a second _login() inside one test would be a
        silent no-op and keep serving the previous user.
        """
        from flask import g

        if hasattr(g, "_login_user"):
            del g._login_user

        user_agent = self.client.environ_base.get("HTTP_USER_AGENT", "Werkzeug/Test")
        with self.app.test_request_context(
            "/",
            headers={"User-Agent": user_agent},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ):
            session_identifier = _create_identifier()
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["_user_id"] = user_id
            sess["_fresh"] = True
            sess["_id"] = session_identifier

    def _csrf_headers(self):
        """Return headers containing a valid CSRF token for the current session."""
        with self.client.session_transaction() as client_session:
            raw_token = client_session.get("csrf_token") or uuid.uuid4().hex
            client_session["csrf_token"] = raw_token
        secret_key = self.app.config.get("WTF_CSRF_SECRET_KEY") or self.app.secret_key
        serializer = URLSafeTimedSerializer(secret_key, salt="wtf-csrf-token")
        token = serializer.dumps(raw_token)
        return {"X-CSRFToken": token}
