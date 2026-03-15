import os
import uuid
from flask import url_for
from app import db
from app.models.va_users import VaUsers
from tests.base import BaseTestCase

class MediaAccessTests(BaseTestCase):
    def test_media_access_requires_login(self):
        """Verify that media files cannot be accessed without logging in."""
        with self.app.test_request_context():
            media_url = url_for("va_api.va_servemedia", va_form_id="test_form", va_filename="test.jpg")
        
        response = self.client.get(media_url)
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn("/valogin", response.location)

    def test_path_traversal_protection(self):
        """Verify that path traversal attempts are blocked."""
        # Create and login a user
        email = f"test.media.{uuid.uuid4().hex[:8]}@example.com"
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status="active",
        )
        user.set_password("password")
        db.session.add(user)
        db.session.commit()
        
        with self.app.test_request_context():
            login_url = url_for("va_auth.va_login")
            
        self.client.post(
            login_url,
            data={"email": email, "password": "password"},
            headers=self._csrf_headers()
        )

        # Attempt path traversal
        # We manually construct the path because url_for or the client might normalize '..'
        traversal_paths = [
            "/vaservemedia/../config.py",
            "/vaservemedia/test/../../../config.py",
            "/vaservemedia/test/%2e%2e/%2e%2e/config.py",
        ]
        
        for path in traversal_paths:
            response = self.client.get(path)
            # If it doesn't match the route, it's 404, which is also a form of protection,
            # but if it matches, it should be 400 because of our validation.
            self.assertIn(response.status_code, [400, 404])
