"""Admin API and panel for ICD-11 client tokens (app/routes/admin_icd11_clients.py).
Policy: docs/policy/icd11-client-api.md."""

import json
import uuid

import sqlalchemy as sa
from flask import g

from app import db
from app.models import AuthIcd11ApiClient
from tests.base import BaseTestCase

API = "/admin/api/icd11-api-clients"
PANEL = "/admin/panels/icd11-api-clients"


class AdminIcd11ClientTests(BaseTestCase):
    def _issue(self, **body):
        payload = {"name": "DeathNote", "scopes": ["icd11:search", "icd11:validate"], **body}
        return self.client.post(API, json=payload, headers=self._csrf_headers())

    def test_admin_issues_lists_and_revokes(self):
        self._login(self.base_admin_id)
        issued = self._issue(expires_in_days=30)
        self.assertEqual(issued.status_code, 201, issued.get_data(as_text=True))
        self.assertEqual(issued.headers["Cache-Control"], "no-store")
        body = issued.get_json()
        token, client = body["token"], body["client"]
        self.assertTrue(token.startswith(f"dvicd_{client['key_id']}_"))
        self.assertEqual(client["status"], "active")
        self.assertEqual(client["created_by"], self.base_admin_user.name)
        self.assertEqual(client["scopes"], ["icd11:search", "icd11:validate"])

        listing = self.client.get(API)
        self.assertEqual(listing.status_code, 200)
        listed = [c for c in listing.get_json()["clients"] if c["id"] == client["id"]]
        self.assertEqual(len(listed), 1)
        revoked = self.client.post(f"{API}/{client['id']}/revoke", headers=self._csrf_headers())
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(revoked.get_json()["client"]["status"], "revoked")
        self.assertEqual(revoked.get_json()["client"]["revoked_by"], self.base_admin_user.name)
        again = self.client.post(f"{API}/{client['id']}/revoke", headers=self._csrf_headers())
        self.assertEqual(again.status_code, 200)
        later_list = self.client.get(API)
        panel = self.client.get(PANEL)

        # The token is in the issuance response only.
        self.assertIn(token, issued.get_data(as_text=True))
        secret = token.rsplit("_", 1)[1]
        for later in (listing, revoked, again, later_list, panel):
            self.assertNotIn(secret, later.get_data(as_text=True))
        row = db.session.get(AuthIcd11ApiClient, uuid.UUID(client["id"]))
        self.assertNotIn("token_sha256", json.dumps(listing.get_json()))
        self.assertNotIn(row.token_sha256, later_list.get_data(as_text=True))

    def test_bad_input_names_the_field(self):
        self._login(self.base_admin_id)
        for body, field in (({"name": ""}, "name"), ({"scopes": ["icd11:everything"]}, "scopes"),
                            ({"expires_in_days": 400}, "expires_in_days")):
            with self.subTest(body=body):
                response = self._issue(**body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["field"], field)
        not_object = self.client.post(API, json=["x"], headers=self._csrf_headers())
        self.assertEqual(not_object.get_json()["field"], "name")

    def test_unknown_client_is_404(self):
        self._login(self.base_admin_id)
        response = self.client.post(f"{API}/{uuid.uuid4()}/revoke", headers=self._csrf_headers())
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.get_json())

    def test_a_post_without_csrf_is_refused(self):
        self._login(self.base_admin_id)
        before = db.session.scalar(sa.select(sa.func.count()).select_from(AuthIcd11ApiClient))
        refused = self.client.post(API, json={"name": "No CSRF", "scopes": ["icd11:search"]})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.get_json()["code"], "csrf_failed")
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuthIcd11ApiClient)), before)
        # Positive control: the same request with the token is accepted.
        self.assertEqual(self._issue().status_code, 201)

    def test_panel_renders_for_admin_with_every_scope(self):
        self._login(self.base_admin_id)
        response = self.client.get(PANEL)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for scope in ("icd11:search", "icd11:lookup", "icd11:postcoordination", "icd11:validate"):
            self.assertIn(f'value="{scope}"', html)
        self.assertIn("This token is shown once.", html)
        self.assertNotIn("innerHTML", html)
        index = self.client.get("/admin/")
        self.assertIn("ICD-11 API clients", index.get_data(as_text=True))

    def test_non_admins_and_anonymous_are_refused_everywhere(self):
        self._login(self.base_admin_id)
        client_id = self._issue().get_json()["client"]["id"]
        calls = [("GET", PANEL), ("GET", API), ("POST", API), ("POST", f"{API}/{client_id}/revoke")]
        for user_id in (self.base_coder_id, self.base_project_pi_id, None):
            for method, path in calls:
                with self.subTest(user=user_id, method=method, path=path):
                    self.client = self.app.test_client()
                    g.pop("_login_user", None)  # the suite's g outlives a request
                    if user_id:
                        self._login(user_id)
                    headers = self._csrf_headers() if method == "POST" else {}
                    body = {"name": "Intruder", "scopes": ["icd11:search"]} if method == "POST" else None
                    response = self.client.open(path, method=method, json=body, headers=headers)
                    expected = (403,) if user_id else (401, 302)
                    self.assertIn(response.status_code, expected, response.get_data(as_text=True)[:200])
        row = db.session.get(AuthIcd11ApiClient, uuid.UUID(client_id))
        self.assertIsNone(row.revoked_at)
        self.assertEqual(db.session.scalar(
            sa.select(sa.func.count()).select_from(AuthIcd11ApiClient).where(AuthIcd11ApiClient.name == "Intruder")
        ), 0)
