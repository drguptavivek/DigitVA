"""Unit tests for clinical DORIS processing and signed proof contracts."""

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from requests import Response

from app.routes.api.doris_clinical import (
    ClinicalDorisContext,
    clinical_codeinfo,
    clinical_process,
    clinical_selection_check,
    clinical_terms,
)
from app.services.doris_process_proof import (
    ProcessProofCertificateChanged,
    ProcessProofContextMismatch,
    ProcessProofResultMismatch,
    generate_process_proof,
    verify_process_submission,
)
from app.services.doris_processing import certificate_digest, processor_result_digest
from tests.base import BaseTestCase

_IMAGE = "sha256:pinned-image"
_URI = "http://id.who.int/icd/release/11/2026-01/mms/882244568/unspecified"


def _certificate(text="Respiratory tuberculosis"):
    return {
        "ICDVersion": "ICD11",
        "ICDMinorVersion": "2026-01",
        "Part1": [
            {
                "Conditions": [
                    {
                        "Text": text,
                        "Code": "1B10.Z",
                        "LinearizationURI": _URI,
                        "Interval": "P14D",
                    }
                ]
            }
        ],
    }


def _engines():
    doris = {
        "status": "completed",
        "result": {
            "code": "1B10.Z",
            "stemCode": "1B10.Z",
            "uri": _URI,
            "stemURI": _URI,
            "report": "report",
            "tabularReport": "table",
            "reject": False,
            "error": None,
            "warning": None,
        },
    }
    codedit = {
        "status": "completed",
        "result": {"report": "report", "tabularReport": "table", "issueIds": "A|B"},
    }
    return doris, codedit


def _upstream(payload: bytes):
    response = Response()
    response.status_code = 200
    response._content = payload
    return response


class TestDorisProcessProof(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user_id = uuid4()
        self.allocation_id = uuid4()
        self.payload_version_id = uuid4()

    def _proof(self):
        certificate = _certificate()
        doris, codedit = _engines()
        cert_digest = certificate_digest(certificate)
        result_digest = processor_result_digest(
            doris, codedit, release="2026-01", who_image_digest=_IMAGE
        )
        token = generate_process_proof(
            certificate_digest=cert_digest,
            result_digest=result_digest,
            va_sid="SID-1",
            role="coder",
            user_id=self.user_id,
            allocation_id=self.allocation_id,
            payload_version_id=self.payload_version_id,
            icd_release="2026-01",
            who_image_digest=_IMAGE,
        )
        return token, certificate, doris, codedit, result_digest

    def test_submission_round_trip_returns_normalized_verified_artifacts(self):
        token, certificate, doris, codedit, result_digest = self._proof()

        verified = verify_process_submission(
            token,
            certificate=certificate,
            doris_result=doris,
            codedit_result=codedit,
            submitted_result_digest=result_digest,
            va_sid="SID-1",
            role="coder",
            user_id=self.user_id,
            allocation_id=self.allocation_id,
            payload_version_id=self.payload_version_id,
            icd_release="2026-01",
            who_image_digest=_IMAGE,
        )

        self.assertEqual(verified["certificate_digest"], certificate_digest(certificate))
        self.assertEqual(verified["codedit"]["result"]["issueIds"], "A|B")

    def test_changed_certificate_has_distinct_failure(self):
        token, _, doris, codedit, result_digest = self._proof()
        with self.assertRaises(ProcessProofCertificateChanged):
            verify_process_submission(
                token,
                certificate=_certificate("Changed text"),
                doris_result=doris,
                codedit_result=codedit,
                submitted_result_digest=result_digest,
                va_sid="SID-1",
                role="coder",
                user_id=self.user_id,
                allocation_id=self.allocation_id,
                payload_version_id=self.payload_version_id,
                icd_release="2026-01",
                who_image_digest=_IMAGE,
            )

    def test_changed_results_and_context_have_distinct_failures(self):
        token, certificate, doris, codedit, result_digest = self._proof()
        changed_codedit = {**codedit, "result": {**codedit["result"], "issueIds": "changed"}}
        with self.assertRaises(ProcessProofResultMismatch):
            verify_process_submission(
                token,
                certificate=certificate,
                doris_result=doris,
                codedit_result=changed_codedit,
                submitted_result_digest=result_digest,
                va_sid="SID-1",
                role="coder",
                user_id=self.user_id,
                allocation_id=self.allocation_id,
                payload_version_id=self.payload_version_id,
                icd_release="2026-01",
                who_image_digest=_IMAGE,
            )
        with self.assertRaises(ProcessProofContextMismatch):
            verify_process_submission(
                token,
                certificate=certificate,
                doris_result=doris,
                codedit_result=codedit,
                submitted_result_digest=result_digest,
                va_sid="SID-1",
                role="reviewer",
                user_id=self.user_id,
                allocation_id=self.allocation_id,
                payload_version_id=self.payload_version_id,
                icd_release="2026-01",
                who_image_digest=_IMAGE,
            )

    def test_process_route_issues_context_bound_token(self):
        doris, codedit = _engines()
        result = {
            "schema_version": 1,
            "client_revision": 4,
            "icd_release": "2026-01",
            "certificate": _certificate(),
            "certificate_digest": certificate_digest(_certificate()),
            "result_digest": processor_result_digest(
                doris, codedit, release="2026-01", who_image_digest=_IMAGE
            ),
            "doris": doris,
            "codedit": codedit,
        }
        payload = {
            "schema_version": 1,
            "client_revision": 4,
            "role": "coder",
            "certificate": _certificate(),
        }
        context = ClinicalDorisContext("coder", self.allocation_id, self.payload_version_id)
        fake_user = SimpleNamespace(user_id=self.user_id)
        self.app.config["DORIS_WHO_IMAGE_DIGEST"] = _IMAGE
        with self.app.test_request_context(json=payload):
            with (
                patch("app.routes.api.doris_clinical._clinical_context", return_value=context),
                patch("app.routes.api.doris_clinical.process_certificate", return_value=result),
                patch("app.routes.api.doris_clinical.current_user", fake_user),
            ):
                response = clinical_process.__wrapped__("SID-1")

        body = response.get_json()
        self.assertEqual(body["doris"]["status"], "completed")
        self.assertTrue(body["process_token"])

    def test_process_route_signs_advisory_dual_engine_failure(self):
        failed = {
            "schema_version": 1,
            "client_revision": 4,
            "icd_release": "2026-01",
            "certificate": _certificate(),
            "certificate_digest": certificate_digest(_certificate()),
            "result_digest": "a" * 64,
            "doris": {"status": "timeout", "result": None},
            "codedit": {"status": "unavailable", "result": None},
        }
        payload = {
            "schema_version": 1,
            "client_revision": 4,
            "role": "coder",
            "certificate": _certificate(),
        }
        context = ClinicalDorisContext("coder", self.allocation_id, self.payload_version_id)
        self.app.config["DORIS_WHO_IMAGE_DIGEST"] = _IMAGE
        with self.app.test_request_context(json=payload):
            with (
                patch("app.routes.api.doris_clinical._clinical_context", return_value=context),
                patch("app.routes.api.doris_clinical.process_certificate", return_value=failed),
                patch(
                    "app.routes.api.doris_clinical.current_user",
                    SimpleNamespace(user_id=self.user_id),
                ),
            ):
                response = clinical_process.__wrapped__("SID-1")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["process_token"])

    def test_process_rejects_request_over_32_kib_before_processing(self):
        oversized = {
            "schema_version": 1,
            "client_revision": 1,
            "role": "coder",
            "certificate": {"padding": "x" * (33 * 1024)},
        }
        with self.app.test_request_context(json=oversized):
            with patch("app.routes.api.doris_clinical.process_certificate") as processor:
                response, status = clinical_process.__wrapped__("SID-1")

        self.assertEqual(status, 400)
        self.assertEqual(response.get_json()["error"]["code"], "MALFORMED_JSON")
        processor.assert_not_called()

    def test_terms_returns_bounded_plain_normalized_items(self):
        payload = {"schema_version": 1, "query": "diabetes", "limit": 1, "cursor": None}
        upstream = _upstream(
            b'{"destinationEntities":[{"theCode":"5A11","id":"http://id.who.int/x",'
            b'"title":"<em>Type 2</em> diabetes","matchingPVs":["diabetes"]}],'
            b'"resultChopped":true}'
        )
        with self.app.test_request_context(json=payload):
            with (
                patch(
                    "app.routes.api.doris_clinical._require_terminology_context",
                    return_value=(SimpleNamespace(), None),
                ),
                patch(
                    "app.routes.api.doris_clinical.proxy_who_icd_request",
                    return_value=upstream,
                ),
            ):
                response = clinical_terms.__wrapped__("SID-1")

        body = response.get_json()
        self.assertEqual(body["items"][0]["title"], "Type 2 diabetes")
        self.assertTrue(body["truncated"])
        self.assertIsNone(body["next_cursor"])

    def test_codeinfo_and_selection_check_use_canonical_item(self):
        item = {
            "code": "1B10.Z",
            "title": "Respiratory tuberculosis",
            "uri": _URI,
            "release": "2026-01",
            "postcoordination": False,
        }
        context_patch = patch(
            "app.routes.api.doris_clinical._require_terminology_context",
            return_value=(SimpleNamespace(), None),
        )
        with self.app.test_request_context(
            json={"schema_version": 1, "code": "1B10.Z"}
        ):
            with context_patch, patch(
                "app.routes.api.doris_clinical._codeinfo_item", return_value=item
            ):
                codeinfo_response = clinical_codeinfo.__wrapped__("SID-1")
        with self.app.test_request_context(
            json={"schema_version": 1, "code": "1B10.Z", "uri": _URI}
        ):
            with patch(
                "app.routes.api.doris_clinical._require_terminology_context",
                return_value=(SimpleNamespace(), None),
            ), patch("app.routes.api.doris_clinical._codeinfo_item", return_value=item):
                selected_response = clinical_selection_check.__wrapped__("SID-1")

        self.assertEqual(codeinfo_response.get_json()["item"], item)
        self.assertEqual(selected_response.get_json()["item"], item)
