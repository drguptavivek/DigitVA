"""Respondent DPDP consent (digitva-gb8w.3): GET /api/v1/intake/consent-config,
the ``consent`` object on POST /intake/deaths and /intake/submissions, the
consent_required / consent_invalid / consent_conflict refusals, the
configuration API and the append-only record table.

Contract: docs/policy/offline-api-contract.md section 5.
"""
import hashlib
import json
import uuid
from unittest.mock import patch
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from app import db, limiter
from app.models import (
    MapConsentAudit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaConsentRecord,
    VaDeathRegister,
    VaForms,
    VaWebIntakeDraft,
    VaSubmissions,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import consent_service, web_intake_service
from app.services import device_auth_service as devices
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase
from tests.routes.test_device_api import _FreshGClient

INTAKE = "/api/v1/intake"
NOTICE_TEXT = "Consent notice v1. **Required**: record the death.\nOptional: messages."
PURPOSES = [
    {"code": "messages", "label": "Messages", "required": False},
    {"code": "record_interview", "label": "Record the interview", "required": True},
]


def _answers(**extra):
    return {
        "Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "Id10019": "female",
        "Id10023": (date.today() - timedelta(days=5)).isoformat(), "finalAgeInYears": "71",
        "narr_language": "english", **extra,
    }


class ConsentApiTests(BaseTestCase):
    REQUIRED = "CNS01"   # consent required, one notice version
    PLAIN = "CNS02"      # no consent settings: today's behaviour
    SITE_REQ = "CS01"
    SITE_PLAIN = "CS02"

    @classmethod
    def _project(cls, project_id, site_id, now):
        db.session.add(VaProjectMaster(
            project_id=project_id, project_code=project_id, project_name=f"Consent {project_id}",
            project_nickname=project_id, project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=site_id, site_name=f"Site {site_id}", site_abbr=site_id,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=project_id, site_id=site_id, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(project_id, site_id)
        db.session.add(VaForms(
            form_id=f"{project_id}{site_id}01", project_id=project_id, site_id=site_id,
            odk_form_id=f"ODK_{project_id}", odk_project_id="7", form_type="WHO VA 2022",
            form_source="odk", form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()

    @classmethod
    def _grant(cls, user, project_id, role=VaAccessRoles.interviewer):
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
            project_id=project_id, notes="consent test grant", grant_status=VaStatuses.active,
        ))
        db.session.flush()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._project(cls.REQUIRED, cls.SITE_REQ, now)
        cls._project(cls.PLAIN, cls.SITE_PLAIN, now)
        cls.interviewer = cls._get_or_make_user("consent.interviewer@test.local", "Consent123!")
        cls.outsider = cls._get_or_make_user("consent.outsider@test.local", "Consent123!")
        cls.manager = cls._get_or_make_user("consent.dm@test.local", "Consent123!")
        cls._grant(cls.interviewer, cls.REQUIRED)
        cls._grant(cls.interviewer, cls.PLAIN)
        cls._grant(cls.outsider, cls.PLAIN)
        cls._grant(cls.manager, cls.REQUIRED, VaAccessRoles.data_manager)
        cls.notice = consent_service.create_notice_version(cls.base_admin_user, cls.REQUIRED, {
            "language": "en", "text": NOTICE_TEXT, "purposes": PURPOSES,
            "allowed_modes": ["spoken", "tap"], "witness_allowed": False,
        })
        consent_service.save_settings(cls.base_admin_user, cls.REQUIRED, {"consent_required": True})
        db.session.commit()
        cls.interviewer_id = str(cls.interviewer.user_id)

    def setUp(self):
        super().setUp()
        limiter.reset()
        self._login(self.interviewer_id)

    # ── helpers ────────────────────────────────────────────────────────────

    def _consent(self, *, decision="granted", client_draft_id=None, **overrides):
        body = {
            "client_id": str(uuid.uuid4()),
            "client_draft_id": str(client_draft_id) if client_draft_id else None,
            "notice_version_id": str(self.notice.notice_version_id),
            "notice_language": "en",
            "notice_sha256": hashlib.sha256(NOTICE_TEXT.encode("utf-8")).hexdigest(),
            "decision": decision,
            "purposes": [{"code": "messages", "granted": False},
                         {"code": "record_interview", "granted": decision == "granted"}],
            "mode": "spoken",
            "witness_present": False,
            "supersedes_client_id": None,
            "recorded_at": "2026-10-21T10:00:00+05:30",
        }
        body.update(overrides)
        return body

    def _register(self, project_id=None, **fields):
        project_id = project_id or self.REQUIRED
        site_id = self.SITE_REQ if project_id == self.REQUIRED else self.SITE_PLAIN
        body = {
            "project_id": project_id, "site_id": site_id, "deceased_name": "Bina Sahu",
            "deceased_sex": "female", "date_of_death": (date.today() - timedelta(days=5)).isoformat(),
            "age_years": 71, **fields,
        }
        return self.client.post(f"{INTAKE}/deaths", json=body, headers=self._csrf_headers())

    def _upload(self, death_id, answers, *, client_draft_id=None, project_id=None, **extra):
        project_id = project_id or self.REQUIRED
        answers_json = json.dumps(answers, separators=(",", ":"))
        body = {
            "client_draft_id": str(client_draft_id or uuid.uuid4()),
            "project_id": project_id,
            "site_id": self.SITE_REQ if project_id == self.REQUIRED else self.SITE_PLAIN,
            "death_id": death_id,
            "draft": {"instrumentVersion": "2023072701"},
            "completion": {"valid": True, "issues": []},
            "answers_json": answers_json,
            "answers_sha256": hashlib.sha256(answers_json.encode()).hexdigest(),
            **extra,
        }
        return self.client.post(f"{INTAKE}/submissions", json=body, headers=self._csrf_headers())

    def _records(self, death_id=None):
        stmt = sa.select(VaConsentRecord)
        if death_id:
            stmt = stmt.where(VaConsentRecord.death_id == uuid.UUID(death_id))
        return list(db.session.scalars(stmt))

    def _refusal(self, response, status, code):
        body = response.get_json()
        self.assertEqual((response.status_code, body["code"]), (status, code), body)
        self.assertNotIn("reason", body)
        return body

    # ── GET /intake/consent-config ─────────────────────────────────────────

    def test_config_of_a_project_requiring_consent(self):
        response = self.client.get(f"{INTAKE}/consent-config", query_string={"project_id": self.REQUIRED})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        body = response.get_json()
        self.assertEqual(set(body), {"project_id", "consent_required", "notice_versions", "contacts",
                                     "retention", "refusal_behaviour"})
        self.assertTrue(body["consent_required"])
        [version] = body["notice_versions"]
        self.assertEqual(version["text"], NOTICE_TEXT)
        self.assertEqual(version["text_sha256"], hashlib.sha256(NOTICE_TEXT.encode()).hexdigest())
        self.assertEqual(version["version"], 1)
        self.assertEqual([p["code"] for p in version["purposes"]], ["messages", "record_interview"])
        self.assertIn("informant_phone", version["covered_fields"])
        self.assertIn("Id10007", version["covered_fields"])
        self.assertEqual(version["allowed_modes"], ["spoken", "tap"])
        self.assertFalse(version["witness_allowed"])
        self.assertEqual(body["refusal_behaviour"], "interview_without_informant_data")

    def test_config_of_a_project_without_settings_is_not_required(self):
        response = self.client.get(f"{INTAKE}/consent-config", query_string={"project_id": self.PLAIN})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["project_id"], self.PLAIN)
        self.assertFalse(body["consent_required"])
        self.assertEqual(body["notice_versions"], [])
        self.assertEqual(body["contacts"]["districts"], {})
        self.assertIsNone(body["contacts"]["dpo"])
        self.assertEqual(body["retention"], {"period_days": None, "expiry_action": "erase"})

    def test_config_answers_a_device_bearer(self):
        client = _FreshGClient(self.app, self.app.response_class, use_cookies=False)
        _row, code = devices.create_enrolment_code(self.REQUIRED, actor=self.base_admin_user)
        db.session.commit()
        device = client.post("/api/v1/auth/enroll", json={
            "code": code, "device_name": "Station 1", "platform": "android", "app_version": "0.1.0"}).get_json()
        tokens = client.post("/api/v1/auth/sessions", json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "email": "consent.interviewer@test.local", "password": "Consent123!"}).get_json()
        response = client.get(f"{INTAKE}/consent-config", query_string={"project_id": self.REQUIRED},
                              headers={"Authorization": f"Bearer {tokens['access_token']}"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["consent_required"])

    def test_config_requires_project_id_and_access(self):
        self._refusal(self.client.get(f"{INTAKE}/consent-config"), 400, "invalid_request")
        self._login(str(self.outsider.user_id))
        self.assertEqual(
            self.client.get(f"{INTAKE}/consent-config", query_string={"project_id": self.PLAIN}).status_code, 200)
        response = self.client.get(f"{INTAKE}/consent-config", query_string={"project_id": self.REQUIRED})
        self._refusal(response, 403, "project_forbidden")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    # ── registration (contract 5.4) ────────────────────────────────────────

    def test_registration_with_informant_fields_needs_a_granted_consent(self):
        body = self._refusal(self._register(informant_name="Ram", informant_phone="9876543210"),
                             422, "consent_required")
        self.assertEqual(body["fields"], ["consent"])
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister)
                                           .where(VaDeathRegister.project_id == self.REQUIRED)), 0)

        consent = self._consent()
        response = self._register(informant_name="Ram", informant_phone="9876543210", consent=consent)
        self.assertEqual(response.status_code, 201, response.get_json())
        death_id = response.get_json()["case"]["death_id"]
        [record] = self._records(death_id)
        self.assertEqual(record.event, "granted")
        self.assertIsNone(record.client_draft_id)
        self.assertEqual(record.client_consent_id, uuid.UUID(consent["client_id"]))
        self.assertEqual(record.notice_sha256, self.notice.text_sha256)
        self.assertEqual(record.channel, "web")
        self.assertEqual({(p.purpose_code, p.required, p.granted) for p in record.purposes},
                         {("messages", False, False), ("record_interview", True, True)})

    def test_registration_without_informant_fields_needs_no_consent(self):
        response = self._register()
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(self._records(response.get_json()["case"]["death_id"]), [])

    def test_refused_consent_with_informant_fields_is_a_conflict(self):
        self._refusal(self._register(informant_name="Ram", consent=self._consent(decision="refused")),
                      422, "consent_refused")
        self.assertEqual(self._records(), [])
        self._refusal(self._register(consent=self._consent(decision="refused")), 422, "consent_refused")

    def test_project_without_consent_settings_registers_as_today(self):
        response = self._register(self.PLAIN, informant_name="Ram", informant_phone="9876543210")
        self.assertEqual(response.status_code, 201, response.get_json())
        death = db.session.get(VaDeathRegister, uuid.UUID(response.get_json()["case"]["death_id"]))
        self.assertEqual(death.informant_name, "Ram")
        self.assertEqual(self._records(), [])

    # ── record_consent validation (contract 5.3) ───────────────────────────

    def test_invalid_consents_are_refused(self):
        sha = hashlib.sha256(NOTICE_TEXT.encode()).hexdigest()
        cases = {
            "hash mismatch": {"notice_sha256": "0" * 64},
            "unknown version": {"notice_version_id": str(uuid.uuid4())},
            "language": {"notice_language": "hi"},
            "missing purpose": {"purposes": [{"code": "record_interview", "granted": True}]},
            "extra purpose": {"purposes": [{"code": "messages", "granted": False},
                                           {"code": "record_interview", "granted": True},
                                           {"code": "other", "granted": True}]},
            "granted without required": {"purposes": [{"code": "messages", "granted": True},
                                                      {"code": "record_interview", "granted": False}]},
            "mode": {"mode": "signed"},
            "witness": {"witness_present": True},
            "draft id at registration": {"client_draft_id": str(uuid.uuid4())},
            "unknown key": {"witness_name": "X"},
            "no offset": {"recorded_at": "2026-10-21T10:00:00"},
        }
        for label, overrides in cases.items():
            with self.subTest(label):
                body = self._refusal(self._register(informant_name="Ram", consent=self._consent(**overrides)),
                                     422, "consent_invalid")
                self.assertEqual(body["fields"], ["consent"])
                self.assertNotIn(sha, json.dumps(body))
        self.assertEqual(self._records(), [])

    def test_a_notice_version_of_another_project_is_invalid(self):
        other = consent_service.create_notice_version(self.base_admin_user, self.PLAIN, {
            "language": "en", "text": NOTICE_TEXT, "purposes": PURPOSES, "allowed_modes": ["spoken"],
        })
        db.session.commit()
        self.assertIsNotNone(other.notice_version_id)
        self._refusal(self._register(informant_name="Ram",
                                     consent=self._consent(notice_version_id=str(other.notice_version_id))),
                      422, "consent_invalid")

    def test_record_consent_is_idempotent_on_client_id(self):
        death = self._register().get_json()["case"]
        case = db.session.get(VaDeathRegister, uuid.UUID(death["death_id"]))
        consent = self._consent()
        first, created = consent_service.record_consent(
            self.interviewer, project_id=self.REQUIRED, death=case, consent=consent,
            client_draft_id=None, channel="bundle")
        self.assertTrue(created)
        again, created = consent_service.record_consent(
            self.interviewer, project_id=self.REQUIRED, death=case, consent=dict(consent),
            client_draft_id=None, channel="bundle")
        self.assertFalse(created)
        self.assertEqual(again.consent_id, first.consent_id)
        with self.assertRaises(consent_service.ConsentError) as raised:
            consent_service.record_consent(
                self.interviewer, project_id=self.REQUIRED, death=case,
                consent={**consent, "mode": "tap"}, client_draft_id=None, channel="bundle")
        self.assertEqual((raised.exception.code, raised.exception.status_code), ("conflict", 409))
        self.assertEqual(len(self._records(death["death_id"])), 1)

    def test_a_reused_consent_id_with_other_content_is_409_on_https(self):
        consent = self._consent()
        self.assertEqual(self._register(informant_name="Ram", consent=consent).status_code, 201)
        response = self._register(informant_name="Shyam", consent=consent)
        self._refusal(response, 409, "conflict")

    def test_a_correction_names_the_consent_it_supersedes(self):
        first = self._consent()
        death_id = self._register(informant_name="Ram", consent=first).get_json()["case"]["death_id"]
        case = db.session.get(VaDeathRegister, uuid.UUID(death_id))
        record, _ = consent_service.record_consent(
            self.interviewer, project_id=self.REQUIRED, death=case,
            consent=self._consent(supersedes_client_id=first["client_id"]), client_draft_id=None, channel="web")
        original = next(r for r in self._records(death_id) if r.client_consent_id == uuid.UUID(first["client_id"]))
        self.assertEqual(record.supersedes_consent_id, original.consent_id)
        with self.assertRaises(consent_service.ConsentError):
            consent_service.record_consent(
                self.interviewer, project_id=self.REQUIRED, death=case,
                consent=self._consent(supersedes_client_id=str(uuid.uuid4())), client_draft_id=None, channel="web")

    def test_records_are_append_only(self):
        death_id = self._register(informant_name="Ram", consent=self._consent()).get_json()["case"]["death_id"]
        [record] = self._records(death_id)
        self.assertEqual(record.event, "granted")
        with self.assertRaises(DBAPIError) as raised:
            with db.session.begin_nested():
                db.session.execute(sa.update(VaConsentRecord)
                                   .where(VaConsentRecord.consent_id == record.consent_id)
                                   .values(event="refused"))
        self.assertIn("append-only", str(raised.exception))
        db.session.expire_all()
        self.assertEqual(db.session.get(VaConsentRecord, record.consent_id).event, "granted")
        self.assertFalse(any(name.startswith(("update_", "delete_")) for name in dir(consent_service)))

    # ── submissions (contract 5.3, 5.4) ────────────────────────────────────

    def test_the_interview_reuses_the_registration_consent(self):
        registration = self._consent()
        death_id = self._register(informant_name="Ram", consent=registration).get_json()["case"]["death_id"]
        # The registration consent resent as the attempt's own names no attempt.
        self._refusal(self._upload(death_id, _answers(Id10007="Ram"), consent=registration),
                      422, "consent_invalid")
        response = self._upload(death_id, _answers(Id10007="Ram"))
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(len(self._records(death_id)), 1)

    def test_covered_answers_without_any_consent_are_refused(self):
        death_id = self._register().get_json()["case"]["death_id"]
        body = self._refusal(self._upload(death_id, _answers(Id10007="Ram")), 422, "consent_required")
        self.assertEqual(body["fields"], ["consent"])
        # Without covered answers the upload goes through as today.
        self.assertEqual(self._upload(death_id, _answers()).status_code, 201)

    def test_a_different_informant_gives_consent_for_the_attempt(self):
        death_id = self._register(informant_name="Ram", consent=self._consent()).get_json()["case"]["death_id"]
        attempt = uuid.uuid4()
        # The consent must name this attempt.
        self._refusal(self._upload(death_id, _answers(Id10007="Sita"), client_draft_id=attempt,
                                   consent=self._consent(client_draft_id=uuid.uuid4())), 422, "consent_invalid")
        response = self._upload(death_id, _answers(Id10007="Sita"), client_draft_id=attempt,
                                consent=self._consent(client_draft_id=attempt))
        self.assertEqual(response.status_code, 201, response.get_json())
        drafts = {r.client_draft_id for r in self._records(death_id)}
        self.assertEqual(drafts, {None, attempt})

    def test_refused_attempt_consent_with_covered_answers_is_a_conflict(self):
        death_id = self._register(informant_name="Ram", consent=self._consent()).get_json()["case"]["death_id"]
        attempt = uuid.uuid4()
        self._refusal(self._upload(death_id, _answers(Id10007="Sita"), client_draft_id=attempt,
                                   consent=self._consent(decision="refused", client_draft_id=attempt)),
                      422, "consent_refused")
        response = self._upload(death_id, {"refusal_sex": "female"}, client_draft_id=attempt,
                                consent=self._consent(decision="refused", client_draft_id=attempt))
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertIn("refused", {r.event for r in self._records(death_id)})

    def _sync_draft(self, death_id, answers, project_id=None, client_draft_id=None):
        project_id = project_id or self.REQUIRED
        now = datetime.now(UTC).isoformat()
        answers_json = json.dumps(answers, separators=(",", ":"))
        return self.client.post(f"{INTAKE}/drafts/sync", json={
            "project_id": project_id, "site_id": self.SITE_REQ if project_id == self.REQUIRED else self.SITE_PLAIN,
            "death_id": death_id, "client_draft_id": str(client_draft_id or uuid.uuid4()),
            "draft": {"currentSection": "consented"},
            "answers_json": answers_json, "answers_sha256": hashlib.sha256(answers_json.encode()).hexdigest(),
            "savedAt": now, "deviceClockAt": now, "base_updated_at": None,
        }, headers=self._csrf_headers())

    def _synced_answers(self, death_id):
        draft = db.session.scalars(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.death_id == uuid.UUID(death_id), VaWebIntakeDraft.status == "draft")).one()
        db.session.refresh(draft)
        return {k: v for sec in draft.sections for k, v in sec.data.items()}

    def test_draft_sync_drops_covered_answers_without_a_granted_consent_on_file(self):
        # The submit path refuses these (422 consent_required); an in-progress save is stripped instead, so a
        # phone saving before its consent is uploaded is not refused and no covered data is stored.
        death_id = self._register().get_json()["case"]["death_id"]
        response = self._sync_draft(death_id, _answers(Id10007="Ram", Id10061="Hari"))
        self.assertEqual(response.status_code, 200, response.get_json())
        stored = self._synced_answers(death_id)
        self.assertEqual(stored["Id10017"], "Bina")  # present: the rest of the answers are kept
        self.assertNotIn("Id10007", stored)
        self.assertNotIn("Id10061", stored)

    def test_draft_sync_keeps_covered_answers_under_a_granted_registration_consent(self):
        death_id = self._register(informant_name="Ram", consent=self._consent()).get_json()["case"]["death_id"]
        self.assertEqual(self._sync_draft(death_id, _answers(Id10007="Ram")).status_code, 200)
        self.assertEqual(self._synced_answers(death_id)["Id10007"], "Ram")

    def test_draft_sync_drops_covered_answers_under_a_refused_registration_consent(self):
        death_id = self._register().get_json()["case"]["death_id"]
        consent_service.record_consent(self.interviewer, project_id=self.REQUIRED, death=self._death(death_id),
                                      consent=self._consent(decision="refused"), client_draft_id=None, channel="web")
        db.session.commit()
        self.assertEqual(self._sync_draft(death_id, _answers(Id10007="Ram")).status_code, 200)
        stored = self._synced_answers(death_id)
        self.assertEqual(stored, {"Id10013": "yes"})

    def test_a_stripped_sync_is_stored_in_full_when_resent_after_consent(self):
        death_id = self._register().get_json()["case"]["death_id"]
        attempt = uuid.uuid4()
        answers = _answers(Id10007="Ram")
        self.assertEqual(self._sync_draft(death_id, answers, client_draft_id=attempt).status_code, 200)
        stored = self._synced_answers(death_id)
        self.assertEqual(stored["Id10017"], "Bina")
        self.assertNotIn("Id10007", stored)
        # The consent reaches the server later (the final upload's, or the registration's) ...
        consent_service.record_consent(
            self.interviewer, project_id=self.REQUIRED, death=self._death(death_id),
            consent=self._consent(), client_draft_id=None, channel="device")
        db.session.commit()
        # ... and the same save sent again is no no-op: it is stored in full and the flag clears.
        self.assertEqual(self._sync_draft(death_id, answers, client_draft_id=attempt).status_code, 200)
        self.assertEqual(self._synced_answers(death_id)["Id10007"], "Ram")
        draft = db.session.scalars(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.death_id == uuid.UUID(death_id), VaWebIntakeDraft.status == "draft")).one()
        self.assertNotIn("stripped", draft.meta["lastSync"])

    def test_a_partial_consent_drops_only_the_fields_it_does_not_cover(self):
        consent_service.create_notice_version(self.base_admin_user, self.REQUIRED, {
            "language": "en", "text": "Notice v2", "purposes": PURPOSES, "allowed_modes": ["spoken"],
            "covered_fields": [*consent_service.DEFAULT_COVERED_FIELDS, "Id10008"],
        })
        db.session.commit()
        # The v1 consent on file covers Id10007 but not the v2-only Id10008.
        death_id = self._register(informant_name="Ram", consent=self._consent()).get_json()["case"]["death_id"]
        self.assertEqual(self._sync_draft(death_id, _answers(Id10007="Ram", Id10008="parent")).status_code, 200)
        stored = self._synced_answers(death_id)
        self.assertEqual(stored["Id10007"], "Ram")
        self.assertNotIn("Id10008", stored)

    def test_draft_sync_in_a_project_without_consent_settings_keeps_everything(self):
        death_id = self._register(self.PLAIN).get_json()["case"]["death_id"]
        self.assertEqual(self._sync_draft(death_id, _answers(Id10007="Ram"), self.PLAIN).status_code, 200)
        self.assertEqual(self._synced_answers(death_id)["Id10007"], "Ram")

    def test_project_without_consent_settings_uploads_as_today(self):
        death_id = self._register(self.PLAIN, informant_name="Ram").get_json()["case"]["death_id"]
        response = self._upload(death_id, _answers(Id10007="Ram"), project_id=self.PLAIN)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(self._records(), [])

    def test_browser_posts_need_the_csrf_header(self):
        response = self.client.post(f"{INTAKE}/deaths", json={
            "project_id": self.REQUIRED, "site_id": self.SITE_REQ, "deceased_name": "X",
            "deceased_sex": "female", "date_of_death": date.today().isoformat(), "age_years": 1,
            "informant_name": "Ram", "consent": self._consent(),
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._records(), [])

    # ── configuration API ──────────────────────────────────────────────────

    def test_a_project_data_manager_configures_consent_with_audit(self):
        self._login(str(self.manager.user_id))
        url = f"/api/v1/projects/{self.REQUIRED}"
        self.assertEqual(self.client.post(f"{url}/consent-notices", json={}).status_code, 400)  # no CSRF
        response = self.client.post(f"{url}/consent-notices", headers=self._csrf_headers(), json={
            "language": "hi", "version": 1, "text": "Hindi notice", "purposes": PURPOSES,
            "allowed_modes": ["tap"],
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["notice_version"]["text_sha256"],
                         hashlib.sha256(b"Hindi notice").hexdigest())
        again = self.client.post(f"{url}/consent-notices", headers=self._csrf_headers(), json={
            "language": "hi", "version": 1, "text": "Other", "purposes": PURPOSES, "allowed_modes": ["tap"],
        })
        self._refusal(again, 409, "conflict")

        response = self.client.put(f"{url}/consent-settings", headers=self._csrf_headers(), json={
            "retention": {"period_days": 1825, "expiry_action": "lock"},
            "contacts": {"central_team": {"email": "central@example.org", "phone": "0110000000"}},
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual(body["retention"], {"period_days": 1825, "expiry_action": "lock"})
        self.assertEqual(body["contacts"]["central_team"]["email"], "central@example.org")
        self.assertEqual(body["contacts"]["deletion"], {"email": "", "phone": ""})
        events = set(db.session.scalars(sa.select(MapConsentAudit.event)
                                        .where(MapConsentAudit.project_id == self.REQUIRED)))
        self.assertTrue({"consent_notice_created", "consent_settings_saved"} <= events)

    def test_requiring_consent_needs_a_notice_version(self):
        self._login(self.base_admin_id)
        response = self.client.put(f"/api/v1/projects/{self.PLAIN}/consent-settings",
                                   headers=self._csrf_headers(), json={"consent_required": True})
        body = self._refusal(response, 400, "invalid_request")
        self.assertEqual(body["fields"], ["consent_required"])

    def test_an_interviewer_cannot_configure_consent(self):
        response = self.client.put(f"/api/v1/projects/{self.REQUIRED}/consent-settings",
                                   headers=self._csrf_headers(), json={"consent_required": False})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(consent_service.get_settings(self.REQUIRED).consent_required)

    # ── the gate on every write path (PATCH, revisions, browser submit) ────

    def _patch(self, death_id, **body):
        return self.client.patch(f"{INTAKE}/deaths/{death_id}", json=body, headers=self._csrf_headers())

    def _death(self, death_id):
        db.session.expire_all()
        return db.session.get(VaDeathRegister, uuid.UUID(death_id))

    def _revise(self, va_sid, answers, **extra):
        answers_json = json.dumps(answers, separators=(",", ":"))
        return self.client.post(f"{INTAKE}/submissions/{va_sid}/revisions", headers=self._csrf_headers(), json={
            "reason_code": "interviewer_correction", "draft": {}, "completion": {"valid": True, "issues": []},
            "answers_json": answers_json, "answers_sha256": hashlib.sha256(answers_json.encode()).hexdigest(),
            **extra,
        })

    def _submit_draft(self, death_id, answers, project_id=None):
        project_id = project_id or self.REQUIRED
        site_id = self.SITE_REQ if project_id == self.REQUIRED else self.SITE_PLAIN
        started = self.client.post(f"{INTAKE}/drafts", headers=self._csrf_headers(), json={
            "project_id": project_id, "site_id": site_id, "death_id": death_id})
        self.assertEqual(started.status_code, 201, started.get_json())
        draft_id = started.get_json()["draft"]["draft_id"]
        return self.client.post(f"{INTAKE}/drafts/{draft_id}/submit", headers=self._csrf_headers(), json={
            "completion": {"valid": True, "issues": [], "data": answers}})

    # ── PATCH /intake/deaths/<id> (contract 5.5) ──────────────────────────

    def test_patch_adding_informant_fields_needs_a_granted_consent(self):
        death_id = self._register().get_json()["case"]["death_id"]
        body = self._refusal(self._patch(death_id, informant_name="Ram"), 422, "consent_required")
        self.assertEqual(body["fields"], ["consent"])
        self.assertIsNone(self._death(death_id).informant_name)

        response = self._patch(death_id, informant_name="Ram", consent=self._consent())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._death(death_id).informant_name, "Ram")
        [record] = self._records(death_id)
        self.assertEqual((record.event, record.client_draft_id), ("granted", None))
        # The registration consent is now on file: a later patch needs none.
        response = self._patch(death_id, informant_phone="9876543210")
        self.assertEqual(response.status_code, 200, response.get_json())
        # A patch of no covered field never needed one.
        self.assertEqual(self._patch(death_id, remarks="visited").status_code, 200)

    def test_patch_after_a_refused_registration_consent_is_a_conflict(self):
        refused = self._consent(decision="refused")
        death_id = self._register().get_json()["case"]["death_id"]
        consent_service.record_consent(self.interviewer, project_id=self.REQUIRED, death=self._death(death_id),
                                      consent=refused, client_draft_id=None, channel="web")
        db.session.commit()
        self._refusal(self._patch(death_id, informant_name="Ram"), 422, "consent_refused")
        self.assertIsNone(self._death(death_id).informant_name)
        # A new granted consent that corrects the refusal lets it through.
        response = self._patch(death_id, informant_name="Ram",
                               consent=self._consent(supersedes_client_id=refused["client_id"]))
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._death(death_id).informant_name, "Ram")

    def test_patch_in_a_project_without_settings_is_as_today(self):
        death_id = self._register(self.PLAIN).get_json()["case"]["death_id"]
        response = self._patch(death_id, informant_name="Ram")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._death(death_id).informant_name, "Ram")
        self.assertEqual(self._records(), [])

    # ── POST /intake/submissions/<va_sid>/revisions ────────────────────────

    def test_a_revision_adding_covered_answers_needs_a_consent(self):
        death_id = self._register().get_json()["case"]["death_id"]
        attempt = uuid.uuid4()
        uploaded = self._upload(death_id, _answers(), client_draft_id=attempt)
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
        va_sid = uploaded.get_json()["va_sid"]
        self.assertIsNotNone(va_sid)

        self._refusal(self._revise(va_sid, _answers(Id10007="Ram")), 422, "consent_required")
        response = self._revise(va_sid, _answers(Id10007="Ram"), consent=self._consent(client_draft_id=attempt))
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual({r.client_draft_id for r in self._records(death_id)}, {attempt})

    def test_a_revision_under_a_refused_consent_must_scrub_covered_answers(self):
        death_id = self._register(informant_name="Ram", consent=self._consent()).get_json()["case"]["death_id"]
        attempt = uuid.uuid4()
        uploaded = self._upload(death_id, _answers(Id10007="Sita"), client_draft_id=attempt,
                                consent=self._consent(client_draft_id=attempt))
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
        va_sid = uploaded.get_json()["va_sid"]
        refusal = self._consent(decision="refused", client_draft_id=attempt)
        self._refusal(self._revise(va_sid, _answers(Id10007="Sita"), consent=refusal), 422, "consent_refused")
        self._refusal(self._revise(va_sid, {}, consent=refusal), 422, "consent_refused")

    # ── POST /intake/drafts/<id>/submit (browser) ──────────────────────────

    def test_a_browser_submit_of_covered_answers_needs_a_consent_on_file(self):
        death_id = self._register().get_json()["case"]["death_id"]
        body = self._refusal(self._submit_draft(death_id, _answers(Id10007="Ram")), 422, "consent_required")
        self.assertEqual(body["fields"], ["consent"])
        self.assertIn("consent", body["error"])
        self.assertIsNone(self._death(death_id).va_sid)

        consented = self._register(informant_name="Ram", consent=self._consent()).get_json()["case"]["death_id"]
        response = self._submit_draft(consented, _answers(Id10007="Ram"))
        self.assertEqual(response.status_code, 201, response.get_json())

    def test_a_browser_submit_without_covered_answers_is_as_today(self):
        death_id = self._register().get_json()["case"]["death_id"]
        response = self._submit_draft(death_id, _answers())
        self.assertEqual(response.status_code, 201, response.get_json())
        plain = self._register(self.PLAIN).get_json()["case"]["death_id"]
        response = self._submit_draft(plain, _answers(Id10007="Ram"), project_id=self.PLAIN)
        self.assertEqual(response.status_code, 201, response.get_json())

    # ── covered fields ─────────────────────────────────────────────────────

    def test_default_covered_fields_include_the_prefilled_family_answers(self):
        self.assertTrue({"Id10055", "Id10057", "Id10061", "Id10062"} <= set(self.notice.covered_fields))
        death_id = self._register().get_json()["case"]["death_id"]
        for name in ("Id10055", "Id10057", "Id10061", "Id10062"):
            with self.subTest(name):
                self._refusal(self._upload(death_id, _answers(**{name: "Some value"})), 422, "consent_required")

    def test_a_consent_must_cover_every_filled_field(self):
        v2 = consent_service.create_notice_version(self.base_admin_user, self.REQUIRED, {
            "language": "en", "text": "Notice v2", "purposes": PURPOSES, "allowed_modes": ["spoken"],
            "covered_fields": [*consent_service.DEFAULT_COVERED_FIELDS, "Id10008"],
        })
        db.session.commit()
        self.assertEqual(v2.version, 2)
        # A v1 consent on file does not cover the v2-only field.
        death_id = self._register(informant_name="Ram", consent=self._consent()).get_json()["case"]["death_id"]
        body = self._refusal(self._upload(death_id, _answers(Id10007="Ram", Id10008="parent")),
                             422, "consent_invalid")
        self.assertEqual(body["fields"], ["Id10008"])
        self.assertNotIn("parent", json.dumps(body))
        # Sent with the upload, the same v1 consent is refused the same way.
        attempt = uuid.uuid4()
        body = self._refusal(self._upload(death_id, _answers(Id10008="parent"), client_draft_id=attempt,
                                          consent=self._consent(client_draft_id=attempt)), 422, "consent_invalid")
        self.assertEqual(body["fields"], ["Id10008"])
        # What v1 covers still goes through.
        self.assertEqual(self._upload(death_id, _answers(Id10007="Ram")).status_code, 201)

    def test_a_same_hash_resend_is_returned_unchecked(self):
        granted = self._consent()
        death_id = self._register(informant_name="Ram", consent=granted).get_json()["case"]["death_id"]
        attempt = uuid.uuid4()
        answers = _answers(Id10007="Ram")
        self.assertEqual(self._upload(death_id, answers, client_draft_id=attempt).status_code, 201)
        consent_service.record_consent(
            self.interviewer, project_id=self.REQUIRED, death=self._death(death_id),
            consent=self._consent(decision="refused", supersedes_client_id=granted["client_id"]),
            client_draft_id=None, channel="web")
        db.session.commit()
        # The first result again (documented), not a consent check ...
        self.assertEqual(self._upload(death_id, answers, client_draft_id=attempt).status_code, 200)
        # ... while other answers of that attempt are checked.
        self._refusal(self._upload(death_id, _answers(Id10007="Ram", Id10008="x"), client_draft_id=attempt),
                      422, "consent_refused")

    # ── configuration edge cases ───────────────────────────────────────────

    def test_active_versions_keep_the_newest_past_the_cap(self):
        for text in ("Notice v2", "Notice v3"):
            consent_service.create_notice_version(self.base_admin_user, self.REQUIRED, {
                "language": "en", "text": text, "purposes": PURPOSES, "allowed_modes": ["spoken"]})
        db.session.flush()
        original = consent_service.MAX_VERSIONS_LISTED
        consent_service.MAX_VERSIONS_LISTED = 2
        try:
            listed = [v.version for v in consent_service.active_versions(self.REQUIRED)]
            settings = [v["version"] for v in consent_service.serialize_settings(self.REQUIRED)["notice_versions"]]
        finally:
            consent_service.MAX_VERSIONS_LISTED = original
        self.assertEqual(listed, [2, 3])
        self.assertEqual(settings, [2, 3])

    def test_notice_text_with_nul_or_a_lone_surrogate_is_400(self):
        self._login(self.base_admin_id)
        for label, text in (("nul", "Notice\x00text"), ("surrogate", "Notice \ud800 text")):
            with self.subTest(label):
                response = self.client.post(
                    f"/api/v1/projects/{self.REQUIRED}/consent-notices", headers=self._csrf_headers(),
                    json={"language": "en", "text": text, "purposes": PURPOSES, "allowed_modes": ["spoken"]})
                body = self._refusal(response, 400, "invalid_request")
                self.assertEqual(body["fields"], ["text"])
        with self.assertRaises(consent_service.ConsentError) as raised:
            consent_service.create_notice_version(self.base_admin_user, self.REQUIRED, {
                "language": "en", "text": "ok", "allowed_modes": ["spoken"],
                "purposes": [{"code": "x", "label": "bad\x00label", "required": True}]})
        self.assertEqual(raised.exception.status_code, 400)

    def test_a_first_save_that_loses_the_insert_race_is_applied_to_the_winner(self):
        # The row exists (setUpClass); this save is made to believe it does not,
        # as a concurrent first save would, so its insert hits the primary key.
        db.session.expunge(consent_service.get_settings(self.REQUIRED))
        real, calls = consent_service._lock_settings, []

        def racing(project_id):
            calls.append(project_id)
            return None if len(calls) == 1 else real(project_id)

        consent_service._lock_settings = racing
        try:
            consent_service.save_settings(self.base_admin_user, self.REQUIRED,
                                          {"retention": {"period_days": 30, "expiry_action": "lock"}})
        finally:
            consent_service._lock_settings = real
        self.assertEqual(len(calls), 2)
        db.session.expire_all()
        settings = consent_service.get_settings(self.REQUIRED)
        self.assertEqual((settings.retention_period_days, settings.expiry_action), (30, "lock"))
        self.assertTrue(settings.consent_required)

    # ── Project Setup: seed from draft, approve (digitva-athy) ─────────────

    def test_seed_from_draft_creates_english_and_hindi_version_1_pending_review(self):
        self._login(self.base_admin_id)
        url = f"/api/v1/projects/{self.PLAIN}/consent-notices/seed"
        self.assertEqual(self.client.post(url).status_code, 400)  # no CSRF
        response = self.client.post(url, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 201, response.get_json())
        versions = response.get_json()["notice_versions"]
        self.assertEqual([(v["version"], v["language"]) for v in versions], [(1, "en"), (1, "hi")])
        for version in versions:
            self.assertIn("Consent CNS02", version["text"])
            self.assertNotIn("[PROJECT NAME]", version["text"])
            self.assertEqual(version["text_sha256"], hashlib.sha256(version["text"].encode()).hexdigest())
        # Both languages answer the same purposes, so a record validates in either.
        self.assertEqual(*[[(p["code"], p["required"]) for p in v["purposes"]] for v in versions])
        listed = self.client.get(f"/api/v1/projects/{self.PLAIN}/consent-settings").get_json()["notice_versions"]
        self.assertEqual([v["approved_at"] for v in listed], [None, None])
        self._refusal(self.client.post(url, headers=self._csrf_headers()), 409, "conflict")

    def test_seed_is_refused_to_an_interviewer(self):
        response = self.client.post(f"/api/v1/projects/{self.PLAIN}/consent-notices/seed",
                                    headers=self._csrf_headers())
        self.assertEqual(response.status_code, 403)

    def test_only_an_admin_approves_a_notice_version(self):
        notice_id = str(self.notice.notice_version_id)
        url = f"/api/v1/projects/{self.REQUIRED}/consent-notices/{notice_id}/approve"
        self._login(str(self.manager.user_id))
        self.assertEqual(self.client.post(url, headers=self._csrf_headers()).status_code, 403)
        self._login(self.base_admin_id)
        self.assertEqual(self.client.post(url).status_code, 400)  # no CSRF
        response = self.client.post(url, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        approved = {v["notice_version_id"]: v["approved_at"] for v in response.get_json()["notice_versions"]}
        self.assertIsNotNone(approved[notice_id])
        again = self.client.post(url, headers=self._csrf_headers()).get_json()["notice_versions"]
        self.assertEqual({v["notice_version_id"]: v["approved_at"] for v in again}[notice_id], approved[notice_id])
        events = list(db.session.scalars(sa.select(MapConsentAudit.event).where(
            MapConsentAudit.event == "consent_notice_approved",
            MapConsentAudit.notice_version_id == self.notice.notice_version_id)))
        self.assertEqual(events, ["consent_notice_approved"])
        other = self.client.post(f"/api/v1/projects/{self.PLAIN}/consent-notices/{notice_id}/approve",
                                 headers=self._csrf_headers())
        self._refusal(other, 404, "not_found")
        # The approval is not part of the 5.2 config shape.
        self.assertNotIn("approved_at", consent_service.serialize_version(self.notice))

    def test_an_edit_is_a_new_version_and_the_old_one_stays_usable(self):
        self._login(self.base_admin_id)
        response = self.client.post(f"/api/v1/projects/{self.REQUIRED}/consent-notices",
                                    headers=self._csrf_headers(), json={
                                        "language": "en", "text": "Edited notice", "purposes": PURPOSES,
                                        "allowed_modes": ["spoken"]})
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["notice_version"]["version"], 2)
        self._login(self.interviewer_id)
        # A consent shown the earlier version is still recorded against it.
        death_id = self._register(informant_name="Ram", consent=self._consent()).get_json()["case"]["death_id"]
        self.assertEqual([r.notice_version_id for r in self._records(death_id)], [self.notice.notice_version_id])

    # ── the browser interview: /intake/drafts/<id>/consent ─────────────────

    def _direct_draft(self, project_id=None):
        project_id = project_id or self.REQUIRED
        site_id = self.SITE_REQ if project_id == self.REQUIRED else self.SITE_PLAIN
        started = self.client.post(f"{INTAKE}/drafts", headers=self._csrf_headers(),
                                   json={"project_id": project_id, "site_id": site_id})
        self.assertEqual(started.status_code, 201, started.get_json())
        return started.get_json()["draft"]["draft_id"]

    def _submit(self, draft_id, answers):
        return self.client.post(f"{INTAKE}/drafts/{draft_id}/submit", headers=self._csrf_headers(), json={
            "completion": {"valid": True, "issues": [], "data": answers}})

    def _draft_consent(self, draft_id, consent):
        return self.client.post(f"{INTAKE}/drafts/{draft_id}/consent", headers=self._csrf_headers(),
                                json={"consent": consent})

    def test_a_direct_interview_needs_a_decision_before_covered_answers(self):
        draft_id = self._direct_draft()
        status = self.client.get(f"{INTAKE}/drafts/{draft_id}/consent").get_json()
        self.assertEqual(status, {"consent_required": True, "decision": None, "covered_fields": [],
                                  "client_draft_id": None})
        self._refusal(self._submit(draft_id, _answers(Id10007="Ram")), 422, "consent_required")
        response = self._draft_consent(draft_id, self._consent())
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["decision"], "granted")
        self.assertEqual(self.client.get(f"{INTAKE}/drafts/{draft_id}/consent").get_json()["decision"], "granted")
        response = self._submit(draft_id, _answers(Id10007="Ram"))
        self.assertEqual(response.status_code, 201, response.get_json())
        [record] = [r for r in self._records() if r.channel == "web" and r.client_draft_id is None
                    and r.event == "granted"]
        self.assertEqual(record.notice_version_id, self.notice.notice_version_id)

    def test_a_refused_direct_interview_goes_ahead_without_covered_answers(self):
        draft_id = self._direct_draft()
        response = self._draft_consent(draft_id, self._consent(decision="refused"))
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertEqual(body["decision"], "refused")
        self.assertIn("Id10007", body["covered_fields"])
        self._refusal(self._submit(draft_id, _answers(Id10007="Ram")), 422, "consent_conflict")
        response = self._submit(draft_id, {"refusal_age_group": "65_plus", "refusal_sex": "female"})
        self.assertEqual(response.status_code, 201, response.get_json())
        draft = db.session.get(VaWebIntakeDraft, uuid.UUID(draft_id))
        db.session.refresh(draft)
        self.assertEqual(draft.meta["interviewOutcome"], "refused")
        self.assertNotIn("Id10013", self._saved_answers(draft_id))
        self.assertEqual(self._saved_answers(draft_id)["refusal_sex"], "female")

    def test_refusal_clears_saved_answers_and_a_grant_does_not_restore_them(self):
        draft_id = self._direct_draft()
        self.assertEqual(self._draft_consent(draft_id, self._consent()).status_code, 201)
        self.assertEqual(self._save_draft(draft_id, {"Id10013": "yes", "Id10007": "Ram"}).status_code, 200)
        self.assertEqual(self._saved_answers(draft_id)["Id10007"], "Ram")
        self.assertEqual(self._draft_consent(draft_id, self._consent(decision="refused")).status_code, 201)
        self.assertEqual(self._saved_answers(draft_id), {"Id10013": "yes"})
        self.assertEqual(self._draft_consent(draft_id, self._consent()).status_code, 201)
        self.assertEqual(self._saved_answers(draft_id), {"Id10013": "yes"})

    def test_refusal_clears_identity_copied_from_an_unsent_direct_draft(self):
        draft_id = self._direct_draft()
        self.assertEqual(self._draft_consent(draft_id, self._consent()).status_code, 201)
        self.assertEqual(self._save_draft(draft_id, _answers()).status_code, 200)
        draft = db.session.get(VaWebIntakeDraft, uuid.UUID(draft_id))
        death = db.session.get(VaDeathRegister, draft.death_id)
        self.assertTrue(death.has_deceased_name or death.deceased_name)
        self.assertEqual(self._draft_consent(draft_id, self._consent(decision="refused")).status_code, 201)
        db.session.refresh(death)
        self.assertFalse(death.has_deceased_name or death.deceased_name)
        self.assertIsNone(death.deceased_sex)
        self.assertIsNone(death.date_of_death)
        self.assertEqual(death.status, "draft_identity")

    def test_stale_who_yes_does_not_reverse_refusal(self):
        draft_id = self._direct_draft(self.PLAIN)
        self.assertEqual(self._save_draft(draft_id, {"Id10013": "no"}).status_code, 200)
        self._refusal(self._save_draft(draft_id, {"Id10013": "yes", "Id10017": "Bina"}), 409, "refusal_stale")
        self.assertEqual(self._saved_answers(draft_id), {"Id10013": "no"})
        self.assertEqual(self._save_draft(draft_id, {}).status_code, 200)
        self.assertEqual(self._saved_answers(draft_id), {"Id10013": "no"})
        draft = self.client.get(f"{INTAKE}/drafts/{draft_id}").get_json()["draft"]
        response = self.client.patch(f"{INTAKE}/drafts/{draft_id}", headers=self._csrf_headers(), json={
            "sections": {"main": {"Id10013": "yes"}}, "resume_refused": True,
            "if_updated_at": draft["updated_at"],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._saved_answers(draft_id), {"Id10013": "yes"})

    def test_refused_draft_rejects_attachment_upload(self):
        draft_id = self._direct_draft(self.PLAIN)
        self.assertEqual(self._save_draft(draft_id, {"Id10013": "no"}).status_code, 200)
        response = self.client.put(
            f"{INTAKE}/drafts/{draft_id}/attachments/{uuid.uuid4()}",
            headers=self._csrf_headers(), data=b"%PDF-1.4 test", content_type="application/octet-stream",
        )
        self._refusal(response, 422, "consent_refused")

    def test_refusal_scrubs_the_unsent_drafts_saved_history(self):
        draft_id = self._direct_draft(self.PLAIN)
        draft = db.session.get(VaWebIntakeDraft, uuid.UUID(draft_id))
        web_intake_service._keep_history(draft, {"Id10017": "Bina", "refusal_sex": "female"},
                                         sha256=None, meta={})
        db.session.commit()
        self.assertEqual(self._save_draft(draft_id, {"Id10013": "no"}).status_code, 200)
        history = db.session.scalars(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.status == "replaced", VaWebIntakeDraft.death_id == draft.death_id)).one()
        self.assertEqual(history.sections[0].data, {"refusal_sex": "female"})

    def test_phone_can_submit_a_deliberate_grant_with_the_current_draft_version(self):
        death_id = self._register(self.PLAIN).get_json()["case"]["death_id"]
        attempt = uuid.uuid4()
        synced = self._sync_draft(death_id, {"Id10013": "no"}, project_id=self.PLAIN, client_draft_id=attempt)
        self.assertEqual(synced.status_code, 200, synced.get_json())
        self.assertEqual(self._synced_answers(death_id)["Id10013"], "no")
        response = self._upload(death_id, _answers(), project_id=self.PLAIN, client_draft_id=attempt,
                                resume_refused=True, base_updated_at=synced.get_json()["draft"]["updated_at"])
        self.assertEqual(response.status_code, 201, response.get_json())

    def test_direct_upload_rechecks_consent_after_the_case_lock(self):
        attempt = uuid.uuid4()
        started = self.client.post(f"{INTAKE}/drafts", headers=self._csrf_headers(), json={
            "project_id": self.REQUIRED, "site_id": self.SITE_REQ, "client_draft_id": str(attempt),
        })
        self.assertEqual(started.status_code, 201, started.get_json())
        self.assertIsNotNone(db.session.get(VaWebIntakeDraft, uuid.UUID(started.get_json()["draft"]["draft_id"])))
        # The route's initial check has already run when the case lock is taken.
        from app.services import case_transition_service as cases
        original = cases.lock_case
        injected = False

        def lock_with_refusal(death):
            nonlocal injected
            if not injected:
                injected = True
                consent_service.record_consent(self.interviewer, project_id=self.REQUIRED, death=death,
                    consent=self._consent(client_draft_id=attempt, decision="refused"),
                    client_draft_id=attempt, channel="web")
            return original(death)

        with patch.object(cases, "lock_case", side_effect=lock_with_refusal):
            response = self._upload(None, {"Id10013": "yes", "Id10017": "Bina"}, client_draft_id=attempt)
        self._refusal(response, 422, "consent_refused")

    def test_direct_upload_cannot_bypass_a_refusal_already_on_file(self):
        attempt = uuid.uuid4()
        started = self.client.post(f"{INTAKE}/drafts", headers=self._csrf_headers(), json={
            "project_id": self.REQUIRED, "site_id": self.SITE_REQ, "client_draft_id": str(attempt),
        })
        self.assertEqual(started.status_code, 201, started.get_json())
        draft = db.session.get(VaWebIntakeDraft, uuid.UUID(started.get_json()["draft"]["draft_id"]))
        death = db.session.get(VaDeathRegister, draft.death_id)
        consent_service.record_consent(self.interviewer, project_id=self.REQUIRED, death=death,
            consent=self._consent(client_draft_id=attempt, decision="refused"), client_draft_id=attempt, channel="web")
        db.session.commit()
        self._refusal(self._upload(None, {"Id10013": "yes", "Id10017": "Bina"}, client_draft_id=attempt),
                      422, "consent_refused")

    def test_old_phone_answers_cannot_return_after_refusal_and_later_grant(self):
        death_id = self._register(consent=self._consent()).get_json()["case"]["death_id"]
        attempt = uuid.uuid4()
        old = _answers(Id10007="Ram")
        first = self._sync_draft(death_id, old, client_draft_id=attempt)
        self.assertEqual(first.status_code, 200, first.get_json())
        draft_id = first.get_json()["draft"]["draft_id"]
        self.assertEqual(self._draft_consent(draft_id, self._consent(decision="refused")).status_code, 201)
        self.assertEqual(self._draft_consent(draft_id, self._consent()).status_code, 201)
        stale = self._refusal(self._sync_draft(death_id, old, client_draft_id=attempt), 409, "refusal_stale")
        self.assertEqual(stale["draft_id"], draft_id)
        self._refusal(self._sync_draft(death_id, _answers(Id10007="Sita"), client_draft_id=attempt), 409, "refusal_stale")
        stale = self._refusal(self._upload(death_id, old, client_draft_id=attempt), 409, "refusal_stale")
        self.assertEqual(stale["draft_id"], draft_id)
        self.assertNotIn("Id10007", self._saved_answers(draft_id))

    def test_browser_sections_share_one_consent_lookup(self):
        draft_id = self._direct_draft()
        statements = []

        def count(conn, cursor, statement, parameters, context, executemany):
            if "va_consent_records" in statement:
                statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", count)
        try:
            response = self.client.patch(f"{INTAKE}/drafts/{draft_id}", headers=self._csrf_headers(),
                json={"sections": {f"s{i}": {"Id10007": "Ram"} for i in range(8)}})
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", count)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertLessEqual(len(statements), 3)

    def test_refusal_blocks_identifier_writes_for_browser_and_station(self):
        from app.services import death_identifier_write

        draft_id = self._direct_draft(self.PLAIN)
        self.assertEqual(self._save_draft(draft_id, {"Id10013": "no"}).status_code, 200)
        draft = db.session.get(VaWebIntakeDraft, uuid.UUID(draft_id))
        death_id = str(draft.death_id)
        response = self.client.put(f"{INTAKE}/cases/{death_id}/identifiers", headers=self._csrf_headers(),
                                   json={"identifiers": {"crs": "12345"}})
        self._refusal(response, 422, "consent_refused")
        with self.assertRaises(death_identifier_write.WebIntakeError) as error:
            death_identifier_write.put_identifiers(self.interviewer, death_id, {"crs": "12345"}, station_roster=True)
        self.assertEqual(error.exception.code, "consent_refused")

    def test_shared_direct_case_holds_other_drafts_until_each_explicit_resume(self):
        first_id = self._direct_draft(self.PLAIN)
        self.assertEqual(self._save_draft(first_id, _answers()).status_code, 200)
        first = db.session.get(VaWebIntakeDraft, uuid.UUID(first_id))
        death_id = str(first.death_id)
        self._login(str(self.outsider.user_id))
        started = self.client.post(f"{INTAKE}/drafts", headers=self._csrf_headers(), json={
            "project_id": self.PLAIN, "site_id": self.SITE_PLAIN, "death_id": death_id,
        })
        self.assertEqual(started.status_code, 201, started.get_json())
        other_id = started.get_json()["draft"]["draft_id"]
        self.assertEqual(self._save_draft(other_id, {"Id10013": "yes", "Id10017": "Other"}).status_code, 200)
        self._login(self.interviewer_id)
        self.assertEqual(self._save_draft(first_id, {"Id10013": "no"}).status_code, 200)
        self._login(str(self.outsider.user_id))
        self._refusal(self._save_draft(other_id, {"Id10013": "yes", "Id10017": "Changed"}),
                      409, "consent_refused")
        self.assertEqual(self._saved_answers(other_id)["Id10017"], "Other")
        version = self.client.get(f"{INTAKE}/drafts/{other_id}").get_json()["draft"]["updated_at"]
        attack = self.client.patch(f"{INTAKE}/drafts/{other_id}", headers=self._csrf_headers(), json={
            "sections": {"main": {"Id10013": "yes"}}, "resume_refused": True, "if_updated_at": version,
        })
        self._refusal(attack, 409, "consent_refused")
        self._login(self.interviewer_id)
        version = self.client.get(f"{INTAKE}/drafts/{first_id}").get_json()["draft"]["updated_at"]
        resumed = self.client.patch(f"{INTAKE}/drafts/{first_id}", headers=self._csrf_headers(), json={
            "sections": {"main": {"Id10013": "yes"}}, "resume_refused": True, "if_updated_at": version,
        })
        self.assertEqual(resumed.status_code, 200, resumed.get_json())
        self._login(str(self.outsider.user_id))
        self._refusal(self._save_draft(other_id, {"Id10017": "Changed"}), 409, "refusal_stale")
        version = self.client.get(f"{INTAKE}/drafts/{other_id}").get_json()["draft"]["updated_at"]
        resumed = self.client.patch(f"{INTAKE}/drafts/{other_id}", headers=self._csrf_headers(), json={
            "sections": {}, "resume_refused": True, "if_updated_at": version,
        })
        self.assertEqual(resumed.status_code, 200, resumed.get_json())

    def test_shared_case_dp_grant_does_not_override_who_refusal(self):
        self._grant(self.outsider, self.REQUIRED)
        db.session.commit()
        first_id = self._direct_draft()
        self.assertEqual(self._draft_consent(first_id, self._consent()).status_code, 201)
        self.assertEqual(self._save_draft(first_id, _answers()).status_code, 200)
        first = db.session.get(VaWebIntakeDraft, uuid.UUID(first_id))
        self._login(str(self.outsider.user_id))
        other = self.client.post(f"{INTAKE}/drafts", headers=self._csrf_headers(), json={
            "project_id": self.REQUIRED, "site_id": self.SITE_REQ, "death_id": str(first.death_id),
        })
        self.assertEqual(other.status_code, 201, other.get_json())
        other_id = other.get_json()["draft"]["draft_id"]
        self._login(self.interviewer_id)
        self.assertEqual(self._save_draft(first_id, {"Id10013": "no"}).status_code, 200)
        self.assertEqual(self._draft_consent(first_id, self._consent(decision="refused")).status_code, 201)
        self.assertEqual(self._draft_consent(first_id, self._consent()).status_code, 201)
        self._login(str(self.outsider.user_id))
        self._refusal(self._save_draft(other_id, {"Id10013": "yes"}), 409, "consent_refused")

    def test_submitting_shared_refusal_keeps_the_hold(self):
        first_id = self._direct_draft(self.PLAIN)
        self.assertEqual(self._save_draft(first_id, _answers()).status_code, 200)
        first = db.session.get(VaWebIntakeDraft, uuid.UUID(first_id))
        self._login(str(self.outsider.user_id))
        other = self.client.post(f"{INTAKE}/drafts", headers=self._csrf_headers(), json={
            "project_id": self.PLAIN, "site_id": self.SITE_PLAIN, "death_id": str(first.death_id),
        })
        self.assertEqual(other.status_code, 201, other.get_json())
        other_id = other.get_json()["draft"]["draft_id"]
        self._login(self.interviewer_id)
        self.assertEqual(self._save_draft(first_id, {"Id10013": "no"}).status_code, 200)
        response = self._submit(first_id, {"Id10013": "no"})
        self.assertEqual(response.status_code, 201, response.get_json())
        self._login(str(self.outsider.user_id))
        self._refusal(self._save_draft(other_id, {"Id10013": "yes"}), 409, "consent_refused")

    def test_refusal_on_an_existing_open_attempt_preserves_an_earlier_submission(self):
        first_id = self._direct_draft(self.PLAIN)
        self.assertEqual(self._save_draft(first_id, _answers()).status_code, 200)
        first = db.session.get(VaWebIntakeDraft, uuid.UUID(first_id))
        death_id = first.death_id
        self._login(str(self.outsider.user_id))
        other = self.client.post(f"{INTAKE}/drafts", headers=self._csrf_headers(), json={
            "project_id": self.PLAIN, "site_id": self.SITE_PLAIN, "death_id": str(death_id),
        })
        self.assertEqual(other.status_code, 201, other.get_json())
        other_id = other.get_json()["draft"]["draft_id"]
        third = self._get_or_make_user("consent.third.parallel@test.local", "Consent123!")
        self._grant(third, self.PLAIN)
        db.session.commit()
        self._login(str(third.user_id))
        third_draft = self.client.post(f"{INTAKE}/drafts", headers=self._csrf_headers(), json={
            "project_id": self.PLAIN, "site_id": self.SITE_PLAIN, "death_id": str(death_id),
        })
        self.assertEqual(third_draft.status_code, 201, third_draft.get_json())
        third_id = third_draft.get_json()["draft"]["draft_id"]
        self._login(self.interviewer_id)
        submitted = self._submit(first_id, _answers())
        self.assertEqual(submitted.status_code, 201, submitted.get_json())
        va_sid = submitted.get_json()["va_sid"]
        self._login(str(self.outsider.user_id))
        refused = self._save_draft(other_id, {"Id10013": "no"})
        self.assertEqual(refused.status_code, 200, refused.get_json())
        self.assertEqual(self._saved_answers(other_id), {"Id10013": "no"})
        death = db.session.get(VaDeathRegister, death_id)
        db.session.refresh(death)
        self.assertEqual((death.status, death.va_sid), ("submitted", va_sid))
        self.assertEqual(db.session.get(VaSubmissions, va_sid).va_consent, "yes")
        self._login(str(third.user_id))
        self._refusal(self._save_draft(third_id, {"Id10013": "yes", "Id10017": "Other"}),
                      409, "consent_refused")

    def test_a_case_with_a_registration_consent_opens_the_interview_at_once(self):
        death_id = self._register(informant_name="Ram", consent=self._consent()).get_json()["case"]["death_id"]
        started = self.client.post(f"{INTAKE}/drafts", headers=self._csrf_headers(), json={
            "project_id": self.REQUIRED, "site_id": self.SITE_REQ, "death_id": death_id})
        draft_id = started.get_json()["draft"]["draft_id"]
        self.assertEqual(self.client.get(f"{INTAKE}/drafts/{draft_id}/consent").get_json()["decision"], "granted")

    def _save_draft(self, draft_id, answers):
        return self.client.patch(f"{INTAKE}/drafts/{draft_id}", headers=self._csrf_headers(),
                                 json={"sections": {"main": answers}})

    def _saved_answers(self, draft_id):
        draft = db.session.get(VaWebIntakeDraft, uuid.UUID(draft_id))
        db.session.refresh(draft)
        return {k: v for sec in draft.sections for k, v in sec.data.items()}

    def test_a_browser_draft_save_drops_covered_answers_without_a_granted_consent(self):
        draft_id = self._direct_draft()
        response = self._save_draft(draft_id, _answers(Id10007="Ram", Id10061="Hari"))
        self.assertEqual(response.status_code, 200, response.get_json())
        saved = self._saved_answers(draft_id)
        self.assertEqual(saved["Id10017"], "Bina")  # present: the rest is kept
        self.assertNotIn("Id10007", saved)
        self.assertNotIn("Id10061", saved)

    def test_a_browser_draft_save_keeps_covered_answers_after_a_granted_consent(self):
        draft_id = self._direct_draft()
        self.assertEqual(self._draft_consent(draft_id, self._consent()).status_code, 201)
        self.assertEqual(self._save_draft(draft_id, _answers(Id10007="Ram")).status_code, 200)
        self.assertEqual(self._saved_answers(draft_id)["Id10007"], "Ram")
        # and the submit that follows is unchanged
        self.assertEqual(self._submit(draft_id, _answers(Id10007="Ram")).status_code, 201)

    def test_a_browser_draft_save_drops_covered_answers_after_a_refusal(self):
        draft_id = self._direct_draft()
        self.assertEqual(self._draft_consent(draft_id, self._consent(decision="refused")).status_code, 201)
        self.assertEqual(self._save_draft(draft_id, _answers(Id10007="Ram")).status_code, 200)
        saved = self._saved_answers(draft_id)
        self.assertEqual(saved, {"Id10013": "yes"})

    def test_a_browser_draft_save_in_a_project_without_consent_keeps_everything(self):
        draft_id = self._direct_draft(self.PLAIN)
        self.assertEqual(self._save_draft(draft_id, _answers(Id10007="Ram")).status_code, 200)
        self.assertEqual(self._saved_answers(draft_id)["Id10007"], "Ram")

    def test_a_project_without_consent_needs_no_decision(self):
        draft_id = self._direct_draft(self.PLAIN)
        status = self.client.get(f"{INTAKE}/drafts/{draft_id}/consent").get_json()
        self.assertEqual((status["consent_required"], status["decision"]), (False, None))
        self.assertEqual(self._submit(draft_id, _answers(Id10007="Ram")).status_code, 201)

    def test_draft_consent_is_the_draft_owners_and_needs_csrf(self):
        draft_id = self._direct_draft()
        self.assertEqual(self.client.post(f"{INTAKE}/drafts/{draft_id}/consent",
                                          json={"consent": self._consent()}).status_code, 400)
        self._refusal(self._draft_consent(draft_id, {"decision": "granted"}), 422, "consent_invalid")
        self._login(str(self.outsider.user_id))
        self.assertEqual(self.client.get(f"{INTAKE}/drafts/{draft_id}/consent").status_code, 404)
        self.assertEqual(self._draft_consent(draft_id, self._consent()).status_code, 404)
        self.assertEqual(self._records(), [])
