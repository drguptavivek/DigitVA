"""Data-manager dashboard caches (digitva-r8nh.4).

Three cache-aside helpers serve dashboard data: ``analytics._cached``,
``data_management._cached`` and ``dm_kpi_scope.cached_kpi``. Policy
(docs/policy/data-manager-workflow.md, "Dashboard caches"): a user's access
change shows on the next request, and a data-manager action invalidates the
dashboard data it affects, not every user's cache.
"""
import uuid
from unittest import mock

from flask_login import login_user

from app import cache, db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
)
from tests.base import BaseTestCase
from tests.test_unit_scoped_dm_tester import UnitScopeFixture

R = VaAccessRoles
ANALYTICS_KPI = "/api/v1/analytics/kpi"
DM_KPI = "/api/v1/data-management/kpi"


class DmDashboardCacheTests(UnitScopeFixture, BaseTestCase):
    def setUp(self):
        super().setUp()
        # The grant cache (Redis, unique prefix) supplies the authz versions.
        for name, value in (
            ("AUTHZ_GRANT_CACHE_ENABLED", True),
            ("AUTHZ_GRANT_CACHE_PREFIX", f"digitva_authz_test_{uuid.uuid4().hex}:"),
        ):
            previous = self.app.config.get(name)
            self.app.config[name] = value
            self.addCleanup(self.app.config.__setitem__, name, previous)
        from app.services.authz import grant_cache

        client = grant_cache._client()
        self.assertIsNotNone(client)
        prefix = self.app.config["AUTHZ_GRANT_CACHE_PREFIX"]
        self.addCleanup(lambda: [client.delete(k) for k in client.scan_iter(prefix + "*")])
        client.set(prefix + "gv", "seed")
        self._cache_keys = []
        self.addCleanup(lambda: [cache.delete(k) for k in self._cache_keys])

    def _dm(self, key, unit):
        return self._user_with(f"r8nh4.{key}@test.local", R.data_manager, unit)

    def _grant(self, user, unit):
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=R.data_manager,
            scope_type=VaAccessScopeTypes.org_unit, org_unit_id=unit.org_unit_id,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def _get(self, user, url):
        self._login(str(user.user_id))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def _fake_kpi(self):
        """Stands in for the MV query: reports the scope it was asked for."""
        calls = []

        def fake(*args, **kwargs):
            calls.append(1)
            from flask_login import current_user

            from app.services.data_management_service import dm_grant_scope

            return {"units": sorted(str(u) for u in dm_grant_scope(current_user).unit_grant_ids)}

        return fake, calls

    # -- (a) a grant change refreshes the dashboards -----------------------

    def test_analytics_kpi_refreshes_after_the_users_grant_changes(self):
        _, district, chc, phc_a, phc_b = self._tree()
        dm = self._dm("grant", phc_a)
        fake, calls = self._fake_kpi()
        with mock.patch("app.routes.api.analytics.get_dm_kpi_from_mv", fake):
            first = self._get(dm, ANALYTICS_KPI)
            self._grant(dm, phc_b)
            second = self._get(dm, ANALYTICS_KPI)
        self.assertEqual(len(first["units"]), 1)
        self.assertEqual(len(second["units"]), 2, "stale: served the pre-grant scope")
        self.assertEqual(len(calls), 2)

    def test_data_management_kpi_refreshes_after_the_users_grant_changes(self):
        _, district, chc, phc_a, phc_b = self._tree()
        dm = self._dm("grant.dm", phc_a)
        fake, calls = self._fake_kpi()
        with mock.patch("app.routes.api.data_management.get_dm_kpi_from_mv", fake):
            first = self._get(dm, DM_KPI)
            self._grant(dm, phc_b)
            second = self._get(dm, DM_KPI)
        self.assertEqual(len(first["units"]), 1)
        self.assertEqual(len(second["units"]), 2)

    # -- a repeat request is served from the cache -------------------------

    def test_a_repeat_request_hits_the_cache(self):
        _, _, _, phc_a, _ = self._tree()
        dm = self._dm("repeat", phc_a)
        fake, calls = self._fake_kpi()
        with mock.patch("app.routes.api.analytics.get_dm_kpi_from_mv", fake):
            self.assertEqual(self._get(dm, ANALYTICS_KPI), self._get(dm, ANALYTICS_KPI))
        self.assertEqual(len(calls), 1)
        fake, calls = self._fake_kpi()
        with mock.patch("app.routes.api.data_management.get_dm_kpi_from_mv", fake):
            self.assertEqual(self._get(dm, DM_KPI), self._get(dm, DM_KPI))
        self.assertEqual(len(calls), 1)

    def test_cached_kpi_hits_on_repeat(self):
        from app.routes.api.dm_kpi import dm_kpi_scope

        _, _, _, phc_a, _ = self._tree()
        dm = self._dm("kpi.repeat", phc_a)
        calls = []
        with self.app.test_request_context("/"):
            login_user(dm)
            for _ in range(2):
                dm_kpi_scope.cached_kpi("r8nh4", lambda: calls.append(1) or {"n": len(calls)})
            self._cache_keys.append(dm_kpi_scope._cache_key("r8nh4"))
        self.assertEqual(len(calls), 1)

    # -- (b) a data-manager action's cache invalidation --------------------

    def _run_dm_action(self):
        from app.routes.api import data_management

        with mock.patch.object(data_management, "refresh_submission_analytics_mv"):
            data_management._refresh_dm_dashboard_analytics()

    def test_dm_action_makes_every_dm_dashboard_fresh(self):
        from app.routes.api.dm_kpi import dm_kpi_scope

        _, _, _, phc_a, phc_b = self._tree()
        dm_a, dm_b = self._dm("act.a", phc_a), self._dm("act.b", phc_b)
        fake, calls = self._fake_kpi()
        with mock.patch("app.routes.api.analytics.get_dm_kpi_from_mv", fake), \
                mock.patch("app.routes.api.data_management.get_dm_kpi_from_mv", fake):
            for user in (dm_a, dm_b):
                self._get(user, ANALYTICS_KPI)
                self._get(user, DM_KPI)
            self.assertEqual(len(calls), 4)
            self._run_dm_action()
            for user in (dm_a, dm_b):
                self._get(user, ANALYTICS_KPI)
                self._get(user, DM_KPI)
            self.assertEqual(len(calls), 8, "every user's dashboards recompute after the action")
        kpi_calls = []
        with self.app.test_request_context("/"):
            login_user(dm_a)
            dm_kpi_scope.cached_kpi("r8nh4", lambda: kpi_calls.append(1) or {})
            self._run_dm_action()
            dm_kpi_scope.cached_kpi("r8nh4", lambda: kpi_calls.append(1) or {})
            self._cache_keys.append(dm_kpi_scope._cache_key("r8nh4"))
        self.assertEqual(len(kpi_calls), 2)

    def test_dm_action_leaves_unrelated_cache_entries(self):
        key = f"r8nh4:unrelated:{uuid.uuid4().hex}"
        self._cache_keys.append(key)
        cache.set(key, "kept", timeout=60)
        self.assertEqual(cache.get(key), "kept")  # present before the action
        self._run_dm_action()
        self.assertEqual(cache.get(key), "kept")
