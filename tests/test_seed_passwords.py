"""Seed passwords: documented ones only on a debug or testing app."""
import sqlalchemy as sa

from app import db
from app.commands import seed
from app.models import VaUsers
from tests.base import BaseTestCase


class SeedPasswordTests(BaseTestCase):
    def _admin(self):
        return db.session.scalar(
            sa.select(VaUsers).where(VaUsers.email == "testadmin@digitva.com")
        )

    def _seed_with(self, testing):
        was_debug = self.app.debug
        existing = self._admin()
        if existing:
            db.session.delete(existing)
            db.session.commit()
        self.app.testing, self.app.debug = testing, testing
        try:
            seed._seed_admin()
        finally:
            self.app.testing, self.app.debug = True, was_debug
        return self._admin()

    def test_debug_or_testing_keeps_documented_password(self):
        user = self._seed_with(True)
        self.assertTrue(user.check_password("Admin@123"))

    def test_other_app_gets_random_password(self):
        user = self._seed_with(False)
        self.assertIsNotNone(user)
        self.assertFalse(user.check_password("Admin@123"))
