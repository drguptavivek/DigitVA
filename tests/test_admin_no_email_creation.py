"""Admin mobile-only creation confirms the number before writing an account."""
import uuid
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import AuthMobileCode, VaUsers
from app.models.mas_languages import MasLanguages
from tests.base import BaseTestCase
from tests.test_mobile_sign_in import _number


class AdminNoEmailCreationTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        if db.session.get(MasLanguages, "english") is None:
            db.session.add(MasLanguages(
                language_code="english", language_name="English", is_active=True
            ))
            db.session.commit()
        self._login(self.base_admin_id)
        self.name = f"No email {uuid.uuid4().hex}"
        self.phone = _number()

    def _post(self, **changes):
        payload = {
            "name": self.name, "email": "", "email_confirm": "", "no_email": True,
            "phone": self.phone, "phone_confirm": self.phone, "languages": ["english"],
        }
        payload.update(changes)
        return self.client.post(
            "/admin/api/users", json=payload, headers=self._csrf_headers()
        )

    def test_missing_invalid_and_mismatched_numbers_never_create_an_account(self):
        for values in (
            {"phone": ""}, {"phone": "123456789"}, {"phone": "12345678901"},
            {"phone": "９８７６５４３２１０"}, {"phone": "+919876543210"},
            {"phone": 9876543210}, {"phone_confirm": None},
            {"phone_confirm": "123456789"}, {"phone_confirm": "1111111111"},
            {"no_email": "true"}, {"email": "stale@example.com"},
            {"email": " ", "phone_confirm": None}, {"email": ["invalid"]},
        ):
            with self.subTest(values=values):
                response = self._post(**values)
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertIsNone(db.session.scalar(
                    sa.select(VaUsers.user_id).where(VaUsers.name == self.name)
                ))

    def test_no_email_creation_returns_code_once_without_sending_email(self):
        with patch("app.services.email_service._dispatch_email") as dispatch:
            response = self._post()
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        body = response.get_json()
        self.assertRegex(body["sign_in_code"], r"^[0-9]{6}$")
        self.assertNotIn("sign_in_code", body["user"])
        self.assertTrue(body["user"]["mobile_only"])
        user = db.session.get(VaUsers, uuid.UUID(body["user"]["user_id"]))
        self.assertIsNone(user.email)
        self.assertEqual(user.mobile_login, self.phone)
        self.assertIsNotNone(db.session.scalar(
            sa.select(AuthMobileCode).where(AuthMobileCode.user_id == user.user_id).limit(1)
        ))
        dispatch.delay.assert_not_called()
        listed = self.client.get("/admin/api/users?master=1")
        self.assertNotIn(body["sign_in_code"], listed.get_data(as_text=True))
        self.assertEqual(self._post().status_code, 400)

    def test_email_creation_keeps_existing_invitation_flow(self):
        email = f"{uuid.uuid4().hex}@example.com"
        with patch("app.services.user_account_service.send_invitation") as invitation:
            response = self._post(no_email=False, email=email, email_confirm=email,
                                  phone_confirm=None)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertNotIn("sign_in_code", response.get_json())
        invitation.assert_called_once()

    def test_email_creation_refuses_invalid_optional_mobile(self):
        email = f"{uuid.uuid4().hex}@example.com"
        for phone in ("123", "+919876543210", "98765 43210", "９８７６５４３２１０", 9876543210):
            with self.subTest(phone=phone):
                response = self._post(no_email=False, email=email, email_confirm=email,
                                      phone=phone)
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertIsNone(db.session.scalar(
                    sa.select(VaUsers.user_id).where(VaUsers.email == email)
                ))

    def test_number_held_by_email_account_is_refused(self):
        user = self._get_or_make_user(f"{uuid.uuid4().hex}@example.com", "unused")
        user.phone = f"+91{self.phone}"
        db.session.commit()
        response = self._post()
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn("already used", response.get_json()["error"])
