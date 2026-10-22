"""Device Ed25519 bundle-signing keys (bead digitva-gb8w.5).

Policy: docs/policy/offline-bundle-and-transfer.md section 3.2; contract
docs/policy/offline-api-contract.md 3.1 and 3.8. Covers the optional key on
``POST /api/v1/auth/enroll``, the set-once ``POST
/api/v1/auth/devices/current/signing-key``, the admin registration of a
never-online station from its enrolment file, the compromised revoke, the
bundle-ingest key lookup and the signature check, and the key id parity
with ``compute_signing_key_id`` in desktop/crates/digitva-bundle.
"""
import base64
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import db, limiter
from app.models import (
    AuthDevice,
    AuthDeviceSigningKey,
    AuthSecurityEvent,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import device_auth_service as devices
from app.services import device_signing_service as signing
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase
from tests.routes.test_device_api import _FreshGClient

API = "/api/v1/auth"
PASSWORD = "SigningKey123!"
PROJECT_ID = "SIG01"
SITE_ID = "SG01"
#: compute_signing_key_id(&[0u8; 32]) in desktop/crates/digitva-bundle:
#: hex of the first 8 bytes of SHA-256 of 32 zero bytes.
ZERO_KEY_ID = "66687aadf862bd77"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _keypair():
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, raw


class DeviceSigningKeyTests(BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=PROJECT_ID, project_code=PROJECT_ID, project_name="Signing project",
            project_nickname=PROJECT_ID, project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, web_intake_mode="both",
        ))
        db.session.flush()
        # A site with a web intake form, so the interviewer can open a device session.
        db.session.add(VaSiteMaster(
            site_id=SITE_ID, site_name="Signing site", site_abbr=SITE_ID,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=PROJECT_ID, site_id=SITE_ID, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(PROJECT_ID, SITE_ID)
        db.session.add(VaForms(
            form_id=f"{PROJECT_ID}{SITE_ID}01", project_id=PROJECT_ID, site_id=SITE_ID,
            odk_form_id=f"ODK_{PROJECT_ID}", odk_project_id="7", form_type="WHO VA 2022",
            form_source="odk", form_status=VaStatuses.active, form_registered_at=now,
            form_updated_at=now,
        ))
        db.session.flush()
        cls.interviewer =cls._get_or_make_user("signing.interviewer@test.local", PASSWORD)
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id, role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project, project_id=PROJECT_ID,
            notes="signing key test grant", grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = _FreshGClient(self.app, self.app.response_class, use_cookies=True)

    # ── helpers ────────────────────────────────────────────────────────────

    def _enrol(self, **extra):
        _row, code = devices.create_enrolment_code(PROJECT_ID, actor=self.base_admin_user)
        db.session.commit()
        return self.client.post(f"{API}/enroll", json={
            "code": code, "device_name": "Station 1", "platform": "desktop", "app_version": "0.1.0", **extra,
        })

    def _bearer_for(self, device):
        response = self.client.post(f"{API}/sessions", json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "email": "signing.interviewer@test.local", "password": PASSWORD,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return {"Authorization": f"Bearer {response.get_json()['access_token']}"}

    def _set_key(self, headers, key):
        return self.client.post(f"{API}/devices/current/signing-key",
                                json={"signing_public_key": key}, headers=headers)

    def _paste(self, enrolment_file, name="PHC station", headers=None):
        return self.client.post(
            f"/admin/api/projects/{PROJECT_ID}/station-registrations",
            json={"name": name, "enrolment_file": enrolment_file},
            headers=self._csrf_headers() if headers is None else headers,
        )

    def _events(self, event_type, device_id):
        rows = db.session.scalars(sa.select(AuthSecurityEvent).where(AuthSecurityEvent.event_type == event_type)).all()
        return [r for r in rows if (r.detail or {}).get("device_id") == str(device_id)]

    def _device(self, device_id):
        db.session.expire_all()
        return db.session.get(AuthDevice, uuid.UUID(str(device_id)))

    # ── key id and verify helper ───────────────────────────────────────────

    def test_key_id_matches_the_rust_crate(self):
        self.assertEqual(signing.compute_signing_key_id(bytes(32)), ZERO_KEY_ID)

    def test_verify_bundle_signature(self):
        private, raw = _keypair()
        line = b'{"bundle_id":"x"}'
        sig = private.sign(signing.BUNDLE_SIG_DOMAIN + line)
        self.assertTrue(signing.verify_bundle_signature(raw, line, sig))
        self.assertFalse(signing.verify_bundle_signature(raw, line + b" ", sig))
        self.assertFalse(signing.verify_bundle_signature(raw, line, private.sign(line)))  # no domain prefix
        self.assertFalse(signing.verify_bundle_signature(raw, line, sig[:63]))
        self.assertFalse(signing.verify_bundle_signature(_keypair()[1], line, sig))

    def test_parse_public_key_refuses_bad_encodings_and_off_curve_points(self):
        _private, raw = _keypair()
        self.assertEqual(signing.parse_public_key(_b64u(raw)), raw)
        self.assertEqual(signing.parse_public_key(_b64u(raw) + "="), raw)  # padding tolerated
        for bad in (None, 7, "", "not base64!", _b64u(raw[:31]), _b64u(raw + b"\x00"),
                    base64.b64encode(b"\xfb" * 32).decode(),  # standard alphabet (+ /)
                    _b64u(b"\xff" * 32),  # y >= p
                    _b64u((2).to_bytes(32, "little"))):  # y = 2 is not on the curve
            with self.assertRaises(devices.DeviceAuthError, msg=repr(bad)) as caught:
                signing.parse_public_key(bad)
            self.assertEqual(caught.exception.fields, ["signing_public_key"])

    # ── enrolment ──────────────────────────────────────────────────────────

    def test_enrol_without_a_key_is_unchanged(self):
        response = self._enrol()
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertIn("device_secret", body)
        self.assertNotIn("signing_key_id", body)
        self.assertIsNone(self._device(body["device_id"]).signing_public_key)

    def test_enrol_with_a_key_stores_it_and_returns_its_id(self):
        _private, raw = _keypair()
        response = self._enrol(signing_public_key=_b64u(raw))
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertEqual(body["signing_key_id"], signing.compute_signing_key_id(raw))
        device = self._device(body["device_id"])
        self.assertEqual(bytes(device.signing_public_key), raw)
        self.assertEqual(device.signing_key_id, body["signing_key_id"])
        self.assertIsNotNone(device.signing_key_set_at.tzinfo)
        history = db.session.scalars(sa.select(AuthDeviceSigningKey).where(
            AuthDeviceSigningKey.device_id == device.device_id)).all()
        self.assertEqual([(h.signing_key_id, h.retired_at) for h in history], [(body["signing_key_id"], None)])
        self.assertEqual(len(self._events("device_signing_key_set", device.device_id)), 1)

    def test_enrol_with_a_bad_key_is_400_and_keeps_the_code(self):
        _row, code = devices.create_enrolment_code(PROJECT_ID, actor=self.base_admin_user)
        db.session.commit()
        body = {"code": code, "device_name": "Station 1", "platform": "desktop"}
        refused = self.client.post(f"{API}/enroll", json={**body, "signing_public_key": "AAAA"})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.get_json(), {
            "error": refused.get_json()["error"], "code": "invalid_request", "fields": ["signing_public_key"],
        })
        self.assertEqual(self.client.post(f"{API}/enroll", json=body).status_code, 201)  # single-use code unspent

    # ── set once on an existing device ─────────────────────────────────────

    def test_set_signing_key_once_from_the_bearer_session(self):
        device = self._enrol().get_json()
        headers = self._bearer_for(device)
        _private, raw = _keypair()
        response = self._set_key(headers, _b64u(raw))
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json(), {"signing_key_id": signing.compute_signing_key_id(raw)})
        self.assertEqual(bytes(self._device(device["device_id"]).signing_public_key), raw)

        again = self._set_key(headers, _b64u(_keypair()[1]))
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.get_json()["code"], "conflict")
        self.assertEqual(bytes(self._device(device["device_id"]).signing_public_key), raw)

        bad = self._set_key(headers, "short")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.get_json()["fields"], ["signing_public_key"])

    def test_set_signing_key_refuses_no_bearer_a_browser_session_and_a_revoked_device(self):
        key = _b64u(_keypair()[1])
        self.assertEqual(self._set_key({}, key).status_code, 401)
        self._login(str(self.interviewer.user_id))
        browser = self._set_key({}, key)
        self.assertEqual(browser.status_code, 403)
        self.assertEqual(browser.get_json()["code"], "device_session_required")
        self.client.delete_cookie("session")

        device = self._enrol().get_json()
        headers = self._bearer_for(device)
        devices.revoke_device(self._device(device["device_id"]), actor=self.base_admin_user)
        db.session.commit()
        self.assertEqual(self._set_key(headers, key).status_code, 401)
        self.assertIsNone(self._device(device["device_id"]).signing_public_key)

    def test_service_refuses_a_revoked_device(self):
        device = self._enrol().get_json()
        devices.revoke_device(self._device(device["device_id"]), actor=self.base_admin_user)
        db.session.commit()
        with self.assertRaises(devices.DeviceAuthError) as caught:
            signing.set_current_device_key(uuid.UUID(device["device_id"]), _b64u(_keypair()[1]))
        db.session.rollback()
        self.assertEqual(caught.exception.code, "device_revoked")

    # ── admin paste of a never-online station ──────────────────────────────

    def test_admin_registers_a_station_from_its_enrolment_file(self):
        _private, raw = _keypair()
        device_id = str(uuid.uuid4())
        self._login(str(self.base_admin_id))
        response = self._paste({"device_id": device_id, "signing_public_key": _b64u(raw), "app_version": "1.2.0"})
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json(), {"device_id": device_id,
                                               "signing_key_id": signing.compute_signing_key_id(raw)})
        device = self._device(device_id)
        self.assertEqual((device.project_id, device.name, device.platform, device.app_version),
                         (PROJECT_ID, "PHC station", "desktop", "1.2.0"))
        self.assertIsNone(device.enrolled_via)
        self.assertEqual(bytes(device.signing_public_key), raw)
        audit = self._events("device_registered_from_file", device_id)
        self.assertEqual(len(audit), 1)
        self.assertEqual(str(audit[0].actor_user_id), str(self.base_admin_id))
        self.assertNotIn(_b64u(raw), json.dumps(audit[0].detail))

        listed = self.client.get(f"/admin/api/projects/{PROJECT_ID}/devices").get_json()["devices"]
        row = next(d for d in listed if d["device_id"] == device_id)
        self.assertEqual(row["signing_key_id"], signing.compute_signing_key_id(raw))
        self.assertFalse(row["revoked_compromised"])

        # No secret was issued, and none can match the stored hash.
        self.client.delete_cookie("session")
        for secret in ("", signing.UNUSABLE_SECRET_HASH, "x"):
            sign_in = self.client.post(f"{API}/sessions", json={
                "device_id": device_id, "device_secret": secret,
                "email": "signing.interviewer@test.local", "password": PASSWORD,
            })
            self.assertEqual(sign_in.get_json()["code"], "device_invalid")

    def test_admin_paste_refusals(self):
        _private, raw = _keypair()
        good = {"device_id": str(uuid.uuid4()), "signing_public_key": _b64u(raw), "app_version": "1.0"}
        self._login(str(self.base_admin_id))
        self.assertEqual(self._paste(good, headers={}).status_code, 400)  # no CSRF token
        self.assertIsNone(self._device(good["device_id"]))
        for bad in ("not an object", {**good, "extra": 1}, {**good, "device_id": "nope"},
                    {**good, "signing_public_key": "AAAA"}, {k: v for k, v in good.items() if k != "device_id"}):
            self.assertEqual(self._paste(bad).status_code, 400, bad)
        self.assertEqual(self._paste(good, name="").status_code, 400)
        self.assertIsNone(self._device(good["device_id"]))

        self.assertEqual(self._paste(good).status_code, 201)
        duplicate = self._paste({**good, "signing_public_key": _b64u(_keypair()[1])})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(bytes(self._device(good["device_id"]).signing_public_key), raw)

        missing = self.client.post("/admin/api/projects/NOPE1/station-registrations",
                                   json={"name": "x", "enrolment_file": {**good, "device_id": str(uuid.uuid4())}},
                                   headers=self._csrf_headers())
        self.assertEqual(missing.status_code, 404)

    def test_project_setup_page_carries_the_station_form(self):
        self._login(str(self.base_admin_id))
        page = self.client.get(f"/admin/panels/project-setup/{PROJECT_ID}")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('id="setup-devices"', html)
        self.assertIn('id="station-register"', html)
        self.assertIn("/station-registrations", html)

    def test_admin_paste_is_admin_only(self):
        good = {"device_id": str(uuid.uuid4()), "signing_public_key": _b64u(_keypair()[1])}
        for user_id in (self.interviewer.user_id, self.base_project_pi_id):
            self._login(str(user_id))
            self.assertEqual(self._paste(good).status_code, 403)
        self.assertIsNone(self._device(good["device_id"]))

    # ── revoke and the ingest lookup ───────────────────────────────────────

    def _revoke(self, device_id, **body):
        self._login(str(self.base_admin_id))
        return self.client.post(f"/admin/api/devices/{device_id}/revoke", json=body, headers=self._csrf_headers())

    def test_revoke_records_the_compromised_flag_and_audits_it(self):
        device = self._enrol().get_json()
        self.assertEqual(self._revoke(device["device_id"], revoked_compromised="yes").status_code, 400)
        plain = self._revoke(device["device_id"])
        self.assertEqual(plain.status_code, 200)
        self.assertFalse(plain.get_json()["revoked_compromised"])
        revoked_at = self._device(device["device_id"]).revoked_at
        self.assertIsNotNone(revoked_at)

        # A later revoke may raise the flag on an already revoked device, never clear it.
        self.assertTrue(self._revoke(device["device_id"], revoked_compromised=True).get_json()["revoked_compromised"])
        self.assertTrue(self._revoke(device["device_id"], revoked_compromised=False).get_json()["revoked_compromised"])
        row = self._device(device["device_id"])
        self.assertTrue(row.revoked_compromised)
        self.assertEqual(row.revoked_at, revoked_at)
        flags = [e.detail["compromised"] for e in self._events("device_revoked", device["device_id"])]
        self.assertEqual(sorted(flags), [False, True, True])

    def test_bundle_signing_key_lookup(self):
        _private, raw = _keypair()
        device = self._enrol(signing_public_key=_b64u(raw)).get_json()
        key_id = device["signing_key_id"]
        now = datetime.now(UTC)
        self.assertEqual(signing.bundle_signing_key(device["device_id"], key_id, now), raw)

        # An earlier (retired) key still verifies bundles signed with it.
        _old_private, old_raw = _keypair()
        old_id = signing.compute_signing_key_id(old_raw)
        db.session.add(AuthDeviceSigningKey(device_id=uuid.UUID(device["device_id"]), signing_public_key=old_raw,
                                            signing_key_id=old_id, set_at=now - timedelta(days=30),
                                            retired_at=now - timedelta(days=1)))
        db.session.commit()
        self.assertEqual(signing.bundle_signing_key(device["device_id"], old_id, now), old_raw)

        def refusal(*args):
            with self.assertRaises(signing.SigningKeyRefusal) as caught:
                signing.bundle_signing_key(*args)
            return caught.exception.code

        self.assertEqual(refusal(str(uuid.uuid4()), key_id, now), "device_unknown")
        self.assertEqual(refusal("not-a-uuid", key_id, now), "device_unknown")
        self.assertEqual(refusal(device["device_id"], "0" * 16, now), "signing_key_unknown")
        with self.assertRaises(ValueError):
            signing.bundle_signing_key(device["device_id"], key_id, now.replace(tzinfo=None))

        # Decommissioned: bundles created before the revoke are accepted.
        self._revoke(device["device_id"])
        revoked_at = self._device(device["device_id"]).revoked_at
        self.assertEqual(signing.bundle_signing_key(device["device_id"], key_id, revoked_at - timedelta(seconds=1)), raw)
        self.assertEqual(refusal(device["device_id"], key_id, revoked_at), "device_revoked")
        # Compromised: every bundle is refused.
        self._revoke(device["device_id"], revoked_compromised=True)
        self.assertEqual(refusal(device["device_id"], key_id, revoked_at - timedelta(days=10)), "device_revoked")

    def test_no_key_material_reaches_the_logs(self):
        _private, raw = _keypair()
        with self.assertLogs(level=logging.DEBUG) as captured:
            logging.getLogger("app").info("signing test marker")
            device = self._enrol(signing_public_key=_b64u(raw)).get_json()
        text = "\n".join(captured.output)
        self.assertIn(device["signing_key_id"], text)
        self.assertNotIn(_b64u(raw), text)
        self.assertNotIn(raw.hex(), text)
