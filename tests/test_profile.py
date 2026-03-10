import uuid

from app import db
from app.models.va_users import VaUsers
from tests.base import BaseTestCase


class ProfileTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        sfx = uuid.uuid4().hex[:8]
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=f"test.profile.{sfx}@example.com",
            email=f"test.profile.{sfx}@example.com",
            vacode_language=["English"],
            vacode_formcount=0,
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status="active",
        )
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        self.user_id = str(user.user_id)
        self._login(self.user_id)

    def test_timezone_update(self):
        headers = self._csrf_headers()
        resp = self.client.post(
            "/vaprofile",
            data={"va_timezone": "America/New_York", "va_update_timezone": "1"},
            headers=headers,
        )

        self.assertEqual(resp.status_code, 200)

        user = db.session.get(VaUsers, uuid.UUID(self.user_id))
        db.session.refresh(user)
        self.assertEqual(user.timezone, "America/New_York")
