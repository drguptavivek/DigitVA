from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from app.services.payload_enrichment_backfill_service import (
    _enrich_with_single_reauth_retry,
    _is_odk_auth_401_error,
)


class PayloadEnrichmentBackfillRetryTests(TestCase):
    def test_is_odk_auth_401_error_matches_expected_messages(self):
        self.assertTrue(_is_odk_auth_401_error(Exception("HTTP 401 from ODK")))
        self.assertTrue(
            _is_odk_auth_401_error(
                Exception("Could not authenticate with the provided credentials.")
            )
        )
        self.assertFalse(_is_odk_auth_401_error(Exception("HTTP 429 too many requests")))
        self.assertFalse(_is_odk_auth_401_error(Exception("HTTP 500 internal error")))

    def test_enrich_retries_once_with_reauth_on_401(self):
        va_form = SimpleNamespace(project_id="PROJ01")
        original_client = object()
        refreshed_client = object()
        payload_data = {"KEY": "uuid:abc"}

        calls = {"count": 0}

        def enrich_fn(_va_form, _payload_data, *, client):
            calls["count"] += 1
            if calls["count"] == 1:
                raise Exception("Submission XML fetch failed HTTP 401 for FORM01/uuid:abc")
            self.assertIs(client, refreshed_client)
            return {"KEY": "uuid:abc", "FormVersion": "1"}

        client_factory = Mock(return_value=refreshed_client)
        log_submission_step = Mock()

        enriched, final_client = _enrich_with_single_reauth_retry(
            va_form=va_form,
            payload_data=payload_data,
            client=original_client,
            enrich_fn=enrich_fn,
            client_factory=client_factory,
            log_submission_step=log_submission_step,
        )

        self.assertEqual(calls["count"], 2)
        self.assertEqual(enriched["FormVersion"], "1")
        self.assertIs(final_client, refreshed_client)
        client_factory.assert_called_once_with(project_id="PROJ01")
        log_submission_step.assert_called_once_with(
            "enrich: auth failed (401), reauth and retry once"
        )

    def test_enrich_does_not_retry_for_non_401_error(self):
        va_form = SimpleNamespace(project_id="PROJ01")
        original_client = object()
        payload_data = {"KEY": "uuid:abc"}

        def enrich_fn(_va_form, _payload_data, *, client):
            self.assertIs(client, original_client)
            raise Exception("Submission XML fetch failed HTTP 500 for FORM01/uuid:abc")

        client_factory = Mock()
        log_submission_step = Mock()

        with self.assertRaisesRegex(Exception, "HTTP 500"):
            _enrich_with_single_reauth_retry(
                va_form=va_form,
                payload_data=payload_data,
                client=original_client,
                enrich_fn=enrich_fn,
                client_factory=client_factory,
                log_submission_step=log_submission_step,
            )

        client_factory.assert_not_called()
        log_submission_step.assert_not_called()
