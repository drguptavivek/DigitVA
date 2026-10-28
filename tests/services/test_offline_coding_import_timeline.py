"""Offline coding timeline provenance validation and retention."""

import unittest

from app.services.offline_coding_import_service import OfflineCodingError, parse_offline_coding


class TestOfflineCodingTimeline(unittest.TestCase):
    def _coding(self, timeline):
        return {
            "coded_answers_sha256": "a" * 64,
            "device_uuid": "123e4567-e89b-12d3-a456-426614174000",
            "process_token": "local-123e4567-e89b-12d3-a456-426614174000",
            "conclusive_cod": "1B10.Z Pulmonary tuberculosis",
            "certificate": {},
            "provenance": {
                "allowability": {"rules": "rules-v1", "release": "2026-01"},
                "antecedent": {"code": "1B10.Z", "primary_stem": "1B10.Z", "release": "2026-01"},
                "workflowTimelineV1": timeline,
                "codingTimelineV1": timeline,
            },
        }

    def test_accepts_and_retains_bounded_offset_coding_events(self):
        events = [
            {"event": "coding_opened", "at": "2026-10-28T09:00:00+05:30"},
            {"event": "doris_processed", "at": "2026-10-28T09:05:00+05:30", "elapsed_ms": 2500},
            {"event": "initial_saved", "at": "2026-10-28T09:06:00+05:30"},
        ]

        parsed = parse_offline_coding(self._coding(events))

        self.assertEqual(parsed["provenance"]["workflowTimelineV1"], events)
        self.assertEqual(parsed["provenance"]["codingTimelineV1"], events)

    def test_rejects_non_coding_or_unbounded_timeline_input(self):
        invalid_events = [
            [{"event": "coding_allocated", "at": "2026-10-28T09:00:00+05:30"}],
            [{"event": "interview_started", "at": "2026-10-28T09:00:00+05:30"}],
            [{"event": "coding_opened", "at": "2026-10-28T09:00:00"}],
            [{"event": "coding_opened", "at": "2026-10-28T09:00:00+05:30", "elapsed_ms": 86_400_001}],
        ]

        for timeline in invalid_events:
            with self.subTest(timeline=timeline), self.assertRaises(OfflineCodingError):
                parse_offline_coding(self._coding(timeline))

    def test_duplicate_coding_events_keep_the_first_timestamp(self):
        first_open = {"event": "coding_opened", "at": "2026-10-28T09:00:00+05:30"}
        duplicate_open = {"event": "coding_opened", "at": "2026-10-28T09:01:00+05:30"}
        parsed = parse_offline_coding(self._coding([first_open, duplicate_open]))

        self.assertEqual(parsed["provenance"]["codingTimelineV1"], [first_open])

    def test_rejects_client_final_saved_even_in_the_new_timeline_field(self):
        for key in ("workflowTimelineV1", "codingTimelineV1"):
            payload = self._coding([])
            payload["provenance"][key] = [
                {"event": "final_saved", "at": "2026-10-28T09:00:00+05:30"},
            ]
            with self.subTest(key=key), self.assertRaises(OfflineCodingError):
                parse_offline_coding(payload)
