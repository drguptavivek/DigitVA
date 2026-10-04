"""The Redis cache of resolved grants (digitva-5hmc).

Runs against the suite's real Redis (Flask-Caching's client) under a prefix
of its own, deleted afterwards; the cache is off for the rest of the suite.
"""
import uuid
from datetime import UTC, datetime
from unittest import mock

import flask
import redis
import sqlalchemy as sa

from app import db
from app.models import VaProjectSites, VaStatuses, VaUserAccessGrants
from app.services import organization_service as org
from app.services.authz import grant_cache, grants, invalidate, resolve_grants
from tests.authz.fixture import SP, TA, USERS, AuthzFixtureMixin, P, R
from tests.authz.test_grants import count_queries
from tests.base import BaseTestCase


def _grant_selects(statements):
    return [s for s in statements if "FROM va_user_access_grants" in s]


class GrantCacheTests(AuthzFixtureMixin, BaseTestCase):

    def setUp(self):
        super().setUp()
        self.prefix = f"digitva_authz_test_{uuid.uuid4().hex}:"
        for key, value in (
            ("AUTHZ_GRANT_CACHE_ENABLED", True),
            ("AUTHZ_GRANT_CACHE_PREFIX", self.prefix),
        ):
            previous = self.app.config.get(key)
            self.app.config[key] = value
            self.addCleanup(self.app.config.__setitem__, key, previous)
        self.redis = grant_cache._client()
        self.assertIsNotNone(self.redis)
        self.addCleanup(self._drop_keys)

    def _drop_keys(self):
        keys = list(self.redis.scan_iter(self.prefix + "*"))
        if keys:
            self.redis.delete(*keys)

    def _resolve(self, user):
        """Resolve in a request of its own, as a page would."""
        with flask.current_app.test_request_context("/"):
            return resolve_grants(user)

    def _key(self, user):
        return grant_cache.entry_key(self.redis, self.prefix, user.user_id)

    def _fresh(self, user):
        return grants._resolve(user.user_id)

    def test_an_evicted_version_never_revives_an_older_entry(self):
        user = self.users["coder_ta"]
        uv_key = f"{self.prefix}uv:{user.user_id}"
        self.assertTrue(self._resolve(user).grants)
        old_entry = self._key(user)
        old_version = self.redis.get(uv_key)
        # Revoke, then lose the version as allkeys-lru eviction would.
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id))
        grant.grant_status = VaStatuses.deactive
        db.session.commit()
        self.redis.delete(uv_key)
        self.assertIsNotNone(self.redis.get(old_entry))  # the stale entry is still there
        self.assertFalse([g for g in self._resolve(user).grants if not g.virtual])
        self.assertNotEqual(self.redis.get(uv_key), old_version)

    def test_invalidate_reads_the_database_for_the_rest_of_the_request(self):
        user = self.users["coder_ta"]
        self.assertTrue(self._resolve(user).grants)
        with flask.current_app.test_request_context("/"):
            db.session.execute(
                sa.update(VaUserAccessGrants)
                .where(VaUserAccessGrants.user_id == user.user_id)
                .values(grant_status=VaStatuses.deactive)
            )
            invalidate(user.user_id)
            self.assertFalse([g for g in resolve_grants(user).grants if not g.virtual])

    # -- hits ----------------------------------------------------------------

    def test_a_hit_answers_without_the_grant_query(self):
        user = self.users["coder_c1"]
        with count_queries() as statements:
            first = self._resolve(user)
        self.assertTrue(_grant_selects(statements))  # the miss read the DB
        with count_queries() as statements:
            second = self._resolve(user)
        self.assertEqual(_grant_selects(statements), [])
        self.assertEqual(second, first)
        self.assertEqual(second, self._fresh(user))

    def test_every_fixture_user_round_trips(self):
        for key in USERS:
            user = self.users[key]
            resolved = self._fresh(user)
            self.assertEqual(grant_cache.decode(grant_cache.encode(resolved), user.user_id),
                             resolved, key)

    def test_the_entry_expires_within_five_minutes(self):
        user = self.users["dm_ta"]
        self._resolve(user)
        ttl = self.redis.ttl(self._key(user))
        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, 300)

    def test_every_key_it_writes_has_an_expiry(self):
        # Redis runs volatile-lru: a key without a TTL is never evicted.
        user = self.users["dm_ta"]
        self._resolve(user)  # seeds gv and uv, writes the entry
        self._assert_all_keys_expire(3)
        # Bump both versions the way a grant write does, then re-check.
        with flask.current_app.test_request_context("/"):
            grants.invalidate(user.user_id)
            grants.invalidate_all()
            db.session.commit()
        self._assert_all_keys_expire(3)

    def _assert_all_keys_expire(self, expected):
        keys = list(self.redis.scan_iter(self.prefix + "*"))
        self.assertEqual(len(keys), expected)  # gv, uv, entry: subject present
        for key in keys:
            self.assertGreater(self.redis.ttl(key), 0, key)

    def test_the_entry_holds_no_personal_data(self):
        user = self.users["mixed"]
        self.assertTrue(user.email and user.name)
        user.phone = "+919999912345"
        db.session.flush()
        self._resolve(user)
        raw = self.redis.get(self._key(user)).decode()
        self.assertIn(R.coder.value, raw)  # presence first
        self.assertIn(SP, raw)
        for value in (user.email, user.name, user.phone):
            self.assertNotIn(value, raw)

    # -- invalidation ----------------------------------------------------------

    def test_a_grant_write_bumps_that_user(self):
        user = self.users["nobody"]
        self.assertFalse(self._resolve(user).grants)
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=R.coder, scope_type=P, project_id=TA,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self.assertEqual([g.role for g in self._resolve(user).grants if not g.virtual], [R.coder])

    def test_a_core_grant_update_bumps_through_invalidate(self):
        user = self.users["coder_ta"]
        self.assertTrue(self._resolve(user).grants)
        db.session.execute(
            sa.update(VaUserAccessGrants)
            .where(VaUserAccessGrants.user_id == user.user_id)
            .values(grant_status=VaStatuses.deactive)
        )
        self.assertTrue(self._resolve(user).grants)  # not bumped yet: stale until told
        invalidate(user.user_id)
        db.session.commit()
        self.assertFalse(self._resolve(user).grants)

    def test_another_user_stays_cached_after_a_grant_write(self):
        other = self.users["dm_ta"]
        self._resolve(other)
        key = self._key(other)
        db.session.add(VaUserAccessGrants(
            user_id=self.users["nobody"].user_id, role=R.coder, scope_type=P,
            project_id=TA, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self.assertEqual(self._key(other), key)

    def test_a_unit_deactivation_bumps_everyone(self):
        user = self.users["coder_c1"]
        self.assertEqual({g.org_unit_id for g in self._resolve(user).grants if not g.virtual},
                         {self.units["C1"].org_unit_id})
        org.set_unit_active(TA, self.units["D1"].org_unit_id, False)
        db.session.commit()
        self.assertFalse([g for g in self._resolve(user).grants if not g.virtual])

    def test_a_project_site_deactivation_bumps_everyone(self):
        user = self.users["coder_sp1"]
        self.assertTrue(self._resolve(user).grants)
        pair = db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == SP, VaProjectSites.site_id == "AZS1",
        ))
        pair.project_site_status = VaStatuses.deactive
        pair.project_site_updated_at = datetime.now(UTC)
        db.session.commit()
        self.assertFalse(self._resolve(user).grants)

    def test_a_status_change_bumps_that_user(self):
        user = self.users["dm_ta"]
        self._resolve(user)
        key = self._key(user)
        user.user_status = VaStatuses.deactive
        db.session.commit()
        self.assertNotEqual(self._key(user), key)

    def test_a_rolled_back_change_still_reads_the_database(self):
        """No commit, no bump: the cached answer is the committed one."""
        user = self.users["coder_ta"]
        first = self._resolve(user)
        db.session.execute(
            sa.update(VaUserAccessGrants)
            .where(VaUserAccessGrants.user_id == user.user_id)
            .values(grant_status=VaStatuses.deactive)
        )
        db.session.rollback()
        self.assertEqual(self._resolve(user), first)

    # -- failure ---------------------------------------------------------------

    def test_redis_down_falls_back_to_the_database(self):
        user = self.users["reviewer_c1"]
        broken = mock.Mock()
        broken.mget.side_effect = redis.ConnectionError("down")
        with mock.patch.object(grant_cache, "_client", return_value=broken):
            with count_queries() as statements:
                resolved = self._resolve(user)
        self.assertTrue(_grant_selects(statements))
        self.assertEqual(resolved, self._fresh(user))
        broken.set.assert_not_called()

    def test_redis_down_never_serves_a_revoked_grant(self):
        user = self.users["coder_ta"]
        self.assertTrue(self._resolve(user).grants)  # cached with the grant
        db.session.execute(
            sa.update(VaUserAccessGrants)
            .where(VaUserAccessGrants.user_id == user.user_id)
            .values(grant_status=VaStatuses.deactive)
        )
        broken = mock.Mock()
        broken.mget.side_effect = redis.ConnectionError("down")
        with mock.patch.object(grant_cache, "_client", return_value=broken):
            self.assertFalse(self._resolve(user).grants)

    def test_an_unparsable_entry_is_discarded(self):
        user = self.users["dm_c1"]
        expected = self._fresh(user)
        for garbage in (b"not json", b'{"format": 1}', b"[]",
                        grant_cache.encode(expected).replace('"data_manager"', '"nope"')):
            self.redis.set(self._key(user), garbage)
            with self.assertLogs(grant_cache.log, level="WARNING"):
                self.assertEqual(self._resolve(user), expected)
            stored = self.redis.get(self._key(user))
            self.assertEqual(grant_cache.decode(stored, user.user_id), expected)

    def test_an_entry_for_another_user_is_discarded(self):
        user, other = self.users["dm_c1"], self.users["dm_ta"]
        self.redis.set(self._key(user), grant_cache.encode(self._fresh(other)))
        with self.assertLogs(grant_cache.log, level="WARNING"):
            self.assertEqual(self._resolve(user), self._fresh(user))

    def test_off_means_no_redis_at_all(self):
        self.app.config["AUTHZ_GRANT_CACHE_ENABLED"] = False
        self.assertIsNone(grant_cache._client())
        user = self.users["dm_ta"]
        self._resolve(user)
        self.app.config["AUTHZ_GRANT_CACHE_ENABLED"] = True
        self.assertIsNone(self.redis.get(self._key(user)))
