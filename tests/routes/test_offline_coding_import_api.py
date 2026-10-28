"""Collect Plus standalone and enrolled offline coding pushes.

``POST /api/v1/intake/submissions`` with ``standalone`` or enrolled
``offline_coding``:
idempotent duplicate push, routing by org code or to the unrouted queue, the
standalone consent snapshot (stored, sha mismatch refused), the device UUID
bound to the bearer session, offline coding held and imported as the coder's
final with the server's allowability re-check (agreement: coded with the normal
recode window; disagreement: flagged and in the reviewer pool at once), the
refusal for an account with no coding grant, no DORIS or WHO call, and the
training separation of every intake write.
"""
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest import mock

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    MasConsentNoticeVersion,
    MasIcd11Mms,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaBundlePendingCoding,
    VaConsentRecord,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUserAccessGrants,
    VaWebIntakeDraft,
)
from app.services import bundle_ingest_service, consent_service
from app.services import device_auth_service as devices
from app.services import organization_service as org
from app.services.consent_notice_seed import SEED_PURPOSES, SEED_TEXT, standalone_bundle_sha256
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from app.services.who_icd_api import DEFAULT_ICD11_RELEASE
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from tests.base import BaseTestCase
from tests.routes.test_device_api import _FreshGClient

PASSWORD = "Standalone123!"
PROJECT = "SAP01"
SITE = "SA01"
UNIT_CODE = "SAFAC01"
INTAKE = "/api/v1/intake/submissions"
AGREEING_CODE = "1B10.Z"
MALE_ONLY_CODE = "2C82.Z"
NEONATE_ONLY_CODE = "KA21.0"
OTHER_CODE = "1A00"


def _answers():
    # Female, 71 years: an adult woman.
    return {
        "Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "Id10019": "female",
        "Id10023": (date.today() - timedelta(days=5)).isoformat(), "finalAgeInYears": "71",
        "narr_language": "english",
    }


def _mms(code, *, sex="both", age="all"):
    return MasIcd11Mms(
        release=DEFAULT_ICD11_RELEASE, code=code, title=f"Title {code}", class_kind="category",
        linearization_uri=f"http://id.who.int/icd/release/11/{DEFAULT_ICD11_RELEASE}/mms/{code}",
        is_coding_selectable=True, sex_selectable=sex, age_group_selectable=age, source_version="test",
    )


class StandalonePushTests(BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=PROJECT, project_code=PROJECT, project_name="Standalone push", project_nickname=PROJECT,
            project_status=VaStatuses.active, project_registered_at=now, project_updated_at=now,
            web_intake_mode="both", self_coding_enabled=True, masked_cod_required=False,
            cod_entry_mode="doris", icd_classification="icd11",
        ))
        db.session.add(VaSiteMaster(site_id=SITE, site_name="Standalone site", site_abbr=SITE,
                                    site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now))
        db.session.flush()
        db.session.add(VaProjectSites(project_id=PROJECT, site_id=SITE, project_site_status=VaStatuses.active,
                                      project_site_registered_at=now, project_site_updated_at=now))
        db.session.flush()
        _ensure_legacy_project_site_rows(PROJECT, SITE)
        db.session.add(VaForms(
            form_id=f"{PROJECT}{SITE}01", project_id=PROJECT, site_id=SITE, odk_form_id="ODK_SAP01",
            odk_project_id="7", form_type="WHO VA 2022", form_source="odk", form_status=VaStatuses.active,
            form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()
        level = org.create_level(PROJECT, level_code="facility", level_name="Facility", depth=1)
        cls.unit = org.create_unit(PROJECT, org_level_id=level.org_level_id, unit_code=UNIT_CODE,
                                   unit_name="Standalone facility")
        cls.coder = cls._get_or_make_user("standalone.coder@test.local", PASSWORD)
        cls.interviewer = cls._get_or_make_user("standalone.interviewer@test.local", PASSWORD)
        for user, roles in ((cls.coder, (VaAccessRoles.interviewer, VaAccessRoles.coder)),
                            (cls.interviewer, (VaAccessRoles.interviewer,))):
            for role in roles:
                db.session.add(VaUserAccessGrants(
                    user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project, project_id=PROJECT,
                    notes="standalone push test grant", grant_status=VaStatuses.active,
                ))
        db.session.add_all([_mms(AGREEING_CODE), _mms(MALE_ONLY_CODE, sex="male"),
                            _mms(NEONATE_ONLY_CODE, age="neonate"), _mms(OTHER_CODE)])
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = _FreshGClient(self.app, self.app.response_class, use_cookies=True)
        # No DORIS re-run and no WHO call, at push or import: either one fails the test.
        for target in ("app.services.doris_processing.process_certificate",
                       "app.services.who_icd_api.get_icd11_codeinfo"):
            patcher = mock.patch(target, side_effect=AssertionError(f"{target} must not be called"))
            patcher.start()
            self.addCleanup(patcher.stop)

    # ── helpers ────────────────────────────────────────────────────────────

    def _device(self, user, client_uuid=None):
        """Enrol a phone with its install UUID and sign *user* in; returns (uuid, bearer headers)."""
        client_uuid = client_uuid or str(uuid.uuid4())
        _row, code = devices.create_enrolment_code(PROJECT, actor=self.base_admin_user)
        db.session.commit()
        device = self.client.post("/api/v1/auth/enroll", json={
            "code": code, "device_name": "Plus phone", "platform": "android", "client_device_uuid": client_uuid,
        }).get_json()
        tokens = self.client.post("/api/v1/auth/sessions", json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "email": user.email, "password": PASSWORD,
        })
        self.assertEqual(tokens.status_code, 201, tokens.get_json())
        return client_uuid, {"Authorization": f"Bearer {tokens.get_json()['access_token']}"}

    @staticmethod
    def _answers_json(answers=None):
        text = json.dumps(answers or _answers(), separators=(",", ":"))
        return text, hashlib.sha256(text.encode()).hexdigest()

    def _coding(self, client_uuid, answers_sha, code=AGREEING_CODE, *, confirmation=None):
        antecedent = {"code": code, "primary_stem": code, "release": DEFAULT_ICD11_RELEASE}
        if confirmation:
            antecedent["age_restriction_confirmation"] = confirmation
        return {
            "coded_answers_sha256": answers_sha, "device_uuid": client_uuid,
            "process_token": f"local-{uuid.uuid4()}", "conclusive_cod": f"{code} Title {code}", "remark": None,
            "certificate": {"ICDVersion": "ICD11", "Part1": [{"Conditions": [{"Code": code}]}]},
            "result": {"status": "ok", "result": {"stemCode": code}}, "codedit_result": None,
            "certificate_digest": "a" * 64, "result_digest": "b" * 64,
            "provenance": {"allowability": {"rules": "pack-2026-01", "release": DEFAULT_ICD11_RELEASE},
                           "antecedent": antecedent},
            "pack_versions": {"allowability": "pack-2026-01", "engine": "doris-1.1.176"},
        }

    @staticmethod
    def _consent(client_draft_id, *, text=None, sha=None, bundle=None):
        text = text or SEED_TEXT["en"].replace("[PROJECT NAME]", "the study team")
        real = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return {
            "envelope": {
                "client_id": str(uuid.uuid4()), "client_draft_id": str(client_draft_id),
                "notice_version_id": f"standalone-{real}", "notice_language": "en", "notice_sha256": sha or real,
                "decision": "granted",
                "purposes": sorted(({"code": p["code"], "granted": p["required"]} for p in SEED_PURPOSES["en"]),
                                   key=lambda p: p["code"]),
                "mode": "tap", "witness_present": False, "supersedes_client_id": None,
                "recorded_at": datetime.now(UTC).isoformat(),
            },
            "notice_text": text, "bundle_version": "seed-test", "bundle_sha256": bundle or standalone_bundle_sha256(),
        }

    def _push(self, headers, client_uuid, *, client_draft_id=None, answers=None, coding=True, code=AGREEING_CODE,
              org_code=UNIT_CODE, consent=None, confirmation=None, **extra):
        client_draft_id = client_draft_id or uuid.uuid4()
        answers_json, answers_sha = self._answers_json(answers)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        body = {
            "client_draft_id": str(client_draft_id), "project_id": PROJECT, "site_id": SITE,
            "draft": {"instrumentVersion": "2023072701", "startedAt": now, "completedAt": now,
                      "interviewOutcome": "completed"},
            "completion": {"valid": True, "issues": []},
            "answers_json": answers_json, "answers_sha256": answers_sha,
            "standalone": {"client_device_uuid": client_uuid, "org_code": org_code, "consent": consent,
                           "profile_snapshot": {"name": "Dr. Plus", "designation": "MO", "facility": "PHC",
                                                "country": "IND"}},
            **extra,
        }
        if coding:
            body["offline_coding"] = self._coding(client_uuid, answers_sha, code, confirmation=confirmation)
        return self.client.post(INTAKE, json=body, headers=headers), client_draft_id

    def _push_enrolled(self, headers, client_uuid, *, client_draft_id=None, answers=None, coding=True,
                       code=AGREEING_CODE, project_id=PROJECT, site_id=SITE, org_unit_id=None, **extra):
        client_draft_id = client_draft_id or uuid.uuid4()
        answers_json, answers_sha = self._answers_json(answers)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        body = {
            "client_draft_id": str(client_draft_id), "project_id": project_id, "site_id": site_id,
            "org_unit_id": str(org_unit_id or self.unit.org_unit_id),
            "draft": {"instrumentVersion": "2023072701", "startedAt": now, "completedAt": now,
                      "interviewOutcome": "completed"},
            "completion": {"valid": True, "issues": []},
            "answers_json": answers_json, "answers_sha256": answers_sha,
            **extra,
        }
        if coding:
            body["offline_coding"] = self._coding(client_uuid, answers_sha, code)
        return self.client.post(INTAKE, json=body, headers=headers), client_draft_id

    @staticmethod
    def _draft(client_draft_id):
        return db.session.scalar(sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.client_draft_id == client_draft_id))

    @staticmethod
    def _apply(va_sid):
        """The case leaves SmartVA, then the bundle applier's Celery run."""
        set_submission_workflow_state(va_sid, "ready_for_coding", reason="test", by_role="test")
        db.session.commit()
        return bundle_ingest_service.apply_pending_coding()

    def _final(self, va_sid):
        return db.session.scalar(sa.select(VaFinalAssessments).where(
            VaFinalAssessments.va_sid == va_sid, VaFinalAssessments.va_finassess_status == VaStatuses.active))

    def _audits(self, va_sid, prefix):
        return [a for a in db.session.scalars(sa.select(VaSubmissionsAuditlog.va_audit_action).where(
            VaSubmissionsAuditlog.va_sid == va_sid)) if a.startswith(prefix)]

    # ── interview: idempotency, device, routing, training ──────────────────

    def test_a_duplicate_push_returns_the_first_result_and_writes_nothing(self):
        client_uuid, headers = self._device(self.coder)
        first, draft_id = self._push(headers, client_uuid)
        self.assertEqual(first.status_code, 201, first.get_json())
        self.assertEqual(first.get_json()["offline_coding"], {"status": "pending", "code": "not_ready"})
        counts = lambda: (db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft)),  # noqa: E731
                          db.session.scalar(sa.select(sa.func.count()).select_from(VaBundlePendingCoding)),
                          db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissionsAuditlog)))
        before = counts()
        again, _ = self._push(headers, client_uuid, client_draft_id=draft_id)
        self.assertEqual(again.status_code, 200, again.get_json())
        self.assertEqual(again.get_json()["va_sid"], first.get_json()["va_sid"])
        self.assertEqual(again.get_json()["offline_coding"]["status"], "pending")
        self.assertEqual(counts(), before)
        meta = self._draft(draft_id).meta["standalone"]
        self.assertEqual((meta["clientDeviceUuid"], meta["orgCode"], meta["orgCodeMatched"]),
                         (client_uuid, UNIT_CODE, True))
        self.assertTrue(meta["processToken"].startswith("local-"))
        self.assertEqual(meta["packVersions"]["engine"], "doris-1.1.176")

    def test_the_same_draft_from_another_device_is_a_conflict(self):
        client_uuid, headers = self._device(self.coder)
        first, draft_id = self._push(headers, client_uuid, coding=False)
        self.assertEqual(first.status_code, 201, first.get_json())
        other_uuid, other_headers = self._device(self.coder)
        response, _ = self._push(other_headers, other_uuid, client_draft_id=draft_id, coding=False)
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "conflict"))

    def test_a_device_uuid_not_of_this_session_is_refused(self):
        client_uuid, headers = self._device(self.coder)
        before = db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft))
        response, _ = self._push(headers, str(uuid.uuid4()), coding=False)
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "device_mismatch"))
        # The coding's device_uuid must be the session's too.
        response, _ = self._push(headers, client_uuid, coding=False,
                                 offline_coding=self._coding(str(uuid.uuid4()), "c" * 64))
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "device_mismatch"))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft)), before)

    def test_routing_by_org_code_and_to_the_unrouted_queue(self):
        client_uuid, headers = self._device(self.interviewer)
        routed, routed_id = self._push(headers, client_uuid, coding=False)
        self.assertEqual(routed.status_code, 201, routed.get_json())
        submission = db.session.get(VaSubmissions, routed.get_json()["va_sid"])
        self.assertEqual((submission.org_unit_id, submission.org_unit_resolution),
                         (self.unit.org_unit_id, "form_field"))
        for org_code in ("NOSUCH01", None):
            unrouted, draft_id = self._push(headers, client_uuid, coding=False, org_code=org_code)
            self.assertEqual(unrouted.status_code, 201, unrouted.get_json())
            submission = db.session.get(VaSubmissions, unrouted.get_json()["va_sid"])
            self.assertIsNotNone(submission)
            self.assertIsNone(submission.org_unit_id)
            self.assertFalse(self._draft(draft_id).meta["standalone"]["orgCodeMatched"])

    def test_an_org_code_of_any_level_routes_to_that_unit(self):
        # self.unit is the tree's top level; a child below it makes it non-leaf.
        ward_level = org.create_level(PROJECT, level_code="ward", level_name="Ward", depth=2)
        ward = org.create_unit(PROJECT, org_level_id=ward_level.org_level_id, unit_code="SAWARD01",
                               unit_name="Standalone ward", parent_org_unit_id=self.unit.org_unit_id)
        client_uuid, headers = self._device(self.interviewer)
        for code, unit in (("sawArd01", ward), (UNIT_CODE, self.unit)):
            response, draft_id = self._push(headers, client_uuid, coding=False, org_code=code)
            self.assertEqual(response.status_code, 201, response.get_json())
            submission = db.session.get(VaSubmissions, response.get_json()["va_sid"])
            self.assertEqual((submission.org_unit_id, submission.org_unit_resolution),
                             (unit.org_unit_id, "form_field"))
            self.assertTrue(self._draft(draft_id).meta["standalone"]["orgCodeMatched"])

    def test_a_training_project_push_keeps_the_intake_training_rule(self):
        client_uuid, headers = self._device(self.coder)
        with mock.patch.dict(self.app.config, DIGITVA_TRAINING_PROJECT_ID=PROJECT):
            response, draft_id = self._push(headers, client_uuid)
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "training_scope"))
        self.assertIsNone(self._draft(draft_id))

    def test_enrolled_offline_coding_is_held_without_standalone_provenance(self):
        client_uuid, headers = self._device(self.coder)
        response, draft_id = self._push_enrolled(headers, client_uuid)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["offline_coding"], {"status": "pending", "code": "not_ready"})
        self.assertNotIn("standalone", self._draft(draft_id).meta)
        held = db.session.get(VaBundlePendingCoding, draft_id)
        self.assertEqual((held.result["enrolled_context"], held.result["profile_snapshot"]), (True, {}))

    def test_enrolled_coding_device_mismatch_is_refused_before_the_interview(self):
        _client_uuid, headers = self._device(self.coder)
        answers_json, answers_sha = self._answers_json()
        bad = self._coding(str(uuid.uuid4()), answers_sha)
        response = self.client.post(INTAKE, headers=headers, json={
            "client_draft_id": str(uuid.uuid4()), "project_id": PROJECT, "site_id": SITE,
            "org_unit_id": str(self.unit.org_unit_id),
            "draft": {"instrumentVersion": "2023072701"}, "completion": {"valid": True, "issues": []},
            "answers_json": answers_json, "answers_sha256": answers_sha, "offline_coding": bad,
        })
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "device_mismatch"))

    def test_same_hash_retry_can_add_enrolled_coding_and_is_idempotent(self):
        client_uuid, headers = self._device(self.coder)
        first, draft_id = self._push_enrolled(headers, client_uuid, coding=False)
        self.assertEqual(first.status_code, 201, first.get_json())
        second, _ = self._push_enrolled(headers, client_uuid, client_draft_id=draft_id)
        self.assertEqual(second.get_json()["offline_coding"], {"status": "pending", "code": "not_ready"})
        count = db.session.scalar(sa.select(sa.func.count()).select_from(VaBundlePendingCoding))
        again, _ = self._push_enrolled(headers, client_uuid, client_draft_id=draft_id)
        self.assertEqual(again.get_json()["offline_coding"], {"status": "pending", "code": "not_ready"})
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaBundlePendingCoding)), count)

    def test_same_hash_retry_rejects_a_cross_project_substitution(self):
        other_project, other_site = "SAP02", "SA02"
        now = datetime.now(UTC)
        db.session.add_all([
            VaProjectMaster(
                project_id=other_project, project_code=other_project, project_name="Other push",
                project_nickname=other_project, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, web_intake_mode="both",
                self_coding_enabled=True, masked_cod_required=False, cod_entry_mode="doris",
                icd_classification="icd11",
            ),
            VaSiteMaster(site_id=other_site, site_name="Other site", site_abbr=other_site,
                         site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now),
        ])
        db.session.flush()
        db.session.add(VaProjectSites(project_id=other_project, site_id=other_site,
                                      project_site_status=VaStatuses.active,
                                      project_site_registered_at=now, project_site_updated_at=now))
        _ensure_legacy_project_site_rows(other_project, other_site)
        db.session.add(VaForms(
            form_id=f"{other_project}{other_site}01", project_id=other_project, site_id=other_site,
            odk_form_id="ODK_SAP02", odk_project_id="8", form_type="WHO VA 2022", form_source="odk",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        db.session.add(VaUserAccessGrants(
            user_id=self.coder.user_id, role=VaAccessRoles.interviewer, scope_type=VaAccessScopeTypes.project,
            project_id=other_project, notes="cross-project retry test", grant_status=VaStatuses.active,
        ))
        db.session.commit()

        client_uuid, headers = self._device(self.coder)
        first, draft_id = self._push_enrolled(headers, client_uuid, coding=False)
        self.assertEqual(first.status_code, 201, first.get_json())
        response, _ = self._push_enrolled(
            headers, client_uuid, client_draft_id=draft_id, project_id=other_project, site_id=other_site,
        )
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "conflict"))
        self.assertIsNone(db.session.get(VaBundlePendingCoding, draft_id))

    def test_enrolled_coding_requires_self_coding_at_push(self):
        project = db.session.get(VaProjectMaster, PROJECT)
        project.self_coding_enabled = False
        db.session.commit()
        try:
            client_uuid, headers = self._device(self.coder)
            response, draft_id = self._push_enrolled(headers, client_uuid)
            self.assertEqual(response.get_json()["offline_coding"], {"status": "refused", "code": "self_coding_required"})
            self.assertTrue(db.session.get(VaBundlePendingCoding, draft_id).result["enrolled_context"])
        finally:
            project.self_coding_enabled = True
            db.session.commit()

    def test_enrolled_coding_is_refused_if_grant_is_revoked_before_apply(self):
        client_uuid, headers = self._device(self.coder)
        response, draft_id = self._push_enrolled(headers, client_uuid)
        self.assertEqual(response.get_json()["offline_coding"], {"status": "pending", "code": "not_ready"})
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.coder.user_id,
            VaUserAccessGrants.project_id == PROJECT,
            VaUserAccessGrants.role == VaAccessRoles.coder,
        ))
        grant.grant_status = VaStatuses.deactive
        db.session.commit()
        try:
            va_sid = response.get_json()["va_sid"]
            self.assertEqual(self._apply(va_sid)["applied"], 0)
            held = db.session.get(VaBundlePendingCoding, draft_id)
            self.assertEqual((held.status, held.code), ("rejected", "coding_grant_required"))
        finally:
            grant.grant_status = VaStatuses.active
            db.session.commit()

    def test_enrolled_coding_in_masked_project_is_refused_with_explicit_receipt(self):
        project = db.session.get(VaProjectMaster, PROJECT)
        project.masked_cod_required = True
        db.session.commit()
        try:
            client_uuid, headers = self._device(self.coder)
            response, draft_id = self._push_enrolled(headers, client_uuid)
            self.assertEqual(response.get_json()["offline_coding"], {"status": "refused", "code": "coding_mode_mismatch"})
            self.assertEqual(db.session.get(VaBundlePendingCoding, draft_id).code, "coding_mode_mismatch")
        finally:
            project.masked_cod_required = False
            db.session.commit()

    # ── consent ────────────────────────────────────────────────────────────

    def test_the_standalone_consent_snapshot_is_stored_once_and_never_served(self):
        client_uuid, headers = self._device(self.interviewer)
        draft_id = uuid.uuid4()
        consent = self._consent(draft_id)
        response, _ = self._push(headers, client_uuid, client_draft_id=draft_id, coding=False, consent=consent)
        self.assertEqual(response.status_code, 201, response.get_json())
        record = db.session.scalar(sa.select(VaConsentRecord).where(VaConsentRecord.client_draft_id == draft_id))
        self.assertIsNotNone(record)
        version = db.session.get(MasConsentNoticeVersion, record.notice_version_id)
        self.assertEqual((version.source, version.text, version.bundle_sha256),
                         ("standalone", consent["notice_text"], standalone_bundle_sha256()))
        self.assertEqual(record.notice_sha256, hashlib.sha256(consent["notice_text"].encode()).hexdigest())
        self.assertIn("narrative_automated_processing", {p.purpose_code for p in record.purposes})
        # Item 7 is honoured as answered (optional, refused here).
        item7 = next(p for p in record.purposes if p.purpose_code == "narrative_automated_processing")
        self.assertFalse(item7.granted)
        # A second interview with the same text reuses the version; neither is served.
        second_id = uuid.uuid4()
        again, _ = self._push(headers, client_uuid, client_draft_id=second_id, coding=False,
                              consent=self._consent(second_id))
        self.assertEqual(again.status_code, 201, again.get_json())
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(MasConsentNoticeVersion).where(
            MasConsentNoticeVersion.project_id == PROJECT, MasConsentNoticeVersion.source == "standalone")), 1)
        self.assertNotIn(version.notice_version_id,
                         {v.notice_version_id for v in consent_service.active_versions(PROJECT)})

    def test_a_consent_sha_mismatch_or_unknown_bundle_is_refused_and_nothing_stored(self):
        client_uuid, headers = self._device(self.interviewer)
        for kwargs in ({"sha": "0" * 64}, {"bundle": "f" * 64}):
            draft_id = uuid.uuid4()
            response, _ = self._push(headers, client_uuid, client_draft_id=draft_id, coding=False,
                                     consent=self._consent(draft_id, **kwargs))
            self.assertEqual((response.status_code, response.get_json()["code"]), (422, "consent_invalid"), kwargs)
            self.assertIsNone(self._draft(draft_id))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(MasConsentNoticeVersion).where(
            MasConsentNoticeVersion.source == "standalone", MasConsentNoticeVersion.project_id == PROJECT)), 0)

    # ── offline coding ─────────────────────────────────────────────────────

    def test_agreement_lands_coded_with_the_normal_recode_window(self):
        client_uuid, headers = self._device(self.coder)
        response, draft_id = self._push(headers, client_uuid)
        va_sid = response.get_json()["va_sid"]
        self.assertNotEqual(get_submission_workflow_state(va_sid), "ready_for_coding")
        # Not ready yet: still pending, nothing applied.
        self.assertEqual(bundle_ingest_service.apply_pending_coding()["applied"], 0)
        counts = self._apply(va_sid)
        held = db.session.get(VaBundlePendingCoding, draft_id)
        self.assertEqual(counts["applied"], 1, (counts, held.status, held.code))
        self.assertEqual(get_submission_workflow_state(va_sid), "coder_finalized")
        final = self._final(va_sid)
        self.assertEqual(final.va_finassess_by, self.coder.user_id)
        conclusive = final.icd11_provenance["conclusive"]
        self.assertEqual((conclusive["code"], conclusive["primary_stem"], conclusive["coding_origin"]),
                         (AGREEING_CODE, AGREEING_CODE, "collect_plus_offline"))
        self.assertNotIn("allowability_disagreement", conclusive)
        self.assertIsNone(conclusive["codeinfo_uri"])
        snapshot = final.cod_entry_mode_snapshot
        self.assertEqual(snapshot["coding_origin"], "collect_plus_offline")
        self.assertEqual(snapshot["offline"]["device_uuid"], client_uuid)
        self.assertEqual(snapshot["offline"]["profile_snapshot"]["name"], "Dr. Plus")
        self.assertEqual(final.doris_certificate["Part1"][0]["Conditions"][0]["Code"], AGREEING_CODE)
        self.assertEqual(self._audits(va_sid, "final cod imported from collect plus offline"),
                         ["final cod imported from collect plus offline"])
        self.assertEqual(self._audits(va_sid, "offline coding allowability disagreement"), [])
        again, _ = self._push(headers, client_uuid, client_draft_id=draft_id)
        self.assertEqual(again.get_json()["offline_coding"], {"status": "applied", "code": None})

    def test_coding_timeline_survives_the_pending_import_and_uses_server_final_save_time(self):
        client_uuid, headers = self._device(self.coder)
        answers_json, answers_sha = self._answers_json()
        coding = self._coding(client_uuid, answers_sha)
        coding["provenance"]["workflowTimelineV1"] = [
            {"event": "coding_opened", "at": "2026-10-28T09:00:00+05:30"},
            {"event": "doris_processed", "at": "2026-10-28T09:04:00+05:30", "elapsed_ms": 2000},
            {"event": "initial_saved", "at": "2026-10-28T09:05:00+05:30"},
        ]
        response, draft_id = self._push(
            headers, client_uuid, coding=False, offline_coding=coding,
            answers=json.loads(answers_json),
        )
        va_sid = response.get_json()["va_sid"]
        held = db.session.get(VaBundlePendingCoding, draft_id)
        self.assertEqual(
            held.result["coding"]["provenance"]["workflowTimelineV1"],
            coding["provenance"]["workflowTimelineV1"],
        )

        self.assertEqual(self._apply(va_sid)["applied"], 1)
        timeline = self._final(va_sid).cod_entry_mode_snapshot["offline"]["workflowTimelineV1"]
        self.assertEqual(timeline[:-1], coding["provenance"]["workflowTimelineV1"])
        self.assertEqual(timeline[-1]["event"], "final_saved")

    def test_disagreement_is_flagged_and_sent_to_reviewers_at_once(self):
        client_uuid, headers = self._device(self.coder)
        cases = (
            (MALE_ONLY_CODE, None, ["sex_conflict"]),
            (NEONATE_ONLY_CODE, None, ["age_unconfirmed"]),
        )
        for code, confirmation, flags in cases:
            response, _ = self._push(headers, client_uuid, code=code, confirmation=confirmation)
            va_sid = response.get_json()["va_sid"]
            self.assertEqual(self._apply(va_sid)["applied"], 1, code)
            self.assertEqual(get_submission_workflow_state(va_sid), "reviewer_eligible", code)
            conclusive = self._final(va_sid).icd11_provenance["conclusive"]
            self.assertEqual(conclusive["allowability_disagreement"], flags)
            self.assertEqual(self._audits(va_sid, "offline coding allowability disagreement"),
                             [f"offline coding allowability disagreement: {flags[0]}"])

    def test_an_age_conflict_the_coder_confirmed_on_the_phone_agrees(self):
        client_uuid, headers = self._device(self.coder)
        confirmation = {"confirmed_by": str(self.coder.user_id), "confirmed_at": datetime.now(UTC).isoformat(),
                        "code": NEONATE_ONLY_CODE, "age_group_selectable": "neonate", "restriction_note": None,
                        "doris_warning": None}
        response, _ = self._push(headers, client_uuid, code=NEONATE_ONLY_CODE, confirmation=confirmation)
        va_sid = response.get_json()["va_sid"]
        self.assertEqual(self._apply(va_sid)["applied"], 1)
        self.assertEqual(get_submission_workflow_state(va_sid), "coder_finalized")
        conclusive = self._final(va_sid).icd11_provenance["conclusive"]
        self.assertNotIn("allowability_disagreement", conclusive)
        self.assertEqual(conclusive["age_restriction_confirmation"]["code"], NEONATE_ONLY_CODE)

    def test_an_account_without_a_coding_grant_gets_the_interview_and_not_the_coding(self):
        client_uuid, headers = self._device(self.interviewer)
        response, draft_id = self._push(headers, client_uuid)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["offline_coding"], {"status": "refused", "code": "coding_grant_required"})
        va_sid = response.get_json()["va_sid"]
        self.assertIsNotNone(db.session.get(VaSubmissions, va_sid))
        self.assertEqual(self._audits(va_sid, "offline coding refused"),
                         ["offline coding refused (coding_grant_required)"])
        self.assertEqual(self._apply(va_sid)["applied"], 0)
        # The case is in the normal coding queue, uncoded.
        self.assertEqual(get_submission_workflow_state(va_sid), "ready_for_coding")
        self.assertIsNone(self._final(va_sid))
        self.assertEqual(db.session.get(VaBundlePendingCoding, draft_id).status, "rejected")

    def test_a_later_version_with_its_own_coding_replaces_the_pending_coding(self):
        client_uuid, headers = self._device(self.coder)
        first, draft_id = self._push(headers, client_uuid)
        self.assertEqual(first.get_json()["offline_coding"]["status"], "pending")
        edited = {**_answers(), "Id10018": "Sahoo"}
        second, _ = self._push(headers, client_uuid, client_draft_id=draft_id, answers=edited, code=OTHER_CODE)
        self.assertEqual(second.status_code, 200, second.get_json())
        self.assertEqual(second.get_json()["offline_coding"], {"status": "pending", "code": "not_ready"})
        va_sid = first.get_json()["va_sid"]
        self.assertEqual(self._apply(va_sid)["applied"], 1)
        self.assertEqual(self._final(va_sid).icd11_provenance["conclusive"]["code"], OTHER_CODE)
        # A later version whose coding is of other answers: the pending one is refused now.
        _third, other_id = self._push(headers, client_uuid)
        stale = self._coding(client_uuid, "d" * 64)
        again, _ = self._push(headers, client_uuid, client_draft_id=other_id, answers={**_answers(), "Id10018": "X"},
                              coding=False, offline_coding=stale)
        self.assertEqual(again.get_json()["offline_coding"], {"status": "refused", "code": "coded_version_superseded"})

    def test_stale_coding_is_not_applied(self):
        client_uuid, headers = self._device(self.coder)
        _json, sha = self._answers_json()
        stale = self._coding(client_uuid, "d" * 64)
        response, _ = self._push(headers, client_uuid, coding=False, offline_coding=stale)
        self.assertEqual(response.get_json()["offline_coding"], {"status": "refused", "code": "coded_version_superseded"})
        self.assertNotEqual(sha, "d" * 64)

    def test_malformed_offline_coding_refuses_the_whole_push(self):
        client_uuid, headers = self._device(self.coder)
        bad = self._coding(client_uuid, "e" * 64)
        bad["conclusive_cod"] = "XX99 not the antecedent"
        response, draft_id = self._push(headers, client_uuid, coding=False, offline_coding=bad)
        self.assertEqual((response.status_code, response.get_json()["code"]), (422, "offline_coding_invalid"))
        self.assertIsNone(self._draft(draft_id))
