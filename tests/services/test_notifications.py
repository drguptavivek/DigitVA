"""Polled per-user notifications (digitva-hdrv): the service, the Redis key,
GET /api/v1/me/notifications and the purge. Emitters are tested beside the
code that fires them (send-back, intake, case reopen)."""
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import MapUserNotification
from app.services import notification_service as ns
from tests.authz.test_grants import count_queries
from tests.base import BaseTestCase

URL = "/api/v1/me/notifications"
PROJECT = "NTF01"


class NotificationTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.prefix = f"digitva_msg_test_{uuid.uuid4().hex}:"
        for key, value in (("NOTIFICATION_CACHE_ENABLED", True), ("NOTIFICATION_CACHE_PREFIX", self.prefix)):
            previous = self.app.config.get(key)
            self.app.config[key] = value
            self.addCleanup(self.app.config.__setitem__, key, previous)
        self.redis = ns._client()
        self.assertIsNotNone(self.redis)
        self.addCleanup(self._drop_keys)
        self.me, self.other = self.base_coder_user.user_id, self.base_project_pi_user.user_id

    def _drop_keys(self):
        keys = list(self.redis.scan_iter(self.prefix + "*"))
        if keys:
            self.redis.delete(*keys)

    def _cached(self, user_id):
        value = self.redis.get(self.prefix + str(user_id))
        return None if value is None else int(value)

    def _notify(self, users, kind="revision_requested", **kw):
        count = ns.notify(users, kind, project_id=PROJECT, **kw)
        db.session.commit()
        return count

    def _ids(self, user_id):
        return list(db.session.scalars(
            sa.select(MapUserNotification.id).where(MapUserNotification.user_id == user_id).order_by(MapUserNotification.id)))

    # -- write side ---------------------------------------------------------

    def test_commit_sets_the_key_to_the_newest_id_with_a_ttl(self):
        self._notify([self.me])
        self._notify([self.me, self.other])
        newest = self._ids(self.me)[-1]
        self.assertEqual(self._cached(self.me), newest)
        self.assertEqual(self._cached(self.other), self._ids(self.other)[-1])
        self.assertTrue(0 < self.redis.ttl(self.prefix + str(self.me)) <= ns.CACHE_TTL_SECONDS)

    def test_a_lower_id_never_moves_the_key_backwards(self):
        self._notify([self.me])
        newest = self._ids(self.me)[-1]
        pipe = self.redis.pipeline()
        pipe.eval(ns._RAISE, 1, self.prefix + str(self.me), newest - 1, ns.CACHE_TTL_SECONDS)
        pipe.execute()
        self.assertEqual(self._cached(self.me), newest)

    def test_a_rolled_back_event_leaves_no_row_and_no_key(self):
        before = self._ids(self.me)
        ns.notify([self.me], "revision_requested", project_id=PROJECT)
        db.session.rollback()
        self.assertEqual(self._ids(self.me), before)
        self.assertIsNone(self._cached(self.me))
        # The pending ids went with the transaction: a later commit publishes nothing stale.
        db.session.commit()
        self.assertIsNone(self._cached(self.me))

    def test_notify_is_one_statement_for_many_recipients_and_dedupes(self):
        users = [self.me, self.other, self.me, None]
        with count_queries() as statements:
            count = ns.notify(users, "case_reopened", project_id=PROJECT, death_id=uuid.uuid4())
        db.session.rollback()
        self.assertEqual(count, 2)
        self.assertEqual(len([s for s in statements if "INSERT INTO map_user_notifications" in s]), 1)
        self.assertEqual(len(statements), 1)

    def test_fan_out_is_capped_and_draft_ids_can_differ_per_recipient(self):
        mine, theirs = uuid.uuid4(), uuid.uuid4()
        self._notify([self.me, self.other], "case_submitted_by_other", draft_id={self.me: mine, self.other: theirs})
        rows = {r.user_id: r.draft_id for r in db.session.scalars(
            sa.select(MapUserNotification).where(MapUserNotification.id.in_(self._ids(self.me) + self._ids(self.other))))}
        self.assertEqual(rows, {self.me: mine, self.other: theirs})
        self.assertEqual(ns.notify([], "x", project_id=PROJECT), 0)

    def test_redis_errors_are_swallowed_and_the_row_stays(self):
        class Broken:
            def pipeline(self, **_):
                raise ConnectionError("down")

        original = ns._client
        ns._client = lambda: Broken()
        self.addCleanup(setattr, ns, "_client", original)
        self._notify([self.me])
        self.assertEqual(len(self._ids(self.me)), 1)

    # -- read side ----------------------------------------------------------

    def test_a_cache_hit_with_nothing_newer_runs_zero_queries(self):
        self._notify([self.me])
        newest = self._ids(self.me)[-1]
        with count_queries() as statements:
            reply = ns.poll(self.me, newest)
        self.assertEqual(statements, [])
        self.assertEqual(reply, {"notifications": [], "next_cursor": newest})

    def test_a_user_with_no_rows_costs_two_index_reads_then_none(self):
        with count_queries() as statements:
            first = ns.poll(self.other, 0)
        self.assertEqual(len(statements), 2)  # the page, then the real newest id
        self.assertEqual(first, {"notifications": [], "next_cursor": 0})
        self.assertEqual(self._cached(self.other), 0)
        with count_queries() as statements:
            ns.poll(self.other, 0)
        self.assertEqual(statements, [])

    def test_a_cursor_above_the_real_ids_is_rewound_not_stuck(self):
        self._notify([self.me])
        newest = self._ids(self.me)[-1]
        ns._client().delete(ns._key(self.me))  # start from a cache miss
        for _ in range(2):  # cache miss, then cache hit
            reply = ns.poll(self.me, newest + 1000)
            self.assertEqual(reply, {"notifications": [], "next_cursor": newest})
        self._notify([self.me])
        later = ns.poll(self.me, reply["next_cursor"])
        self.assertEqual([n["id"] for n in later["notifications"]], [self._ids(self.me)[-1]])

    def test_a_newer_row_than_the_cursor_is_one_indexed_query(self):
        self._notify([self.me])
        first = self._ids(self.me)[-1]
        self._notify([self.me])
        with count_queries() as statements:
            reply = ns.poll(self.me, first)
        # The SAVEPOINT is the test harness reopening its joined transaction.
        self.assertEqual([s for s in statements if not s.startswith("SAVEPOINT")][0][:6], "SELECT")
        self.assertEqual(len([s for s in statements if not s.startswith("SAVEPOINT")]), 1, statements)
        self.assertEqual([n["id"] for n in reply["notifications"]], self._ids(self.me)[1:])

    def test_a_cache_miss_reads_the_database_and_seeds_the_key(self):
        self._notify([self.me])
        self.redis.delete(self.prefix + str(self.me))
        reply = ns.poll(self.me, 0)
        self.assertEqual(len(reply["notifications"]), 1)
        self.assertEqual(self._cached(self.me), reply["next_cursor"])

    def test_a_full_page_does_not_seed_the_key(self):
        db.session.execute(sa.insert(MapUserNotification), [
            {"user_id": self.me, "kind": "revision_requested", "project_id": PROJECT} for _ in range(ns.PAGE_SIZE + 5)])
        db.session.commit()
        reply = ns.poll(self.me, 0)
        self.assertEqual(len(reply["notifications"]), ns.PAGE_SIZE)
        self.assertIsNone(self._cached(self.me))
        rest = ns.poll(self.me, reply["next_cursor"])
        self.assertEqual(len(rest["notifications"]), 5)
        self.assertEqual(self._cached(self.me), rest["next_cursor"])

    # -- the endpoint -------------------------------------------------------

    def test_the_endpoint_returns_own_rows_in_order_with_a_working_cursor(self):
        death, draft = uuid.uuid4(), uuid.uuid4()
        self._notify([self.me, self.other], "other_draft_started", death_id=death, draft_id=draft)
        self._notify([self.me], "case_reopened", death_id=death, va_sid="SID1")
        self._login(str(self.me))
        body = self.client.get(URL).get_json()
        kinds = [n["kind"] for n in body["notifications"]]
        self.assertEqual(kinds, ["other_draft_started", "case_reopened"])
        ids = [n["id"] for n in body["notifications"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(body["next_cursor"], ids[-1])
        first = body["notifications"][0]
        self.assertEqual(set(first), {"id", "kind", "created_at", "project_id", "death_id", "draft_id", "va_sid"})
        self.assertEqual((first["project_id"], first["death_id"], first["draft_id"], first["va_sid"]), (PROJECT, str(death), str(draft), None))
        self.assertEqual(self.client.get(f"{URL}?after={ids[0]}").get_json()["notifications"][0]["id"], ids[1])
        again = self.client.get(f"{URL}?after={ids[-1]}").get_json()
        self.assertEqual(again, {"notifications": [], "next_cursor": ids[-1]})

    def test_the_endpoint_never_returns_another_users_rows(self):
        self._notify([self.other], "case_reopened")
        self._login(str(self.me))
        self.redis.delete(self.prefix + str(self.me))
        body = self.client.get(URL).get_json()
        self.assertEqual(body["notifications"], [])

    def test_an_empty_poll_reads_no_notification_table(self):
        self._notify([self.me])
        newest = self._ids(self.me)[-1]
        self._login(str(self.me))
        with count_queries() as statements:
            response = self.client.get(f"{URL}?after={newest}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s for s in statements if "map_user_notifications" in s], [])

    def test_a_bad_cursor_is_400_and_signed_out_is_401(self):
        self._login(str(self.me))
        for bad in ("abc", "-1", "1.5", "", "99999999999999999999", "%C2%B2"):
            response = self.client.get(f"{URL}?after={bad}")
            self.assertEqual((response.status_code, response.get_json()["code"]), (400, "invalid_request"), bad)
        from flask import g

        g.pop("_login_user", None)  # Flask-Login's per-context cache outlives a request in tests
        self.assertEqual(self.app.test_client().get(URL).status_code, 401)

    # -- purge --------------------------------------------------------------

    def test_purge_deletes_only_rows_older_than_thirty_days_in_batches(self):
        now = datetime.now(UTC)
        old = now - timedelta(days=ns.RETENTION_DAYS, hours=1)
        recent = now - timedelta(days=ns.RETENTION_DAYS - 1)
        db.session.execute(sa.insert(MapUserNotification), (
            [{"user_id": self.me, "kind": "case_reopened", "project_id": PROJECT, "created_at": old} for _ in range(7)]
            + [{"user_id": self.me, "kind": "case_reopened", "project_id": PROJECT, "created_at": recent} for _ in range(2)]))
        db.session.commit()
        survivors = set(db.session.scalars(sa.select(MapUserNotification.id).where(MapUserNotification.created_at >= recent)))
        self.assertEqual(len(survivors), 2)
        original = ns.PURGE_BATCH
        ns.PURGE_BATCH = 3
        self.addCleanup(setattr, ns, "PURGE_BATCH", original)
        with count_queries() as statements:
            purged = ns.purge_expired()
        self.assertEqual(purged, 7)
        self.assertEqual(len([s for s in statements if s.startswith("DELETE")]), 3)  # 3 + 3 + 1
        remaining = set(db.session.scalars(sa.select(MapUserNotification.id).where(MapUserNotification.user_id == self.me)))
        self.assertEqual(remaining, survivors)


def test_a_savepoint_release_does_not_publish_before_the_outer_commit():
    class Savepoint:
        info = {ns._PENDING: {"u": 7}}

        def in_nested_transaction(self):
            return True

    session = Savepoint()
    ns._publish_latest_ids(session)
    assert session.info == {ns._PENDING: {"u": 7}}  # still pending for the outer commit
