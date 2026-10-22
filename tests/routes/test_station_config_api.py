"""Offline station onboarding and the signed station config (digitva-gb8w.4,
digitva-gb8w.8): custodian, roster, issue, browser download and the
station's own ``GET /api/v1/intake/station-config``.

Contract docs/policy/offline-api-contract.md 3.8, 4.1, 6.6, 7, 11; file
format docs/policy/offline-bundle-and-transfer.md 6.4.
"""
import base64
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import mock

import sqlalchemy as sa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app import db, limiter
from app.models import (
    AuthDevice,
    AuthSecurityEvent,
    AuthStationConfig,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import consent_service
from app.services import device_auth_service as devices
from app.services import station_config_service as service
from app.services.pii_field_registry import sealed_field_ids
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase
from tests.routes.test_device_api import _FreshGClient

PASSWORD = "StationCfg123!"
PROJECT_ID = "STC01"
OTHER_PROJECT = "STC02"
SITE_ID = "SC01"
OTHER_SITE = "SC02"
KEY_FILE = str(Path(__file__).resolve().parents[1] / "fixtures" / "station_config" / "test_server_signing_key")
NOTICE = "Station consent notice. **Required**: record the death."


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _station_key() -> str:
    raw = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64u(raw)


class StationConfigApiTests(BaseTestCase):

    @classmethod
    def _project(cls, project_id, site_id, now):
        db.session.add(VaProjectMaster(
            project_id=project_id, project_code=project_id, project_name=f"Station {project_id}",
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
    def _grant(cls, user, project_id, role):
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
            project_id=project_id, notes="station config test grant", grant_status=VaStatuses.active,
        ))
        db.session.flush()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._project(PROJECT_ID, SITE_ID, now)
        cls._project(OTHER_PROJECT, OTHER_SITE, now)
        cls.interviewer = cls._get_or_make_user("station.interviewer@test.local", PASSWORD)
        cls.coder = cls._get_or_make_user("station.coder@test.local", PASSWORD)
        cls.manager = cls._get_or_make_user("station.dm@test.local", PASSWORD)
        cls.other_manager = cls._get_or_make_user("station.other.dm@test.local", PASSWORD)
        cls._grant(cls.interviewer, PROJECT_ID, VaAccessRoles.interviewer)
        cls._grant(cls.coder, PROJECT_ID, VaAccessRoles.coder)
        cls._grant(cls.manager, PROJECT_ID, VaAccessRoles.data_manager)
        cls._grant(cls.other_manager, OTHER_PROJECT, VaAccessRoles.data_manager)
        consent_service.create_notice_version(cls.base_admin_user, PROJECT_ID, {
            "language": "en", "text": NOTICE,
            "purposes": [{"code": "record_interview", "label": "Record", "required": True}],
            "allowed_modes": ["spoken", "tap"], "witness_allowed": False,
        })
        consent_service.save_settings(cls.base_admin_user, PROJECT_ID, {"consent_required": True})
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = _FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self._saved_key_file = self.app.config.get("BUNDLE_SERVER_SIGNING_KEY_FILE")
        self.app.config["BUNDLE_SERVER_SIGNING_KEY_FILE"] = KEY_FILE

    def tearDown(self):
        self.app.config["BUNDLE_SERVER_SIGNING_KEY_FILE"] = self._saved_key_file
        super().tearDown()

    # ── helpers ────────────────────────────────────────────────────────────

    def _enrol(self, *, key=True):
        _row, code = devices.create_enrolment_code(PROJECT_ID, actor=self.base_admin_user)
        db.session.commit()
        body = {"code": code, "device_name": "PHC station", "platform": "desktop", "app_version": "0.1.0"}
        if key:
            body["signing_public_key"] = _station_key()
        response = self.client.post("/api/v1/auth/enroll", json=body)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def _bearer_for(self, device):
        response = self.client.post("/api/v1/auth/sessions", json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "email": "station.interviewer@test.local", "password": PASSWORD,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return {"Authorization": f"Bearer {response.get_json()['access_token']}"}

    def _url(self, device_id, tail=""):
        return f"/api/v1/projects/{PROJECT_ID}/stations/{device_id}{tail}"

    def _custodian(self, device_id, **overrides):
        body = {"name": "Dr. Meera Rao", "designation": "medical_officer", "phone": "+91 98765-43210",
                "email": None, "onboarded_on": date.today().isoformat(), **overrides}
        return self.client.put(self._url(device_id, "/custodian"), json=body, headers=self._csrf_headers())

    def _roster(self, device_id, members):
        return self.client.put(self._url(device_id, "/roster"), json={"members": members},
                               headers=self._csrf_headers())

    def _member(self, user, *roles, designation="health_worker", active=True):
        return {"user_id": str(user.user_id), "designation": designation, "active": active,
                "roles": [{"role": r, "site_id": SITE_ID, "org_unit_id": None} for r in roles]}

    def _issue(self, device_id):
        return self.client.post(f"/api/v1/projects/{PROJECT_ID}/station-config?device_id={device_id}",
                                headers=self._csrf_headers())

    def _download(self, device_id, headers=None):
        return self.client.get(f"/api/v1/projects/{PROJECT_ID}/station-config?device_id={device_id}",
                               headers=headers or {})

    def _onboard(self, device_id):
        self.assertEqual(self._custodian(device_id).status_code, 200)
        response = self._roster(device_id, [
            self._member(self.interviewer, "interviewer"),
            self._member(self.coder, "coder"),
            self._member(self.manager, "station_supervisor", designation="health_supervisor"),
        ])
        self.assertEqual(response.status_code, 200, response.get_json())
        issued = self._issue(device_id)
        self.assertEqual(issued.status_code, 201, issued.get_json())
        return issued.get_json()

    def _events(self, event_type, device_id):
        rows = db.session.scalars(sa.select(AuthSecurityEvent).where(AuthSecurityEvent.event_type == event_type)).all()
        return [r for r in rows if (r.detail or {}).get("device_id") == str(device_id)]

    # ── the issued file ────────────────────────────────────────────────────

    def test_issued_config_is_signed_and_carries_the_contract_fields(self):
        device = self._enrol()
        self._login(str(self.manager.user_id))
        issued = self._onboard(device["device_id"])
        response = self._download(device["device_id"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        text = response.get_data(as_text=True)
        line1, line2, tail = text.split("\n")
        self.assertEqual(tail, "")

        signature = json.loads(line2)
        public = service.public_signing_key(service.parse_signing_key(Path(KEY_FILE).read_text()))
        self.assertEqual(signature["signing_key_id"], public["signing_key_id"])
        Ed25519PublicKey.from_public_bytes(service.decode_b64url(public["public"])).verify(
            service.decode_b64url(signature["sig"]), service.STATION_CONFIG_SIG_DOMAIN + line1.encode())
        self.assertEqual(line1.encode(), service.canonical_json(json.loads(line1)))

        payload = json.loads(line1)
        self.assertEqual(payload["config_id"], issued["config"]["config_id"])
        self.assertEqual(payload["device_id"], device["device_id"])
        self.assertEqual(payload["station_config_format_version"], 1)
        self.assertEqual(payload["server_signing_key"], public)
        self.assertEqual(set(payload["kem_public_key"]), {"key_id", "public"})
        project = payload["projects"][0]
        self.assertEqual(project["project_id"], PROJECT_ID)
        self.assertEqual(project["sites"], [SITE_ID])
        self.assertEqual(project["site_names"], {SITE_ID: f"Site {SITE_ID}"})
        # No unit on any role: the unit maps are left out, as the station's writer does.
        self.assertNotIn("org_unit_paths", project)
        self.assertNotIn("org_unit_sites", project)
        self.assertEqual(project["consent"], consent_service.get_consent_config(PROJECT_ID))
        self.assertTrue(project["consent"]["notice_versions"])
        self.assertIn("Id10073", project["sealed_field_ids"])
        self.assertEqual(project["sealed_field_ids"], sorted(sealed_field_ids("WHO_2022_VA")))
        self.assertEqual(project["project_name"], db.session.get(VaProjectMaster, PROJECT_ID).project_name)
        # A masked simple project (the default) has no station coding mode.
        self.assertIn("coding_mode", project)
        self.assertIsNone(project["coding_mode"])
        self.assertEqual(payload["designations"][0], {"code": "medical_officer", "label": "Medical Officer"})
        self.assertEqual(payload["purge"], [])

        custodian = payload["custodian"]
        self.assertEqual(custodian["phone"], "9876543210")
        self.assertIsNone(custodian["email"])
        self.assertEqual(custodian["verified_by_user_id"], self.manager.user_number)

        roster = payload["roster"]
        self.assertEqual([m["user_id"] for m in roster], sorted(m["user_id"] for m in roster))
        by_id = {m["user_id"]: m for m in roster}
        supervisor = by_id[self.manager.user_number]
        self.assertEqual(supervisor["roles"], [{"role": "station_supervisor", "project_id": PROJECT_ID,
                                                "site_id": SITE_ID, "org_unit_id": None}])
        self.assertEqual(set(supervisor), {"user_id", "name", "designation", "roles", "active"})
        self.assertNotIn("email", line1.split('"roster"')[1])

    def test_config_carries_the_projects_form_policy_and_offered_translations(self):
        """The station offers exactly what the project offers on the server: its
        form-options body, the served definition's sha of its modules, and one
        translations body per offered non-English locale (a disabled module and
        a servable locale the project does not offer are absent)."""
        from app.models.mas_instrument_locales import (
            LIFECYCLE_APPROVED,
            LIFECYCLE_IN_REVIEW,
            MapInstrumentTranslations,
            MasInstrumentLocales,
        )
        from app.routes.api.organization import form_options_payload
        from app.services import served_form_service
        from app.services.instrument_translation_service import export_translations

        def locale(code, *, active, state, version):
            row = db.session.get(MasInstrumentLocales, ("WHO_2022_VA", code))
            if row is None:
                row = MasInstrumentLocales(instrument_code="WHO_2022_VA", locale_code=code, language_name=code,
                                           version=version, is_active=active, updated_at=datetime.now(UTC),
                                           lifecycle_state=state)
                db.session.add(row)
            row.is_active, row.lifecycle_state, row.version = active, state, version
            db.session.flush()

        locale("hi", active=True, state=LIFECYCLE_APPROVED, version=7)
        locale("ta", active=False, state=LIFECYCLE_IN_REVIEW, version=3)
        if db.session.scalar(sa.select(MapInstrumentTranslations).where(
                MapInstrumentTranslations.locale_code == "hi",
                MapInstrumentTranslations.item_key == "yes_no/yes")) is None:
            db.session.add(MapInstrumentTranslations(
                instrument_code="WHO_2022_VA", locale_code="hi", item_kind="choice", item_key="yes_no/yes",
                field="label", text="हाँ", source="human", updated_at=datetime.now(UTC)))
        project = db.session.get(VaProjectMaster, PROJECT_ID)
        saved = (project.web_intake_available_locales, project.social_autopsy_enabled)
        project.web_intake_available_locales = ["en", "hi"]
        project.social_autopsy_enabled = False
        db.session.commit()
        try:
            device = self._enrol()
            self._login(str(self.manager.user_id))
            self._onboard(device["device_id"])
            line1 = self._download(device["device_id"]).get_data(as_text=True).split("\n")[0]
            entry = json.loads(line1)["projects"][0]

            options = entry["form_options"]
            self.assertEqual(options, form_options_payload(db.session.get(VaProjectMaster, PROJECT_ID)))
            self.assertIn("digitva_core", options["enabled_extensions"])
            self.assertNotIn("social_autopsy", options["enabled_extensions"])
            served = served_form_service.served_definition(options["enabled_extensions"])
            self.assertEqual(options["definition_sha256"], served.sha256)
            self.assertEqual(options["instrument_version"], served_form_service.composed_version())
            self.assertEqual([loc["code"] for loc in options["available_locales"]], ["en", "hi"])
            # "ta" is servable on the server (in review) but not offered by this project.
            self.assertIn("ta", options["translation_versions"])

            self.assertEqual(sorted(entry["translations"]), ["hi"])
            self.assertEqual(entry["translations"]["hi"], export_translations("WHO_2022_VA", "hi"))
            self.assertEqual(entry["translations"]["hi"]["version"], 7)
            self.assertEqual(entry["translations"]["hi"]["choices"]["yes_no/yes"]["label"], "हाँ")
        finally:
            project = db.session.get(VaProjectMaster, PROJECT_ID)
            project.web_intake_available_locales, project.social_autopsy_enabled = saved
            db.session.commit()

    def test_device_bearer_gets_the_same_bytes_with_etag_and_304(self):
        device = self._enrol()
        headers = self._bearer_for(device)
        self._login(str(self.manager.user_id))
        self._onboard(device["device_id"])
        browser = self._download(device["device_id"])
        self.client.delete_cookie("session")

        fetched = self.client.get("/api/v1/intake/station-config", headers=headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.get_data(), browser.get_data())
        self.assertEqual(fetched.headers["Cache-Control"], "no-store")
        etag = fetched.headers["ETag"]
        self.assertTrue(etag)
        self.assertEqual(etag, browser.headers["ETag"])
        again = self.client.get("/api/v1/intake/station-config", headers={**headers, "If-None-Match": etag})
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.get_data(), b"")

    def test_reissue_replaces_the_config_in_force(self):
        device = self._enrol()
        self._login(str(self.manager.user_id))
        first = self._onboard(device["device_id"])["config"]["config_id"]
        second = self._issue(device["device_id"]).get_json()["config"]["config_id"]
        self.assertNotEqual(first, second)
        payload = json.loads(self._download(device["device_id"]).get_data(as_text=True).split("\n")[0])
        self.assertEqual(payload["config_id"], second)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuthStationConfig).where(
            AuthStationConfig.device_id == uuid.UUID(device["device_id"]))), 2)

    # ── not issued, other devices, revoked ─────────────────────────────────

    def test_no_config_issued_is_404_and_issue_needs_custodian_and_roster(self):
        device = self._enrol()
        headers = self._bearer_for(device)
        missing = self.client.get("/api/v1/intake/station-config", headers=headers)
        self.assertEqual((missing.status_code, missing.get_json()["code"]), (404, "not_found"))

        self._login(str(self.manager.user_id))
        self.assertEqual(self._download(device["device_id"]).status_code, 404)
        refused = self._issue(device["device_id"])
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (409, "station_not_onboarded"))
        self.assertEqual(self._custodian(device["device_id"]).status_code, 200)
        self.assertEqual(self._issue(device["device_id"]).get_json()["code"], "station_not_onboarded")
        self.assertEqual(self._roster(device["device_id"], [self._member(self.interviewer, "interviewer")]).status_code, 200)
        self.assertEqual(self._issue(device["device_id"]).status_code, 201)

    def test_a_station_without_a_signing_key_cannot_be_issued_a_config(self):
        device = self._enrol(key=False)
        self._login(str(self.manager.user_id))
        self._custodian(device["device_id"])
        self._roster(device["device_id"], [self._member(self.interviewer, "interviewer")])
        refused = self._issue(device["device_id"])
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (409, "station_not_onboarded"))

    def test_another_devices_bearer_gets_only_its_own_config(self):
        device = self._enrol()
        other = self._enrol()
        other_headers = self._bearer_for(other)
        self._login(str(self.manager.user_id))
        self._onboard(device["device_id"])
        self.client.delete_cookie("session")
        response = self.client.get("/api/v1/intake/station-config", headers=other_headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["code"], "not_found")

    def test_revoked_device_is_refused(self):
        device = self._enrol()
        headers = self._bearer_for(device)
        self._login(str(self.manager.user_id))
        self._onboard(device["device_id"])
        self.client.delete_cookie("session")
        self.assertEqual(self.client.get("/api/v1/intake/station-config", headers=headers).status_code, 200)
        devices.revoke_device(db.session.get(AuthDevice, uuid.UUID(device["device_id"])), actor=self.base_admin_user)
        db.session.commit()
        # The revoke ends the bearer session (401) before the route runs; the
        # service answers 403 device_revoked to any later lookup.
        self.assertEqual(self.client.get("/api/v1/intake/station-config", headers=headers).status_code, 401)
        with self.assertRaises(service.StationConfigError) as caught:
            service.device_config(uuid.UUID(device["device_id"]))
        self.assertEqual((caught.exception.status, caught.exception.code), (403, "device_revoked"))
        self._login(str(self.manager.user_id))
        refused = self._issue(device["device_id"])
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (409, "device_revoked"))

    def test_device_route_refuses_a_browser_session_and_browser_routes_refuse_a_bearer(self):
        device = self._enrol()
        headers = self._bearer_for(device)
        self.assertEqual(self.client.get("/api/v1/intake/station-config").status_code, 401)
        self._login(str(self.manager.user_id))
        cookie = self.client.get("/api/v1/intake/station-config")
        self.assertEqual((cookie.status_code, cookie.get_json()["code"]), (403, "device_session_required"))
        self.client.delete_cookie("session")
        self.assertEqual(self._download(device["device_id"], headers=headers).status_code, 403)

    # ── authorization, CSRF, audit ─────────────────────────────────────────

    def test_other_project_manager_and_interviewer_are_refused(self):
        device = self._enrol()
        self._login(str(self.manager.user_id))
        self.assertEqual(self._custodian(device["device_id"]).status_code, 200)

        self._login(str(self.other_manager.user_id))
        self.assertEqual(self._custodian(device["device_id"]).status_code, 404)
        self.assertEqual(self._issue(device["device_id"]).status_code, 404)
        self.assertEqual(self._download(device["device_id"]).status_code, 404)
        # Their own project does not hold this device either.
        other_url = f"/api/v1/projects/{OTHER_PROJECT}/stations/{device['device_id']}"
        self.assertEqual(self.client.get(other_url).status_code, 404)

        self._login(str(self.interviewer.user_id))
        self.assertEqual(self._custodian(device["device_id"]).status_code, 403)
        self.assertEqual(self._download(device["device_id"]).status_code, 403)

    def test_admin_may_onboard(self):
        device = self._enrol()
        self._login(str(self.base_admin_id))
        self.assertEqual(self._onboard(device["device_id"])["custodian"]["verified_by"], str(self.base_admin_id))

    def test_state_changes_need_the_csrf_header(self):
        device = self._enrol()
        self._login(str(self.manager.user_id))
        body = {"name": "X", "designation": "other", "phone": "9876543210", "onboarded_on": "2026-01-01"}
        self.assertEqual(self.client.put(self._url(device["device_id"], "/custodian"), json=body).status_code, 400)
        self.assertEqual(self.client.put(self._url(device["device_id"], "/roster"), json={"members": []}).status_code, 400)
        self.assertEqual(self.client.post(
            f"/api/v1/projects/{PROJECT_ID}/station-config?device_id={device['device_id']}").status_code, 400)
        self.assertEqual(self.client.get(self._url(device["device_id"])).get_json()["custodian"], None)

    def test_every_change_is_audited_without_contact_values(self):
        device = self._enrol()
        self._login(str(self.manager.user_id))
        self._onboard(device["device_id"])
        custodian = self._events("station_custodian_set", device["device_id"])
        self.assertEqual(len(custodian), 1)
        self.assertEqual(custodian[0].actor_user_id, self.manager.user_id)
        self.assertIn("phone", custodian[0].detail["changed"])
        self.assertNotIn("9876543210", json.dumps(custodian[0].detail))
        roster = self._events("station_roster_set", device["device_id"])
        self.assertEqual(len(roster), 1)
        self.assertIn(str(self.coder.user_id), roster[0].detail["added"])
        issued = self._events("station_config_issued", device["device_id"])
        self.assertEqual(len(issued), 1)
        self.assertEqual(issued[0].detail["roster_members"], 3)

        self._roster(device["device_id"], [self._member(self.interviewer, "interviewer")])
        roster = self._events("station_roster_set", device["device_id"])
        self.assertEqual(len(roster), 2)
        latest = next(r for r in roster if r.detail["removed"])
        self.assertEqual(sorted(latest.detail["removed"]), sorted([str(self.coder.user_id), str(self.manager.user_id)]))

    # ── validation ─────────────────────────────────────────────────────────

    def test_custodian_validation(self):
        device = self._enrol()
        self._login(str(self.manager.user_id))
        cases = [
            ({"phone": None, "email": None}, "phone"),
            ({"phone": "12345"}, "phone"),
            ({"email": "not-an-email", "phone": None}, "email"),
            ({"designation": "chief"}, "designation"),
            ({"name": "  "}, "name"),
            ({"onboarded_on": (date.today() + timedelta(days=5)).isoformat()}, "onboarded_on"),
            ({"onboarded_on": "21/10/2026"}, "onboarded_on"),
        ]
        for overrides, field in cases:
            with self.subTest(field=field, overrides=overrides):
                response = self._custodian(device["device_id"], **overrides)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["fields"], [field])
        extra = self.client.put(self._url(device["device_id"], "/custodian"), headers=self._csrf_headers(),
                                json={"name": "A", "designation": "other", "phone": "9876543210",
                                      "onboarded_on": "2026-01-01", "verified_by": "x"})
        self.assertEqual(extra.status_code, 400)
        ok = self._custodian(device["device_id"], phone=None, email="mo@phc.example")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.get_json()["custodian"]["email"], "mo@phc.example")

    def test_roster_roles_come_only_from_the_allowed_set_and_grants(self):
        device = self._enrol()
        self._login(str(self.manager.user_id))
        unknown = self._roster(device["device_id"], [self._member(self.interviewer, "admin")])
        self.assertEqual((unknown.status_code, unknown.get_json()["fields"]), (400, ["members[0].roles[0].role"]))

        # An interviewer holds no supervising grant: owner decision 10.
        no_grant = self._roster(device["device_id"], [self._member(self.interviewer, "station_supervisor")])
        self.assertEqual((no_grant.status_code, no_grant.get_json()["code"]), (422, "invalid_roster"))
        self.assertEqual(no_grant.get_json()["fields"], ["members[0].roles[0]"])
        # A coder is not an interviewer.
        self.assertEqual(self._roster(device["device_id"], [self._member(self.coder, "interviewer")]).status_code, 422)
        # Nor at a site of another project.
        other_site = self._member(self.interviewer, "interviewer")
        other_site["roles"][0]["site_id"] = OTHER_SITE
        self.assertEqual(self._roster(device["device_id"], [other_site]).status_code, 422)

        twice = self._roster(device["device_id"], [self._member(self.interviewer, "interviewer")] * 2)
        self.assertEqual(twice.status_code, 400)
        bad_designation = self._roster(device["device_id"], [self._member(self.interviewer, "interviewer",
                                                                          designation="boss")])
        self.assertEqual(bad_designation.get_json()["fields"], ["members[0].designation"])
        no_roles = self._roster(device["device_id"], [self._member(self.interviewer)])
        self.assertEqual(no_roles.get_json()["fields"], ["members[0].roles"])

        # An inactive member keeps roles the server no longer backs.
        ok = self._roster(device["device_id"], [
            self._member(self.interviewer, "interviewer", "death_reporter", active=False),
            self._member(self.manager, "station_supervisor", designation="medical_officer"),
        ])
        self.assertEqual(ok.status_code, 200, ok.get_json())
        roster = {m["user_id"]: m for m in ok.get_json()["roster"]}
        self.assertFalse(roster[str(self.interviewer.user_id)]["active"])
        self.assertEqual([r["role"] for r in roster[str(self.interviewer.user_id)]["roles"]],
                         ["death_reporter", "interviewer"])

    def test_issue_rechecks_grants_and_names_the_stale_users(self):
        device = self._enrol()
        self._login(str(self.manager.user_id))
        self._custodian(device["device_id"])
        self._roster(device["device_id"], [self._member(self.coder, "coder"),
                                           self._member(self.interviewer, "interviewer")])
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.coder.user_id, VaUserAccessGrants.role == VaAccessRoles.coder))
        grant.grant_status = VaStatuses.deactive
        db.session.commit()
        try:
            refused = self._issue(device["device_id"])
            self.assertEqual((refused.status_code, refused.get_json()["code"]), (422, "invalid_roster"))
            self.assertEqual(refused.get_json()["fields"], [str(self.coder.user_id)])
        finally:
            grant.grant_status = VaStatuses.active
            db.session.commit()

    def test_inactive_members_still_need_the_project_and_its_places(self):
        device = self._enrol()
        self._login(str(self.manager.user_id))
        stranger = self._get_or_make_user("station.stranger@test.local", PASSWORD)
        refused = self._roster(device["device_id"], [self._member(stranger, "interviewer", active=False)])
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (422, "invalid_roster"))
        self.assertEqual(refused.get_json()["fields"], ["members[0].user_id"])

        other_site = self._member(self.interviewer, "interviewer", active=False)
        other_site["roles"][0]["site_id"] = OTHER_SITE
        refused = self._roster(device["device_id"], [other_site])
        self.assertEqual(refused.get_json()["fields"], ["members[0].roles[0].site_id"])
        foreign_unit = self._member(self.interviewer, "interviewer", active=False)
        foreign_unit["roles"][0]["org_unit_id"] = str(uuid.uuid4())
        refused = self._roster(device["device_id"], [foreign_unit])
        self.assertEqual(refused.get_json()["fields"], ["members[0].roles[0].org_unit_id"])

        # A member already on this roster may be kept inactive after the grant goes.
        self.assertEqual(self._roster(device["device_id"], [self._member(self.coder, "coder")]).status_code, 200)
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.coder.user_id, VaUserAccessGrants.role == VaAccessRoles.coder))
        grant.grant_status = VaStatuses.deactive
        db.session.commit()
        try:
            kept = self._roster(device["device_id"], [self._member(self.coder, "coder", active=False)])
            self.assertEqual(kept.status_code, 200, kept.get_json())
        finally:
            grant.grant_status = VaStatuses.active
            db.session.commit()

    def test_project_entry_names_sites_and_unit_paths(self):
        from app.services import organization_service as org

        org.seed_default_organization(PROJECT_ID)
        levels = {lv.level_code: lv for lv in org.list_levels(PROJECT_ID)}

        def unit(level, code, parent=None):
            return org.create_unit(PROJECT_ID, org_level_id=levels[level].org_level_id, unit_code=code,
                                   unit_name=f"Unit {code}", parent_org_unit_id=parent.org_unit_id if parent else None)

        phc = unit("phc", "SP1", unit("chc", "SC1", unit("district", "SD1")))
        db.session.commit()
        device = self._enrol()
        self._login(str(self.manager.user_id))
        self.assertEqual(self._custodian(device["device_id"]).status_code, 200)
        member = self._member(self.interviewer, "interviewer")
        member["roles"][0]["org_unit_id"] = str(phc.org_unit_id)
        response = self._roster(device["device_id"], [member, self._member(self.coder, "coder")])
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._issue(device["device_id"]).status_code, 201)
        project = json.loads(self._download(device["device_id"]).get_data(as_text=True).split("\n")[0])["projects"][0]
        self.assertEqual(project["site_names"], {SITE_ID: f"Site {SITE_ID}"})
        self.assertEqual(project["org_units"], [str(phc.org_unit_id)])
        self.assertEqual(project["org_unit_paths"], {str(phc.org_unit_id): "Unit SD1, Unit SC1, Unit SP1"})
        self.assertEqual(project["org_unit_sites"], {str(phc.org_unit_id): SITE_ID})

    def test_project_entry_locks_the_station_coding_mode_to_the_projects(self):
        """Contract 4.3: the station codes a project only in the mode the
        project's own coding mode maps to; null where it has none."""
        project = db.session.get(VaProjectMaster, PROJECT_ID)
        expected = {
            ("unmasked", "doris"): "icd11_doris",
            ("unmasked", "simple"): "icd10",
            ("masked", "doris"): None,  # no station workspace for masked DORIS
            ("masked", "simple"): None,  # needs Step 1, which the station does not make
        }
        for (masking, entry), mode in expected.items():
            with self.subTest(masking=masking, entry=entry):
                project.masked_cod_required = masking == "masked"
                project.cod_entry_mode = entry
                project.icd_classification = "icd11" if entry == "doris" else "icd10"  # DB check
                db.session.flush()
                self.assertEqual(service._project_entry(PROJECT_ID, [])["coding_mode"], mode)

    def test_issue_refuses_without_a_server_url_or_a_canonical_payload(self):
        device = self._enrol()
        self._login(str(self.manager.user_id))
        self._custodian(device["device_id"])
        self._roster(device["device_id"], [self._member(self.interviewer, "interviewer")])
        with mock.patch.dict(self.app.config, {"DEVICE_PUBLIC_URL": ""}):
            refused = self._issue(device["device_id"])
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (503, "station_config_unavailable"))
        with mock.patch.object(service, "sign_station_config", side_effect=ValueError("no canonical form")):
            refused = self._issue(device["device_id"])
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (409, "config_not_canonical"))
        self.assertEqual(self._download(device["device_id"]).status_code, 404)

    def test_the_published_test_key_is_refused_outside_testing(self):
        self.app.extensions.pop("station_config_signing_keys", None)
        with mock.patch.dict(self.app.config, {"TESTING": False}):
            with self.assertRaises(service.StationConfigError) as refused:
                service.server_signing_key()
        self.assertEqual(refused.exception.code, "station_config_unavailable")
        self.assertEqual(service.public_signing_key(service.server_signing_key())["signing_key_id"],
                         service.FIXTURE_SIGNING_KEY_ID)

    def test_signing_key_missing_is_503(self):
        device = self._enrol()
        self._login(str(self.manager.user_id))
        self._custodian(device["device_id"])
        self._roster(device["device_id"], [self._member(self.interviewer, "interviewer")])
        self.app.config["BUNDLE_SERVER_SIGNING_KEY_FILE"] = ""
        refused = self._issue(device["device_id"])
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (503, "station_config_unavailable"))

    def test_device_fetch_is_limited_per_device(self):
        device = self._enrol()
        headers = self._bearer_for(device)
        for _ in range(60):
            self.assertEqual(self.client.get("/api/v1/intake/station-config", headers=headers).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/intake/station-config", headers=headers).status_code, 429)
        other = self._enrol()
        self.assertEqual(self.client.get("/api/v1/intake/station-config",
                                         headers=self._bearer_for(other)).status_code, 404)

    def test_a_notice_text_not_in_nfc_is_refused(self):
        device = self._enrol()
        self._login(str(self.manager.user_id))
        self._custodian(device["device_id"])
        self._roster(device["device_id"], [self._member(self.interviewer, "interviewer")])
        config = consent_service.get_consent_config(PROJECT_ID)
        self.assertTrue(config["notice_versions"])
        config["notice_versions"][0]["text"] = "e\u0301"
        with mock.patch.object(service.consent_service, "get_consent_config", return_value=config):
            refused = self._issue(device["device_id"])
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (409, "notice_not_nfc"))
        self.assertEqual(self._download(device["device_id"]).status_code, 404)
