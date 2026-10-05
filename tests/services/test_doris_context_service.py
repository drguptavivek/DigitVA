"""DORIS seeds and saved-processing context (app/services/doris_context_service.py).

Pure unit tests: rows are namespaces, so no database is needed. The one rule
under test everywhere: a redacting viewer never receives AdministrativeData
(the deceased's Sex, DateBirth, DateDeath, age) in any returned certificate.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.models import VaStatuses
from app.services import doris_context_service as svc

_ADMIN = {"Sex": 2, "DateDeath": "2026-01-02"}
_PART1 = {"Conditions": [{"Code": "1B10.Z", "Text": "TB"}]}


def _certificate():
    return {"AdministrativeData": dict(_ADMIN), "Part1": [dict(_PART1)]}


def _step1(*, result=True, status=VaStatuses.active, certificate=True):
    return SimpleNamespace(
        va_iniassess_status=status,
        doris_certificate=_certificate() if certificate else None,
        doris_result={"status": "ok"} if result else None,
        codedit_result={"status": "ok"} if result else None,
        va_antecedent_cod="1B10.Z TB",
    )


def _walk_has_administrative_data(value) -> bool:
    if isinstance(value, dict):
        return "AdministrativeData" in value or any(
            _walk_has_administrative_data(v) for v in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_walk_has_administrative_data(v) for v in value)
    return False


class DorisInitialTests(unittest.TestCase):
    def test_saved_certificate_is_copied_and_redacted_only_for_a_redacting_viewer(self):
        saved = _certificate()
        full, provenance = svc.doris_initial(saved, None, "masked_doris", False)
        self.assertIn("AdministrativeData", full)  # present before asserting absent
        self.assertIsNot(full, saved)
        self.assertEqual(provenance, {})
        redacted, _ = svc.doris_initial(saved, None, "masked_doris", True)
        self.assertNotIn("AdministrativeData", redacted)
        self.assertEqual(redacted["Part1"], [_PART1])
        self.assertIn("AdministrativeData", saved)  # the stored row is untouched

    def test_prefill_only_for_a_doris_project_and_a_non_redacting_viewer(self):
        submission = SimpleNamespace(va_sid="uuid:x")
        version = SimpleNamespace(payload_data={"Id10019": "female"})
        prefilled = ({"AdministrativeData": {"Sex": 2}}, {"AdministrativeData.Sex": {}})
        with patch.object(svc, "doris_prefill_from_payload", return_value=prefilled) as prefill:
            self.assertEqual(
                svc.doris_initial(None, submission, "masked_doris", False, version), prefilled
            )
            self.assertEqual(prefill.call_args.args, (version.payload_data,))
            self.assertEqual(svc.doris_initial(None, submission, "masked_doris", True, version), ({}, {}))
            self.assertEqual(svc.doris_initial(None, submission, "masked_simple", False, version), ({}, {}))
            self.assertEqual(svc.doris_initial(None, None, "masked_doris", False, version), ({}, {}))
        self.assertEqual(prefill.call_count, 1)


class SavedProcessingTests(unittest.TestCase):
    def test_a_saved_result_reopens_with_a_redacted_certificate(self):
        step1 = _step1()
        full = svc.saved_step1_processing(step1, False)
        self.assertIn("AdministrativeData", full["certificate"])
        redacted = svc.saved_step1_processing(step1, True)
        self.assertNotIn("AdministrativeData", redacted["certificate"])
        self.assertEqual(redacted["final_choice"], "1B10.Z TB")
        self.assertEqual(redacted["doris"], {"status": "ok"})
        self.assertIn("AdministrativeData", step1.doris_certificate)

    def test_no_row_or_no_result_is_none(self):
        self.assertIsNone(svc.saved_step1_processing(None, False))
        self.assertIsNone(svc.saved_step1_processing(_step1(result=False), False))

    def test_step2_context_redacts_the_step1_certificate(self):
        step1 = _step1()
        self.assertIn("AdministrativeData", svc.masked_step2_context(step1, None, False)["step1_doris_certificate"])
        context = svc.masked_step2_context(step1, None, True)
        self.assertNotIn("AdministrativeData", context["step1_doris_certificate"])
        self.assertEqual(context["step1_doris_processing"], {"doris": {"status": "ok"}, "codedit": {"status": "ok"}})
        empty = svc.masked_step2_context(None, None, True)
        self.assertEqual(
            (empty["step1_doris_certificate"], empty["step1_doris_processing"]), (None, None)
        )


class MaskedReviewerContextTests(unittest.TestCase):
    def test_own_saved_step1_is_the_seed_and_reopens_redacted(self):
        own = _step1()
        source, context = svc.masked_reviewer_context("uuid:x", own, None, True)
        self.assertIs(source, own)
        self.assertNotIn("AdministrativeData", context["doris_initial_processing"]["certificate"])
        self.assertNotIn("AdministrativeData", context["step1_doris_certificate"])

    def test_without_an_own_step1_the_coders_step1_is_the_seed(self):
        coder_step1 = _step1()
        coder_final = SimpleNamespace(source_initial_assessment_id="initial-id")
        with patch.object(svc, "get_authoritative_final_assessment", return_value=coder_final), patch.object(
            svc.db.session, "get", return_value=coder_step1
        ) as get:
            source, context = svc.masked_reviewer_context("uuid:x", None, None, False)
        self.assertIs(source, coder_step1)
        self.assertNotIn("doris_initial_processing", context)
        self.assertEqual(get.call_args.args[1], "initial-id")

    def test_no_coder_final_leaves_the_admin_defaults(self):
        with patch.object(svc, "get_authoritative_final_assessment", return_value=None):
            self.assertEqual(svc.masked_reviewer_context("uuid:x", None, None, False)[0], None)


class WorkspaceDorisTests(unittest.TestCase):
    def _call(self, **kwargs):
        defaults = dict(
            va_sid="uuid:x", mode="coding", project_mode="masked_doris",
            submission=SimpleNamespace(va_sid="uuid:x"),
            active_version=SimpleNamespace(payload_data={}), redact_pii=False,
        )
        defaults.update(kwargs)
        with patch.object(svc, "doris_prefill_from_payload", return_value=({}, {})):
            return svc.workspace_doris(**defaults)

    def test_none_outside_a_doris_project(self):
        for mode in ("masked_simple", "unmasked_simple"):
            self.assertIsNone(self._call(project_mode=mode))

    def test_masked_coder_step1_carries_prefill_and_a_saved_result(self):
        body = self._call(step1=_step1())
        self.assertEqual(
            set(body),
            {"initial_certificate", "prefill_provenance", "saved_processing",
             "step1_certificate", "step1_processing"},
        )
        self.assertEqual(body["saved_processing"]["final_choice"], "1B10.Z TB")
        # A recode's inactive prior draft seeds the editor but is not a saved result.
        prior = self._call(step1=_step1(status=VaStatuses.deactive))
        self.assertIn("AdministrativeData", prior["initial_certificate"])
        self.assertIsNone(prior["saved_processing"])
        self.assertIsNone(prior["step1_certificate"])
        self.assertIsNone(self._call(step1=None)["saved_processing"])

    def test_every_certificate_is_redacted_for_a_redacting_viewer(self):
        for kwargs in (
            dict(mode="coding", step1=_step1()),
            dict(mode="reviewing", reviewer_initial=_step1()),
        ):
            with self.subTest(kwargs=sorted(kwargs)):
                # Present for a viewer entitled to personal data ...
                self.assertTrue(_walk_has_administrative_data(self._call(**kwargs)))
                # ... and gone, in every field, for a redacting one.
                self.assertFalse(
                    _walk_has_administrative_data(self._call(redact_pii=True, **kwargs))
                )
        seed = SimpleNamespace(doris_certificate=_certificate())
        with patch.object(svc, "get_authoritative_final_assessment", return_value=seed):
            for project_mode in ("unmasked_doris",):
                for mode in ("coding", "reviewing"):
                    with self.subTest(project_mode=project_mode, mode=mode):
                        self.assertTrue(
                            _walk_has_administrative_data(self._call(project_mode=project_mode, mode=mode))
                        )
                        self.assertFalse(_walk_has_administrative_data(
                            self._call(project_mode=project_mode, mode=mode, redact_pii=True)
                        ))

    def test_unmasked_seed_is_the_reviewers_final_else_the_authoritative_coder_final(self):
        coder_final = SimpleNamespace(doris_certificate={"Part1": ["coder"]})
        reviewer_final = SimpleNamespace(doris_certificate={"Part1": ["reviewer"]})
        with patch.object(svc, "get_authoritative_final_assessment", return_value=coder_final):
            own = self._call(project_mode="unmasked_doris", mode="reviewing", reviewer_final=reviewer_final)
            fallback = self._call(project_mode="unmasked_doris", mode="reviewing")
        self.assertEqual(own, {"initial_certificate": {"Part1": ["reviewer"]}, "prefill_provenance": {}})
        self.assertEqual(fallback["initial_certificate"], {"Part1": ["coder"]})
        self.assertEqual(set(fallback), {"initial_certificate", "prefill_provenance"})
