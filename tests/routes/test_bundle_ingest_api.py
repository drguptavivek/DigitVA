"""Offline bundle ingest (digitva-gb8w.2): ``POST /api/v1/intake/bundles``,
``/validate``, the stored report and the signed receipt.

Policy docs/policy/offline-bundle-and-transfer.md 2-5 and 9; contract
docs/policy/offline-api-contract.md 4, 4.1, 4.2, 5, 7, 8. Bundles are built
with tests/bundle_builder.py (the Rust writer's format) against the test
process's KEM key and a test station key.
"""
import base64
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import mock

import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app import db, limiter
from app.models import (
    AuthDevice,
    AuthSecurityEvent,
    MapBundleRecord,
    MapCaseTransition,
    MapDeathIdentifier,
    MasDeathIdentifierType,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaBundleIngest,
    VaConsentRecord,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaWebIntakeDraft,
)
from app.services import bundle_ingest_service as service
from app.services import consent_service, station_config_service
from app.services import device_auth_service as devices
from app.services.authz import grants as authz_grants
from app.services.device_signing_service import register_pasted_station
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests import bundle_builder as bb
from tests.base import BaseTestCase
from tests.routes.test_device_api import _FreshGClient

PASSWORD = "BundleIngest123!"
PROJECT = "BNQ71"
OTHER_PROJECT = "BNQ72"
SITE = "BQ71"
OTHER_SITE = "BQ72"
KEY_FILE = str(Path(__file__).resolve().parents[1] / "fixtures" / "station_config" / "test_server_signing_key")
NOTICE = "Bundle consent notice: we record the interview."
URL = "/api/v1/intake/bundles"
SENTINEL_NAME = "Sentinelname Qwerty"
SENTINEL_PHONE = "9876501234"
#: A DORIS certificate the online save takes (tests/services/test_doris_clinical_finalization.py).
DORIS_CERTIFICATE = {
    "ICDVersion": "ICD11", "ICDMinorVersion": "2026-01",
    "Part1": [{"Conditions": [{
        "Text": "Respiratory tuberculosis", "Code": "1B10.Z",
        "LinearizationURI": "http://id.who.int/icd/release/11/2026-01/mms/882244568/unspecified",
        "Interval": "P14D"}]}],
}


def _make_project(project_id, site_id, now, **settings):
    db.session.add(VaProjectMaster(
        project_id=project_id, project_code=project_id, project_name=f"Bundle {project_id}",
        project_nickname=project_id, project_status=VaStatuses.active,
        project_registered_at=now, project_updated_at=now, web_intake_mode="both", **settings,
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
        form_id=f"{project_id}{site_id}01"[:12], project_id=project_id, site_id=site_id,
        odk_form_id=f"ODK_{project_id}", odk_project_id="7", form_type="WHO VA 2022",
        form_source="odk", form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
    ))
    db.session.flush()


def _grant(user, project_id, role):
    row = VaUserAccessGrants(
        user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project, project_id=project_id,
        notes="bundle ingest test grant", grant_status=VaStatuses.active,
    )
    db.session.add(row)
    db.session.flush()
    return row


def _public_b64(key) -> str:
    return bb.b64u(bb.public_bytes(key))


class BundleIngestApiTests(BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._saved_key_file = cls.app.config.get("BUNDLE_SERVER_SIGNING_KEY_FILE")
        cls.app.config["BUNDLE_SERVER_SIGNING_KEY_FILE"] = KEY_FILE
        now = datetime.now(UTC)
        # Not self-coding: a station's coding rests on its registration and roster (Q5).
        _make_project(PROJECT, SITE, now, masked_cod_required=True, self_coding_enabled=False)
        _make_project(OTHER_PROJECT, OTHER_SITE, now)
        mk = cls._get_or_make_user
        cls.interviewer = mk("bundle.interviewer@test.local", PASSWORD)
        cls.second = mk("bundle.second@test.local", PASSWORD)
        cls.coder = mk("bundle.coder@test.local", PASSWORD)
        cls.supervisor = mk("bundle.supervisor@test.local", PASSWORD)
        cls.manager = mk("bundle.dm@test.local", PASSWORD)
        cls.other_manager = mk("bundle.other.dm@test.local", PASSWORD)
        cls.outsider = mk("bundle.outsider@test.local", PASSWORD)
        _grant(cls.interviewer, PROJECT, VaAccessRoles.interviewer)
        cls.second_grant = _grant(cls.second, PROJECT, VaAccessRoles.interviewer)
        _grant(cls.coder, PROJECT, VaAccessRoles.coder)
        # A supervising grant backs station_supervisor (decision 10); interview_supervisor
        # grants are unit-scoped, a project data manager is the simplest one.
        _grant(cls.supervisor, PROJECT, VaAccessRoles.data_manager)
        _grant(cls.manager, PROJECT, VaAccessRoles.data_manager)
        _grant(cls.other_manager, OTHER_PROJECT, VaAccessRoles.data_manager)
        db.session.add(MasDeathIdentifierType(project_id=PROJECT, code="crs", label="CRS number", sort_order=1,
                                              min_length=6, max_length=12, char_type="digits"))
        cls.notice = consent_service.create_notice_version(cls.base_admin_user, PROJECT, {
            "language": "en", "text": NOTICE,
            "purposes": [{"code": "record_interview", "label": "Record", "required": True}],
            "allowed_modes": ["spoken", "tap"], "witness_allowed": False,
        })
        consent_service.save_settings(cls.base_admin_user, PROJECT, {"consent_required": True})
        cls.station_key = Ed25519PrivateKey.generate()
        cls.station = cls._onboard_paste_station(cls.station_key)
        cls.config_id = station_config_service.latest_config(cls.station.device_id).config_id
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        cls.app.config["BUNDLE_SERVER_SIGNING_KEY_FILE"] = cls._saved_key_file
        super().tearDownClass()

    @classmethod
    def _onboard_paste_station(cls, key, *, custodian=True, roster=True):
        device = register_pasted_station(PROJECT, {
            "device_id": str(uuid.uuid4()), "signing_public_key": _public_b64(key), "app_version": "0.1.0",
        }, name="PHC station", actor=cls.base_admin_user)
        cls._onboard(device.device_id, custodian=custodian, roster=roster)
        return device

    @classmethod
    def _onboard(cls, device_id, *, custodian=True, roster=True):
        admin = cls.base_admin_user
        if custodian:
            station_config_service.set_custodian(admin, PROJECT, device_id, {
                "name": "Dr. Custodian", "designation": "medical_officer", "phone": "9876543210",
                "email": None, "onboarded_on": date.today().isoformat()})
        if roster:
            def member(user, role):
                return {"user_id": str(user.user_id), "designation": "health_worker", "active": True,
                        "roles": [{"role": role, "site_id": SITE, "org_unit_id": None}]}
            station_config_service.set_roster(admin, PROJECT, device_id, {"members": [
                member(cls.interviewer, "interviewer"), member(cls.second, "interviewer"),
                member(cls.coder, "coder"), member(cls.supervisor, "station_supervisor"),
            ]})
        if custodian and roster:
            station_config_service.issue_config(admin, PROJECT, device_id)

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = _FreshGClient(self.app, self.app.response_class, use_cookies=True)

    # ── builders ───────────────────────────────────────────────────────────

    def _rec(self, record_type, actor, role, **body):
        return bb.record(record_type, project_id=PROJECT, actor_user_id=actor.user_number, acting_role=role, **body)

    def _registration(self, actor=None, role="interviewer", consent=None, **fields):
        body = {"site_id": SITE, "deceased_name": "Ram Lal", "deceased_sex": "male",
                "date_of_death": (date.today() - timedelta(days=3)).isoformat(), "age_years": 70, **fields}
        if consent is not None:
            body["consent_client_id"] = consent["client_id"]
        return self._rec("death_registration", actor or self.interviewer, role, **body)

    def _consent(self, death_ref, actor=None, *, draft_id=None, granted=True):
        return self._rec(
            "consent", actor or self.interviewer, "interviewer", death_ref=death_ref,
            client_draft_id=draft_id, notice_version_id=str(self.notice.notice_version_id),
            notice_language="en", notice_sha256=self.notice.text_sha256,
            decision="granted" if granted else "refused",
            purposes=[{"code": "record_interview", "granted": granted}], mode="tap", witness_present=False,
            supersedes_client_id=None)

    def _interview(self, death_ref, *, consent_client_id=None, answers=None, client_id=None, completed_at=None):
        answers_json = json.dumps(answers or {
            "Id10013": "yes", "Id10017": "Ram", "Id10018": "Lal", "Id10019": "male",
            "Id10023": (date.today() - timedelta(days=3)).isoformat(), "finalAgeInYears": "70",
            "narr_language": "english"}, separators=(",", ":"))
        now = (completed_at or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        return self._rec(
            "interview_submission", self.interviewer, "interviewer", client_id=client_id,
            site_id=SITE, death_ref=death_ref,
            draft={"instrumentVersion": "2023072701", "startedAt": now, "completedAt": now,
                   "deviceClockAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                   "interviewOutcome": "completed"},
            completion={"valid": True, "issues": []}, answers_json=answers_json,
            answers_sha256=hashlib.sha256(answers_json.encode()).hexdigest(), consent_client_id=consent_client_id)

    def _correction(self, death_ref, base, changes, actor=None, role="station_supervisor"):
        return self._rec("death_correction", actor or self.supervisor, role, death_ref=death_ref,
                         reason="Spelling fixed", if_updated_at=None, base_client_id=base, changes=changes)

    def _identifiers(self, death_ref, base, values):
        return self._rec("identifiers_set", self.supervisor, "station_supervisor", death_ref=death_ref,
                         reason="Number added", if_updated_at=None, base_client_id=base, identifiers=values)

    def _coding(self, interview, *, kind="final"):
        body = {"kind": kind, "client_draft_id": interview["client_id"],
                "coded_answers_sha256": interview["answers_sha256"]}
        if kind == "final":
            body["initial"] = {"immediate_cod": "I64", "antecedent_cod": "I64", "other_conditions": []}
            body["final"] = {"conclusive_cod": "I64", "remark": None, "cod_search_id": None,
                             "cod_chosen_code": None, "cod_chosen_rank": None}
        else:
            body["not_codeable"] = {"reason": "no_info", "other": None}
        return self._rec("coding_result", self.coder, "coder", **body)

    def _bundle(self, records, *, key=None, device=None, config_id=None, **kwargs):
        return bb.build(records, signing_key=key or self.station_key,
                        device_id=(device or self.station).device_id,
                        station_config_id=config_id or self.config_id, project_id=PROJECT, **kwargs)

    def _post(self, raw, *, user=None, path=URL, csrf=True, headers=None):
        if headers is None:
            self._login(str((user or self.manager).user_id))
            headers = self._csrf_headers() if csrf else {}
        return self.client.post(path, data=raw, headers=headers, content_type=service.MEDIA_TYPE)

    @staticmethod
    def _by_id(response):
        return {r["client_id"]: r for r in response.get_json()["records"]}

    def _refusals(self, code):
        rows = db.session.scalars(sa.select(AuthSecurityEvent).where(AuthSecurityEvent.event_type == "bundle_refused"))
        return [r for r in rows if (r.detail or {}).get("code") == code]

    # ── the happy path ─────────────────────────────────────────────────────

    def test_every_record_type_is_applied_through_the_https_services(self):
        reg_consent_ref = {"client_death_id": None}
        registration = self._registration(informant_name=SENTINEL_NAME, informant_phone=SENTINEL_PHONE)
        reg_consent_ref["client_death_id"] = registration["client_id"]
        consent = self._consent(dict(reg_consent_ref))
        registration["consent_client_id"] = consent["client_id"]
        interview = self._interview(dict(reg_consent_ref), consent_client_id=consent["client_id"])
        correction = self._correction(dict(reg_consent_ref), registration["client_id"], {"remarks": "Corrected"})
        numbers = self._identifiers(dict(reg_consent_ref), correction["client_id"], {"crs": "1234567"})
        coding = self._rec("coding_result", self.coder, "coder", client_draft_id=interview["client_id"],
                           coded_answers_sha256=interview["answers_sha256"], kind="final",
                           initial={"immediate_cod": None, "antecedent_cod": "Stroke", "other_conditions": []},
                           final={"conclusive_cod": "Stroke", "remark": None, "cod_search_id": None,
                                  "cod_chosen_code": None, "cod_chosen_rank": None})
        raw = self._bundle([registration, consent, interview, correction, numbers, coding])

        with self.assertLogs("app", level="DEBUG") as logs:
            response = self._post(raw)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertTrue(any("bundle ingested" in line for line in logs.output))
        for line in logs.output:
            self.assertNotIn(SENTINEL_NAME, line)
            self.assertNotIn(SENTINEL_PHONE, line)
        records = self._by_id(response)
        for rec in (registration, consent, interview, correction, numbers):
            self.assertEqual(records[rec["client_id"]]["outcome"], "accepted", records[rec["client_id"]])
        # The interview just landed: SmartVA has not run, so coding waits.
        self.assertEqual(records[coding["client_id"]]["outcome"], "pending")
        self.assertEqual(records[coding["client_id"]]["code"], "not_ready")
        self.assertEqual(records[interview["client_id"]]["received_sha256"], interview["answers_sha256"])

        death = db.session.scalar(sa.select(VaDeathRegister).where(
            VaDeathRegister.client_death_id == uuid.UUID(registration["client_id"])))
        self.assertIsNotNone(death)
        self.assertEqual(death.registered_by, self.interviewer.user_id)
        self.assertEqual(death.informant_name, SENTINEL_NAME)
        self.assertEqual(death.remarks, "Corrected")
        self.assertEqual(records[registration["client_id"]]["death_id"], str(death.death_id))
        stored_consent = db.session.scalar(sa.select(VaConsentRecord).where(
            VaConsentRecord.client_consent_id == uuid.UUID(consent["client_id"])))
        self.assertEqual((stored_consent.channel, stored_consent.event), ("bundle", "granted"))
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.client_draft_id == uuid.UUID(interview["client_id"])))
        self.assertEqual(draft.status, "submitted")
        self.assertEqual(draft.meta["deviceId"], str(self.station.device_id))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(MapDeathIdentifier).where(
            MapDeathIdentifier.death_id == death.death_id)), 1)
        audits = db.session.scalars(sa.select(MapCaseTransition).where(
            MapCaseTransition.death_id == death.death_id, MapCaseTransition.action == "station_correction")).all()
        self.assertEqual(len(audits), 2)
        for audit in audits:
            self.assertEqual(audit.changes["authorized_by"], "station_roster")
            self.assertEqual(audit.changes["device_id"], str(self.station.device_id))
            self.assertEqual(audit.changes["station_config_id"], str(self.config_id))
            self.assertEqual(audit.actor_user_id, self.supervisor.user_id)
        # One station_record row per other applied record (coding is pending), no values.
        station_rows = db.session.scalars(sa.select(MapCaseTransition).where(
            MapCaseTransition.death_id == death.death_id, MapCaseTransition.action == "station_record")).all()
        self.assertEqual(sorted(r.changes["record_type"] for r in station_rows),
                         ["consent", "death_registration", "interview_submission"])
        for row in station_rows:
            self.assertEqual(row.changes["device_id"], str(self.station.device_id))
            self.assertEqual(row.changes["station_config_id"], str(self.config_id))
            self.assertEqual(row.changes["custodian"]["name"], "Dr. Custodian")
            self.assertIn(row.changes["client_id"], {registration["client_id"], consent["client_id"],
                                                     interview["client_id"]})
            self.assertNotIn(SENTINEL_NAME, json.dumps(row.changes))
            self.assertNotIn(SENTINEL_PHONE, json.dumps(row.changes))
        ingest = db.session.get(VaBundleIngest, uuid.UUID(json.loads(raw.split(b"\n")[0])["bundle_id"]))
        self.assertEqual((ingest.status, ingest.channel), ("processed", "browser"))
        self.assertEqual(ingest.counts["accepted"], 5)
        # Never a value in the report or receipt (spec 9).
        for text in (response.get_data(as_text=True), ingest.receipt_text):
            self.assertIn(registration["client_id"], text)
            self.assertNotIn(SENTINEL_NAME, text)
            self.assertNotIn(SENTINEL_PHONE, text)

    def test_replay_returns_the_stored_report_and_writes_nothing(self):
        raw = self._bundle([self._registration()])
        first = self._post(raw)
        self.assertEqual(first.status_code, 201, first.get_json())
        deaths = db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister))
        again = self._post(raw)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.get_json(), first.get_json())
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister)), deaths)

    def test_reused_bundle_id_with_other_bytes_is_refused(self):
        bundle_id = uuid.uuid4()
        self.assertEqual(self._post(self._bundle([self._registration()], bundle_id=bundle_id)).status_code, 201)
        response = self._post(self._bundle([self._registration()], bundle_id=bundle_id))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "bundle_id_reused")
        self.assertTrue(self._refusals("bundle_id_reused"))

    def test_same_records_in_a_later_bundle_are_duplicates(self):
        registration = self._registration()
        consent = self._consent({"client_death_id": registration["client_id"]})
        self.assertEqual(self._post(self._bundle([registration, consent])).status_code, 201)
        audits = db.session.scalar(sa.select(sa.func.count()).select_from(MapCaseTransition).where(
            MapCaseTransition.action == "station_record"))
        self.assertGreaterEqual(audits, 2)
        response = self._post(self._bundle([registration, consent], bundle_seq=2))
        self.assertEqual(response.status_code, 201)
        records = self._by_id(response)
        self.assertEqual(records[registration["client_id"]]["outcome"], "duplicate")
        self.assertEqual(records[consent["client_id"]]["outcome"], "duplicate")
        # A duplicate writes nothing, so no further audit row.
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(MapCaseTransition).where(
            MapCaseTransition.action == "station_record")), audits)

    def test_a_registration_client_id_reused_with_other_content_is_a_conflict(self):
        registration = self._registration()
        self.assertEqual(self._post(self._bundle([registration])).status_code, 201)
        other = dict(registration, deceased_name="Shyam Lal")
        entry = self._by_id(self._post(self._bundle([other], bundle_seq=2)))[other["client_id"]]
        self.assertEqual((entry["outcome"], entry["code"]), ("rejected", "conflict"))
        same = self._by_id(self._post(self._bundle([registration], bundle_seq=3)))[registration["client_id"]]
        self.assertEqual(same["outcome"], "duplicate")

    # ── interrupted and concurrent ingests ─────────────────────────────────

    def test_an_interrupted_ingest_is_resumed_on_resend(self):
        registration = self._registration()
        raw = self._bundle([registration])
        bundle_id = uuid.UUID(json.loads(raw.split(b"\n")[0])["bundle_id"])
        self.assertEqual(self._post(raw).status_code, 201)
        # A worker died after the records were applied, before the report.
        row = db.session.get(VaBundleIngest, bundle_id)
        row.status, row.report, row.counts, row.receipt_text = "processing", None, None, None
        db.session.commit()
        self.assertEqual(self.client.get(f"{URL}/{bundle_id}").status_code, 404)

        response = self._post(raw)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(self._by_id(response)[registration["client_id"]]["outcome"], "duplicate")
        db.session.expire_all()
        row = db.session.get(VaBundleIngest, bundle_id)
        self.assertEqual(row.status, "processed")
        self.assertIsNotNone(row.receipt_text)
        self.assertEqual(self._receipt_body(bundle_id), response.get_json())
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister).where(
            VaDeathRegister.client_death_id == uuid.UUID(registration["client_id"]))), 1)

    def test_an_ingest_another_request_holds_is_409_until_released(self):
        raw = self._bundle([self._registration()])
        bundle_id = json.loads(raw.split(b"\n")[0])["bundle_id"]
        params = {"cls": service._INGEST_LOCK_CLASS, "name": f"bundle_ingest:{bundle_id}"}
        with db.engine.connect() as other:
            self.assertTrue(other.scalar(sa.text("SELECT pg_try_advisory_lock(:cls, hashtext(:name))"), params))
            try:
                response = self._post(raw)
            finally:
                other.scalar(sa.text("SELECT pg_advisory_unlock(:cls, hashtext(:name))"), params)
                other.commit()
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "conflict"))
        self.assertIsNone(db.session.get(VaBundleIngest, uuid.UUID(bundle_id)))
        self.assertEqual(self._post(raw).status_code, 201)

    # ── tamper, keys, revocation, age ──────────────────────────────────────

    def test_tampered_reordered_and_badly_signed_bundles_are_refused_before_decryption(self):
        raw = self._bundle([self._registration(), self._registration()])
        lines = raw.split(b"\n")
        record = json.loads(lines[2])
        record["ct"] = record["ct"][:-2] + ("AA" if not record["ct"].endswith("AA") else "BB")
        tampered = b"\n".join([*lines[:2], station_config_service.canonical_json(record), *lines[3:]])
        reordered = b"\n".join([*lines[:2], lines[3], lines[2], *lines[4:]])
        manifest = json.loads(lines[0])
        manifest["app_version"] = "9.9.9"
        resigned = b"\n".join([station_config_service.canonical_json(manifest), *lines[1:]])
        with mock.patch.object(service.pii_crypto, "unwrap_dek", side_effect=AssertionError("decrypted")):
            for bad, code in ((tampered, "body_hash_invalid"), (reordered, "body_hash_invalid"),
                              (resigned, "signature_invalid"), (raw[:-1], "manifest_invalid")):
                response = self._post(bad)
                self.assertEqual(response.status_code, 422, response.get_json())
                self.assertEqual(response.get_json()["code"], code)
        self.assertTrue(self._refusals("body_hash_invalid"))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaBundleIngest)), 0)

    def test_a_record_moved_from_another_bundle_does_not_open(self):
        registration = self._registration()
        response = self._post(self._bundle([registration], aad_bundle_id=uuid.uuid4()))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self._by_id(response)[registration["client_id"]]["code"], "record_invalid")

    def test_nul_and_lone_surrogate_records_are_rejected_without_a_trace_of_the_value(self):
        nul = self._registration(deceased_name="Sentinelname\x00Qwerty")
        surrogate = self._registration(deceased_name="Sentinelname\ud800Qwerty")
        # Escaped JSON: the strict UTF-8 decode passes, the parsed text holds the code point.
        surrogate_bytes = json.dumps(surrogate, sort_keys=True, separators=(",", ":")).encode("ascii")
        self.assertIn(b"\\ud800", surrogate_bytes)
        in_answers = self._interview({"client_death_id": nul["client_id"]},
                                     answers={"Id10013": "yes", "Id10017": "Sentinelname\x00", "narr_language": "x"})
        good = self._registration()
        raw = self._bundle([nul, surrogate, in_answers, good], record_bytes={surrogate["client_id"]: surrogate_bytes})
        with self.assertLogs("app", level="DEBUG") as logs:
            response = self._post(raw)
        self.assertEqual(response.status_code, 201, response.get_json())
        records = self._by_id(response)
        self.assertEqual(records[nul["client_id"]]["code"], "record_invalid")
        self.assertEqual(records[surrogate["client_id"]]["code"], "record_invalid")
        self.assertEqual(records[in_answers["client_id"]]["outcome"], "rejected")
        self.assertEqual(records[good["client_id"]]["outcome"], "accepted")
        for line in logs.output:
            self.assertNotIn("Sentinelname", line)
            self.assertNotIn("Traceback", line)
            # Refused by the parse check, not caught as a failure further on.
            self.assertNotIn("bundle record failed", line)

    def test_answers_json_holding_nul_is_record_invalid(self):
        registration = self._registration()
        interview = self._interview({"client_death_id": registration["client_id"]},
                                    answers={"Id10013": "yes", "Id10017": "Ram\x00", "narr_language": "english"})
        self.assertIn("\\u0000", interview["answers_json"])
        with self.assertLogs("app", level="DEBUG") as logs:
            records = self._by_id(self._post(self._bundle([registration, interview])))
        self.assertFalse([line for line in logs.output if "bundle record failed" in line])
        self.assertEqual(records[registration["client_id"]]["outcome"], "accepted")
        self.assertEqual(records[interview["client_id"]]["code"], "record_invalid")

    def test_an_unexpected_failure_rejects_the_record_and_logs_only_the_class(self):
        def explode(*_args):
            raise RuntimeError(SENTINEL_NAME)

        failing, good = self._registration(), self._consent({"client_death_id": str(uuid.uuid4())})
        with mock.patch.dict(service._HANDLERS, {"death_registration": explode}), \
                self.assertLogs("app", level="DEBUG") as logs:
            response = self._post(self._bundle([failing, good]))
        self.assertEqual(response.status_code, 201, response.get_json())
        records = self._by_id(response)
        self.assertEqual(records[failing["client_id"]]["code"], "record_invalid")
        self.assertEqual(records[good["client_id"]]["code"], "not_found")
        self.assertTrue(any("RuntimeError" in line for line in logs.output))
        for record in logs.records:
            self.assertNotIn(SENTINEL_NAME, record.getMessage())
            self.assertIsNone(record.exc_info)

    def test_echoed_field_names_are_capped(self):
        noisy = self._registration(**{f"{i:02d}" + "k" * 200: "v" for i in range(20)})
        response = self._post(self._bundle([noisy]))
        entry = self._by_id(response)[noisy["client_id"]]
        self.assertEqual(entry["code"], "record_invalid")
        self.assertEqual(len(entry["fields"]), service.FIELDS_MAX)
        self.assertTrue(all(len(name) == service.FIELD_NAME_MAX for name in entry["fields"]))
        receipt = self._receipt_body(response.get_json()["bundle_id"])
        self.assertEqual(receipt["records"][0]["fields"], entry["fields"])
        self.assertNotIn("k" * 65, json.dumps(receipt))

    def test_unknown_signing_key_and_unknown_device_are_refused(self):
        response = self._post(self._bundle([self._registration()], key=Ed25519PrivateKey.generate()))
        self.assertEqual(response.get_json()["code"], "signing_key_unknown")
        ghost = mock.Mock(device_id=uuid.uuid4())
        response = self._post(self._bundle([self._registration()], device=ghost))
        self.assertEqual(response.get_json()["code"], "device_unknown")

    def test_compromised_station_is_refused_and_a_decommissioned_one_only_after_revocation(self):
        key = Ed25519PrivateKey.generate()
        station = self._onboard_paste_station(key)
        config_id = station_config_service.latest_config(station.device_id).config_id
        station.revoked_at = datetime.now(UTC) - timedelta(hours=1)
        db.session.commit()
        before = self._bundle([self._registration()], key=key, device=station, config_id=config_id,
                              created_at=datetime.now(UTC) - timedelta(hours=2))
        after = self._bundle([self._registration()], key=key, device=station, config_id=config_id)
        self.assertEqual(self._post(after).get_json()["code"], "device_revoked")
        self.assertEqual(self._post(before).status_code, 201)
        station.revoked_compromised = True
        db.session.commit()
        older = self._bundle([self._registration()], key=key, device=station, config_id=config_id,
                             created_at=datetime.now(UTC) - timedelta(hours=3))
        response = self._post(older)
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "device_revoked"))

    def test_too_old_and_future_bundles_are_refused(self):
        old = self._bundle([self._registration()], created_at=datetime.now(UTC) - timedelta(days=91))
        future = self._bundle([self._registration()], created_at=datetime.now(UTC) + timedelta(days=2))
        self.assertEqual(self._post(old).get_json()["code"], "bundle_too_old")
        self.assertEqual(self._post(future).get_json()["code"], "bundle_from_future")

    def test_a_retired_kem_key_is_refused(self):
        from app.utils import pii_crypto

        retired, _private = pii_crypto.generate_keyset("retired")
        response = self._post(self._bundle([self._registration()], public_key=retired))
        self.assertEqual(response.get_json()["code"], "bundle_key_unknown")

    # ── onboarding, sandbox, project ───────────────────────────────────────

    def test_station_not_onboarded_and_sandbox_bundles_are_refused(self):
        key = Ed25519PrivateKey.generate()
        bare = self._onboard_paste_station(key, custodian=False)
        response = self._post(self._bundle([self._registration()], key=key, device=bare, config_id=uuid.uuid4()))
        self.assertEqual(response.get_json()["code"], "station_not_onboarded")
        # The sandbox: a config this server never issued, the local project key.
        sandbox = self._bundle([self._registration()], config_id=uuid.uuid4())
        self.assertEqual(self._post(sandbox).get_json()["code"], "station_not_onboarded")
        local = bb.build([bb.record("death_registration", project_id="1", actor_user_id=1,
                                    acting_role="interviewer", site_id=SITE)],
                         signing_key=self.station_key, device_id=self.station.device_id,
                         station_config_id=self.config_id, project_id="1")
        self._login(str(self.base_admin_user.user_id))
        response = self.client.post(URL, data=local, headers=self._csrf_headers(), content_type=service.MEDIA_TYPE)
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "forbidden"))

    # ── actors ─────────────────────────────────────────────────────────────

    def test_unknown_actor_wrong_role_and_lapsed_grant_are_rejected_per_record(self):
        stranger = self._registration(actor=self.outsider)
        wrong_role = self._registration(role="death_reporter")
        lapsed = self._registration(actor=self.second)
        self.second_grant.grant_status = VaStatuses.deactive
        db.session.commit()
        authz_grants.invalidate(self.second.user_id)
        good = self._registration()
        response = self._post(self._bundle([stranger, wrong_role, lapsed, good]))
        self.assertEqual(response.status_code, 201, response.get_json())
        records = self._by_id(response)
        self.assertEqual(records[stranger["client_id"]]["code"], "actor_unknown_on_device")
        self.assertEqual(records[wrong_role["client_id"]]["code"], "forbidden")
        self.assertEqual(records[lapsed["client_id"]]["code"], "forbidden")
        self.assertEqual(records[good["client_id"]]["outcome"], "accepted")

    def test_correction_needs_the_station_supervisor_role(self):
        registration = self._registration()
        correction = self._correction({"client_death_id": registration["client_id"]}, registration["client_id"],
                                      {"remarks": "x"}, actor=self.interviewer, role="interviewer")
        records = self._by_id(self._post(self._bundle([registration, correction])))
        self.assertEqual(records[correction["client_id"]]["code"], "forbidden")

    def test_an_interview_naming_another_site_or_unit_than_its_case_is_forbidden(self):
        registration = self._registration()
        ref = {"client_death_id": registration["client_id"]}
        other_unit = dict(self._interview(ref), org_unit_id=str(uuid.uuid4()))
        other_site = dict(self._interview(ref), site_id=OTHER_SITE)
        odd_unit = dict(self._interview(ref), org_unit_id=7)
        records = self._by_id(self._post(self._bundle([registration, other_unit, other_site, odd_unit])))
        self.assertEqual(records[registration["client_id"]]["outcome"], "accepted")
        for rec in (other_unit, other_site, odd_unit):
            self.assertEqual(records[rec["client_id"]]["code"], "forbidden", records[rec["client_id"]])
        self.assertFalse(db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.client_draft_id.in_([uuid.UUID(r["client_id"]) for r in (other_unit, other_site)]))))

    # ── consent ────────────────────────────────────────────────────────────

    def test_informant_fields_need_a_granted_registration_consent_in_the_bundle(self):
        without = self._registration(informant_name="Someone")
        refused_reg = self._registration(informant_name="Someone")
        refused = self._consent({"client_death_id": refused_reg["client_id"]}, granted=False)
        refused_reg["consent_client_id"] = refused["client_id"]
        response = self._post(self._bundle([without, refused_reg, refused]))
        records = self._by_id(response)
        self.assertEqual(records[without["client_id"]]["code"], "consent_required")
        self.assertEqual(records[refused_reg["client_id"]]["code"], "consent_required")
        self.assertEqual(records[refused["client_id"]]["outcome"], "rejected")
        self.assertFalse(db.session.scalar(sa.select(VaConsentRecord).where(
            VaConsentRecord.client_consent_id == uuid.UUID(refused["client_id"]))))

    def test_covered_answers_need_consent_on_the_case(self):
        registration = self._registration()
        interview = self._interview({"client_death_id": registration["client_id"]},
                                    answers={"Id10013": "yes", "Id10007": "Respondent", "narr_language": "english"})
        records = self._by_id(self._post(self._bundle([registration, interview])))
        self.assertEqual(records[registration["client_id"]]["outcome"], "accepted")
        self.assertEqual(records[interview["client_id"]]["code"], "consent_required")

    # ── partial acceptance and dependencies ────────────────────────────────

    def test_one_bad_record_never_rolls_back_another(self):
        bad = self._registration(deceased_name="")
        interview_on_bad = self._interview({"client_death_id": bad["client_id"]})
        good = self._registration()
        response = self._post(self._bundle([bad, interview_on_bad, good]))
        records = self._by_id(response)
        self.assertEqual(records[bad["client_id"]]["code"], "invalid_registration")
        self.assertEqual(records[interview_on_bad["client_id"]]["code"], "depends_on_rejected")
        self.assertEqual(records[good["client_id"]]["outcome"], "accepted")
        self.assertEqual(response.get_json()["counts"]["rejected"], 2)

    # ── corrections ────────────────────────────────────────────────────────

    def test_stale_completed_and_closed_corrections_are_rejected(self):
        registration = self._registration()
        ref = {"client_death_id": registration["client_id"]}
        stale = self._correction(ref, str(uuid.uuid4()), {"remarks": "stale"})
        records = self._by_id(self._post(self._bundle([registration, stale])))
        self.assertEqual(records[stale["client_id"]]["code"], "death_stale")
        interview = self._interview(ref)
        self.assertEqual(self._by_id(self._post(self._bundle([interview], bundle_seq=2)))[
            interview["client_id"]]["outcome"], "accepted")
        late = self._correction(ref, registration["client_id"], {"remarks": "late"})
        self.assertEqual(self._by_id(self._post(self._bundle([late], bundle_seq=3)))[
            late["client_id"]]["code"], "case_completed")
        death = db.session.scalar(sa.select(VaDeathRegister).where(
            VaDeathRegister.client_death_id == uuid.UUID(registration["client_id"])))
        death.status = "cancelled"
        db.session.commit()
        numbers = self._identifiers(ref, registration["client_id"], {"crs": "7654321"})
        self.assertEqual(self._by_id(self._post(self._bundle([numbers], bundle_seq=4)))[
            numbers["client_id"]]["code"], "case_closed")

    def test_a_correction_client_id_reused_with_other_content_is_a_conflict(self):
        registration = self._registration()
        ref = {"client_death_id": registration["client_id"]}
        correction = self._correction(ref, registration["client_id"], {"remarks": "one"})
        self.assertEqual(self._post(self._bundle([registration, correction])).status_code, 201)
        same = self._by_id(self._post(self._bundle([correction], bundle_seq=2)))
        self.assertEqual(same[correction["client_id"]]["outcome"], "duplicate")
        other = dict(correction, changes={"remarks": "two"})
        self.assertEqual(self._by_id(self._post(self._bundle([other], bundle_seq=3)))[
            other["client_id"]]["code"], "conflict")

    # ── transport, callers ─────────────────────────────────────────────────

    def test_size_limit_is_413_before_reading(self):
        raw = self._bundle([self._registration()])
        with mock.patch.object(service, "MAX_BYTES", 100), \
                mock.patch.object(service, "parse_container", side_effect=AssertionError("read")):
            response = self._post(raw)
        self.assertEqual((response.status_code, response.get_json()["code"]), (413, "payload_too_large"))

    def test_browser_upload_needs_csrf_and_a_project_uploader(self):
        raw = self._bundle([self._registration()])
        self.assertIn(self._post(raw, csrf=False).status_code, (400, 403))
        self.assertEqual(self._post(raw, user=self.other_manager).status_code, 403)
        self.assertEqual(self._post(raw, user=self.outsider).status_code, 403)
        self.assertEqual(self._post(raw, user=self.supervisor).status_code, 201)

    def test_station_bearer_uploads_its_own_bundles_only_and_actors_must_have_signed_in(self):
        key = Ed25519PrivateKey.generate()
        _row, code = devices.create_enrolment_code(PROJECT, actor=self.base_admin_user)
        db.session.commit()
        enrolled = self.client.post("/api/v1/auth/enroll", json={
            "code": code, "device_name": "Online PHC", "platform": "desktop", "app_version": "0.1.0",
            "signing_public_key": _public_b64(key)}).get_json()
        signed_in = self.client.post("/api/v1/auth/sessions", json={
            "device_id": enrolled["device_id"], "device_secret": enrolled["device_secret"],
            "email": "bundle.interviewer@test.local", "password": PASSWORD}).get_json()
        bearer = {"Authorization": f"Bearer {signed_in['access_token']}"}
        online = db.session.get(AuthDevice, uuid.UUID(enrolled["device_id"]))
        self._onboard(online.device_id)
        db.session.commit()
        config_id = station_config_service.latest_config(online.device_id).config_id

        # Another station's bundle with this bearer.
        response = self._post(self._bundle([self._registration()]), headers=bearer)
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "forbidden"))
        mine = self._registration()
        not_signed_in = self._registration(actor=self.second)
        response = self._post(self._bundle([mine, not_signed_in], key=key, device=online, config_id=config_id,
                                           created_at=datetime.now(UTC) + timedelta(minutes=1)), headers=bearer)
        self.assertEqual(response.status_code, 201, response.get_json())
        records = self._by_id(response)
        self.assertEqual(records[mine["client_id"]]["outcome"], "accepted")
        self.assertEqual(records[not_signed_in["client_id"]]["code"], "actor_unknown_on_device")
        bundle_id = response.get_json()["bundle_id"]
        self.assertEqual(self.client.get(f"{URL}/{bundle_id}", headers=bearer).status_code, 200)
        other_bearer = self.client.get(f"{URL}/{self._ingested_id()}", headers=bearer)
        self.assertEqual(other_bearer.status_code, 404)

    def _ingested_id(self):
        raw = self._bundle([self._registration()])
        response = self._post(raw)
        self.assertEqual(response.status_code, 201)
        return response.get_json()["bundle_id"]

    # ── dry run, report, receipt ───────────────────────────────────────────

    def test_validate_runs_every_check_and_stores_nothing(self):
        registration = self._registration()
        bad = self._registration(deceased_name="")
        deaths = db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister))
        response = self._post(self._bundle([registration, bad]), path=f"{URL}/validate")
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual(body["status"], "validated")
        records = self._by_id(response)
        self.assertEqual(records[registration["client_id"]]["outcome"], "not_processed")
        self.assertEqual(records[bad["client_id"]]["code"], "invalid_registration")
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister)), deaths)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaBundleIngest)), 0)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(MapBundleRecord)), 0)

    def test_receipt_verifies_with_the_server_key_and_carries_purge(self):
        registration = self._registration()
        response = self._post(self._bundle([registration]))
        bundle_id = response.get_json()["bundle_id"]
        report = self.client.get(f"{URL}/{bundle_id}")
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.get_json(), response.get_json())
        receipt = self.client.get(f"{URL}/{bundle_id}/receipt")
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt.headers["Cache-Control"], "no-store")
        line1, line2, tail = receipt.get_data(as_text=True).split("\n")
        self.assertEqual(tail, "")
        with open(KEY_FILE, encoding="ascii") as handle:
            server_key = station_config_service.parse_signing_key(handle.read())
        public = station_config_service.public_signing_key(server_key)
        signature = json.loads(line2)
        self.assertEqual(signature["signing_key_id"], public["signing_key_id"])
        raw_public = base64.urlsafe_b64decode(public["public"] + "=")
        Ed25519PublicKey.from_public_bytes(raw_public).verify(
            base64.urlsafe_b64decode(signature["sig"] + "=="), b"digitva-receipt-v1\x00" + line1.encode())
        body = json.loads(line1)
        self.assertEqual(body["purge"], [])
        self.assertEqual(body["records"][0]["client_id"], registration["client_id"])
        self.assertEqual(body["missing_seq"], [])
        # Another project's manager reads neither.
        self._login(str(self.other_manager.user_id))
        self.assertEqual(self.client.get(f"{URL}/{bundle_id}/receipt").status_code, 404)

    # ── pending coding (spec 5.5) ──────────────────────────────────────────

    def _interviewed_case(self):
        registration = self._registration()
        interview = self._interview({"client_death_id": registration["client_id"]})
        records = self._by_id(self._post(self._bundle([registration, interview])))
        self.assertEqual(records[interview["client_id"]]["outcome"], "accepted", records)
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.client_draft_id == uuid.UUID(interview["client_id"])))
        return interview, draft

    @staticmethod
    def _ready(va_sid):
        from app.services.workflow.state_store import set_submission_workflow_state

        set_submission_workflow_state(va_sid, "ready_for_coding", reason="test", by_role="test")
        db.session.commit()

    def _receipt_body(self, bundle_id):
        receipt = self.client.get(f"{URL}/{bundle_id}/receipt")
        self.assertEqual(receipt.status_code, 200)
        line1, line2, _tail = receipt.get_data(as_text=True).split("\n")
        with open(KEY_FILE, encoding="ascii") as handle:
            public = station_config_service.public_signing_key(station_config_service.parse_signing_key(handle.read()))
        Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(public["public"] + "=")).verify(
            base64.urlsafe_b64decode(json.loads(line2)["sig"] + "=="), b"digitva-receipt-v1\x00" + line1.encode())
        return json.loads(line1)

    def test_a_coding_result_for_a_case_not_ready_is_held_then_applied(self):
        from app.models import VaBundlePendingCoding
        from app.services.workflow.state_store import get_submission_workflow_state

        interview, draft = self._interviewed_case()
        self.assertNotEqual(get_submission_workflow_state(draft.va_sid), "ready_for_coding")
        coding = self._coding(interview, kind="not_codeable")
        first = self._post(self._bundle([coding], bundle_seq=2))
        self.assertEqual(self._by_id(first)[coding["client_id"]]["outcome"], "pending")
        # A resend while it is held stays pending and is resolved with the first.
        again = self._post(self._bundle([coding], bundle_seq=3))
        self.assertEqual(self._by_id(again)[coding["client_id"]]["outcome"], "pending")
        held = db.session.get(VaBundlePendingCoding, uuid.UUID(coding["client_id"]))
        self.assertEqual(held.status, "pending")
        self.assertEqual(len(held.bundle_ids), 2)
        # The masked result only: no envelope, no informant data.
        self.assertEqual(set(held.result), {"client_draft_id", "coded_answers_sha256", "kind", "not_codeable"})
        self.assertNotIn("Ram", json.dumps(held.result))

        self.assertEqual(service.apply_pending_coding(), {"applied": 0, "rejected": 0, "pending": 0})
        self._ready(draft.va_sid)
        # The Celery worker holds no server signing key: the applier needs none.
        with mock.patch.dict(self.app.config, {"BUNDLE_SERVER_SIGNING_KEY_FILE": ""}):
            counts = service.apply_pending_coding()
        row = db.session.get(VaBundlePendingCoding, held.client_id)
        self.assertEqual(counts["applied"], 1, (counts, row.status, row.code))

        self.assertEqual(row.status, "applied")
        self.assertIsNone(db.session.get(VaBundleIngest, uuid.UUID(first.get_json()["bundle_id"])).receipt_text)
        self.assertNotIn(get_submission_workflow_state(draft.va_sid), ("ready_for_coding", "coding_in_progress"))
        self.assertIsNotNone(db.session.get(MapBundleRecord, uuid.UUID(coding["client_id"])))
        for response in (first, again):
            bundle_id = response.get_json()["bundle_id"]
            report = self.client.get(f"{URL}/{bundle_id}").get_json()
            entry = next(r for r in report["records"] if r["client_id"] == coding["client_id"])
            self.assertEqual((entry["outcome"], entry["code"]), ("accepted", None))
            self.assertEqual((report["counts"]["accepted"], report["counts"]["pending"]), (1, 0))
            self.assertEqual(self._receipt_body(bundle_id), report)
        # Nothing is left to apply, and a later resend is a duplicate.
        self.assertEqual(service.apply_pending_coding()["applied"], 0)
        later = self._by_id(self._post(self._bundle([coding], bundle_seq=4)))
        self.assertEqual(later[coding["client_id"]]["outcome"], "duplicate")

    def test_a_coding_result_on_a_ready_case_is_applied_at_once(self):
        from app.services import coder_cod_service
        from app.services.workflow.state_store import get_submission_workflow_state

        interview, draft = self._interviewed_case()
        self._ready(draft.va_sid)
        coding = self._coding(interview)
        # The ICD catalogue is not loaded in tests: the code check is the coder service's own.
        with mock.patch.object(coder_cod_service, "validate_coding_value_for_submission", return_value="icd10"), \
                mock.patch.object(coder_cod_service, "build_icd11_provenance_for_values", return_value=None):
            records = self._by_id(self._post(self._bundle([coding], bundle_seq=2)))
        self.assertEqual(records[coding["client_id"]]["outcome"], "accepted", records)
        self.assertEqual(get_submission_workflow_state(draft.va_sid), "coder_finalized")
        audit = db.session.scalar(sa.select(MapCaseTransition).where(
            MapCaseTransition.death_id == draft.death_id, MapCaseTransition.action == "station_record",
            MapCaseTransition.changes["client_id"].astext == coding["client_id"]))
        self.assertIsNotNone(audit)
        self.assertEqual((audit.changes["record_type"], audit.changes["acting_role"]), ("coding_result", "coder"))
        self.assertEqual(audit.actor_user_id, self.coder.user_id)

    def test_coding_needs_an_active_station_and_the_coded_version(self):
        from app.models import VaBundlePendingCoding

        self.assertFalse(db.session.get(VaProjectMaster, PROJECT).self_coding_enabled)
        interview, draft = self._interviewed_case()
        stale = dict(self._coding(interview), coded_answers_sha256="0" * 64)
        held = self._coding(interview)
        records = self._by_id(self._post(self._bundle([stale, held], bundle_seq=2)))
        self.assertEqual(records[stale["client_id"]]["code"], "coded_version_superseded")
        self.assertEqual(records[held["client_id"]]["outcome"], "pending")

        # Decommissioned: a bundle made before revocation still lands, but not its coding.
        self.station.revoked_at = datetime.now(UTC) - timedelta(hours=1)
        db.session.commit()
        registration, late = self._registration(), self._coding(interview)
        records = self._by_id(self._post(self._bundle(
            [registration, late], bundle_seq=3, created_at=datetime.now(UTC) - timedelta(hours=2))))
        self.assertEqual(records[registration["client_id"]]["outcome"], "accepted")
        self.assertEqual(records[late["client_id"]]["code"], "offline_coding_disabled")
        # A held result meets the same rule when its case becomes ready.
        self._ready(draft.va_sid)
        self.assertEqual(service.apply_pending_coding()["rejected"], 1)
        row = db.session.get(VaBundlePendingCoding, uuid.UUID(held["client_id"]))
        self.assertEqual((row.status, row.code), ("rejected", "offline_coding_disabled"))
        bundle_id = next(iter(row.bundle_ids))
        entry = next(r for r in self._receipt_body(bundle_id)["records"] if r["client_id"] == held["client_id"])
        self.assertEqual((entry["outcome"], entry["code"]), ("rejected", "offline_coding_disabled"))

    def test_coding_needs_a_coder_on_the_station_roster(self):
        interview, _draft = self._interviewed_case()
        coding = self._coding(interview)
        by_interviewer = dict(coding, client_id=str(uuid.uuid4()), actor_user_id=self.interviewer.user_number)
        as_interviewer = dict(coding, client_id=str(uuid.uuid4()), acting_role="interviewer")
        records = self._by_id(self._post(self._bundle([by_interviewer, as_interviewer], bundle_seq=2)))
        self.assertEqual(records[by_interviewer["client_id"]]["code"], "actor_not_station_coder")
        self.assertEqual(records[as_interviewer["client_id"]]["code"], "forbidden")

    def test_a_station_codes_only_interviews_it_uploaded(self):
        key = Ed25519PrivateKey.generate()
        other = self._onboard_paste_station(key)
        other_config = station_config_service.latest_config(other.device_id).config_id
        registration = self._registration()
        interview = self._interview({"client_death_id": registration["client_id"]})
        records = self._by_id(self._post(self._bundle([registration, interview], key=key, device=other,
                                                      config_id=other_config)))
        self.assertEqual(records[interview["client_id"]]["outcome"], "accepted", records)
        coding = self._coding(interview, kind="not_codeable")
        records = self._by_id(self._post(self._bundle([coding], bundle_seq=2)))
        self.assertEqual((records[coding["client_id"]]["code"], records[coding["client_id"]]["fields"]),
                         ("not_available", ["client_draft_id"]))
        # The station that uploaded it codes it.
        records = self._by_id(self._post(self._bundle([coding], key=key, device=other, config_id=other_config,
                                                      bundle_seq=2)))
        self.assertEqual(records[coding["client_id"]]["outcome"], "pending", records)

    # ── station coding modes (bundle spec 2.4 Q5, digitva-lmxr) ────────────

    @staticmethod
    def _project_mode(mode):
        project = db.session.get(VaProjectMaster, PROJECT)
        doris = mode.endswith("_doris")
        project.masked_cod_required = mode.startswith("masked_")
        project.cod_entry_mode = "doris" if doris else "simple"
        project.icd_classification = "icd11" if doris else "icd10"  # ICD-11 means DORIS (DB check)
        db.session.commit()

    def _station_coding(self, interview, mode, *, kind="final", final=None, initial=None):
        """A coding result as a station in *mode* builds it: the unmasked
        workspace's finalize body, no Step 1 unless *initial*."""
        body = {"kind": kind, "client_draft_id": interview["client_id"],
                "coded_answers_sha256": interview["answers_sha256"], "coding_mode": mode}
        if kind == "not_codeable":
            body["not_codeable"] = {"reason": "no_info", "other": None}
        elif mode == "icd11_doris":
            body["final"] = final or {
                "conclusive_cod": "1B10.Z Respiratory tuberculosis", "doris_certificate": DORIS_CERTIFICATE,
                # The station engine's own results: advisory, never stored.
                "doris_result": {"status": "completed", "result": {"code": "1B10.Z"}},
                "codedit_result": {"status": "completed", "result": {}},
                "doris_process_token": "station-token", "doris_result_digest": "0" * 64,
                "doris_client_revision": 4}
        else:
            body["final"] = final or {"conclusive_cod": "I64", "remark": "station", "immediate_cod": "I64",
                                      "other_conditions": "I10 | E11"}
        if initial is not None:
            body["initial"] = initial
        return self._rec("coding_result", self.coder, "coder", **body)

    @staticmethod
    def _who():
        """The WHO service the server reprocesses a certificate with: code
        lookups pass, both engines are down (an outcome the online save takes)."""
        from app.services import doris_processing
        from app.services.who_icd_api import WhoIcdApiUnavailable

        return (mock.patch.object(doris_processing, "verify_certificate_codes"),
                mock.patch.object(doris_processing, "post_mortality_processor",
                                  side_effect=WhoIcdApiUnavailable("down")))

    @staticmethod
    def _catalogue():
        from app.services import coder_cod_service

        # The ICD catalogue is not loaded in tests: the code check is the coder service's own.
        return (mock.patch.object(coder_cod_service, "validate_coding_value_for_submission", return_value="icd10"),
                mock.patch.object(coder_cod_service, "build_icd11_provenance_for_values", return_value=None))

    def _final(self, va_sid):
        from app.models import VaFinalAssessments

        return db.session.scalar(sa.select(VaFinalAssessments).where(
            VaFinalAssessments.va_sid == va_sid, VaFinalAssessments.va_finassess_status == VaStatuses.active))

    def test_an_icd10_result_lands_in_an_unmasked_simple_project_at_once(self):
        from app.services.workflow.state_store import get_submission_workflow_state

        self._project_mode("unmasked_simple")
        interview, draft = self._interviewed_case()
        self._ready(draft.va_sid)
        coding = self._station_coding(interview, "icd10")
        validate, provenance = self._catalogue()
        with validate, provenance:
            records = self._by_id(self._post(self._bundle([coding], bundle_seq=2)))
        self.assertEqual(records[coding["client_id"]]["outcome"], "accepted", records)
        self.assertEqual(get_submission_workflow_state(draft.va_sid), "coder_finalized")
        final = self._final(draft.va_sid)
        self.assertIsNotNone(final)
        self.assertEqual((final.va_conclusive_cod, final.va_immediate_cod, final.va_other_conditions,
                          final.va_finassess_by), ("I64", "I64", "I10 | E11", self.coder.user_id))
        self.assertIsNone(final.source_initial_assessment_id)
        # Idempotent: the same record again is a duplicate, and writes no second final.
        again = self._by_id(self._post(self._bundle([coding], bundle_seq=3)))
        self.assertEqual(again[coding["client_id"]]["outcome"], "duplicate")
        self.assertEqual(self._final(draft.va_sid).va_finassess_id, final.va_finassess_id)

    def test_an_icd10_result_held_for_a_case_not_ready_is_applied_by_the_task(self):
        from app.models import VaBundlePendingCoding

        self._project_mode("unmasked_simple")
        interview, draft = self._interviewed_case()
        coding = self._station_coding(interview, "icd10")
        first = self._by_id(self._post(self._bundle([coding], bundle_seq=2)))
        self.assertEqual((first[coding["client_id"]]["outcome"], first[coding["client_id"]]["code"]),
                         ("pending", "not_ready"))
        held = db.session.get(VaBundlePendingCoding, uuid.UUID(coding["client_id"]))
        self.assertEqual(held.result["coding_mode"], "icd10")
        self._ready(draft.va_sid)
        validate, provenance = self._catalogue()
        with validate, provenance:
            self.assertEqual(service.apply_pending_coding()["applied"], 1)
        self.assertEqual(self._final(draft.va_sid).va_immediate_cod, "I64")

    def test_an_icd11_doris_final_is_held_and_reprocessed_by_the_task(self):
        from app.models import VaBundlePendingCoding
        from app.services.workflow.state_store import get_submission_workflow_state

        self._project_mode("unmasked_doris")
        interview, draft = self._interviewed_case()
        self._ready(draft.va_sid)
        coding = self._station_coding(interview, "icd11_doris")
        # Never applied in the request: processing a certificate calls the WHO service.
        with mock.patch("app.services.doris_processing.process_certificate") as process:
            response = self._post(self._bundle([coding], bundle_seq=2))
            records = self._by_id(response)
        process.assert_not_called()
        self.assertEqual((records[coding["client_id"]]["outcome"], records[coding["client_id"]]["code"]),
                         ("pending", "doris_pending"))
        self.assertEqual(get_submission_workflow_state(draft.va_sid), "ready_for_coding")
        # A resend while held is still pending with the same reason.
        again = self._by_id(self._post(self._bundle([coding], bundle_seq=3)))
        self.assertEqual(again[coding["client_id"]]["code"], "doris_pending")

        codes, engines = self._who()
        validate, provenance = self._catalogue()
        with codes, engines, validate, provenance:
            counts = service.apply_pending_coding()
        row = db.session.get(VaBundlePendingCoding, uuid.UUID(coding["client_id"]))
        self.assertEqual(counts["applied"], 1, (counts, row.status, row.code))
        self.assertEqual(get_submission_workflow_state(draft.va_sid), "coder_finalized")
        final = self._final(draft.va_sid)
        self.assertIsNotNone(final)
        self.assertEqual((final.va_conclusive_cod, final.va_finassess_by),
                         ("1B10.Z Respiratory tuberculosis", self.coder.user_id))
        self.assertEqual(final.doris_certificate["Part1"][0]["Conditions"][0]["Code"], "1B10.Z")
        # The server's engine results are kept, not the station's.
        self.assertEqual(final.doris_result, {"status": "unavailable", "result": None})
        # The station audit row the ingest writes for an applied record.
        audit = db.session.scalar(sa.select(MapCaseTransition).where(
            MapCaseTransition.death_id == draft.death_id, MapCaseTransition.action == "station_record",
            MapCaseTransition.changes["client_id"].astext == coding["client_id"]))
        self.assertIsNotNone(audit)
        self.assertEqual((audit.changes["record_type"], audit.changes["acting_role"], audit.actor_user_id),
                         ("coding_result", "coder", self.coder.user_id))
        self.assertEqual(audit.changes["device_id"], str(self.station.device_id))
        bundle_id = response.get_json()["bundle_id"]
        entry = next(r for r in self._receipt_body(bundle_id)["records"] if r["client_id"] == coding["client_id"])
        self.assertEqual((entry["outcome"], entry["code"]), ("accepted", None))
        later = self._by_id(self._post(self._bundle([coding], bundle_seq=4)))
        self.assertEqual(later[coding["client_id"]]["outcome"], "duplicate")

    def test_an_invalid_doris_certificate_is_refused_with_the_online_code(self):
        from app.models import VaBundlePendingCoding

        self._project_mode("unmasked_doris")
        interview, draft = self._interviewed_case()
        self._ready(draft.va_sid)
        coding = self._station_coding(interview, "icd11_doris", final={
            "conclusive_cod": "1B10.Z Respiratory tuberculosis",
            "doris_certificate": {**DORIS_CERTIFICATE, "ICDVersion": "ICD10"}})
        self._post(self._bundle([coding], bundle_seq=2))
        codes, engines = self._who()
        with codes, engines:
            self.assertEqual(service.apply_pending_coding()["rejected"], 1)
        row = db.session.get(VaBundlePendingCoding, uuid.UUID(coding["client_id"]))
        self.assertEqual((row.status, row.code), ("rejected", "invalid_doris"))
        self.assertIsNone(self._final(draft.va_sid))
        # The coder's allocation taken for it is released again.
        from app.services.coder_workflow_service import get_active_coding_allocation
        self.assertIsNone(get_active_coding_allocation(self.coder.user_id))

    def test_a_doris_final_stays_pending_while_the_who_service_is_down(self):
        from app.models import VaBundlePendingCoding
        from app.services import doris_processing
        from app.services.who_icd_api import WhoIcdApiUnavailable

        self._project_mode("unmasked_doris")
        interview, draft = self._interviewed_case()
        self._ready(draft.va_sid)
        coding = self._station_coding(interview, "icd11_doris")
        self._post(self._bundle([coding], bundle_seq=2))
        with mock.patch.object(doris_processing, "verify_certificate_codes", side_effect=WhoIcdApiUnavailable("x")):
            self.assertEqual(service.apply_pending_coding(), {"applied": 0, "rejected": 0, "pending": 1})
        row = db.session.get(VaBundlePendingCoding, uuid.UUID(coding["client_id"]))
        self.assertEqual((row.status, row.code), ("pending", "doris_pending"))
        self.assertIsNone(self._final(draft.va_sid))

    def test_an_icd11_doris_not_codeable_is_applied_at_once(self):
        from app.services.workflow.state_store import get_submission_workflow_state

        self._project_mode("unmasked_doris")
        interview, draft = self._interviewed_case()
        self._ready(draft.va_sid)
        coding = self._station_coding(interview, "icd11_doris", kind="not_codeable")
        records = self._by_id(self._post(self._bundle([coding], bundle_seq=2)))
        self.assertEqual(records[coding["client_id"]]["outcome"], "accepted", records)
        self.assertNotIn(get_submission_workflow_state(draft.va_sid), ("ready_for_coding", "coding_in_progress"))

    def test_a_station_mode_must_match_the_project_mode(self):
        interview, draft = self._interviewed_case()
        unknown = self._station_coding(interview, "icd9")
        masked_no_step1 = self._station_coding(interview, "icd10")
        masked_doris = self._station_coding(interview, "icd11_doris")
        records = self._by_id(self._post(self._bundle([unknown, masked_no_step1, masked_doris], bundle_seq=2)))
        # The project is masked simple: an ICD-10 final needs its Step 1, a DORIS one never fits.
        self.assertEqual(records[unknown["client_id"]]["code"], "coding_mode_unsupported")
        self.assertEqual(records[masked_no_step1["client_id"]]["code"], "coding_mode_mismatch")
        self.assertEqual(records[masked_doris["client_id"]]["code"], "coding_mode_mismatch")
        # With its Step 1 an icd10 result fits a masked simple project (held: not ready).
        with_step1 = self._station_coding(interview, "icd10", initial={
            "immediate_cod": "I64", "antecedent_cod": "I64", "other_conditions": []})
        records = self._by_id(self._post(self._bundle([with_step1], bundle_seq=3)))
        self.assertEqual(records[with_step1["client_id"]]["outcome"], "pending", records)
        self._ready(draft.va_sid)
        validate, provenance = self._catalogue()
        with validate, provenance:
            self.assertEqual(service.apply_pending_coding()["applied"], 1)
        self.assertIsNotNone(self._final(draft.va_sid).source_initial_assessment_id)

        self._project_mode("unmasked_simple")
        doris = self._station_coding(interview, "icd11_doris")
        legacy = self._coding(interview)  # no coding_mode: v1 masked simple only
        records = self._by_id(self._post(self._bundle([doris, legacy], bundle_seq=4)))
        self.assertEqual(records[doris["client_id"]]["code"], "coding_mode_mismatch")
        self.assertEqual(records[legacy["client_id"]]["code"], "coding_mode_unsupported")

        self._project_mode("unmasked_doris")
        icd10 = self._station_coding(interview, "icd10")
        records = self._by_id(self._post(self._bundle([icd10], bundle_seq=5)))
        self.assertEqual(records[icd10["client_id"]]["code"], "coding_mode_mismatch")

        self._project_mode("masked_doris")
        doris = self._station_coding(interview, "icd11_doris")
        records = self._by_id(self._post(self._bundle([doris], bundle_seq=6)))
        self.assertEqual(records[doris["client_id"]]["code"], "coding_mode_mismatch")

    def test_a_final_text_field_must_be_text(self):
        self._project_mode("unmasked_simple")
        interview, _draft = self._interviewed_case()
        coding = self._station_coding(interview, "icd10", final={"conclusive_cod": "I64", "immediate_cod": ["I64"]})
        records = self._by_id(self._post(self._bundle([coding], bundle_seq=2)))
        self.assertEqual((records[coding["client_id"]]["code"], records[coding["client_id"]]["fields"]),
                         ("record_invalid", ["final"]))

    # ── dry run leaves nothing behind (spec 5.1) ───────────────────────────

    def test_validate_queues_no_smartva_run_or_marker(self):
        from app.services import smartva_service

        interview, draft = self._interviewed_case()
        newer = dict(self._interview({"death_id": str(draft.death_id)}, client_id=interview["client_id"],
                                     answers={"Id10013": "yes", "Id10019": "female", "narr_language": "english"},
                                     completed_at=datetime.now(UTC) + timedelta(minutes=5)))
        with mock.patch.object(smartva_service, "set_run_marker") as marker, \
                mock.patch.object(smartva_service, "enqueue_smartva") as enqueue:
            response = self._post(self._bundle([newer], bundle_seq=2), path=f"{URL}/validate")
        self.assertEqual(response.status_code, 200, response.get_json())
        entry = self._by_id(response)[newer["client_id"]]
        self.assertEqual(entry["outcome"], "not_processed", entry)
        self.assertIsNone(entry["death_id"])
        marker.assert_not_called()
        enqueue.assert_not_called()
        db.session.refresh(draft)
        self.assertEqual(draft.answers_sha256, interview["answers_sha256"])

    # ── spec 9: previous KEM key, two versions of one interview ────────────

    def test_a_bundle_sealed_to_the_previous_kem_key_opens(self):
        from app.utils import pii_crypto

        current = pii_crypto._keyring()
        previous_public, previous_private = pii_crypto.generate_keyset("prev1")
        keyring = pii_crypto.Keyring(current.public, {**current.private, "prev1": previous_private},
                                     current.blind_key)
        registration = self._registration()
        with mock.patch.dict(self.app.extensions, {"pii_keyring": keyring}):
            response = self._post(self._bundle([registration], public_key=previous_public))
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["kem_key_id"], "prev1")
        self.assertEqual(self._by_id(response)[registration["client_id"]]["outcome"], "accepted")

    def test_the_newer_interview_version_wins_across_two_bundles(self):
        registration = self._registration()
        ref = {"client_death_id": registration["client_id"]}
        now = datetime.now(UTC)
        first = self._interview(ref, completed_at=now - timedelta(hours=1))
        older = dict(self._interview(ref, client_id=first["client_id"], completed_at=now - timedelta(hours=2),
                                     answers={"Id10013": "yes", "Id10019": "female", "narr_language": "english"}))
        newer = dict(self._interview(ref, client_id=first["client_id"], completed_at=now,
                                     answers={"Id10013": "yes", "Id10019": "male", "narr_language": "hindi"}))
        self.assertEqual(self._by_id(self._post(self._bundle([registration, first])))[
            first["client_id"]]["outcome"], "accepted")
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.client_draft_id == uuid.UUID(first["client_id"])))

        stale = self._by_id(self._post(self._bundle([older], bundle_seq=2)))[older["client_id"]]
        self.assertEqual((stale["outcome"], stale["received_sha256"]), ("superseded", older["answers_sha256"]))
        db.session.refresh(draft)
        self.assertEqual(draft.answers_sha256, first["answers_sha256"])

        fresh = self._by_id(self._post(self._bundle([newer], bundle_seq=3)))[newer["client_id"]]
        self.assertEqual((fresh["outcome"], fresh["received_sha256"]), ("accepted", newer["answers_sha256"]))
        db.session.refresh(draft)
        self.assertEqual(draft.answers_sha256, newer["answers_sha256"])

    # ── conformance vectors (digitva-gb8w.6; scenario table in tests/bundle_vectors.py) ──

    def _vector_kit(self, scenario):
        """A kit for *scenario* on a station of its own (the hourly bundle limit is per device)."""
        key = Ed25519PrivateKey.generate()
        station = self._onboard_paste_station(key)
        return _LiveKit(self, key, station, station_config_service.latest_config(station.device_id).config_id)

    def _apply_setup(self, kit, token):
        if token == "unknown_device":
            kit.device = mock.Mock(device_id=uuid.uuid4())
        elif token == "unissued_config":
            kit.config_id = uuid.uuid4()
        elif token == "revoked_station":
            kit.device.revoked_at = datetime.now(UTC) - timedelta(hours=1)
            db.session.commit()
        elif token == "superseded_config":
            station_config_service.issue_config(self.base_admin_user, PROJECT, kit.device.device_id)
            self.assertNotEqual(station_config_service.latest_config(kit.device.device_id).config_id, kit.config_id)
        elif token.startswith("project_mode:"):
            self._project_mode(token.split(":", 1)[1])
        elif token == "ready":
            draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(
                VaWebIntakeDraft.client_draft_id == uuid.UUID(kit.last_interview["client_id"])))
            self._ready(draft.va_sid)
        else:
            self.fail(f"unknown vector setup token {token}")

    def test_the_conformance_vectors_ingest_as_expected(self):
        import contextlib

        from tests import bundle_vectors as vectors

        for name, _doc, _container, steps in vectors.SCENARIOS:
            with self.subTest(vector=name):
                limiter.reset()
                kit, raws = self._vector_kit(name), []
                for setup, build, expect in steps:
                    for token in setup:
                        self._apply_setup(kit, token)
                    raws.append(raws[-1] if build == "again" else vectors.oversize(kit) if build == "oversize"
                                else build(kit))
                    with contextlib.ExitStack() as stack:
                        for patch in self._catalogue():  # the ICD catalogue is not loaded in tests
                            stack.enter_context(patch)
                        response = self._post(raws[-1])
                    body = response.get_json()
                    self.assertEqual(response.status_code, expect["status"], body)
                    self.assertEqual(body.get("code"), expect["code"], body)
                    if expect["records"]:
                        self.assertEqual([[r["record_type"], r["outcome"], r["code"]] for r in body["records"]],
                                         expect["records"], body)


class _LiveKit:
    """tests/bundle_vectors.py's ``FixedKit`` interface over this test case's builders and one live station."""

    fixed = False

    def __init__(self, case, key, device, config_id):
        self.case, self.key, self.device, self.config_id = case, key, device, config_id
        self._ids, self.last_interview, self.signing_key_id = {}, None, bb.key_id(key)

    def id(self, name):
        return self._ids.setdefault(name, uuid.uuid4())

    def registration(self, name="reg", consent=None, **fields):
        return self.case._registration(consent=consent, client_id=self.id(name), **fields)

    def consent(self, death_ref, name="consent", granted=True):
        return self.case._consent(death_ref, granted=granted)

    def interview(self, death_ref, name="interview", consent_client_id=None, answers=None):
        from tests import bundle_vectors as vectors

        record = self.case._interview(death_ref, consent_client_id=consent_client_id, client_id=self.id(name),
                                      answers=None if answers in (None, vectors.ANSWERS) else json.loads(answers))
        self.last_interview = record
        return record

    def coding(self, interview, mode, name="coding"):
        return self.case._station_coding(interview, mode)

    def bundle(self, records, *, key=None, bundle_id=None, bundle_seq=1, **kwargs):
        extra = {"bundle_id": bundle_id} if bundle_id else {}
        return self.case._bundle(records, key=key or self.key, device=self.device, config_id=self.config_id,
                                 bundle_seq=bundle_seq, **extra, **kwargs)
