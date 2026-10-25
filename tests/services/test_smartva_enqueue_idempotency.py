"""SmartVA enqueue claims prevent duplicate dispatches for one submission."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import sqlalchemy as sa

from app import cache, db
from app.models import VaSmartvaResults
from app.services import smartva_service
from tests.base import BaseTestCase


class SmartvaEnqueueIdempotencyTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.va_sid = f"ENQUEUE-{uuid.uuid4()}"

    def tearDown(self):
        smartva_service.clear_run_marker(self.va_sid)
        super().tearDown()

    def test_concurrent_enqueues_dispatch_once(self):
        claim_created = threading.Event()
        release_claimant = threading.Event()
        original_add = smartva_service.flask_cache.add

        def pause_after_claim(key, value, timeout=None):
            claimed = original_add(key, value, timeout=timeout)
            if claimed:
                claim_created.set()
                self.assertTrue(release_claimant.wait(timeout=5))
            return claimed

        delay = mock.Mock()

        def enqueue():
            with self.app.app_context():
                return smartva_service.enqueue_smartva(self.va_sid, "coding_page")

        with (
            mock.patch.object(smartva_service, "_has_current_payload_success", return_value=False),
            mock.patch.object(smartva_service.flask_cache, "add", side_effect=pause_after_claim),
            mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay", delay),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            winner = pool.submit(enqueue)
            self.assertTrue(claim_created.wait(timeout=5))
            loser_result = enqueue()
            release_claimant.set()
            winner_result = winner.result(timeout=5)

        self.assertEqual([winner_result, loser_result], [True, True])
        delay.assert_called_once_with(
            va_sid=self.va_sid,
            triggered_by="coding_page",
            regenerate=False,
        )

    def test_prequeued_after_commit_marker_still_dispatches(self):
        smartva_service.set_run_marker(self.va_sid, smartva_service.SMARTVA_QUEUED)
        with (
            mock.patch.object(smartva_service, "_has_current_payload_success", return_value=False),
            mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay") as delay,
        ):
            self.assertTrue(smartva_service.enqueue_smartva(self.va_sid, "web_intake_submit"))

        delay.assert_called_once()
        self.assertEqual(smartva_service.run_marker(self.va_sid), smartva_service.SMARTVA_QUEUED)

    def test_after_commit_callback_skips_redundant_outcome_queries(self):
        with (
            mock.patch.object(
                smartva_service,
                "_has_current_payload_success",
                side_effect=AssertionError("fresh payload should not need a result lookup"),
            ),
            mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay") as delay,
        ):
            db.session.execute(sa.text("SELECT 1"))
            smartva_service.queue_smartva_after_commit(self.va_sid, "web_intake_submit")
            db.session.commit()

        delay.assert_called_once_with(
            va_sid=self.va_sid,
            triggered_by="web_intake_submit",
            regenerate=False,
        )

    def test_broker_failure_releases_claim_for_retry(self):
        with mock.patch.object(smartva_service, "_has_current_payload_success", return_value=False):
            with mock.patch(
                "app.tasks.sync_tasks.run_smartva_for_submission.delay",
                side_effect=ConnectionError("broker down"),
            ):
                self.assertFalse(smartva_service.enqueue_smartva(self.va_sid, "coding_page"))

            self.assertIsNone(cache.get(smartva_service.enqueue_claim_key(self.va_sid)))
            self.assertIsNone(smartva_service.run_marker(self.va_sid))

            with mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay") as delay:
                self.assertTrue(smartva_service.enqueue_smartva(self.va_sid, "coding_page"))
        delay.assert_called_once()

    def test_fast_worker_does_not_leave_a_claim_after_completion(self):
        def complete_before_delay_returns(**_kwargs):
            smartva_service.clear_run_marker(self.va_sid)

        with (
            mock.patch.object(smartva_service, "_has_current_payload_success", return_value=False),
            mock.patch(
                "app.tasks.sync_tasks.run_smartva_for_submission.delay",
                side_effect=complete_before_delay_returns,
            ),
        ):
            self.assertTrue(smartva_service.enqueue_smartva(self.va_sid, "coding_page"))

        self.assertIsNone(cache.get(smartva_service.enqueue_claim_key(self.va_sid)))

    def test_successful_current_payload_skips_dispatch(self):
        with (
            mock.patch.object(smartva_service, "_has_current_payload_success", return_value=True),
            mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay") as delay,
        ):
            self.assertTrue(smartva_service.enqueue_smartva(self.va_sid, "coding_page"))

        delay.assert_not_called()
        self.assertIsNone(cache.get(smartva_service.enqueue_claim_key(self.va_sid)))

    def test_current_payload_success_after_claim_releases_unused_claim(self):
        with (
            mock.patch.object(
                smartva_service,
                "_has_current_payload_success",
                side_effect=(False, True),
            ),
            mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay") as delay,
        ):
            self.assertTrue(smartva_service.enqueue_smartva(self.va_sid, "coding_page"))

        delay.assert_not_called()
        self.assertIsNone(cache.get(smartva_service.enqueue_claim_key(self.va_sid)))
        self.assertIsNone(smartva_service.run_marker(self.va_sid))

    def test_regeneration_keeps_request_audit_arguments(self):
        requested_by = (str(uuid.uuid4()), "vacoder")
        with (
            mock.patch.object(smartva_service, "_has_current_payload_success", return_value=True),
            mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay") as delay,
        ):
            self.assertTrue(
                smartva_service.enqueue_smartva(
                    self.va_sid,
                    "coding_page",
                    regenerate=True,
                    requested_by=requested_by,
                )
            )

        delay.assert_called_once_with(
            va_sid=self.va_sid,
            triggered_by="coding_page",
            regenerate=True,
            requested_by=requested_by,
        )

    def test_failed_current_result_can_be_run_again(self):
        with (
            mock.patch.object(
                smartva_service,
                "_current_payload_result_outcome",
                return_value=VaSmartvaResults.OUTCOME_FAILED,
            ),
            mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay") as delay,
        ):
            self.assertTrue(smartva_service.enqueue_smartva(self.va_sid, "coding_page"))

        delay.assert_called_once_with(
            va_sid=self.va_sid,
            triggered_by="coding_page",
            regenerate=False,
        )

    def test_expired_orphan_claim_can_be_retried(self):
        cache.add(smartva_service.enqueue_claim_key(self.va_sid), True, timeout=1)
        with mock.patch.object(smartva_service, "_has_current_payload_success", return_value=False):
            with mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay") as delay:
                self.assertFalse(
                    smartva_service.enqueue_smartva(self.va_sid, "coding_page")
                )
                time.sleep(1.1)
                self.assertTrue(
                    smartva_service.enqueue_smartva(self.va_sid, "coding_page")
                )

        delay.assert_called_once()

    def test_stale_dispatching_claim_without_work_is_not_accepted(self):
        cache.add(
            smartva_service.enqueue_claim_key(self.va_sid),
            {
                "state": "dispatching",
                "started_at": time.time() - smartva_service.SMARTVA_ENQUEUE_IN_PROGRESS_SECONDS - 1,
            },
            timeout=smartva_service.SMARTVA_CLAIMED_MARKER_TTL_SECONDS,
        )
        with (
            mock.patch.object(smartva_service, "_has_current_payload_success", return_value=False),
            mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay") as delay,
        ):
            self.assertFalse(smartva_service.enqueue_smartva(self.va_sid, "coding_page"))

        delay.assert_not_called()

    def test_expired_claim_does_not_duplicate_a_running_case(self):
        smartva_service.set_run_marker(self.va_sid, smartva_service.SMARTVA_RUNNING)
        with (
            mock.patch.object(smartva_service, "_has_current_payload_success", return_value=False),
            mock.patch.object(smartva_service.flask_cache, "add", return_value=True),
            mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay") as delay,
        ):
            self.assertTrue(smartva_service.enqueue_smartva(self.va_sid, "coding_page"))

        delay.assert_not_called()
        self.assertEqual(smartva_service.run_marker(self.va_sid), smartva_service.SMARTVA_RUNNING)
        self.assertIsNone(cache.get(smartva_service.enqueue_claim_key(self.va_sid)))

    def test_post_claim_query_failure_releases_claim_for_retry(self):
        with (
            mock.patch.object(
                smartva_service,
                "_has_current_payload_success",
                side_effect=(False, RuntimeError("database unavailable")),
            ),
            mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay") as delay,
        ):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                smartva_service.enqueue_smartva(self.va_sid, "coding_page")

        self.assertIsNone(cache.get(smartva_service.enqueue_claim_key(self.va_sid)))
        with (
            mock.patch.object(smartva_service, "_has_current_payload_success", return_value=False),
            mock.patch("app.tasks.sync_tasks.run_smartva_for_submission.delay") as delay,
        ):
            self.assertTrue(smartva_service.enqueue_smartva(self.va_sid, "coding_page"))
        delay.assert_called_once()
