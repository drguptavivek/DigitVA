"""
Tests for ODK Connections API and credential encryption.

Covers:
  - Encryption round-trip (encrypt_credential / decrypt_credential)
  - Wrong pepper raises ValueError
  - Admin CRUD: create, list, update, toggle
  - Credential fields never returned in API responses
  - Non-admin access is denied (403)
  - Project assignment and unassignment
  - Duplicate connection name rejected
  - CSRF enforcement on mutating endpoints
"""

import uuid
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import MasOdkConnections, MapProjectOdk, VaStatuses
from app.services.odk_connection_guard_service import OdkConnectionCooldownError
from app.utils.credential_crypto import decrypt_credential, encrypt_credential
from tests.base import BaseTestCase


PEPPER = "test-pepper-do-not-use-in-production"


# ---------------------------------------------------------------------------
# Encryption unit tests (no HTTP, no DB)
# ---------------------------------------------------------------------------

class CredentialCryptoTests(unittest.TestCase):

    def test_encrypt_decrypt_roundtrip(self):
        ct, salt = encrypt_credential("secret-password", PEPPER)
        self.assertEqual(decrypt_credential(ct, salt, PEPPER), "secret-password")

    def test_encrypt_produces_different_ciphertext_each_time(self):
        ct1, salt1 = encrypt_credential("same", PEPPER)
        ct2, salt2 = encrypt_credential("same", PEPPER)
        self.assertNotEqual(ct1, ct2)
        self.assertNotEqual(salt1, salt2)

    def test_wrong_pepper_raises_value_error(self):
        ct, salt = encrypt_credential("secret", PEPPER)
        with self.assertRaises(ValueError):
            decrypt_credential(ct, salt, "wrong-pepper")

    def test_tampered_ciphertext_raises_value_error(self):
        ct, salt = encrypt_credential("secret", PEPPER)
        tampered = ct[:-4] + "XXXX"
        with self.assertRaises(ValueError):
            decrypt_credential(tampered, salt, PEPPER)

    def test_unicode_plaintext_roundtrip(self):
        plaintext = "pàsswörd-üñícode@example.com"
        ct, salt = encrypt_credential(plaintext, PEPPER)
        self.assertEqual(decrypt_credential(ct, salt, PEPPER), plaintext)


# ---------------------------------------------------------------------------
# ODK Connections API tests
# ---------------------------------------------------------------------------

class OdkConnectionsApiTests(BaseTestCase):

    # ── helpers ──────────────────────────────────────────────────────────────

    def _create_connection(self, name="Test ODK Server"):
        """Create a connection row directly in the DB and return it."""
        username_enc, username_salt = encrypt_credential("admin@odk.test", PEPPER)
        password_enc, password_salt = encrypt_credential("s3cr3t", PEPPER)
        conn = MasOdkConnections(
            connection_name=name,
            base_url="https://odk.test",
            username_enc=username_enc,
            username_salt=username_salt,
            password_enc=password_enc,
            password_salt=password_salt,
            status=VaStatuses.active,
        )
        db.session.add(conn)
        db.session.flush()
        return conn

    def _post_json(self, url, payload, user_id, with_csrf=True):
        self._login(user_id)
        headers = self._csrf_headers() if with_csrf else {}
        headers["Content-Type"] = "application/json"
        import json
        return self.client.post(url, data=json.dumps(payload), headers=headers)

    def _put_json(self, url, payload, user_id):
        self._login(user_id)
        headers = self._csrf_headers()
        headers["Content-Type"] = "application/json"
        import json
        return self.client.put(url, data=json.dumps(payload), headers=headers)

    # ── list ──────────────────────────────────────────────────────────────────

    def test_list_returns_connections_for_admin(self):
        self._create_connection("Server A")
        self._create_connection("Server B")
        self._login(self.base_admin_id)
        resp = self.client.get("/admin/api/odk-connections")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        names = [c["connection_name"] for c in data["connections"]]
        self.assertIn("Server A", names)
        self.assertIn("Server B", names)

    def test_list_denied_for_non_admin(self):
        self._login(self.base_project_pi_id)
        resp = self.client.get("/admin/api/odk-connections")
        self.assertEqual(resp.status_code, 403)

    def test_list_response_never_contains_encrypted_fields(self):
        self._create_connection("Secure Server")
        self._login(self.base_admin_id)
        resp = self.client.get("/admin/api/odk-connections")
        body = resp.get_data(as_text=True)
        self.assertNotIn("username_enc", body)
        self.assertNotIn("password_enc", body)
        self.assertNotIn("username_salt", body)
        self.assertNotIn("password_salt", body)

    def test_list_includes_guard_state(self):
        conn = self._create_connection("Guarded Server")
        conn.consecutive_failure_count = 2
        conn.last_failure_at = datetime.now(timezone.utc)
        conn.last_failure_message = "connect timeout"
        conn.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=5)
        db.session.flush()

        self._login(self.base_admin_id)
        resp = self.client.get("/admin/api/odk-connections")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        target = next(
            c for c in data["connections"]
            if c["connection_name"] == "Guarded Server"
        )
        self.assertTrue(target["guard"]["cooldown_active"])
        self.assertEqual(target["guard"]["consecutive_failure_count"], 2)
        self.assertEqual(target["guard"]["last_failure_message"], "connect timeout")

    # ── create ────────────────────────────────────────────────────────────────

    def test_admin_can_create_connection(self):
        resp = self._post_json(
            "/admin/api/odk-connections",
            {
                "connection_name": "New Server",
                "base_url": "https://new.odk.test",
                "username": "user@new.test",
                "password": "newpass",
                "notes": "test note",
            },
            self.base_admin_id,
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["connection"]
        self.assertEqual(data["connection_name"], "New Server")
        self.assertEqual(data["base_url"], "https://new.odk.test")
        self.assertNotIn("username_enc", data)
        self.assertNotIn("password_enc", data)

    def test_create_verifies_credentials_are_stored_encrypted(self):
        self._post_json(
            "/admin/api/odk-connections",
            {
                "connection_name": "Enc Test",
                "base_url": "https://enc.test",
                "username": "enc@test.com",
                "password": "plaintextpass",
            },
            self.base_admin_id,
        )
        conn = db.session.scalar(
            sa.select(MasOdkConnections).where(
                MasOdkConnections.connection_name == "Enc Test"
            )
        )
        self.assertIsNotNone(conn)
        # Ciphertext must not equal plaintext
        self.assertNotEqual(conn.username_enc, "enc@test.com")
        self.assertNotEqual(conn.password_enc, "plaintextpass")
        # Round-trip must decrypt correctly
        self.assertEqual(
            decrypt_credential(conn.username_enc, conn.username_salt, PEPPER),
            "enc@test.com",
        )
        self.assertEqual(
            decrypt_credential(conn.password_enc, conn.password_salt, PEPPER),
            "plaintextpass",
        )

    def test_duplicate_name_rejected(self):
        self._create_connection("Dup Server")
        resp = self._post_json(
            "/admin/api/odk-connections",
            {
                "connection_name": "Dup Server",
                "base_url": "https://dup.test",
                "username": "u@test.com",
                "password": "pass",
            },
            self.base_admin_id,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already exists", resp.get_json()["error"])

    def test_create_requires_all_fields(self):
        for missing_field, payload in [
            ("connection_name", {"base_url": "https://x.test", "username": "u@x.test", "password": "p"}),
            ("base_url", {"connection_name": "X", "username": "u@x.test", "password": "p"}),
            ("username", {"connection_name": "X", "base_url": "https://x.test", "password": "p"}),
            ("password", {"connection_name": "X", "base_url": "https://x.test", "username": "u@x.test"}),
        ]:
            with self.subTest(missing=missing_field):
                resp = self._post_json("/admin/api/odk-connections", payload, self.base_admin_id)
                self.assertEqual(resp.status_code, 400)

    def test_create_requires_csrf(self):
        resp = self._post_json(
            "/admin/api/odk-connections",
            {"connection_name": "X", "base_url": "https://x.test", "username": "u@x.test", "password": "p"},
            self.base_admin_id,
            with_csrf=False,
        )
        self.assertEqual(resp.status_code, 400)

    def test_non_admin_cannot_create(self):
        resp = self._post_json(
            "/admin/api/odk-connections",
            {"connection_name": "X", "base_url": "https://x.test", "username": "u", "password": "p"},
            self.base_project_pi_id,
        )
        self.assertEqual(resp.status_code, 403)

    # ── update ────────────────────────────────────────────────────────────────

    def test_admin_can_update_name_and_url(self):
        conn = self._create_connection("Original Name")
        resp = self._put_json(
            f"/admin/api/odk-connections/{conn.connection_id}",
            {"connection_name": "Updated Name", "base_url": "https://updated.test"},
            self.base_admin_id,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()["connection"]
        self.assertEqual(data["connection_name"], "Updated Name")
        self.assertEqual(data["base_url"], "https://updated.test")

    def test_update_password_re_encrypts(self):
        conn = self._create_connection("ReKey Server")
        original_enc = conn.password_enc

        self._put_json(
            f"/admin/api/odk-connections/{conn.connection_id}",
            {"password": "newpassword"},
            self.base_admin_id,
        )
        db.session.refresh(conn)
        # Ciphertext must have changed
        self.assertNotEqual(conn.password_enc, original_enc)
        # New ciphertext must decrypt to the new plaintext
        self.assertEqual(
            decrypt_credential(conn.password_enc, conn.password_salt, PEPPER),
            "newpassword",
        )

    def test_update_without_password_keeps_existing_credentials(self):
        conn = self._create_connection("Keep Creds")
        original_password_enc = conn.password_enc
        original_password_salt = conn.password_salt

        self._put_json(
            f"/admin/api/odk-connections/{conn.connection_id}",
            {"notes": "changed note only"},
            self.base_admin_id,
        )
        db.session.refresh(conn)
        self.assertEqual(conn.password_enc, original_password_enc)
        self.assertEqual(conn.password_salt, original_password_salt)

    # ── toggle ────────────────────────────────────────────────────────────────

    def test_toggle_deactivates_then_activates(self):
        conn = self._create_connection("Toggle Server")
        cid = str(conn.connection_id)
        self._login(self.base_admin_id)
        headers = self._csrf_headers()

        resp = self.client.post(
            f"/admin/api/odk-connections/{cid}/toggle", headers=headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "deactive")

        resp = self.client.post(
            f"/admin/api/odk-connections/{cid}/toggle", headers=headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "active")

    # ── project assignment ────────────────────────────────────────────────────

    def test_assign_and_unassign_project(self):
        conn = self._create_connection("Assign Server")
        cid = str(conn.connection_id)
        self._login(self.base_admin_id)
        headers = self._csrf_headers()
        import json

        # Assign
        resp = self.client.post(
            f"/admin/api/odk-connections/{cid}/assign-project",
            data=json.dumps({"project_id": self.BASE_PROJECT_ID}),
            headers={**headers, "Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 201)

        mapping = db.session.scalar(
            sa.select(MapProjectOdk).where(
                MapProjectOdk.project_id == self.BASE_PROJECT_ID
            )
        )
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.connection_id, conn.connection_id)

        # Unassign
        resp = self.client.delete(
            f"/admin/api/odk-connections/{cid}/assign-project/{self.BASE_PROJECT_ID}",
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)

        mapping = db.session.scalar(
            sa.select(MapProjectOdk).where(
                MapProjectOdk.project_id == self.BASE_PROJECT_ID
            )
        )
        self.assertIsNone(mapping)

    def test_reassign_project_to_different_connection(self):
        conn_a = self._create_connection("Server A")
        conn_b = self._create_connection("Server B")
        self._login(self.base_admin_id)
        headers = self._csrf_headers()
        import json

        # Assign to A
        self.client.post(
            f"/admin/api/odk-connections/{conn_a.connection_id}/assign-project",
            data=json.dumps({"project_id": self.BASE_PROJECT_ID}),
            headers={**headers, "Content-Type": "application/json"},
        )

        # Re-assign to B (same project_id, different connection)
        resp = self.client.post(
            f"/admin/api/odk-connections/{conn_b.connection_id}/assign-project",
            data=json.dumps({"project_id": self.BASE_PROJECT_ID}),
            headers={**headers, "Content-Type": "application/json"},
        )
        self.assertIn(resp.status_code, (200, 201))

        mapping = db.session.scalar(
            sa.select(MapProjectOdk).where(
                MapProjectOdk.project_id == self.BASE_PROJECT_ID
            )
        )
        self.assertEqual(mapping.connection_id, conn_b.connection_id)

    def test_list_includes_project_assignments(self):
        conn = self._create_connection("Proj Server")
        db.session.add(
            MapProjectOdk(
                project_id=self.BASE_PROJECT_ID,
                connection_id=conn.connection_id,
            )
        )
        db.session.flush()

        self._login(self.base_admin_id)
        resp = self.client.get("/admin/api/odk-connections")
        data = resp.get_json()
        target = next(
            c for c in data["connections"]
            if c["connection_name"] == "Proj Server"
        )
        self.assertIn(self.BASE_PROJECT_ID, target["project_ids"])

    def test_project_connection_includes_guard_state(self):
        conn = self._create_connection("Project Guard Server")
        conn.consecutive_failure_count = 1
        conn.last_failure_message = "recent timeout"
        db.session.add(
            MapProjectOdk(
                project_id=self.BASE_PROJECT_ID,
                connection_id=conn.connection_id,
            )
        )
        db.session.flush()

        self._login(self.base_admin_id)
        resp = self.client.get(
            f"/admin/api/projects/{self.BASE_PROJECT_ID}/odk-connection"
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()["connection"]
        self.assertEqual(payload["connection_name"], "Project Guard Server")
        self.assertEqual(payload["guard"]["consecutive_failure_count"], 1)
        self.assertEqual(payload["guard"]["last_failure_message"], "recent timeout")

    # ── panel route ──────────────────────────────────────────────────────────

    def test_odk_connections_panel_renders_for_admin(self):
        self._login(self.base_admin_id)
        resp = self.client.get("/admin/panels/odk-connections")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"ODK Connections", resp.data)

    def test_odk_connections_panel_denied_for_non_admin(self):
        self._login(self.base_project_pi_id)
        resp = self.client.get("/admin/panels/odk-connections")
        self.assertEqual(resp.status_code, 403)

    def test_connection_test_returns_cooldown_message_without_hitting_network(self):
        conn = self._create_connection("Cooling Server")
        self._login(self.base_admin_id)
        headers = self._csrf_headers()
        with patch(
            "app.routes.admin.guarded_odk_call",
            side_effect=OdkConnectionCooldownError(
                conn.connection_name,
                datetime.now(timezone.utc) + timedelta(minutes=5),
                "ODK Central timed out",
            ),
        ) as mock_guard:
            resp = self.client.post(
                f"/admin/api/odk-connections/{conn.connection_id}/test",
                headers=headers,
            )

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["ok"])
        self.assertIn("cooldown", resp.get_json()["message"].lower())
        mock_guard.assert_called_once()
