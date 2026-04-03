"""
Base test case for DigitVA tests.

Uses TestConfig which points to a separate `minerva_test` database so that
the development database is never touched during test runs.

Schema lifecycle (per test class):
  - setUpClass: create app context, create all tables, seed standard fixtures
  - tearDownClass: drop all tables, pop context

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
super().setUpClass() first).

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
from sqlalchemy.exc import ProgrammingError

from app import create_app, db
from app.models import (
    VaAllocation,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsernotesFor,
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
    def _drop_test_materialized_views(cls):
        for mv in (
            "va_submission_cod_detail_mv",
            "va_submission_analytics_demographics_mv",
            "va_submission_analytics_core_mv",
            "va_submission_analytics_mv",
        ):
            db.session.execute(
                sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE")
            )
        db.session.commit()

    @classmethod
    def _ensure_named_enums(cls):
        enum_defs = {
            "status_enum": [member.value for member in VaStatuses],
            "allocation_enum": [member.value for member in VaAllocation],
            "usernote_enum": [member.value for member in VaUsernotesFor],
            "access_role_enum": [member.value for member in VaAccessRoles],
            "access_scope_enum": [member.value for member in VaAccessScopeTypes],
        }

        for table in db.Model.metadata.tables.values():
            for column in table.columns:
                col_type = getattr(column, "type", None)
                if isinstance(col_type, sa.Enum) and col_type.name in enum_defs:
                    col_type.create_type = False

        for enum_name, values in enum_defs.items():
            quoted_values = ", ".join(f"'{value}'" for value in values)
            db.session.execute(
                sa.text(
                    f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_type t
                            JOIN pg_namespace n ON n.oid = t.typnamespace
                            WHERE t.typname = '{enum_name}'
                              AND n.nspname = current_schema()
                        ) THEN
                            CREATE TYPE {enum_name} AS ENUM ({quoted_values});
                        END IF;
                    END
                    $$;
                    """
                )
            )
        db.session.commit()

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(cls.config_class)
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        cls._drop_test_materialized_views()
        try:
            db.drop_all()
        except ProgrammingError:
            db.session.rollback()
        cls._ensure_named_enums()
        db.create_all()
        cls._seed_base_fixtures()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        cls._drop_test_materialized_views()
        try:
            db.drop_all()
        except ProgrammingError:
            db.session.rollback()
        db.engine.dispose()   # close all pool connections so next class can acquire DDL locks
        cls.ctx.pop()

    @classmethod
    def _seed_base_fixtures(cls):
        """
        Create the minimal reference data that every test class may rely on:
        one project, one site, one project-site mapping, and three users
        (admin, project_pi, coder).
        """
        now = datetime.now(timezone.utc)

        project = VaProjectMaster(
            project_id=cls.BASE_PROJECT_ID,
            project_code=cls.BASE_PROJECT_ID,
            project_name="Base Test Project",
            project_nickname="BaseTest",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
        )
        site = VaSiteMaster(
            site_id=cls.BASE_SITE_ID,
            site_name="Base Test Site",
            site_abbr=cls.BASE_SITE_ID,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        )
        db.session.add_all([project, site])
        db.session.flush()

        project_site = VaProjectSites(
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            project_site_status=VaStatuses.active,
            project_site_registered_at=now,
            project_site_updated_at=now,
        )
        db.session.add(project_site)
        db.session.flush()

        cls.base_admin_user = cls._make_user(
            "base.admin@test.local", "BaseAdmin123"
        )
        cls.base_project_pi_user = cls._make_user(
            "base.project_pi@test.local", "BaseProjectPi123"
        )
        cls.base_coder_user = cls._make_user(
            "base.coder@test.local", "BaseCoder123"
        )

        db.session.add_all([
            VaUserAccessGrants(
                user_id=cls.base_admin_user.user_id,
                role=VaAccessRoles.admin,
                scope_type=VaAccessScopeTypes.global_scope,
                notes="base admin grant",
                grant_status=VaStatuses.active,
            ),
            VaUserAccessGrants(
                user_id=cls.base_project_pi_user.user_id,
                role=VaAccessRoles.project_pi,
                scope_type=VaAccessScopeTypes.project,
                project_id=cls.BASE_PROJECT_ID,
                notes="base project pi grant",
                grant_status=VaStatuses.active,
            ),
            VaUserAccessGrants(
                user_id=cls.base_coder_user.user_id,
                role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site.project_site_id,
                notes="base coder grant",
                grant_status=VaStatuses.active,
            ),
        ])
        db.session.commit()

        cls.base_admin_id = str(cls.base_admin_user.user_id)
        cls.base_project_pi_id = str(cls.base_project_pi_user.user_id)
        cls.base_coder_id = str(cls.base_coder_user.user_id)

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
